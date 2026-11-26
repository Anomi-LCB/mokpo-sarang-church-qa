import type {
  AiConnectionMode,
  AiTestResult,
  AuditLogItem,
  AuthState,
  BackupItem,
  ChatSession,
  Citation,
  CliSettings,
  CollabGroup,
  DocumentItem,
  FeedbackCategory,
  FeedbackInboxResponse,
  FeedbackItem,
  FeedbackStatus,
  FormItem,
  GroupsResponse,
  MemberDirectoryItem,
  NetworkSummary,
  Notebook,
  QuickSearchResult,
  StdBoard,
  StdBoardDetail,
  StdComment,
  StdConfig,
  StdCrossMemory,
  StdProposal,
  StdSubmission,
  StructuredFormDraft,
  UpdateCheckResponse,
  UpdateProgress,
  UpdateSettings,
  VerificationResult,
} from './types';
import { cacheFormPdfBlob, getCachedFormPdf, type OfflineBundle } from './offlineStore';

const TOKEN_STORAGE_KEY = 'church_search_auth_token';
const CLIENT_ID_KEY = 'church_search_client_id';

export function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  return (
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  );
}

export function isStandalonePWA(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    window.matchMedia?.('(display-mode: standalone)')?.matches === true ||
    (window.navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

export function getClientId(): string {
  try {
    let cid = localStorage.getItem(CLIENT_ID_KEY);
    if (!cid) {
      cid = 'dev_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
      localStorage.setItem(CLIENT_ID_KEY, cid);
    }
    return cid;
  } catch {
    return 'dev_default';
  }
}

export function getStoredToken(): string {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

export function setStoredToken(token: string): void {
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // ignore
  }
}

export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const tok = getStoredToken();
  return tok ? { Authorization: `Bearer ${tok}`, ...extra } : { ...extra };
}

/** Same-origin GET requests use HttpOnly cookie cleanly with zero long-lived token in URLs. */
export function safeAssetUrl(path: string): string {
  return path;
}

function parseFilenameFromDisposition(cd: string | null, fallback: string): string {
  if (!cd) return fallback;
  const utf8Match = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      // ignore
    }
  }
  const plainMatch = cd.match(/filename="?([^";]+)"?/i);
  if (plainMatch?.[1]) return plainMatch[1].trim();
  return fallback;
}

async function deliverBlobOnDevice(blob: Blob, filename: string): Promise<void> {
  const mime = blob.type || (filename.endsWith('.pdf') ? 'application/pdf' : 'application/octet-stream');
  const file = new File([blob], filename, { type: mime });
  const nav = navigator as Navigator & {
    canShare?: (data: { files?: File[] }) => boolean;
    share?: (data: { files?: File[]; title?: string }) => Promise<void>;
  };

  if (nav.share && (!nav.canShare || nav.canShare({ files: [file] }))) {
    try {
      await nav.share({ files: [file], title: filename });
      return;
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
    }
  }

  // Safe fallback for iOS standalone PWA (never hijack window.location.href!)
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objUrl;
  a.download = filename;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(objUrl), 60_000);
}

/**
 * Smart download handler:
 * - On iOS/Safari/PWA: fetches blob + opens native iOS Share Sheet ("파일에 저장 / 프린트 / AirDrop") & caches PDFs offline!
 * - In offline mode: serves previously cached form PDFs from Cache Storage!
 * - On Desktop / Android APK: triggers direct short-lived ticket download.
 */
export async function triggerTicketDownload(path: string, fallbackName = 'document.pdf'): Promise<void> {
  const formPdfMatch = path.match(/\/api\/forms\/([^/]+)\/download\/pdf/i);
  const formId = formPdfMatch ? decodeURIComponent(formPdfMatch[1]) : '';

  // Serve cached PDF immediately if offline
  if (formId && typeof navigator !== 'undefined' && !navigator.onLine) {
    const cached = await getCachedFormPdf(formId);
    if (cached) {
      await deliverBlobOnDevice(cached.blob, cached.filename);
      return;
    }
    window.alert('오프라인 상태이며 이 서식 PDF가 아직 기기에 저장되지 않았습니다. 온라인 연결 시 [설정 → 오프라인 서식 저장]을 눌러두면 오프라인에서도 열 수 있습니다.');
    return;
  }

  if (isIOS() || isStandalonePWA()) {
    try {
      const res = await fetch(path, {
        credentials: 'include',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`다운로드 오류 (${res.status})`);
      const blob = await res.blob();
      const filename = parseFilenameFromDisposition(res.headers.get('Content-Disposition'), fallbackName);
      if (formId) {
        void cacheFormPdfBlob(formId, blob, filename);
      }
      await deliverBlobOnDevice(blob, filename);
      return;
    } catch {
      if (formId) {
        const cached = await getCachedFormPdf(formId);
        if (cached) {
          await deliverBlobOnDevice(cached.blob, cached.filename);
          return;
        }
      }
    }
  }

  try {
    const { ticket } = await api.issueTicket();
    const sep = path.includes('?') ? '&' : '?';
    window.location.href = `${path}${sep}ticket=${encodeURIComponent(ticket)}`;
  } catch {
    if (formId) {
      const cached = await getCachedFormPdf(formId);
      if (cached) {
        await deliverBlobOnDevice(cached.blob, cached.filename);
        return;
      }
    }
    window.location.href = path;
  }
}

async function reqJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    credentials: 'include',
    ...init,
    headers: authHeaders(
      init.body instanceof FormData
        ? (init.headers as Record<string, string>) || {}
        : { 'Content-Type': 'application/json', ...((init.headers as Record<string, string>) || {}) }
    ),
  });
  if (!res.ok) {
    let msg = `요청 오류 (${res.status})`;
    try {
      const data = await res.json();
      if (data?.detail) msg = data.detail;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  authMe: () => reqJson<AuthState>('/api/auth/me'),
  issueTicket: () => reqJson<{ ticket: string; expires_in: number }>('/api/auth/ticket', { method: 'POST' }),
  login: async (pin: string, label: string) => {
    const res = await reqJson<{
      ok: boolean;
      role: 'member' | 'admin';
      label: string;
      owner_id: string;
      is_default_pin: boolean;
      token: string;
    }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ pin, label, client_id: getClientId() }),
    });
    setStoredToken(res.token);
    return res;
  },
  logout: async () => {
    setStoredToken('');
    await reqJson('/api/auth/logout', { method: 'POST' }).catch(() => {});
  },
  updatePins: async (member_pin?: string, admin_pin?: string, revoke_existing = true) => {
    const res = await reqJson<{ ok: boolean; token?: string; is_default_pin: boolean }>('/api/admin/pins', {
      method: 'PUT',
      body: JSON.stringify({
        member_pin: member_pin || null,
        admin_pin: admin_pin || null,
        revoke_existing,
      }),
    });
    if (res.token) setStoredToken(res.token);
    return res;
  },
  revokeAllSessions: async () => {
    const res = await reqJson<{ ok: boolean; token?: string; token_version: number }>(
      '/api/admin/revoke-sessions',
      { method: 'POST' }
    );
    if (res.token) setStoredToken(res.token);
    return res;
  },

  listNotebooks: () => reqJson<Notebook[]>('/api/notebooks'),
  createNotebook: (name: string, description: string, system_rules: string) =>
    reqJson<Notebook>('/api/notebooks', {
      method: 'POST',
      body: JSON.stringify({ name, description, system_rules }),
    }),
  updateNotebook: (id: string, payload: { name?: string; description?: string; system_rules?: string }) =>
    reqJson<Notebook>(`/api/notebooks/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteNotebook: (id: string, adminPin: string) =>
    reqJson<{ ok: boolean }>(`/api/notebooks/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: { 'X-Admin-Pin': adminPin },
    }),

  listDocuments: (notebookId: string) =>
    reqJson<DocumentItem[]>(`/api/notebooks/${encodeURIComponent(notebookId)}/documents`),
  getOfflineBundle: (notebookId: string) =>
    reqJson<Omit<OfflineBundle, 'synced_at'>>(
      `/api/notebooks/${encodeURIComponent(notebookId)}/offline-bundle`
    ),
  uploadDocuments: (notebookId: string, files: File[], category = '일반 자료', priority = 50) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));
    fd.append('category', category);
    fd.append('priority', String(priority));
    return reqJson<{ job_id: string; status: string }>(
      `/api/notebooks/${encodeURIComponent(notebookId)}/documents/upload`,
      { method: 'POST', body: fd }
    );
  },
  updateDocumentMeta: (docId: string, payload: { title?: string; category?: string; priority?: number }) =>
    reqJson<DocumentItem>(`/api/documents/${encodeURIComponent(docId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  updateDocumentLibrary: (docId: string, payload: { is_pinned_default?: boolean; tags?: string[] }) =>
    reqJson<DocumentItem>(`/api/documents/${encodeURIComponent(docId)}/library`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  replaceDocument: (
    docId: string,
    file: File,
    meta: { title?: string; category?: string; priority?: number } = {}
  ) => {
    const fd = new FormData();
    fd.append('file', file);
    if (meta.title !== undefined) fd.append('title', meta.title);
    if (meta.category !== undefined) fd.append('category', meta.category);
    if (meta.priority !== undefined) fd.append('priority', String(meta.priority));
    return reqJson<{ job_id: string; status: string }>(
      `/api/documents/${encodeURIComponent(docId)}/replace`,
      { method: 'POST', body: fd }
    );
  },
  getJob: (jobId: string) =>
    reqJson<{ id: string; status: string; progress: number; message: string; error: string }>(
      `/api/jobs/${encodeURIComponent(jobId)}`
    ),
  deleteDocument: (docId: string, adminPin: string) =>
    reqJson<{ ok: boolean }>(`/api/documents/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
      headers: { 'X-Admin-Pin': adminPin },
    }),
  getPageText: (docId: string, pageNo: number) =>
    reqJson<{
      doc_id: string;
      doc_title: string;
      file_type: string;
      page_count: number;
      page_no: number;
      is_ocr: boolean;
      text: string;
    }>(`/api/documents/${encodeURIComponent(docId)}/page/${pageNo}/text`),

  listSessions: (notebookId: string) =>
    reqJson<ChatSession[]>(`/api/notebooks/${encodeURIComponent(notebookId)}/sessions`),
  getSessionMessages: (sessionId: string) =>
    reqJson<
      Array<{
        id: number;
        role: 'user' | 'assistant';
        content: string;
        mode: 'auto' | 'practical' | 'strict' | 'advisory' | 'instant';
        citations: Citation[];
        forms: FormItem[];
        verification?: VerificationResult;
        provider: string;
        author_label?: string;
        author_owner_id?: string;
      }>
    >(`/api/sessions/${encodeURIComponent(sessionId)}/messages`),
  updateSession: (sessionId: string, payload: { title?: string; is_shared?: boolean; group_id?: string }) =>
    reqJson<ChatSession>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteSession: (sessionId: string) =>
    reqJson<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),

  listForms: (notebookId: string, q = '') =>
    reqJson<FormItem[]>(
      `/api/notebooks/${encodeURIComponent(notebookId)}/forms${q ? `?q=${encodeURIComponent(q)}` : ''}`
    ),
  autofillForm: (formId: string, instruction: string, profile?: Record<string, string>) =>
    reqJson<{
      ok: boolean;
      filename: string;
      download_url: string;
      structured: Partial<StructuredFormDraft>;
    }>(`/api/forms/${encodeURIComponent(formId)}/autofill`, {
      method: 'POST',
      body: JSON.stringify({ instruction, use_cli: true, profile: profile || null }),
    }),
  renderFormDocx: (formId: string, draft: StructuredFormDraft) =>
    reqJson<{ ok: boolean; filename: string; download_url: string }>(
      `/api/forms/${encodeURIComponent(formId)}/render-docx`,
      {
        method: 'POST',
        body: JSON.stringify(draft),
      }
    ),

  // Feedback & Creator-only Inbox
  submitFeedback: (payload: {
    category: FeedbackCategory;
    title: string;
    description: string;
    device_info?: string;
    context_info?: string;
  }) =>
    reqJson<{ ok: boolean; id: number; relayed_remote: boolean; created_at: string }>('/api/feedback', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listCreatorFeedback: (creatorPin: string, status = '') =>
    reqJson<FeedbackInboxResponse>(
      `/api/admin/feedback${status ? `?status=${encodeURIComponent(status)}` : ''}`,
      { headers: { 'X-Creator-Pin': creatorPin } }
    ),
  updateCreatorFeedback: (
    feedbackId: number,
    creatorPin: string,
    payload: { status?: FeedbackStatus; creator_note?: string }
  ) =>
    reqJson<FeedbackItem>(`/api/admin/feedback/${feedbackId}`, {
      method: 'PATCH',
      headers: { 'X-Creator-Pin': creatorPin },
      body: JSON.stringify(payload),
    }),
  deleteCreatorFeedback: (feedbackId: number, creatorPin: string) =>
    reqJson<{ ok: boolean }>(`/api/admin/feedback/${feedbackId}`, {
      method: 'DELETE',
      headers: { 'X-Creator-Pin': creatorPin },
    }),
  updateCreatorSettings: (
    creatorPin: string,
    payload: { new_creator_pin?: string; creator_relay_url?: string; creator_relay_token_out?: string }
  ) =>
    reqJson<{ ok: boolean; has_custom_creator_pin: boolean }>('/api/admin/creator-settings', {
      method: 'PUT',
      headers: { 'X-Creator-Pin': creatorPin },
      body: JSON.stringify(payload),
    }),

  exportReportDocx: (payload: {
    notebook_name: string;
    question: string;
    answer: string;
    mode: string;
    citations: Citation[];
    verification?: VerificationResult;
  }) =>
    reqJson<{ ok: boolean; filename: string; download_url: string }>('/api/reports/export-docx', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getCliSettings: () => reqJson<CliSettings>('/api/admin/cli'),
  updateCliSettings: (payload: {
    connection_mode: AiConnectionMode;
    provider: string;
    model: string;
    api_provider: string;
    api_model: string;
    api_base_url: string;
    api_key?: string;
    clear_api_key?: boolean;
    max_concurrent: number;
    custom_public_url: string;
    cli_failover_enabled: boolean;
    default_double_verify: boolean;
    default_chat_shared: boolean;
    audit_log_enabled: boolean;
  }) => reqJson<{ ok: boolean }>('/api/admin/cli', { method: 'PUT', body: JSON.stringify(payload) }),
  testAiConnection: (payload: {
    mode: 'api' | 'cli';
    provider: string;
    api_key?: string;
    model?: string;
    base_url?: string;
  }) => reqJson<AiTestResult>('/api/admin/ai/test', { method: 'POST', body: JSON.stringify(payload) }),

  // ---- Opt-In Updates ----
  checkUpdates: (force = false) =>
    reqJson<UpdateCheckResponse>(`/api/updates/check${force ? '?force=1' : ''}`),
  getUpdateStatus: () =>
    reqJson<{ current_version: string; progress: UpdateProgress }>('/api/updates/status'),
  saveUpdateSettings: (payload: Partial<UpdateSettings>) =>
    reqJson<{ ok: boolean; settings: UpdateSettings }>('/api/updates/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  skipUpdateVersion: (version: string) =>
    reqJson<{ ok: boolean; skipped_version: string }>('/api/updates/skip', {
      method: 'POST',
      body: JSON.stringify({ version }),
    }),
  downloadUpdate: () =>
    reqJson<{ ok: boolean; already_running?: boolean; progress: UpdateProgress }>('/api/updates/download', {
      method: 'POST',
    }),
  uploadOfflinePatch: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return reqJson<{ ok: boolean; version: string; progress: UpdateProgress }>('/api/updates/upload-patch', {
      method: 'POST',
      body: fd,
    });
  },
  applyUpdate: () =>
    reqJson<{ ok: boolean; restarting: boolean; install_mode: string; message: string }>('/api/updates/apply', {
      method: 'POST',
    }),

  listAuditLogs: () => reqJson<AuditLogItem[]>('/api/admin/audit-logs'),
  clearAuditLogs: () => reqJson<{ ok: boolean }>('/api/admin/audit-logs', { method: 'DELETE' }),

  listBackups: () => reqJson<BackupItem[]>('/api/admin/backups'),
  createBackup: () => reqJson<BackupItem>('/api/admin/backups', { method: 'POST' }),
  restoreBackup: (name: string) =>
    reqJson<{ ok: boolean; restored: string; safety_backup: string }>(
      `/api/admin/backups/${encodeURIComponent(name)}/restore`,
      { method: 'POST' }
    ),

  getNetwork: () => reqJson<NetworkSummary>('/api/admin/network'),
  startTunnel: (kind: 'tailscale' | 'cloudflare', token = '') =>
    reqJson<{ ok: boolean; url?: string; message: string }>('/api/admin/tunnel/start', {
      method: 'POST',
      body: JSON.stringify({ kind, token }),
    }),
  stopTunnel: (kind: 'tailscale' | 'cloudflare') =>
    reqJson<{ ok: boolean; message: string }>('/api/admin/tunnel/stop', {
      method: 'POST',
      body: JSON.stringify({ kind }),
    }),

  // ---- Groups, Invites, Member Permissions, Recovery & Quick Search ----
  listGroups: () => reqJson<GroupsResponse>('/api/groups'),
  createGroup: (name: string, description = '') =>
    reqJson<CollabGroup>('/api/groups', { method: 'POST', body: JSON.stringify({ name, description }) }),
  joinGroup: (invite_code: string) =>
    reqJson<{ ok: boolean; group: CollabGroup }>('/api/groups/join', {
      method: 'POST',
      body: JSON.stringify({ invite_code }),
    }),
  inviteGroupMember: (groupId: string, owner_id: string, member_label = '') =>
    reqJson<{ ok: boolean; group: CollabGroup }>(`/api/groups/${encodeURIComponent(groupId)}/invite`, {
      method: 'POST',
      body: JSON.stringify({ owner_id, member_label }),
    }),
  regenerateGroupCode: (groupId: string) =>
    reqJson<{ ok: boolean; group: CollabGroup }>(`/api/groups/${encodeURIComponent(groupId)}/regenerate-code`, {
      method: 'POST',
    }),
  getGroupInviteQr: (groupId: string) =>
    reqJson<{ invite_code: string; join_url: string; qr_data_url: string }>(
      `/api/groups/${encodeURIComponent(groupId)}/invite-qr`
    ),
  removeGroupMember: (groupId: string, memberOwnerId: string) =>
    reqJson<{ ok: boolean }>(
      `/api/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(memberOwnerId)}`,
      { method: 'DELETE' }
    ),
  deleteGroup: (groupId: string) =>
    reqJson<{ ok: boolean }>(`/api/groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' }),
  listMembersAdmin: () => reqJson<MemberDirectoryItem[]>('/api/admin/members'),
  setMemberGroupPermission: (ownerId: string, can_create_group: boolean) =>
    reqJson<MemberDirectoryItem>(`/api/admin/members/${encodeURIComponent(ownerId)}/permissions`, {
      method: 'PATCH',
      body: JSON.stringify({ can_create_group }),
    }),
  setRecoveryCode: (code: string) =>
    reqJson<{ ok: boolean }>('/api/auth/recovery-code', { method: 'POST', body: JSON.stringify({ code }) }),
  claimRecoveryCode: async (code: string) => {
    const res = await reqJson<{ ok: boolean; owner_id: string; label: string; role: 'member' | 'admin'; token: string }>(
      '/api/auth/claim-recovery',
      { method: 'POST', body: JSON.stringify({ code }) }
    );
    if (res.token) setStoredToken(res.token);
    return res;
  },
  quickSearch: (q: string, notebookId = 'mokpo-sarang-church') =>
    reqJson<QuickSearchResult>(
      `/api/search/quick?notebook_id=${encodeURIComponent(notebookId)}&q=${encodeURIComponent(q)}`
    ),

  // ---- Administrative Standardization Workspace ----
  stdGetConfig: () => reqJson<StdConfig>('/api/std/config'),
  stdSaveConfig: (payload: Partial<StdConfig>) =>
    reqJson<StdConfig>('/api/std/config', { method: 'PUT', body: JSON.stringify(payload) }),
  stdResetConfig: () => reqJson<StdConfig>('/api/std/config/reset', { method: 'POST' }),
  stdListBoards: () => reqJson<StdBoard[]>('/api/std/boards'),
  stdCreateBoard: (payload: {
    title: string;
    category: string;
    work_type: string;
    description: string;
    guidelines: string;
    deadline: string;
    vote_visibility: 'named' | 'anonymous';
    submission_anonymous: boolean;
    allow_vote_change: boolean;
    auto_route_enabled: boolean;
    group_id?: string;
  }) =>
    reqJson<StdBoard & { matched_memories?: StdCrossMemory[] }>('/api/std/boards', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stdGetBoard: (boardId: string) => reqJson<StdBoardDetail>(`/api/std/boards/${encodeURIComponent(boardId)}`),
  stdUpdateBoard: (boardId: string, payload: Record<string, unknown>) =>
    reqJson<StdBoard>(`/api/std/boards/${encodeURIComponent(boardId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  stdDeleteBoard: (boardId: string) =>
    reqJson<{ ok: boolean }>(`/api/std/boards/${encodeURIComponent(boardId)}`, { method: 'DELETE' }),
  stdSubmit: (boardId: string, payload: { title: string; notes: string; file?: File | null; use_ai?: boolean }) => {
    const fd = new FormData();
    fd.append('title', payload.title);
    fd.append('notes', payload.notes);
    fd.append('use_ai', payload.use_ai === false ? 'false' : 'true');
    if (payload.file) fd.append('file', payload.file);
    return reqJson<{ ok: boolean; submission: StdSubmission; analysis: { memories: StdCrossMemory[]; auto_applied_count: number } }>(
      `/api/std/boards/${encodeURIComponent(boardId)}/submissions`,
      { method: 'POST', body: fd }
    );
  },
  stdDeleteSubmission: (subId: string) =>
    reqJson<{ ok: boolean }>(`/api/std/submissions/${encodeURIComponent(subId)}`, { method: 'DELETE' }),
  stdListCrossMemories: (boardId = '', status = '') => {
    const qs = new URLSearchParams();
    if (boardId) qs.set('board_id', boardId);
    if (status) qs.set('status', status);
    const s = qs.toString();
    return reqJson<StdCrossMemory[]>(`/api/std/cross-memory${s ? `?${s}` : ''}`);
  },
  stdScanMemory: (boardId: string) =>
    reqJson<{ ok: boolean; matched: StdCrossMemory[] }>(`/api/std/boards/${encodeURIComponent(boardId)}/scan-memory`, {
      method: 'POST',
    }),
  stdApplyMemory: (
    memId: string,
    payload: { action: 'move' | 'copy' | 'merge' | 'dismiss' | 'revert'; target_board_id?: string; merged_title?: string }
  ) =>
    reqJson<{ ok: boolean; memory: StdCrossMemory }>(`/api/std/cross-memory/${encodeURIComponent(memId)}/apply`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stdBatchAction: (payload: {
    action: 'move' | 'copy' | 'merge';
    submission_ids: string[];
    target_board_id: string;
    merged_title?: string;
  }) =>
    reqJson<{ ok: boolean }>('/api/std/submissions/batch-action', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stdGenerateProposals: (boardId: string, useAi = true) =>
    reqJson<{ ok: boolean; created: StdProposal[]; count: number }>(
      `/api/std/boards/${encodeURIComponent(boardId)}/generate-proposals?use_ai=${useAi ? 'true' : 'false'}`,
      { method: 'POST' }
    ),
  stdCreateProposal: (
    boardId: string,
    payload: { cluster_title: string; category_tag: string; summary: string; options: Array<{ label: string; title: string; content_md: string }> }
  ) =>
    reqJson<StdProposal>(`/api/std/boards/${encodeURIComponent(boardId)}/proposals`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stdCastVote: (proposalId: string, optionId: string, comment = '') =>
    reqJson<{ ok: boolean; proposal: StdProposal }>(`/api/std/proposals/${encodeURIComponent(proposalId)}/vote`, {
      method: 'POST',
      body: JSON.stringify({ option_id: optionId, comment }),
    }),
  stdUpdateProposal: (proposalId: string, payload: { status?: 'open' | 'closed' | 'adopted'; winning_option_id?: string }) =>
    reqJson<StdProposal>(`/api/std/proposals/${encodeURIComponent(proposalId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  stdDeleteProposal: (proposalId: string) =>
    reqJson<{ ok: boolean }>(`/api/std/proposals/${encodeURIComponent(proposalId)}`, { method: 'DELETE' }),
  stdAddComment: (
    boardId: string,
    payload: { content: string; proposal_id?: string; submission_id?: string; kind?: 'improvement' | 'question' | 'decision' }
  ) =>
    reqJson<StdComment>(`/api/std/boards/${encodeURIComponent(boardId)}/comments`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stdPublishToQa: (
    pubId: string,
    payload: { notebook_id?: string; replace_doc_id?: string; title?: string; category?: string; priority?: number }
  ) =>
    reqJson<{ ok: boolean; document: DocumentItem }>(`/api/std/publications/${encodeURIComponent(pubId)}/publish-to-qa`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
