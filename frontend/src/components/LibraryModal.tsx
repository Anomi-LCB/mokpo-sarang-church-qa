import React, { useMemo, useRef, useState } from 'react';
import {
  Check,
  Eye,
  FileSpreadsheet,
  FileText,
  Layers,
  Library,
  Loader2,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { ShelfState } from '../libraryStore';
import type { DocumentItem } from '../types';
import { AdminPinConfirmModal } from './AdminPinConfirmModal';
import { UpdateDocumentModal } from './UpdateDocumentModal';

interface Props {
  notebookId: string;
  documents: DocumentItem[];
  shelf: ShelfState;
  shelfDocIds: Set<string>;
  isAdmin: boolean;
  onToggleUserPin: (docId: string) => void;
  onToggleShelfLoad: (docId: string) => void;
  onBatchLoadToShelf: (docIds: string[], replaceLoaded?: boolean) => void;
  onOpenViewer: (docId: string, pageNo: number) => void;
  onRefresh: () => void;
  onClose: () => void;
}

export const LibraryModal: React.FC<Props> = ({
  notebookId,
  documents,
  shelf,
  shelfDocIds,
  isAdmin,
  onToggleUserPin,
  onToggleShelfLoad,
  onBatchLoadToShelf,
  onOpenViewer,
  onRefresh,
  onClose,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('전체');
  const [sortBy, setSortBy] = useState<'priority' | 'recent' | 'title'>('priority');
  const [uploadState, setUploadState] = useState<{ running: boolean; progress: number; message: string }>({
    running: false,
    progress: 0,
    message: '',
  });
  const [err, setErr] = useState('');
  const [updateTarget, setUpdateTarget] = useState<DocumentItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);
  const [busyDocId, setBusyDocId] = useState('');

  const categories = useMemo(() => {
    const s = new Set<string>(['전체']);
    documents.forEach((d) => s.add(d.category || '일반 자료'));
    return Array.from(s);
  }, [documents]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = documents.filter((d) => {
      if (category !== '전체' && (d.category || '일반 자료') !== category) return false;
      if (!q) return true;
      return (
        d.title.toLowerCase().includes(q) ||
        (d.category || '').toLowerCase().includes(q) ||
        (d.original_filename || '').toLowerCase().includes(q) ||
        (d.tags || []).some((t) => t.toLowerCase().includes(q))
      );
    });
    return [...list].sort((a, b) => {
      if (sortBy === 'title') return a.title.localeCompare(b.title, 'ko');
      if (sortBy === 'recent') return (b.created_at || '').localeCompare(a.created_at || '');
      const pinDiff = Number(Boolean(b.is_pinned_default)) - Number(Boolean(a.is_pinned_default));
      if (pinDiff !== 0) return pinDiff;
      return (b.priority || 0) - (a.priority || 0);
    });
  }, [documents, query, category, sortBy]);

  const handleUploadFiles = async (files: FileList | null) => {
    if (!files || !files.length || !isAdmin) return;
    setErr('');
    setUploadState({ running: true, progress: 8, message: `${files.length}개 파일 서고에 등록 중...` });
    try {
      const { job_id } = await api.uploadDocuments(notebookId, Array.from(files));
      while (true) {
        await new Promise((r) => setTimeout(r, 900));
        const st = await api.getJob(job_id);
        setUploadState({ running: st.status === 'running', progress: st.progress, message: st.message });
        if (st.status === 'done') {
          onRefresh();
          setTimeout(() => setUploadState({ running: false, progress: 0, message: '' }), 1800);
          break;
        }
        if (st.status === 'error') {
          setErr(st.error || '색인 중 오류가 발생했습니다.');
          setUploadState({ running: false, progress: 0, message: '' });
          break;
        }
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '업로드 실패');
      setUploadState({ running: false, progress: 0, message: '' });
    }
  };

  const handleToggleAdminPin = async (doc: DocumentItem) => {
    if (!isAdmin || busyDocId) return;
    setBusyDocId(doc.id);
    try {
      await api.updateDocumentLibrary(doc.id, { is_pinned_default: !doc.is_pinned_default });
      onRefresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '필수 고정 변경 실패');
    } finally {
      setBusyDocId('');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#0f4c81] text-white">
              <Library className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#18181b]">
                전체 자료 라이브러리 (서고 · 총 {documents.length}권)
              </h3>
              <p className="text-[11px] text-[#71717a]">
                자주 쓰는 PDF는 <strong className="text-[#18181b]">고정(Pin)</strong>하고, 필요한 자료만 왼쪽 작업대로{' '}
                <strong className="text-[#18181b]">불러오기 · 내리기</strong>할 수 있습니다(내려도 서고 원본 유지).
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {isAdmin && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.zip,.txt,.md,.docx,.hwpx,.xlsx"
                  className="hidden"
                  onChange={(e) => {
                    void handleUploadFiles(e.target.files);
                    e.target.value = '';
                  }}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#27272a]"
                >
                  <Upload className="h-3.5 w-3.5" />
                  <span>새 자료 추가</span>
                </button>
              </>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="rounded-lg p-1.5 text-[#71717a] hover:bg-black/[0.06]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Search, Category Filter & Bundle Presets */}
        <div className="space-y-2.5 border-b border-black/[0.07] bg-white px-5 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[200px] flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-[#a1a1aa]" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="문서 제목, 분류, 파일명, 태그로 검색..."
                className="w-full rounded-lg border border-black/[0.1] bg-[#fafaf9] py-2 pr-3 pl-8.5 text-xs text-[#18181b] outline-none focus:border-[#18181b] focus:bg-white"
              />
            </div>

            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as 'priority' | 'recent' | 'title')}
              className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-xs text-[#3f3f46]"
            >
              <option value="priority">중요도 · 고정 우선</option>
              <option value="recent">최신 등록순</option>
              <option value="title">가나다순</option>
            </select>

            <button
              type="button"
              onClick={() => onBatchLoadToShelf(filtered.map((d) => d.id), false)}
              disabled={filtered.length === 0}
              className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-[#0f4c81]/30 bg-[#0f4c81]/[0.06] px-2.5 py-2 text-xs font-semibold text-[#0f4c81] hover:bg-[#0f4c81]/[0.12] disabled:opacity-40"
            >
              <Layers className="h-3.5 w-3.5" />
              <span>현재 목록 작업대로 불러오기 ({filtered.length})</span>
            </button>

            <button
              type="button"
              onClick={() => onBatchLoadToShelf([], true)}
              title="필수 고정 문서만 남기고 나머지 임시 불러온 문서를 작업대에서 내립니다"
              className="chip-nowrap rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-xs font-medium text-[#52525b] hover:bg-[#f7f7f5]"
            >
              고정 문서만 남기기
            </button>
          </div>

          <div className="flex gap-1 overflow-x-auto pb-0.5">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setCategory(cat)}
                className={`chip-nowrap rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                  category === cat
                    ? 'bg-[#18181b] text-white'
                    : 'bg-[#f7f7f5] text-[#52525b] hover:bg-[#ededeb]'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>

          {(uploadState.message || err) && (
            <div className="space-y-1.5">
              {uploadState.message && (
                <div className="flex items-center gap-2 rounded-lg border border-black/[0.08] bg-[#fafaf9] px-3 py-2 text-xs text-[#18181b]">
                  {uploadState.running && <Loader2 className="h-3.5 w-3.5 animate-spin text-[#0f4c81]" />}
                  <span className="flex-1">{uploadState.message}</span>
                  <span className="font-semibold text-[#0f4c81]">{uploadState.progress}%</span>
                </div>
              )}
              {err && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-700">{err}</div>
              )}
            </div>
          )}
        </div>

        {/* Document List */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5">
          {filtered.length === 0 ? (
            <div className="rounded-xl border border-dashed border-black/[0.12] p-12 text-center text-xs text-[#8a8a8e]">
              조건에 맞는 문서가 서고에 없습니다.
            </div>
          ) : (
            <div className="space-y-2">
              {filtered.map((doc) => {
                const isAdminPin = Boolean(doc.is_pinned_default);
                const isUserPin = shelf.pinnedIds.includes(doc.id);
                const onShelf = shelfDocIds.has(doc.id);
                return (
                  <div
                    key={doc.id}
                    className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 transition ${
                      onShelf
                        ? 'border-[#0f4c81]/30 bg-[#0f4c81]/[0.03]'
                        : 'border-black/[0.08] bg-white hover:bg-[#fafaf9]'
                    }`}
                  >
                    <div className="flex min-w-0 flex-1 items-start gap-2.5">
                      <div
                        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                          onShelf ? 'bg-[#0f4c81] text-white' : 'bg-[#f4f4f2] text-[#71717a]'
                        }`}
                      >
                        {doc.file_type === 'xlsx' ? (
                          <FileSpreadsheet className="h-4 w-4" />
                        ) : (
                          <FileText className="h-4 w-4" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate text-xs font-semibold text-[#18181b]">{doc.title}</span>
                          {isAdminPin && (
                            <span className="chip-nowrap inline-flex items-center gap-0.5 rounded bg-[#0f4c81]/12 px-1.5 py-0.5 text-[10px] font-semibold text-[#0f4c81]">
                              <ShieldCheck className="h-2.5 w-2.5" />
                              필수 고정
                            </span>
                          )}
                          {isUserPin && !isAdminPin && (
                            <span className="chip-nowrap inline-flex items-center gap-0.5 rounded bg-[#18181b] px-1.5 py-0.5 text-[10px] font-semibold text-white">
                              <Pin className="h-2.5 w-2.5" />
                              내 고정
                            </span>
                          )}
                          {onShelf && !isAdminPin && !isUserPin && (
                            <span className="chip-nowrap rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">
                              작업대 올라감
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 truncate text-[11px] text-[#71717a]">
                          {doc.category} · {doc.page_count}쪽 · {doc.original_filename}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5">
                      {/* Personal Pin Toggle */}
                      <button
                        type="button"
                        onClick={() => onToggleUserPin(doc.id)}
                        title={isUserPin ? '내 고정 해제' : '왼쪽 작업대 최상단에 고정(Pin)'}
                        className={`chip-nowrap inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition ${
                          isUserPin
                            ? 'border-[#18181b] bg-[#18181b] text-white'
                            : 'border-black/[0.1] bg-white text-[#3f3f46] hover:bg-[#f7f7f5]'
                        }`}
                      >
                        {isUserPin ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}
                        <span>{isUserPin ? '고정 해제' : '고정'}</span>
                      </button>

                      {/* Load / Unload to Workspace Shelf */}
                      {!isAdminPin && !isUserPin && (
                        <button
                          type="button"
                          onClick={() => onToggleShelfLoad(doc.id)}
                          className={`chip-nowrap inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold transition ${
                            onShelf
                              ? 'border border-black/[0.1] bg-white text-[#52525b] hover:bg-amber-50 hover:text-amber-800'
                              : 'bg-[#0f4c81] text-white hover:bg-[#0c3d68]'
                          }`}
                        >
                          {onShelf ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                          <span>{onShelf ? '작업대에서 내리기' : '작업대 불러오기'}</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => onOpenViewer(doc.id, 1)}
                        title="원본 보기"
                        className="rounded-lg border border-black/[0.08] bg-white p-1.5 text-[#52525b] hover:bg-[#f7f7f5] hover:text-[#18181b]"
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </button>

                      {isAdmin && (
                        <>
                          <button
                            type="button"
                            disabled={busyDocId === doc.id}
                            onClick={() => void handleToggleAdminPin(doc)}
                            title={isAdminPin ? '전체 팀원 필수 고정 해제' : '전체 팀원 왼쪽 작업대에 필수 고정'}
                            className={`chip-nowrap rounded-lg border px-2 py-1.5 text-[11px] font-medium transition ${
                              isAdminPin
                                ? 'border-[#0f4c81] bg-[#0f4c81]/10 text-[#0f4c81]'
                                : 'border-black/[0.08] bg-white text-[#71717a] hover:text-[#18181b]'
                            }`}
                          >
                            {isAdminPin ? '필수 해제' : '필수 고정'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setUpdateTarget(doc)}
                            title="파일 교체 · 메타 수정"
                            className="rounded-lg border border-black/[0.08] bg-white p-1.5 text-[#52525b] hover:bg-[#f7f7f5]"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(doc)}
                            title="서고에서 완전 삭제 (관리자 PIN 필요)"
                            className="rounded-lg border border-black/[0.08] bg-white p-1.5 text-[#8a8a8e] hover:bg-red-50 hover:text-red-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {updateTarget && (
        <UpdateDocumentModal doc={updateTarget} onUpdated={onRefresh} onClose={() => setUpdateTarget(null)} />
      )}

      {deleteTarget && (
        <AdminPinConfirmModal
          title="서고 자료 완전 삭제 확인"
          targetName={deleteTarget.title}
          onConfirm={async (pin) => {
            await api.deleteDocument(deleteTarget.id, pin);
            onRefresh();
          }}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};
