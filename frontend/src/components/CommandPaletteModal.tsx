import React, { useEffect, useRef, useState } from 'react';
import {
  FileEdit,
  FileText,
  FolderKanban,
  Library,
  Loader2,
  MessageSquare,
  Search,
  SquarePen,
  Users,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { ChatSession, DocumentItem, FormItem, QuickSearchResult, StdBoard } from '../types';

interface Props {
  notebookId: string;
  onSelectDocument: (doc: DocumentItem) => void;
  onSelectForm: (form: FormItem) => void;
  onSelectSession: (session: ChatSession) => void;
  onSelectBoard: (board: StdBoard) => void;
  onQuickAction: (action: 'new_chat' | 'library' | 'groups' | 'std') => void;
  onClose: () => void;
}

export const CommandPaletteModal: React.FC<Props> = ({
  notebookId,
  onSelectDocument,
  onSelectForm,
  onSelectSession,
  onSelectBoard,
  onQuickAction,
  onClose,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [res, setRes] = useState<QuickSearchResult | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void api
        .quickSearch(query, notebookId)
        .then((data) => {
          if (!cancelled) setRes(data);
        })
        .catch(() => {})
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, notebookId]);

  const hasAny =
    res &&
    (res.documents.length > 0 || res.forms.length > 0 || res.sessions.length > 0 || res.boards.length > 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/45 p-4 pt-[10vh] backdrop-blur-xs"
      onClick={onClose}
    >
      <div
        className="flex max-h-[75dvh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-black/[0.1] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-black/[0.08] px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-[#0f4c81]" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="서고 문서, 서식, 저장된 대화, 표준화 과제를 빠르게 검색..."
            className="min-w-0 flex-1 bg-transparent text-sm text-[#18181b] placeholder-[#a1a1aa] outline-none"
          />
          {loading && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[#8a8a8e]" />}
          <kbd className="hidden rounded border border-black/[0.1] bg-[#f7f7f5] px-1.5 py-0.5 text-[10px] font-semibold text-[#71717a] sm:inline">
            ESC
          </kbd>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded p-1 text-[#8a8a8e] hover:bg-black/[0.05]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Quick Actions Bar */}
        <div className="flex flex-wrap items-center gap-1.5 border-b border-black/[0.06] bg-[#fafaf9] px-4 py-2">
          <button
            type="button"
            onClick={() => {
              onClose();
              onQuickAction('new_chat');
            }}
            className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-white px-2.5 py-1 text-[11px] font-medium text-[#18181b] hover:bg-[#f4f4f2]"
          >
            <SquarePen className="h-3 w-3 text-[#0f4c81]" />
            <span>새 대화</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onClose();
              onQuickAction('library');
            }}
            className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-white px-2.5 py-1 text-[11px] font-medium text-[#18181b] hover:bg-[#f4f4f2]"
          >
            <Library className="h-3 w-3 text-[#0f4c81]" />
            <span>전체 자료 라이브러리</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onClose();
              onQuickAction('groups');
            }}
            className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-white px-2.5 py-1 text-[11px] font-medium text-[#18181b] hover:bg-[#f4f4f2]"
          >
            <Users className="h-3 w-3 text-[#0f4c81]" />
            <span>그룹 · 초대 관리</span>
          </button>
          <button
            type="button"
            onClick={() => {
              onClose();
              onQuickAction('std');
            }}
            className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-white px-2.5 py-1 text-[11px] font-medium text-[#18181b] hover:bg-[#f4f4f2]"
          >
            <FolderKanban className="h-3 w-3 text-[#0f4c81]" />
            <span>행정 표준화실</span>
          </button>
        </div>

        {/* Results */}
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {!res ? (
            <div className="py-8 text-center text-xs text-[#8a8a8e]">검색 준비 중...</div>
          ) : !hasAny ? (
            <div className="py-10 text-center text-xs text-[#8a8a8e]">일치하는 문서·서식·대화·과제가 없습니다.</div>
          ) : (
            <>
              {res.documents.length > 0 && (
                <div>
                  <p className="mb-1.5 px-2 text-[10.5px] font-semibold text-[#71717a]">
                    서고 문서 (클릭 시 작업대로 불러오고 원문 열기)
                  </p>
                  <div className="space-y-0.5">
                    {res.documents.map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        onClick={() => {
                          onSelectDocument(d);
                          onClose();
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition hover:bg-[#f7f7f5]"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <FileText className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                          <span className="truncate font-semibold text-[#18181b]">{d.title}</span>
                        </div>
                        <span className="chip-nowrap text-[11px] text-[#8a8a8e]">
                          {d.category} · {d.page_count}쪽
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {res.forms.length > 0 && (
                <div>
                  <p className="mb-1.5 px-2 text-[10.5px] font-semibold text-[#71717a]">행정 서식 · 표 (바로 작성)</p>
                  <div className="space-y-0.5">
                    {res.forms.map((f) => (
                      <button
                        key={f.id}
                        type="button"
                        onClick={() => {
                          onSelectForm(f);
                          onClose();
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition hover:bg-[#f7f7f5]"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <FileEdit className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                          <span className="truncate font-medium text-[#18181b]">{f.title}</span>
                        </div>
                        <span className="chip-nowrap text-[11px] text-[#8a8a8e]">
                          {f.doc_title} p.{f.page_start}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {res.sessions.length > 0 && (
                <div>
                  <p className="mb-1.5 px-2 text-[10.5px] font-semibold text-[#71717a]">저장된 대화 · 그룹 채팅방</p>
                  <div className="space-y-0.5">
                    {res.sessions.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => {
                          onSelectSession(s);
                          onClose();
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition hover:bg-[#f7f7f5]"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-[#52525b]" />
                          <span className="truncate font-medium text-[#18181b]">{s.title}</span>
                        </div>
                        <span className="chip-nowrap text-[11px] text-[#8a8a8e]">
                          {s.group_name ? `[${s.group_name}]` : s.is_shared ? '전체 공유' : '내 대화'}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {res.boards.length > 0 && (
                <div>
                  <p className="mb-1.5 px-2 text-[10.5px] font-semibold text-[#71717a]">행정 표준화 과제</p>
                  <div className="space-y-0.5">
                    {res.boards.map((b) => (
                      <button
                        key={b.id}
                        type="button"
                        onClick={() => {
                          onSelectBoard(b);
                          onClose();
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition hover:bg-[#f7f7f5]"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <FolderKanban className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                          <span className="truncate font-medium text-[#18181b]">{b.title}</span>
                        </div>
                        <span className="chip-nowrap text-[11px] text-[#8a8a8e]">
                          {b.group_name ? `[${b.group_name}] · ` : ''}
                          {b.category}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
