import React, { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, FileText, Image as ImageIcon, Loader2, X } from 'lucide-react';
import { api, safeAssetUrl } from '../api';
import { getOfflinePageText, type OfflineBundle } from '../offlineStore';

interface Props {
  docId: string;
  initialPage: number;
  offlineBundle?: OfflineBundle | null;
  isOfflineMode?: boolean;
  onClose: () => void;
}

export const PageViewerModal: React.FC<Props> = ({
  docId,
  initialPage,
  offlineBundle = null,
  isOfflineMode = false,
  onClose,
}) => {
  const [pageNo, setPageNo] = useState(initialPage);
  const [viewMode, setViewMode] = useState<'image' | 'text'>(isOfflineMode ? 'text' : 'image');
  const [meta, setMeta] = useState<{
    doc_title: string;
    file_type: string;
    page_count: number;
    is_ocr: boolean;
    text: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);

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

  const pageCount = meta?.page_count || pageNo;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-3 sm:p-6">
      <div className="flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-bold text-slate-900">{meta?.doc_title || '원본 페이지 보기'}</h3>
            <p className="text-[11px] text-slate-500">
              {pageNo} / {pageCount}쪽 {meta?.is_ocr ? '· OCR 추출 페이지' : ''}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {meta?.file_type === 'pdf' && (
              <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100 p-0.5">
                <button
                  type="button"
                  onClick={() => setViewMode('image')}
                  className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold ${
                    viewMode === 'image' ? 'bg-white text-[#1e3a5f] shadow-2xs' : 'text-slate-600'
                  }`}
                >
                  <ImageIcon className="h-3 w-3" />
                  <span>원본</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('text')}
                  className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold ${
                    viewMode === 'text' ? 'bg-white text-[#1e3a5f] shadow-2xs' : 'text-slate-600'
                  }`}
                >
                  <FileText className="h-3 w-3" />
                  <span>텍스트</span>
                </button>
              </div>
            )}

            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto bg-slate-100 p-3 sm:p-5">
          {loading ? (
            <div className="flex h-64 items-center justify-center text-slate-500">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : viewMode === 'image' && meta?.file_type === 'pdf' ? (
            <div className="flex justify-center">
              <img
                src={safeAssetUrl(`/api/documents/${encodeURIComponent(docId)}/page/${pageNo}.png?dpi=180`)}
                alt={`${meta.doc_title} ${pageNo}쪽`}
                className="max-w-full rounded-lg border border-slate-300 bg-white shadow-sm"
              />
            </div>
          ) : (
            <div className="mx-auto max-w-2xl rounded-xl border border-slate-200 bg-white p-5 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
              {meta?.text || '추출된 텍스트가 없습니다.'}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-200 bg-white px-4 py-2.5">
          <button
            type="button"
            disabled={pageNo <= 1}
            onClick={() => setPageNo((p) => Math.max(1, p - 1))}
            className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
            <span>이전 쪽</span>
          </button>

          <span className="text-xs font-medium text-slate-600">
            {pageNo} / {pageCount}
          </span>

          <button
            type="button"
            disabled={pageNo >= pageCount}
            onClick={() => setPageNo((p) => Math.min(pageCount, p + 1))}
            className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            <span>다음 쪽</span>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
