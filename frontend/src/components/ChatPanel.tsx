import React, { memo, useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Eye,
  FileDown,
  FileEdit,
  FileSpreadsheet,
  FileText,
  Loader2,
  ShieldCheck,
  Users,
  Zap,
} from 'lucide-react';
import { api, triggerTicketDownload } from '../api';
import type { AnswerMode, ChatMessage, ChatSession, Citation, FormItem, Notebook } from '../types';
import { MarkdownView } from './MarkdownView';

interface Props {
  notebook: Notebook | null;
  activeSession?: ChatSession | null;
  messages: ChatMessage[];
  mode: AnswerMode;
  instantMode: boolean;
  doubleVerify: boolean;
  selectedDocCount: number;
  totalDocCount: number;
  busy: boolean;
  onModeChange: (m: AnswerMode) => void;
  onInstantToggle: (v: boolean) => void;
  onDoubleVerifyToggle: (v: boolean) => void;
  onSend: (query: string) => void;
  onOpenViewer: (docId: string, pageNo: number, highlightText?: string) => void;
  onOpenAutofill: (form: FormItem) => void;
}

const DEFAULT_PROMPTS = [
  { tag: '임직', query: '장로 후보자 추천 나이와 임직 절차를 정리해줘' },
  { tag: '직분', query: '무임 장로와 권찰의 역할과 임기를 알려줘' },
  { tag: '인사', query: '유급직원의 조건과 복무·휴가 규정을 정리해줘' },
  { tag: '서식', query: '학습세례 신청서 양식과 제출 안내를 찾아줘' },
];

const MODE_LABELS: Record<string, string> = {
  auto: '자동',
  practical: '실무 정리',
  strict: '원문 엄격',
  advisory: '적용·제안',
  instant: '즉시 검색',
};

const MOBILE_MODE_OPTS: Array<{ id: AnswerMode; label: string; desc: string }> = [
  { id: 'auto', label: '자동', desc: '질문 성격을 파악해 원문 엄격·실무 정리·적용 제안을 스스로 조합합니다.' },
  { id: 'practical', label: '실무', desc: '조항 근거를 바탕으로 절차·요건·기한을 표와 체크리스트로 정리합니다.' },
  { id: 'strict', label: '원문', desc: '규정 원문 조항만 엄격히 인용하며 추측이나 확대 해석을 배제합니다.' },
  { id: 'advisory', label: '제안', desc: '원문 근거에 더해 실무 적용 주의점과 행정 실행안을 함께 제안합니다.' },
];

const ChatComposer = memo<{
  busy: boolean;
  instantMode: boolean;
  doubleVerify: boolean;
  selectedDocCount: number;
  onInstantToggle: (v: boolean) => void;
  onDoubleVerifyToggle: (v: boolean) => void;
  onSend: (query: string) => void;
}>(({ busy, instantMode, doubleVerify, selectedDocCount, onInstantToggle, onDoubleVerifyToggle, onSend }) => {
  const [input, setInput] = useState('');

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const q = input.trim();
    if (!q || busy) return;
    setInput('');
    onSend(q);
  };

  return (
    <div className="bg-gradient-to-t from-white via-white to-white/85 px-3.5 pt-1.5 pb-3 sm:px-6 sm:pb-4">
      <div className="mx-auto max-w-[700px] space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5 px-1">
          <button
            type="button"
            onClick={() => onInstantToggle(!instantMode)}
            title="AI 호출 없이 0.05초 만에 오프라인 원문 조항을 바로 찾습니다"
            className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition ${
              instantMode
                ? 'bg-amber-100 text-amber-900 ring-1 ring-amber-300/80'
                : 'text-[#71717a] hover:bg-black/[0.045] hover:text-[#18181b]'
            }`}
          >
            <Zap className="h-3 w-3" />
            <span>즉시 원문 검색</span>
          </button>

          {!instantMode && (
            <button
              type="button"
              onClick={() => onDoubleVerifyToggle(!doubleVerify)}
              title="답변 생성 후 AI가 원본 조항·숫자·쪽수를 1:1 재대조합니다"
              className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition ${
                doubleVerify
                  ? 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200'
                  : 'text-[#71717a] hover:bg-black/[0.045] hover:text-[#18181b]'
              }`}
            >
              <ShieldCheck className="h-3 w-3" />
              <span>이중 원문 재대조</span>
            </button>
          )}
        </div>

        <form onSubmit={submit}>
          <div className="flex items-end gap-2 rounded-2xl border border-black/[0.12] bg-[#fafaf9] p-1.5 pl-3.5 transition focus-within:border-[#18181b]/50 focus-within:bg-white focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.05)]">
            <textarea
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={
                selectedDocCount === 0
                  ? '검색 자료를 먼저 선택하세요'
                  : instantMode
                    ? '키워드·조항 즉시 검색...'
                    : '법규·행정 규정에 대해 질문하세요...'
              }
              disabled={selectedDocCount === 0}
              className="h-[38px] max-h-28 min-w-0 flex-1 resize-none bg-transparent py-2 text-[16px] leading-5 text-[#18181b] placeholder-[#a1a1aa] outline-none disabled:opacity-45 lg:text-[14px]"
            />
            <button
              type="submit"
              disabled={!input.trim() || busy || selectedDocCount === 0}
              aria-label="질문 전송"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#18181b] text-white transition hover:bg-[#27272a] disabled:bg-black/[0.08] disabled:text-[#a1a1aa]"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" strokeWidth={2.2} />}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
});
ChatComposer.displayName = 'ChatComposer';

export const ChatPanel: React.FC<Props> = memo(({
  notebook,
  activeSession = null,
  messages,
  mode,
  instantMode,
  doubleVerify,
  selectedDocCount,
  totalDocCount,
  busy,
  onModeChange,
  onInstantToggle,
  onDoubleVerifyToggle,
  onSend,
  onOpenViewer,
  onOpenAutofill,
}) => {
  const [openCites, setOpenCites] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string>('');
  const [exportingId, setExportingId] = useState<string>('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const toggleCites = (msgId: string) => {
    setOpenCites((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const copyMessage = (msgId: string, content: string) => {
    navigator.clipboard?.writeText(content).catch(() => {});
    setCopiedId(msgId);
    setTimeout(() => setCopiedId(''), 1800);
  };

  const handleExportReport = async (msg: ChatMessage, msgIdx: number) => {
    if (exportingId) return;
    setExportingId(msg.id);
    let question = '법규·행정 검토 질의';
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        question = messages[i].content;
        break;
      }
    }
    try {
      const res = await api.exportReportDocx({
        notebook_name: notebook?.name || '목포사랑의교회 행정Q&A',
        question,
        answer: msg.content,
        mode: msg.mode,
        citations: msg.citations,
        verification: msg.verification,
      });
      await triggerTicketDownload(res.download_url, res.filename);
    } catch {
      // ignore
    } finally {
      setExportingId('');
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      {/* Mobile-only compact 4-mode bar */}
      <div className="flex items-center justify-between gap-2 border-b border-black/[0.06] bg-[#fafaf9] px-3 py-1.5 lg:hidden">
        <div className="inline-flex rounded-lg bg-black/[0.05] p-0.5">
          {MOBILE_MODE_OPTS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              title={opt.desc}
              onClick={() => onModeChange(opt.id)}
              className={`chip-nowrap rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                mode === opt.id ? 'bg-white text-[#18181b] shadow-2xs' : 'text-[#71717a]'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <span className="chip-nowrap text-[11px] font-medium text-[#8a8a8e]">
          {selectedDocCount}/{totalDocCount}
        </span>
      </div>

      {/* Group Collaborative Chat Banner */}
      {activeSession && (activeSession.group_id || activeSession.is_shared) && (
        <div className="flex items-center justify-between gap-2 border-b border-[#0f4c81]/15 bg-[#0f4c81]/[0.04] px-4 py-1.5 text-[11.5px] text-[#0f4c81]">
          <div className="flex min-w-0 items-center gap-1.5">
            <Users className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate font-semibold">
              {activeSession.group_id
                ? `${activeSession.group_name || '그룹'} 공동 대화`
                : '전체 팀 공유 대화'}
            </span>
            <span className="hidden truncate text-[#52525b] sm:inline">
              · 참여자 누구나 이어서 질문할 수 있으며 실시간으로 동기화됩니다
            </span>
          </div>
        </div>
      )}

      {/* Serene Editorial Canvas */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
        <div className="mx-auto w-full max-w-[700px] space-y-6">
          {messages.length === 0 ? (
            <div className="pt-8 pb-6 sm:pt-16">
              <div className="mb-8 space-y-1.5">
                <p className="text-[11px] font-semibold tracking-[0.06em] text-[#0f4c81] uppercase">
                  MOKPO SARANG ARCHIVE
                </p>
                <h2 className="text-[22px] font-semibold tracking-tight text-[#18181b] sm:text-[26px]">
                  목포사랑의교회 행정Q&amp;A
                </h2>
                <p className="text-[13px] text-[#71717a]">
                  헌법 · 정관 · 시행세칙 · 해설서 원문 근거로 답변하고 공문 서식을 바로 작성합니다.
                </p>
              </div>

              {/* Refined Editorial Hairline Quick Prompts (No boxy ChatGPT starter cards) */}
              <div className="divide-y divide-black/[0.06] border-y border-black/[0.06]">
                {DEFAULT_PROMPTS.map((item) => (
                  <button
                    key={item.query}
                    type="button"
                    disabled={busy || selectedDocCount === 0}
                    onClick={() => onSend(item.query)}
                    className="group flex w-full items-center justify-between gap-3 py-3 text-left transition hover:bg-[#fafaf9] disabled:opacity-40 sm:px-2"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="chip-nowrap w-9 shrink-0 text-[11px] font-semibold text-[#8a8a8e] group-hover:text-[#0f4c81]">
                        {item.tag}
                      </span>
                      <span className="truncate text-[13.5px] font-medium text-[#27272a] group-hover:text-[#18181b]">
                        {item.query}
                      </span>
                    </div>
                    <ArrowUpRight className="h-4 w-4 shrink-0 text-[#a1a1aa] transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-[#18181b]" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, msgIdx) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'user' ? (
                  <div className="flex max-w-[85%] flex-col items-end gap-1 sm:max-w-[76%]">
                    {msg.author_label && (activeSession?.group_id || activeSession?.is_shared) && (
                      <span className="px-1 text-[10.5px] font-medium text-[#71717a]">{msg.author_label}</span>
                    )}
                    <div
                      data-bubble="user"
                      className="rounded-2xl rounded-br-sm bg-[#18181b] px-4 py-2.5 text-[14px] leading-relaxed text-white"
                    >
                      {msg.content}
                    </div>
                  </div>
                ) : (
                  <div className="group w-full min-w-0 space-y-3">
                    {/* Clean borderless editorial reading block */}
                    <div className="border-b border-black/[0.06] pb-4">
                      {msg.statusText && msg.streaming && (
                        <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-[#f7f7f5] px-3 py-1 text-xs font-medium text-[#3f3f46] ring-1 ring-black/[0.06]">
                          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[#0f4c81]" />
                          <span>{msg.statusText}</span>
                        </div>
                      )}

                      {msg.hasEvidence === false && !msg.streaming && (
                        <div className="mb-2.5 inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 ring-1 ring-amber-200/70">
                          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                          <span>선택된 자료에서 근거 미발견</span>
                        </div>
                      )}

                      {msg.content ? (
                        <MarkdownView content={msg.content} />
                      ) : (
                        msg.streaming && (
                          <div className="flex items-center gap-2 py-1 text-xs text-[#8a8a8e]">
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-[#0f4c81]" />
                            <span>근거 자료를 정리하고 있습니다...</span>
                          </div>
                        )
                      )}

                      {/* Quiet Metadata & Hover Actions Strip */}
                      {!msg.streaming && msg.content && (
                        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 pt-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            {msg.citations.length > 0 && (
                              <button
                                type="button"
                                onClick={() => toggleCites(msg.id)}
                                className="chip-nowrap inline-flex items-center gap-1.5 rounded-md bg-[#f7f7f5] px-2.5 py-1 text-[11.5px] font-semibold text-[#18181b] ring-1 ring-black/[0.07] transition hover:bg-[#ededeb]"
                              >
                                <BookOpen className="h-3.5 w-3.5 text-[#0f4c81]" />
                                <span>근거 원문 {msg.citations.length}건</span>
                                {openCites[msg.id] ? (
                                  <ChevronUp className="h-3.5 w-3.5 text-[#71717a]" />
                                ) : (
                                  <ChevronDown className="h-3.5 w-3.5 text-[#71717a]" />
                                )}
                              </button>
                            )}

                            {msg.verification && msg.verification.status !== 'no_evidence' && (
                              <span
                                title={msg.verification.summary}
                                className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium ${
                                  msg.verification.status === 'verified'
                                    ? 'bg-emerald-50/90 text-emerald-800 ring-1 ring-emerald-200/70'
                                    : 'bg-amber-50 text-amber-800 ring-1 ring-amber-200/70'
                                }`}
                              >
                                {msg.verification.status === 'verified' ? (
                                  <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
                                ) : (
                                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                                )}
                                <span>
                                  {msg.verification.status === 'verified'
                                    ? msg.verification.double_verified
                                      ? '이중 검증됨'
                                      : '근거 검증됨'
                                    : '원문 확인 권장'}
                                </span>
                              </span>
                            )}

                            <span className="chip-nowrap text-[11px] text-[#8a8a8e]">
                              {MODE_LABELS[msg.mode] || msg.mode}
                            </span>
                          </div>

                          <div className="mac-hover-reveal flex items-center gap-1">
                            {msg.hasEvidence !== false && (
                              <button
                                type="button"
                                disabled={exportingId === msg.id}
                                onClick={() => void handleExportReport(msg, msgIdx)}
                                title="당회·제직회 보고용 Word(.docx) 문서로 내보내기"
                                className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b] disabled:opacity-50"
                              >
                                {exportingId === msg.id ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <FileDown className="h-3.5 w-3.5" />
                                )}
                                <span>보고서 DOCX</span>
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => copyMessage(msg.id, msg.content)}
                              title="답변 복사"
                              className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-[#71717a] transition hover:bg-black/[0.05] hover:text-[#18181b]"
                            >
                              {copiedId === msg.id ? (
                                <>
                                  <Check className="h-3.5 w-3.5 text-emerald-700" />
                                  <span className="text-emerald-700">복사됨</span>
                                </>
                              ) : (
                                <>
                                  <Copy className="h-3.5 w-3.5" />
                                  <span>복사</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Collapsible Citations */}
                    {openCites[msg.id] && msg.citations.length > 0 && (
                      <div className="space-y-2 rounded-xl border border-black/[0.07] bg-[#fafaf9] p-3">
                        {msg.citations.map((c: Citation, idx: number) => (
                          <div key={`${c.chunk_id}-${idx}`} className="rounded-lg border border-black/[0.06] bg-white p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="min-w-0 flex-1">
                                <span className="text-xs font-semibold text-[#18181b]">{c.doc_title}</span>
                                {(c.section_path || c.heading) && (
                                  <p className="truncate text-[11px] text-[#71717a]">
                                    {[c.section_path, c.heading].filter(Boolean).join(' · ')}
                                  </p>
                                )}
                              </div>
                              <button
                                type="button"
                                onClick={() => onOpenViewer(c.doc_id, c.page_start, c.excerpt)}
                                className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#f7f7f5] px-2 py-1 text-[11px] font-medium text-[#0f4c81] transition hover:bg-[#ededeb]"
                              >
                                <Eye className="h-3 w-3" />
                                <span>p.{c.page_start}</span>
                              </button>
                            </div>
                            <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-[#3f3f46]">
                              {c.excerpt}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Inline Related Forms */}
                    {msg.forms.length > 0 && (
                      <div className="space-y-2 rounded-xl border border-black/[0.07] bg-[#fafaf9] p-3">
                        <div className="flex items-center gap-1.5 text-xs font-semibold text-[#18181b]">
                          <FileText className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                          <span>관련 서식 · 표</span>
                        </div>
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {msg.forms.map((f) => (
                            <div key={f.id} className="rounded-lg border border-black/[0.06] bg-white p-2.5">
                              <p className="truncate text-xs font-semibold text-[#18181b]">{f.title}</p>
                              <p className="mt-0.5 truncate text-[11px] text-[#8a8a8e]">
                                {f.doc_title} · p.{f.page_start}
                              </p>
                              <div className="mt-2 flex flex-wrap items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => void triggerTicketDownload(`/api/forms/${f.id}/download/pdf`, `${f.title}.pdf`)}
                                  className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#f7f7f5] px-2 py-1 text-[11px] font-medium text-[#18181b] hover:bg-[#ededeb]"
                                >
                                  <Download className="h-3 w-3" />
                                  <span>PDF</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={() => onOpenAutofill(f)}
                                  className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#18181b] px-2 py-1 text-[11px] font-medium text-white hover:bg-[#27272a]"
                                >
                                  <FileEdit className="h-3 w-3" />
                                  <span>서식 작성</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void triggerTicketDownload(`/api/forms/${f.id}/download/docx`, `${f.title}.docx`)}
                                  className="chip-nowrap inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]"
                                >
                                  <FileText className="h-3 w-3" />
                                  <span>DOCX</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void triggerTicketDownload(`/api/forms/${f.id}/download/xlsx`, `${f.title}.xlsx`)}
                                  className="chip-nowrap inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]"
                                >
                                  <FileSpreadsheet className="h-3 w-3" />
                                  <span>XLSX</span>
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Isolated Editorial Composer (typing never re-renders chat messages!) */}
      <ChatComposer
        busy={busy}
        instantMode={instantMode}
        doubleVerify={doubleVerify}
        selectedDocCount={selectedDocCount}
        onInstantToggle={onInstantToggle}
        onDoubleVerifyToggle={onDoubleVerifyToggle}
        onSend={onSend}
      />
    </div>
  );
});
ChatPanel.displayName = 'ChatPanel';
