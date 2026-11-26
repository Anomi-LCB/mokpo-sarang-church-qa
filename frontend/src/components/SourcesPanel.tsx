import React, { useRef, useState } from 'react';
import {
  Check,
  Eye,
  FileSpreadsheet,
  FileText,
  Loader2,
  Lock,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  SquarePen,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { ChatSession, DocumentItem } from '../types';
import { AdminPinConfirmModal } from './AdminPinConfirmModal';
import { UpdateDocumentModal } from './UpdateDocumentModal';

interface Props {
  notebookId: string;
  documents: DocumentItem[];
  selectedDocIds: string[];
  sessions: ChatSession[];
  activeSessionId: string | null;
  currentOwnerId: string;
  isAdmin: boolean;
  onToggleDoc: (docId: string) => void;
  onSelectAll: (all: boolean) => void;
  onOpenViewer: (docId: string, pageNo: number) => void;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onRenameSession: (sessionId: string, title: string) => Promise<void>;
  onToggleShareSession: (sessionId: string, nextShared: boolean) => Promise<void>;
  onDeleteSession: (sessionId: string) => Promise<void>;
  onRefresh: () => void;
}

function formatShortTime(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
  if (diffMin < 1) return '방금';
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}시간 전`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export const SourcesPanel: React.FC<Props> = ({
  notebookId,
  documents,
  selectedDocIds,
  sessions,
  activeSessionId,
  currentOwnerId,
  isAdmin,
  onToggleDoc,
  onSelectAll,
  onOpenViewer,
  onSelectSession,
  onNewChat,
  onRenameSession,
  onToggleShareSession,
  onDeleteSession,
  onRefresh,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadState, setUploadState] = useState<{ running: boolean; progress: number; message: string }>({
    running: false,
    progress: 0,
    message: '',
  });
  const [error, setError] = useState('');
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [updateTarget, setUpdateTarget] = useState<DocumentItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);

  const allSelected = documents.length > 0 && selectedDocIds.length === documents.length;
  const sharedSessions = sessions.filter((s) => Boolean(s.is_shared));
  const privateSessions = sessions.filter((s) => !s.is_shared);

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0 || !isAdmin) return;
    setError('');
    setUploadState({ running: true, progress: 6, message: '자료 업로드 중...' });
    try {
      const { job_id } = await api.uploadDocuments(notebookId, Array.from(fileList));
      while (true) {
        await new Promise((r) => setTimeout(r, 900));
        const st = await api.getJob(job_id);
        setUploadState({ running: st.status === 'running', progress: st.progress, message: st.message });
        if (st.status === 'done') {
          onRefresh();
          setTimeout(() => setUploadState({ running: false, progress: 0, message: '' }), 2000);
          break;
        }
        if (st.status === 'error') {
          setError(st.error || '색인 중 오류가 발생했습니다.');
          setUploadState({ running: false, progress: 0, message: '' });
          break;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '업로드 실패');
      setUploadState({ running: false, progress: 0, message: '' });
    }
  };

  const handleConfirmDeleteDoc = async (adminPin: string) => {
    if (!deleteTarget) return;
    await api.deleteDocument(deleteTarget.id, adminPin);
    onRefresh();
  };

  const startEditSession = (e: React.MouseEvent, s: ChatSession) => {
    e.stopPropagation();
    setEditingSessionId(s.id);
    setEditingTitle(s.title);
  };

  const commitEditSession = async (sessionId: string) => {
    const trimmed = editingTitle.trim();
    setEditingSessionId(null);
    if (!trimmed) return;
    await onRenameSession(sessionId, trimmed);
  };

  const renderSessionRow = (s: ChatSession) => {
    const isActive = s.id === activeSessionId;
    const isEditing = s.id === editingSessionId;
    const isShared = Boolean(s.is_shared);
    const canModify = isAdmin || (Boolean(s.owner_id) && s.owner_id === currentOwnerId);

    return (
      <div
        key={s.id}
        role="button"
        tabIndex={0}
        onClick={() => !isEditing && onSelectSession(s.id)}
        onKeyDown={(e) => {
          if (!isEditing && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            onSelectSession(s.id);
          }
        }}
        className={`group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 transition ${
          isActive ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgba(0,0,0,0.04)]' : 'text-[#52525b] hover:bg-black/[0.04]'
        }`}
      >
        {isShared ? (
          <Users className={`h-3.5 w-3.5 shrink-0 ${isActive ? 'text-[#0f4c81]' : 'text-[#a1a1aa]'}`} strokeWidth={1.8} />
        ) : (
          <MessageSquare className={`h-3.5 w-3.5 shrink-0 ${isActive ? 'text-[#0f4c81]' : 'text-[#a1a1aa]'}`} strokeWidth={1.8} />
        )}

        {isEditing ? (
          <div className="flex min-w-0 flex-1 items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <input
              type="text"
              value={editingTitle}
              onChange={(e) => setEditingTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void commitEditSession(s.id);
                if (e.key === 'Escape') setEditingSessionId(null);
              }}
              autoFocus
              className="min-w-0 flex-1 rounded border border-[#18181b] bg-white px-1.5 py-0.5 text-xs text-[#18181b] outline-none"
            />
            <button type="button" onClick={() => void commitEditSession(s.id)} aria-label="저장" className="rounded p-1 text-[#0f4c81] hover:bg-black/[0.05]">
              <Check className="h-3 w-3" />
            </button>
            <button type="button" onClick={() => setEditingSessionId(null)} aria-label="취소" className="rounded p-1 text-[#71717a] hover:bg-black/[0.05]">
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : (
          <>
            <div className="min-w-0 flex-1">
              <p className={`truncate text-[12.5px] ${isActive ? 'font-semibold text-[#18181b]' : 'font-normal'}`}>{s.title}</p>
              <p className="text-[10.5px] text-[#8a8a8e]">
                {formatShortTime(s.updated_at)}
                {isShared ? ' · 공유' : ''}
              </p>
            </div>

            {canModify && (
              <div className="mac-hover-reveal flex shrink-0 items-center gap-0.5">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void onToggleShareSession(s.id, !isShared);
                  }}
                  title={isShared ? '나만 보기(비공개)로 전환' : '팀 전체와 공유하기'}
                  aria-label={isShared ? '비공개로 전환' : '팀에 공유'}
                  className="rounded p-1 text-[#71717a] transition hover:bg-black/[0.07] hover:text-[#18181b]"
                >
                  {isShared ? <Lock className="h-3 w-3" /> : <Users className="h-3 w-3" />}
                </button>
                <button
                  type="button"
                  onClick={(e) => startEditSession(e, s)}
                  title="대화 이름 변경"
                  aria-label="대화 이름 변경"
                  className="rounded p-1 text-[#71717a] transition hover:bg-black/[0.07] hover:text-[#18181b]"
                >
                  <Pencil className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`"${s.title}" 대화 기록을 삭제할까요?`)) {
                      void onDeleteSession(s.id);
                    }
                  }}
                  title="대화 삭제"
                  aria-label="대화 삭제"
                  className="rounded p-1 text-[#8a8a8e] transition hover:bg-red-50 hover:text-red-600"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  return (
    <div
      onDragOver={(e) => {
        if (!isAdmin) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragging(false);
      }}
      onDrop={(e) => {
        if (!isAdmin) return;
        e.preventDefault();
        setDragging(false);
        void handleFiles(e.dataTransfer.files);
      }}
      className="relative flex h-full min-h-0 flex-col bg-[#f7f7f5] select-none"
    >
      {isAdmin && (
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.zip,.txt,.md,.docx,.hwpx,.xlsx"
          className="hidden"
          onChange={(e) => {
            void handleFiles(e.target.files);
            e.target.value = '';
          }}
        />
      )}

      {dragging && isAdmin && (
        <div className="pointer-events-none absolute inset-2 z-30 flex flex-col items-center justify-center rounded-xl border border-dashed border-[#18181b] bg-white/95 p-5 text-center backdrop-blur-md">
          <Upload className="mb-2 h-5 w-5 text-[#18181b]" />
          <p className="text-xs font-semibold text-[#18181b]">여기에 파일을 놓아 추가</p>
          <p className="mt-1 text-[11px] text-[#71717a]">PDF · ZIP · DOCX · HWPX · TXT · XLSX</p>
        </div>
      )}

      {(uploadState.message || error) && (
        <div className="px-3 pt-3">
          {uploadState.message && (
            <div className="rounded-lg border border-black/[0.08] bg-white px-3 py-2">
              <div className="flex items-center gap-2 text-[11px] font-medium text-[#18181b]">
                {uploadState.running && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[#0f4c81]" />}
                <span className="min-w-0 truncate">{uploadState.message}</span>
              </div>
              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-black/[0.06]">
                <div className="h-full rounded-full bg-[#18181b] transition-all" style={{ width: `${uploadState.progress}%` }} />
              </div>
            </div>
          )}
          {error && (
            <div className="mt-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-[11px] text-red-700">
              {error}
            </div>
          )}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2.5 py-3">
        {/* Section 1: Flat Finder-Style Clickable Document Rows */}
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-1.5 px-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="text-[11px] font-semibold tracking-tight text-[#71717a]">검색 자료</span>
              <span className="chip-nowrap text-[10.5px] font-medium text-[#8a8a8e]">
                {selectedDocIds.length}/{documents.length}
              </span>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              {documents.length > 0 && (
                <button
                  type="button"
                  onClick={() => onSelectAll(!allSelected)}
                  className="chip-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b]"
                >
                  {allSelected ? '해제' : '전체'}
                </button>
              )}
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  title="문서 자료 추가 (드래그&드롭 가능)"
                  className="chip-nowrap inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#18181b] transition hover:bg-black/[0.06]"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>추가</span>
                </button>
              )}
            </div>
          </div>

          <div className="space-y-0.5">
            {documents.length === 0 ? (
              <div className="rounded-lg border border-dashed border-black/[0.1] p-4 text-center text-xs text-[#8a8a8e]">
                자료 없음
              </div>
            ) : (
              documents.map((doc) => {
                const selected = selectedDocIds.includes(doc.id);
                return (
                  <div
                    key={doc.id}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected}
                    onClick={() => onToggleDoc(doc.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onToggleDoc(doc.id);
                      }
                    }}
                    className={`group relative flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 transition outline-none focus-visible:ring-1 focus-visible:ring-[#18181b] ${
                      selected
                        ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgba(0,0,0,0.045)]'
                        : 'text-[#71717a] hover:bg-black/[0.04] hover:text-[#3f3f46]'
                    }`}
                  >
                    {/* Minimal refined left active indicator */}
                    <span
                      className={`h-4 w-[2.5px] shrink-0 rounded-full transition-colors ${
                        selected ? 'bg-[#0f4c81]' : 'bg-transparent'
                      }`}
                    />

                    {doc.file_type === 'xlsx' ? (
                      <FileSpreadsheet
                        className={`h-3.5 w-3.5 shrink-0 ${selected ? 'text-[#0f4c81]' : 'text-[#a1a1aa]'}`}
                        strokeWidth={1.8}
                      />
                    ) : (
                      <FileText
                        className={`h-3.5 w-3.5 shrink-0 ${selected ? 'text-[#0f4c81]' : 'text-[#a1a1aa]'}`}
                        strokeWidth={1.8}
                      />
                    )}

                    <div className="min-w-0 flex-1">
                      <p className={`truncate text-[12.5px] leading-snug ${selected ? 'font-semibold text-[#18181b]' : 'font-normal'}`}>
                        {doc.title}
                      </p>
                      <p className="mt-0.5 truncate text-[10.5px] text-[#8a8a8e]">
                        {doc.category} · {doc.page_count}쪽
                      </p>
                    </div>

                    <div className="mac-hover-reveal flex shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenViewer(doc.id, 1);
                        }}
                        title="원본 문서 보기"
                        aria-label={`${doc.title} 원본 보기`}
                        className="rounded p-1 text-[#71717a] transition hover:bg-black/[0.06] hover:text-[#18181b]"
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </button>
                      {isAdmin && (
                        <>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setUpdateTarget(doc);
                            }}
                            title="자료 업데이트 · 파일 교체"
                            aria-label={`${doc.title} 업데이트`}
                            className="rounded p-1 text-[#71717a] transition hover:bg-black/[0.06] hover:text-[#18181b]"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteTarget(doc);
                            }}
                            title="자료 삭제 (관리자 PIN 필요)"
                            aria-label={`${doc.title} 삭제`}
                            className="rounded p-1 text-[#8a8a8e] transition hover:bg-red-50 hover:text-red-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="my-4 border-t border-black/[0.06]" />

        {/* Section 2: Saved Chat Pages */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-1.5 flex items-center justify-between gap-1.5 px-2">
            <span className="text-[11px] font-semibold tracking-tight text-[#71717a]">저장된 대화</span>
            <button
              type="button"
              onClick={onNewChat}
              className="chip-nowrap inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
            >
              <SquarePen className="h-3 w-3" />
              <span>새 대화</span>
            </button>
          </div>

          {sessions.length === 0 ? (
            <p className="px-2 py-2 text-[11px] text-[#8a8a8e]">저장된 대화 없음</p>
          ) : (
            <div className="space-y-2.5">
              {privateSessions.length > 0 && (
                <div className="space-y-0.5">
                  <p className="px-2 text-[10px] font-medium text-[#a1a1aa]">내 대화</p>
                  {privateSessions.map(renderSessionRow)}
                </div>
              )}
              {sharedSessions.length > 0 && (
                <div className="space-y-0.5">
                  <p className="px-2 text-[10px] font-medium text-[#a1a1aa]">공유 대화</p>
                  {sharedSessions.map(renderSessionRow)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {updateTarget && (
        <UpdateDocumentModal doc={updateTarget} onUpdated={onRefresh} onClose={() => setUpdateTarget(null)} />
      )}

      {deleteTarget && (
        <AdminPinConfirmModal
          title="자료 삭제 확인"
          targetName={deleteTarget.title}
          onConfirm={handleConfirmDeleteDoc}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};
