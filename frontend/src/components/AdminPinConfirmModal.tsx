import React, { useState } from 'react';
import { KeyRound, Loader2, ShieldAlert, Trash2, X } from 'lucide-react';

interface Props {
  title: string;
  targetName: string;
  onConfirm: (adminPin: string) => Promise<void>;
  onClose: () => void;
}

export const AdminPinConfirmModal: React.FC<Props> = ({ title, targetName, onConfirm, onClose }) => {
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pin.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      await onConfirm(pin.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '관리자 PIN 확인에 실패했습니다.');
      setPin('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-xs"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[380px] rounded-2xl border border-black/[0.08] bg-white p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-600 ring-1 ring-red-200/70">
              <ShieldAlert className="h-4.5 w-4.5" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[#1d1d1f]">{title}</h3>
              <p className="truncate text-[11.5px] font-medium text-red-700">{targetName}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-lg p-1 text-[#86868b] hover:bg-black/[0.06]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-[#6e6e73]">
              <KeyRound className="h-3.5 w-3.5 text-[#86868b]" />
              <span>관리자 PIN 또는 비밀번호 확인</span>
            </label>
            <input
              type="password"
              value={pin}
              onChange={(e) => {
                setPin(e.target.value);
                setError('');
              }}
              placeholder="관리자 PIN 입력"
              autoFocus
              className="w-full rounded-xl border border-black/[0.12] bg-[#fbfbfd] px-3 py-2 text-sm text-[#1d1d1f] outline-none focus:border-red-500 focus:bg-white focus:ring-3 focus:ring-red-500/15"
            />
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="chip-nowrap rounded-xl border border-black/[0.1] bg-white px-3.5 py-2 text-xs font-semibold text-[#424245] hover:bg-[#f5f5f7]"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={!pin.trim() || busy}
              className="chip-nowrap inline-flex items-center gap-1.5 rounded-xl bg-red-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-red-700 disabled:opacity-45"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              <span>삭제 승인</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
