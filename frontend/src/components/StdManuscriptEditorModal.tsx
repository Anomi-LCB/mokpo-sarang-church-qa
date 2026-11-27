import React, { useState } from 'react';
import {
  AlertTriangle,
  BookCheck,
  CheckCircle2,
  FileDiff,
  Loader2,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import type { StdDiffReport, StdManuscriptDraft } from '../types';

interface EditorProps {
  versionLabel: string;
  initialManuscript: StdManuscriptDraft;
  lawAudit: Array<{ source: string; status: string; note: string }>;
  finalizing: boolean;
  onFinalize: (edited: StdManuscriptDraft, version: string) => void;
  onClose: () => void;
}

export const StdManuscriptEditorModal: React.FC<EditorProps> = ({
  versionLabel,
  initialManuscript,
  lawAudit,
  finalizing,
  onFinalize,
  onClose,
}) => {
  const [ver, setVer] = useState(versionLabel);
  const [draft, setDraft] = useState<StdManuscriptDraft>(() => JSON.parse(JSON.stringify(initialManuscript)));
  const [activeTab, setActiveTab] = useState<'chapters' | 'forms' | 'audit'>('chapters');

  const updateChapter = (cIdx: number, patch: Partial<StdManuscriptDraft['chapters'][number]>) => {
    setDraft((prev) => ({
      ...prev,
      chapters: prev.chapters.map((ch, i) => (i === cIdx ? { ...ch, ...patch } : ch)),
    }));
  };

  const updateArticle = (
    cIdx: number,
    aIdx: number,
    patch: Partial<StdManuscriptDraft['chapters'][number]['articles'][number]>
  ) => {
    setDraft((prev) => ({
      ...prev,
      chapters: prev.chapters.map((ch, i) =>
        i === cIdx
          ? { ...ch, articles: ch.articles.map((art, j) => (j === aIdx ? { ...art, ...patch } : art)) }
          : ch
      ),
    }));
  };

  const addArticle = (cIdx: number) => {
    setDraft((prev) => ({
      ...prev,
      chapters: prev.chapters.map((ch, i) =>
        i === cIdx
          ? {
              ...ch,
              articles: [
                ...ch.articles,
                {
                  number: `제${ch.articles.length + 1}조`,
                  title: '새 조항',
                  body: '',
                  points: [],
                  practical_tip: '',
                },
              ],
            }
          : ch
      ),
    }));
  };

  const removeArticle = (cIdx: number, aIdx: number) => {
    setDraft((prev) => ({
      ...prev,
      chapters: prev.chapters.map((ch, i) =>
        i === cIdx ? { ...ch, articles: ch.articles.filter((_, j) => j !== aIdx) } : ch
      ),
    }));
  };

  const updateForm = (fIdx: number, patch: Partial<NonNullable<StdManuscriptDraft['standard_forms']>[number]>) => {
    setDraft((prev) => ({
      ...prev,
      standard_forms: (prev.standard_forms || []).map((fm, i) => (i === fIdx ? { ...fm, ...patch } : fm)),
    }));
  };

  const conflictCnt = lawAudit.filter((a) => a.status.includes('충돌')).length;
  const warnCnt = lawAudit.filter((a) => a.status.includes('권고') || a.status.includes('보완')).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="flex h-[88dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[#18181b]">
              출판 전 원고 초안 검토 · 직접 편집
            </h3>
            <p className="mt-0.5 text-[11px] text-[#71717a]">
              장·조항 본문과 표준 서식 항목을 최종 확인·수정한 뒤 PDF · Word · 한글(HWPX) 3종으로 한 번에 조판합니다.
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

        {/* Title + Sub-tabs */}
        <div className="space-y-2.5 border-b border-black/[0.07] bg-[#f7f7f5] px-5 py-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-12">
            <input
              type="text"
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="규정집 공식 제목"
              className="rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-semibold text-[#18181b] sm:col-span-6"
            />
            <input
              type="text"
              value={draft.subtitle || ''}
              onChange={(e) => setDraft({ ...draft, subtitle: e.target.value })}
              placeholder="부제목"
              className="rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs text-[#3f3f46] sm:col-span-4"
            />
            <input
              type="text"
              value={ver}
              onChange={(e) => setVer(e.target.value)}
              placeholder="판본 (예: v1.0)"
              className="rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-semibold text-[#0f4c81] sm:col-span-2"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setActiveTab('chapters')}
              className={`chip-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold ${
                activeTab === 'chapters' ? 'bg-[#18181b] text-white' : 'bg-white text-[#52525b] hover:bg-black/[0.04]'
              }`}
            >
              본문 장 · 조항 ({draft.chapters.length}개 장)
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('forms')}
              className={`chip-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold ${
                activeTab === 'forms' ? 'bg-[#18181b] text-white' : 'bg-white text-[#52525b] hover:bg-black/[0.04]'
              }`}
            >
              표준 서식 ({(draft.standard_forms || []).length}종)
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('audit')}
              className={`chip-nowrap inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold ${
                activeTab === 'audit' ? 'bg-[#0f4c81] text-white' : 'bg-white text-[#52525b] hover:bg-black/[0.04]'
              }`}
            >
              <span>법규 위계 감사 ({lawAudit.length}건)</span>
              {conflictCnt > 0 && (
                <span className="rounded bg-red-600 px-1.5 py-0.2 text-[10px] text-white">충돌 {conflictCnt}</span>
              )}
              {conflictCnt === 0 && warnCnt > 0 && (
                <span className="rounded bg-amber-500 px-1.5 py-0.2 text-[10px] text-white">권고 {warnCnt}</span>
              )}
            </button>
          </div>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {activeTab === 'chapters' && (
            <>
              <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3.5 space-y-1.5">
                <label className="text-[11px] font-semibold text-[#52525b]">표지 요약문</label>
                <textarea
                  rows={2}
                  value={draft.executive_summary || ''}
                  onChange={(e) => setDraft({ ...draft, executive_summary: e.target.value })}
                  className="w-full rounded-lg border border-black/[0.1] bg-white p-2.5 text-xs leading-relaxed"
                />
              </div>

              {draft.chapters.map((ch, cIdx) => (
                <div key={cIdx} className="rounded-xl border border-black/[0.09] bg-white p-4 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      value={ch.title}
                      onChange={(e) => updateChapter(cIdx, { title: e.target.value })}
                      className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-[#fafaf9] px-3 py-1.5 text-xs font-bold text-[#18181b]"
                    />
                    <button
                      type="button"
                      onClick={() => addArticle(cIdx)}
                      className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-[11px] font-semibold text-[#0f4c81] hover:bg-[#0f4c81]/5"
                    >
                      <Plus className="h-3 w-3" />
                      <span>조항 추가</span>
                    </button>
                  </div>

                  <div className="space-y-2.5">
                    {ch.articles.map((art, aIdx) => (
                      <div key={aIdx} className="rounded-lg border border-black/[0.07] bg-[#fafaf9] p-3 space-y-2">
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={art.number}
                            onChange={(e) => updateArticle(cIdx, aIdx, { number: e.target.value })}
                            className="w-20 rounded-md border border-black/[0.1] bg-white px-2 py-1 text-xs font-bold text-[#0f4c81]"
                          />
                          <input
                            type="text"
                            value={art.title}
                            onChange={(e) => updateArticle(cIdx, aIdx, { title: e.target.value })}
                            className="min-w-0 flex-1 rounded-md border border-black/[0.1] bg-white px-2.5 py-1 text-xs font-semibold text-[#18181b]"
                          />
                          <button
                            type="button"
                            onClick={() => removeArticle(cIdx, aIdx)}
                            title="조항 삭제"
                            className="rounded p-1 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <textarea
                          rows={2}
                          value={art.body}
                          onChange={(e) => updateArticle(cIdx, aIdx, { body: e.target.value })}
                          placeholder="조항 본문"
                          className="w-full rounded-md border border-black/[0.1] bg-white p-2 text-xs leading-relaxed"
                        />
                        <input
                          type="text"
                          value={art.practical_tip || ''}
                          onChange={(e) => updateArticle(cIdx, aIdx, { practical_tip: e.target.value })}
                          placeholder="실무 가이드 한 줄 메모 (선택)"
                          className="w-full rounded-md border border-black/[0.08] bg-white px-2.5 py-1 text-[11px] text-[#52525b]"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}

          {activeTab === 'forms' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-[#52525b]">
                  편찬 완료 후 오른쪽 [서식·표 보관함]에 1클릭 등록하여 전 교역자가 바로 작성·출력할 수 있습니다.
                </p>
                <button
                  type="button"
                  onClick={() =>
                    setDraft((prev) => ({
                      ...prev,
                      standard_forms: [
                        ...(prev.standard_forms || []),
                        {
                          title: '새 표준 행정 서식',
                          purpose: '교회 공식 행정 제출용',
                          fields: ['작성일', '소속 부서', '성명 / 직분', '연락처', '상세 내용 및 사유'],
                        },
                      ],
                    }))
                  }
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3 py-1.5 text-xs font-semibold text-white"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>서식 추가</span>
                </button>
              </div>
              {(draft.standard_forms || []).map((fm, fIdx) => (
                <div key={fIdx} className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4 space-y-2.5">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={fm.title}
                      onChange={(e) => updateForm(fIdx, { title: e.target.value })}
                      className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-semibold"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setDraft((prev) => ({
                          ...prev,
                          standard_forms: (prev.standard_forms || []).filter((_, i) => i !== fIdx),
                        }))
                      }
                      className="rounded p-1.5 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <input
                    type="text"
                    value={fm.purpose || ''}
                    onChange={(e) => updateForm(fIdx, { purpose: e.target.value })}
                    placeholder="서식 용도"
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs"
                  />
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#71717a]">
                      기입 항목 (쉼표로 구분)
                    </label>
                    <input
                      type="text"
                      value={(fm.fields || []).join(', ')}
                      onChange={(e) =>
                        updateForm(fIdx, {
                          fields: e.target.value
                            .split(',')
                            .map((x) => x.trim())
                            .filter(Boolean),
                        })
                      }
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs"
                    />
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === 'audit' && (
            <div className="space-y-2.5">
              {lawAudit.length === 0 ? (
                <div className="rounded-xl border border-dashed border-black/[0.12] p-8 text-center text-xs text-[#8a8a8e]">
                  상위 법규 대조 결과가 없습니다.
                </div>
              ) : (
                lawAudit.map((la, i) => {
                  const isConflict = la.status.includes('충돌');
                  const isWarn = la.status.includes('권고') || la.status.includes('보완');
                  return (
                    <div
                      key={i}
                      className={`rounded-xl border p-3.5 space-y-1 ${
                        isConflict
                          ? 'border-red-300 bg-red-50/70'
                          : isWarn
                            ? 'border-amber-300 bg-amber-50/70'
                            : 'border-emerald-200 bg-emerald-50/50'
                      }`}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        {isConflict ? (
                          <ShieldAlert className="h-4 w-4 text-red-700" />
                        ) : isWarn ? (
                          <AlertTriangle className="h-4 w-4 text-amber-700" />
                        ) : (
                          <ShieldCheck className="h-4 w-4 text-emerald-700" />
                        )}
                        <span
                          className={`chip-nowrap rounded px-2 py-0.5 text-[10.5px] font-bold ${
                            isConflict
                              ? 'bg-red-700 text-white'
                              : isWarn
                                ? 'bg-amber-600 text-white'
                                : 'bg-emerald-700 text-white'
                          }`}
                        >
                          {la.status}
                        </span>
                        <strong className="text-xs text-[#18181b]">{la.source}</strong>
                      </div>
                      <p className="text-xs leading-relaxed text-[#3f3f46]">{la.note}</p>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.08] bg-[#fafaf9] px-5 py-3">
          <span className="text-[11px] text-[#71717a]">
            최종 조판 시 PDF · Word(.docx) · 한글(.hwpx) 3종이 동시 생성됩니다.
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="chip-nowrap rounded-lg px-3.5 py-2 text-xs font-medium text-[#71717a] hover:bg-black/[0.05]"
            >
              취소
            </button>
            <button
              type="button"
              disabled={finalizing}
              onClick={() => onFinalize(draft, ver)}
              className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-50"
            >
              {finalizing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookCheck className="h-3.5 w-3.5" />}
              <span>{finalizing ? '조판 중...' : '편집본으로 PDF · Word · HWPX 최종 조판'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

interface DiffModalProps {
  title: string;
  diffReport: StdDiffReport;
  onClose: () => void;
}

export const StdDiffModal: React.FC<DiffModalProps> = ({ title, diffReport, onClose }) => {
  const rows = diffReport.rows || [];
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <FileDiff className="h-4 w-4 shrink-0 text-[#0f4c81]" />
              <h3 className="truncate text-sm font-semibold text-[#18181b]">
                신·구조문 대조표 · {title}
              </h3>
            </div>
            <p className="mt-0.5 text-[11px] text-[#71717a]">
              {diffReport.prev_version || '이전 판본'} → {diffReport.curr_version || '현재 판본'} · 신설 {diffReport.added_count || 0}건 · 개정 {diffReport.modified_count || 0}건 · 삭제 {diffReport.removed_count || 0}건 · 현행 유지 {diffReport.unchanged_count || 0}건
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

        <div className="flex-1 overflow-y-auto p-5">
          {rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-black/[0.12] p-10 text-center text-xs text-[#71717a]">
              <CheckCircle2 className="h-6 w-6 text-emerald-600" />
              <span>이전 판본과 비교하여 변경된 조항이 없습니다.</span>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-black/[0.08]">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="bg-[#f4f4f2] text-left text-[#18181b]">
                    <th className="w-[18%] border-b border-black/[0.08] px-3 py-2.5 font-semibold">조항 / 구분</th>
                    <th className="w-[41%] border-b border-l border-black/[0.08] px-3 py-2.5 font-semibold">
                      현행 ({diffReport.prev_version || '이전'})
                    </th>
                    <th className="w-[41%] border-b border-l border-black/[0.08] px-3 py-2.5 font-semibold">
                      개정안 ({diffReport.curr_version || '신규'})
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/[0.07]">
                  {rows.map((r, idx) => (
                    <tr key={idx} className="align-top">
                      <td className="px-3 py-2.5 font-semibold text-[#18181b]">
                        <div>{r.article}</div>
                        <span
                          className={`chip-nowrap mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            r.status === '신설'
                              ? 'bg-emerald-50 text-emerald-800'
                              : r.status === '삭제'
                                ? 'bg-red-50 text-red-700'
                                : 'bg-amber-50 text-amber-800'
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="border-l border-black/[0.07] px-3 py-2.5 whitespace-pre-wrap text-[#52525b]">
                        {r.before}
                      </td>
                      <td className="border-l border-black/[0.07] bg-[#fafaf9] px-3 py-2.5 whitespace-pre-wrap text-[#18181b]">
                        {r.after}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="flex justify-end border-t border-black/[0.08] bg-[#fafaf9] px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="chip-nowrap rounded-lg bg-[#18181b] px-4 py-1.5 text-xs font-semibold text-white"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
};
