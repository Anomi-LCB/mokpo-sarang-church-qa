from __future__ import annotations

import gzip
import json
import socket
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.config import DEFAULT_NOTEBOOK_ID, resolve_stored_path
from core.database import Database
from server.discovery import DISCOVERY_PROBE, DiscoveryResponder
from server.main import create_app
from server.tunnel import NetworkTunnelManager

ROOT = Path(__file__).resolve().parent.parent


def _login_headers(client: TestClient, pin: str = "0000") -> dict[str, str]:
    r = client.post("/api/auth/login", json={"pin": pin, "label": "테스트", "client_id": "test_off_1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_offline_bundle_endpoint_and_gzip() -> None:
    app = create_app()
    with TestClient(app) as client:
        headers = _login_headers(client)
        r = client.get(
            f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/offline-bundle",
            headers={**headers, "Accept-Encoding": "gzip"},
        )
        assert r.status_code == 200
        bundle = r.json()
        assert bundle["version"] == 1
        assert bundle["notebook"]["id"] == DEFAULT_NOTEBOOK_ID
        assert len(bundle["documents"]) >= 4
        assert len(bundle["chunks"]) >= 1200
        assert len(bundle["forms"]) >= 55

        # Verify gzipped payload size is compact (< 750 KB)
        raw = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz = gzip.compress(raw, compresslevel=6)
        assert len(gz) < 750_000, f"Offline bundle gzip unexpectedly large: {len(gz)} bytes"


def test_pc_chat_offline_auto_fallback_when_cli_unavailable() -> None:
    async def _failing_cli(*args, **kwargs):
        raise RuntimeError("No internet / CLI offline simulated")
        yield  # pragma: no cover

    app = create_app()
    with TestClient(app) as client:
        headers = _login_headers(client)
        with patch("server.main.stream_cli_with_failover", side_effect=_failing_cli):
            r = client.post(
                "/api/chat/stream",
                headers=headers,
                json={
                    "notebook_id": DEFAULT_NOTEBOOK_ID,
                    "query": "장로 후보자 추천 나이",
                    "mode": "auto",
                    "instant": False,
                },
            )
        assert r.status_code == 200
        body = r.text
        assert "event: error" not in body
        assert "offline_fallback" in body
        assert "local-offline-fallback" in body
        assert "오프라인 원문 검색 자동 전환" in body
        assert "event: done" in body


def test_udp_lan_discovery_responder() -> None:
    test_udp_port = 48799
    responder = DiscoveryResponder(
        port=8765,
        info_provider=lambda: {
            "lan_url": "http://192.168.0.50:8765",
            "primary_external_url": "https://church.tail.ts.net",
        },
        udp_port=test_udp_port,
    )
    assert responder.start() is True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as cli:
            cli.settimeout(2.0)
            cli.sendto(DISCOVERY_PROBE, ("127.0.0.1", test_udp_port))
            data, _ = cli.recvfrom(2048)
        payload = json.loads(data.decode("utf-8"))
        assert payload["app"] == "church-search"
        assert payload["port"] == 8765
        assert payload["lan_url"] == "http://192.168.0.50:8765"
        assert payload["external_url"] == "https://church.tail.ts.net"
    finally:
        responder.stop()


def test_apk_connect_deeplink_qr() -> None:
    tm = NetworkTunnelManager(port=8765)
    summary = tm.get_network_summary(custom_public_url="https://church.example.ts.net", apk_available=True)
    assert summary["apk_connect_url"].startswith("churchsearch://connect?url=")
    assert "church.example.ts.net" in summary["apk_connect_url"]
    assert summary["apk_connect_qr"].startswith("data:image/png;base64,")
    assert summary["smart_connect_url"].startswith("https://church.example.ts.net/connect?url=")
    assert summary["smart_connect_qr"].startswith("data:image/png;base64,")
    assert summary["has_public_https"] is True
    assert summary["access_scope"] == "public_https"


def test_qr_excludes_private_tailscale_vpn_ip_and_serves_smart_connect_page() -> None:
    tm = NetworkTunnelManager(port=17865)
    fake_ts = {
        "installed": True,
        "logged_in": True,
        "ip": "100.106.197.23",
        "dns_name": "desktop-test.tail.ts.net",
        "funnel_active": False,
        "funnel_url": "",
        "suggested_funnel_url": "https://desktop-test.tail.ts.net",
    }
    with patch.object(tm, "get_tailscale_info", return_value=fake_ts):
        summary = tm.get_network_summary(custom_public_url="", apk_available=True)

    # Critical fix: private 100.64.0.0/10 Tailscale VPN IP must NEVER appear in primary or smart QR!
    assert summary["has_public_https"] is False
    assert summary["access_scope"] == "lan_only"
    assert "100.106.197.23" not in summary["primary_external_url"]
    assert "100.106.197.23" not in summary["apk_url"]
    assert "100.106.197.23" not in summary["smart_connect_url"]
    assert summary["primary_external_url"] == summary["lan_url"]
    assert summary["tailscale_url"] == "http://100.106.197.23:17865"

    # Verify /connect universal mobile landing page renders cleanly without auth!
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/connect?url=http%3A%2F%2F192.168.0.63%3A17865&lan=http%3A%2F%2F192.168.0.63%3A17865")
        assert r.status_code == 200
        assert "모바일 간편 연결" in r.text
        assert "churchsearch://connect?url=" in r.text
        assert "웹으로 바로 시작하기" in r.text

        # Verify preferred LAN IP selector endpoint works & excludes virtual/VPN IPs
        headers = _login_headers(client)
        r_lan = client.put("/api/admin/network/lan-ip", headers=headers, json={"lan_ip": ""})
        assert r_lan.status_code == 200
        lan_opts = r_lan.json()["lan_options"]
        assert all("172.25." not in o["ip"] and not o["ip"].startswith("100.") for o in lan_opts), lan_opts
        assert "100." not in r_lan.json()["primary_external_url"]


def test_portable_stored_path_resolution() -> None:
    db = Database()
    docs = db.list_documents(DEFAULT_NOTEBOOK_ID)
    assert len(docs) >= 4
    sample = docs[0]
    fname = Path(sample["stored_path"]).name

    # Relative path resolution (as stored inside sanitized installer DB)
    rel_resolved = resolve_stored_path(f"notebooks/{DEFAULT_NOTEBOOK_ID}/docs/{fname}", DEFAULT_NOTEBOOK_ID)
    assert Path(rel_resolved).exists()

    # Cross-PC relocated absolute path resolution
    fake_old_pc = rf"D:\SomeOtherPC\교회검색기\data\notebooks\{DEFAULT_NOTEBOOK_ID}\docs\{fname}"
    moved_resolved = resolve_stored_path(fake_old_pc, DEFAULT_NOTEBOOK_ID)
    assert Path(moved_resolved).exists()


def test_android_hybrid_apks_contain_offline_assets() -> None:
    std_apk = ROOT / "dist" / "목포사랑의교회-행정Q&A.apk"
    lite_apk = ROOT / "dist" / "목포사랑의교회-행정Q&A-lite.apk"
    assert std_apk.exists(), "standard APK missing"
    assert lite_apk.exists(), "lite APK missing"

    with zipfile.ZipFile(std_apk, "r") as z:
        names = set(z.namelist())
        assert "classes.dex" in names
        assert "AndroidManifest.xml" in names
        assert "assets/offline/index.html" in names
        assert "assets/offline/corpus.js" in names
        form_pdfs = [n for n in names if n.startswith("assets/offline/forms/") and n.endswith(".pdf")]
        assert len(form_pdfs) >= 55, f"Expected ~60 bundled form PDFs in standard APK, got {len(form_pdfs)}"

    with zipfile.ZipFile(lite_apk, "r") as z:
        names = set(z.namelist())
        assert "assets/offline/index.html" in names
        assert "assets/offline/corpus.js" in names
        form_pdfs = [n for n in names if n.startswith("assets/offline/forms/") and n.endswith(".pdf")]
        assert len(form_pdfs) == 0


def test_feedback_submission_and_creator_only_access_control(tmp_path: Path) -> None:
    db_file = tmp_path / "feedback_test.db"
    app = create_app(db_path=db_file)
    with TestClient(app) as client:
        member_h = _login_headers(client, pin="1234")
        admin_h = _login_headers(client, pin="0000")

        # 1. Any member can submit bug/UX feedback
        sub = client.post(
            "/api/feedback",
            headers=member_h,
            json={
                "category": "ux",
                "title": "서식 미리보기 글씨 크기 개선",
                "description": "모바일에서도 미리보기가 잘 보이면 좋겠습니다.",
                "device_info": "412x915",
                "context_info": "mode=auto",
            },
        )
        assert sub.status_code == 200, sub.text
        fid = sub.json()["id"]

        # 2. Regular member CANNOT view creator inbox (403)
        r_mem = client.get("/api/admin/feedback", headers={**member_h, "X-Creator-Pin": "0000"})
        assert r_mem.status_code == 403

        # 3. Admin with wrong creator PIN CANNOT view creator inbox (403)
        r_bad = client.get("/api/admin/feedback", headers={**admin_h, "X-Creator-Pin": "9999"})
        assert r_bad.status_code == 403

        # 4. Creator unlocks inbox with default creator PIN (= Admin PIN)
        r_ok = client.get("/api/admin/feedback", headers={**admin_h, "X-Creator-Pin": "0000"})
        assert r_ok.status_code == 200
        inbox = r_ok.json()
        assert any(it["id"] == fid for it in inbox["items"])
        relay_tok = inbox["creator_relay_token"]
        assert relay_tok.startswith("cr_")

        # 5. Creator updates status & private memo
        r_upd = client.patch(
            f"/api/admin/feedback/{fid}",
            headers={**admin_h, "X-Creator-Pin": "0000"},
            json={"status": "resolved", "creator_note": "v2.2 반영 완료"},
        )
        assert r_upd.status_code == 200
        assert r_upd.json()["status"] == "resolved"
        assert r_upd.json()["creator_note"] == "v2.2 반영 완료"

        # 6. Creator sets separate Creator Password -> old Admin PIN rejected!
        r_set = client.put(
            "/api/admin/creator-settings",
            headers={**admin_h, "X-Creator-Pin": "0000"},
            json={"new_creator_pin": "creator7788"},
        )
        assert r_set.status_code == 200 and r_set.json()["has_custom_creator_pin"] is True
        assert client.get("/api/admin/feedback", headers={**admin_h, "X-Creator-Pin": "0000"}).status_code == 403
        assert client.get("/api/admin/feedback", headers={**admin_h, "X-Creator-Pin": "creator7788"}).status_code == 200

        # 7. Multi-PC remote feedback relay requires exact X-Creator-Token
        assert (
            client.post(
                "/api/feedback/relay",
                headers={"X-Creator-Token": "wrong_token"},
                json={"category": "bug", "title": "외부 PC 테스트", "description": "내용 테스트입니다."},
            ).status_code
            == 403
        )
        r_rel = client.post(
            "/api/feedback/relay",
            headers={"X-Creator-Token": relay_tok},
            json={"category": "bug", "title": "외부 PC 제보", "description": "다른 사무실 PC에서 자동 전달됨"},
        )
        assert r_rel.status_code == 200
        items_after = client.get(
            "/api/admin/feedback", headers={**admin_h, "X-Creator-Pin": "creator7788"}
        ).json()["items"]
        assert any(it["title"] == "외부 PC 제보" and it["relayed_remote"] == 1 for it in items_after)


def test_form_live_render_docx_with_profile() -> None:
    import io
    import docx as py_docx

    app = create_app()
    with TestClient(app) as client:
        headers = _login_headers(client)
        forms = client.get(f"/api/notebooks/{DEFAULT_NOTEBOOK_ID}/forms", headers=headers).json()
        assert len(forms) >= 1
        target_form = forms[0]

        res = client.post(
            f"/api/forms/{target_form['id']}/render-docx",
            headers=headers,
            json={
                "document_title": target_form["title"],
                "fields": [
                    {"label": "성명", "value": "이행정"},
                    {"label": "직분", "value": "부목사"},
                    {"label": "소속", "value": "행정실"},
                ],
                "body_paragraphs": ["위와 같이 신청하오니 허락하여 주시기 바랍니다."],
                "date_line": "2026년 11월 26일",
                "signer_line": "신청인(제출자): 이행정 (인)",
                "recipient_line": "목포사랑의교회 당회장 귀하",
            },
        )
        assert res.status_code == 200, res.text
        dl_url = res.json()["download_url"]
        dl = client.get(dl_url, headers=headers)
        assert dl.status_code == 200
        doc = py_docx.Document(io.BytesIO(dl.content))
        all_text = "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
            c.text for tbl in doc.tables for row in tbl.rows for c in row.cells
        )
        assert "이행정" in all_text
        assert "부목사" in all_text
        assert "목포사랑의교회 당회장 귀하" in all_text
