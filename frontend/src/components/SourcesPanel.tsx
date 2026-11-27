import React, { memo, useMemo, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Eye,
  FileSpreadsheet,
  FileText,
  Globe,
  Library,
  Loader2,
  Lock,
  MessageSquare,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  Share2,
  SquarePen,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { ChatSession, CollabGroup, DocumentItem } from '../types';
import { AdminPinConfirmModal } from './AdminPinConfirmModal';
import { UpdateDocumentModal } from './UpdateDocumentModal';

interface Props {
  notebookId: string;
  allDocumentCount: number;
  pinnedDocs: DocumentItem[];
  loadedDocs: DocumentItem[];
  userPinnedIds: Set<string>;
  selectedDocIds: string[];
  sessions: ChatSession[];
  groups: CollabGroup[];
  activeSessionId: string | null;
  currentOwnerId: string;
  isAdmin: boolean;
  onToggleDoc: (docId: string) => void;
  onSelectAll: (all: boolean) => void;
  onToggleUserPin: (docId: string) => void;
  onUnloadFromShelf: (docId: string) => void;
  onOpenLibrary: () => void;
  onOpenGroups: () => void;
  onOpenViewer: (docId: string, pageNo: number) => void;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onRenameSession: (sessionId: string, title: string) => Promise<void>;
  onSetSessionScope: (sessionId: string, scope: { is_shared: boolean; group_id: string }) => Promise<void>;
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

export const SourcesPanel: React.FC<Props> = memo(({
  notebookId,
  allDocumentCount,
  pinnedDocs,
  loadedDocs,
  userPinnedIds,
  selectedDocIds,
  sessions,
  groups,
  activeSessionId,
  currentOwnerId,
  isAdmin,
  onToggleDoc,
  onSelectAll,
  onToggleUserPin,
  onUnloadFromShelf,
  onOpenLibrary,
  onOpenGroups,
  onOpenViewer,
  onSelectSession,
  onNewChat,
  onRenameSession,
  onSetSessionScope,
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
  const [shareMenuSessionId, setShareMenuSessionId] = useState<string | null>(null);
  const [updateTarget, setUpdateTarget] = useState<DocumentItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);
  const [sourcesCollapsed, setSourcesCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('church_search_sources_collapsed') === '1';
    } catch {
      return false;
    }
  });

  const toggleSourcesCollapsed = () => {
    setSourcesCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('church_search_sources_collapsed', next ? '1' : '0');
      } catch {
        // ignore
      }
      return next;
    });
  };

  const shelfDocs = useMemo(() => [...pinnedDocs, ...loadedDocs], [pinnedDocs, loadedDocs]);
  const shelfIds = useMemo(() => new Set(shelfDocs.map((d) => d.id)), [shelfDocs]);
  const selectedOnShelfCount = useMemo(
    () => selectedDocIds.filter((id) => shelfIds.has(id)).length,
    [selectedDocIds, shelfIds]
  );
  const allSelected = shelfDocs.length > 0 && selectedOnShelfCount === shelfDocs.length;

  const groupNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const g of groups) map[g.id] = g.name;
    return map;
  }, [groups]);

  const privateSessions = sessions.filter((s) => !s.is_shared && !s.group_id);
  const groupSessions = sessions.filter((s) => Boolean(s.group_id));
  const teamSessions = sessions.filter((s) => Boolean(s.is_shared) && !s.group_id);

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
    setShareMenuSessionId(null);
    setEditingSessionId(s.id);
    setEditingTitle(s.title);
  };

  const commitEditSession = async (sessionId: string) => {
    const trimmed = editingTitle.trim();
    setEditingSessionId(null);
    if (!trimmed) return;
    await onRenameSession(sessionId, trimmed);
  };

  const renderDocRow = (doc: DocumentItem, isPinnedSection: boolean) => {
    const selected = selectedDocIds.includes(doc.id);
    const isAdminPin = Boolean(doc.is_pinned_default);
    const isUserPin = userPinnedIds.has(doc.id);

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
        className={`group relative flex cursor-pointer items-center gap-2 rounded-lg border px-2 py-2 transition outline-none focus-visible:ring-1 focus-visible:ring-[#0f4c81] ${
          selected
            ? 'border-[#0f4c81]/35 bg-white text-[#18181b] shadow-[0_1px_3px_rgba(15,76,129,0.08)]'
            : 'border-transparent bg-transparent text-[#71717a] opacity-70 hover:bg-black/[0.04] hover:opacity-100'
        }`}
      >
        {/* High-Contrast Selection Checkbox Badge */}
        <span
          aria-hidden="true"
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] border transition ${
            selected
              ? 'border-[#0f4c81] bg-[#0f4c81] text-white'
              : 'border-black/20 bg-white/80 text-transparent group-hover:border-black/35'
          }`}
        >
          <Check className="h-2.5 w-2.5" strokeWidth={3} />
        </span>

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
          <div className="flex items-center gap-1">
            <p className={`truncate text-[12.5px] leading-snug ${selected ? 'font-semibold text-[#18181b]' : 'font-normal'}`}>
              {doc.title}
            </p>
            {isPinnedSection && isAdminPin && (
              <span className="chip-nowrap shrink-0 rounded bg-[#0f4c81]/10 px-1 py-0.2 text-[9px] font-bold text-[#0f4c81]">
                필수
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-[10.5px] text-[#8a8a8e]">
            {doc.category} · {doc.page_count}쪽
          </p>
        </div>

        <div className="mac-hover-reveal flex shrink-0 items-center gap-0.5 lg:absolute lg:top-1/2 lg:right-1.5 lg:-translate-y-1/2 lg:rounded-md lg:bg-white/95 lg:px-1 lg:py-0.5 lg:shadow-xs lg:ring-1 lg:ring-black/[0.06]">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleUserPin(doc.id);
            }}
            title={isUserPin ? '개인 고정 해제' : '자주 쓰는 자료로 상단 고정'}
            aria-label={isUserPin ? `${doc.title} 고정 해제` : `${doc.title} 상단 고정`}
            className={`rounded p-1 transition hover:bg-black/[0.06] ${
              isUserPin ? 'text-[#0f4c81]' : 'text-[#71717a] hover:text-[#18181b]'
            }`}
          >
            {isUserPin ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
          </button>

          {!isAdminPin && !isUserPin && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onUnloadFromShelf(doc.id);
              }}
              title="작업대에서 내리기 (라이브러리에는 안전하게 보관됨)"
              aria-label={`${doc.title} 작업대에서 내리기`}
              className="rounded p-1 text-[#8a8a8e] transition hover:bg-black/[0.06] hover:text-[#18181b]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}

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
                title="자료 영구 삭제 (관리자 PIN 필요)"
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
  };

  const renderSessionRow = (s: ChatSession) => {
    const isActive = s.id === activeSessionId;
    const isEditing = s.id === editingSessionId;
    const isShared = Boolean(s.is_shared);
    const gid = s.group_id || '';
    const gName = s.group_name || (gid ? groupNameMap[gid] : '');
    const canModify = isAdmin || (Boolean(s.owner_id) && s.owner_id === currentOwnerId);
    const showShareMenu = shareMenuSessionId === s.id;

    return (
      <div key={s.id} className="relative">
        <div
          role="button"
          tabIndex={0}
          onClick={() => {
            if (!isEditing) {
              setShareMenuSessionId(null);
              onSelectSession(s.id);
            }
          }}
          onKeyDown={(e) => {
            if (!isEditing && (e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault();
              onSelectSession(s.id);
            }
          }}
          className={`group relative flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 transition ${
            isActive ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgba(0,0,0,0.05)]' : 'text-[#52525b] hover:bg-black/[0.04]'
          }`}
        >
          {gid ? (
            <Users className={`h-3.5 w-3.5 shrink-0 ${isActive ? 'text-[#0f4c81]' : 'text-[#0f4c81]/70'}`} strokeWidth={1.9} />
          ) : isShared ? (
            <Globe className={`h-3.5 w-3.5 shrink-0 ${isActive ? 'text-[#0f4c81]' : 'text-[#a1a1aa]'}`} strokeWidth={1.8} />
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
                <p className="truncate text-[10.5px] text-[#8a8a8e]">
                  {formatShortTime(s.updated_at)}
                  {gid ? ` · ${gName || '그룹'}` : isShared ? ' · 전체 공유' : ''}
                </p>
              </div>

              {canModify && (
                <div className="mac-hover-reveal flex shrink-0 items-center gap-0.5 lg:absolute lg:top-1/2 lg:right-1.5 lg:-translate-y-1/2 lg:rounded-md lg:bg-white/95 lg:px-1 lg:py-0.5 lg:shadow-xs lg:ring-1 lg:ring-black/[0.06]">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setShareMenuSessionId(showShareMenu ? null : s.id);
                    }}
                    title="공유 범위 변경 (비공개 / 그룹 공동 / 전체)"
                    aria-label="대화 공유 범위 설정"
                    className={`rounded p-1 transition hover:bg-black/[0.07] ${
                      gid || isShared ? 'text-[#0f4c81]' : 'text-[#71717a] hover:text-[#18181b]'
                    }`}
                  >
                    <Share2 className="h-3 w-3" />
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

        {/* Share Scope Popover */}
        {showShareMenu && (
          <div
            onClick={(e) => e.stopPropagation()}
            className="mt-1 space-y-0.5 rounded-xl border border-black/[0.1] bg-white p-1.5 shadow-lg"
          >
            <p className="px-2 py-0.5 text-[10px] font-semibold text-[#8a8a8e]">공유 범위 선택</p>
            <button
              type="button"
              onClick={() => {
                setShareMenuSessionId(null);
                void onSetSessionScope(s.id, { is_shared: false, group_id: '' });
              }}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] transition ${
                !gid && !isShared ? 'bg-[#0f4c81]/10 font-semibold text-[#0f4c81]' : 'text-[#3f3f46] hover:bg-[#f7f7f5]'
              }`}
            >
              <Lock className="h-3 w-3 shrink-0" />
              <span className="truncate">내 비공개 대화</span>
            </button>

            {groups.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => {
                  setShareMenuSessionId(null);
                  void onSetSessionScope(s.id, { is_shared: false, group_id: g.id });
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] transition ${
                  gid === g.id ? 'bg-[#0f4c81]/10 font-semibold text-[#0f4c81]' : 'text-[#3f3f46] hover:bg-[#f7f7f5]'
                }`}
              >
                <Users className="h-3 w-3 shrink-0" />
                <span className="truncate">{g.name} (공동 대화)</span>
              </button>
            ))}

            <button
              type="button"
              onClick={() => {
                setShareMenuSessionId(null);
                void onSetSessionScope(s.id, { is_shared: true, group_id: '' });
              }}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] transition ${
                !gid && isShared ? 'bg-[#0f4c81]/10 font-semibold text-[#0f4c81]' : 'text-[#3f3f46] hover:bg-[#f7f7f5]'
              }`}
            >
              <Globe className="h-3 w-3 shrink-0" />
              <span className="truncate">전체 팀 공유</span>
            </button>

            <div className="my-1 border-t border-black/[0.06]" />
            <button
              type="button"
              onClick={() => {
                setShareMenuSessionId(null);
                onOpenGroups();
              }}
              className="flex w-full items-center justify-between rounded-lg px-2 py-1 text-left text-[11px] font-medium text-[#0f4c81] hover:bg-[#0f4c81]/5"
            >
              <span>그룹 관리 · 초대 참여</span>
              <ChevronRight className="h-3 w-3" />
            </button>
          </div>
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
        {/* Section 1: Workspace Shelf + Library Trigger (Collapsible to 1 compact top line) */}
        <div data-section="sources">
          <div className={`${sourcesCollapsed ? 'mb-0' : 'mb-1.5'} flex items-center justify-between gap-1 px-1`}>
            <div className="flex min-w-0 items-center gap-1">
              <button
                type="button"
                onClick={toggleSourcesCollapsed}
                title={sourcesCollapsed ? '자료 공간 펼치기' : '자료 공간 한 줄로 줄이기'}
                aria-label={sourcesCollapsed ? '자료 공간 펼치기' : '자료 공간 한 줄로 줄이기'}
                aria-expanded={!sourcesCollapsed}
                className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[#52525b] transition hover:bg-black/[0.06] hover:text-[#18181b]"
              >
                {sourcesCollapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
              </button>
              <button
                type="button"
                onClick={toggleSourcesCollapsed}
                title={sourcesCollapsed ? '자료 공간 펼치기' : '자료 공간 한 줄로 줄이기'}
                className="chip-nowrap text-[11px] font-semibold tracking-tight text-[#52525b] hover:text-[#18181b]"
              >
                검색 자료
              </button>
              <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-1.5 py-0.2 text-[10.5px] font-semibold text-[#0f4c81]">
                {selectedOnShelfCount}/{shelfDocs.length}
              </span>
            </div>

            <div className="flex shrink-0 items-center gap-0.5">
              {sourcesCollapsed ? (
                <button
                  type="button"
                  onClick={onOpenLibrary}
                  title={`자료 라이브러리 열기 (전체 ${allDocumentCount}권)`}
                  aria-label="자료 라이브러리 열기"
                  className="chip-nowrap inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#0f4c81] transition hover:bg-[#0f4c81]/10"
                >
                  <Library className="h-3 w-3" />
                  <span>서고 {allDocumentCount}</span>
                </button>
              ) : (
                shelfDocs.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onSelectAll(!allSelected)}
                    title={allSelected ? '선택한 자료 모두 해제' : '작업대 자료 모두 선택'}
                    className="chip-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b]"
                  >
                    {allSelected ? '해제' : '전체'}
                  </button>
                )
              )}
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  title="문서 자료 추가 (드래그&드롭 가능)"
                  aria-label="문서 자료 추가"
                  className="chip-nowrap inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#18181b] transition hover:bg-black/[0.06]"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>추가</span>
                </button>
              )}
            </div>
          </div>

          {!sourcesCollapsed && (
            <>
              {/* Prominent Library (서고) Drawer Button */}
              <button
                type="button"
                onClick={onOpenLibrary}
                title="전체 자료 라이브러리(서고) 열기"
                className="mb-2.5 flex w-full items-center justify-between gap-2 rounded-xl border border-black/[0.08] bg-white px-2.5 py-2 text-left transition hover:border-[#0f4c81]/40 hover:bg-[#fafaf9]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Library className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                  <span className="truncate text-[12px] font-semibold text-[#18181b]">자료 라이브러리</span>
                </div>
                <div className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-[#71717a]">
                  <span className="chip-nowrap">전체 {allDocumentCount}권</span>
                  <ChevronRight className="h-3.5 w-3.5" />
                </div>
              </button>

              {shelfDocs.length === 0 ? (
                <div className="rounded-xl border border-dashed border-black/[0.12] bg-white/60 p-4 text-center">
                  <p className="text-xs font-medium text-[#71717a]">
                    {allDocumentCount > 0 ? '작업대에 불러온 자료가 없습니다' : '등록된 자료가 없습니다'}
                  </p>
                  {allDocumentCount > 0 ? (
                    <button
                      type="button"
                      onClick={onOpenLibrary}
                      className="chip-nowrap mt-2 inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-[#27272a]"
                    >
                      <Library className="h-3 w-3" />
                      <span>라이브러리에서 불러오기</span>
                    </button>
                  ) : (
                    isAdmin && (
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className="chip-nowrap mt-2 inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-[#27272a]"
                      >
                        <Upload className="h-3 w-3" />
                        <span>첫 자료 올리기</span>
                      </button>
                    )
                  )}
                </div>
              ) : (
                <div className="space-y-2.5">
                  {pinnedDocs.length > 0 && (
                    <div className="space-y-1">
                      <p className="flex items-center gap-1 px-1.5 text-[10px] font-semibold text-[#8a8a8e]">
                        <Pin className="h-2.5 w-2.5 text-[#0f4c81]" />
                        <span>고정됨</span>
                      </p>
                      {pinnedDocs.map((doc) => renderDocRow(doc, true))}
                    </div>
                  )}

                  {loadedDocs.length > 0 && (
                    <div className="space-y-1">
                      {pinnedDocs.length > 0 && (
                        <p className="px-1.5 text-[10px] font-semibold text-[#8a8a8e]">작업대 자료</p>
                      )}
                      {loadedDocs.map((doc) => renderDocRow(doc, false))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div className={`${sourcesCollapsed ? 'my-2.5' : 'my-4'} border-t border-black/[0.06]`} />

        {/* Section 2: Saved Chat Pages (Private / Group Collaborative / Team) */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-1.5 flex items-center justify-between gap-1.5 px-1.5">
            <span className="text-[11px] font-semibold tracking-tight text-[#52525b]">대화</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={onOpenGroups}
                title="그룹 초대 · 참여 관리"
                className="chip-nowrap inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#0f4c81] transition hover:bg-[#0f4c81]/10"
              >
                <Users className="h-3 w-3" />
                <span>그룹{groups.length > 0 ? ` ${groups.length}` : ''}</span>
              </button>
              <button
                type="button"
                onClick={onNewChat}
                className="chip-nowrap inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
              >
                <SquarePen className="h-3 w-3" />
                <span>새 대화</span>
              </button>
            </div>
          </div>

          {sessions.length === 0 ? (
            <p className="px-2 py-2 text-[11px] leading-relaxed text-[#8a8a8e]">
              저장된 대화가 없습니다. 질문을 시작하거나 그룹 초대를 받으면 여기에 표시됩니다.
            </p>
          ) : (
            <div className="space-y-3">
              {groupSessions.length > 0 && (
                <div className="space-y-0.5">
                  <p className="px-2 text-[10px] font-semibold text-[#0f4c81]">그룹 공동 대화</p>
                  {groupSessions.map(renderSessionRow)}
                </div>
              )}
              {privateSessions.length > 0 && (
                <div className="space-y-0.5">
                  <p className="px-2 text-[10px] font-semibold text-[#a1a1aa]">내 비공개 대화</p>
                  {privateSessions.map(renderSessionRow)}
                </div>
              )}
              {teamSessions.length > 0 && (
                <div className="space-y-0.5">
                  <p className="px-2 text-[10px] font-semibold text-[#a1a1aa]">전체 팀 공유</p>
                  {teamSessions.map(renderSessionRow)}
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
});
SourcesPanel.displayName = 'SourcesPanel';
