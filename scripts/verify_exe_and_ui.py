from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EXE_PATH = ROOT / "dist" / "목포사랑의교회 행정Q&A" / "목포사랑의교회 행정Q&A.exe"
PORT = 18765
BASE_URL = f"http://127.0.0.1:{PORT}"
SHOT_DIR = Path(
    os.environ.get(
        "AUDIT_SHOT_DIR",
        r"C:\Users\L\.gemini\antigravity\brain\e9a1a797-b0e4-4ce8-9a40-9eb1ac61ff26",
    )
)
SHOT_DIR.mkdir(parents=True, exist_ok=True)

EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def wait_health(timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    last_err = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < deadline:
        try:
            with opener.open(f"{BASE_URL}/api/health", timeout=2) as r:
                if r.status == 200:
                    return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            last_err = exc
        time.sleep(0.4)
    log_file = EXE_PATH.parent / "data" / "server.log"
    if log_file.exists():
        print("=== server.log ===\n" + log_file.read_text(encoding="utf-8", errors="replace"), flush=True)
    raise RuntimeError(f"EXE server failed to start on {BASE_URL}: {last_err}")


def audit_geometry(page, label: str) -> dict:
    res = page.evaluate(
        """() => {
            const docW = document.documentElement.scrollWidth;
            const winW = window.innerWidth;
            const overflow = Math.max(0, docW - winW);

            function visibleRect(el) {
                let r = el.getBoundingClientRect();
                let left = r.left, top = r.top, right = r.right, bottom = r.bottom;
                let cur = el.parentElement;
                while (cur && cur !== document.documentElement) {
                    const st = window.getComputedStyle(cur);
                    if (/(auto|scroll|hidden|clip)/.test(st.overflowY + ' ' + st.overflowX)) {
                        const pr = cur.getBoundingClientRect();
                        left = Math.max(left, pr.left);
                        top = Math.max(top, pr.top);
                        right = Math.min(right, pr.right);
                        bottom = Math.min(bottom, pr.bottom);
                    }
                    cur = cur.parentElement;
                }
                return { left, top, right, bottom, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
            }

            // Scope overlap check to top-most modal if one is open, else full document
            const modalRoot = document.querySelector('div.fixed.inset-0.z-50') || document;
            // Check visible buttons/links/inputs for unintended overlap
            const items = Array.from(modalRoot.querySelectorAll('button, a, select')).map(el => {
                const st = window.getComputedStyle(el);
                if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) return null;
                const r = visibleRect(el);
                if (r.width <= 4 || r.height <= 4 || r.bottom <= 0 || r.top >= window.innerHeight) return null;
                return { el, r };
            }).filter(Boolean);

            const overlaps = [];
            for (let i = 0; i < items.length; i++) {
                const a = items[i].r;
                for (let j = i + 1; j < items.length; j++) {
                    if (items[i].el.contains(items[j].el) || items[j].el.contains(items[i].el)) continue;
                    const b = items[j].r;
                    const ix = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
                    const iy = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
                    if (ix > 2 && iy > 2) {
                        overlaps.push({
                            a: (items[i].el.innerText || items[i].el.getAttribute('aria-label') || '').slice(0, 24),
                            b: (items[j].el.innerText || items[j].el.getAttribute('aria-label') || '').slice(0, 24),
                            ix: Math.round(ix),
                            iy: Math.round(iy),
                        });
                    }
                }
            }
            const svgs = document.querySelectorAll('svg.lucide').length;
            const bodyText = document.body.innerText || '';
            return { docW, winW, overflow, overlaps, svgs, bodyText };
        }"""
    )
    emojis = EMOJI_RE.findall(res["bodyText"])
    print(
        f"[AUDIT {label}] width={res['docW']}/{res['winW']} overflow={res['overflow']}px "
        f"overlaps={len(res['overlaps'])} lucide_svgs={res['svgs']} emojis={len(emojis)}",
        flush=True,
    )
    if res["overlaps"]:
        print(f"  Overlaps: {res['overlaps'][:5]}", flush=True)
    assert res["overflow"] == 0, f"{label}: Horizontal overflow {res['overflow']}px!"
    assert len(res["overlaps"]) == 0, f"{label}: Element overlaps detected: {res['overlaps']}"
    assert len(emojis) == 0, f"{label}: Raw emoji characters detected in UI: {emojis[:5]}"
    assert res["svgs"] >= 3, f"{label}: Expected lucide-react SVG icons, found {res['svgs']}"
    return res


def main() -> None:
    assert EXE_PATH.exists(), f"Missing EXE: {EXE_PATH}"
    env = os.environ.copy()
    env["CHURCH_SEARCH_PORT"] = str(PORT)

    proc = subprocess.Popen(
        [str(EXE_PATH), "--headless"],
        cwd=str(EXE_PATH.parent),
        env=env,
    )
    try:
        health = wait_health()
        print("EXE Health OK:", health, flush=True)

        # Verify APK download & PWA manifest directly from frozen .exe server
        with urllib.request.urlopen(f"{BASE_URL}/downloads/mokpo-sarang-qa.apk", timeout=5) as r:
            apk_bytes = r.read()
            assert r.status == 200 and apk_bytes[:4] == b"PK\x03\x04", "Invalid APK served by EXE"
            print(f"EXE /downloads/mokpo-sarang-qa.apk OK ({len(apk_bytes):,} bytes)", flush=True)

        with urllib.request.urlopen(f"{BASE_URL}/manifest.json", timeout=5) as r:
            mf = json.loads(r.read().decode("utf-8"))
            assert mf["name"] == "목포사랑의교회 행정Q&A"
            print("EXE /manifest.json OK", flush=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)

            # ---- 1. Android Mobile Viewport (412 x 915) ----
            m_ctx = browser.new_context(viewport={"width": 412, "height": 915}, device_scale_factor=2)
            page = m_ctx.new_page()
            page.goto(BASE_URL, wait_until="networkidle")
            audit_geometry(page, "Mobile-412x915-PinGate")
            page.screenshot(path=str(SHOT_DIR / "audit_mobile_pingate.png"))

            # Login as admin (0000)
            page.fill('input[type="password"]', "0000")
            page.click('button[type="submit"]')
            page.wait_for_selector("header", timeout=10000)
            page.wait_for_timeout(600)
            audit_geometry(page, "Mobile-412x915-Chat")
            page.screenshot(path=str(SHOT_DIR / "audit_mobile_chat.png"))

            # Switch to Sources & Chat History tab
            page.click('nav button:has-text("자료·대화")')
            page.wait_for_timeout(400)
            audit_geometry(page, "Mobile-412x915-Sources")
            page.screenshot(path=str(SHOT_DIR / "audit_mobile_sources.png"))

            # Verify direct card click toggles selection (no checkbox needed) and no OCR/form count clutter
            first_doc = page.locator('aside div[role="button"][aria-pressed]').first
            assert first_doc.get_attribute("aria-pressed") == "true"
            first_doc.click()
            page.wait_for_timeout(150)
            assert first_doc.get_attribute("aria-pressed") == "false"
            first_doc.click()
            page.wait_for_timeout(150)
            assert first_doc.get_attribute("aria-pressed") == "true"
            sidebar_txt = page.locator("aside").first.inner_text()
            assert "OCR " not in sidebar_txt, f"Unexpected OCR badge in sidebar: {sidebar_txt}"
            assert "서식·표 " not in sidebar_txt, f"Unexpected form count badge in sidebar: {sidebar_txt}"
            assert "직접 클릭해" not in sidebar_txt, f"Unexpected helper copy in sidebar: {sidebar_txt}"

            # Switch to Forms Vault tab
            page.click('nav button:has-text("서식함")')
            page.wait_for_timeout(400)
            audit_geometry(page, "Mobile-412x915-Forms")
            page.screenshot(path=str(SHOT_DIR / "audit_mobile_forms.png"))

            # Wait for deferred background offline sync (4.2s) before flipping to 100% OFFLINE
            page.wait_for_timeout(4600)
            m_ctx.set_offline(True)
            page.click('nav button:has-text("질문")')
            page.wait_for_timeout(250)
            page.fill("textarea", "장로 후보자 추천 나이")
            page.click('button[aria-label="질문 전송"]')
            page.wait_for_selector("text=오프라인 원문 검색 결과", timeout=8000)
            page.wait_for_timeout(300)
            audit_geometry(page, "Mobile-412x915-OfflinePWA")
            page.screenshot(path=str(SHOT_DIR / "audit_mobile_offline.png"))

            # Verify Mobile Dark Mode toggle cleanly with zero overlaps
            page.click('header button[aria-label="다크 모드 전환"]')
            page.wait_for_timeout(200)
            assert page.evaluate("() => document.documentElement.classList.contains('dark')"), "Mobile dark mode did not activate!"
            audit_geometry(page, "Mobile-412x915-DarkMode")
            page.screenshot(path=str(SHOT_DIR / "audit_mobile_dark.png"))
            m_ctx.set_offline(False)
            m_ctx.close()

            # ---- 1b. Android Embedded Offline WebApp Audit (412 x 915) ----
            offline_html = ROOT / "android" / "build" / "assets" / "offline" / "index.html"
            if offline_html.exists():
                ao_ctx = browser.new_context(viewport={"width": 412, "height": 915}, device_scale_factor=2)
                aopage = ao_ctx.new_page()
                aopage.goto(offline_html.as_uri(), wait_until="load")
                aopage.fill("#sInput", "셀지기 조건")
                aopage.click("#sForm button[type='submit']")
                aopage.wait_for_selector("text=근거 1", timeout=5000)
                aopage.wait_for_timeout(200)
                # Check geometry & UI chrome (excluding raw PDF text inside .card-body which may contain original PDF symbols like ★/☎)
                ov = aopage.evaluate("() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
                ui_chrome_t = aopage.evaluate(
                    """() => {
                        const clone = document.body.cloneNode(true);
                        clone.querySelectorAll('.card-body').forEach(el => el.remove());
                        return clone.innerText || '';
                    }"""
                )
                assert ov == 0, f"Android offline HTML overflow: {ov}px"
                found_e = EMOJI_RE.findall(ui_chrome_t)
                assert len(found_e) == 0, f"Raw emoji in Android offline HTML chrome: {found_e}"
                aopage.screenshot(path=str(SHOT_DIR / "audit_android_offline.png"))
                print(f"[AUDIT Android-Offline-412x915] overflow={ov}px chrome_emojis=0 hits_ok=True", flush=True)
                ao_ctx.close()

            # ---- 2. Desktop Viewport (1440 x 900) ----
            d_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            dpage = d_ctx.new_page()
            dpage.goto(BASE_URL, wait_until="networkidle")
            dpage.fill('input[type="password"]', "0000")
            dpage.click('button[type="submit"]')
            dpage.wait_for_selector("header", timeout=10000)
            dpage.wait_for_timeout(700)

            # Verify hover-revealed icons are hidden at rest on desktop and appear on hover
            hover_btn = dpage.locator('aside .mac-hover-reveal').first
            rest_opacity = hover_btn.evaluate("el => parseFloat(getComputedStyle(el).opacity)")
            assert rest_opacity == 0.0, f"Expected hover icon opacity 0 at rest on desktop, got {rest_opacity}"
            dpage.locator('aside div[role="button"][aria-pressed]').first.hover()
            dpage.wait_for_timeout(250)
            hover_opacity = hover_btn.evaluate("el => parseFloat(getComputedStyle(el).opacity)")
            assert hover_opacity > 0.9, f"Expected hover icon opacity ~1 on hover, got {hover_opacity}"
            dpage.mouse.move(720, 450)
            dpage.wait_for_timeout(200)

            audit_geometry(dpage, "Desktop-1440x900-Main")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_main.png"))

            # Verify v3.0: '자율' renamed to '자동', mode hover popover explains each mode, and FormsVault DOCX/XLSX zero clipping
            header_txt = dpage.locator("header").inner_text()
            assert "자동" in header_txt and "자율" not in header_txt, f"Expected '자동' (not '자율') in header: {header_txt}"
            auto_btn = dpage.locator('header button:has-text("자동")').first
            auto_btn.hover()
            dpage.wait_for_timeout(220)
            tip_opacity = dpage.locator('header [role="tooltip"]').first.evaluate("el => parseFloat(getComputedStyle(el).opacity)")
            assert tip_opacity > 0.9, f"Expected mode hover tooltip opacity > 0.9, got {tip_opacity}"
            dpage.mouse.move(720, 450)
            dpage.wait_for_timeout(150)

            # Verify FormsVault DOCX/XLSX buttons fit inside inspector without right-edge clipping
            clip_res = dpage.evaluate(
                """() => {
                    const insp = document.querySelector('aside[data-panel="inspector"]');
                    if (!insp) return { checked: 0, clipped: [] };
                    const ir = insp.getBoundingClientRect();
                    const clipped = [];
                    let checked = 0;
                    for (const btn of insp.querySelectorAll('button')) {
                        const txt = (btn.innerText || '').trim();
                        if (txt === 'DOCX' || txt === 'XLSX' || txt === 'PDF') {
                            const r = btn.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0 || r.top > window.innerHeight) continue;
                            checked++;
                            if (r.right > ir.right - 2) {
                                clipped.push({ txt, btnRight: Math.round(r.right), inspRight: Math.round(ir.right) });
                            }
                        }
                    }
                    return { checked, clipped };
                }"""
            )
            print(f"[AUDIT FormsVault-Buttons] checked={clip_res['checked']} clipped={len(clip_res['clipped'])}", flush=True)
            assert clip_res["checked"] >= 3 and len(clip_res["clipped"]) == 0, f"FormsVault clipped buttons: {clip_res}"

            # Open v3.0 Document Library (서고) Modal & audit
            dpage.click('aside[data-panel="sidebar"] button:has-text("자료 라이브러리")')
            dpage.wait_for_selector("text=전체 자료 라이브러리", timeout=6000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-LibraryModal")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_library.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(150)

            # Open v3.0 Collaboration Groups & Permissions Modal & audit
            dpage.click('header button[aria-label="그룹 관리"]')
            dpage.wait_for_selector("text=그룹 · 초대 협업 관리", timeout=6000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-GroupsModal")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_groups.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(150)

            # Open v3.0 Ctrl+K Unified Command Palette & audit
            dpage.keyboard.press("Control+k")
            dpage.wait_for_selector('input[placeholder*="빠르게 검색"]', timeout=6000)
            dpage.wait_for_timeout(250)
            audit_geometry(dpage, "Desktop-1440x900-CommandPalette")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_palette.png"))
            dpage.keyboard.press("Escape")
            dpage.wait_for_timeout(150)

            # Verify Left Sidebar collapse/expand via top toolbar PanelLeft
            assert dpage.locator('aside[data-panel="sidebar"]').is_visible()
            dpage.click('header button[aria-label="왼쪽 자료 패널 접기"]')
            dpage.wait_for_timeout(150)
            assert not dpage.locator('aside[data-panel="sidebar"]').is_visible()
            dpage.click('header button[aria-label="왼쪽 자료 패널 열기"]')
            dpage.wait_for_timeout(150)
            assert dpage.locator('aside[data-panel="sidebar"]').is_visible()

            # Verify v3.1: redundant PanelRightClose inside inspector is REMOVED & '내 정보' moved UP into top header!
            assert dpage.locator('aside[data-panel="inspector"] button[aria-label="서식 창 접기"]').count() == 0, "Redundant inspector close button should be removed!"
            assert dpage.locator('header button[aria-label="내 기본 정보"]').is_visible(), "'내 정보' button should be in top header!"

            # Verify Right Inspector collapse/expand cleanly via top toolbar button
            assert dpage.locator('aside[data-panel="inspector"]').is_visible()
            dpage.click('header button[aria-label="오른쪽 서식 창 접기"]')
            dpage.wait_for_timeout(150)
            assert not dpage.locator('aside[data-panel="inspector"]').is_visible()
            dpage.click('header button[aria-label="오른쪽 서식 창 열기"]')
            dpage.wait_for_timeout(150)
            assert dpage.locator('aside[data-panel="inspector"]').is_visible()

            # Verify v3.1 Editorial Dark Mode on Desktop (1440x900)
            dpage.click('header button[aria-label="다크 모드 전환"]')
            dpage.wait_for_timeout(220)
            dark_bg = dpage.evaluate("() => getComputedStyle(document.body).backgroundColor")
            assert dpage.evaluate("() => document.documentElement.classList.contains('dark')")
            print(f"[AUDIT Desktop-DarkMode] body_bg={dark_bg}", flush=True)
            audit_geometry(dpage, "Desktop-1440x900-DarkMode")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_dark.png"))
            # Switch back to Light Mode for remaining audits
            dpage.click('header button[aria-label="다크 모드 전환"]')
            dpage.wait_for_timeout(180)

            # Open Connect / QR modal & verify QR images (External, APK install, and APK 1-scan auto-connect)
            dpage.click('header button[title="모바일 QR 연결 및 APK"]')
            dpage.wait_for_selector('img[alt="외부 접속 QR"]', timeout=8000)
            dpage.wait_for_selector('img[alt="APK 자동 연결 QR"]', timeout=8000)
            dpage.wait_for_timeout(350)
            audit_geometry(dpage, "Desktop-1440x900-ConnectQR")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_qr.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(200)

            # Open Settings -> AI Engine (CLI / API selector) & Updates tab audits
            dpage.click('header button:has-text("설정")')
            dpage.wait_for_selector("text=화면 · AI 엔진", timeout=8000)
            dpage.click('div.fixed.inset-0.z-50 button:has-text("화면 · AI 엔진")')
            dpage.wait_for_selector("text=AI 연결 방식 선택", timeout=6000)
            dpage.wait_for_timeout(250)
            audit_geometry(dpage, "Desktop-1440x900-AiEngineSettings")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_ai_engine.png"))

            dpage.click('div.fixed.inset-0.z-50 button:has-text("업데이트")')
            dpage.wait_for_selector("text=지금 업데이트 확인", timeout=6000)
            dpage.wait_for_timeout(250)
            audit_geometry(dpage, "Desktop-1440x900-UpdatesTab")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_updates.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(200)

            # Open Form Autofill Studio + register personal profile + verify live A4 preview!
            dpage.locator('aside[data-panel="inspector"] button:has-text("작성 · 미리보기")').first.click()
            dpage.wait_for_selector("text=실시간 A4 미리보기", timeout=8000)
            dpage.click('button:has-text("등록")')
            dpage.fill('input[placeholder*="홍길동"]', "이행정")
            dpage.fill('input[placeholder*="목사, 장로"]', "부목사")
            dpage.fill('input[placeholder*="소속 부서"]', "행정실")
            dpage.click('button:has-text("저장 · 즉시 적용")')
            dpage.wait_for_timeout(300)
            modal_txt = dpage.locator('div.fixed.inset-0.z-50').first.inner_text()
            assert "이행정" in modal_txt, "Saved profile name did not reflect in live A4 preview!"
            audit_geometry(dpage, "Desktop-1440x900-FormStudio")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_form_studio.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(200)

            # Open Creator Feedback Report Modal
            dpage.click('header button[aria-label="버그 및 개선사항 제보"]')
            dpage.wait_for_selector("text=제작자 전용 암호로 보호", timeout=8000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-Feedback")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_feedback.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(150)

            # Switch to Administrative Standardization Studio ('표준화실') and verify clean layout + Create modal
            dpage.click('header button:has-text("표준화실")')
            dpage.wait_for_selector("text=행정 표준화 과제", timeout=8000)
            dpage.wait_for_timeout(250)
            audit_geometry(dpage, "Desktop-1440x900-StdWorkspace")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_workspace.png"))

            dpage.click('aside button:has-text("새 모집")')
            dpage.wait_for_selector("text=새 행정 표준화 모집 게시글 개설", timeout=5000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-StdCreateModal")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_modal.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(150)

            # Open Church Taxonomy & Approval Line Customization Modal in Standardization Studio
            dpage.click('aside button[aria-label="표준화실 규격 및 결재선 설정"]')
            dpage.wait_for_selector("text=목포사랑의교회 표준화실 규격", timeout=5000)
            dpage.click('div.fixed.inset-0.z-50 button:has-text("교회 결재선 양식")')
            dpage.wait_for_selector("text=PDF·Word 결재란 미리보기", timeout=5000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-StdConfigApprovals")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_config.png"))
            dpage.click('div.fixed.inset-0.z-50 button:has-text("PDF 표지 · 서식 양식")')
            dpage.wait_for_selector("text=표지 최상단 교단·문서 표기", timeout=5000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-StdConfigCover")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_cover.png"))
            d_ctx.close()

            browser.close()
        print("\nALL EXE + PLAYWRIGHT 412x915 & 1440x900 UI AUDITS PASSED!", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
