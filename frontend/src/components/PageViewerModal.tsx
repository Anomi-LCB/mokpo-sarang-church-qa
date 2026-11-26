import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileText, Highlighter, Image as ImageIcon, Loader2, X } from 'lucide-react';
import { api, safeAssetUrl } from '../api';
import { getOfflinePageText, type OfflineBundle } from '../offlineStore';

interface Props {
  docId: string;
  initialPage: number;
  highlightText?: string;
  offlineBundle?: OfflineBundle | null;
  isOfflineMode?: boolean;
  onClose: () => void;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Extracts meaningful phrases from a citation excerpt so we can accurately highlight
 * the cited clause even when PDF OCR has minor line-break differences.
 */
function buildHighlightRegex(excerpt: string): RegExp | null {
  const cleaned = excerpt
    .replace(/\.\.\./g, ' ')
    .replace(/[•·※▪■◆●]/g, ' ')
    .trim();
  if (!cleaned) return null;

  const rawLines = cleaned
    .split(/[\n\r]+|(?<=[.?!다])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 6);

  const candidates: string[] = [];
  for (const ln of rawLines) {
    if (ln.length <= 72) {
      candidates.push(ln);
    } else {
      // Take sliding chunks of up to 48 chars so line wraps don't prevent matches
      const words = ln.split(/\s+/).filter(Boolean);
      let chunk = '';
      for (const w of words) {
        if ((chunk + ' ' + w).trim().length > 42 && chunk.length >= 10) {
          candidates.push(chunk.trim());
          chunk = w;
        } else {
          chunk = (chunk + ' ' + w).trim();
        }
      }
      if (chunk.length >= 6) candidates.push(chunk.trim());
    }
    if (candidates.length >= 10) break;
  }

  // Fallback to individual distinctive Korean/numeric tokens >= 3 chars if needed
  if (candidates.length === 0 && cleaned.length >= 4) {
    candidates.push(cleaned.slice(0, 60));
  }

  const patterns = candidates
    .sort((a, b) => b.length - a.length)
    .slice(0, 8)
    .map((phrase) =>
      phrase
        .split(/\s+/)
        .filter(Boolean)
        .map(escapeRegExp)
        .join('\\s+')
    )
    .filter(Boolean);

  if (patterns.length === 0) return null;
  try {
    return new RegExp(`(${patterns.join('|')})`, 'gi');
  } catch {
    return null;
  }
}

export const PageViewerModal: React.FC<Props> = ({
  docId,
  initialPage,
  highlightText = '',
  offlineBundle = null,
  isOfflineMode = false,
  onClose,
}) => {
  const hasHighlight = Boolean(highlightText && highlightText.trim().length >= 4);
  const [pageNo, setPageNo] = useState(initialPage);
  const [viewMode, setViewMode] = useState<'image' | 'text'>(
    isOfflineMode || hasHighlight ? 'text' : 'image'
  );
  const [meta, setMeta] = useState<{
    doc_title: string;
    file_type: string;
    page_count: number;
    is_ocr: boolean;
    text: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const textBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    if (isOfflineMode && offlineBundle) {
      const localMeta = getOfflinePageText(offlineBundle, docId, pageNo);
      setMeta(localMeta);
      setViewMode('text');
      setLoading(false);
      return;
    }
    api
      .getPageText(docId, pageNo)
      .then((res) => {
        if (!active) return;
        setMeta(res);
        if (res.file_type !== 'pdf') {
          setViewMode('text');
        }
      })
      .catch(() => {
        if (!active || !offlineBundle) return;
        const localMeta = getOfflinePageText(offlineBundle, docId, pageNo);
        if (localMeta) {
          setMeta(localMeta);
          setViewMode('text');
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [docId, pageNo, isOfflineMode, offlineBundle]);

  const activeHighlight = pageNo === initialPage && hasHighlight ? highlightText.trim() : '';

  const highlightedNodes = useMemo(() => {
    const rawText = meta?.text || '';
    if (!rawText) return { nodes: null as React.ReactNode, matchCount: 0 };
    if (!activeHighlight) return { nodes: rawText, matchCount: 0 };

    const regex = buildHighlightRegex(activeHighlight);
    if (!regex) return { nodes: rawText, matchCount: 0 };

    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let matchCount = 0;
    let m: RegExpExecArray | null;
    regex.lastIndex = 0;
    while ((m = regex.exec(rawText)) !== null) {
      if (m[0].length === 0) {
        regex.lastIndex += 1;
        continue;
      }
      if (m.index > lastIndex) {
        parts.push(rawText.slice(lastIndex, m.index));
      }
      matchCount += 1;
      parts.push(
        <mark
          key={`hl_${m.index}_${matchCount}`}
          data-cite-hit={matchCount === 1 ? '1' : undefined}
          className="rounded bg-amber-200/90 px-0.5 font-medium text-[#18181b] ring-1 ring-amber-300/80"
        >
          {m[0]}
        </mark>
      );
      lastIndex = m.index + m[0].length;
      if (matchCount >= 40) break;
    }
    if (lastIndex < rawText.length) {
      parts.push(rawText.slice(lastIndex));
    }
    return { nodes: matchCount > 0 ? parts : rawText, matchCount };
  }, [meta?.text, activeHighlight]);

  useEffect(() => {
    if (viewMode === 'text' && highlightedNodes.matchCount > 0 && textBoxRef.current) {
      const hit = textBoxRef.current.querySelector('[data-cite-hit="1"]');
      if (hit) {
        hit.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [viewMode, highlightedNodes.matchCount, pageNo]);

  const pageCount = meta?.page_count || pageNo;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 backdrop-blur-xs sm:p-6"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.07] px-4 py-3">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-[#18181b]">{meta?.doc_title || '원본 페이지 보기'}</h3>
            <p className="text-[11px] text-[#71717a]">
              {pageNo} / {pageCount}쪽 {meta?.is_ocr ? '· OCR 추출 페이지' : ''}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {meta?.file_type === 'pdf' && (
              <div className="inline-flex rounded-lg bg-[#f0f0ee] p-0.5">
                <button
                  type="button"
                  onClick={() => setViewMode('image')}
                  className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                    viewMode === 'image' ? 'bg-white text-[#18181b] shadow-2xs' : 'text-[#71717a] hover:text-[#18181b]'
                  }`}
                >
                  <ImageIcon className="h-3 w-3" />
                  <span>원본 스캔</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('text')}
                  className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                    viewMode === 'text' ? 'bg-white text-[#0f4c81] shadow-2xs' : 'text-[#71717a] hover:text-[#18181b]'
                  }`}
                >
                  <FileText className="h-3 w-3" />
                  <span>{activeHighlight ? '원문 하이라이트' : '텍스트'}</span>
                </button>
              </div>
            )}

            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="rounded-lg p-1.5 text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Cited Excerpt Callout Banner */}
        {activeHighlight && (
          <div className="flex items-start justify-between gap-3 border-b border-amber-200/80 bg-amber-50/85 px-4 py-2.5">
            <div className="flex min-w-0 flex-1 items-start gap-2">
              <Highlighter className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700" />
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold text-amber-900">
                  인용 근거 구절 {highlightedNodes.matchCount > 0 ? `(본문 내 ${highlightedNodes.matchCount}곳 자동 강조)` : '(이 페이지 발췌)'}
                </p>
                <p className="mt-0.5 line-clamp-2 text-[11.5px] leading-relaxed text-amber-950/90">
                  {activeHighlight}
                </p>
              </div>
            </div>
            {meta?.file_type === 'pdf' && (
              <button
                type="button"
                onClick={() => setViewMode(viewMode === 'text' ? 'image' : 'text')}
                className="chip-nowrap shrink-0 rounded-md border border-amber-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-amber-900 hover:bg-amber-50"
              >
                {viewMode === 'text' ? '원본 스캔 보기' : '하이라이트 보기'}
              </button>
            )}
          </div>
        )}

        <div className="flex-1 overflow-auto bg-[#f4f4f2] p-3 sm:p-5">
          {loading ? (
            <div className="flex h-64 items-center justify-center text-[#71717a]">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : viewMode === 'image' && meta?.file_type === 'pdf' ? (
            <div className="flex justify-center">
              <img
                src={safeAssetUrl(`/api/documents/${encodeURIComponent(docId)}/page/${pageNo}.png?dpi=180`)}
                alt={`${meta.doc_title} ${pageNo}쪽`}
                className="max-w-full rounded-lg border border-black/[0.1] bg-white shadow-sm"
              />
            </div>
          ) : (
            <div
              ref={textBoxRef}
              className="mx-auto max-w-2xl rounded-xl border border-black/[0.08] bg-white p-5 whitespace-pre-wrap text-[13.5px] leading-7 text-[#27272a]"
            >
              {highlightedNodes.nodes || '추출된 텍스트가 없습니다.'}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-black/[0.07] bg-white px-4 py-2.5">
          <button
            type="button"
            disabled={pageNo <= 1}
            onClick={() => setPageNo((p) => Math.max(1, p - 1))}
            className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] px-3 py-1.5 text-xs font-semibold text-[#3f3f46] hover:bg-[#f7f7f5] disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
            <span>이전 쪽</span>
          </button>

          <span className="text-xs font-medium text-[#52525b]">
            {pageNo} / {pageCount}
          </span>

          <button
            type="button"
            disabled={pageNo >= pageCount}
            onClick={() => setPageNo((p) => Math.min(pageCount, p + 1))}
            className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] px-3 py-1.5 text-xs font-semibold text-[#3f3f46] hover:bg-[#f7f7f5] disabled:opacity-40"
          >
            <span>다음 쪽</span>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
