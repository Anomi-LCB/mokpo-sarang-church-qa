from __future__ import annotations

import json
import os
import socket
import threading
from typing import Callable

from core.config import APP_NAME

DISCOVERY_PORT = 48765
DISCOVERY_PROBE = b"CHURCH_SEARCH_DISCOVER"


class DiscoveryResponder:
    """Lightweight UDP LAN responder so Android APKs on the same Wi-Fi auto-discover this PC in 1 tap."""

    def __init__(
        self,
        port: int,
        info_provider: Callable[[], dict[str, str]],
        udp_port: int = DISCOVERY_PORT,
    ) -> None:
        self.http_port = port
        self.info_provider = info_provider
        self.udp_port = udp_port
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if os.environ.get("CHURCH_SEARCH_DISABLE_DISCOVERY") == "1":
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            sock.bind(("", self.udp_port))
            self._sock = sock
        except OSError:
            return False

        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="church-udp-discovery", daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data or not data.startswith(DISCOVERY_PROBE):
                continue
            try:
                net = self.info_provider()
                payload = {
                    "app": "church-search",
                    "name": APP_NAME,
                    "port": self.http_port,
                    "lan_url": net.get("lan_url", ""),
                    "external_url": net.get("primary_external_url", "") or net.get("lan_url", ""),
                }
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._sock.sendto(raw, addr)
            except OSError:
                continue

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
