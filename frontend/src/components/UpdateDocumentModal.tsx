import React, { useRef, useState } from 'react';
import { FileUp, Loader2, RefreshCw, Save, X } from 'lucide-react';
import { api } from '../api';
import type { DocumentItem } from '../types';

interface Props {
  doc: DocumentItem;
  onUpdated: () => void;
  onClose: () => void;
}

export const UpdateDocumentModal: React.FC<Props> = ({ doc, onUpdated, onClose }) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState(doc.title);
  const [category, setCategory] = useState(doc.category);
  const [priority, setPriority] = useState(doc.priority);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      if (file) {
        setProgress(6);
        setStatusMsg('새 파일 업로드 및 백업 중...');
        const { job_id } = await api.replaceDocument(doc.id, file, {
          title: title.trim(),
          category: category.trim(),
          priority,
        });
        while (true) {
          await new Promise((r) => setTimeout(r, 850));
          const st = await api.getJob(job_id);
          setProgress(st.progress);
          setStatusMsg(st.message);
          if (st.status === 'done') {
            onUpdated();
            onClose();
            return;
          }
          if (st.status === 'error') {
            throw new Error(st.error || '업데이트 중 오류가 발생했습니다.');
          }
        }
      } else {
        await api.updateDocumentMeta(doc.id, {
          title: title.trim(),
          category: category.trim(),
          priority,
        });
        onUpdated();
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '자료 업데이트에 실패했습니다.');
      setBusy(false);
      setStatusMsg('');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-xs"
      onClick={() => !busy && onClose()}
    >
      <div
        className="w-full max-w-[440px] rounded-2xl border border-black/[0.08] bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#007AFF]/10 text-[#007AFF]">
              <RefreshCw className="h-4 w-4" />
            </div>
            <h3 className="text-sm font-semibold text-[#1d1d1f]">자료 업데이트 · 교체</h3>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            aria-label="닫기"
            className="rounded-lg p-1 text-[#86868b] hover:bg-black/[0.06] disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3.5">
          <div>
            <label className="mb-1 block text-[11.5px] font-medium text-[#6e6e73]">문서 이름</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={busy}
              className="w-full rounded-xl border border-black/[0.12] px-3 py-2 text-xs font-medium text-[#1d1d1f] outline-none focus:border-[#007AFF]"
            />
          </div>

          <div className="grid grid-cols-2 gap-2.5">
            <div>
              <label className="mb-1 block text-[11.5px] font-medium text-[#6e6e73]">분류</label>
              <input
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                disabled={busy}
                className="w-full rounded-xl border border-black/[0.12] px-3 py-2 text-xs text-[#1d1d1f] outline-none focus:border-[#007AFF]"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11.5px] font-medium text-[#6e6e73]">법규 우선순위 (0~100)</label>
              <input
                type="number"
                min={0}
                max={100}
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                disabled={busy}
                className="w-full rounded-xl border border-black/[0.12] px-3 py-2 text-xs text-[#1d1d1f] outline-none focus:border-[#007AFF]"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-[11.5px] font-medium text-[#6e6e73]">개정 파일 교체 (선택)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.zip,.txt,.md,.docx,.hwpx,.xlsx"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-black/[0.16] bg-[#f5f5f7]/70 px-3 py-3 text-xs font-medium text-[#424245] transition hover:border-[#007AFF] hover:bg-[#007AFF]/[0.04]"
            >
              <FileUp className="h-4 w-4 shrink-0 text-[#007AFF]" />
              <span className="truncate">
                {file ? file.name : '새 PDF · ZIP · DOCX · HWPX · TXT 선택 (비우면 정보만 수정)'}
              </span>
            </button>
          </div>

          {statusMsg && (
            <div className="rounded-xl border border-[#007AFF]/20 bg-[#007AFF]/[0.06] px-3 py-2">
              <div className="flex items-center gap-2 text-[11px] font-medium text-[#1d1d1f]">
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[#007AFF]" />
                <span className="truncate">{statusMsg}</span>
              </div>
              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-black/[0.08]">
                <div className="h-full rounded-full bg-[#007AFF] transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              disabled={busy}
              onClick={onClose}
              className="chip-nowrap rounded-xl border border-black/[0.1] bg-white px-3.5 py-2 text-xs font-semibold text-[#424245] hover:bg-[#f5f5f7] disabled:opacity-40"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={!title.trim() || busy}
              className="chip-nowrap inline-flex items-center gap-1.5 rounded-xl bg-[#007AFF] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#0066D6] disabled:opacity-45"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : file ? (
                <RefreshCw className="h-3.5 w-3.5" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              <span>{file ? '파일 교체 · 재색인' : '변경 저장'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
