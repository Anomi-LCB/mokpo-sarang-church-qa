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
            # v4.4.0: Local PC loopback enters directly without a PIN wall (opens live SSE stream, so wait domcontentloaded)!
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_selector("header", timeout=10000)
            page.wait_for_timeout(450)

            # Click Logout to audit PinGate layout & verify explicit logout locks cleanly
            page.click('header button[aria-label="로그아웃"]')
            page.wait_for_selector('input[type="password"]', timeout=8000)
            page.wait_for_timeout(250)
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
            # v4.4.0: Personal local desktop launches directly into the app with ZERO PIN login wall!
            dpage.goto(BASE_URL, wait_until="domcontentloaded")
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
            tip_opacity = auto_btn.locator('xpath=following-sibling::*[@role="tooltip"]').evaluate("el => parseFloat(getComputedStyle(el).opacity)")
            assert tip_opacity > 0.9, f"Expected mode hover tooltip opacity > 0.9, got {tip_opacity}"

            # Verify universal icon hover tooltip on top header (using 제보 icon since 그룹 moved solely to sidebar beside 대화)!
            rpt_btn = dpage.locator('header button[aria-label="버그 및 개선사항 제보"]').first
            rpt_btn.hover()
            dpage.wait_for_timeout(200)
            rpt_tip_op = rpt_btn.locator('xpath=following-sibling::*[@role="tooltip"]').evaluate("el => parseFloat(getComputedStyle(el).opacity)")
            assert rpt_tip_op > 0.9, f"Expected icon hover tooltip opacity > 0.9, got {rpt_tip_op}"
            dpage.mouse.move(720, 450)
            dpage.wait_for_timeout(150)

            # Verify FormsVault v4.1: clicking a form card reveals frosted 5-button overlay (작성·미리보기, PDF 다운, DOCX, HWPX, XLSX) with zero clipping!
            first_form_card = dpage.locator('aside[data-panel="inspector"] div[data-form-card] div[role="button"]').first
            first_form_card.click()
            dpage.wait_for_selector('aside[data-panel="inspector"] div[data-form-overlay]', timeout=5000)
            dpage.wait_for_timeout(180)
            clip_res = dpage.evaluate(
                """() => {
                    const insp = document.querySelector('aside[data-panel="inspector"]');
                    const ov = insp ? insp.querySelector('div[data-form-overlay]') : null;
                    if (!insp || !ov) return { checked: 0, found: [], clipped: [] };
                    const ir = insp.getBoundingClientRect();
                    const clipped = [];
                    const found = [];
                    for (const btn of ov.querySelectorAll('button')) {
                        const txt = (btn.innerText || '').trim();
                        if (!txt) continue;
                        found.push(txt);
                        const r = btn.getBoundingClientRect();
                        if (r.right > ir.right - 2 || r.left < ir.left + 2) {
                            clipped.push({ txt, btnLeft: Math.round(r.left), btnRight: Math.round(r.right), inspRight: Math.round(ir.right) });
                        }
                    }
                    return { checked: found.length, found, clipped };
                }"""
            )
            print(f"[AUDIT FormsVault-5ActionOverlay] checked={clip_res['checked']} found={clip_res['found']} clipped={len(clip_res['clipped'])}", flush=True)
            assert clip_res["checked"] == 5 and len(clip_res["clipped"]) == 0, f"FormsVault overlay issue: {clip_res}"
            for expected_lbl in ("작성·미리보기", "PDF 다운", "DOCX", "HWPX", "XLSX"):
                assert expected_lbl in clip_res["found"], f"Missing button {expected_lbl} in overlay: {clip_res['found']}"
            audit_geometry(dpage, "Desktop-1440x900-FormsOverlay")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_forms_overlay.png"))
            dpage.keyboard.press("Escape")
            dpage.wait_for_timeout(150)

            # Verify v4.1: Left sources area collapses cleanly to 1 single top line and expands back
            dpage.click('aside[data-panel="sidebar"] button[aria-label="자료 공간 한 줄로 줄이기"]')
            dpage.wait_for_timeout(180)
            collapsed_h = dpage.locator('aside[data-panel="sidebar"] div[data-section="sources"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            print(f"[AUDIT LeftSources-Collapsed] height={collapsed_h}px", flush=True)
            assert collapsed_h <= 42, f"Expected collapsed left sources section <= 42px (1 line), got {collapsed_h}px"
            audit_geometry(dpage, "Desktop-1440x900-SourcesCollapsed")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_sources_collapsed.png"))
            dpage.click('aside[data-panel="sidebar"] button[aria-label="자료 공간 펼치기"]')
            dpage.wait_for_timeout(180)

            # Verify v4.2.5 Top Header: ONLY '행정 Q&A', '표준화실', and 4 mode tabs have text; '그룹' removed from top bar (lives next to '대화' in sidebar)!
            hdr_check = dpage.evaluate(
                """() => {
                    const hdr = document.querySelector('header');
                    const stdBtn = Array.from(hdr.querySelectorAll('button')).find(b => b.innerText.includes('표준화실'));
                    const grpBtn = hdr.querySelector('button[aria-label="그룹 관리"]');
                    const rptBtn = hdr.querySelector('button[aria-label="버그 및 개선사항 제보"]');
                    const newChatBtn = Array.from(hdr.querySelectorAll('button')).find(b => b.innerText.includes('새 대화'));
                    const allowedText = new Set(['행정 Q&A', '표준화실', '자동', '실무', '원문', '제언']);
                    const strayTextButtons = Array.from(hdr.querySelectorAll('button'))
                        .filter(b => {
                            const st = getComputedStyle(b);
                            if (st.display === 'none' || st.visibility === 'hidden') return false;
                            const txt = (b.innerText || '').trim();
                            return txt.length > 0 && !allowedText.has(txt);
                        })
                        .map(b => ({ label: b.getAttribute('aria-label') || '', text: (b.innerText || '').trim() }));
                    return {
                        stdRight: stdBtn ? Math.round(stdBtn.getBoundingClientRect().right) : -1,
                        hasHeaderGroup: Boolean(grpBtn),
                        rptLeft: rptBtn ? Math.round(rptBtn.getBoundingClientRect().left) : -1,
                        hasTopNewChat: Boolean(newChatBtn),
                        strayTextButtons,
                    };
                }"""
            )
            print(f"[AUDIT TopHeader-Layout] {hdr_check}", flush=True)
            assert hdr_check["hasTopNewChat"] is False, "Top bar should not have '새 대화' button!"
            assert hdr_check["hasHeaderGroup"] is False, "Top bar should not have duplicate '그룹' button!"
            assert len(hdr_check["strayTextButtons"]) == 0, f"Top bar icon buttons must have zero visible text: {hdr_check['strayTextButtons']}"
            assert 0 < hdr_check["rptLeft"] < 650 and hdr_check["rptLeft"] >= hdr_check["stdRight"] - 4, f"Report button not right of 표준화실: {hdr_check}"

            # Open v3.0 Document Library (서고) Modal & audit uniform fixed height across categories
            dpage.click('aside[data-panel="sidebar"] button:has-text("자료 라이브러리")')
            dpage.wait_for_selector("text=전체 자료 라이브러리", timeout=6000)
            dpage.wait_for_timeout(200)
            lib_h1 = dpage.locator('div[data-modal="library"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            dpage.locator('div[data-modal="library"] button:has-text("교단 헌법")').first.click()
            dpage.wait_for_timeout(150)
            lib_h2 = dpage.locator('div[data-modal="library"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            assert abs(lib_h1 - lib_h2) <= 2, f"Library modal height changed across filter tabs: {lib_h1} vs {lib_h2}"
            audit_geometry(dpage, "Desktop-1440x900-LibraryModal")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_library.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(150)

            # Open Groups Modal from left sidebar beside '대화' & verify uniform fixed height across ALL 3 tabs!
            dpage.click('aside[data-panel="sidebar"] button:has-text("그룹")')
            dpage.wait_for_selector("text=그룹 · 초대 협업 관리", timeout=6000)
            dpage.wait_for_timeout(200)
            grp_h1 = dpage.locator('div[data-modal="groups"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            dpage.click('div[data-modal="groups"] button:has-text("그룹 개설 권한 관리")')
            dpage.wait_for_timeout(180)
            grp_h2 = dpage.locator('div[data-modal="groups"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            dpage.click('div[data-modal="groups"] button:has-text("기기 간 내 그룹 연결")')
            dpage.wait_for_timeout(180)
            grp_h3 = dpage.locator('div[data-modal="groups"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            print(f"[AUDIT GroupsModal-UniformHeight] h1={grp_h1} h2={grp_h2} h3={grp_h3}", flush=True)
            assert abs(grp_h1 - grp_h2) <= 2 and abs(grp_h1 - grp_h3) <= 2, f"GroupsModal height varied across tabs: {grp_h1}/{grp_h2}/{grp_h3}"
            dpage.click('div[data-modal="groups"] button:has-text("내 그룹 · 초대")')
            dpage.wait_for_timeout(150)
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

            # Open Connect / QR modal & verify accurate QR (zero dead 100.x Tailscale VPN IP in primary QR + live reachability check!)
            dpage.click('header button[aria-label="모바일 QR 연결 및 APK"]')
            dpage.wait_for_selector('img[alt="외부 접속 QR"]', timeout=8000)
            dpage.wait_for_selector('img[alt="APK 자동 연결 QR"]', timeout=8000)
            dpage.wait_for_timeout(300)
            qr_url_txt = dpage.locator('div[data-modal="settings"] code').first.inner_text().strip()
            print(f"[AUDIT ConnectQR-PrimaryURL] {qr_url_txt}", flush=True)
            assert not qr_url_txt.startswith("http://100."), f"Dead Tailscale private VPN IP leaked into primary QR: {qr_url_txt}"
            dpage.click('div[data-modal="settings"] button:has-text("접속 점검")')
            dpage.wait_for_selector("text=응답 정상", timeout=8000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-ConnectQR")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_qr.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(200)

            # Open Settings -> Verify uniform modal height + hireDate & yearly departments + citation display option!
            dpage.click('header button[aria-label="환경 설정"]')
            dpage.wait_for_selector("text=화면 · AI 엔진", timeout=8000)
            dpage.click('div[data-modal="settings"] button:has-text("내 기본 정보")')
            dpage.wait_for_selector("text=서식 자동 작성용 내 기본 정보", timeout=6000)
            dpage.wait_for_selector("text=입사년월일", timeout=5000)
            dpage.wait_for_selector("text=연도별 담당 부서", timeout=5000)
            dpage.fill('div[data-modal="settings"] input[placeholder*="2021-03-01"]', "2022-03-01")
            dpage.click('div[data-modal="settings"] button:has-text("연도 추가")')
            dpage.wait_for_selector('div[data-modal="settings"] input[aria-label="연도별 담당 부서"]', timeout=5000)
            dpage.fill('div[data-modal="settings"] input[aria-label="연도별 담당 부서"]', "청년부")
            dpage.wait_for_timeout(180)
            profile_modal_h = dpage.locator('div[data-modal="settings"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_profile.png"))

            dpage.click('div[data-modal="settings"] button:has-text("화면 · AI 엔진")')
            dpage.wait_for_selector("text=근거 원문 표시 방식", timeout=6000)
            dpage.wait_for_selector("text=하단 열기·닫기", timeout=5000)
            dpage.wait_for_selector("text=팝업창으로 보기", timeout=5000)
            dpage.wait_for_selector("text=토큰 절약 모드 (0원 원문 우선)", timeout=5000)
            dpage.wait_for_selector("text=무료 AI 간편 연결 (0원으로 시작)", timeout=5000)
            dpage.wait_for_selector("text=Google AI Studio 열기", timeout=5000)
            dpage.click('div[data-modal="settings"] button:has-text("오프라인 로컬 AI (평생 0원)")')
            dpage.wait_for_selector("text=Gemma 3 4B (추천)", timeout=5000)
            dpage.wait_for_timeout(150)
            audit_geometry(dpage, "Desktop-1440x900-FreeLocalOllama")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_ollama.png"))
            dpage.click('div[data-modal="settings"] button:has-text("무료 Google Gemini")')
            dpage.wait_for_timeout(120)
            dpage.click('div[data-modal="settings"] button:has-text("팝업창으로 보기")')
            dpage.wait_for_timeout(120)
            assert dpage.evaluate("() => localStorage.getItem('church_search_citation_mode')") == "popup"
            dpage.click('div[data-modal="settings"] button:has-text("하단 열기·닫기")')
            dpage.wait_for_timeout(120)
            assert dpage.evaluate("() => localStorage.getItem('church_search_citation_mode')") == "inline"
            dpage.wait_for_selector("text=창을 닫아도 백그라운드 유지", timeout=6000)
            dpage.wait_for_selector("text=AI 연결 방식 선택", timeout=6000)
            dpage.wait_for_selector("text=스마트 검색 엔진", timeout=6000)
            dpage.wait_for_selector("text=한글 정밀 분석 켜짐", timeout=6000)
            dpage.wait_for_selector("text=고급 의미 검색 추가", timeout=6000)
            dpage.wait_for_timeout(250)
            cli_modal_metrics = dpage.evaluate(
                """() => {
                    const m = document.querySelector('div[data-modal="settings"]');
                    const tabs = document.querySelector('div[data-role="settings-tabs"]');
                    const mr = m.getBoundingClientRect();
                    const tr = tabs.getBoundingClientRect();
                    return {
                        modalH: Math.round(mr.height),
                        tabsH: Math.round(tr.height),
                        tabsNotClipped: tr.height >= 36 && tr.top >= mr.top,
                    };
                }"""
            )
            print(f"[AUDIT Settings-UniformHeight] profileH={profile_modal_h} cliMetrics={cli_modal_metrics}", flush=True)
            assert abs(profile_modal_h - cli_modal_metrics["modalH"]) <= 2, f"Settings modal height changed between tabs: {profile_modal_h} vs {cli_modal_metrics['modalH']}"
            assert cli_modal_metrics["tabsNotClipped"] is True, f"Settings tab bar clipped: {cli_modal_metrics}"

            eng_status = dpage.evaluate(
                """async () => {
                    const r = await fetch('/api/engine/status', { credentials: 'include' });
                    return await r.json();
                }"""
            )
            print(f"[AUDIT Engine-v4.4-EXE] {eng_status}", flush=True)
            assert eng_status.get("version") == "4.4.0", f"Expected v4.4.0, got {eng_status}"
            assert eng_status.get("kiwi_active") is True, f"Kiwi failed to load inside frozen EXE: {eng_status}"
            assert eng_status.get("stats", {}).get("cross_refs", 0) > 500, f"Expected >500 cross_refs: {eng_status}"
            audit_geometry(dpage, "Desktop-1440x900-AiEngineSettings")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_ai_engine.png"))

            dpage.click('div[data-modal="settings"] button:has-text("보안 · PIN")')
            dpage.wait_for_selector("text=로컬 PC 실행 시 PIN 없이 바로 열기", timeout=6000)
            dpage.wait_for_selector("text=최근 사용 기록", timeout=6000)
            dpage.wait_for_timeout(200)
            sec_txt = dpage.locator('div[data-modal="settings"]').inner_text()
            assert "doc_library_updated" not in sec_txt, "Raw English event code should be translated to Korean!"

            dpage.click('div[data-modal="settings"] button:has-text("업데이트")')
            dpage.wait_for_selector("text=지금 업데이트 확인", timeout=6000)
            dpage.wait_for_timeout(250)
            audit_geometry(dpage, "Desktop-1440x900-UpdatesTab")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_updates.png"))
            dpage.click('div.fixed.inset-0.z-50 button[aria-label="닫기"]')
            dpage.wait_for_timeout(200)

            # Open Form Autofill Studio via the new click-to-reveal frosted 5-action overlay!
            dpage.locator('aside[data-panel="inspector"] div[data-form-card] div[role="button"]').first.click()
            dpage.wait_for_selector('aside[data-panel="inspector"] div[data-form-overlay]', timeout=5000)
            dpage.locator('aside[data-panel="inspector"] div[data-form-overlay] button:has-text("작성·미리보기")').click()
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

            # Switch to Administrative Standardization Studio ('표준화실') and verify v4.2.0 upgrades!
            dpage.click('header button:has-text("표준화실")')
            dpage.wait_for_selector("text=행정 표준화 과제", timeout=8000)
            dpage.wait_for_timeout(250)
            audit_geometry(dpage, "Desktop-1440x900-StdWorkspace")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_workspace.png"))

            dpage.click('aside button:has-text("새 모집")')
            dpage.wait_for_selector("text=새 행정 표준화 모집 게시글 개설", timeout=5000)
            dpage.wait_for_selector("text=목표 투표 정족수 인원", timeout=5000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-StdCreateModal")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_modal.png"))

            # Create a temporary test board to audit v4.2.0 Submissions (Image/PPTX multi-upload), Voting & Publish Studio!
            dpage.fill('input[placeholder*="재정·지출결의서"]', "UI 감사 임시 표준화 과제")
            dpage.click('button:has-text("모집 게시글 개설")')
            dpage.wait_for_selector("text=수집 자료", timeout=8000)
            dpage.wait_for_timeout(250)
            accept_attr = dpage.locator('input[type="file"]').first.get_attribute("accept") or ""
            assert ".pptx" in accept_attr and ".png" in accept_attr and ".jpg" in accept_attr, (
                f"Expected image+pptx in accept attr, got: {accept_attr}"
            )
            audit_geometry(dpage, "Desktop-1440x900-StdBoardActive")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_board.png"))

            # Check Publish Tab (v4.2 2-stage draft editor + HWPX 3-format compile + image appendix option)
            dpage.click('button:has-text("전문가 PDF 편찬")')
            dpage.wait_for_selector("text=초안 먼저 검토 · 직접 편집", timeout=5000)
            dpage.wait_for_selector("text=원클릭 PDF · Word · HWPX 편찬", timeout=5000)
            dpage.wait_for_timeout(200)
            audit_geometry(dpage, "Desktop-1440x900-StdPublish")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_publish.png"))

            # Clean up temporary test board so dist/ data stays pristine
            dpage.once("dialog", lambda dialog: dialog.accept())
            dpage.click('button[title="게시글 삭제"]')
            dpage.wait_for_timeout(350)

            # Open Church Taxonomy & Approval Line Customization Modal & verify uniform fixed height across all 3 tabs!
            dpage.click('aside button[aria-label="표준화실 규격 및 결재선 설정"]')
            dpage.wait_for_selector("text=목포사랑의교회 표준화실 규격", timeout=5000)
            std_cfg_h1 = dpage.locator('div[data-modal="std-config"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            dpage.click('div.fixed.inset-0.z-50 button:has-text("교회 결재선 양식")')
            dpage.wait_for_selector("text=PDF·Word 결재란 미리보기", timeout=5000)
            dpage.wait_for_timeout(200)
            std_cfg_h2 = dpage.locator('div[data-modal="std-config"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            audit_geometry(dpage, "Desktop-1440x900-StdConfigApprovals")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_config.png"))
            dpage.click('div.fixed.inset-0.z-50 button:has-text("PDF 표지 · 서식 양식")')
            dpage.wait_for_selector("text=표지 최상단 교단·문서 표기", timeout=5000)
            dpage.wait_for_timeout(200)
            std_cfg_h3 = dpage.locator('div[data-modal="std-config"]').evaluate("el => Math.round(el.getBoundingClientRect().height)")
            print(f"[AUDIT StdConfigModal-UniformHeight] h1={std_cfg_h1} h2={std_cfg_h2} h3={std_cfg_h3}", flush=True)
            assert abs(std_cfg_h1 - std_cfg_h2) <= 2 and abs(std_cfg_h1 - std_cfg_h3) <= 2, f"StdConfigModal height varied across tabs: {std_cfg_h1}/{std_cfg_h2}/{std_cfg_h3}"
            audit_geometry(dpage, "Desktop-1440x900-StdConfigCover")
            dpage.screenshot(path=str(SHOT_DIR / "audit_desktop_std_cover.png"))
            d_ctx.close()

            # ---- 3. Mobile Standardization Studio Audit (412 x 915) ----
            mstd_ctx = browser.new_context(viewport={"width": 412, "height": 915}, device_scale_factor=2)
            mspage = mstd_ctx.new_page()
            mspage.goto(BASE_URL, wait_until="domcontentloaded")
            mspage.wait_for_selector("header", timeout=10000)
            mspage.wait_for_timeout(300)
            mspage.click('header button:has-text("표준화실")')
            mspage.wait_for_selector('button[aria-label="전체 교차 분류 기억함"]', timeout=8000)
            mspage.wait_for_selector('button[aria-label="표준화실 설정"]', timeout=5000)
            mspage.wait_for_timeout(250)
            audit_geometry(mspage, "Mobile-412x915-StdWorkspace")
            mspage.screenshot(path=str(SHOT_DIR / "audit_mobile_std.png"))
            mstd_ctx.close()

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
