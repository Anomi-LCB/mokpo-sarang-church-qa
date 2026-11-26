import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  ArrowUpCircle,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  ShieldCheck,
  SkipForward,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { UpdateCheckResponse, UpdateProgress } from '../types';

interface Props {
  info: UpdateCheckResponse;
  isAdmin: boolean;
  onSkipped: (version: string) => void;
  onClose: () => void;
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '';
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

export const UpdateModal: React.FC<Props> = ({ info, isAdmin, onSkipped, onClose }) => {
  const [progress, setProgress] = useState<UpdateProgress>(info.progress);
  const [busy, setBusy] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [errMsg, setErrMsg] = useState('');

  const latest = info.latest;
  const patchAsset = latest?.assets?.win_patch_zip || null;
  const installerAsset = latest?.assets?.win_installer_exe || null;

  useEffect(() => {
    if (progress.status !== 'downloading' && progress.status !== 'verifying') return;
    const timer = window.setInterval(() => {
      void api
        .getUpdateStatus()
        .then((res) => {
          setProgress(res.progress);
          if (res.progress.status === 'error' && res.progress.error) {
            setErrMsg(res.progress.error);
          }
        })
        .catch(() => {});
    }, 650);
    return () => window.clearInterval(timer);
  }, [progress.status]);

  useEffect(() => {
    if (!restarting) return;
    const timer = window.setInterval(() => {
      void fetch('/api/health', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data && data.status === 'ok' && data.version && data.version !== info.current_version) {
            window.location.reload();
          }
        })
        .catch(() => {});
    }, 1500);
    return () => window.clearInterval(timer);
  }, [restarting, info.current_version]);

  if (!latest) return null;

  const handleStartDownload = async () => {
    setBusy(true);
    setErrMsg('');
    setStatusMsg('');
    try {
      const res = await api.downloadUpdate();
      setProgress(res.progress);
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : '업데이트 다운로드 시작 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleApply = async () => {
    setBusy(true);
    setErrMsg('');
    try {
      const res = await api.applyUpdate();
      setStatusMsg(res.message);
      if (res.restarting) {
        setRestarting(true);
      }
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : '업데이트 적용 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleSkip = async () => {
    try {
      await api.skipUpdateVersion(latest.version);
    } catch {
      // still save local skip
    }
    onSkipped(latest.version);
    onClose();
  };

  const canAutoApply = Boolean(patchAsset?.url);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-6">
      <div className="flex max-h-[90dvh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#0f4c81] text-white">
              <ArrowUpCircle className="h-4.5 w-4.5" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-[#18181b]">새 버전 업데이트 안내</h3>
              <p className="text-[11px] text-[#71717a]">
                현재 v{info.current_version} → 새 버전{' '}
                <span className="font-semibold text-[#0f4c81]">v{latest.version}</span>
                {latest.published_at ? ` · ${latest.published_at.slice(0, 10)}` : ''}
                {patchAsset?.size_bytes ? ` · ${formatBytes(patchAsset.size_bytes)}` : ''}
              </p>
            </div>
          </div>
          {!restarting && (
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="rounded-lg p-1.5 text-[#71717a] hover:bg-black/[0.06]"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div className="flex items-start gap-2 rounded-xl border border-[#0f4c81]/15 bg-[#0f4c81]/[0.04] px-3.5 py-2.5 text-[11.5px] text-[#27272a]">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#0f4c81]" />
            <span>
              <strong>선택형 안전 업데이트:</strong> 업데이트 전 기존 DB를 자동 백업하며, 저장된 문서·대화·설정·표준화실 자료는 100% 그대로 유지됩니다. 원하지 않으시면 나중에 하거나 건너뛸 수 있습니다.
            </span>
          </div>

          {/* Release Notes */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-[#18181b]">
                {latest.title || `v${latest.version} 업데이트 내용`}
              </h4>
              {latest.release_url && (
                <a
                  href={latest.release_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="chip-nowrap inline-flex items-center gap-1 text-[11px] font-medium text-[#0f4c81] hover:underline"
                >
                  <span>릴리즈 상세</span>
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
            <div className="max-h-60 overflow-y-auto rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3.5 text-xs leading-relaxed whitespace-pre-wrap text-[#27272a]">
              {latest.notes_md}
            </div>
          </div>

          {/* Live Download / Verification Progress */}
          {(progress.status === 'downloading' ||
            progress.status === 'verifying' ||
            progress.status === 'ready' ||
            progress.status === 'applying' ||
            restarting) && (
            <div className="space-y-2 rounded-xl border border-black/[0.08] bg-white p-3.5">
              <div className="flex items-center justify-between text-xs font-semibold text-[#18181b]">
                <span className="inline-flex items-center gap-1.5">
                  {progress.status === 'ready' && !restarting ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <Loader2 className="h-4 w-4 animate-spin text-[#0f4c81]" />
                  )}
                  <span>
                    {restarting
                      ? '새 버전 적용 후 프로그램을 재시작하고 있습니다...'
                      : progress.message || '업데이트 준비 중...'}
                  </span>
                </span>
                <span className="tabular-nums text-[#0f4c81]">{progress.progress_pct}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-[#e4e4e7]">
                <div
                  className="h-full rounded-full bg-[#0f4c81] transition-all duration-300"
                  style={{ width: `${Math.max(4, progress.progress_pct)}%` }}
                />
              </div>
              {progress.total_bytes > 0 && progress.status === 'downloading' && (
                <p className="text-[11px] text-[#71717a]">
                  {formatBytes(progress.downloaded_bytes)} / {formatBytes(progress.total_bytes)}
                </p>
              )}
            </div>
          )}

          {statusMsg && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-xs text-emerald-900">
              {statusMsg}
            </div>
          )}

          {errMsg && (
            <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2 text-xs text-red-800">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
              <span>{errMsg}</span>
            </div>
          )}
        </div>

        {/* Footer — User-Optional Choices */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.08] bg-[#fafaf9] px-5 py-3">
          <div className="flex items-center gap-1.5">
            {!restarting && (
              <>
                <button
                  type="button"
                  onClick={() => void handleSkip()}
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]"
                >
                  <SkipForward className="h-3.5 w-3.5" />
                  <span>이 버전 건너뛰기</span>
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="chip-nowrap rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-medium text-[#3f3f46] hover:bg-[#f4f4f5]"
                >
                  나중에
                </button>
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            {!isAdmin ? (
              <span className="text-[11px] font-medium text-[#71717a]">
                관리자 PIN으로 로그인하면 바로 업데이트할 수 있습니다
              </span>
            ) : restarting ? (
              <span className="chip-nowrap inline-flex items-center gap-1.5 text-xs font-semibold text-[#0f4c81]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>재연결 대기 중...</span>
              </span>
            ) : progress.status === 'ready' && progress.staged_ready ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleApply()}
                className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-50"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>백업 후 적용 · 재시작</span>
              </button>
            ) : canAutoApply ? (
              <button
                type="button"
                disabled={busy || progress.status === 'downloading' || progress.status === 'verifying'}
                onClick={() => void handleStartDownload()}
                className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-50"
              >
                {progress.status === 'downloading' || progress.status === 'verifying' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                <span>지금 업데이트</span>
              </button>
            ) : installerAsset?.url ? (
              <a
                href={installerAsset.url}
                target="_blank"
                rel="noopener noreferrer"
                className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a]"
              >
                <Download className="h-3.5 w-3.5" />
                <span>설치파일 다운로드</span>
              </a>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};
