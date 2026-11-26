import React, { useState } from 'react';
import {
  FileText,
  FolderKanban,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Stamp,
  Trash2,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { StdApprovalPreset, StdCategoryItem, StdConfig, StdPdfTemplate } from '../types';

interface Props {
  config: StdConfig;
  onSaved: (next: StdConfig) => void;
  onClose: () => void;
}

type TabId = 'categories' | 'approvals' | 'cover';

const ACCENT_SWATCHES = [
  { hex: '#0f4c81', label: '교회 네이비' },
  { hex: '#18181b', label: '차콜 블랙' },
  { hex: '#14532d', label: '딥 포레스트' },
  { hex: '#7f1d1d', label: '버건디' },
  { hex: '#1d4ed8', label: '로열 블루' },
];

export const StdConfigModal: React.FC<Props> = ({ config, onSaved, onClose }) => {
  const [tab, setTab] = useState<TabId>('categories');
  const [categories, setCategories] = useState<StdCategoryItem[]>(() =>
    config.categories.map((c) => ({ ...c, keywords: [...c.keywords] }))
  );
  const [workTypes, setWorkTypes] = useState<string[]>(() => [...config.work_types]);
  const [newWorkType, setNewWorkType] = useState('');
  const [presets, setPresets] = useState<StdApprovalPreset[]>(() =>
    config.approval_presets.map((p) => ({ ...p, slots: [...p.slots] }))
  );
  const [tpl, setTpl] = useState<StdPdfTemplate>(() => ({ ...config.pdf_template }));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const handleSave = async () => {
    setSaving(true);
    setErr('');
    try {
      const saved = await api.stdSaveConfig({
        categories: categories.filter((c) => c.name.trim()),
        work_types: workTypes.filter((w) => w.trim()),
        approval_presets: presets.filter((p) => p.name.trim() && p.slots.some((s) => s.trim())),
        pdf_template: tpl,
      });
      onSaved(saved);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '규격 설정 저장 실패');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm('목포사랑의교회 2025년 시행세칙 기본 분류(12개)와 위임전결 결재선 기본값으로 복원할까요?')) {
      return;
    }
    setSaving(true);
    setErr('');
    try {
      const def = await api.stdResetConfig();
      onSaved(def);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '기본값 복원 실패');
    } finally {
      setSaving(false);
    }
  };

  const previewPreset =
    presets.find((p) => p.id === tpl.default_approval_preset_id) || presets[0] || {
      id: 'default',
      name: '부서 기본 결재선',
      slots: ['총무', '부장', '지도교역자', '당회장'],
      basis: '',
    };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div>
            <h3 className="text-sm font-semibold text-[#18181b]">
              목포사랑의교회 표준화실 규격 · 결재선 · PDF 표지 맞춤 설정
            </h3>
            <p className="text-[11px] text-[#71717a]">
              2025년 사랑의교회 시행세칙(제53조 10개 부서 · 제11장 위임전결규정)을 기본값으로 하며, 교회 실정에 맞게 자유롭게 편집할 수 있습니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-lg p-1.5 text-[#71717a] hover:bg-black/[0.06]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Sub-Tabs */}
        <div className="flex gap-1 overflow-x-auto border-b border-black/[0.07] bg-[#f7f7f5] px-4 pt-2">
          <button
            type="button"
            onClick={() => setTab('categories')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'categories' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <FolderKanban className="h-3.5 w-3.5" />
            <span>분류 · 부서 체계 ({categories.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('approvals')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'approvals' ? 'border-[#0f4c81] text-[#0f4c81]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <Stamp className="h-3.5 w-3.5" />
            <span>교회 결재선 양식 ({presets.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('cover')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'cover' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <FileText className="h-3.5 w-3.5" />
            <span>PDF 표지 · 서식 양식</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {err && (
            <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2 text-xs text-red-700">
              {err}
            </div>
          )}

          {tab === 'categories' ? (
            <div className="space-y-5">
              <div className="space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <h4 className="text-xs font-semibold text-[#18181b]">교회 부서 · 행정 분류 목록</h4>
                    <p className="text-[11px] text-[#71717a]">
                      게시글 개설 선택지, AI 교차 분류 자동 감지 키워드, PDF 편찬 시 기본 결재선에 즉시 반영됩니다.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setCategories([
                        ...categories,
                        {
                          name: '',
                          keywords: [],
                          approval_preset_id: presets[0]?.id || 'dept_standard',
                        },
                      ])
                    }
                    className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-[#27272a]"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    <span>분류 추가</span>
                  </button>
                </div>

                <div className="space-y-2">
                  {categories.map((cat, idx) => (
                    <div
                      key={idx}
                      className="grid grid-cols-1 gap-2 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3 sm:grid-cols-12 sm:items-center"
                    >
                      <div className="sm:col-span-3">
                        <label className="mb-0.5 block text-[10px] font-medium text-[#71717a]">분류 · 부서명</label>
                        <input
                          type="text"
                          value={cat.name}
                          onChange={(e) =>
                            setCategories(
                              categories.map((c, i) => (i === idx ? { ...c, name: e.target.value } : c))
                            )
                          }
                          placeholder="예: 예배선교부"
                          className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs font-semibold text-[#18181b]"
                        />
                      </div>
                      <div className="sm:col-span-3">
                        <label className="mb-0.5 block text-[10px] font-medium text-[#71717a]">자동 적용 결재선</label>
                        <select
                          value={cat.approval_preset_id}
                          onChange={(e) =>
                            setCategories(
                              categories.map((c, i) =>
                                i === idx ? { ...c, approval_preset_id: e.target.value } : c
                              )
                            )
                          }
                          className="w-full rounded-lg border border-black/[0.1] bg-white px-2 py-1.5 text-xs"
                        >
                          {presets.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="sm:col-span-5">
                        <label className="mb-0.5 block text-[10px] font-medium text-[#71717a]">
                          AI 교차 분류 감지 키워드 (쉼표 구분)
                        </label>
                        <input
                          type="text"
                          value={cat.keywords.join(', ')}
                          onChange={(e) =>
                            setCategories(
                              categories.map((c, i) =>
                                i === idx
                                  ? {
                                      ...c,
                                      keywords: e.target.value
                                        .split(',')
                                        .map((k) => k.trim())
                                        .filter(Boolean),
                                    }
                                  : c
                              )
                            )
                          }
                          placeholder="예배, 성찬, 찬양, 주보..."
                          className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-[#3f3f46]"
                        />
                      </div>
                      <div className="flex justify-end sm:col-span-1">
                        <button
                          type="button"
                          disabled={categories.length <= 1}
                          onClick={() => setCategories(categories.filter((_, i) => i !== idx))}
                          title="분류 삭제"
                          className="rounded-lg p-1.5 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Work Type Presets */}
              <div className="space-y-2 rounded-xl border border-black/[0.08] p-4">
                <h4 className="text-xs font-semibold text-[#18181b]">표준화 작업 형태 목록</h4>
                <div className="flex flex-wrap gap-1.5">
                  {workTypes.map((wt, i) => (
                    <span
                      key={i}
                      className="chip-nowrap inline-flex items-center gap-1 rounded-full border border-black/[0.1] bg-[#f7f7f5] px-2.5 py-1 text-[11px] font-medium text-[#18181b]"
                    >
                      <span>{wt}</span>
                      {workTypes.length > 1 && (
                        <button
                          type="button"
                          onClick={() => setWorkTypes(workTypes.filter((_, idx) => idx !== i))}
                          className="text-[#8a8a8e] hover:text-red-600"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <input
                    type="text"
                    value={newWorkType}
                    onChange={(e) => setNewWorkType(e.target.value)}
                    placeholder="새 작업 형태 추가 (예: 교역자 사역 지침서)"
                    className="min-w-0 flex-1 rounded-lg border border-black/[0.1] px-3 py-1.5 text-xs"
                  />
                  <button
                    type="button"
                    disabled={!newWorkType.trim()}
                    onClick={() => {
                      if (newWorkType.trim() && !workTypes.includes(newWorkType.trim())) {
                        setWorkTypes([...workTypes, newWorkType.trim()]);
                        setNewWorkType('');
                      }
                    }}
                    className="chip-nowrap rounded-lg bg-[#18181b] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                  >
                    추가
                  </button>
                </div>
              </div>
            </div>
          ) : tab === 'approvals' ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h4 className="text-xs font-semibold text-[#18181b]">교회 실제 결재선 프리셋</h4>
                  <p className="text-[11px] text-[#71717a]">
                    결재 칸은 쉼표(,)로 구분해 최대 7단계까지 자유롭게 구성할 수 있습니다. (예: 총무, 부장, 지도교역자, 당회장)
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setPresets([
                      ...presets,
                      {
                        id: `custom_${Date.now().toString(36).slice(-4)}`,
                        name: '새 사용자 결재선',
                        slots: ['기안', '부서장', '당회장'],
                        basis: '교회 행정 결재 기준',
                      },
                    ])
                  }
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#0f4c81] px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-[#0c3d68]"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>결재선 추가</span>
                </button>
              </div>

              <div className="space-y-3">
                {presets.map((p, idx) => (
                  <div key={p.id} className="space-y-3 rounded-xl border border-black/[0.08] bg-white p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-1 items-center gap-2">
                        <input
                          type="text"
                          value={p.name}
                          onChange={(e) =>
                            setPresets(presets.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                          }
                          className="min-w-0 flex-1 rounded-lg border border-black/[0.1] px-2.5 py-1.5 text-xs font-semibold text-[#18181b]"
                        />
                        <label className="chip-nowrap inline-flex cursor-pointer items-center gap-1.5 text-[11px] font-medium text-[#52525b]">
                          <input
                            type="radio"
                            name="default_ap_preset"
                            checked={tpl.default_approval_preset_id === p.id}
                            onChange={() => setTpl({ ...tpl, default_approval_preset_id: p.id })}
                            className="accent-[#0f4c81]"
                          />
                          <span>기본 결재선</span>
                        </label>
                      </div>
                      {presets.length > 1 && (
                        <button
                          type="button"
                          onClick={() => setPresets(presets.filter((_, i) => i !== idx))}
                          className="rounded-lg p-1.5 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                      <div>
                        <label className="mb-1 block text-[11px] font-medium text-[#52525b]">
                          결재 단계 (쉼표로 구분 · 왼쪽→오른쪽 순서)
                        </label>
                        <input
                          type="text"
                          value={p.slots.join(', ')}
                          onChange={(e) =>
                            setPresets(
                              presets.map((x, i) =>
                                i === idx
                                  ? {
                                      ...x,
                                      slots: e.target.value
                                        .split(',')
                                        .map((s) => s.trim())
                                        .filter(Boolean)
                                        .slice(0, 7),
                                    }
                                  : x
                              )
                            )
                          }
                          placeholder="총무, 부장, 지도교역자, 당회장"
                          className="w-full rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1.5 text-xs"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] font-medium text-[#52525b]">근거 규정 표기</label>
                        <input
                          type="text"
                          value={p.basis}
                          onChange={(e) =>
                            setPresets(presets.map((x, i) => (i === idx ? { ...x, basis: e.target.value } : x)))
                          }
                          placeholder="예: 시행세칙 제11장 위임전결규정 제127조 [별표]"
                          className="w-full rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1.5 text-xs"
                        />
                      </div>
                    </div>

                    {/* Live Authentic Korean Approval Box Preview */}
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[#fafaf9] px-3 py-2">
                      <span className="text-[11px] text-[#71717a]">PDF·Word 결재란 미리보기</span>
                      <table className="border-collapse bg-white text-[11px]">
                        <tbody>
                          <tr>
                            <th
                              rowSpan={2}
                              className="border border-zinc-500 bg-[#ecece9] px-1.5 py-1 text-center font-bold leading-tight text-[#18181b]"
                            >
                              결<br />재
                            </th>
                            {(p.slots.length ? p.slots : ['담당']).map((s, si) => (
                              <th
                                key={si}
                                className="min-w-[52px] border border-zinc-500 bg-[#f4f4f2] px-2 py-1 text-center font-semibold text-[#18181b]"
                              >
                                {s}
                              </th>
                            ))}
                          </tr>
                          <tr>
                            {(p.slots.length ? p.slots : ['담당']).map((_, si) => (
                              <td key={si} className="h-8 border border-zinc-500" />
                            ))}
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Live Mini Cover Preview */}
              <div
                data-paper="a4"
                className="rounded-xl border border-black/[0.1] bg-white p-4 shadow-xs"
                style={{ borderLeft: `8px solid ${tpl.accent_color}` }}
              >
                <div className="flex items-center justify-between border-b border-black/[0.08] pb-2 text-[11px] text-[#52525b]">
                  <span>{tpl.denomination_header}</span>
                  <span className="rounded bg-[#18181b] px-2 py-0.5 text-[10px] font-bold text-white">v1.0</span>
                </div>
                <div className="flex flex-wrap items-end justify-between gap-3 py-4">
                  <div>
                    <p className="text-[10.5px] font-bold" style={{ color: tpl.accent_color }}>
                      예배선교부 · 규정·서식 표준화
                    </p>
                    <h4 className="mt-0.5 text-lg font-extrabold text-[#18181b]">
                      {tpl.church_name} 공식 행정 표준 규정집 (표지 미리보기)
                    </h4>
                  </div>
                  {tpl.show_cover_approval_box && (
                    <table className="border-collapse bg-white text-[10.5px]">
                      <tbody>
                        <tr>
                          <th
                            rowSpan={2}
                            className="border border-zinc-500 bg-[#ecece9] px-1.5 py-0.5 text-center font-bold leading-tight"
                          >
                            결<br />재
                          </th>
                          {previewPreset.slots.map((s, si) => (
                            <th key={si} className="min-w-[46px] border border-zinc-500 bg-[#f4f4f2] px-2 py-0.5 text-center font-semibold">
                              {s}
                            </th>
                          ))}
                        </tr>
                        <tr>
                          {previewPreset.slots.map((_, si) => (
                            <td key={si} className="h-7 border border-zinc-500" />
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  )}
                </div>
                {tpl.show_delegation_footnote && (
                  <p className="mb-2 text-[10.5px] text-[#71717a]">{tpl.delegation_footnote}</p>
                )}
                <div className="flex items-center justify-between border-t-2 border-[#18181b] pt-2 text-[11px] font-semibold text-[#27272a]">
                  <span>{tpl.footer_left}</span>
                  <span>{tpl.footer_right}</span>
                </div>
              </div>

              {/* Cover & Form Fields Editor */}
              <div className="grid grid-cols-1 gap-3 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">표지 최상단 교단·문서 표기</label>
                  <input
                    type="text"
                    value={tpl.denomination_header}
                    onChange={(e) => setTpl({ ...tpl, denomination_header: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">교회명</label>
                  <input
                    type="text"
                    value={tpl.church_name}
                    onChange={(e) => setTpl({ ...tpl, church_name: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">편찬 위원회·주관 명칭</label>
                  <input
                    type="text"
                    value={tpl.committee_label}
                    onChange={(e) => setTpl({ ...tpl, committee_label: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">표지 하단 좌측 문구</label>
                  <input
                    type="text"
                    value={tpl.footer_left}
                    onChange={(e) => setTpl({ ...tpl, footer_left: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">표지 하단 우측 문구</label>
                  <input
                    type="text"
                    value={tpl.footer_right}
                    onChange={(e) => setTpl({ ...tpl, footer_right: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">표준 서식 기본 수신처</label>
                  <input
                    type="text"
                    value={tpl.default_recipient}
                    onChange={(e) => setTpl({ ...tpl, default_recipient: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">표준 서식 제출 문구</label>
                  <input
                    type="text"
                    value={tpl.default_submit_statement}
                    onChange={(e) => setTpl({ ...tpl, default_submit_statement: e.target.value })}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                  />
                </div>

                {/* Accent Color Swatches */}
                <div className="sm:col-span-2">
                  <label className="mb-1.5 block text-[11px] font-semibold text-[#18181b]">표지 · 장 구분 강조 색상</label>
                  <div className="flex flex-wrap items-center gap-2">
                    {ACCENT_SWATCHES.map((sw) => (
                      <button
                        key={sw.hex}
                        type="button"
                        onClick={() => setTpl({ ...tpl, accent_color: sw.hex })}
                        className={`chip-nowrap inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-medium ${
                          tpl.accent_color === sw.hex
                            ? 'border-[#18181b] bg-white ring-1 ring-[#18181b]'
                            : 'border-black/[0.1] bg-white'
                        }`}
                      >
                        <span className="h-3 w-3 rounded-full" style={{ backgroundColor: sw.hex }} />
                        <span>{sw.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-2 border-t border-black/[0.06] pt-3 sm:col-span-2">
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-[#18181b]">
                    <input
                      type="checkbox"
                      checked={tpl.show_cover_approval_box}
                      onChange={(e) => setTpl({ ...tpl, show_cover_approval_box: e.target.checked })}
                      className="accent-[#18181b]"
                    />
                    <span>PDF 공식 표지에 교회 결재란(결재선 박스) 함께 표시</span>
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-[#18181b]">
                    <input
                      type="checkbox"
                      checked={tpl.show_delegation_footnote}
                      onChange={(e) => setTpl({ ...tpl, show_delegation_footnote: e.target.checked })}
                      className="accent-[#18181b]"
                    />
                    <span>표지·서식 하단에 위임전결 대결 및 부서 합의 주석 표시</span>
                  </label>
                  {tpl.show_delegation_footnote && (
                    <input
                      type="text"
                      value={tpl.delegation_footnote}
                      onChange={(e) => setTpl({ ...tpl, delegation_footnote: e.target.value })}
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs"
                    />
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.08] bg-[#fafaf9] px-5 py-3">
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleReset()}
            className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-medium text-[#52525b] hover:bg-[#f4f4f5]"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span>2025 시행세칙 기본값 복원</span>
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="chip-nowrap rounded-lg px-3.5 py-2 text-xs font-medium text-[#71717a] hover:bg-black/[0.05]"
            >
              취소
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void handleSave()}
              className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              <span>규격 · 결재선 저장</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
