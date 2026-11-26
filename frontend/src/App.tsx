import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUpCircle,
  BookOpen,
  FileStack,
  Flag,
  FolderKanban,
  FolderOpen,
  LogOut,
  MessageSquareText,
  PanelLeft,
  PanelRight,
  PlusSquare,
  QrCode,
  RefreshCw,
  Search,
  Server,
  Share,
  SlidersHorizontal,
  SquarePen,
  Users,
  WifiOff,
  X,
} from 'lucide-react';
import { api, authHeaders, isIOS, isStandalonePWA } from './api';
import { AdminModal, type AdminTab } from './components/AdminModal';
import { AutofillModal } from './components/AutofillModal';
import { ChatPanel } from './components/ChatPanel';
import { CommandPaletteModal } from './components/CommandPaletteModal';
import { FeedbackModal } from './components/FeedbackModal';
import { FormsVault } from './components/FormsVault';
import { GroupsModal } from './components/GroupsModal';
import { LibraryModal } from './components/LibraryModal';
import { PageViewerModal } from './components/PageViewerModal';
import { PinGate } from './components/PinGate';
import { SourcesPanel } from './components/SourcesPanel';
import { StandardizationWorkspace } from './components/StandardizationWorkspace';
import { UpdateModal } from './components/UpdateModal';
import {
  loadShelfState,
  resolveShelfDocuments,
  saveShelfState,
  type ShelfState,
} from './libraryStore';
import {
  bundleToDocuments,
  bundleToNotebook,
  listOfflineBundles,
  loadOfflineBundle,
  saveOfflineBundle,
  searchOfflineBundle,
  type OfflineBundle,
} from './offlineStore';
import type {
  AnswerMode,
  AuthState,
  ChatMessage,
  ChatSession,
  CollabGroup,
  DocumentItem,
  FormItem,
  Notebook,
  UpdateCheckResponse,
} from './types';

const ANSWER_MODES: Array<{
  id: AnswerMode;
  label: string;
  badge: string;
  desc: string;
}> = [
  {
    id: 'auto',
    label: '자동',
    badge: '질문 맞춤 자동 조합',
    desc: '질문 성격을 AI가 판단해 원문 조항 인용·실무 절차 정리·적용 제안을 가장 알맞게 조합해 답변합니다.',
  },
  {
    id: 'practical',
    label: '실무 정리',
    badge: '절차·표·체크리스트',
    desc: '근거 조항을 바탕으로 자격 요건·기한·담당 부서·처리 절차를 실무용 표와 단계별로 일목요연하게 정리합니다.',
  },
  {
    id: 'strict',
    label: '원문 엄격',
    badge: '무추측 조항 그대로',
    desc: '헌법·정관·시행세칙 원문에 명시된 내용만 엄격히 인용하며, 규정 밖의 해석이나 추측을 배제합니다.',
  },
  {
    id: 'advisory',
    label: '적용·제안',
    badge: '근거 + 현장 실행안',
    desc: '관련 규정 원문을 먼저 제시한 뒤, 실제 교회 행정 현장에서의 적용 유의점과 보완 실행안을 함께 제안합니다.',
  },
];

function lastSessionKey(nbId: string): string {
  return `church_search_last_session_${nbId}`;
}

interface AndroidBridge {
  openServerSettings?: () => void;
}

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [activeNbId, setActiveNbId] = useState<string>('mokpo-sarang-church');
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [forms, setForms] = useState<FormItem[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mode, setMode] = useState<AnswerMode>('auto');
  const [instantMode, setInstantMode] = useState(false);
  const [doubleVerify, setDoubleVerify] = useState(false);
  const [busy, setBusy] = useState(false);

  const [isOfflineMode, setIsOfflineMode] = useState(false);
  const [offlineBundle, setOfflineBundle] = useState<OfflineBundle | null>(null);
  const [offlineSyncedAt, setOfflineSyncedAt] = useState('');
  const [dismissIosBanner, setDismissIosBanner] = useState<boolean>(() => {
    try {
      return localStorage.getItem('church_search_dismiss_ios_tip') === '1';
    } catch {
      return false;
    }
  });

  const [showSidebar, setShowSidebar] = useState<boolean>(() => {
    try {
      return localStorage.getItem('church_search_show_sidebar') !== '0';
    } catch {
      return true;
    }
  });
  const [showInspector, setShowInspector] = useState<boolean>(() => {
    try {
      return localStorage.getItem('church_search_show_inspector') !== '0';
    } catch {
      return true;
    }
  });
  const [disableFormsPanel, setDisableFormsPanel] = useState<boolean>(() => {
    try {
      return localStorage.getItem('church_search_disable_forms') === '1';
    } catch {
      return false;
    }
  });
  const [mobileTab, setMobileTab] = useState<'chat' | 'sources' | 'forms'>('chat');

  const toggleSidebar = () => {
    setShowSidebar((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('church_search_show_sidebar', next ? '1' : '0');
      } catch {
        // ignore
      }
      return next;
    });
  };

  const toggleInspector = () => {
    setShowInspector((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('church_search_show_inspector', next ? '1' : '0');
      } catch {
        // ignore
      }
      return next;
    });
  };

  const handleDisableFormsPanel = (disabled: boolean) => {
    setDisableFormsPanel(disabled);
    try {
      localStorage.setItem('church_search_disable_forms', disabled ? '1' : '0');
    } catch {
      // ignore
    }
    if (disabled && mobileTab === 'forms') {
      setMobileTab('chat');
    }
  };

  const [viewerTarget, setViewerTarget] = useState<{
    docId: string;
    pageNo: number;
    highlightText?: string;
  } | null>(null);
  const [autofillTarget, setAutofillTarget] = useState<FormItem | null>(null);
  const [adminModalTab, setAdminModalTab] = useState<AdminTab | null>(null);
  const [showFeedbackModal, setShowFeedbackModal] = useState(false);
  const [showLibraryModal, setShowLibraryModal] = useState(false);
  const [showGroupsModal, setShowGroupsModal] = useState(false);
  const [showCommandPalette, setShowCommandPalette] = useState(false);
  const [shelf, setShelf] = useState<ShelfState>(() => loadShelfState('mokpo-sarang-church'));
  const [groups, setGroups] = useState<CollabGroup[]>([]);
  const [stdRefreshTick, setStdRefreshTick] = useState(0);
  const [stdInitialBoardId, setStdInitialBoardId] = useState('');
  const [globalNotice, setGlobalNotice] = useState('');
  const [workspace, setWorkspace] = useState<'qa' | 'std'>('qa');
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResponse | null>(null);
  const [showUpdateModal, setShowUpdateModal] = useState(false);
  const [localSkippedVer, setLocalSkippedVer] = useState<string>(() => {
    try {
      return localStorage.getItem('church_search_skipped_ver') || '';
    } catch {
      return '';
    }
  });

  const activeNbIdRef = useRef(activeNbId);
  activeNbIdRef.current = activeNbId;
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  const flashGlobalNotice = useCallback((msg: string) => {
    setGlobalNotice(msg);
    window.setTimeout(() => setGlobalNotice(''), 4200);
  }, []);

  const loadGroups = useCallback(async () => {
    try {
      const res = await api.listGroups();
      setGroups(res.groups || []);
    } catch {
      // ignore
    }
  }, []);

  // Global Ctrl+K / Cmd+K Quick Command Palette
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        if (!auth?.authenticated || isOfflineMode) return;
        e.preventDefault();
        setShowCommandPalette((prev) => !prev);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [auth?.authenticated, isOfflineMode]);

  useEffect(() => {
    if (!auth?.authenticated || isOfflineMode) return;
    let cancelled = false;
    void api
      .checkUpdates(false)
      .then((res) => {
        if (!cancelled && res.settings?.auto_check !== false) {
          setUpdateInfo(res);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [auth?.authenticated, isOfflineMode]);

  const showUpdateBadge = Boolean(
    updateInfo?.should_notify &&
      updateInfo.latest?.version &&
      updateInfo.latest.version !== localSkippedVer
  );

  const androidBridge = (window as unknown as { AndroidApp?: AndroidBridge }).AndroidApp;

  const enterOfflineModeWithBundle = useCallback((bundle: OfflineBundle) => {
    setOfflineBundle(bundle);
    setOfflineSyncedAt(bundle.synced_at || bundle.generated_at);
    setIsOfflineMode(true);
    setInstantMode(true);
    setNotebooks([bundleToNotebook(bundle)]);
    setActiveNbId(bundle.notebook.id);
    const docs = bundleToDocuments(bundle);
    setDocuments(docs);
    setSelectedDocIds(docs.map((d) => d.id));
    setForms(bundle.forms);
    setSessions([]);
    setAuth({ authenticated: true, role: 'member', label: '오프라인 모드', owner_id: 'offline' });
  }, []);

  const syncOfflineInBackground = useCallback(async (nbId: string) => {
    try {
      const existing = await loadOfflineBundle(nbId);
      if (existing) {
        setOfflineBundle(existing);
        setOfflineSyncedAt(existing.synced_at || existing.generated_at);
      }
      if (typeof navigator !== 'undefined' && !navigator.onLine) return;
      const raw = await api.getOfflineBundle(nbId);
      const syncedAt = new Date().toISOString();
      const full: OfflineBundle = { ...raw, synced_at: syncedAt };
      await saveOfflineBundle(full);
      setOfflineBundle(full);
      setOfflineSyncedAt(syncedAt);
    } catch {
      // silent background sync
    }
  }, []);

  const checkAuth = useCallback(async () => {
    const cachedList = await listOfflineBundles();
    const cachedDefault =
      cachedList.find((b) => b.notebook.id === 'mokpo-sarang-church') || cachedList[0] || null;
    if (cachedDefault) {
      setOfflineBundle(cachedDefault);
      setOfflineSyncedAt(cachedDefault.synced_at || cachedDefault.generated_at);
    }

    if (typeof navigator !== 'undefined' && !navigator.onLine && cachedDefault) {
      enterOfflineModeWithBundle(cachedDefault);
      return;
    }

    try {
      const st = await api.authMe();
      setIsOfflineMode(false);
      setAuth(st);
      if (st.default_double_verify) {
        setDoubleVerify(true);
      }
    } catch {
      if (cachedDefault) {
        enterOfflineModeWithBundle(cachedDefault);
      } else {
        setAuth({ authenticated: false });
      }
    }
  }, [enterOfflineModeWithBundle]);

  useEffect(() => {
    void checkAuth();
  }, [checkAuth]);

  useEffect(() => {
    const onOffline = () => {
      if (offlineBundle && !isOfflineMode) {
        setIsOfflineMode(true);
        setInstantMode(true);
      }
    };
    const onOnline = () => {
      if (isOfflineMode) {
        void checkAuth();
      }
    };
    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onOnline);
    return () => {
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onOnline);
    };
  }, [offlineBundle, isOfflineMode, checkAuth]);

  const loadSessionMessages = useCallback(async (sid: string, nbId: string) => {
    try {
      const rows = await api.getSessionMessages(sid);
      setSessionId(sid);
      try {
        localStorage.setItem(lastSessionKey(nbId), sid);
      } catch {
        // ignore
      }
      setMessages(
        rows.map((r) => ({
          id: `db_${r.id}`,
          role: r.role,
          content: r.content,
          mode: r.mode || 'practical',
          citations: r.citations || [],
          forms: r.forms || [],
          verification: r.verification && Object.keys(r.verification).length > 0 ? r.verification : undefined,
          provider: r.provider,
          author_label: r.author_label || '',
          hasEvidence: r.provider !== 'grounding-gate',
          streaming: false,
        }))
      );
      setMobileTab('chat');
    } catch {
      // ignore
    }
  }, []);

  const refreshSessions = useCallback(async (nbId: string) => {
    try {
      const sessList = await api.listSessions(nbId);
      setSessions(sessList);
      return sessList;
    } catch {
      return [] as ChatSession[];
    }
  }, []);

  const loadNotebookData = useCallback(
    async (nbId: string, restoreSavedChat = true) => {
      try {
        const [docs, frms, sessList] = await Promise.all([
          api.listDocuments(nbId),
          api.listForms(nbId),
          api.listSessions(nbId),
        ]);
        setDocuments(docs);
        const nextShelf = loadShelfState(nbId);
        setShelf(nextShelf);
        const { allShelfDocs } = resolveShelfDocuments(docs, nextShelf);
        setSelectedDocIds(allShelfDocs.filter((d) => d.status === 'ready').map((d) => d.id));
        setForms(frms);
        setSessions(sessList);
        void syncOfflineInBackground(nbId);

        if (restoreSavedChat && sessList.length > 0) {
          let savedSid = '';
          try {
            savedSid = localStorage.getItem(lastSessionKey(nbId)) || '';
          } catch {
            // ignore
          }
          const target = sessList.find((s) => s.id === savedSid);
          if (target) {
            await loadSessionMessages(target.id, nbId);
          }
        }
      } catch {
        // ignore
      }
    },
    [loadSessionMessages, syncOfflineInBackground]
  );

  const loadNotebooks = useCallback(
    async (selectId?: string, restoreSavedChat = true) => {
      try {
        const list = await api.listNotebooks();
        setNotebooks(list);
        const targetId =
          selectId && list.some((n) => n.id === selectId)
            ? selectId
            : list.some((n) => n.id === activeNbId)
              ? activeNbId
              : list[0]?.id || 'mokpo-sarang-church';
        setActiveNbId(targetId);
        await loadNotebookData(targetId, restoreSavedChat);
      } catch {
        // ignore
      }
    },
    [activeNbId, loadNotebookData]
  );

  useEffect(() => {
    if (auth?.authenticated && !isOfflineMode) {
      void loadNotebooks(undefined, true);
      void loadGroups();
    }
  }, [auth?.authenticated, isOfflineMode, loadNotebooks, loadGroups]);

  // Handle ?join=INVITE_CODE auto-join from shared invite link / QR
  useEffect(() => {
    if (!auth?.authenticated || isOfflineMode) return;
    const params = new URLSearchParams(window.location.search);
    const code = (params.get('join') || '').trim();
    if (!code) return;
    const cleanUrl = `${window.location.pathname}${window.location.hash || ''}`;
    window.history.replaceState({}, '', cleanUrl);
    void api
      .joinGroup(code)
      .then((res) => {
        void loadGroups();
        void refreshSessions(activeNbIdRef.current);
        setStdRefreshTick((t) => t + 1);
        flashGlobalNotice(`"${res.group.name}" 그룹에 초대 코드로 참여했습니다.`);
      })
      .catch((err: unknown) => {
        flashGlobalNotice(err instanceof Error ? err.message : '초대 코드 참여에 실패했습니다.');
      });
  }, [auth?.authenticated, isOfflineMode, loadGroups, refreshSessions, flashGlobalNotice]);

  // Real-time Server-Sent Events (/api/events/stream) for live group chats & standardization boards
  useEffect(() => {
    if (!auth?.authenticated || isOfflineMode) return;
    let disposed = false;
    let controller = new AbortController();
    let reconnectTimer: number | null = null;

    const connect = async () => {
      if (disposed) return;
      controller = new AbortController();
      try {
        const res = await fetch('/api/events/stream', {
          method: 'GET',
          credentials: 'include',
          headers: authHeaders({ Accept: 'text/event-stream' }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (!disposed) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf('\n\n')) !== -1) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            let evName = 'message';
            let dataStr = '';
            for (const line of block.split('\n')) {
              if (line.startsWith('event:')) evName = line.slice(6).trim();
              else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
            }
            if (!dataStr || evName === 'connected' || evName === 'ping') continue;
            try {
              const payload = JSON.parse(dataStr);
              if (evName === 'chat_updated') {
                void refreshSessions(activeNbIdRef.current);
                if (
                  payload.session_id &&
                  payload.session_id === sessionIdRef.current &&
                  !busyRef.current
                ) {
                  void loadSessionMessages(payload.session_id, activeNbIdRef.current);
                }
              } else if (evName === 'std_updated') {
                setStdRefreshTick((t) => t + 1);
              } else if (evName === 'group_updated') {
                void loadGroups();
                void refreshSessions(activeNbIdRef.current);
                setStdRefreshTick((t) => t + 1);
              }
            } catch {
              // ignore malformed SSE chunk
            }
          }
        }
      } catch {
        // automatic quiet reconnect below
      }
      if (!disposed) {
        reconnectTimer = window.setTimeout(() => {
          void connect();
        }, 4500);
      }
    };

    void connect();
    return () => {
      disposed = true;
      controller.abort();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    };
  }, [auth?.authenticated, isOfflineMode, loadGroups, loadSessionMessages, refreshSessions]);

  const handleNotebookSwitch = async (nbId: string) => {
    setActiveNbId(nbId);
    setMessages([]);
    setSessionId(null);
    if (isOfflineMode) {
      const b = await loadOfflineBundle(nbId);
      if (b) enterOfflineModeWithBundle(b);
      return;
    }
    await loadNotebookData(nbId, true);
  };

  const handleNewChat = () => {
    setMessages([]);
    setSessionId(null);
    try {
      localStorage.removeItem(lastSessionKey(activeNbId));
    } catch {
      // ignore
    }
    setMobileTab('chat');
  };

  const handleRenameSession = async (sid: string, title: string) => {
    await api.updateSession(sid, { title });
    await refreshSessions(activeNbId);
  };

  const handleSetSessionScope = async (
    sid: string,
    scope: { is_shared: boolean; group_id: string }
  ) => {
    await api.updateSession(sid, { is_shared: scope.is_shared, group_id: scope.group_id });
    await refreshSessions(activeNbId);
  };

  const handleDeleteSession = async (sid: string) => {
    await api.deleteSession(sid);
    if (sessionId === sid) {
      handleNewChat();
    }
    await refreshSessions(activeNbId);
  };

  const { pinnedDocs, loadedDocs, allShelfDocs } = useMemo(
    () => resolveShelfDocuments(documents, shelf),
    [documents, shelf]
  );
  const shelfDocIds = useMemo(() => new Set(allShelfDocs.map((d) => d.id)), [allShelfDocs]);
  const userPinnedIds = useMemo(() => new Set(shelf.pinnedIds), [shelf.pinnedIds]);

  const updateShelf = useCallback(
    (updater: (prev: ShelfState) => ShelfState) => {
      setShelf((prev) => {
        const next = updater(prev);
        saveShelfState(activeNbId, next);
        return next;
      });
    },
    [activeNbId]
  );

  const handleToggleUserPin = (docId: string) => {
    const currentlyPinned = shelf.pinnedIds.includes(docId);
    updateShelf((prev) => ({
      pinnedIds: currentlyPinned
        ? prev.pinnedIds.filter((id) => id !== docId)
        : [...prev.pinnedIds, docId],
      loadedIds: currentlyPinned ? prev.loadedIds : prev.loadedIds.filter((id) => id !== docId),
      unloadedIds: prev.unloadedIds.filter((id) => id !== docId),
    }));
    if (!currentlyPinned) {
      setSelectedDocIds((prev) => (prev.includes(docId) ? prev : [...prev, docId]));
    }
  };

  const handleUnloadFromShelf = (docId: string) => {
    updateShelf((prev) => ({
      pinnedIds: prev.pinnedIds.filter((id) => id !== docId),
      loadedIds: prev.loadedIds.filter((id) => id !== docId),
      unloadedIds: prev.unloadedIds.includes(docId) ? prev.unloadedIds : [...prev.unloadedIds, docId],
    }));
    setSelectedDocIds((prev) => prev.filter((id) => id !== docId));
  };

  const handleToggleShelfLoad = (docId: string) => {
    if (shelfDocIds.has(docId)) {
      handleUnloadFromShelf(docId);
    } else {
      updateShelf((prev) => ({
        pinnedIds: prev.pinnedIds,
        loadedIds: prev.loadedIds.includes(docId) ? prev.loadedIds : [...prev.loadedIds, docId],
        unloadedIds: prev.unloadedIds.filter((id) => id !== docId),
      }));
      setSelectedDocIds((prev) => (prev.includes(docId) ? prev : [...prev, docId]));
    }
  };

  const handleBatchLoadToShelf = (docIds: string[], replaceLoaded = false) => {
    const unique = Array.from(new Set(docIds));
    updateShelf((prev) => {
      const baseLoaded = replaceLoaded ? [] : prev.loadedIds;
      const merged = Array.from(new Set([...baseLoaded, ...unique])).filter(
        (id) => !prev.pinnedIds.includes(id)
      );
      const nextUnloaded = replaceLoaded
        ? documents
            .map((d) => d.id)
            .filter((id) => !unique.includes(id) && !prev.pinnedIds.includes(id))
        : prev.unloadedIds.filter((id) => !unique.includes(id));
      return {
        pinnedIds: prev.pinnedIds,
        loadedIds: merged,
        unloadedIds: nextUnloaded,
      };
    });
    setSelectedDocIds((prev) => Array.from(new Set([...prev, ...unique])));
    flashGlobalNotice(`${unique.length}건의 자료를 왼쪽 작업대에 불러왔습니다.`);
  };

  const handleToggleDoc = (docId: string) => {
    setSelectedDocIds((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]));
  };

  const handleSelectAllDocs = (all: boolean) => {
    setSelectedDocIds(all ? allShelfDocs.filter((d) => d.status === 'ready').map((d) => d.id) : []);
  };

  const handleSend = async (query: string) => {
    if (busy) return;
    setBusy(true);
    const effMode = instantMode || isOfflineMode ? 'instant' : mode;
    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      role: 'user',
      content: query,
      mode: effMode,
      citations: [],
      forms: [],
      author_label: auth?.label || '',
    };
    const aiMsgId = `a_${Date.now() + 1}`;
    const aiPlaceholder: ChatMessage = {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      mode: effMode,
      citations: [],
      forms: [],
      streaming: true,
      statusText: instantMode || isOfflineMode ? '오프라인 원문 즉시 검색 중...' : '근거 조항 검색 중...',
    };
    setMessages((prev) => [...prev, userMsg, aiPlaceholder]);

    const updateAi = (patch: Partial<ChatMessage>) => {
      setMessages((prev) => prev.map((m) => (m.id === aiMsgId ? { ...m, ...patch } : m)));
    };
    const appendAiText = (delta: string) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === aiMsgId ? { ...m, content: m.content + delta } : m))
      );
    };

    const runOfflineAnswer = (bundle: OfflineBundle) => {
      const out = searchOfflineBundle(bundle, query, selectedDocIds, 8);
      updateAi({
        streaming: false,
        statusText: '',
        content: out.markdown,
        citations: out.citations,
        forms: out.forms,
        hasEvidence: out.hasEvidence,
        provider: 'device-offline',
        verification: out.hasEvidence
          ? {
              status: 'verified',
              verified_count: out.citations.length,
              summary: `기기 내장 오프라인 색인 직접 추출 ${out.citations.length}건`,
            }
          : {
              status: 'no_evidence',
              verified_count: 0,
              summary: '근거 미발견 차단',
            },
      });
    };

    if ((isOfflineMode || (typeof navigator !== 'undefined' && !navigator.onLine)) && offlineBundle) {
      runOfflineAnswer(offlineBundle);
      setBusy(false);
      return;
    }

    try {
      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          notebook_id: activeNbId,
          session_id: sessionId,
          query,
          doc_ids: selectedDocIds,
          mode,
          instant: instantMode,
          double_verify: doubleVerify && !instantMode,
        }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`응답 오류 (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const rawBlock = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let evName = 'message';
          let dataStr = '';
          for (const line of rawBlock.split('\n')) {
            if (line.startsWith('event:')) evName = line.slice(6).trim();
            else if (line.startsWith('data:')) dataStr += line.slice(5).trim();
          }
          if (!dataStr) continue;
          try {
            const payload = JSON.parse(dataStr);
            if (evName === 'meta') {
              if (payload.session_id) {
                setSessionId(payload.session_id);
                try {
                  localStorage.setItem(lastSessionKey(activeNbId), payload.session_id);
                } catch {
                  // ignore
                }
              }
              updateAi({ provider: payload.provider });
            } else if (evName === 'status') {
              updateAi({ statusText: payload.message });
            } else if (evName === 'evidence') {
              updateAi({
                hasEvidence: payload.has_evidence,
                citations: payload.citations || [],
                forms: payload.forms || [],
              });
            } else if (evName === 'delta') {
              appendAiText(payload.text || '');
            } else if (evName === 'replace') {
              updateAi({ content: payload.text || '' });
            } else if (evName === 'verification') {
              updateAi({ verification: payload });
            } else if (evName === 'done') {
              updateAi({
                streaming: false,
                statusText: '',
                hasEvidence: payload.has_evidence,
                provider: payload.provider,
                verification: payload.verification || undefined,
              });
            } else if (evName === 'error') {
              updateAi({
                streaming: false,
                statusText: '',
                content: `오류가 발생했습니다: ${payload.message}`,
              });
            }
          } catch {
            // ignore
          }
        }
      }
      updateAi({ streaming: false, statusText: '' });
      void refreshSessions(activeNbId);
    } catch (err) {
      if (offlineBundle) {
        setIsOfflineMode(true);
        setInstantMode(true);
        runOfflineAnswer(offlineBundle);
      } else {
        updateAi({
          streaming: false,
          statusText: '',
          content: `요청 처리 중 오류가 발생했습니다: ${err instanceof Error ? err.message : '알 수 없는 오류'}`,
        });
      }
    } finally {
      setBusy(false);
    }
  };

  if (auth === null) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[#f7f7f5] text-sm text-[#71717a]">
        연결 확인 중...
      </div>
    );
  }

  if (!auth.authenticated) {
    return (
      <PinGate
        hasOfflineCache={Boolean(offlineBundle)}
        onEnterOffline={offlineBundle ? () => enterOfflineModeWithBundle(offlineBundle) : undefined}
        onSuccess={(role, label, ownerId, isDefaultPin) => {
          setIsOfflineMode(false);
          setAuth({ authenticated: true, role, label, owner_id: ownerId, is_default_pin: isDefaultPin });
        }}
      />
    );
  }

  const isAdmin = auth.role === 'admin' && !isOfflineMode;
  const activeNotebook = notebooks.find((n) => n.id === activeNbId) || null;
  const activeSession = sessions.find((s) => s.id === sessionId) || null;
  const showIosInstallBanner = isIOS() && !isStandalonePWA() && !dismissIosBanner;

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-white">
      {/* Bespoke Editorial Window Toolbar (48px) */}
      <header className="safe-top relative z-30 flex min-h-[48px] shrink-0 items-center justify-between gap-2 border-b border-black/[0.075] bg-white/95 px-3 py-1 backdrop-blur-xl sm:px-4">
        {/* Left: Sidebar Toggle + Minimal Brand + Workspace Switcher + Notebook */}
        <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
          {workspace === 'qa' && (
            <button
              type="button"
              onClick={toggleSidebar}
              title={showSidebar ? '왼쪽 자료 패널 접기' : '왼쪽 자료 패널 열기'}
              aria-label={showSidebar ? '왼쪽 자료 패널 접기' : '왼쪽 자료 패널 열기'}
              className={`hidden rounded-md p-1.5 transition lg:inline-flex ${
                showSidebar ? 'bg-black/[0.06] text-[#18181b]' : 'text-[#71717a] hover:bg-black/[0.045] hover:text-[#18181b]'
              }`}
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          )}

          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[#18181b] text-white">
            <BookOpen className="h-3.5 w-3.5" strokeWidth={2} />
          </div>

          {/* 2-Workspace Primary Switcher: 행정 Q&A | 행정 표준화실 */}
          {!isOfflineMode && (
            <div className="inline-flex shrink-0 rounded-lg bg-[#f0f0ee] p-0.5">
              <button
                type="button"
                onClick={() => setWorkspace('qa')}
                className={`chip-nowrap rounded-[6px] px-2 py-1 text-[11.5px] font-semibold transition ${
                  workspace === 'qa'
                    ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgba(0,0,0,0.07)]'
                    : 'text-[#71717a] hover:text-[#18181b]'
                }`}
              >
                행정 Q&amp;A
              </button>
              <button
                type="button"
                onClick={() => setWorkspace('std')}
                className={`chip-nowrap inline-flex items-center gap-1 rounded-[6px] px-2 py-1 text-[11.5px] font-semibold transition ${
                  workspace === 'std'
                    ? 'bg-white text-[#0f4c81] shadow-[0_1px_2px_rgba(0,0,0,0.07)]'
                    : 'text-[#71717a] hover:text-[#18181b]'
                }`}
              >
                <FolderKanban className="h-3 w-3 hidden sm:inline" />
                <span>표준화실</span>
              </button>
            </div>
          )}

          {workspace === 'qa' && (
            <select
              aria-label="노트북 선택"
              value={activeNbId}
              onChange={(e) => void handleNotebookSwitch(e.target.value)}
              className="hidden min-w-0 max-w-[165px] truncate rounded-md border border-transparent bg-transparent px-1.5 py-1 text-[12.5px] font-semibold text-[#3f3f46] outline-none transition hover:bg-black/[0.045] focus:border-black/[0.12] focus:bg-[#f7f7f5] xl:block xl:max-w-[200px]"
            >
              {notebooks.map((nb) => (
                <option key={nb.id} value={nb.id}>
                  {nb.id === 'mokpo-sarang-church' ? '목포사랑의교회 행정Q&A' : nb.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Center (Desktop): Refined 4-Mode Segmented Control with Hover Explanation Cards */}
        <div className="hidden items-center justify-center lg:flex">
          {workspace === 'qa' ? (
            <div className="inline-flex rounded-lg bg-[#f0f0ee] p-0.5">
              {ANSWER_MODES.map((opt) => (
                <div key={opt.id} className="group/mode relative">
                  <button
                    type="button"
                    title={`${opt.label} — ${opt.desc}`}
                    onClick={() => {
                      setMode(opt.id);
                      setInstantMode(false);
                    }}
                    className={`chip-nowrap rounded-[6px] px-2.5 py-1 text-[11.5px] font-semibold transition ${
                      mode === opt.id && !instantMode
                        ? 'bg-white text-[#18181b] shadow-[0_1px_2px_rgba(0,0,0,0.07)]'
                        : 'text-[#71717a] hover:text-[#18181b]'
                    }`}
                  >
                    {opt.label}
                  </button>
                  {/* Hover Popover Card explaining each mode's specialty */}
                  <div
                    role="tooltip"
                    className="pointer-events-none invisible absolute top-full left-1/2 z-50 mt-2 w-64 -translate-x-1/2 rounded-xl border border-black/[0.09] bg-white p-3 text-left opacity-0 shadow-[0_10px_28px_rgba(0,0,0,0.12)] transition duration-150 group-hover/mode:visible group-hover/mode:opacity-100 group-focus-within/mode:visible group-focus-within/mode:opacity-100"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[12px] font-semibold text-[#18181b]">{opt.label}</span>
                      <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[#0f4c81]">
                        {opt.badge}
                      </span>
                    </div>
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-[#52525b]">{opt.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <span className="text-xs font-semibold text-[#52525b]">
              행정 표준화실 · 파일 수집 · 투표 합의 · 전문가 PDF 편찬
            </span>
          )}
        </div>

        {/* Right: Quiet Studio Toolbar Actions */}
        <div className="flex shrink-0 flex-1 items-center justify-end gap-0.5 sm:gap-1">
          {showUpdateBadge && updateInfo?.latest && (
            <button
              type="button"
              onClick={() => setShowUpdateModal(true)}
              title={`새 버전 v${updateInfo.latest.version} 업데이트 내용 보기`}
              className="chip-nowrap inline-flex items-center gap-1 rounded-full bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold text-white transition hover:bg-[#0c3d68]"
            >
              <ArrowUpCircle className="h-3.5 w-3.5 shrink-0" />
              <span className="hidden sm:inline">업데이트</span>
              <span>v{updateInfo.latest.version}</span>
            </button>
          )}

          {isOfflineMode && (
            <button
              type="button"
              onClick={() => void checkAuth()}
              title="오프라인 모드 동작 중 — 눌러서 서버 재연결 시도"
              className="chip-nowrap inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-300/80 transition hover:bg-amber-200"
            >
              <WifiOff className="h-3 w-3 shrink-0" />
              <span>오프라인</span>
              <RefreshCw className="h-3 w-3 shrink-0" />
            </button>
          )}

          {androidBridge?.openServerSettings && (
            <button
              type="button"
              onClick={() => androidBridge.openServerSettings?.()}
              title="서버 주소 변경"
              aria-label="서버 주소 변경"
              className="rounded-md p-1.5 text-[#0f4c81] transition hover:bg-black/[0.05]"
            >
              <Server className="h-4 w-4" />
            </button>
          )}

          {!isOfflineMode && (
            <>
              <button
                type="button"
                onClick={() => setShowCommandPalette(true)}
                title="전체 빠른 검색 (Ctrl+K)"
                aria-label="전체 빠른 검색"
                className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
              >
                <Search className="h-3.5 w-3.5" />
                <span className="hidden xl:inline">검색</span>
                <kbd className="hidden rounded border border-black/[0.1] bg-[#f7f7f5] px-1 text-[10px] text-[#8a8a8e] xl:inline">
                  Ctrl K
                </kbd>
              </button>

              <button
                type="button"
                onClick={() => setShowGroupsModal(true)}
                title="협업 그룹 · 초대 · 개설 권한 · 기기 간 복구"
                aria-label="그룹 관리"
                className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
              >
                <Users className="h-3.5 w-3.5" />
                <span className="hidden md:inline">그룹</span>
                {groups.length > 0 && (
                  <span className="rounded-full bg-[#0f4c81]/12 px-1.5 py-0.2 text-[10px] font-bold text-[#0f4c81]">
                    {groups.length}
                  </span>
                )}
              </button>
            </>
          )}

          <button
            type="button"
            onClick={handleNewChat}
            title="새 대화 시작"
            className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
          >
            <SquarePen className="h-4 w-4" />
            <span className="hidden xl:inline">새 대화</span>
          </button>

          <button
            type="button"
            onClick={() => setShowFeedbackModal(true)}
            title="버그·불편·개선사항 제작자에게 제보"
            aria-label="버그 및 개선사항 제보"
            className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
          >
            <Flag className="h-3.5 w-3.5" />
            <span className="hidden md:inline">제보</span>
          </button>

          {!isOfflineMode && (
            <>
              <button
                type="button"
                onClick={() => setAdminModalTab('connect')}
                title="모바일 QR 연결 및 APK"
                className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
              >
                <QrCode className="h-4 w-4" />
                <span className="hidden sm:inline">연결</span>
              </button>

              <button
                type="button"
                onClick={() => setAdminModalTab(isAdmin && auth.is_default_pin ? 'security' : 'cli')}
                title={isAdmin && auth.is_default_pin ? '설정 (기본 PIN 변경 권장)' : '환경 설정'}
                className="chip-nowrap relative inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-[#52525b] transition hover:bg-black/[0.05] hover:text-[#18181b]"
              >
                <SlidersHorizontal className="h-4 w-4" />
                <span className="hidden sm:inline">설정</span>
                {isAdmin && auth.is_default_pin && (
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
                )}
              </button>
            </>
          )}

          {workspace === 'qa' && !disableFormsPanel && (
            <button
              type="button"
              onClick={toggleInspector}
              title={showInspector ? '오른쪽 서식 창 접기' : '오른쪽 서식 창 열기'}
              aria-label={showInspector ? '오른쪽 서식 창 접기' : '오른쪽 서식 창 열기'}
              className={`hidden rounded-md p-1.5 transition lg:inline-flex ${
                showInspector ? 'bg-black/[0.06] text-[#18181b]' : 'text-[#71717a] hover:bg-black/[0.045] hover:text-[#18181b]'
              }`}
            >
              <PanelRight className="h-4 w-4" />
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              setIsOfflineMode(false);
              void api.logout().then(() => setAuth({ authenticated: false }));
            }}
            title="로그아웃"
            aria-label="로그아웃"
            className="rounded-md p-1.5 text-[#8a8a8e] transition hover:bg-red-50 hover:text-red-600"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Subtle iOS Safari Home-Screen Install Tip (shown ONLY on non-standalone iOS) */}
      {showIosInstallBanner && (
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.07] bg-[#f7f7f5] px-3.5 py-1.5 text-[11.5px] text-[#3f3f46]">
          <div className="flex min-w-0 items-center gap-1.5">
            <Share className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
            <span className="truncate">
              Safari 하단 <strong>공유</strong> →{' '}
              <PlusSquare className="inline h-3 w-3 align-text-bottom text-[#0f4c81]" />{' '}
              <strong>홈 화면에 추가</strong>로 오프라인 앱 설치
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              setDismissIosBanner(true);
              try {
                localStorage.setItem('church_search_dismiss_ios_tip', '1');
              } catch {
                // ignore
              }
            }}
            aria-label="안내 닫기"
            className="shrink-0 rounded p-0.5 text-[#71717a] hover:bg-black/[0.06]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {globalNotice && (
        <div className="flex items-center justify-between gap-2 border-b border-[#0f4c81]/20 bg-[#0f4c81]/[0.06] px-4 py-1.5 text-xs font-medium text-[#0f4c81]">
          <span className="truncate">{globalNotice}</span>
          <button
            type="button"
            onClick={() => setGlobalNotice('')}
            aria-label="알림 닫기"
            className="shrink-0 rounded p-0.5 hover:bg-black/[0.06]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Main Workspace: Either Q&A 3-Surface Studio OR Administrative Standardization Studio */}
      {workspace === 'std' ? (
        <StandardizationWorkspace
          isAdmin={isAdmin}
          currentOwnerId={auth.owner_id || ''}
          qaDocuments={documents}
          activeNotebookId={activeNbId}
          groups={groups}
          refreshTick={stdRefreshTick}
          initialBoardId={stdInitialBoardId}
          onOpenGroups={() => setShowGroupsModal(true)}
          onQaDocumentsUpdated={() => void loadNotebooks(activeNbId, false)}
        />
      ) : (
        <>
      <main className="flex min-h-0 flex-1 overflow-hidden">
        <aside
          data-panel="sidebar"
          className={`${
            mobileTab === 'sources'
              ? 'flex w-full'
              : showSidebar
                ? 'hidden lg:flex lg:w-[264px] xl:w-[280px]'
                : 'hidden'
          } min-h-0 min-w-0 shrink-0 flex-col border-r border-black/[0.07]`}
        >
          <SourcesPanel
            notebookId={activeNbId}
            allDocumentCount={documents.length}
            pinnedDocs={pinnedDocs}
            loadedDocs={loadedDocs}
            userPinnedIds={userPinnedIds}
            selectedDocIds={selectedDocIds}
            sessions={sessions}
            groups={groups}
            activeSessionId={sessionId}
            currentOwnerId={auth.owner_id || ''}
            isAdmin={isAdmin}
            onToggleDoc={handleToggleDoc}
            onSelectAll={handleSelectAllDocs}
            onToggleUserPin={handleToggleUserPin}
            onUnloadFromShelf={handleUnloadFromShelf}
            onOpenLibrary={() => setShowLibraryModal(true)}
            onOpenGroups={() => setShowGroupsModal(true)}
            onOpenViewer={(docId, pageNo) => setViewerTarget({ docId, pageNo })}
            onSelectSession={(sid) => void loadSessionMessages(sid, activeNbId)}
            onNewChat={handleNewChat}
            onRenameSession={handleRenameSession}
            onSetSessionScope={handleSetSessionScope}
            onDeleteSession={handleDeleteSession}
            onRefresh={() => void loadNotebooks(activeNbId, false)}
          />
        </aside>

        <section
          className={`${
            mobileTab === 'chat' ? 'flex w-full' : 'hidden'
          } min-h-0 min-w-0 flex-1 flex-col lg:flex`}
        >
          <ChatPanel
            notebook={activeNotebook}
            activeSession={activeSession}
            messages={messages}
            mode={mode}
            instantMode={instantMode || isOfflineMode}
            doubleVerify={doubleVerify}
            selectedDocCount={selectedDocIds.length}
            totalDocCount={allShelfDocs.length}
            busy={busy}
            onModeChange={(m) => {
              setMode(m);
              if (!isOfflineMode) setInstantMode(false);
            }}
            onInstantToggle={(v) => {
              if (!isOfflineMode) setInstantMode(v);
            }}
            onDoubleVerifyToggle={setDoubleVerify}
            onSend={(q) => void handleSend(q)}
            onOpenViewer={(docId, pageNo, highlightText) =>
              setViewerTarget({ docId, pageNo, highlightText })
            }
            onOpenAutofill={(form) => setAutofillTarget(form)}
          />
        </section>

        {!disableFormsPanel && (
          <aside
            data-panel="inspector"
            className={`${
              mobileTab === 'forms'
                ? 'flex w-full'
                : showInspector
                  ? 'hidden lg:flex lg:w-[296px] xl:w-[320px]'
                  : 'hidden'
            } min-h-0 min-w-0 shrink-0 flex-col border-l border-black/[0.07]`}
          >
            <FormsVault
              forms={forms}
              onOpenViewer={(docId, pageNo) => setViewerTarget({ docId, pageNo })}
              onOpenAutofill={(form) => setAutofillTarget(form)}
              onOpenProfile={!isOfflineMode ? () => setAdminModalTab('profile') : undefined}
              onCollapse={toggleInspector}
            />
          </aside>
        )}
      </main>

      {/* Mobile Bottom Tab Bar (< lg) */}
      <nav
        className={`safe-bottom relative z-10 grid min-h-14 shrink-0 ${
          disableFormsPanel ? 'grid-cols-2' : 'grid-cols-3'
        } border-t border-black/[0.075] bg-white/95 backdrop-blur-lg lg:hidden`}
      >
        <button
          type="button"
          onClick={() => setMobileTab('chat')}
          className={`chip-nowrap flex flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] font-semibold ${
            mobileTab === 'chat' ? 'text-[#18181b]' : 'text-[#8a8a8e]'
          }`}
        >
          <MessageSquareText className="h-5 w-5" strokeWidth={1.85} />
          <span>질문</span>
        </button>
        <button
          type="button"
          onClick={() => setMobileTab('sources')}
          className={`chip-nowrap flex flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] font-semibold ${
            mobileTab === 'sources' ? 'text-[#18181b]' : 'text-[#8a8a8e]'
          }`}
        >
          <FolderOpen className="h-5 w-5" strokeWidth={1.85} />
          <span>자료·대화</span>
        </button>
        {!disableFormsPanel && (
          <button
            type="button"
            onClick={() => setMobileTab('forms')}
            className={`chip-nowrap flex flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] font-semibold ${
              mobileTab === 'forms' ? 'text-[#18181b]' : 'text-[#8a8a8e]'
            }`}
          >
            <FileStack className="h-5 w-5" strokeWidth={1.85} />
            <span>서식함</span>
          </button>
        )}
      </nav>
        </>
      )}

      {viewerTarget && (
        <PageViewerModal
          docId={viewerTarget.docId}
          initialPage={viewerTarget.pageNo}
          highlightText={viewerTarget.highlightText}
          offlineBundle={offlineBundle}
          isOfflineMode={isOfflineMode}
          onClose={() => setViewerTarget(null)}
        />
      )}

      {showLibraryModal && (
        <LibraryModal
          notebookId={activeNbId}
          documents={documents}
          shelf={shelf}
          shelfDocIds={shelfDocIds}
          isAdmin={isAdmin}
          onToggleUserPin={handleToggleUserPin}
          onToggleShelfLoad={handleToggleShelfLoad}
          onBatchLoadToShelf={handleBatchLoadToShelf}
          onOpenViewer={(docId, pageNo) => setViewerTarget({ docId, pageNo })}
          onRefresh={() => void loadNotebooks(activeNbId, false)}
          onClose={() => setShowLibraryModal(false)}
        />
      )}

      {showGroupsModal && (
        <GroupsModal
          isAdmin={isAdmin}
          currentOwnerId={auth.owner_id || ''}
          onGroupsChanged={() => {
            void loadGroups();
            void refreshSessions(activeNbId);
            setStdRefreshTick((t) => t + 1);
          }}
          onIdentityRecovered={() => {
            void checkAuth();
            void loadGroups();
            void refreshSessions(activeNbId);
            setStdRefreshTick((t) => t + 1);
          }}
          onClose={() => setShowGroupsModal(false)}
        />
      )}

      {showCommandPalette && (
        <CommandPaletteModal
          notebookId={activeNbId}
          onSelectDocument={(doc) => {
            if (!shelfDocIds.has(doc.id)) {
              handleToggleShelfLoad(doc.id);
            } else if (!selectedDocIds.includes(doc.id)) {
              setSelectedDocIds((prev) => [...prev, doc.id]);
            }
            setWorkspace('qa');
            setViewerTarget({ docId: doc.id, pageNo: 1 });
          }}
          onSelectForm={(form) => {
            setWorkspace('qa');
            setAutofillTarget(form);
          }}
          onSelectSession={(sess) => {
            setWorkspace('qa');
            void loadSessionMessages(sess.id, activeNbId);
          }}
          onSelectBoard={(board) => {
            setStdInitialBoardId(board.id);
            setWorkspace('std');
          }}
          onQuickAction={(action) => {
            if (action === 'new_chat') {
              setWorkspace('qa');
              handleNewChat();
            } else if (action === 'library') {
              setWorkspace('qa');
              setShowLibraryModal(true);
            } else if (action === 'groups') {
              setShowGroupsModal(true);
            } else if (action === 'std') {
              setWorkspace('std');
            }
          }}
          onClose={() => setShowCommandPalette(false)}
        />
      )}

      {autofillTarget && (
        <AutofillModal form={autofillTarget} onClose={() => setAutofillTarget(null)} />
      )}

      {showFeedbackModal && (
        <FeedbackModal
          contextInfo={`노트북:${activeNbId} | 모드:${mode} | 선택문서:${selectedDocIds.length}/${documents.length}`}
          isOfflineMode={isOfflineMode}
          onClose={() => setShowFeedbackModal(false)}
        />
      )}

      {showUpdateModal && updateInfo && (
        <UpdateModal
          info={updateInfo}
          isAdmin={isAdmin}
          onSkipped={(ver) => {
            setLocalSkippedVer(ver);
            try {
              localStorage.setItem('church_search_skipped_ver', ver);
            } catch {
              // ignore
            }
          }}
          onClose={() => setShowUpdateModal(false)}
        />
      )}

      {adminModalTab && (
        <AdminModal
          isAdmin={isAdmin}
          initialTab={adminModalTab}
          activeNotebook={activeNotebook}
          notebooks={notebooks}
          forms={forms}
          offlineSyncedAt={offlineSyncedAt}
          onOfflineSynced={setOfflineSyncedAt}
          disableFormsPanel={disableFormsPanel}
          onDisableFormsPanelChange={handleDisableFormsPanel}
          onNotebooksChanged={(sel) => void loadNotebooks(sel, false)}
          onPinSecurityChanged={(isDef) =>
            setAuth((prev) => (prev ? { ...prev, is_default_pin: isDef } : prev))
          }
          onClose={() => setAdminModalTab(null)}
        />
      )}
    </div>
  );
}
export default App;
