import React, { useEffect, useMemo, useState } from 'react';
import {
  Check,
  Download,
  Eye,
  FileEdit,
  FileText,
  Loader2,
  Plus,
  Printer,
  Save,
  Sparkles,
  Trash2,
  UserCheck,
  UserCog,
  X,
} from 'lucide-react';
import { api, safeAssetUrl, triggerTicketDownload } from '../api';
import {
  hasSavedProfile,
  loadUserProfile,
  matchProfileToFieldLabel,
  profileToFlatMap,
  saveUserProfile,
  todayKoreanDate,
  type UserProfile,
} from '../profileStore';
import type { FormItem, StructuredFormDraft } from '../types';

interface Props {
  form: FormItem;
  onClose: () => void;
}

function buildInitialDraft(form: FormItem, profile: UserProfile): StructuredFormDraft {
  const baseLabels =
    form.fields && form.fields.length > 0
      ? form.fields
      : ['성명', '직분', '소속', '연락처', '신청 사유'];
  const shouldApply = profile.autoApply && hasSavedProfile(profile);
  const fields = baseLabels.map((label) => ({
    label,
    value: shouldApply ? matchProfileToFieldLabel(label, profile) : '',
  }));
  const signerName = shouldApply && profile.name.trim() ? profile.name.trim() : '            ';
  return {
    document_title: form.title,
    fields,
    body_paragraphs: [],
    date_line: todayKoreanDate(),
    signer_line: `신청인(제출자): ${signerName} (인)`,
    recipient_line: (shouldApply && profile.recipient.trim()) || '목포사랑의교회 당회장 귀하',
  };
}

export const AutofillModal: React.FC<Props> = ({ form, onClose }) => {
  const [profile, setProfile] = useState<UserProfile>(() => loadUserProfile());
  const [showProfileEditor, setShowProfileEditor] = useState(false);
  const [profileSavedToast, setProfileSavedToast] = useState(false);

  const [draft, setDraft] = useState<StructuredFormDraft>(() => buildInitialDraft(form, loadUserProfile()));
  const [bodyText, setBodyText] = useState('');
  const [aiPrompt, setAiPrompt] = useState('');
  const [previewTab, setPreviewTab] = useState<'draft' | 'original'>('draft');
  const [imgError, setImgError] = useState(false);

  const [aiLoading, setAiLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [statusNotice, setStatusNotice] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const p = loadUserProfile();
    setProfile(p);
    setDraft(buildInitialDraft(form, p));
    setBodyText('');
    setImgError(false);
  }, [form]);

  const profileConfigured = useMemo(() => hasSavedProfile(profile), [profile]);

  const applyProfileToDraft = (p: UserProfile = profile) => {
    setDraft((prev) => {
      const nextFields = prev.fields.map((f) => {
        const matched = matchProfileToFieldLabel(f.label, p);
        return matched ? { ...f, value: matched } : f;
      });
      const signerName = p.name.trim() || '            ';
      return {
        ...prev,
        fields: nextFields,
        signer_line: `신청인(제출자): ${signerName} (인)`,
        recipient_line: p.recipient.trim() || prev.recipient_line,
      };
    });
    setStatusNotice('내 기본 정보가 서식 항목과 미리보기에 즉시 반영되었습니다.');
    setTimeout(() => setStatusNotice(''), 2600);
  };

  const handleSaveProfile = () => {
    saveUserProfile(profile);
    setProfileSavedToast(true);
    setTimeout(() => setProfileSavedToast(false), 1800);
    applyProfileToDraft(profile);
    setShowProfileEditor(false);
  };

  const updateField = (idx: number, key: 'label' | 'value', val: string) => {
    setDraft((prev) => ({
      ...prev,
      fields: prev.fields.map((f, i) => (i === idx ? { ...f, [key]: val } : f)),
    }));
  };

  const addCustomField = () => {
    setDraft((prev) => ({
      ...prev,
      fields: [...prev.fields, { label: '추가 항목', value: '' }],
    }));
  };

  const removeField = (idx: number) => {
    setDraft((prev) => ({
      ...prev,
      fields: prev.fields.filter((_, i) => i !== idx),
    }));
  };

  const effectiveDraft: StructuredFormDraft = useMemo(
    () => ({
      ...draft,
      body_paragraphs: bodyText
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
    }),
    [draft, bodyText]
  );

  const handleAiFill = async (e: React.FormEvent) => {
    e.preventDefault();
    if (aiLoading) return;
    const summaryPairs = draft.fields
      .filter((f) => f.value.trim())
      .map((f) => `${f.label}: ${f.value.trim()}`)
      .join(', ');
    const combinedInstruction = [aiPrompt.trim(), summaryPairs].filter(Boolean).join('\n');
    if (!combinedInstruction && !profileConfigured) {
      setError('내 기본 정보를 등록하거나 AI에게 요청할 내용을 입력해 주세요.');
      return;
    }

    setAiLoading(true);
    setError('');
    setStatusNotice('');
    try {
      const res = await api.autofillForm(form.id, combinedInstruction || '내 기본 정보에 맞게 서식 작성', profileToFlatMap(profile));
      const s = res.structured || {};
      setDraft((prev) => ({
        document_title: s.document_title || prev.document_title,
        fields: Array.isArray(s.fields) && s.fields.length > 0 ? s.fields : prev.fields,
        body_paragraphs: Array.isArray(s.body_paragraphs) ? s.body_paragraphs : prev.body_paragraphs,
        date_line: s.date_line || prev.date_line,
        signer_line: s.signer_line || prev.signer_line,
        recipient_line: s.recipient_line || prev.recipient_line,
      }));
      if (Array.isArray(s.body_paragraphs) && s.body_paragraphs.length > 0) {
        setBodyText(s.body_paragraphs.join('\n'));
      }
      setPreviewTab('draft');
      setStatusNotice('AI가 서식 항목과 문구를 정리해 오른쪽 A4 미리보기에 반영했습니다.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 자동 작성 중 오류가 발생했습니다.');
    } finally {
      setAiLoading(false);
    }
  };

  const handleDownloadDocx = async () => {
    if (exporting) return;
    setExporting(true);
    setError('');
    try {
      const res = await api.renderFormDocx(form.id, effectiveDraft);
      await triggerTicketDownload(res.download_url, res.filename);
      setStatusNotice(`작성된 Word 파일(${res.filename}) 다운로드를 시작했습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Word 파일 생성에 실패했습니다.');
    } finally {
      setExporting(false);
    }
  };

  const handlePrintPreview = () => {
    const win = window.open('', '_blank', 'width=840,height=1020');
    if (!win) {
      window.print();
      return;
    }
    const esc = (s: string) =>
      s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] || c);
    const rowsHtml = effectiveDraft.fields
      .map(
        (f) =>
          `<tr><th style="width:28%;background:#f5f5f4;border:1px solid #444;padding:10px 12px;text-align:left;font-weight:600;">${esc(f.label)}</th><td style="border:1px solid #444;padding:10px 12px;">${esc(f.value)}</td></tr>`
      )
      .join('');
    const bodyHtml = effectiveDraft.body_paragraphs
      .map((p) => `<p style="margin:8px 0;line-height:1.8;">${esc(p)}</p>`)
      .join('');
    win.document.write(`<!doctype html><html lang="ko"><head><meta charset="utf-8"/><title>${esc(effectiveDraft.document_title)}</title><style>@page{size:A4;margin:20mm;}body{font-family:"Malgun Gothic","Apple SD Gothic Neo",sans-serif;color:#111;padding:24px;}table{width:100%;border-collapse:collapse;margin-top:20px;font-size:13.5px;}</style></head><body><h1 style="text-align:center;font-size:22px;letter-spacing:0.08em;border-bottom:2px solid #111;padding-bottom:12px;margin:0 0 18px;">${esc(effectiveDraft.document_title)}</h1><table>${rowsHtml}</table>${bodyHtml ? `<div style="margin-top:22px;font-size:14px;">${bodyHtml}</div>` : ''}<p style="text-align:center;margin-top:42px;font-size:14px;">${esc(effectiveDraft.date_line)}</p><p style="text-align:right;margin-top:22px;font-size:14.5px;font-weight:600;">${esc(effectiveDraft.signer_line)}</p><p style="text-align:center;margin-top:44px;font-size:17px;font-weight:700;">${esc(effectiveDraft.recipient_line)}</p><script>window.onload=function(){window.print();}</script></body></html>`);
    win.document.close();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-2.5 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="flex max-h-[94dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-[#fafaf9] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Studio Header */}
        <div className="flex items-center justify-between gap-3 border-b border-black/[0.07] bg-white px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#18181b] text-white">
              <FileEdit className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold tracking-tight text-[#18181b]">
                서식 작성 · 실시간 미리보기 — {form.title}
              </h3>
              <p className="truncate text-[11px] text-[#71717a]">
                {form.doc_title} · p.{form.page_start}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="shrink-0 rounded-lg p-1.5 text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Split Studio Body */}
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-12 lg:overflow-hidden">
          {/* LEFT: Personal Profile + Direct Field Editor + AI Helper */}
          <div className="space-y-4 border-b border-black/[0.07] bg-white p-4 sm:p-5 lg:col-span-5 lg:overflow-y-auto lg:border-r lg:border-b-0">
            {/* Saved Personal Profile Strip */}
            <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <UserCheck className="h-4 w-4 shrink-0 text-[#0f4c81]" />
                  <span className="truncate text-xs font-semibold text-[#18181b]">내 기본 정보 프로필</span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {profileConfigured && (
                    <button
                      type="button"
                      onClick={() => applyProfileToDraft()}
                      className="chip-nowrap rounded-md bg-[#18181b] px-2.5 py-1 text-[11px] font-medium text-white transition hover:bg-[#27272a]"
                    >
                      바로 적용
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowProfileEditor((v) => !v)}
                    className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.1] bg-white px-2 py-1 text-[11px] font-medium text-[#3f3f46] transition hover:bg-black/[0.04]"
                  >
                    <UserCog className="h-3 w-3" />
                    <span>{showProfileEditor ? '접기' : profileConfigured ? '수정' : '등록'}</span>
                  </button>
                </div>
              </div>

              {!showProfileEditor && (
                <p className="mt-1.5 truncate text-[11.5px] text-[#71717a]">
                  {profileConfigured
                    ? [profile.name, profile.position, profile.department, profile.phone].filter(Boolean).join(' · ')
                    : '성명·직분·부서·연락처를 1회 등록해 두면 이 기기에서만 보관되며 모든 서식에 즉시 자동 기입됩니다.'}
                </p>
              )}

              {showProfileEditor && (
                <div className="mt-3 space-y-2.5 border-t border-black/[0.07] pt-3">
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      type="text"
                      value={profile.name}
                      onChange={(e) => setProfile({ ...profile, name: e.target.value })}
                      placeholder="성명 (예: 홍길동)"
                      className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                    <input
                      type="text"
                      value={profile.position}
                      onChange={(e) => setProfile({ ...profile, position: e.target.value })}
                      placeholder="직분 (예: 목사, 장로, 간사)"
                      className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                    <input
                      type="text"
                      value={profile.department}
                      onChange={(e) => setProfile({ ...profile, department: e.target.value })}
                      placeholder="소속 부서·교구·셀"
                      className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                    <input
                      type="text"
                      value={profile.birthDate}
                      onChange={(e) => setProfile({ ...profile, birthDate: e.target.value })}
                      placeholder="생년월일 (1985-03-15)"
                      className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                    <input
                      type="text"
                      value={profile.phone}
                      onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
                      placeholder="연락처 (010-0000-0000)"
                      className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                    <input
                      type="text"
                      value={profile.email}
                      onChange={(e) => setProfile({ ...profile, email: e.target.value })}
                      placeholder="이메일 (선택)"
                      className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                  </div>
                  <input
                    type="text"
                    value={profile.address}
                    onChange={(e) => setProfile({ ...profile, address: e.target.value })}
                    placeholder="주소 (선택)"
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                  />
                  <input
                    type="text"
                    value={profile.recipient}
                    onChange={(e) => setProfile({ ...profile, recipient: e.target.value })}
                    placeholder="기본 수신처 (예: 목포사랑의교회 당회장 귀하)"
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                  />
                  <label className="flex cursor-pointer items-center gap-2 text-[11.5px] text-[#52525b]">
                    <input
                      type="checkbox"
                      checked={profile.autoApply}
                      onChange={(e) => setProfile({ ...profile, autoApply: e.target.checked })}
                      className="accent-[#18181b]"
                    />
                    <span>서식 창을 열 때 내 기본 정보 자동으로 채우기</span>
                  </label>
                  <div className="flex items-center justify-between pt-1">
                    <span className="text-[10.5px] text-[#71717a]">현재 기기 브라우저에만 안전하게 저장됩니다</span>
                    <button
                      type="button"
                      onClick={handleSaveProfile}
                      className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#0f4c81] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0c3d68]"
                    >
                      {profileSavedToast ? <Check className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
                      <span>저장 · 즉시 적용</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Live Direct Field Editor */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[#18181b]">서식 항목 직접 입력</span>
                <button
                  type="button"
                  onClick={addCustomField}
                  className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
                >
                  <Plus className="h-3 w-3" />
                  <span>항목 추가</span>
                </button>
              </div>

              <div className="space-y-1.5">
                {draft.fields.map((f, idx) => (
                  <div key={idx} className="group flex items-center gap-1.5">
                    <input
                      type="text"
                      value={f.label}
                      onChange={(e) => updateField(idx, 'label', e.target.value)}
                      aria-label="항목명"
                      className="w-24 shrink-0 rounded-lg border border-black/[0.08] bg-[#fafaf9] px-2 py-1.5 text-xs font-medium text-[#3f3f46] outline-none focus:border-[#0f4c81] focus:bg-white"
                    />
                    <input
                      type="text"
                      value={f.value}
                      onChange={(e) => updateField(idx, 'value', e.target.value)}
                      placeholder={`${f.label} 입력`}
                      className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                    />
                    <button
                      type="button"
                      onClick={() => removeField(idx)}
                      aria-label="항목 삭제"
                      className="shrink-0 rounded p-1 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-2 pt-1 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-[11px] font-medium text-[#71717a]">작성일</label>
                  <input
                    type="text"
                    value={draft.date_line}
                    onChange={(e) => setDraft({ ...draft, date_line: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-[#18181b] outline-none focus:border-[#0f4c81]"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-medium text-[#71717a]">제출자 서명란</label>
                  <input
                    type="text"
                    value={draft.signer_line}
                    onChange={(e) => setDraft({ ...draft, signer_line: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-[#18181b] outline-none focus:border-[#0f4c81]"
                  />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[11px] font-medium text-[#71717a]">본문 사유 · 추가 내용 (선택)</label>
                <textarea
                  rows={2}
                  value={bodyText}
                  onChange={(e) => setBodyText(e.target.value)}
                  placeholder="위와 같이 신청(청원)하오니 허락하여 주시기 바랍니다."
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[16px] leading-relaxed text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
                />
              </div>
            </div>

            {/* AI Natural Language Assistant */}
            <form onSubmit={handleAiFill} className="space-y-2 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3">
              <label className="flex items-center gap-1.5 text-xs font-semibold text-[#18181b]">
                <Sparkles className="h-3.5 w-3.5 text-[#0f4c81]" />
                <span>AI 자연어 자동 기입 (선택)</span>
              </label>
              <textarea
                rows={2}
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                placeholder="예: 12월 1일부터 14일까지 가족 돌봄 사유로 청원휴가 신청 문구를 정중하게 채워줘"
                className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-[16px] leading-relaxed text-[#18181b] outline-none focus:border-[#0f4c81] lg:text-xs"
              />
              <button
                type="submit"
                disabled={aiLoading}
                className="chip-nowrap flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#0f4c81] py-2 text-xs font-semibold text-white transition hover:bg-[#0c3d68] disabled:opacity-50"
              >
                {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                <span>{aiLoading ? 'AI가 항목·문구 구성 중...' : '내 정보 + 요청으로 AI 자동 채우기'}</span>
              </button>
            </form>

            {statusNotice && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11.5px] font-medium text-emerald-800">
                {statusNotice}
              </div>
            )}
            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11.5px] font-medium text-red-700">
                {error}
              </div>
            )}
          </div>

          {/* RIGHT: Live A4 Document Preview + Original PDF Comparison */}
          <div className="flex min-h-[380px] flex-col bg-[#f4f4f2] p-4 sm:p-5 lg:col-span-7 lg:overflow-y-auto">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="inline-flex rounded-lg bg-black/[0.06] p-0.5">
                <button
                  type="button"
                  onClick={() => setPreviewTab('draft')}
                  className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                    previewTab === 'draft' ? 'bg-white text-[#18181b] shadow-2xs' : 'text-[#71717a]'
                  }`}
                >
                  <FileText className="h-3.5 w-3.5" />
                  <span>실시간 A4 미리보기</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewTab('original')}
                  className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                    previewTab === 'original' ? 'bg-white text-[#18181b] shadow-2xs' : 'text-[#71717a]'
                  }`}
                >
                  <Eye className="h-3.5 w-3.5" />
                  <span>원본 서식 대조</span>
                </button>
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => void triggerTicketDownload(`/api/forms/${form.id}/download/pdf`, `${form.title}.pdf`)}
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1 text-[11px] font-medium text-[#3f3f46] hover:bg-black/[0.03]"
                >
                  <Download className="h-3 w-3" />
                  <span>빈 원본 PDF</span>
                </button>
                <button
                  type="button"
                  onClick={handlePrintPreview}
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1 text-[11px] font-medium text-[#3f3f46] hover:bg-black/[0.03]"
                >
                  <Printer className="h-3 w-3" />
                  <span>인쇄</span>
                </button>
              </div>
            </div>

            {previewTab === 'draft' ? (
              <div className="mx-auto w-full max-w-[560px] rounded-lg border border-black/[0.1] bg-white px-6 py-8 shadow-[0_8px_28px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
                {/* Official Korean Document Sheet */}
                <div className="border-b-2 border-[#18181b] pb-3 text-center">
                  <input
                    type="text"
                    value={draft.document_title}
                    onChange={(e) => setDraft({ ...draft, document_title: e.target.value })}
                    className="w-full bg-transparent text-center text-lg font-bold tracking-[0.1em] text-[#18181b] outline-none sm:text-xl"
                  />
                </div>

                <table className="mt-5 w-full border-collapse text-xs sm:text-[13px]">
                  <tbody>
                    {effectiveDraft.fields.map((f, idx) => (
                      <tr key={idx}>
                        <th className="w-[30%] border border-[#3f3f46] bg-[#f8f8f7] px-3 py-2.5 text-left font-semibold text-[#18181b]">
                          {f.label}
                        </th>
                        <td className="border border-[#3f3f46] px-3 py-2.5 text-[#18181b]">
                          {f.value ? (
                            f.value
                          ) : (
                            <span className="text-[11px] text-[#a1a1aa]">(미입력 · 공란 유지)</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {effectiveDraft.body_paragraphs.length > 0 && (
                  <div className="mt-5 space-y-2 rounded border border-black/[0.06] bg-[#fafaf9] p-3.5 text-[13px] leading-7 text-[#27272a]">
                    {effectiveDraft.body_paragraphs.map((p, i) => (
                      <p key={i}>{p}</p>
                    ))}
                  </div>
                )}

                <div className="mt-9 space-y-4">
                  <p className="text-center text-xs font-medium text-[#27272a] sm:text-[13.5px]">
                    {effectiveDraft.date_line}
                  </p>
                  <p className="text-right text-xs font-semibold text-[#18181b] sm:text-[13.5px]">
                    {effectiveDraft.signer_line}
                  </p>
                  <p className="pt-4 text-center text-sm font-bold tracking-wide text-[#18181b] sm:text-base">
                    {effectiveDraft.recipient_line}
                  </p>
                </div>
              </div>
            ) : (
              <div className="mx-auto w-full max-w-[560px] rounded-xl border border-black/[0.08] bg-white p-3 shadow-xs">
                {!imgError ? (
                  <img
                    src={safeAssetUrl(`/api/documents/${encodeURIComponent(form.doc_id)}/page/${form.page_start}.png?dpi=160`)}
                    alt={`${form.title} 원본 페이지`}
                    onError={() => setImgError(true)}
                    className="w-full rounded border border-black/[0.06] bg-white"
                  />
                ) : (
                  <div className="space-y-2 p-4 text-xs leading-relaxed text-[#52525b]">
                    <p className="font-semibold text-[#18181b]">원본 서식 텍스트 미리보기</p>
                    <p className="whitespace-pre-wrap">{form.sample_text || '오프라인 상태에서는 원본 이미지 대신 텍스트가 표시됩니다.'}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Sticky Studio Footer */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.07] bg-white px-4 py-3 sm:px-5">
          <span className="text-[11px] text-[#71717a]">
            미리보기에 표시된 내용 그대로 깔끔한 A4 맑은 고딕 Word(.docx) 파일로 저장됩니다
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="chip-nowrap rounded-lg border border-black/[0.1] bg-white px-3.5 py-2 text-xs font-medium text-[#52525b] hover:bg-black/[0.04]"
            >
              닫기
            </button>
            <button
              type="button"
              disabled={exporting}
              onClick={() => void handleDownloadDocx()}
              className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#27272a] disabled:opacity-50"
            >
              {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              <span>작성본 Word(.docx) 저장</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
