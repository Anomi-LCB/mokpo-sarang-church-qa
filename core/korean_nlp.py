from __future__ import annotations

import re
import threading
from typing import Any

# ---- Kiwi Korean Morphological Analyzer (Lazy Thread-Safe Singleton) ----
_KIWI_LOCK = threading.Lock()
_KIWI_INSTANCE: Any = None
_KIWI_TRIED = False

_CHURCH_USER_WORDS: tuple[str, ...] = (
    "목포사랑의교회", "사랑의교회", "대한예수교장로회", "총회헌법", "헌법해설서",
    "시행세칙", "위임전결", "위임전결규정", "전결권자", "전결권자표", "지출결의서",
    "위임목사", "담임목사", "당회장", "당회서기", "부목사", "전도사", "지도교역자",
    "부교역자", "유급직원", "취업규칙", "원회계", "재정부장",
    "시무장로", "치리장로", "무임장로", "협동장로", "원로장로", "은퇴장로",
    "안수집사", "서리집사", "시무권사", "명예권사", "권찰",
    "셀지기", "셀사역자", "셀리더", "교구지기", "지체지기", "교구편성",
    "원입교인", "학습교인", "세례교인", "학습세례", "유아세례", "입교",
    "공동의회", "제직회", "당회", "노회", "치리회", "기소위원회", "재판국",
    "예배선교부", "교육선교부", "목양사역선교부", "장학선교부", "세계선교부",
    "사회봉사부", "재단관리부", "차량관리부", "주방관리부", "재정부",
    "이명증서", "이명", "이래", "청빙", "피택", "임직", "취임", "권징", "책벌",
    "안식년", "휴직", "복직", "청원서", "소원장", "상소장", "재심", "대결",
)

# Explicit compound-noun decomposition for key church-law terms so searching either part matches
_COMPOUND_SPLITS: dict[str, tuple[str, ...]] = {
    "위임전결": ("위임", "전결"),
    "위임전결규정": ("위임", "전결", "위임전결", "규정"),
    "전결권자": ("전결", "권자", "결재"),
    "전결권자표": ("전결", "전결권자", "결재", "별표"),
    "지출결의서": ("지출", "결의", "결의서", "재정"),
    "위임목사": ("위임", "목사", "담임목사"),
    "담임목사": ("담임", "목사", "위임목사", "당회장"),
    "시무장로": ("시무", "장로"),
    "무임장로": ("무임", "장로"),
    "협동장로": ("협동", "장로"),
    "안수집사": ("안수", "집사"),
    "서리집사": ("서리", "집사"),
    "시무권사": ("시무", "권사"),
    "유급직원": ("유급", "직원"),
    "부교역자": ("교역자",),
    "지도교역자": ("지도", "교역자"),
    "학습세례": ("학습", "세례"),
    "유아세례": ("유아", "세례"),
    "원입교인": ("원입", "교인"),
    "학습교인": ("학습", "교인"),
    "세례교인": ("세례", "교인"),
    "이명증서": ("이명", "증서"),
    "재정부장": ("재정", "재정부", "부장"),
    "차량관리부": ("차량", "관리", "배차"),
    "예배선교부": ("예배", "선교"),
    "교육선교부": ("교육", "선교"),
    "목양사역선교부": ("목양", "사역", "셀"),
    "셀사역자": ("셀", "사역자", "셀지기"),
    "셀지기": ("셀", "지기", "셀사역자"),
    "당회서기": ("당회", "서기"),
}

_KOR_PARTICLES = re.compile(
    r"(으로서|으로써|에서부터|으로부터|에게는|에서는|으로는|이라도|까지도|"
    r"에서|에게|으로|부터|까지|처럼|만큼|보다|라도|마저|조차|이나|든지|"
    r"은|는|이|가|을|를|의|에|로|과|와|도|만|께|며|고|서)$"
)
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_CLAUSE_REF_RE = re.compile(
    r"(?:(총회\s*헌법|헌법\s*해설서|헌법|정관|시행\s*세칙|취업\s*규칙|위임\s*전결\s*규정)\s*)?"
    r"(제\s*\d+\s*조(?:\s*의\s*\d+)?|별표\s*\d*|부칙(?:\s*제\s*\d+\s*조)?|문\s*\d+)"
)

_MEANINGFUL_POS_PREFIXES = ("NN", "VV", "VA", "XR", "SL", "SN")

# Comprehensive church-law synonym & colloquial-to-legal semantic bridge
SYNONYM_GROUPS: list[set[str]] = [
    {"위임목사", "담임목사", "당회장"},
    {"시무장로", "치리장로", "장로"},
    {"무임장로", "무임", "협동장로"},
    {"안수집사", "서리집사", "집사"},
    {"시무권사", "권사"},
    {"권찰", "권잘", "권살", "구역심방"},
    {"셀지기", "셀사역자", "셀리더", "지체지기", "교구지기"},
    {"징계", "권징", "책벌", "치리", "시벌"},
    {"상소", "재심", "소원", "불복", "항소", "억울"},
    {"전결", "위임전결", "대결", "전결권자", "결재"},
    {"휴직", "안식년", "복직", "사임", "복귀", "쉬다", "휴식"},
    {"청빙", "위임", "임직", "피택", "취임", "선출"},
    {"이명", "이래", "이명증서", "전입", "옮기다"},
    {"세례", "학습", "입교", "유아세례", "성례"},
    {"공동의회", "제직회", "당회", "노회"},
    {"유급직원", "부교역자", "취업규칙", "복무", "휴가", "연차"},
    {"재정", "회계", "원회계", "재정부", "지출", "지출결의", "지출결의서", "예산", "결산"},
    {"재산", "부동산", "처분", "매각", "취득", "차입", "담보", "팔다"},
    {"차량", "버스", "승합차", "배차", "운행", "차량관리부"},
    {"교사", "주일학교", "교사훈련", "교사지원서", "교육선교부"},
    {"감사", "회계감사", "감사시행세칙"},
    {"교구", "교구편성", "심방"},
]

# Phrase-level colloquial intent bridges (only trigger on explicit Korean church-admin phrasing)
_COLLOQUIAL_INTENT_RULES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"(잠깐\s*쉬|쉬었다|쉬고|휴식).{0,16}(복귀|돌아오|다시|복직)"), ["휴직", "복직", "청원서", "안식년"]),
    (re.compile(r"(돈|자금|비용|지출).{0,16}(결재|승인|전결|지급|쓰)"), ["위임전결", "전결권자", "재정부", "지출결의", "회계"]),
    (re.compile(r"(자리|부재|출장|유고|비웠|없을).{0,16}(대신|결재|대리|대결)"), ["대결", "위임전결", "전결권자", "유고"]),
    (re.compile(r"(다른\s*교회|타\s*교회|옮겨|옮기|이사).{0,16}(증명서|서류|절차|등록|방법)"), ["이명", "이명증서", "이래"]),
    (re.compile(r"(재산|부동산|건물|토지).{0,16}(팔|매각|처분|매매|사|취득)"), ["재산", "처분", "공동의회", "정관", "당회"]),
    (re.compile(r"(버스|승합차|봉고|교회\s*차|차량).{0,16}(빌려|빌리|사용|신청|예약|운행)"), ["차량", "차량관리부", "배차", "운행", "사용"]),
    (re.compile(r"(억울|불복|다시\s*판단|재판).{0,18}(징계|권징|절차|올리|신청|청구)"), ["상소", "재심", "소원", "권징", "재판국"]),
    (re.compile(r"(징계|권징|책벌).{0,24}(억울|불복|다시\s*판단|이의|올리|재심|상소)"), ["상소", "재심", "소원", "권징", "재판국"]),
    (re.compile(r"(교사|선생님).{0,16}(훈련|교육|지원|자격|임명)"), ["교사", "교사훈련", "교사지원서", "교육선교부"]),
]

STOPWORDS: set[str] = {
    "무엇", "무엇인가", "무엇인가요", "뭐", "뭐야", "뭔가요", "어떻게", "어디", "어디서", "언제", "누가", "누구", "왜",
    "얼마", "얼마인가", "얼마인가요", "시간당", "오늘", "어때", "알리", "알리다",
    "알려줘", "알려주세요", "알려", "설명해줘", "설명", "정리해줘", "정리", "요약해줘", "요약",
    "찾아줘", "찾아주세요", "검색", "보여줘", "보여주세요", "있나요", "있는지", "있어", "인가요",
    "대해", "대해서", "대한", "관련", "관련된", "내용", "규정", "조항", "문서", "자료", "파일",
    "만들어줘", "만들어", "작성해줘", "작성", "채워줘", "다운로드", "추출해줘", "추출", "제공",
    "서식", "양식", "서식지", "표", "좀", "그냥", "혹시", "그리고", "또는", "하는", "되는", "할",
    "수", "것", "등", "및", "내", "중", "시", "때", "후", "전", "위", "아래", "경우", "따라",
    "본", "교회", "목포사랑의교회", "사랑의교회", "총회", "추천", "제안", "개정", "수정", "솔루션",
    "하나요", "해야", "되나요", "방법", "절차", "기준", "비교", "차이", "함께", "알다", "하다", "되다",
    "받다", "있다", "없다", "어느", "어떤", "그럼", "그러면", "그건", "그것", "거기", "여기",
}

_FOLLOWUP_TRIGGER_RE = re.compile(
    r"^(그럼|그러면|그렇다면|그건|그것|그\s*경우|그\s*사람|그\s*서식|그\s*양식|그\s*조항|그거|"
    r"위에서|방금|앞에서|이어서|추가로|혹시\s*그럼|임기는|나이는|자격은|절차는|서식은|양식은|예외는|기한은|정족수는)"
)


def get_kiwi() -> Any:
    """Return thread-safe Kiwi Korean morphological analyzer singleton (or None if unavailable)."""
    global _KIWI_INSTANCE, _KIWI_TRIED
    if _KIWI_TRIED:
        return _KIWI_INSTANCE
    with _KIWI_LOCK:
        if _KIWI_TRIED:
            return _KIWI_INSTANCE
        try:
            from kiwipiepy import Kiwi

            kw = Kiwi()
            for w in _CHURCH_USER_WORDS:
                try:
                    kw.add_user_word(w, "NNP", 10.0)
                except Exception:
                    pass
            _KIWI_INSTANCE = kw
        except Exception:
            _KIWI_INSTANCE = None
        _KIWI_TRIED = True
    return _KIWI_INSTANCE


def is_kiwi_available() -> bool:
    return get_kiwi() is not None


def tokenize_korean_morphemes(text: str) -> list[str]:
    """Extract normalized Korean morphemes, compound parts, and domain terms via Kiwi (with regex fallback)."""
    if not text:
        return []
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        t = tok.strip().lower()
        if not t or t in seen:
            return
        if len(t) == 1 and not t.isdigit():
            return
        seen.add(t)
        tokens.append(t)

    # 1. Clause identifiers (제124조, 별표1, 문10)
    for m in _CLAUSE_REF_RE.finditer(text):
        ref = re.sub(r"\s+", "", m.group(2))
        _add(ref)

    # 2. Kiwi morphological analysis
    kiwi = get_kiwi()
    if kiwi is not None:
        try:
            # Cap extremely long chunks cleanly for speed
            sample = text if len(text) <= 4500 else text[:4500]
            for tok in kiwi.tokenize(sample):
                tag = tok.tag
                form = tok.form.strip()
                if not form:
                    continue
                if tag.startswith(_MEANINGFUL_POS_PREFIXES):
                    if tag in ("VV", "VA") and len(form) >= 1 and not form.endswith("다"):
                        _add(form)
                        _add(form + "다")
                    else:
                        _add(form)
                    if form in _COMPOUND_SPLITS:
                        for sub in _COMPOUND_SPLITS[form]:
                            _add(sub)
        except Exception:
            pass

    # 3. Regex stem + compound split (avoid emitting redundant particle-attached surface duplicates)
    for raw in _WORD_RE.findall(text):
        w = raw.lower()
        has_kor = any("\uac00" <= ch <= "\ud7a3" for ch in w)
        stem = _KOR_PARTICLES.sub("", w) if (len(w) >= 3 and has_kor) else w
        if stem and len(stem) >= 2 and stem != w:
            _add(stem)
            if stem in _COMPOUND_SPLITS:
                for sub in _COMPOUND_SPLITS[stem]:
                    _add(sub)
        else:
            # Skip verbose conjugated verb/adjective surface forms if Kiwi already extracted their root
            if kiwi is not None and has_kor and len(w) >= 4 and re.search(r"(인가요|입니까|하나요|되나요|있나요|없나요|주세요|해줘|하세요|합니다|습니다)$", w):
                continue
            _add(w)
            if w in _COMPOUND_SPLITS:
                for sub in _COMPOUND_SPLITS[w]:
                    _add(sub)

    return tokens


def build_search_tokens_v4(text: str) -> str:
    """Create rich FTS5 index tokens: Kiwi morphemes + compound parts + clause IDs + Korean bigrams."""
    if not text:
        return ""
    morphs = tokenize_korean_morphemes(text)
    out = list(morphs)
    seen_bg: set[str] = set()
    for raw in _WORD_RE.findall(text):
        kor_only = "".join(ch for ch in raw if "\uac00" <= ch <= "\ud7a3")
        if len(kor_only) >= 2:
            for i in range(len(kor_only) - 1):
                bg = "bg_" + kor_only[i : i + 2]
                if bg not in seen_bg:
                    seen_bg.add(bg)
                    out.append(bg)
    return " ".join(out)


def expand_colloquial_and_synonyms(keywords: list[str], raw_query: str) -> tuple[list[str], list[str]]:
    """
    Return (extra_primary_terms, synonym_terms).
    - extra_primary_terms: high-precision terms inferred from church-admin phrase patterns.
    - synonym_terms: domain synonym group expansions.
    """
    extra_primary: list[str] = []
    for pat, terms in _COLLOQUIAL_INTENT_RULES:
        if pat.search(raw_query):
            for t in terms:
                if t not in keywords and t not in extra_primary:
                    extra_primary.append(t)

    synonyms: list[str] = []
    seed = list(dict.fromkeys([*keywords, *extra_primary]))
    for k in seed:
        for grp in SYNONYM_GROUPS:
            if k in grp:
                for alt in grp:
                    if alt != k and alt not in seed and alt not in synonyms:
                        synonyms.append(alt)
    return extra_primary[:8], synonyms[:14]


def resolve_followup_query(query: str, history: list[dict[str, Any]] | None) -> tuple[str, bool]:
    """
    If `query` is a conversational follow-up (e.g., "그럼 임기는 몇 년이야?", "그 서식은 어디에 있어?"),
    enrich it with the core domain entities from the previous user turn for accurate retrieval.
    Returns (effective_query, was_rewritten).
    """
    q = (query or "").strip()
    if not q or not history:
        return q, False

    morphs = [t for t in tokenize_korean_morphemes(q) if t not in STOPWORDS and len(t) >= 2]
    is_short_ellipsis = len(q) <= 18 and len(morphs) <= 2
    is_explicit_followup = bool(_FOLLOWUP_TRIGGER_RE.search(q))
    if not (is_explicit_followup or is_short_ellipsis):
        return q, False

    # Collect previous user messages (skip identical current query if already persisted)
    prev_user_texts: list[str] = []
    for m in reversed(history):
        if m.get("role") == "user":
            txt = str(m.get("content") or "").strip()
            if txt and txt != q:
                prev_user_texts.append(txt)
                if len(prev_user_texts) >= 2:
                    break
    if not prev_user_texts:
        return q, False

    anchor_terms: list[str] = []
    for pt in prev_user_texts:
        for tok in tokenize_korean_morphemes(pt):
            if tok not in STOPWORDS and len(tok) >= 2 and tok not in morphs and tok not in anchor_terms:
                anchor_terms.append(tok)
        if len(anchor_terms) >= 5:
            break

    if not anchor_terms:
        return q, False

    enriched = f"{' '.join(anchor_terms[:5])} {q}"
    return enriched, True


def decompose_compound_query(query: str) -> list[str]:
    """
    Split a multi-subject comparative/compound question into parallel sub-queries so both subjects
    receive dedicated top-K retrieval coverage via RRF.
    Example: "장로 후보자 나이와 유급직원 휴가 규정을 함께 비교 정리해줘"
      -> ["장로 후보자 나이", "유급직원 휴가 규정"]
    """
    q = (query or "").strip()
    if len(q) < 14:
        return [q]

    has_multi_cue = bool(re.search(r"(비교|차이|각각|둘\s*다|함께|및|그리고)", q))
    # Split on Korean conjunctions connecting substantive clauses
    parts = re.split(r"(?:과\s+|와\s+|하고\s+|이랑\s+|랑\s+|,\s*|및\s+|그리고\s+)", q)
    clean_parts: list[str] = []
    for p in parts:
        cleaned = re.sub(r"(을|를|은|는|이|가)?\s*(함께|각각)?\s*(비교|차이|정리|알려줘|알려주세요|설명해줘).*$", "", p).strip()
        if len(cleaned) >= 4:
            sub_kws = [t for t in tokenize_korean_morphemes(cleaned) if t not in STOPWORDS and len(t) >= 2]
            if sub_kws:
                clean_parts.append(cleaned)

    if len(clean_parts) >= 2 and (has_multi_cue or len(clean_parts) == 2 and all(len(p) >= 6 for p in clean_parts)):
        # Deduplicate and cap to 3 sub-queries
        out: list[str] = []
        for p in clean_parts:
            if p not in out:
                out.append(p)
        if len(out) >= 2:
            return out[:3]
    return [q]


def extract_legal_references(text: str, self_article: str = "") -> list[dict[str, str]]:
    """
    Extract outgoing legal cross-references from a clause chunk to build the Legal Clause Graph.
    Returns list of {"ref_type": "article"|"appendix"|"addendum"|"qa", "ref_target": "제124조"|"별표1", "target_doc_hint": "정관"|""}
    """
    if not text:
        return []
    self_norm = re.sub(r"\s+", "", self_article or "")
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for m in _CLAUSE_REF_RE.finditer(text):
        doc_hint = re.sub(r"\s+", "", m.group(1) or "")
        target = re.sub(r"\s+", "", m.group(2) or "")
        if not target:
            continue
        if target == self_norm and not doc_hint:
            continue

        if target.startswith("별표"):
            rtype = "appendix"
        elif target.startswith("부칙"):
            rtype = "addendum"
        elif target.startswith("문"):
            rtype = "qa"
        else:
            rtype = "article"

        # Normalize doc hint
        if "해설" in doc_hint:
            doc_hint = "해설서"
        elif "헌법" in doc_hint:
            doc_hint = "헌법"
        elif "정관" in doc_hint:
            doc_hint = "정관"
        elif "시행세칙" in doc_hint or "취업규칙" in doc_hint or "전결" in doc_hint:
            doc_hint = "시행세칙"

        key = (target, doc_hint)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"ref_type": rtype, "ref_target": target, "target_doc_hint": doc_hint})
        if len(refs) >= 12:
            break

    return refs
