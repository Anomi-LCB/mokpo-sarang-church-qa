import React, { useState } from 'react';
import { BookOpen, Delete, KeyRound, Lock, User, WifiOff } from 'lucide-react';
import { api } from '../api';

interface Props {
  hasOfflineCache?: boolean;
  onEnterOffline?: () => void;
  onSuccess: (role: 'member' | 'admin', label: string, ownerId: string, isDefaultPin: boolean) => void;
}

export const PinGate: React.FC<Props> = ({ hasOfflineCache = false, onEnterOffline, onSuccess }) => {
  const [pin, setPin] = useState('');
  const [label, setLabel] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!pin.trim() || loading) return;
    setLoading(true);
    setError('');
    try {
      const res = await api.login(pin.trim(), label.trim());
      onSuccess(res.role, res.label, res.owner_id, res.is_default_pin);
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다.');
      setPin('');
    } finally {
      setLoading(false);
    }
  };

  const pushDigit = (d: string) => {
    if (pin.length < 32) {
      setPin((p) => p + d);
      setError('');
    }
  };

  return (
    <div className="flex min-h-dvh w-full items-center justify-center bg-[#f7f7f5] px-4 py-8">
      <div className="w-full max-w-[356px] rounded-2xl border border-black/[0.08] bg-white p-7 shadow-[0_12px_40px_rgba(0,0,0,0.05)]">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3.5 flex h-11 w-11 items-center justify-center rounded-xl bg-[#18181b] text-white">
            <BookOpen className="h-5 w-5" strokeWidth={1.85} />
          </div>
          <h1 className="text-[17px] font-semibold tracking-tight text-[#18181b]">목포사랑의교회 행정Q&amp;A</h1>
          <p className="mt-1 text-xs text-[#71717a]">PIN 또는 비밀번호로 입장하세요</p>
        </div>

        <form onSubmit={submit} className="space-y-3.5">
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-[#71717a]">
              <User className="h-3.5 w-3.5 text-[#a1a1aa]" />
              <span>사용자 이름 (선택)</span>
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="예: 김목사, 행정실"
              className="w-full rounded-xl border border-black/[0.09] bg-[#fafaf9] px-3.5 py-2 text-[16px] text-[#18181b] outline-none transition focus:border-[#18181b] focus:bg-white lg:text-sm"
            />
          </div>

          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-[#71717a]">
              <KeyRound className="h-3.5 w-3.5 text-[#a1a1aa]" />
              <span>PIN 또는 비밀번호</span>
            </label>
            <input
              type="password"
              value={pin}
              onChange={(e) => {
                setPin(e.target.value);
                setError('');
              }}
              placeholder="PIN / 비밀번호 입력"
              autoFocus
              className="w-full rounded-xl border border-black/[0.1] bg-white px-3.5 py-2.5 text-center text-base font-semibold tracking-[0.25em] text-[#18181b] outline-none transition focus:border-[#18181b]"
            />
          </div>

          <div className="grid grid-cols-3 gap-1.5 pt-0.5">
            {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => pushDigit(d)}
                className="chip-nowrap rounded-lg border border-black/[0.06] bg-[#f7f7f5] py-2.5 text-[15px] font-medium text-[#18181b] transition hover:bg-[#ededeb] active:scale-[0.98]"
              >
                {d}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setPin('')}
              className="chip-nowrap rounded-lg border border-black/[0.06] bg-[#f7f7f5] py-2.5 text-xs font-medium text-[#71717a] transition hover:bg-[#ededeb]"
            >
              초기화
            </button>
            <button
              type="button"
              onClick={() => pushDigit('0')}
              className="chip-nowrap rounded-lg border border-black/[0.06] bg-[#f7f7f5] py-2.5 text-[15px] font-medium text-[#18181b] transition hover:bg-[#ededeb] active:scale-[0.98]"
            >
              0
            </button>
            <button
              type="button"
              onClick={() => setPin((p) => p.slice(0, -1))}
              aria-label="지우기"
              className="flex items-center justify-center rounded-lg border border-black/[0.06] bg-[#f7f7f5] py-2.5 text-[#71717a] transition hover:bg-[#ededeb]"
            >
              <Delete className="h-4 w-4" />
            </button>
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!pin.trim() || loading}
            className="chip-nowrap flex w-full items-center justify-center gap-2 rounded-xl bg-[#18181b] py-2.5 text-sm font-semibold text-white transition hover:bg-[#27272a] disabled:opacity-40"
          >
            <Lock className="h-4 w-4" />
            <span>{loading ? '확인 중...' : '입장하기'}</span>
          </button>

          {hasOfflineCache && onEnterOffline && (
            <button
              type="button"
              onClick={onEnterOffline}
              className="chip-nowrap flex w-full items-center justify-center gap-1.5 rounded-xl border border-black/[0.09] bg-[#fafaf9] py-2 text-xs font-semibold text-[#18181b] transition hover:bg-[#ededeb]"
            >
              <WifiOff className="h-3.5 w-3.5 text-[#0f4c81]" />
              <span>저장된 오프라인 자료로 바로 검색</span>
            </button>
          )}
        </form>
      </div>
    </div>
  );
};
