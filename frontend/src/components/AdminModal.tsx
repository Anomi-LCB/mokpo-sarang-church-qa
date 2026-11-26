import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  ArrowUpCircle,
  Bug,
  Check,
  CheckCircle2,
  Copy,
  Cpu,
  Database,
  Download,
  ExternalLink,
  Globe,
  HardDrive,
  Inbox,
  KeyRound,
  Loader2,
  Lock,
  LogOut,
  Monitor,
  Moon,
  PlugZap,
  Plus,
  QrCode,
  RefreshCw,
  RotateCcw,
  Save,
  Share,
  Shield,
  ShieldAlert,
  ShieldCheck,
  SkipForward,
  Smartphone,
  Sun,
  Terminal,
  Trash2,
  Upload,
  UserCheck,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react';
import { api, authHeaders, triggerTicketDownload } from '../api';
import { cacheFormPdfBlob, countCachedFormPdfs, saveOfflineBundle } from '../offlineStore';
import { loadUserProfile, saveUserProfile, type UserProfile } from '../profileStore';
import type { ThemeMode } from '../themeStore';
import type {
  AiConnectionMode,
  AiTestResult,
  AuditLogItem,
  BackupItem,
  CliSettings,
  FeedbackInboxResponse,
  FeedbackStatus,
  FormItem,
  NetworkSummary,
  Notebook,
  UpdateCheckResponse,
} from '../types';
import { AdminPinConfirmModal } from './AdminPinConfirmModal';
import { MarkdownView } from './MarkdownView';

export type AdminTab = 'connect' | 'profile' | 'cli' | 'updates' | 'security' | 'notebooks' | 'feedback';

interface Props {
  isAdmin: boolean;
  initialTab?: AdminTab;
  activeNotebook: Notebook | null;
  notebooks: Notebook[];
  forms?: FormItem[];
  offlineSyncedAt?: string;
  onOfflineSynced?: (syncedAt: string) => void;
  disableFormsPanel: boolean;
  onDisableFormsPanelChange: (disabled: boolean) => void;
  themeMode: ThemeMode;
  onThemeModeChange: (mode: ThemeMode) => void;
  onNotebooksChanged: (selectId?: string) => void;
  onPinSecurityChanged?: (isDefaultPin: boolean) => void;
  onClose: () => void;
}

export const AdminModal: React.FC<Props> = ({
  isAdmin,
  initialTab = 'connect',
  activeNotebook,
  notebooks,
  forms = [],
  offlineSyncedAt = '',
  onOfflineSynced,
  disableFormsPanel,
  onDisableFormsPanelChange,
  themeMode,
  onThemeModeChange,
  onNotebooksChanged,
  onPinSecurityChanged,
  onClose,
}) => {
  const [tab, setTab] = useState<AdminTab>(initialTab);
  const [network, setNetwork] = useState<NetworkSummary | null>(null);
  const [cli, setCli] = useState<CliSettings | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');
  const [copiedKey, setCopiedKey] = useState('');

  // Editable engine & security options
  const [connectionMode, setConnectionMode] = useState<AiConnectionMode>('auto');
  const [provider, setProvider] = useState('claude');
  const [model, setModel] = useState('');
  const [apiProvider, setApiProvider] = useState('anthropic');
  const [apiModel, setApiModel] = useState('');
  const [apiBaseUrl, setApiBaseUrl] = useState('');
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [aiTestResult, setAiTestResult] = useState<AiTestResult | null>(null);
  const [testingAi, setTestingAi] = useState(false);

  const [maxConcurrent, setMaxConcurrent] = useState(2);
  const [customPublicUrl, setCustomPublicUrl] = useState('');
  const [cliFailover, setCliFailover] = useState(true);
  const [defaultDoubleVerify, setDefaultDoubleVerify] = useState(false);
  const [defaultChatShared, setDefaultChatShared] = useState(false);
  const [auditLogEnabled, setAuditLogEnabled] = useState(true);

  // Opt-In Auto-Update state
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResponse | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [updateChannel, setUpdateChannel] = useState<'github' | 'custom'>('github');
  const [updateRepo, setUpdateRepo] = useState('');
  const [updateCustomUrl, setUpdateCustomUrl] = useState('');
  const [updateAutoCheck, setUpdateAutoCheck] = useState(true);
  const [updateRestarting, setUpdateRestarting] = useState(false);

  const [memberPin, setMemberPin] = useState('');
  const [adminPin, setAdminPin] = useState('');
  const [revokeOnPinChange, setRevokeOnPinChange] = useState(true);

  const [nbRules, setNbRules] = useState(activeNotebook?.system_rules || '');
  const [newNbName, setNewNbName] = useState('');
  const [newNbDesc, setNewNbDesc] = useState('');
  const [newNbRules, setNewNbRules] = useState('');
  const [busyAction, setBusyAction] = useState(false);
  const [deleteNbTarget, setDeleteNbTarget] = useState<Notebook | null>(null);
  const [cachedPdfCount, setCachedPdfCount] = useState(0);
  const [pdfSyncProgress, setPdfSyncProgress] = useState('');

  // Personal Profile state (device-local)
  const [userProfile, setUserProfile] = useState<UserProfile>(() => loadUserProfile());

  // Creator-only Feedback Inbox state
  const [creatorPinInput, setCreatorPinInput] = useState('');
  const [unlockedCreatorPin, setUnlockedCreatorPin] = useState('');
  const [feedbackInbox, setFeedbackInbox] = useState<FeedbackInboxResponse | null>(null);
  const [feedbackFilter, setFeedbackFilter] = useState<'' | FeedbackStatus>('');
  const [feedbackNotes, setFeedbackNotes] = useState<Record<number, string>>({});
  const [newCreatorPin, setNewCreatorPin] = useState('');
  const [relayUrl, setRelayUrl] = useState('');
  const [relayTokenOut, setRelayTokenOut] = useState('');
  const [creatorErr, setCreatorErr] = useState('');

  const handleUnlockCreatorInbox = async (pinToUse = creatorPinInput, filterVal = feedbackFilter) => {
    if (!pinToUse.trim()) return;
    setBusyAction(true);
    setCreatorErr('');
    try {
      const data = await api.listCreatorFeedback(pinToUse.trim(), filterVal);
      setUnlockedCreatorPin(pinToUse.trim());
      setFeedbackInbox(data);
      setRelayUrl(data.creator_relay_url || '');
      setRelayTokenOut(data.creator_relay_token_out || '');
      const notesMap: Record<number, string> = {};
      data.items.forEach((it) => {
        notesMap[it.id] = it.creator_note || '';
      });
      setFeedbackNotes(notesMap);
    } catch (err) {
      setCreatorErr(err instanceof Error ? err.message : '제작자 암호 확인 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleUpdateFeedbackItem = async (id: number, status?: FeedbackStatus, creator_note?: string) => {
    if (!unlockedCreatorPin) return;
    setBusyAction(true);
    try {
      await api.updateCreatorFeedback(id, unlockedCreatorPin, { status, creator_note });
      await handleUnlockCreatorInbox(unlockedCreatorPin, feedbackFilter);
      setMsg(`제보 #${id} 상태가 저장되었습니다.`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '제보 수정 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleDeleteFeedbackItem = async (id: number) => {
    if (!unlockedCreatorPin || !window.confirm(`제보 #${id} 항목을 삭제할까요?`)) return;
    setBusyAction(true);
    try {
      await api.deleteCreatorFeedback(id, unlockedCreatorPin);
      await handleUnlockCreatorInbox(unlockedCreatorPin, feedbackFilter);
      setMsg(`제보 #${id} 삭제됨`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '삭제 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleSaveCreatorSettings = async () => {
    if (!unlockedCreatorPin) return;
    setBusyAction(true);
    setMsg('');
    try {
      await api.updateCreatorSettings(unlockedCreatorPin, {
        new_creator_pin: newCreatorPin.trim() || undefined,
        creator_relay_url: relayUrl,
        creator_relay_token_out: relayTokenOut,
      });
      const nextPin = newCreatorPin.trim() || unlockedCreatorPin;
      setNewCreatorPin('');
      setUnlockedCreatorPin(nextPin);
      await handleUnlockCreatorInbox(nextPin, feedbackFilter);
      setMsg('제작자 전용 암호 및 원격 제보 전달 설정이 저장되었습니다.');
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '제작자 설정 저장 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleExportFeedbackJson = () => {
    if (!feedbackInbox) return;
    const blob = new Blob([JSON.stringify(feedbackInbox.items, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `목포사랑의교회_행정QA_제보내역_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  useEffect(() => {
    void countCachedFormPdfs().then(setCachedPdfCount);
  }, []);

  const handleSyncOfflineIndex = async () => {
    if (!activeNotebook) return;
    setBusyAction(true);
    setMsg('');
    try {
      const raw = await api.getOfflineBundle(activeNotebook.id);
      const syncedAt = new Date().toISOString();
      await saveOfflineBundle({ ...raw, synced_at: syncedAt });
      onOfflineSynced?.(syncedAt);
      setMsg(`오프라인 색인 저장 완료 (${raw.documents.length}개 문서, ${raw.chunks.length}개 조항, 서식 ${raw.forms.length}종)`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '오프라인 동기화 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleSyncAllOfflinePdfs = async () => {
    if (!forms.length) return;
    setBusyAction(true);
    setMsg('');
    let saved = 0;
    try {
      for (let i = 0; i < forms.length; i++) {
        const f = forms[i];
        setPdfSyncProgress(`${i + 1} / ${forms.length} 서식 PDF 저장 중...`);
        const res = await fetch(`/api/forms/${encodeURIComponent(f.id)}/download/pdf`, {
          credentials: 'include',
          headers: authHeaders(),
        });
        if (res.ok) {
          const blob = await res.blob();
          await cacheFormPdfBlob(f.id, blob, `${f.title}.pdf`);
          saved += 1;
        }
      }
      const total = await countCachedFormPdfs();
      setCachedPdfCount(total);
      setMsg(`서식 원본 PDF ${saved}종을 기기에 오프라인 저장했습니다. 이제 인터넷 없이도 열 수 있습니다.`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '서식 PDF 오프라인 저장 중 오류');
    } finally {
      setPdfSyncProgress('');
      setBusyAction(false);
    }
  };

  const loadAll = async () => {
    setLoading(true);
    try {
      const [net, cliCfg, upd] = await Promise.all([
        api.getNetwork(),
        api.getCliSettings(),
        api.checkUpdates(false).catch(() => null),
      ]);
      setNetwork(net);
      setCli(cliCfg);
      setConnectionMode(cliCfg.connection_mode || 'auto');
      setProvider(cliCfg.provider);
      setModel(cliCfg.model || '');
      setApiProvider(cliCfg.api_provider || 'anthropic');
      setApiModel(cliCfg.api_model || '');
      setApiBaseUrl(cliCfg.api_base_url || '');
      setApiKeyInput('');
      setMaxConcurrent(cliCfg.max_concurrent);
      setCustomPublicUrl(cliCfg.custom_public_url || '');
      setCliFailover(cliCfg.cli_failover_enabled);
      setDefaultDoubleVerify(cliCfg.default_double_verify);
      setDefaultChatShared(cliCfg.default_chat_shared);
      setAuditLogEnabled(cliCfg.audit_log_enabled);

      if (upd) {
        setUpdateInfo(upd);
        setUpdateChannel(upd.settings.channel);
        setUpdateRepo(upd.settings.github_repo);
        setUpdateCustomUrl(upd.settings.custom_url);
        setUpdateAutoCheck(upd.settings.auto_check);
      }

      if (isAdmin) {
        const [logs, bks] = await Promise.all([
          api.listAuditLogs().catch(() => [] as AuditLogItem[]),
          api.listBackups().catch(() => [] as BackupItem[]),
        ]);
        setAuditLogs(logs);
        setBackups(bks);
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '설정을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const st = updateInfo?.progress?.status;
    if (st !== 'downloading' && st !== 'verifying') return;
    const timer = window.setInterval(() => {
      void api
        .getUpdateStatus()
        .then((res) => {
          setUpdateInfo((prev) => (prev ? { ...prev, progress: res.progress } : prev));
        })
        .catch(() => {});
    }, 700);
    return () => window.clearInterval(timer);
  }, [updateInfo?.progress?.status]);

  useEffect(() => {
    if (!updateRestarting || !updateInfo) return;
    const curVer = updateInfo.current_version;
    const timer = window.setInterval(() => {
      void fetch('/api/health', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d?.status === 'ok' && d.version && d.version !== curVer) {
            window.location.reload();
          }
        })
        .catch(() => {});
    }, 1500);
    return () => window.clearInterval(timer);
  }, [updateRestarting, updateInfo]);

  useEffect(() => {
    void loadAll();
  }, []);

  useEffect(() => {
    setNbRules(activeNotebook?.system_rules || '');
  }, [activeNotebook]);

  const copyText = (key: string, text: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(''), 1800);
  };

  const handleSaveSettings = async (clearKey = false) => {
    setBusyAction(true);
    setMsg('');
    try {
      await api.updateCliSettings({
        connection_mode: connectionMode,
        provider,
        model,
        api_provider: apiProvider,
        api_model: apiModel,
        api_base_url: apiBaseUrl,
        api_key: !clearKey && apiKeyInput.trim() ? apiKeyInput.trim() : undefined,
        clear_api_key: clearKey,
        max_concurrent: maxConcurrent,
        custom_public_url: customPublicUrl,
        cli_failover_enabled: cliFailover,
        default_double_verify: defaultDoubleVerify,
        default_chat_shared: defaultChatShared,
        audit_log_enabled: auditLogEnabled,
      });
      setApiKeyInput('');
      await loadAll();
      setMsg(
        clearKey
          ? '선택된 API 키가 안전하게 삭제되었습니다.'
          : 'AI 연결(CLI/API) 및 안정성 설정이 암호화 저장되었습니다.'
      );
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '저장 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleTestAiConnection = async (testMode: 'cli' | 'api') => {
    setTestingAi(true);
    setAiTestResult(null);
    try {
      const res = await api.testAiConnection({
        mode: testMode,
        provider: testMode === 'api' ? apiProvider : provider,
        api_key: testMode === 'api' && apiKeyInput.trim() ? apiKeyInput.trim() : undefined,
        model: testMode === 'api' ? apiModel || undefined : model || undefined,
        base_url: testMode === 'api' ? apiBaseUrl || undefined : undefined,
      });
      setAiTestResult(res);
    } catch (err) {
      setAiTestResult({
        ok: false,
        mode: testMode,
        provider: testMode === 'api' ? apiProvider : provider,
        model: '',
        latency_ms: 0,
        reply_preview: '',
        message: err instanceof Error ? err.message : '연결 테스트 오류',
      });
    } finally {
      setTestingAi(false);
    }
  };

  const handleCheckUpdatesNow = async () => {
    setCheckingUpdate(true);
    setMsg('');
    try {
      const res = await api.checkUpdates(true);
      setUpdateInfo(res);
      if (res.update_available && res.latest) {
        setMsg(`새 버전 v${res.latest.version}이 확인되었습니다. 아래 변경 내역을 확인하고 원하실 때 업데이트하세요.`);
      } else if (res.offline) {
        setMsg(res.error || '현재 오프라인 상태입니다.');
      } else if (res.error) {
        setMsg(res.error);
      } else {
        setMsg(`현재 최신 버전(v${res.current_version})을 사용 중입니다.`);
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '업데이트 확인 실패');
    } finally {
      setCheckingUpdate(false);
    }
  };

  const handleSaveUpdateSettings = async () => {
    setBusyAction(true);
    setMsg('');
    try {
      await api.saveUpdateSettings({
        channel: updateChannel,
        github_repo: updateRepo,
        custom_url: updateCustomUrl,
        auto_check: updateAutoCheck,
      });
      const res = await api.checkUpdates(true);
      setUpdateInfo(res);
      setMsg('업데이트 채널 설정이 저장되었습니다.');
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '업데이트 설정 저장 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleStartUpdateDownload = async () => {
    setBusyAction(true);
    setMsg('');
    try {
      const res = await api.downloadUpdate();
      setUpdateInfo((prev) => (prev ? { ...prev, progress: res.progress } : prev));
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '업데이트 다운로드 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleUploadOfflinePatch = async (file: File) => {
    setBusyAction(true);
    setMsg('');
    try {
      const res = await api.uploadOfflinePatch(file);
      setUpdateInfo((prev) => (prev ? { ...prev, progress: res.progress } : prev));
      setMsg(`오프라인 업데이트 패키지(${res.version}) 검증 완료! [백업 후 적용·재시작]을 눌러 반영하세요.`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '로컬 업데이트 파일 검증 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleApplyStagedUpdate = async () => {
    if (!window.confirm('현재 DB를 자동 백업한 뒤 새 버전을 적용하고 프로그램을 재시작할까요?')) return;
    setBusyAction(true);
    setMsg('');
    try {
      const res = await api.applyUpdate();
      setMsg(res.message);
      if (res.restarting) {
        setUpdateRestarting(true);
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '업데이트 적용 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleTunnel = async (action: 'start' | 'stop', kind: 'tailscale' | 'cloudflare') => {
    setBusyAction(true);
    setMsg('');
    try {
      const res = action === 'start' ? await api.startTunnel(kind) : await api.stopTunnel(kind);
      setMsg(res.message);
      await loadAll();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '터널 제어 오류');
    } finally {
      setBusyAction(false);
    }
  };

  const handleSavePins = async () => {
    if (!memberPin && !adminPin) return;
    setBusyAction(true);
    setMsg('');
    try {
      const res = await api.updatePins(memberPin || undefined, adminPin || undefined, revokeOnPinChange);
      setMemberPin('');
      setAdminPin('');
      onPinSecurityChanged?.(res.is_default_pin);
      await loadAll();
      setMsg(
        revokeOnPinChange
          ? 'PIN/비밀번호가 변경되었고 다른 기기의 기존 세션이 안전하게 로그아웃되었습니다.'
          : 'PIN/비밀번호가 변경되었습니다.'
      );
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'PIN 변경 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleRevokeAll = async () => {
    if (!window.confirm('현재 기기를 제외한 모든 스마트폰/PC의 로그인 세션을 즉시 종료할까요?')) return;
    setBusyAction(true);
    setMsg('');
    try {
      await api.revokeAllSessions();
      await loadAll();
      setMsg('모든 외부 기기 세션이 강제 로그아웃되었습니다.');
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '세션 정리 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleCreateBackup = async () => {
    setBusyAction(true);
    setMsg('');
    try {
      const bk = await api.createBackup();
      await loadAll();
      setMsg(`새 DB 백업이 생성되었습니다: ${bk.name}`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '백업 생성 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleRestoreBackup = async (name: string) => {
    if (!window.confirm(`"${name}" 백업으로 DB를 복원할까요? (복원 직전 현재 상태도 자동 백업됩니다)`)) return;
    setBusyAction(true);
    setMsg('');
    try {
      const res = await api.restoreBackup(name);
      onNotebooksChanged();
      await loadAll();
      setMsg(`복원 완료 (${res.restored}). 안전 백업: ${res.safety_backup}`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '복원 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleSaveNotebookRules = async () => {
    if (!activeNotebook) return;
    setBusyAction(true);
    setMsg('');
    try {
      await api.updateNotebook(activeNotebook.id, { system_rules: nbRules });
      onNotebooksChanged();
      setMsg('노트북 전용 답변 규칙이 저장되었습니다.');
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '규칙 저장 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleCreateNotebook = async () => {
    if (!newNbName.trim()) return;
    setBusyAction(true);
    setMsg('');
    try {
      const created = await api.createNotebook(newNbName.trim(), newNbDesc.trim(), newNbRules.trim());
      setNewNbName('');
      setNewNbDesc('');
      setNewNbRules('');
      onNotebooksChanged(created.id);
      setMsg(`새 전용 노트북 "${created.name}"이 생성되었습니다.`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '노트북 생성 실패');
    } finally {
      setBusyAction(false);
    }
  };

  const handleConfirmDeleteNotebook = async (adminPin: string) => {
    if (!deleteNbTarget) return;
    await api.deleteNotebook(deleteNbTarget.id, adminPin);
    onNotebooksChanged();
    await loadAll();
    setMsg(`"${deleteNbTarget.name}" 노트북을 삭제했습니다.`);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-6">
      <div className="flex max-h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl">
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fbfbfd] px-4 py-3">
          <h3 className="text-sm font-semibold text-[#1d1d1f]">환경 설정 · 모바일 연결 · 보안 관리</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="rounded-lg p-1.5 text-[#6e6e73] hover:bg-black/[0.06]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex gap-1 overflow-x-auto border-b border-black/[0.07] bg-[#f7f7f5] px-3 pt-2">
          <button
            type="button"
            onClick={() => setTab('connect')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'connect' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <QrCode className="h-3.5 w-3.5" />
            <span>연결 · APK</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('profile')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'profile' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <UserCheck className="h-3.5 w-3.5" />
            <span>내 기본 정보</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('cli')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'cli' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>화면 · AI 엔진</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('updates')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'updates' ? 'border-[#0f4c81] text-[#0f4c81]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <ArrowUpCircle className="h-3.5 w-3.5" />
            <span>업데이트</span>
            {updateInfo?.update_available && (
              <span className="h-1.5 w-1.5 rounded-full bg-[#0f4c81]" aria-hidden="true" />
            )}
          </button>
          {isAdmin && (
            <>
              <button
                type="button"
                onClick={() => setTab('security')}
                className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
                  tab === 'security' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
                }`}
              >
                <Shield className="h-3.5 w-3.5" />
                <span>보안 · PIN</span>
              </button>
              <button
                type="button"
                onClick={() => setTab('notebooks')}
                className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
                  tab === 'notebooks' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
                }`}
              >
                <Database className="h-3.5 w-3.5" />
                <span>노트북 · 백업</span>
              </button>
              <button
                type="button"
                onClick={() => setTab('feedback')}
                className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
                  tab === 'feedback' ? 'border-[#0f4c81] text-[#0f4c81]' : 'border-transparent text-[#71717a]'
                }`}
              >
                <Inbox className="h-3.5 w-3.5" />
                <span>제작자 제보함</span>
              </button>
            </>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4 sm:p-5">
          {msg && (
            <div className="mb-3 rounded-xl border border-[#007AFF]/25 bg-[#007AFF]/[0.07] px-3 py-2 text-xs font-medium text-[#1d1d1f]">
              {msg}
            </div>
          )}

          {loading ? (
            <div className="flex h-48 items-center justify-center text-[#86868b]">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : tab === 'connect' && network ? (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-black/[0.08] p-3.5">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-[#007AFF]">
                    <Globe className="h-4 w-4 shrink-0" />
                    <span>외부 · 대표 접속 주소 (iOS PWA / 안드로이드)</span>
                  </div>
                  <div className="mt-3 flex justify-center">
                    <img src={network.primary_external_qr} alt="외부 접속 QR" className="h-36 w-36 rounded-lg border border-black/[0.08] p-1" />
                  </div>
                  <div className="mt-2.5 flex items-center gap-1.5 rounded-lg bg-[#f5f5f7] px-2.5 py-1.5">
                    <code className="min-w-0 flex-1 truncate text-[11px] text-[#1d1d1f]">{network.primary_external_url}</code>
                    <button
                      type="button"
                      onClick={() => copyText('ext', network.primary_external_url)}
                      className="shrink-0 rounded p-1 text-[#6e6e73] hover:bg-black/[0.06]"
                    >
                      {copiedKey === 'ext' ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                  <p className="mt-2 text-[11px] leading-relaxed text-[#6e6e73]">
                    아이폰 Safari에서 접속 후 <strong>공유 → 홈 화면에 추가</strong>로 앱처럼 실행하세요.
                  </p>
                </div>

                <div className="rounded-xl border border-black/[0.08] p-3.5">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-[#1d1d1f]">
                    <Wifi className="h-4 w-4 shrink-0" />
                    <span>같은 Wi-Fi (교회 사무실 내부망)</span>
                  </div>
                  <div className="mt-3 flex justify-center">
                    <img src={network.lan_qr} alt="Wi-Fi 접속 QR" className="h-36 w-36 rounded-lg border border-black/[0.08] p-1" />
                  </div>
                  <div className="mt-2.5 flex items-center gap-1.5 rounded-lg bg-[#f5f5f7] px-2.5 py-1.5">
                    <code className="min-w-0 flex-1 truncate text-[11px] text-[#1d1d1f]">{network.lan_url}</code>
                    <button
                      type="button"
                      onClick={() => copyText('lan', network.lan_url)}
                      className="shrink-0 rounded p-1 text-[#6e6e73] hover:bg-black/[0.06]"
                    >
                      {copiedKey === 'lan' ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                  <p className="mt-2 text-[11px] leading-relaxed text-[#6e6e73]">
                    PC와 같은 공유기에 연결된 폰·노트북에서 가장 빠르게 접속됩니다.
                  </p>
                </div>
              </div>

              <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 space-y-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-900">
                      <Smartphone className="h-4 w-4 shrink-0" />
                      <span>안드로이드 하이브리드 앱 (.apk · 오프라인 내장)</span>
                    </div>
                    <p className="text-[11px] leading-relaxed text-emerald-800">
                      ① 아래 QR로 <code>목포사랑의교회-행정Q&amp;A.apk</code>를 설치하면 919쪽 전체 색인과 서식 PDF 60종이 앱 안에 포함됩니다.
                      <br />② 설치 후 오른쪽 <strong>1스캔 자동 연결 QR</strong>을 스캔하면 주소 입력 없이 Tailscale·Wi-Fi가 즉시 연동됩니다.
                    </p>
                    <div className="flex flex-wrap gap-2 pt-1">
                      {network.apk_available && (
                        <a
                          href="/downloads/mokpo-sarang-qa.apk"
                          className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-800"
                        >
                          <Download className="h-3.5 w-3.5" />
                          <span>목포사랑의교회-행정Q&amp;A.apk 받기</span>
                        </a>
                      )}
                      {network.apk_connect_url && (
                        <button
                          type="button"
                          onClick={() => copyText('apk_conn', network.apk_connect_url || '')}
                          className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-900 hover:bg-emerald-50"
                        >
                          {copiedKey === 'apk_conn' ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                          <span>자동 연결 링크 복사</span>
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2.5">
                    {network.apk_qr && (
                      <div className="text-center">
                        <img src={network.apk_qr} alt="APK 다운로드 QR" className="h-24 w-24 rounded-lg border border-emerald-200 bg-white p-1" />
                        <p className="mt-1 text-[10px] font-semibold text-emerald-900">① APK 설치</p>
                      </div>
                    )}
                    {network.apk_connect_qr && (
                      <div className="text-center">
                        <img src={network.apk_connect_qr} alt="APK 자동 연결 QR" className="h-24 w-24 rounded-lg border border-emerald-200 bg-white p-1" />
                        <p className="mt-1 text-[10px] font-semibold text-emerald-900">② 1스캔 연결</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Offline PWA Storage Card (iPhone / iPad / Browser) */}
              <div className="rounded-xl border border-black/[0.08] bg-[#fbfbfd] p-4 space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-[#1d1d1f]">
                    <WifiOff className="h-4 w-4 shrink-0 text-[#007AFF]" />
                    <span>기기 오프라인 저장 (아이폰 PWA · 브라우저)</span>
                  </div>
                  <span className="chip-nowrap rounded-full bg-black/[0.05] px-2 py-0.5 text-[10.5px] font-medium text-[#6e6e73]">
                    {offlineSyncedAt ? '색인 동기화됨' : '대기 중'} · 서식 PDF {cachedPdfCount}건
                  </span>
                </div>
                <p className="text-[11px] leading-relaxed text-[#6e6e73]">
                  아이폰 Safari에서 <Share className="inline h-3 w-3 align-text-bottom text-[#007AFF]" /> <strong>공유 → 홈 화면에 추가</strong> 후 아래 버튼으로 저장해 두면 비행기 모드·PC 꺼짐 상태에서도 919쪽 검색과 서식 PDF 열람이 가능합니다.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={busyAction || !activeNotebook}
                    onClick={() => void handleSyncOfflineIndex()}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#007AFF] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0066D6] disabled:opacity-45"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    <span>원문 색인 지금 동기화</span>
                  </button>
                  {forms.length > 0 && (
                    <button
                      type="button"
                      disabled={busyAction}
                      onClick={() => void handleSyncAllOfflinePdfs()}
                      className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg border border-black/[0.12] bg-white px-3 py-1.5 text-xs font-semibold text-[#1d1d1f] hover:bg-[#f5f5f7] disabled:opacity-45"
                    >
                      <HardDrive className="h-3.5 w-3.5 text-[#007AFF]" />
                      <span>{pdfSyncProgress || `서식 PDF ${forms.length}종 오프라인 저장`}</span>
                    </button>
                  )}
                </div>
              </div>

              {isAdmin && (
                <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-semibold text-[#1d1d1f]">외부 상시 HTTPS 터널 제어</h4>
                    <button
                      type="button"
                      onClick={() => void loadAll()}
                      className="chip-nowrap inline-flex items-center gap-1 text-[11px] text-[#6e6e73] hover:text-[#1d1d1f]"
                    >
                      <RefreshCw className="h-3 w-3" />
                      <span>새로고침</span>
                    </button>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[#f5f5f7] p-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-[#1d1d1f]">
                        Tailscale Funnel {network.tailscale.funnel_active ? '(활성화됨)' : '(대기 중)'}
                      </p>
                      <p className="truncate text-[11px] text-[#6e6e73]">
                        {network.tailscale.installed
                          ? network.tailscale.suggested_funnel_url || `Tailscale IP: ${network.tailscale.ip}`
                          : 'Tailscale 미설치'}
                      </p>
                    </div>
                    {network.tailscale.installed && (
                      <div className="flex gap-1.5">
                        <button
                          type="button"
                          disabled={busyAction}
                          onClick={() => void handleTunnel('start', 'tailscale')}
                          className="chip-nowrap rounded-lg bg-[#007AFF] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0066D6]"
                        >
                          Funnel 켜기
                        </button>
                        <button
                          type="button"
                          disabled={busyAction}
                          onClick={() => void handleTunnel('stop', 'tailscale')}
                          className="chip-nowrap rounded-lg border border-black/[0.12] bg-white px-3 py-1.5 text-xs font-semibold text-[#1d1d1f]"
                        >
                          끄기
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : tab === 'profile' ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4 space-y-3">
                <div>
                  <h4 className="text-xs font-semibold text-[#18181b]">서식 자동 작성용 내 기본 정보 (이 기기 전용 보관)</h4>
                  <p className="mt-0.5 text-[11px] text-[#71717a]">
                    등록한 개인정보는 서버에 저장되지 않고 현재 기기에만 보관되며, 모든 청원서·신청서 작성 시 1클릭으로 자동 입력됩니다.
                  </p>
                </div>

                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">성명</label>
                    <input
                      type="text"
                      value={userProfile.name}
                      onChange={(e) => setUserProfile({ ...userProfile, name: e.target.value })}
                      placeholder="예: 홍길동"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">직분 · 직책</label>
                    <input
                      type="text"
                      value={userProfile.position}
                      onChange={(e) => setUserProfile({ ...userProfile, position: e.target.value })}
                      placeholder="예: 부목사, 장로, 안수집사, 권사, 행정간사"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">소속 부서 · 교구 · 셀</label>
                    <input
                      type="text"
                      value={userProfile.department}
                      onChange={(e) => setUserProfile({ ...userProfile, department: e.target.value })}
                      placeholder="예: 행정실, 교육선교국, 1교구"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">생년월일</label>
                    <input
                      type="text"
                      value={userProfile.birthDate}
                      onChange={(e) => setUserProfile({ ...userProfile, birthDate: e.target.value })}
                      placeholder="예: 1985-05-12"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">연락처</label>
                    <input
                      type="text"
                      value={userProfile.phone}
                      onChange={(e) => setUserProfile({ ...userProfile, phone: e.target.value })}
                      placeholder="예: 010-1234-5678"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">이메일 (선택)</label>
                    <input
                      type="text"
                      value={userProfile.email}
                      onChange={(e) => setUserProfile({ ...userProfile, email: e.target.value })}
                      placeholder="example@church.org"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">주소 (선택)</label>
                    <input
                      type="text"
                      value={userProfile.address}
                      onChange={(e) => setUserProfile({ ...userProfile, address: e.target.value })}
                      placeholder="전남 목포시 ..."
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-[11px] font-medium text-[#52525b]">기본 수신처</label>
                    <input
                      type="text"
                      value={userProfile.recipient}
                      onChange={(e) => setUserProfile({ ...userProfile, recipient: e.target.value })}
                      placeholder="목포사랑의교회 당회장 귀하"
                      className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                    />
                  </div>
                </div>

                {/* Custom extra profile fields */}
                <div className="space-y-1.5 border-t border-black/[0.06] pt-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-semibold text-[#52525b]">추가 항목 (세례일 · 임직일 · 계좌 등)</span>
                    <button
                      type="button"
                      onClick={() =>
                        setUserProfile({
                          ...userProfile,
                          extras: [...userProfile.extras, { label: '', value: '' }],
                        })
                      }
                      className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium text-[#0f4c81] hover:bg-black/[0.04]"
                    >
                      <Plus className="h-3 w-3" />
                      <span>항목 추가</span>
                    </button>
                  </div>
                  {userProfile.extras.map((ex, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <input
                        type="text"
                        value={ex.label}
                        onChange={(e) =>
                          setUserProfile({
                            ...userProfile,
                            extras: userProfile.extras.map((item, idx) => (idx === i ? { ...item, label: e.target.value } : item)),
                          })
                        }
                        placeholder="항목명 (예: 임직일)"
                        className="w-32 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs"
                      />
                      <input
                        type="text"
                        value={ex.value}
                        onChange={(e) =>
                          setUserProfile({
                            ...userProfile,
                            extras: userProfile.extras.map((item, idx) => (idx === i ? { ...item, value: e.target.value } : item)),
                          })
                        }
                        placeholder="값"
                        className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setUserProfile({
                            ...userProfile,
                            extras: userProfile.extras.filter((_, idx) => idx !== i),
                          })
                        }
                        className="rounded p-1 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>

                <label className="flex cursor-pointer items-center gap-2 pt-1 text-xs text-[#3f3f46]">
                  <input
                    type="checkbox"
                    checked={userProfile.autoApply}
                    onChange={(e) => setUserProfile({ ...userProfile, autoApply: e.target.checked })}
                    className="accent-[#18181b]"
                  />
                  <span>서식 작성 창을 열 때 내 기본 정보 자동으로 채워 넣기</span>
                </label>

                <button
                  type="button"
                  onClick={() => {
                    saveUserProfile(userProfile);
                    setMsg('내 기본 정보가 기기에 안전하게 저장되었습니다. 이제 서식 작성에서 바로 적용됩니다.');
                  }}
                  className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a]"
                >
                  <Save className="h-3.5 w-3.5" />
                  <span>내 기본 정보 저장</span>
                </button>
              </div>
            </div>
          ) : tab === 'feedback' ? (
            <div className="space-y-4">
              {!feedbackInbox ? (
                <div className="mx-auto max-w-sm space-y-3 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-5 text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-[#18181b] text-white">
                    <Lock className="h-5 w-5" />
                  </div>
                  <div className="space-y-1">
                    <h4 className="text-sm font-semibold text-[#18181b]">제작자 전용 비공개 제보함</h4>
                    <p className="text-[11.5px] text-[#71717a]">
                      사용자가 보낸 버그·불편·개선사항은 제작자 본인만 열람할 수 있습니다. (초기 암호: 관리자 PIN)
                    </p>
                  </div>
                  <input
                    type="password"
                    value={creatorPinInput}
                    onChange={(e) => {
                      setCreatorPinInput(e.target.value);
                      setCreatorErr('');
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void handleUnlockCreatorInbox();
                    }}
                    placeholder="제작자 전용 암호 입력"
                    className="w-full rounded-lg border border-black/[0.12] bg-white px-3 py-2 text-center text-sm tracking-widest outline-none focus:border-[#18181b]"
                  />
                  {creatorErr && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-700">
                      {creatorErr}
                    </div>
                  )}
                  <button
                    type="button"
                    disabled={!creatorPinInput.trim() || busyAction}
                    onClick={() => void handleUnlockCreatorInbox()}
                    className="chip-nowrap w-full rounded-lg bg-[#18181b] py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-45"
                  >
                    제보함 열기
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      {(
                        [
                          { id: '', label: '전체' },
                          { id: 'open', label: '접수됨' },
                          { id: 'reviewing', label: '검토 중' },
                          { id: 'resolved', label: '해결 완료' },
                        ] as const
                      ).map((st) => (
                        <button
                          key={st.id || 'all'}
                          type="button"
                          onClick={() => {
                            setFeedbackFilter(st.id);
                            void handleUnlockCreatorInbox(unlockedCreatorPin, st.id);
                          }}
                          className={`chip-nowrap rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                            feedbackFilter === st.id
                              ? 'bg-[#18181b] text-white'
                              : 'bg-[#f7f7f5] text-[#52525b] hover:bg-[#ededeb]'
                          }`}
                        >
                          {st.label}
                        </button>
                      ))}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={handleExportFeedbackJson}
                        className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.1] bg-white px-2.5 py-1 text-[11px] font-medium text-[#3f3f46] hover:bg-[#f7f7f5]"
                      >
                        <Download className="h-3 w-3" />
                        <span>JSON 내보내기</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleUnlockCreatorInbox(unlockedCreatorPin, feedbackFilter)}
                        className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.1] bg-white px-2.5 py-1 text-[11px] font-medium text-[#3f3f46] hover:bg-[#f7f7f5]"
                      >
                        <RefreshCw className="h-3 w-3" />
                        <span>새로고침</span>
                      </button>
                    </div>
                  </div>

                  {feedbackInbox.items.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-black/[0.12] p-8 text-center text-xs text-[#8a8a8e]">
                      접수된 제보가 없습니다.
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {feedbackInbox.items.map((item) => (
                        <div key={item.id} className="space-y-2 rounded-xl border border-black/[0.08] bg-white p-3.5">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="chip-nowrap inline-flex items-center gap-1 rounded bg-[#f7f7f5] px-1.5 py-0.5 text-[10.5px] font-semibold text-[#18181b]">
                                  <Bug className="h-3 w-3 text-[#0f4c81]" />
                                  {item.category === 'bug'
                                    ? '버그'
                                    : item.category === 'ux'
                                      ? '불편'
                                      : item.category === 'feature'
                                        ? '개선'
                                        : '자료'}
                                </span>
                                <span className="text-xs font-semibold text-[#18181b]">#{item.id} {item.title}</span>
                                {Boolean(item.relayed_remote) && (
                                  <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[#0f4c81]">
                                    원격 PC
                                  </span>
                                )}
                              </div>
                              <p className="mt-1 text-[11px] text-[#8a8a8e]">
                                {item.reporter_label} · {item.client_ip} · {item.created_at.slice(0, 16).replace('T', ' ')}
                                {item.app_version ? ` · v${item.app_version}` : ''}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-1.5">
                              <select
                                value={item.status}
                                onChange={(e) => void handleUpdateFeedbackItem(item.id, e.target.value as FeedbackStatus)}
                                className="rounded-md border border-black/[0.1] bg-[#fafaf9] px-2 py-1 text-[11px] font-medium text-[#18181b]"
                              >
                                <option value="open">접수됨</option>
                                <option value="reviewing">검토 중</option>
                                <option value="resolved">해결 완료</option>
                              </select>
                              <button
                                type="button"
                                onClick={() => void handleDeleteFeedbackItem(item.id)}
                                aria-label="제보 삭제"
                                className="rounded p-1 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>

                          <p className="whitespace-pre-wrap rounded-lg bg-[#fafaf9] p-2.5 text-xs leading-relaxed text-[#27272a]">
                            {item.description}
                          </p>

                          {(item.context_info || item.device_info) && (
                            <p className="truncate text-[10.5px] text-[#8a8a8e]">
                              진단: {[item.context_info, item.device_info].filter(Boolean).join(' | ')}
                            </p>
                          )}

                          <div className="flex items-center gap-1.5 pt-1">
                            <input
                              type="text"
                              value={feedbackNotes[item.id] ?? ''}
                              onChange={(e) => setFeedbackNotes({ ...feedbackNotes, [item.id]: e.target.value })}
                              placeholder="제작자 비공개 메모 입력..."
                              className="min-w-0 flex-1 rounded-md border border-black/[0.09] px-2.5 py-1 text-xs outline-none focus:border-[#18181b]"
                            />
                            <button
                              type="button"
                              disabled={busyAction}
                              onClick={() => void handleUpdateFeedbackItem(item.id, undefined, feedbackNotes[item.id] ?? '')}
                              className="chip-nowrap rounded-md bg-[#18181b] px-2.5 py-1 text-[11px] font-medium text-white hover:bg-[#27272a]"
                            >
                              메모 저장
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Creator Separate Password & Multi-PC Relay Config */}
                  <div className="space-y-3 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4">
                    <h4 className="text-xs font-semibold text-[#18181b]">제작자 전용 암호 · 다른 PC 원격 제보 수신 설정</h4>
                    <div className="rounded-lg border border-black/[0.07] bg-white p-2.5 text-[11px] text-[#52525b]">
                      <p className="font-semibold text-[#18181b]">내 PC 제보 수신 토큰 (다른 PC에 입력하면 제보가 내 PC로 전달됨)</p>
                      <div className="mt-1 flex items-center gap-1.5">
                        <code className="min-w-0 flex-1 truncate rounded bg-[#f7f7f5] px-2 py-1 text-[11px]">
                          {feedbackInbox.creator_relay_token}
                        </code>
                        <button
                          type="button"
                          onClick={() => copyText('ctok', feedbackInbox.creator_relay_token)}
                          className="shrink-0 rounded p-1 text-[#52525b] hover:bg-black/[0.06]"
                        >
                          {copiedKey === 'ctok' ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <input
                        type="password"
                        value={newCreatorPin}
                        onChange={(e) => setNewCreatorPin(e.target.value)}
                        placeholder={
                          feedbackInbox.has_custom_creator_pin
                            ? '제작자 전용 암호 변경 (설정됨)'
                            : '별도 제작자 전용 암호 설정 (선택)'
                        }
                        className="rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs"
                      />
                      <input
                        type="url"
                        value={relayUrl}
                        onChange={(e) => setRelayUrl(e.target.value)}
                        placeholder="원격 제작자 PC 수신 주소 (선택 · 예: https://...ts.net)"
                        className="rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs"
                      />
                      <input
                        type="text"
                        value={relayTokenOut}
                        onChange={(e) => setRelayTokenOut(e.target.value)}
                        placeholder="원격 제작자 PC 수신 토큰 (다른 PC 설치본에서 전송용)"
                        className="rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs sm:col-span-2"
                      />
                    </div>
                    <button
                      type="button"
                      disabled={busyAction}
                      onClick={() => void handleSaveCreatorSettings()}
                      className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#0c3d68]"
                    >
                      <Save className="h-3.5 w-3.5" />
                      <span>제작자 설정 저장</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : tab === 'cli' && cli ? (
            <div className="space-y-4">
              {/* Display Layout & Theme Options (Available for all users) */}
              <div className="space-y-3 rounded-xl border border-black/[0.08] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/[0.06] pb-3">
                  <div>
                    <p className="text-xs font-semibold text-[#18181b]">화면 테마 (라이트 · 다크 모드)</p>
                    <p className="text-[11px] text-[#71717a]">
                      야간·장시간 문서 검토 시 눈의 피로를 줄여 주는 다크 모드를 선택할 수 있습니다
                    </p>
                  </div>
                  <div className="inline-flex rounded-lg bg-[#f0f0ee] p-0.5">
                    {(
                      [
                        { id: 'light', label: '라이트', Icon: Sun },
                        { id: 'dark', label: '다크', Icon: Moon },
                        { id: 'system', label: '시스템', Icon: Monitor },
                      ] as const
                    ).map(({ id, label, Icon }) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => onThemeModeChange(id)}
                        className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                          themeMode === id
                            ? 'bg-white text-[#18181b] shadow-2xs'
                            : 'text-[#71717a] hover:text-[#18181b]'
                        }`}
                      >
                        <Icon className="h-3 w-3" />
                        <span>{label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <label className="flex cursor-pointer items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold text-[#18181b]">오른쪽 서식·표 창 완전히 끄기</p>
                    <p className="text-[11px] text-[#71717a]">
                      켜면 우측 서식 보관함과 관련 버튼이 화면에서 완전히 숨겨져 대화에만 집중할 수 있습니다
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={disableFormsPanel}
                    onChange={(e) => onDisableFormsPanelChange(e.target.checked)}
                    className="h-4 w-4 accent-[#18181b]"
                  />
                </label>
              </div>

              {/* Active AI Engine Status Banner */}
              <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3.5 text-xs text-[#18181b]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2 font-semibold">
                    <Cpu className="h-4 w-4 shrink-0 text-[#0f4c81]" />
                    <span className="truncate">{cli.active_engine_summary}</span>
                  </div>
                  <span className="chip-nowrap rounded-md bg-white px-2 py-0.5 text-[11px] text-[#52525b] ring-1 ring-black/[0.08]">
                    실행 {cli.queue.active} / 대기 {cli.queue.queued} (최대 {cli.queue.max_concurrent})
                  </span>
                </div>
              </div>

              {/* Connection Mode Switcher: Auto | CLI | API */}
              <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                <div>
                  <p className="text-xs font-semibold text-[#18181b]">AI 연결 방식 선택 (선택 사항)</p>
                  <p className="text-[11px] text-[#71717a]">
                    설치 PC 환경에 맞게 기존 구독 CLI, API 키 직접 연결, 또는 자동 전환을 선택하세요. 미연결 시에도 PC 내장 즉시 원문 검색이 100% 동작합니다.
                  </p>
                </div>

                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {(
                    [
                      {
                        id: 'auto',
                        title: '자동 전환 (CLI + API)',
                        desc: 'CLI 우선 시도 후 미설치·오류 시 API로 자동 연결',
                      },
                      {
                        id: 'cli',
                        title: '구독 CLI 연결',
                        desc: 'Claude · Codex · Gemini 구독 터미널 연동',
                      },
                      {
                        id: 'api',
                        title: 'API 키 직접 연결',
                        desc: 'Anthropic · OpenAI · Gemini · 로컬 Ollama',
                      },
                    ] as const
                  ).map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      disabled={!isAdmin}
                      onClick={() => {
                        setConnectionMode(opt.id);
                        setAiTestResult(null);
                      }}
                      className={`rounded-xl border p-3 text-left transition ${
                        connectionMode === opt.id
                          ? 'border-[#18181b] bg-[#18181b]/[0.03] ring-1 ring-[#18181b]'
                          : 'border-black/[0.08] bg-white hover:bg-[#fafaf9]'
                      } disabled:opacity-60`}
                    >
                      <p className="text-xs font-semibold text-[#18181b]">{opt.title}</p>
                      <p className="mt-0.5 text-[10.5px] leading-snug text-[#71717a]">{opt.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* CLI Provider Section (shown for cli or auto) */}
              {(connectionMode === 'cli' || connectionMode === 'auto') && (
                <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-[#18181b]">구독 CLI 엔진 선택</p>
                    {isAdmin && (
                      <button
                        type="button"
                        disabled={testingAi}
                        onClick={() => void handleTestAiConnection('cli')}
                        className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.12] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#18181b] hover:bg-[#f7f7f5] disabled:opacity-50"
                      >
                        {testingAi ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlugZap className="h-3 w-3 text-[#0f4c81]" />}
                        <span>CLI 연결 테스트</span>
                      </button>
                    )}
                  </div>
                  {cli.providers.map((p) => (
                    <label
                      key={p.id}
                      className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition ${
                        provider === p.id ? 'border-[#0f4c81] bg-[#0f4c81]/[0.04]' : 'border-black/[0.08] bg-white'
                      } ${!p.available ? 'opacity-60' : ''}`}
                    >
                      <input
                        type="radio"
                        name="cli_provider"
                        checked={provider === p.id}
                        disabled={!isAdmin}
                        onChange={() => setProvider(p.id)}
                        className="mt-1 accent-[#0f4c81]"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-[#18181b]">{p.name}</span>
                          <span
                            className={`chip-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                              p.available ? 'bg-emerald-100 text-emerald-800' : 'bg-zinc-200 text-zinc-600'
                            }`}
                          >
                            {p.available ? '감지됨' : '미설치'}
                          </span>
                        </div>
                        <p className="mt-0.5 text-[11px] text-[#71717a]">{p.description}</p>
                      </div>
                    </label>
                  ))}
                  {isAdmin && (
                    <div className="pt-1">
                      <label className="mb-1 block text-[11px] font-semibold text-[#52525b]">CLI 모델 지정 (선택)</label>
                      <input
                        type="text"
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        placeholder="비우면 CLI 기본 모델 사용"
                        className="w-full rounded-lg border border-black/[0.12] px-3 py-1.5 text-xs"
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Direct API Provider Section (shown for api or auto) */}
              {(connectionMode === 'api' || connectionMode === 'auto') && (
                <div className="space-y-3 rounded-xl border border-black/[0.08] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-xs font-semibold text-[#18181b]">API 키 직접 연결 설정</p>
                      <p className="text-[11px] text-[#71717a]">
                        입력한 API 키는 Windows DPAPI로 이 PC에만 로컬 암호화 저장되며 외부로 전송되지 않습니다.
                      </p>
                    </div>
                    {isAdmin && (
                      <button
                        type="button"
                        disabled={testingAi}
                        onClick={() => void handleTestAiConnection('api')}
                        className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-[#0f4c81]/30 bg-[#0f4c81]/[0.06] px-2.5 py-1 text-[11px] font-semibold text-[#0f4c81] hover:bg-[#0f4c81]/[0.12] disabled:opacity-50"
                      >
                        {testingAi ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlugZap className="h-3 w-3" />}
                        <span>API 연결 테스트</span>
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {(cli.api_providers || []).map((ap) => (
                      <label
                        key={ap.id}
                        className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 transition ${
                          apiProvider === ap.id ? 'border-[#0f4c81] bg-[#0f4c81]/[0.04]' : 'border-black/[0.08] bg-white'
                        }`}
                      >
                        <input
                          type="radio"
                          name="api_provider"
                          checked={apiProvider === ap.id}
                          disabled={!isAdmin}
                          onChange={() => {
                            setApiProvider(ap.id);
                            setApiModel('');
                            setApiBaseUrl('');
                            setApiKeyInput('');
                            setAiTestResult(null);
                          }}
                          className="mt-1 accent-[#0f4c81]"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-xs font-semibold text-[#18181b]">{ap.name}</span>
                            {ap.has_key ? (
                              <span className="chip-nowrap rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">
                                키 등록됨
                              </span>
                            ) : !ap.requires_key ? (
                              <span className="chip-nowrap rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-700">
                                키 선택
                              </span>
                            ) : (
                              <span className="chip-nowrap rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500">
                                미등록
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 text-[10.5px] leading-snug text-[#71717a]">{ap.description}</p>
                        </div>
                      </label>
                    ))}
                  </div>

                  {isAdmin && (() => {
                    const activeApiMeta = (cli.api_providers || []).find((a) => a.id === apiProvider);
                    return (
                      <div className="space-y-2.5 rounded-xl border border-black/[0.07] bg-[#fafaf9] p-3.5">
                        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                          <div className="sm:col-span-2">
                            <div className="mb-1 flex items-center justify-between gap-2">
                              <label className="text-[11px] font-semibold text-[#18181b]">
                                {activeApiMeta?.name || 'API'} 키{' '}
                                {!activeApiMeta?.requires_key && <span className="font-normal text-[#71717a]">(로컬 Ollama는 비워도 됨)</span>}
                              </label>
                              {activeApiMeta?.has_key && (
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-[10.5px] text-emerald-700">
                                    저장됨: {activeApiMeta.key_masked}
                                  </span>
                                  {activeApiMeta.key_source === 'saved' && (
                                    <button
                                      type="button"
                                      onClick={() => void handleSaveSettings(true)}
                                      className="text-[10.5px] font-medium text-red-600 hover:underline"
                                    >
                                      키 삭제
                                    </button>
                                  )}
                                </div>
                              )}
                            </div>
                            <input
                              type="password"
                              value={apiKeyInput}
                              onChange={(e) => setApiKeyInput(e.target.value)}
                              placeholder={
                                activeApiMeta?.has_key
                                  ? '새 키로 교체할 때만 입력 (비우면 기존 암호화 키 유지)'
                                  : activeApiMeta?.requires_key
                                    ? 'sk-... 또는 API 키 입력'
                                    : '필요한 경우에만 API 키 입력'
                              }
                              className="w-full rounded-lg border border-black/[0.12] bg-white px-3 py-2 text-xs"
                            />
                          </div>

                          <div>
                            <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">모델 선택 · 직접 입력</label>
                            <input
                              type="text"
                              list={`presets_${apiProvider}`}
                              value={apiModel}
                              onChange={(e) => setApiModel(e.target.value)}
                              placeholder={activeApiMeta?.default_model || '기본 모델'}
                              className="w-full rounded-lg border border-black/[0.12] bg-white px-3 py-1.5 text-xs"
                            />
                            {activeApiMeta?.presets && (
                              <datalist id={`presets_${apiProvider}`}>
                                {activeApiMeta.presets.map((m) => (
                                  <option key={m} value={m} />
                                ))}
                              </datalist>
                            )}
                          </div>

                          <div>
                            <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">
                              엔드포인트 Base URL (선택)
                            </label>
                            <input
                              type="url"
                              value={apiBaseUrl}
                              onChange={(e) => setApiBaseUrl(e.target.value)}
                              placeholder={activeApiMeta?.default_base_url || 'https://...'}
                              className="w-full rounded-lg border border-black/[0.12] bg-white px-3 py-1.5 text-xs"
                            />
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}

              {/* Live AI Connection Test Feedback */}
              {aiTestResult && (
                <div
                  className={`flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-xs ${
                    aiTestResult.ok
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                      : 'border-red-200 bg-red-50 text-red-800'
                  }`}
                >
                  {aiTestResult.ok ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : (
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{aiTestResult.message}</p>
                    {aiTestResult.reply_preview && (
                      <p className="mt-0.5 text-[11px] opacity-80">응답 확인: {aiTestResult.reply_preview}</p>
                    )}
                  </div>
                </div>
              )}

              {isAdmin && (
                <div className="space-y-3 rounded-xl border border-black/[0.08] p-4">
                  <label className="flex cursor-pointer items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-[#18181b]">자동 장애 전환 (Failover)</p>
                      <p className="text-[11px] text-[#71717a]">주 엔진이 일시 한도·오류 발생 시 보조 CLI/API로 자동 전환</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={cliFailover}
                      onChange={(e) => setCliFailover(e.target.checked)}
                      className="h-4 w-4 accent-[#18181b]"
                    />
                  </label>

                  <label className="flex cursor-pointer items-center justify-between gap-3 border-t border-black/[0.06] pt-3">
                    <div>
                      <p className="text-xs font-semibold text-[#18181b]">기본 이중 원문 재대조 활성화</p>
                      <p className="text-[11px] text-[#71717a]">모든 질문에 대해 2차 원문 대조를 기본값으로 켭니다</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={defaultDoubleVerify}
                      onChange={(e) => setDefaultDoubleVerify(e.target.checked)}
                      className="h-4 w-4 accent-[#18181b]"
                    />
                  </label>

                  <div className="grid grid-cols-1 gap-3 border-t border-black/[0.06] pt-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-xs font-semibold text-[#18181b]">동시 AI 처리 수</label>
                      <select
                        value={maxConcurrent}
                        onChange={(e) => setMaxConcurrent(Number(e.target.value))}
                        className="w-full rounded-lg border border-black/[0.12] bg-white px-3 py-2 text-xs"
                      >
                        {[1, 2, 3, 4].map((n) => (
                          <option key={n} value={n}>
                            동시 {n}명 처리
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-semibold text-[#18181b]">고정 외부 도메인 URL (선택)</label>
                      <input
                        type="url"
                        value={customPublicUrl}
                        onChange={(e) => setCustomPublicUrl(e.target.value)}
                        placeholder="예: https://search.mychurch.org"
                        className="w-full rounded-lg border border-black/[0.12] px-3 py-2 text-xs"
                      />
                    </div>
                  </div>

                  <button
                    type="button"
                    disabled={busyAction}
                    onClick={() => void handleSaveSettings(false)}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-xl bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a]"
                  >
                    <Save className="h-3.5 w-3.5" />
                    <span>AI 연결 · 안정성 설정 저장</span>
                  </button>
                </div>
              )}
            </div>
          ) : tab === 'updates' ? (
            <div className="space-y-4">
              {/* Current Version & Manual Check Card */}
              <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold text-[#18181b]">
                      목포사랑의교회 행정Q&A{' '}
                      <span className="rounded-md bg-[#18181b] px-1.5 py-0.5 text-[11px] font-semibold text-white">
                        v{updateInfo?.current_version || '2.4.0'}
                      </span>
                    </p>
                    <p className="mt-1 text-[11px] text-[#71717a]">
                      실행 환경:{' '}
                      {updateInfo?.install_mode === 'frozen_installed'
                        ? 'Windows 공식 설치본'
                        : updateInfo?.install_mode === 'frozen_portable'
                          ? 'Windows 포터블 EXE'
                          : '개발 소스 실행'}
                      {updateInfo?.last_checked_at
                        ? ` · 최근 확인: ${updateInfo.last_checked_at.slice(0, 16).replace('T', ' ')}`
                        : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={checkingUpdate}
                    onClick={() => void handleCheckUpdatesNow()}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-50"
                  >
                    {checkingUpdate ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    <span>지금 업데이트 확인</span>
                  </button>
                </div>
              </div>

              {/* Release Notes & Optional Update Action */}
              {updateInfo?.latest ? (
                <div className="space-y-3 rounded-xl border border-black/[0.08] bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`chip-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                          updateInfo.update_available
                            ? 'bg-[#0f4c81] text-white'
                            : 'bg-emerald-100 text-emerald-800'
                        }`}
                      >
                        {updateInfo.update_available
                          ? `새 버전 v${updateInfo.latest.version} 출시됨`
                          : `최신 버전 (v${updateInfo.latest.version})`}
                      </span>
                      {updateInfo.latest.published_at && (
                        <span className="text-[11px] text-[#71717a]">
                          {updateInfo.latest.published_at.slice(0, 10)}
                        </span>
                      )}
                    </div>
                    {updateInfo.latest.release_url && (
                      <a
                        href={updateInfo.latest.release_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="chip-nowrap inline-flex items-center gap-1 text-[11px] font-medium text-[#0f4c81] hover:underline"
                      >
                        <span>GitHub 릴리즈 보기</span>
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>

                  <div className="max-h-52 overflow-y-auto rounded-lg border border-black/[0.07] bg-[#fafaf9] p-3.5 text-xs leading-relaxed text-[#27272a]">
                    <MarkdownView content={updateInfo.latest.notes_md} />
                  </div>

                  {/* Progress Indicator */}
                  {(updateInfo.progress.status === 'downloading' ||
                    updateInfo.progress.status === 'verifying' ||
                    updateInfo.progress.status === 'ready' ||
                    updateInfo.progress.status === 'applying' ||
                    updateRestarting) && (
                    <div className="space-y-1.5 rounded-lg border border-[#0f4c81]/20 bg-[#0f4c81]/[0.04] p-3">
                      <div className="flex items-center justify-between text-xs font-semibold text-[#18181b]">
                        <span>
                          {updateRestarting
                            ? '새 버전 적용 후 자동 재시작 대기 중...'
                            : updateInfo.progress.message}
                        </span>
                        <span className="tabular-nums text-[#0f4c81]">{updateInfo.progress.progress_pct}%</span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#e4e4e7]">
                        <div
                          className="h-full rounded-full bg-[#0f4c81] transition-all"
                          style={{ width: `${Math.max(4, updateInfo.progress.progress_pct)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {isAdmin && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      {updateInfo.progress.staged_ready ? (
                        <button
                          type="button"
                          disabled={busyAction || updateRestarting}
                          onClick={() => void handleApplyStagedUpdate()}
                          className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-50"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          <span>DB 백업 후 적용 · 재시작</span>
                        </button>
                      ) : updateInfo.update_available && updateInfo.latest.assets?.win_patch_zip?.url ? (
                        <button
                          type="button"
                          disabled={
                            busyAction ||
                            updateInfo.progress.status === 'downloading' ||
                            updateInfo.progress.status === 'verifying'
                          }
                          onClick={() => void handleStartUpdateDownload()}
                          className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-50"
                        >
                          <Download className="h-3.5 w-3.5" />
                          <span>이 버전 선택 업데이트 다운로드</span>
                        </button>
                      ) : null}

                      {updateInfo.update_available && (
                        <button
                          type="button"
                          onClick={() =>
                            void api
                              .skipUpdateVersion(updateInfo.latest!.version)
                              .then(() => handleCheckUpdatesNow())
                          }
                          className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs font-medium text-[#52525b] hover:bg-[#f7f7f5]"
                        >
                          <SkipForward className="h-3.5 w-3.5" />
                          <span>이 버전 건너뛰기</span>
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-black/[0.12] p-5 text-center text-xs text-[#71717a]">
                  {updateInfo?.error || '상단의 [지금 업데이트 확인] 버튼을 눌러 최신 릴리즈를 확인할 수 있습니다.'}
                </div>
              )}

              {/* Safety Guarantee & Offline Patch Upload */}
              {isAdmin && (
                <div className="space-y-3 rounded-xl border border-black/[0.08] p-4">
                  <div className="flex items-start gap-2 text-[11.5px] text-[#3f3f46]">
                    <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#0f4c81]" />
                    <span>
                      모든 업데이트는 <strong>사용자 선택형</strong>이며, 적용 직전 <code>church_search.db</code>를 자동 백업하고 <code>data/</code> 폴더는 절대 건드리지 않습니다. 적용 실패 시 이전 버전으로 자동 롤백됩니다.
                    </span>
                  </div>

                  {/* Offline Patch ZIP Upload */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-black/[0.06] pt-3">
                    <div>
                      <p className="text-xs font-semibold text-[#18181b]">오프라인 업데이트 파일(.zip) 직접 적용</p>
                      <p className="text-[11px] text-[#71717a]">인터넷이 없는 PC에서는 전달받은 패치 ZIP을 직접 올려 업데이트할 수 있습니다</p>
                    </div>
                    <label className="chip-nowrap inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-black/[0.12] bg-white px-3 py-1.5 text-xs font-semibold text-[#18181b] hover:bg-[#f7f7f5]">
                      <Upload className="h-3.5 w-3.5" />
                      <span>패치 ZIP 선택</span>
                      <input
                        type="file"
                        accept=".zip"
                        className="hidden"
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) void handleUploadOfflinePatch(f);
                          e.target.value = '';
                        }}
                      />
                    </label>
                  </div>

                  {/* Update Channel Configuration */}
                  <div className="space-y-2.5 border-t border-black/[0.06] pt-3">
                    <label className="flex cursor-pointer items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-[#18181b]">앱 시작 시 새 버전 알림 자동 확인</p>
                        <p className="text-[11px] text-[#71717a]">끄면 수동으로 [지금 업데이트 확인]을 누를 때만 확인합니다</p>
                      </div>
                      <input
                        type="checkbox"
                        checked={updateAutoCheck}
                        onChange={(e) => setUpdateAutoCheck(e.target.checked)}
                        className="h-4 w-4 accent-[#18181b]"
                      />
                    </label>

                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div>
                        <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">업데이트 수신 채널</label>
                        <select
                          value={updateChannel}
                          onChange={(e) => setUpdateChannel(e.target.value as 'github' | 'custom')}
                          className="w-full rounded-lg border border-black/[0.12] bg-white px-3 py-1.5 text-xs"
                        >
                          <option value="github">GitHub 공식 릴리즈 (어디서든 배포 · 권장)</option>
                          <option value="custom">사용자 지정 피드 URL (Tailscale/교회 서버)</option>
                        </select>
                      </div>
                      {updateChannel === 'github' ? (
                        <div>
                          <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">GitHub 저장소</label>
                          <input
                            type="text"
                            value={updateRepo}
                            onChange={(e) => setUpdateRepo(e.target.value)}
                            placeholder="Anomi-LCB/mokpo-sarang-church-qa"
                            className="w-full rounded-lg border border-black/[0.12] px-3 py-1.5 text-xs"
                          />
                        </div>
                      ) : (
                        <div>
                          <label className="mb-1 block text-[11px] font-semibold text-[#18181b]">커스텀 매니페스트 URL</label>
                          <input
                            type="url"
                            value={updateCustomUrl}
                            onChange={(e) => setUpdateCustomUrl(e.target.value)}
                            placeholder="https://.../api/updates/local-manifest.json"
                            className="w-full rounded-lg border border-black/[0.12] px-3 py-1.5 text-xs"
                          />
                        </div>
                      )}
                    </div>

                    <button
                      type="button"
                      disabled={busyAction}
                      onClick={() => void handleSaveUpdateSettings()}
                      className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#27272a]"
                    >
                      <Save className="h-3.5 w-3.5" />
                      <span>업데이트 채널 설정 저장</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : tab === 'security' ? (
            <div className="space-y-4">
              {cli?.is_default_pin && (
                <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  <span>현재 기본 PIN(1234 / 0000)이 사용 중입니다. 외부 접속 전 반드시 고유 PIN 또는 비밀번호로 변경하세요.</span>
                </div>
              )}

              {/* PIN & Password Management */}
              <div className="space-y-3 rounded-xl border border-black/[0.08] p-4">
                <h4 className="text-xs font-semibold text-[#1d1d1f]">PIN · 비밀번호 변경 (숫자 또는 영문 조합 4~32자리)</h4>
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  <input
                    type="password"
                    value={memberPin}
                    onChange={(e) => setMemberPin(e.target.value)}
                    placeholder="새 팀원 PIN / 비밀번호"
                    className="rounded-lg border border-black/[0.12] px-3 py-2 text-xs"
                  />
                  <input
                    type="password"
                    value={adminPin}
                    onChange={(e) => setAdminPin(e.target.value)}
                    placeholder="새 관리자 PIN / 비밀번호"
                    className="rounded-lg border border-black/[0.12] px-3 py-2 text-xs"
                  />
                </div>
                <label className="flex items-center gap-2 text-xs text-[#424245]">
                  <input
                    type="checkbox"
                    checked={revokeOnPinChange}
                    onChange={(e) => setRevokeOnPinChange(e.target.checked)}
                    className="accent-[#007AFF]"
                  />
                  <span>변경 즉시 기존에 로그인된 다른 기기 세션 모두 만료</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busyAction || (!memberPin && !adminPin)}
                    onClick={() => void handleSavePins()}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#007AFF] px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-45"
                  >
                    <KeyRound className="h-3.5 w-3.5" />
                    <span>암호 변경 적용</span>
                  </button>
                  <button
                    type="button"
                    disabled={busyAction}
                    onClick={() => void handleRevokeAll()}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3.5 py-2 text-xs font-semibold text-red-700 hover:bg-red-100"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span>모든 기기 강제 로그아웃</span>
                  </button>
                </div>
              </div>

              {/* Privacy & Audit Policy toggles */}
              <div className="space-y-3 rounded-xl border border-black/[0.08] p-4">
                <label className="flex cursor-pointer items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold text-[#1d1d1f]">새 대화 기본 공개 범위: 팀 전체 공유</p>
                    <p className="text-[11px] text-[#6e6e73]">끄면(권장) 새 대화는 본인 기기에 비공개 저장되며 필요 시 개별 공유 가능</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={defaultChatShared}
                    onChange={(e) => setDefaultChatShared(e.target.checked)}
                    className="h-4 w-4 accent-[#007AFF]"
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between gap-3 border-t border-black/[0.06] pt-3">
                  <div>
                    <p className="text-xs font-semibold text-[#1d1d1f]">보안 감사 로그 기록</p>
                    <p className="text-[11px] text-[#6e6e73]">로그인·PIN 실패·문서 변경·질의 이력(메타데이터)을 기록합니다</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={auditLogEnabled}
                    onChange={(e) => setAuditLogEnabled(e.target.checked)}
                    className="h-4 w-4 accent-[#007AFF]"
                  />
                </label>

                <button
                  type="button"
                  disabled={busyAction}
                  onClick={() => void handleSaveSettings(false)}
                  className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3.5 py-1.5 text-xs font-semibold text-white"
                >
                  <Save className="h-3.5 w-3.5" />
                  <span>보안 정책 저장</span>
                </button>
              </div>

              {/* Recent Audit Logs */}
              <div className="space-y-2 rounded-xl border border-black/[0.08] p-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-[#1d1d1f]">최근 보안 감사 로그 ({auditLogs.length}건)</h4>
                  {auditLogs.length > 0 && (
                    <button
                      type="button"
                      onClick={() => void api.clearAuditLogs().then(() => setAuditLogs([]))}
                      className="chip-nowrap text-[11px] text-[#86868b] hover:text-red-600"
                    >
                      로그 비우기
                    </button>
                  )}
                </div>
                <div className="max-h-44 overflow-y-auto rounded-lg border border-black/[0.06] bg-[#fbfbfd]">
                  {auditLogs.length === 0 ? (
                    <p className="p-3 text-center text-[11px] text-[#86868b]">기록된 감사 이벤트가 없습니다.</p>
                  ) : (
                    auditLogs.map((lg) => (
                      <div
                        key={lg.id}
                        className="flex flex-wrap items-center justify-between gap-2 border-b border-black/[0.05] px-3 py-1.5 text-[11px] last:border-b-0"
                      >
                        <div className="min-w-0 flex-1">
                          <span className="font-semibold text-[#1d1d1f]">[{lg.event_type}]</span>{' '}
                          <span className="text-[#424245]">{lg.detail}</span>
                        </div>
                        <span className="chip-nowrap text-[10px] text-[#86868b]">
                          {lg.actor_label} · {lg.client_ip} · {lg.created_at.slice(5, 16).replace('T', ' ')}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {/* Active Notebook Rules */}
              {activeNotebook && (
                <div className="space-y-2 rounded-xl border border-black/[0.08] p-4">
                  <h4 className="text-xs font-semibold text-[#1d1d1f]">
                    현재 노트북({activeNotebook.name}) 전용 답변 규칙
                  </h4>
                  <textarea
                    rows={4}
                    value={nbRules}
                    onChange={(e) => setNbRules(e.target.value)}
                    className="w-full rounded-lg border border-black/[0.12] p-2.5 text-xs leading-relaxed"
                  />
                  <button
                    type="button"
                    disabled={busyAction}
                    onClick={() => void handleSaveNotebookRules()}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3.5 py-1.5 text-xs font-semibold text-white"
                  >
                    <Save className="h-3.5 w-3.5" />
                    <span>규칙 저장</span>
                  </button>
                </div>
              )}

              {/* Create New Notebook */}
              <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                <h4 className="text-xs font-semibold text-[#1d1d1f]">새 전용 검색기(노트북) 만들기</h4>
                <input
                  type="text"
                  value={newNbName}
                  onChange={(e) => setNewNbName(e.target.value)}
                  placeholder="노트북 이름 (예: 당회 회의록 검색기, 설교·교육 자료실)"
                  className="w-full rounded-lg border border-black/[0.12] px-3 py-2 text-xs"
                />
                <input
                  type="text"
                  value={newNbDesc}
                  onChange={(e) => setNewNbDesc(e.target.value)}
                  placeholder="간단한 설명 (선택)"
                  className="w-full rounded-lg border border-black/[0.12] px-3 py-2 text-xs"
                />
                <textarea
                  rows={2}
                  value={newNbRules}
                  onChange={(e) => setNewNbRules(e.target.value)}
                  placeholder="전용 답변 지침 (비우면 기본 근거 전용 규칙 적용)"
                  className="w-full rounded-lg border border-black/[0.12] p-2.5 text-xs"
                />
                <button
                  type="button"
                  disabled={busyAction || !newNbName.trim()}
                  onClick={() => void handleCreateNotebook()}
                  className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#007AFF] px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-45"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>새 노트북 생성</span>
                </button>

                {notebooks.length > 1 && (
                  <div className="mt-2 space-y-1.5 border-t border-black/[0.06] pt-2.5">
                    {notebooks.map((nb) => (
                      <div key={nb.id} className="flex items-center justify-between rounded-lg bg-[#f5f5f7] px-3 py-2 text-xs">
                        <span className="min-w-0 truncate font-medium text-[#1d1d1f]">
                          {nb.name} ({nb.doc_count}개 문서)
                        </span>
                        {nb.id !== 'mokpo-sarang-church' && (
                          <button
                            type="button"
                            onClick={() => setDeleteNbTarget(nb)}
                            title="노트북 삭제 (관리자 PIN 필요)"
                            className="shrink-0 rounded p-1 text-[#86868b] hover:bg-red-50 hover:text-red-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Automated DB Backups & Restore */}
              <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-[#1d1d1f]">
                    <HardDrive className="h-4 w-4 text-[#007AFF]" />
                    <span>DB 자동 백업 · 복구 (최신 12건 자동 보관)</span>
                  </div>
                  <button
                    type="button"
                    disabled={busyAction}
                    onClick={() => void handleCreateBackup()}
                    className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#007AFF] px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-[#0066D6]"
                  >
                    <Plus className="h-3 w-3" />
                    <span>지금 백업</span>
                  </button>
                </div>

                <div className="max-h-40 space-y-1 overflow-y-auto">
                  {backups.length === 0 ? (
                    <p className="py-2 text-center text-[11px] text-[#86868b]">저장된 백업이 없습니다.</p>
                  ) : (
                    backups.map((bk) => (
                      <div
                        key={bk.name}
                        className="flex items-center justify-between gap-2 rounded-lg bg-[#f5f5f7] px-3 py-2 text-[11px]"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-medium text-[#1d1d1f]">{bk.name}</p>
                          <p className="text-[10px] text-[#86868b]">
                            {(bk.size_bytes / 1024 / 1024).toFixed(2)} MB · {bk.created_at.replace('T', ' ')}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => void triggerTicketDownload(`/api/admin/backups/${encodeURIComponent(bk.name)}/download`)}
                            title="백업 파일 다운로드"
                            className="rounded-md bg-white p-1.5 text-[#424245] ring-1 ring-black/[0.08] hover:text-[#007AFF]"
                          >
                            <Download className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={busyAction}
                            onClick={() => void handleRestoreBackup(bk.name)}
                            title="이 백업으로 복원"
                            className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-white px-2 py-1 text-[10.5px] font-semibold text-[#1d1d1f] ring-1 ring-black/[0.08] hover:bg-amber-50 hover:text-amber-800"
                          >
                            <RotateCcw className="h-3 w-3" />
                            <span>복원</span>
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {deleteNbTarget && (
        <AdminPinConfirmModal
          title="노트북 삭제 확인"
          targetName={deleteNbTarget.name}
          onConfirm={handleConfirmDeleteNotebook}
          onClose={() => setDeleteNbTarget(null)}
        />
      )}
    </div>
  );
};
