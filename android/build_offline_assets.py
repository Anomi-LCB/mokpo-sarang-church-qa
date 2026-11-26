from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import DEFAULT_NOTEBOOK_ID
from core.database import Database
from core.forms import export_original_pdf

OFFLINE_HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
<title>교회 법규·행정 오프라인 검색기</title>
<style>
  :root {
    --bg: #f7f7f5;
    --card: #ffffff;
    --ink: #18181b;
    --muted: #52525b;
    --subtle: #8a8a8e;
    --blue: #0f4c81;
    --blue-dark: #0c3d68;
    --line: rgba(24,24,27,0.08);
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%;
    font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
    background: var(--bg); color: var(--ink);
    word-break: keep-all; overflow-wrap: break-word; overflow-x: hidden;
    overscroll-behavior: none; -webkit-tap-highlight-color: transparent;
  }
  .app { display: flex; flex-direction: column; height: 100dvh; }
  .topbar {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: calc(env(safe-area-inset-top, 0px) + 10px) 14px 10px;
    background: rgba(255,255,255,0.94); border-bottom: 1px solid var(--line);
    flex-shrink: 0;
  }
  .brand { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .brand-badge {
    width: 28px; height: 28px; border-radius: 8px; background: var(--blue); color: #fff;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  }
  .brand-title { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pill {
    display: inline-flex; align-items: center; gap: 5px; white-space: nowrap;
    padding: 5px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
    border: 1px solid var(--line); background: var(--bg); color: var(--ink);
    cursor: pointer;
  }
  .pill-primary { background: rgba(0,122,255,0.1); border-color: rgba(0,122,255,0.25); color: var(--blue); }
  .offline-strip {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 6px 14px; background: #fffbeb; border-bottom: 1px solid #fde68a;
    font-size: 11px; color: #92400e; flex-shrink: 0;
  }
  .main { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px 20px; }
  .search-wrap { position: sticky; top: 0; z-index: 5; background: var(--bg); padding-bottom: 10px; }
  .search-box {
    display: flex; align-items: center; gap: 8px;
    background: #fff; border: 1px solid rgba(0,0,0,0.12); border-radius: 14px;
    padding: 6px 8px 6px 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  }
  .search-box input {
    flex: 1; min-width: 0; border: 0; outline: 0; background: transparent;
    font-size: 16px; color: var(--ink); padding: 4px 0;
  }
  .btn-go {
    width: 34px; height: 34px; border-radius: 10px; border: 0;
    background: var(--blue); color: #fff; display: flex; align-items: center; justify-content: center;
    cursor: pointer; flex-shrink: 0;
  }
  .chips { display: flex; gap: 6px; overflow-x: auto; padding-top: 8px; padding-bottom: 2px; }
  .chip {
    white-space: nowrap; border: 1px solid var(--line); background: #fff; color: var(--muted);
    padding: 5px 10px; border-radius: 999px; font-size: 11.5px; font-weight: 600; cursor: pointer;
  }
  .chip.active { background: var(--ink); color: #fff; border-color: var(--ink); }
  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: 14px;
    padding: 13px; margin-bottom: 10px;
  }
  .card-title { font-size: 13.5px; font-weight: 700; margin: 0; color: var(--ink); }
  .card-meta { font-size: 11px; color: var(--subtle); margin-top: 3px; }
  .card-body {
    margin-top: 8px; font-size: 13px; line-height: 1.62; color: #3a3a3c;
    white-space: pre-wrap;
  }
  .card-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .btn {
    display: inline-flex; align-items: center; gap: 5px; white-space: nowrap;
    border-radius: 9px; padding: 7px 11px; font-size: 12px; font-weight: 600;
    border: 1px solid var(--line); background: var(--bg); color: var(--ink); cursor: pointer;
  }
  .btn-blue { background: var(--blue); color: #fff; border-color: var(--blue); }
  .quick-grid { display: grid; grid-template-columns: 1fr; gap: 8px; margin-top: 8px; }
  .quick-btn {
    text-align: left; background: #fff; border: 1px solid var(--line); border-radius: 13px;
    padding: 11px 13px; cursor: pointer;
  }
  .quick-btn strong { display: block; font-size: 12.5px; color: var(--ink); }
  .quick-btn span { display: block; font-size: 11.5px; color: var(--muted); margin-top: 2px; }
  .empty { text-align: center; padding: 28px 16px; color: var(--subtle); font-size: 13px; }
  .nav {
    display: grid; grid-template-columns: repeat(3, 1fr);
    background: rgba(255,255,255,0.96); border-top: 1px solid var(--line);
    padding-bottom: env(safe-area-inset-bottom, 0px); flex-shrink: 0;
  }
  .nav-btn {
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
    padding: 8px 4px; border: 0; background: transparent; color: var(--subtle);
    font-size: 11px; font-weight: 600; cursor: pointer; white-space: nowrap;
  }
  .nav-btn.active { color: var(--blue); }
  .modal-bg {
    position: fixed; inset: 0; z-index: 50; background: rgba(0,0,0,0.48);
    display: flex; align-items: center; justify-content: center; padding: 14px;
  }
  .modal {
    width: 100%; max-width: 560px; max-height: 86dvh; display: flex; flex-direction: column;
    background: #fff; border-radius: 16px; overflow: hidden;
  }
  .modal-head {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 12px 14px; border-bottom: 1px solid var(--line); background: #fbfbfd;
  }
  .modal-body { flex: 1; overflow-y: auto; padding: 14px; font-size: 13.5px; line-height: 1.65; white-space: pre-wrap; }
  .modal-foot {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; border-top: 1px solid var(--line); background: #fff;
  }
  .badge-hit {
    display: inline-block; background: rgba(0,122,255,0.1); color: var(--blue);
    border-radius: 6px; padding: 2px 7px; font-size: 11px; font-weight: 700; margin-bottom: 6px;
  }
  mark { background: #fef08a; color: #1d1d1f; border-radius: 3px; padding: 0 2px; }
  svg { width: 16px; height: 16px; flex-shrink: 0; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
</style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <div class="brand">
      <div class="brand-badge" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
      </div>
      <div class="brand-title" id="nbTitle">목포사랑의교회 행정Q&amp;A</div>
    </div>
    <button class="pill pill-primary" id="btnOnline" type="button">
      <svg viewBox="0 0 24 24"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
      <span>서버 연결</span>
    </button>
  </header>

  <div class="offline-strip">
    <span id="offlineInfo">오프라인 내장 모드 · 인터넷 없이 동작</span>
    <span id="profileTag" style="font-weight:700;white-space:nowrap;"></span>
  </div>

  <main class="main" id="mainArea"></main>

  <nav class="nav">
    <button class="nav-btn active" data-tab="search" type="button">
      <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <span>원문 검색</span>
    </button>
    <button class="nav-btn" data-tab="docs" type="button">
      <svg viewBox="0 0 24 24"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>
      <span>자료 열람</span>
    </button>
    <button class="nav-btn" data-tab="forms" type="button">
      <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      <span>서식함</span>
    </button>
  </nav>
</div>

<div id="modalRoot"></div>

<script src="corpus.js"></script>
<script>
(function() {
  const DATA = window.__OFFLINE_CORPUS__ || { notebook: { name: '교회검색기' }, documents: [], chunks: [], forms: [], profile: 'lite' };
  const docMap = new Map(DATA.documents.map(d => [d.id, d]));

  const SYNONYMS = {
    '위임목사': ['위임목사', '담임목사', '당회장'],
    '담임목사': ['위임목사', '당회장'],
    '징계': ['권징', '치리', '책벌', '시벌'],
    '권징': ['징계', '치리', '재판', '책벌'],
    '장로': ['치리장로', '시무장로', '무임장로', '협동장로'],
    '임직': ['안수', '장립', '취임', '임명'],
    '휴가': ['휴직', '청원휴가', '연차', '안식월'],
    '휴직': ['복직', '청원서', '휴가'],
    '재정': ['회계', '예산', '결산', '헌금'],
    '셀지기': ['셀사역자', '지체지기', '교구지기'],
    '유급직원': ['직원', '사무원', '복무'],
    '세례': ['학습', '입교', '유아세례'],
  };
  const STOP = new Set(['알려줘','정리해줘','찾아줘','무엇','어떻게','어떤','있는','있나요','인가요','해주세요','해줘','대한','관련','규정','기준','절차','내용','대해']);
  const PARTICLE = /(으로서|으로써|에서부터|으로부터|에게는|에서는|으로는|이라도|까지도|에서|에게|으로|부터|까지|처럼|만큼|보다|라도|마저|조차|이나|든지|은|는|이|가|을|를|의|에|로|과|와|도|만|께|며|고|서)$/;

  let activeTab = 'search';
  let searchQuery = '';
  let selectedDocId = 'ALL';
  let formQuery = '';
  let formCategory = '전체';
  let lastResults = null;

  document.getElementById('nbTitle').textContent = '목포사랑의교회 행정Q&A';
  const totalPages = DATA.documents.reduce((s, d) => s + (d.page_count || 0), 0);
  document.getElementById('offlineInfo').textContent = `오프라인 내장 · ${DATA.documents.length}개 문서(${totalPages}쪽) · 서식 ${DATA.forms.length}종`;
  const profLabel = DATA.profile === 'full' ? '전체 PDF 내장' : DATA.profile === 'standard' ? '서식 PDF 내장' : '초경량 색인';
  document.getElementById('profileTag').textContent = profLabel;

  document.getElementById('btnOnline').addEventListener('click', () => {
    if (window.AndroidApp && window.AndroidApp.openServerSettings) {
      window.AndroidApp.openServerSettings();
    } else {
      alert('안드로이드 앱에서 실행하면 서버 연결 화면으로 전환됩니다.');
    }
  });

  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      activeTab = btn.dataset.tab;
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
      render();
    });
  });

  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function extractTerms(q) {
    const articles = Array.from(q.matchAll(/제\s*(\d+)\s*조/g)).map(m => `제${m[1]}조`);
    const toks = q.match(/[가-힣A-Za-z0-9]+/g) || [];
    const primary = new Set();
    const expanded = new Set();
    toks.forEach(raw => {
      const low = raw.toLowerCase();
      const stem = low.length >= 3 ? low.replace(PARTICLE, '') : low;
      const cand = stem.length >= 2 ? stem : low;
      if (cand.length < 2 || STOP.has(cand)) return;
      primary.add(cand); expanded.add(cand);
      const syns = SYNONYMS[cand] || SYNONYMS[low];
      if (syns) syns.forEach(s => expanded.add(s.replace(/\s+/g,'').toLowerCase()));
    });
    articles.forEach(a => { primary.add(a); expanded.add(a); });
    if (primary.size === 0) {
      toks.filter(t => t.length >= 2).forEach(t => { primary.add(t.toLowerCase()); expanded.add(t.toLowerCase()); });
    }
    return { primary: Array.from(primary), expanded: Array.from(expanded), articles };
  }

  function runSearch(q) {
    searchQuery = q.trim();
    if (!searchQuery) { lastResults = null; render(); return; }
    const { primary, expanded, articles } = extractTerms(searchQuery);
    const compactQ = searchQuery.replace(/\s+/g, '').toLowerCase();
    const hits = [];

    for (const ch of DATA.chunks) {
      if (selectedDocId !== 'ALL' && ch.doc_id !== selectedDocId) continue;
      const doc = docMap.get(ch.doc_id);
      const head = `${ch.section_path || ''} ${ch.heading || ''}`.replace(/\s+/g, '').toLowerCase();
      const body = ch.content.replace(/\s+/g, '').toLowerCase();
      let score = 0; let pHits = 0;
      if (compactQ.length >= 4 && body.includes(compactQ)) score += 18;
      for (const a of articles) {
        if (head.includes(a) || body.includes(a)) { score += 16; pHits++; }
      }
      for (const t of primary) {
        const ct = t.replace(/\s+/g, '');
        const inH = head.includes(ct); const inB = body.includes(ct);
        if (inH || inB) {
          pHits++;
          if (inH) score += 10;
          if (inB) score += 6;
        }
      }
      for (const s of expanded) {
        if (primary.includes(s)) continue;
        if (head.includes(s) || body.includes(s)) score += 3.5;
      }
      if (score > 0) {
        score += ((doc && doc.priority) || 50) * 0.015;
        hits.push({ ch, doc, score, pHits });
      }
    }
    hits.sort((a, b) => b.score - a.score);
    const top = hits.slice(0, 12);
    const hasEvidence = top.length > 0 && (top[0].pHits >= 1 || top[0].score >= 8.5);
    const relForms = hasEvidence ? DATA.forms.filter(f => {
      if (selectedDocId !== 'ALL' && f.doc_id !== selectedDocId) return false;
      const hay = `${f.title} ${f.category} ${f.sample_text || ''}`.replace(/\s+/g, '').toLowerCase();
      return expanded.some(t => hay.includes(t));
    }).slice(0, 4) : [];

    lastResults = { query: searchQuery, hasEvidence, items: hasEvidence ? top : [], forms: relForms, terms: primary };
    render();
  }

  function highlight(text, terms) {
    let html = esc(text);
    (terms || []).slice(0, 5).forEach(t => {
      if (t.length < 2) return;
      const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
      html = html.replace(re, m => `<mark>${m}</mark>`);
    });
    return html;
  }

  function openPageModal(docId, pageNo) {
    const doc = docMap.get(docId);
    if (!doc) return;
    let cur = Math.max(1, Math.min(doc.page_count || 1, pageNo));
    function draw() {
      const pChunks = DATA.chunks.filter(c => c.doc_id === docId && c.page_start <= cur && c.page_end >= cur);
      const txt = pChunks.length ? pChunks.map(c => c.content).join('\n\n') : '해당 페이지에 색인된 텍스트가 없습니다.';
      document.getElementById('modalRoot').innerHTML = `
        <div class="modal-bg" id="mBg">
          <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-head">
              <div style="min-width:0;flex:1">
                <div class="card-title" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(doc.title)}</div>
                <div class="card-meta">${cur} / ${doc.page_count}쪽 (오프라인 원문)</div>
              </div>
              <button class="btn" id="mClose" type="button">닫기</button>
            </div>
            <div class="modal-body">${esc(txt)}</div>
            <div class="modal-foot">
              <button class="btn" id="mPrev" type="button" ${cur <= 1 ? 'disabled' : ''}>이전 쪽</button>
              <span style="font-size:12px;color:var(--muted)">${cur} / ${doc.page_count}</span>
              <button class="btn" id="mNext" type="button" ${cur >= doc.page_count ? 'disabled' : ''}>다음 쪽</button>
            </div>
          </div>
        </div>`;
      document.getElementById('mBg').onclick = closeModal;
      document.getElementById('mClose').onclick = closeModal;
      document.getElementById('mPrev').onclick = () => { if (cur > 1) { cur--; draw(); } };
      document.getElementById('mNext').onclick = () => { if (cur < doc.page_count) { cur++; draw(); } };
    }
    draw();
  }

  function openFormModal(form) {
    const fieldsText = (form.fields || []).length ? `감지된 항목: ${form.fields.join(', ')}\n\n` : '';
    document.getElementById('modalRoot').innerHTML = `
      <div class="modal-bg" id="mBg">
        <div class="modal" onclick="event.stopPropagation()">
          <div class="modal-head">
            <div style="min-width:0;flex:1">
              <div class="card-title">${esc(form.title)}</div>
              <div class="card-meta">${esc(form.doc_title)} · p.${form.page_start}</div>
            </div>
            <button class="btn" id="mClose" type="button">닫기</button>
          </div>
          <div class="modal-body">${esc(fieldsText + (form.sample_text || '서식 본문 미리보기 없음'))}</div>
          <div class="modal-foot">
            <button class="btn" id="mPage" type="button">원문 p.${form.page_start} 보기</button>
            ${form.has_pdf ? '<button class="btn btn-blue" id="mPdf" type="button">원본 PDF 저장·열기</button>' : ''}
          </div>
        </div>
      </div>`;
    document.getElementById('mBg').onclick = closeModal;
    document.getElementById('mClose').onclick = closeModal;
    document.getElementById('mPage').onclick = () => openPageModal(form.doc_id, form.page_start);
    const pdfBtn = document.getElementById('mPdf');
    if (pdfBtn) pdfBtn.onclick = () => triggerOfflinePdf(form);
  }

  function closeModal() { document.getElementById('modalRoot').innerHTML = ''; }

  function triggerOfflinePdf(form) {
    const safeName = `${form.title.replace(/[\\/:*?"<>|]+/g, '_')}.pdf`;
    if (window.AndroidApp && window.AndroidApp.openOfflineFormPdf) {
      window.AndroidApp.openOfflineFormPdf(form.id, safeName);
    } else {
      window.open(`forms/${encodeURIComponent(form.id)}.pdf`, '_blank');
    }
  }

  function triggerOfflineDocPdf(doc) {
    const safeName = `${doc.title.replace(/[\\/:*?"<>|]+/g, '_')}.pdf`;
    if (window.AndroidApp && window.AndroidApp.openOfflineDocPdf) {
      window.AndroidApp.openOfflineDocPdf(doc.id, safeName);
    } else {
      window.open(`pdfs/${encodeURIComponent(doc.id)}.pdf`, '_blank');
    }
  }

  function render() {
    const el = document.getElementById('mainArea');
    if (activeTab === 'search') {
      const chipsHtml = [
        `<button class="chip ${selectedDocId === 'ALL' ? 'active' : ''}" data-doc="ALL" type="button">전체 (${DATA.documents.length})</button>`,
        ...DATA.documents.map(d => `<button class="chip ${selectedDocId === d.id ? 'active' : ''}" data-doc="${esc(d.id)}" type="button">${esc(d.title)}</button>`)
      ].join('');

      let bodyHtml = '';
      if (!lastResults) {
        const samples = [
          { t: '장로 임직 · 추천 기준', q: '장로 후보자 추천 나이 임직' },
          { t: '셀지기 자격 · 직무', q: '셀지기 조건 자격 직무' },
          { t: '유급직원 복무 · 휴가', q: '유급직원 복무 휴가 규정' },
          { t: '학습·세례 청원서', q: '학습세례 신청서 청원서' },
        ];
        bodyHtml = `<div class="quick-grid">${samples.map(s =>
          `<button class="quick-btn" data-q="${esc(s.q)}" type="button"><strong>${esc(s.t)}</strong><span>${esc(s.q)}</span></button>`
        ).join('')}</div>`;
      } else if (!lastResults.hasEvidence) {
        bodyHtml = `<div class="card"><div class="card-title">제공된 자료에서 해당 정보를 찾을 수 없습니다.</div><div class="card-meta" style="margin-top:6px">검색 범위(문서 필터)를 확인하거나 다른 핵심 단어로 다시 검색해 주세요.</div></div>`;
      } else {
        const formBlock = lastResults.forms.length ? `
          <div class="card" style="background:#fbfbfd">
            <div class="card-title">관련 서식 · 표 (${lastResults.forms.length}건)</div>
            <div class="card-actions" style="margin-top:8px">
              ${lastResults.forms.map(f =>
                f.has_pdf
                  ? `<button class="btn btn-blue" data-fpdf="${esc(f.id)}" type="button">${esc(f.title)} PDF</button>`
                  : `<button class="btn" data-fview="${esc(f.id)}" type="button">${esc(f.title)} 보기</button>`
              ).join('')}
            </div>
          </div>` : '';

        bodyHtml = formBlock + lastResults.items.map((it, idx) => {
          const loc = it.ch.page_start === it.ch.page_end ? `p.${it.ch.page_start}` : `p.${it.ch.page_start}~${it.ch.page_end}`;
          const sec = [it.ch.section_path, it.ch.heading].filter(Boolean).join(' · ');
          return `
            <div class="card">
              <span class="badge-hit">근거 ${idx + 1} · ${esc(loc)}</span>
              <div class="card-title">${esc(it.doc ? it.doc.title : '')}</div>
              ${sec ? `<div class="card-meta">${esc(sec)}</div>` : ''}
              <div class="card-body">${highlight(it.ch.content, lastResults.terms)}</div>
              <div class="card-actions">
                <button class="btn" data-open-doc="${esc(it.ch.doc_id)}" data-open-page="${it.ch.page_start}" type="button">전후 쪽 원문 열람</button>
              </div>
            </div>`;
        }).join('');
      }

      el.innerHTML = `
        <div class="search-wrap">
          <form class="search-box" id="sForm">
            <input id="sInput" type="search" value="${esc(searchQuery)}" placeholder="키워드·조항 즉시 오프라인 검색..." />
            <button class="btn-go" type="submit" aria-label="검색">
              <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </button>
          </form>
          <div class="chips">${chipsHtml}</div>
        </div>
        ${bodyHtml}`;

      document.getElementById('sForm').onsubmit = e => {
        e.preventDefault();
        runSearch(document.getElementById('sInput').value);
      };
      el.querySelectorAll('[data-doc]').forEach(b => b.onclick = () => {
        selectedDocId = b.dataset.doc;
        if (searchQuery) runSearch(searchQuery); else render();
      });
      el.querySelectorAll('[data-q]').forEach(b => b.onclick = () => runSearch(b.dataset.q));
      el.querySelectorAll('[data-open-doc]').forEach(b => b.onclick = () => openPageModal(b.dataset.openDoc, Number(b.dataset.openPage)));
      el.querySelectorAll('[data-fpdf]').forEach(b => b.onclick = () => {
        const f = DATA.forms.find(x => x.id === b.dataset.fpdf);
        if (f) triggerOfflinePdf(f);
      });
      el.querySelectorAll('[data-fview]').forEach(b => b.onclick = () => {
        const f = DATA.forms.find(x => x.id === b.dataset.fview);
        if (f) openFormModal(f);
      });
    } else if (activeTab === 'docs') {
      el.innerHTML = DATA.documents.map(d => `
        <div class="card">
          <div class="card-title">${esc(d.title)}</div>
          <div class="card-meta">${esc(d.category)} · 총 ${d.page_count}쪽</div>
          <div class="card-actions">
            <button class="btn btn-blue" data-read-doc="${esc(d.id)}" type="button">1쪽부터 읽기</button>
            <button class="btn" data-filter-doc="${esc(d.id)}" type="button">이 문서만 검색</button>
            ${d.has_full_pdf ? `<button class="btn" data-doc-pdf="${esc(d.id)}" type="button">원본 PDF 열기</button>` : ''}
          </div>
        </div>`).join('');
      el.querySelectorAll('[data-read-doc]').forEach(b => b.onclick = () => openPageModal(b.dataset.readDoc, 1));
      el.querySelectorAll('[data-filter-doc]').forEach(b => b.onclick = () => {
        selectedDocId = b.dataset.filterDoc;
        activeTab = 'search';
        document.querySelectorAll('.nav-btn').forEach(nb => nb.classList.toggle('active', nb.dataset.tab === 'search'));
        render();
      });
      el.querySelectorAll('[data-doc-pdf]').forEach(b => b.onclick = () => {
        const d = docMap.get(b.dataset.docPdf);
        if (d) triggerOfflineDocPdf(d);
      });
    } else {
      const cats = ['전체', ...Array.from(new Set(DATA.forms.map(f => f.category)))];
      const q = formQuery.trim().toLowerCase();
      const filtered = DATA.forms.filter(f => {
        if (formCategory !== '전체' && f.category !== formCategory) return false;
        if (!q) return true;
        return `${f.title} ${f.category} ${f.doc_title} ${f.sample_text || ''}`.toLowerCase().includes(q);
      });
      el.innerHTML = `
        <div class="search-wrap">
          <div class="search-box">
            <input id="fInput" type="search" value="${esc(formQuery)}" placeholder="서식 검색 (청원서, 신청서, 소원장...)" />
          </div>
          <div class="chips">${cats.map(c => `<button class="chip ${formCategory === c ? 'active' : ''}" data-cat="${esc(c)}" type="button">${esc(c)}</button>`).join('')}</div>
        </div>
        ${filtered.length === 0 ? '<div class="empty">일치하는 서식이 없습니다.</div>' : filtered.map(f => `
          <div class="card">
            <div class="card-title">${esc(f.title)}</div>
            <div class="card-meta">${esc(f.doc_title)} · p.${f.page_start} · ${esc(f.category)}</div>
            <div class="card-actions">
              ${f.has_pdf ? `<button class="btn btn-blue" data-fpdf="${esc(f.id)}" type="button">원본 PDF 저장·열기</button>` : ''}
              <button class="btn" data-fview="${esc(f.id)}" type="button">서식 내용 보기</button>
              <button class="btn" data-open-doc="${esc(f.doc_id)}" data-open-page="${f.page_start}" type="button">p.${f.page_start}</button>
            </div>
          </div>`).join('')}`;
      document.getElementById('fInput').oninput = e => { formQuery = e.target.value; render(); };
      el.querySelectorAll('[data-cat]').forEach(b => b.onclick = () => { formCategory = b.dataset.cat; render(); });
      el.querySelectorAll('[data-fpdf]').forEach(b => b.onclick = () => {
        const f = DATA.forms.find(x => x.id === b.dataset.fpdf);
        if (f) triggerOfflinePdf(f);
      });
      el.querySelectorAll('[data-fview]').forEach(b => b.onclick = () => {
        const f = DATA.forms.find(x => x.id === b.dataset.fview);
        if (f) openFormModal(f);
      });
      el.querySelectorAll('[data-open-doc]').forEach(b => b.onclick = () => openPageModal(b.dataset.openDoc, Number(b.dataset.openPage)));
    }
  }

  render();
})();
</script>
</body>
</html>
"""


def build_offline_assets(profile: str = "standard", out_assets_dir: Path | None = None) -> Path:
    if profile not in ("lite", "standard", "full"):
        raise ValueError(f"Unsupported profile: {profile}")

    assets_dir = out_assets_dir or (ROOT / "android" / "build" / "assets")
    offline_dir = assets_dir / "offline"
    if offline_dir.exists():
        shutil.rmtree(offline_dir)
    offline_dir.mkdir(parents=True, exist_ok=True)

    db = Database()
    bundle = db.export_offline_bundle(DEFAULT_NOTEBOOK_ID)
    if not bundle:
        raise RuntimeError(f"Default notebook '{DEFAULT_NOTEBOOK_ID}' not found in DB.")

    bundle["profile"] = profile

    # Optionally bundle all 60 original form PDFs inside APK (standard & full)
    pdf_count = 0
    if profile in ("standard", "full"):
        forms_dir = offline_dir / "forms"
        forms_dir.mkdir(parents=True, exist_ok=True)
        for f_meta in bundle["forms"]:
            full_form = db.get_form(f_meta["id"])
            if full_form and full_form.get("doc_file_type") == "pdf":
                try:
                    exported = export_original_pdf(full_form)
                    shutil.copy2(exported, forms_dir / f"{f_meta['id']}.pdf")
                    f_meta["has_pdf"] = True
                    pdf_count += 1
                except Exception:
                    f_meta["has_pdf"] = False
            else:
                f_meta["has_pdf"] = False
    else:
        for f_meta in bundle["forms"]:
            f_meta["has_pdf"] = False

    # Optionally bundle all 4 full source PDFs (full profile)
    full_pdf_count = 0
    if profile == "full":
        pdfs_dir = offline_dir / "pdfs"
        pdfs_dir.mkdir(parents=True, exist_ok=True)
        for d_meta in bundle["documents"]:
            full_doc = db.get_document(d_meta["id"])
            if full_doc and full_doc.get("file_type") == "pdf":
                src = Path(full_doc["stored_path"])
                if src.exists():
                    shutil.copy2(src, pdfs_dir / f"{d_meta['id']}.pdf")
                    d_meta["has_full_pdf"] = True
                    full_pdf_count += 1
                else:
                    d_meta["has_full_pdf"] = False
            else:
                d_meta["has_full_pdf"] = False
    else:
        for d_meta in bundle["documents"]:
            d_meta["has_full_pdf"] = False

    # Write corpus.js (classic script tag so file:///android_asset works with zero CORS restrictions)
    corpus_js = "window.__OFFLINE_CORPUS__ = " + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (offline_dir / "corpus.js").write_text(corpus_js, encoding="utf-8")
    (offline_dir / "index.html").write_text(OFFLINE_HTML, encoding="utf-8")

    total_bytes = sum(p.stat().st_size for p in offline_dir.rglob("*") if p.is_file())
    print(
        f"[offline-assets] profile={profile} docs={len(bundle['documents'])} "
        f"chunks={len(bundle['chunks'])} forms={len(bundle['forms'])} "
        f"form_pdfs={pdf_count} full_pdfs={full_pdf_count} raw_size={total_bytes / (1024*1024):.2f} MB",
        flush=True,
    )
    return assets_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline Android WebView assets.")
    parser.add_argument("--profile", choices=["lite", "standard", "full"], default="standard")
    args = parser.parse_args()
    build_offline_assets(profile=args.profile)


if __name__ == "__main__":
    main()
