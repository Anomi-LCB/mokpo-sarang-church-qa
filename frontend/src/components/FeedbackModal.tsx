import React, { useState } from 'react';
import { Bug, CheckCircle2, Download, Flag, Lightbulb, Loader2, Lock, Send, Sparkles, Wrench, X } from 'lucide-react';
import { api } from '../api';
import type { FeedbackCategory } from '../types';

interface Props {
  contextInfo: string;
  isOfflineMode?: boolean;
  onClose: () => void;
}

const CATEGORIES: Array<{ id: FeedbackCategory; label: string; icon: React.ReactNode }> = [
  { id: 'bug', label: '버그 · 오류', icon: <Bug className="h-3.5 w-3.5" /> },
  { id: 'ux', label: '사용 불편', icon: <Wrench className="h-3.5 w-3.5" /> },
  { id: 'feature', label: '기능 개선', icon: <Lightbulb className="h-3.5 w-3.5" /> },
  { id: 'doc', label: '자료 · 서식 요청', icon: <Sparkles className="h-3.5 w-3.5" /> },
];

export const FeedbackModal: React.FC<Props> = ({ contextInfo, isOfflineMode = false, onClose }) => {
  const [category, setCategory] = useState<FeedbackCategory>('bug');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [includeDiag, setIncludeDiag] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState<{ id: number; relayed: boolean } | null>(null);

  const buildDiagInfo = () => {
    if (!includeDiag) return '';
    const w = typeof window !== 'undefined' ? `${window.innerWidth}x${window.innerHeight}` : '';
    const ua = typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 120) : '';
    return `화면:${w} | ${ua}`;
  };

  const handleExportJsonFile = () => {
    const payload = {
      app: '목포사랑의교회 행정Q&A',
      category,
      title: title.trim() || '(제목 없음)',
      description: description.trim(),
      device_info: buildDiagInfo(),
      context_info: includeDiag ? contextInfo : '',
      created_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `행정QA_제보_${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (title.trim().length < 2 || description.trim().length < 4 || busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.submitFeedback({
        category,
        title: title.trim(),
        description: description.trim(),
        device_info: buildDiagInfo(),
        context_info: includeDiag ? contextInfo : '',
      });
      setSubmitted({ id: res.id, relayed: res.relayed_remote });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : '전송하지 못했습니다. 오프라인 상태라면 아래 [제보 파일 저장]을 이용해 주세요.'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[480px] overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.07] bg-[#fafaf9] px-5 py-3.5">
          <div className="flex items-center gap-2">
            <Flag className="h-4 w-4 text-[#0f4c81]" />
            <h3 className="text-sm font-semibold text-[#18181b]">버그 · 불편사항 · 개선 제보</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-lg p-1 text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {submitted ? (
          <div className="space-y-4 p-6 text-center">
            <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-semibold text-[#18181b]">제작자 비공개 제보함으로 접수되었습니다</p>
              <p className="text-xs text-[#71717a]">
                접수 번호 #{submitted.id}
                {submitted.relayed ? ' · 제작자 메인 서버로 즉시 전달됨' : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="chip-nowrap rounded-lg bg-[#18181b] px-5 py-2 text-xs font-semibold text-white hover:bg-[#27272a]"
            >
              확인
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 p-5">
            <div className="flex items-start gap-2 rounded-lg border border-black/[0.06] bg-[#fafaf9] px-3 py-2 text-[11.5px] text-[#52525b]">
              <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
              <span>보내주신 내용은 제작자 전용 암호로 보호되는 비공개 수신함에만 기록됩니다.</span>
            </div>

            <div>
              <label className="mb-1.5 block text-[11.5px] font-medium text-[#52525b]">유형 선택</label>
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                {CATEGORIES.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setCategory(c.id)}
                    className={`chip-nowrap inline-flex items-center justify-center gap-1 rounded-lg border px-2 py-2 text-[11.5px] font-medium transition ${
                      category === c.id
                        ? 'border-[#18181b] bg-[#18181b] text-white'
                        : 'border-black/[0.08] bg-white text-[#52525b] hover:bg-[#f7f7f5]'
                    }`}
                  >
                    {c.icon}
                    <span>{c.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-1 block text-[11.5px] font-medium text-[#52525b]">한 줄 요약</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="예: 시행세칙 특정 조항 검색 시 결과 누락 / 모바일 버튼 개선 요청"
                className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-[16px] text-[#18181b] outline-none focus:border-[#18181b] lg:text-xs"
              />
            </div>

            <div>
              <label className="mb-1 block text-[11.5px] font-medium text-[#52525b]">자세한 내용</label>
              <textarea
                rows={4}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="어떤 상황에서 불편하거나 오류가 있었는지 편하게 적어 주세요."
                className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-[16px] leading-relaxed text-[#18181b] outline-none focus:border-[#18181b] lg:text-xs"
              />
            </div>

            <label className="flex cursor-pointer items-center gap-2 text-[11.5px] text-[#52525b]">
              <input
                type="checkbox"
                checked={includeDiag}
                onChange={(e) => setIncludeDiag(e.target.checked)}
                className="accent-[#18181b]"
              />
              <span>현재 화면 크기·모드 등 기본 진단 정보 함께 첨부</span>
            </label>

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.06] pt-3">
              <button
                type="button"
                onClick={handleExportJsonFile}
                disabled={!title.trim() && !description.trim()}
                title="오프라인 PC에서 제보 내용을 파일로 저장해 제작자에게 전달할 수 있습니다"
                className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs font-medium text-[#52525b] hover:bg-[#f7f7f5] disabled:opacity-40"
              >
                <Download className="h-3.5 w-3.5" />
                <span>파일 저장</span>
              </button>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="chip-nowrap rounded-lg px-3 py-2 text-xs font-medium text-[#71717a] hover:bg-black/[0.04]"
                >
                  취소
                </button>
                <button
                  type="submit"
                  disabled={isOfflineMode || title.trim().length < 2 || description.trim().length < 4 || busy}
                  className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#27272a] disabled:opacity-40"
                >
                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                  <span>{isOfflineMode ? '오프라인 (파일 저장 이용)' : '제작자에게 보내기'}</span>
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
