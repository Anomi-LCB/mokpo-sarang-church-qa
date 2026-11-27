import React, { useMemo, useState } from 'react';
import { Columns2, Sparkles, X } from 'lucide-react';
import type { StdProposal } from '../types';

interface Props {
  proposal: StdProposal;
  onClose: () => void;
}

interface DiffLine {
  text: string;
  kind: 'same' | 'changed';
}

function buildSideLines(leftText: string, rightText: string): { left: DiffLine[]; right: DiffLine[] } {
  const lLines = (leftText || '')
    .split('\n')
    .map((s) => s.trimEnd())
    .filter((s, idx, arr) => s.length > 0 || (idx > 0 && arr[idx - 1].length > 0));
  const rLines = (rightText || '')
    .split('\n')
    .map((s) => s.trimEnd())
    .filter((s, idx, arr) => s.length > 0 || (idx > 0 && arr[idx - 1].length > 0));

  const norm = (s: string) => s.replace(/\s+/g, ' ').trim();
  const rSet = new Set(rLines.map(norm).filter(Boolean));
  const lSet = new Set(lLines.map(norm).filter(Boolean));

  return {
    left: lLines.map((text) => ({
      text,
      kind: !norm(text) || rSet.has(norm(text)) ? 'same' : 'changed',
    })),
    right: rLines.map((text) => ({
      text,
      kind: !norm(text) || lSet.has(norm(text)) ? 'same' : 'changed',
    })),
  };
}

export const StdProposalCompareModal: React.FC<Props> = ({ proposal, onClose }) => {
  const opts = proposal.options || [];
  const defaultRight = opts.find((o) => o.is_ai_improved)?.id || opts[1]?.id || opts[0]?.id || '';
  const defaultLeft = opts.find((o) => o.id !== defaultRight)?.id || opts[0]?.id || '';

  const [leftId, setLeftId] = useState(defaultLeft);
  const [rightId, setRightId] = useState(defaultRight);

  const leftOpt = useMemo(() => opts.find((o) => o.id === leftId) || opts[0], [opts, leftId]);
  const rightOpt = useMemo(() => opts.find((o) => o.id === rightId) || opts[1] || opts[0], [opts, rightId]);

  const compared = useMemo(
    () => buildSideLines(leftOpt?.content_md || '', rightOpt?.content_md || ''),
    [leftOpt, rightOpt]
  );

  const leftChangedCount = compared.left.filter((l) => l.kind === 'changed').length;
  const rightChangedCount = compared.right.filter((l) => l.kind === 'changed').length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <Columns2 className="h-4 w-4 shrink-0 text-[#0f4c81]" />
              <h3 className="truncate text-sm font-semibold text-[#18181b]">
                후보안 나란히 비교 · {proposal.cluster_title}
              </h3>
            </div>
            <p className="mt-0.5 text-[11px] text-[#71717a]">
              두 안건에서 서로 달라진 문장을 색상으로 표시합니다. (왼쪽 고유 문구 {leftChangedCount}줄 · 오른쪽 변경/추가 문구 {rightChangedCount}줄)
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-lg p-1.5 text-[#71717a] hover:bg-black/[0.06]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Selectors */}
        <div className="grid grid-cols-1 gap-2 border-b border-black/[0.07] bg-[#f7f7f5] px-5 py-2.5 sm:grid-cols-2">
          <div className="flex items-center gap-2">
            <span className="chip-nowrap rounded bg-amber-100 px-2 py-0.5 text-[10.5px] font-semibold text-amber-900">
              기준 안
            </span>
            <select
              value={leftId}
              onChange={(e) => setLeftId(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs font-semibold text-[#18181b]"
            >
              {opts.map((o) => (
                <option key={o.id} value={o.id}>
                  [{o.label}] {o.title} ({o.vote_count}표)
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="chip-nowrap inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-900">
              <Sparkles className="h-3 w-3" />
              <span>비교 안</span>
            </span>
            <select
              value={rightId}
              onChange={(e) => setRightId(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs font-semibold text-[#18181b]"
            >
              {opts.map((o) => (
                <option key={o.id} value={o.id}>
                  [{o.label}] {o.title} ({o.vote_count}표)
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Side-by-Side Diff Columns */}
        <div className="grid flex-1 grid-cols-1 divide-y divide-black/[0.08] overflow-y-auto sm:grid-cols-2 sm:divide-x sm:divide-y-0">
          <div className="min-w-0 p-4 space-y-1.5">
            <p className="mb-2 text-xs font-semibold text-[#18181b]">
              [{leftOpt?.label}] {leftOpt?.title}
            </p>
            {compared.left.length === 0 ? (
              <p className="text-xs text-[#8a8a8e]">내용 없음</p>
            ) : (
              compared.left.map((ln, i) => (
                <div
                  key={i}
                  className={`rounded px-2.5 py-1 text-xs leading-relaxed whitespace-pre-wrap ${
                    ln.kind === 'changed'
                      ? 'border-l-2 border-amber-500 bg-amber-50 text-[#18181b]'
                      : 'text-[#52525b]'
                  }`}
                >
                  {ln.text || ' '}
                </div>
              ))
            )}
          </div>

          <div className="min-w-0 p-4 space-y-1.5">
            <p className="mb-2 text-xs font-semibold text-[#0f4c81]">
              [{rightOpt?.label}] {rightOpt?.title}
            </p>
            {compared.right.length === 0 ? (
              <p className="text-xs text-[#8a8a8e]">내용 없음</p>
            ) : (
              compared.right.map((ln, i) => (
                <div
                  key={i}
                  className={`rounded px-2.5 py-1 text-xs leading-relaxed whitespace-pre-wrap ${
                    ln.kind === 'changed'
                      ? 'border-l-2 border-emerald-600 bg-emerald-50 text-[#18181b]'
                      : 'text-[#52525b]'
                  }`}
                >
                  {ln.text || ' '}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-black/[0.08] bg-[#fafaf9] px-5 py-3">
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-[#71717a]">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-xs bg-amber-300" />
              기준 안 고유 문장
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-xs bg-emerald-400" />
              비교 안 보완·추가 문장
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="chip-nowrap rounded-lg bg-[#18181b] px-4 py-1.5 text-xs font-semibold text-white hover:bg-[#27272a]"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
};
