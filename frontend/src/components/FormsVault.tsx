import React, { memo, useDeferredValue, useMemo, useState } from 'react';
import {
  Download,
  Eye,
  FileEdit,
  FileSpreadsheet,
  FileText,
  Search,
  Table,
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
  onOpenViewer: (docId: string, pageNo: number) => void;
  onOpenAutofill: (form: FormItem) => void;
}>(({ form: f, onOpenViewer, onOpenAutofill }) => (
  <div className="cv-auto group px-1.5 py-2.5 transition-colors hover:bg-white">
    <div className="flex items-start justify-between gap-2">
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

      <button
        type="button"
        onClick={() => onOpenViewer(f.doc_id, f.page_start)}
        title="원본 페이지 미리보기"
        aria-label={`${f.title} 원본 미리보기`}
        className="mac-hover-reveal shrink-0 rounded p-1 text-[#71717a] transition hover:bg-black/[0.06] hover:text-[#18181b]"
      >
        <Eye className="h-3.5 w-3.5" />
      </button>
    </div>

    <div className="mt-2 flex flex-wrap items-center justify-between gap-x-1.5 gap-y-1.5 pl-4 pr-1">
      <div className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          onClick={() => onOpenAutofill(f)}
          className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.1] bg-white px-2 py-0.5 text-[11px] font-semibold text-[#18181b] transition hover:border-[#18181b] hover:bg-[#18181b] hover:text-white"
        >
          <FileEdit className="h-3 w-3 shrink-0" />
          <span>작성 · 미리보기</span>
        </button>
        <button
          type="button"
          onClick={() => void triggerTicketDownload(`/api/forms/${f.id}/download/pdf`, `${f.title}.pdf`)}
          className="chip-nowrap inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
        >
          <Download className="h-3 w-3 shrink-0" />
          <span>PDF</span>
        </button>
      </div>

      <div className="mac-hover-reveal flex flex-wrap items-center gap-0.5">
        <button
          type="button"
          onClick={() => void triggerTicketDownload(`/api/forms/${f.id}/download/docx`, `${f.title}.docx`)}
          title="편집용 워드(DOCX) 다운로드"
          className="chip-nowrap inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10.5px] font-medium text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b]"
        >
          <FileText className="h-3 w-3 shrink-0" />
          <span>DOCX</span>
        </button>
        <button
          type="button"
          onClick={() => void triggerTicketDownload(`/api/forms/${f.id}/download/xlsx`, `${f.title}.xlsx`)}
          title="엑셀(XLSX) 표 다운로드"
          className="chip-nowrap inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10.5px] font-medium text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b]"
        >
          <FileSpreadsheet className="h-3 w-3 shrink-0" />
          <span>XLSX</span>
        </button>
      </div>
    </div>
  </div>
));
FormRow.displayName = 'FormRow';

export const FormsVault: React.FC<Props> = memo(({ forms, onOpenViewer, onOpenAutofill }) => {
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [category, setCategory] = useState('전체');

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
    <div className="flex h-full min-h-0 flex-col bg-[#fafaf9]">
      <div className="space-y-2.5 border-b border-black/[0.07] px-3.5 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <h2 className="text-[12px] font-semibold tracking-tight text-[#18181b]">서식 · 표</h2>
            <span className="chip-nowrap text-[11px] font-medium text-[#8a8a8e]">{filtered.length}</span>
          </div>
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
              onClick={() => setCategory(cat)}
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

      {/* Calm hairline list with content-visibility virtualization */}
      <div className="flex-1 divide-y divide-black/[0.06] overflow-y-auto px-2.5">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-xs text-[#8a8a8e]">검색 결과와 일치하는 서식이 없습니다.</div>
        ) : (
          filtered.map((f) => (
            <FormRow key={f.id} form={f} onOpenViewer={onOpenViewer} onOpenAutofill={onOpenAutofill} />
          ))
        )}
      </div>
    </div>
  );
});
FormsVault.displayName = 'FormsVault';
