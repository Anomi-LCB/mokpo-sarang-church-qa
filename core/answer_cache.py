from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Any

import numpy as np


def _normalize_query(q: str) -> str:
    s = re.sub(r"\s+", " ", (q or "").strip().lower())
    s = re.sub(r"[?!.,~]+$", "", s).strip()
    return s


class TwoLayerAnswerCache:
    """
    Ultra-fast Two-Layer Grounded Answer Cache:
    - Layer 1: Exact normalized query cache (<1ms hit, 0 LLM latency)
    - Layer 2: Semantic cosine-similarity cache (>=0.955 when local ONNX embedder is active)
    - Automatically scoped by (notebook_id, corpus_fingerprint, selected_doc_ids, mode, double_verify)
      so any document add/update/delete invalidates stale answers immediately.
    """

    def __init__(self, max_entries: int = 240, ttl_sec: int = 86400) -> None:
        self._lock = threading.Lock()
        self._max = max_entries
        self._ttl = ttl_sec
        self._exact: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # scope_key -> list of (unit_vec_fp32, exact_key)
        self._semantic: dict[str, list[tuple[np.ndarray, str]]] = {}
        self.hits = 0
        self.misses = 0

    def _scope_key(
        self,
        notebook_id: str,
        corpus_fp: str,
        doc_ids: list[str] | None,
        mode: str,
        double_verify: bool,
    ) -> str:
        docs_part = ",".join(sorted(doc_ids)) if doc_ids else "ALL"
        raw = f"{notebook_id}|{corpus_fp}|{docs_part}|{mode}|{int(bool(double_verify))}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _exact_key(self, scope: str, norm_q: str) -> str:
        return hashlib.sha1(f"{scope}::{norm_q}".encode("utf-8")).hexdigest()[:24]

    def get(
        self,
        notebook_id: str,
        corpus_fp: str,
        doc_ids: list[str] | None,
        mode: str,
        double_verify: bool,
        query: str,
        query_vec: np.ndarray | None = None,
    ) -> dict[str, Any] | None:
        norm_q = _normalize_query(query)
        if not norm_q:
            return None
        scope = self._scope_key(notebook_id, corpus_fp, doc_ids, mode, double_verify)
        ekey = self._exact_key(scope, norm_q)
        now = time.time()

        with self._lock:
            entry = self._exact.get(ekey)
            if entry and (now - entry["ts"]) <= self._ttl:
                self._exact.move_to_end(ekey)
                self.hits += 1
                return dict(entry)

            # Layer 2: Semantic near-duplicate lookup
            if query_vec is not None and query_vec.size > 0 and scope in self._semantic:
                best_sim = 0.0
                best_key = ""
                for vec, cand_key in self._semantic[scope]:
                    if vec.shape == query_vec.shape:
                        sim = float(np.dot(vec, query_vec))
                        if sim > best_sim:
                            best_sim = sim
                            best_key = cand_key
                if best_sim >= 0.955 and best_key in self._exact:
                    sem_entry = self._exact[best_key]
                    if (now - sem_entry["ts"]) <= self._ttl:
                        self._exact.move_to_end(best_key)
                        self.hits += 1
                        out = dict(sem_entry)
                        out["semantic_hit"] = round(best_sim, 4)
                        return out

            self.misses += 1
            return None

    def put(
        self,
        notebook_id: str,
        corpus_fp: str,
        doc_ids: list[str] | None,
        mode: str,
        double_verify: bool,
        query: str,
        payload: dict[str, Any],
        query_vec: np.ndarray | None = None,
    ) -> None:
        norm_q = _normalize_query(query)
        if not norm_q:
            return
        scope = self._scope_key(notebook_id, corpus_fp, doc_ids, mode, double_verify)
        ekey = self._exact_key(scope, norm_q)

        with self._lock:
            rec = {**payload, "ts": time.time(), "scope": scope}
            self._exact[ekey] = rec
            self._exact.move_to_end(ekey)
            if query_vec is not None and query_vec.size > 0:
                lst = self._semantic.setdefault(scope, [])
                lst.append((query_vec.astype(np.float32), ekey))
                if len(lst) > 64:
                    del lst[: len(lst) - 64]
            while len(self._exact) > self._max:
                old_k, old_v = self._exact.popitem(last=False)
                old_scope = old_v.get("scope", "")
                if old_scope in self._semantic:
                    self._semantic[old_scope] = [
                        item for item in self._semantic[old_scope] if item[1] != old_k
                    ]

    def clear(self) -> None:
        with self._lock:
            self._exact.clear()
            self._semantic.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._exact),
                "hits": self.hits,
                "misses": self.misses,
            }
