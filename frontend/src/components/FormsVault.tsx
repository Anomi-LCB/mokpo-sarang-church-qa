import React, { memo, useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  ChevronRight,
  Download,
  Eye,
  FileEdit,
  FileSpreadsheet,
  FileText,
  FileType2,
  Search,
  Table,
  X,
} from 'lucide-react';
import { triggerTicketDownload } from '../api';
import type { FormItem } from '../types';

interface Props {
  forms: FormItem[];
  onOpenViewer: (docId: string, pageNo: number) => void;
  onOpenAutofill: (form: FormItem) => void;
}

const FormRow = memo<{
  form: FormItem;
  isActive: boolean;
  onToggleActive: (id: string) => void;
  onCloseActive: () => void;
  onOpenViewer: (docId: string, pageNo: number) => void;
  onOpenAutofill: (form: FormItem) => void;
}>(({ form: f, isActive, onToggleActive, onCloseActive, onOpenViewer, onOpenAutofill }) => (
  <div
    data-form-card={f.id}
    className={`cv-auto relative transition-colors ${isActive ? 'z-20 py-1.5' : 'py-1'}`}
  >
    {/* Clean Resting Form Card (Click anywhere to open 5-action frosted overlay) */}
    <div
      role="button"
      tabIndex={0}
      aria-expanded={isActive}
      onClick={(e) => {
        e.stopPropagation();
        onToggleActive(f.id);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onToggleActive(f.id);
        }
      }}
      title="클릭하여 작성·미리보기 및 파일 다운로드 메뉴 열기"
      className={`group flex cursor-pointer items-center justify-between gap-2 rounded-xl px-2 py-2.5 transition outline-none focus-visible:ring-1 focus-visible:ring-[#0f4c81] ${
        isActive
          ? 'bg-white/60 opacity-30'
          : 'hover:bg-white hover:shadow-[0_1px_3px_rgba(0,0,0,0.05)]'
      }`}
    >
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <div className="mt-0.5 shrink-0 text-[#71717a] group-hover:text-[#0f4c81]">
          {f.form_type === 'table' ? (
            <Table className="h-3.5 w-3.5" strokeWidth={1.8} />
          ) : (
            <FileText className="h-3.5 w-3.5" strokeWidth={1.8} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[12.5px] font-medium text-[#18181b]">{f.title}</h3>
          <p className="mt-0.5 truncate text-[10.5px] text-[#8a8a8e]">
            {f.doc_title} · p.{f.page_start}
          </p>
        </div>
      </div>

      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#a1a1aa] transition group-hover:translate-x-0.5 group-hover:text-[#0f4c81]" />
    </div>

    {/* Frosted Translucent 5-Action Overlay on Click */}
    {isActive && (
      <div
        data-form-overlay={f.id}
        onClick={(e) => e.stopPropagation()}
        className="form-glass-overlay -mt-12 relative z-20 space-y-2 rounded-xl p-2.5"
      >
        <div className="flex items-center justify-between gap-1.5">
          <p className="min-w-0 flex-1 truncate text-[11.5px] font-semibold text-[#18181b]">
            {f.title}
          </p>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => {
                onCloseActive();
                onOpenViewer(f.doc_id, f.page_start);
              }}
              title="원본 PDF 페이지 보기"
              aria-label="원본 페이지 보기"
              className="rounded-md p-1 text-[#52525b] transition hover:bg-black/[0.06] hover:text-[#18181b]"
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onCloseActive}
              title="메뉴 닫기"
              aria-label="서식 메뉴 닫기"
              className="rounded-md p-1 text-[#52525b] transition hover:bg-black/[0.06] hover:text-[#18181b]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Row 1: Primary 2 actions */}
        <div className="grid grid-cols-2 gap-1.5">
          <button
            type="button"
            onClick={() => {
              onCloseActive();
              onOpenAutofill(f);
            }}
            title="서식 항목 입력 및 실시간 A4 미리보기"
            className="chip-nowrap inline-flex items-center justify-center gap-1 rounded-lg bg-[#18181b] px-2 py-1.5 text-[11px] font-semibold text-white transition hover:bg-[#27272a]"
          >
            <FileEdit className="h-3 w-3 shrink-0" />
            <span>작성·미리보기</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onCloseActive();
              void triggerTicketDownload(`/api/forms/${f.id}/download/pdf`, `${f.title}.pdf`);
            }}
            title="원본 서식 PDF 다운로드"
            className="chip-nowrap inline-flex items-center justify-center gap-1 rounded-lg border border-black/[0.12] bg-white px-2 py-1.5 text-[11px] font-semibold text-[#18181b] transition hover:bg-[#f7f7f5]"
          >
            <Download className="h-3 w-3 shrink-0 text-[#0f4c81]" />
            <span>PDF 다운</span>
          </button>
        </div>

        {/* Row 2: Editable format exports (DOCX · HWPX · XLSX) */}
        <div className="grid grid-cols-3 gap-1.5">
          <button
            type="button"
            onClick={() => {
              onCloseActive();
              void triggerTicketDownload(`/api/forms/${f.id}/download/docx`, `${f.title}.docx`);
            }}
            title="편집용 워드(DOCX) 파일 다운로드"
            className="chip-nowrap inline-flex items-center justify-center gap-1 rounded-lg border border-black/[0.1] bg-white/95 px-1.5 py-1.5 text-[10.5px] font-semibold text-[#3f3f46] transition hover:border-[#0f4c81]/40 hover:text-[#0f4c81]"
          >
            <FileText className="h-3 w-3 shrink-0" />
            <span>DOCX</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onCloseActive();
              void triggerTicketDownload(`/api/forms/${f.id}/download/hwpx`, `${f.title}.hwpx`);
            }}
            title="한컴 한글(HWPX) 편집 서식 다운로드"
            className="chip-nowrap inline-flex items-center justify-center gap-1 rounded-lg border border-black/[0.1] bg-white/95 px-1.5 py-1.5 text-[10.5px] font-semibold text-[#3f3f46] transition hover:border-[#0f4c81]/40 hover:text-[#0f4c81]"
          >
            <FileType2 className="h-3 w-3 shrink-0" />
            <span>HWPX</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onCloseActive();
              void triggerTicketDownload(`/api/forms/${f.id}/download/xlsx`, `${f.title}.xlsx`);
            }}
            title="엑셀(XLSX) 표 파일 다운로드"
            className="chip-nowrap inline-flex items-center justify-center gap-1 rounded-lg border border-black/[0.1] bg-white/95 px-1.5 py-1.5 text-[10.5px] font-semibold text-[#3f3f46] transition hover:border-[#0f4c81]/40 hover:text-[#0f4c81]"
          >
            <FileSpreadsheet className="h-3 w-3 shrink-0" />
            <span>XLSX</span>
          </button>
        </div>
      </div>
    )}
  </div>
));
FormRow.displayName = 'FormRow';

export const FormsVault: React.FC<Props> = memo(({ forms, onOpenViewer, onOpenAutofill }) => {
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [category, setCategory] = useState('전체');
  const [activeFormId, setActiveFormId] = useState<string | null>(null);

  useEffect(() => {
    if (!activeFormId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActiveFormId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeFormId]);

  const categories = useMemo(() => {
    const set = new Set<string>(['전체']);
    forms.forEach((f) => set.add(f.category));
    return Array.from(set);
  }, [forms]);

  const filtered = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase();
    return forms.filter((f) => {
      if (category !== '전체' && f.category !== category) return false;
      if (!q) return true;
      return (
        f.title.toLowerCase().includes(q) ||
        f.category.toLowerCase().includes(q) ||
        f.doc_title.toLowerCase().includes(q) ||
        (f.sample_text || '').toLowerCase().includes(q)
      );
    });
  }, [forms, deferredQuery, category]);

  return (
    <div
      className="flex h-full min-h-0 flex-col bg-[#fafaf9]"
      onClick={() => {
        if (activeFormId) setActiveFormId(null);
      }}
    >
      <div className="space-y-2.5 border-b border-black/[0.07] px-3.5 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <h2 className="text-[12px] font-semibold tracking-tight text-[#18181b]">서식 · 표</h2>
            <span className="chip-nowrap text-[11px] font-medium text-[#8a8a8e]">{filtered.length}</span>
          </div>
          <span className="chip-nowrap text-[10.5px] text-[#8a8a8e]">클릭해서 선택</span>
        </div>

        {/* Quiet minimal search */}
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[#a1a1aa]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="서식 검색..."
            className="w-full rounded-lg border border-black/[0.07] bg-white py-1.5 pr-3 pl-8 text-[16px] text-[#18181b] placeholder-[#a1a1aa] outline-none transition focus:border-[#18181b]/40 lg:text-xs"
          />
        </div>

        <div className="flex gap-1 overflow-x-auto pb-0.5">
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => {
                setCategory(cat);
                setActiveFormId(null);
              }}
              className={`chip-nowrap rounded-md px-2 py-1 text-[11px] font-medium transition ${
                category === cat
                  ? 'bg-[#18181b] text-white'
                  : 'text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Calm hairline list with click-to-reveal frosted 5-button overlay */}
      <div className="flex-1 divide-y divide-black/[0.06] overflow-y-auto px-2 py-1">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-xs text-[#8a8a8e]">검색 결과와 일치하는 서식이 없습니다.</div>
        ) : (
          filtered.map((f) => (
            <FormRow
              key={f.id}
              form={f}
              isActive={activeFormId === f.id}
              onToggleActive={(id) => {
                setActiveFormId((prev) => (prev === id ? null : id));
              }}
              onCloseActive={() => setActiveFormId(null)}
              onOpenViewer={onOpenViewer}
              onOpenAutofill={onOpenAutofill}
            />
          ))
        )}
      </div>
    </div>
  );
});
FormsVault.displayName = 'FormsVault';
