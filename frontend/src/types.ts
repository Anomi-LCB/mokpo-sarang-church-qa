export type AnswerMode = 'auto' | 'practical' | 'strict' | 'advisory';

export interface AuthState {
  authenticated: boolean;
  role?: 'member' | 'admin';
  label?: string;
  owner_id?: string;
  can_create_group?: boolean;
  is_default_pin?: boolean;
  default_double_verify?: boolean;
}

export interface Notebook {
  id: string;
  name: string;
  description: string;
  system_rules: string;
  doc_count: number;
  form_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentItem {
  id: string;
  notebook_id: string;
  title: string;
  original_filename: string;
  file_type: string;
  category: string;
  priority: number;
  page_count: number;
  ocr_pages: number;
  total_chars: number;
  chunk_count: number;
  form_count: number;
  is_pinned_default?: number;
  tags?: string[];
  status: string;
  error_msg: string;
  created_at: string;
}

export interface Citation {
  chunk_id: number;
  doc_id: string;
  doc_title: string;
  doc_category: string;
  heading: string;
  section_path: string;
  page_start: number;
  page_end: number;
  excerpt: string;
  score: number;
}

export interface VerificationResult {
  status: 'verified' | 'partial' | 'unverified' | 'no_evidence';
  verified_count: number;
  unverified_refs?: string[];
  checked_refs?: string[];
  summary: string;
  double_verified?: boolean;
}

export interface FormItem {
  id: string;
  doc_id: string;
  doc_title: string;
  title: string;
  category: string;
  form_type: 'form' | 'table';
  page_start: number;
  page_end: number;
  has_table?: number;
  sample_text?: string;
  fields: string[];
}

export interface ChatSession {
  id: string;
  notebook_id: string;
  user_label: string;
  owner_id?: string;
  is_shared?: number | boolean;
  group_id?: string;
  group_name?: string;
  title: string;
  message_count?: number;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  mode: AnswerMode | 'instant';
  citations: Citation[];
  forms: FormItem[];
  verification?: VerificationResult;
  provider?: string;
  author_label?: string;
  author_owner_id?: string;
  hasEvidence?: boolean;
  streaming?: boolean;
  statusText?: string;
}

export type AiConnectionMode = 'auto' | 'cli' | 'api';

export interface CliProviderInfo {
  id: string;
  name: string;
  available: boolean;
  binary_path: string;
  description: string;
}

export interface ApiProviderInfo {
  id: string;
  name: string;
  description: string;
  default_base_url: string;
  default_model: string;
  presets: string[];
  requires_key: boolean;
  has_key: boolean;
  key_source: 'saved' | 'env' | 'none';
  key_masked: string;
  configured: boolean;
  is_selected: boolean;
}

export interface CliSettings {
  connection_mode: AiConnectionMode;
  provider: string;
  model: string;
  api_provider: string;
  api_model: string;
  api_base_url: string;
  active_engine_summary: string;
  max_concurrent: number;
  custom_public_url: string;
  cli_failover_enabled: boolean;
  default_double_verify: boolean;
  default_chat_shared: boolean;
  audit_log_enabled: boolean;
  is_default_pin: boolean;
  queue: { active: number; queued: number; max_concurrent: number };
  providers: CliProviderInfo[];
  api_providers: ApiProviderInfo[];
}

export interface AiTestResult {
  ok: boolean;
  mode: string;
  provider: string;
  model: string;
  latency_ms: number;
  reply_preview: string;
  message: string;
}

export interface UpdateAssetInfo {
  name: string;
  url: string;
  sha256: string;
  size_bytes: number;
}

export interface UpdateManifest {
  version: string;
  published_at: string;
  title: string;
  highlights: string[];
  notes_md: string;
  release_url: string;
  assets: {
    win_patch_zip?: UpdateAssetInfo | null;
    win_installer_exe?: UpdateAssetInfo | null;
    android_apk?: UpdateAssetInfo | null;
  };
}

export interface UpdateProgress {
  status: 'idle' | 'checking' | 'downloading' | 'verifying' | 'ready' | 'applying' | 'error';
  progress_pct: number;
  downloaded_bytes: number;
  total_bytes: number;
  target_version: string;
  staged_ready: boolean;
  staged_file_count: number;
  message: string;
  error: string;
}

export interface UpdateSettings {
  channel: 'github' | 'custom';
  github_repo: string;
  custom_url: string;
  auto_check: boolean;
  skipped_version: string;
}

export interface UpdateCheckResponse {
  ok: boolean;
  offline: boolean;
  error: string;
  current_version: string;
  install_mode: 'frozen_installed' | 'frozen_portable' | 'source';
  update_available: boolean;
  should_notify: boolean;
  is_skipped: boolean;
  last_checked_at: string;
  settings: UpdateSettings;
  latest: UpdateManifest | null;
  progress: UpdateProgress;
}

export interface AuditLogItem {
  id: number;
  event_type: string;
  actor_role: string;
  actor_label: string;
  client_ip: string;
  detail: string;
  created_at: string;
}

export interface BackupItem {
  name: string;
  size_bytes: number;
  created_at: string;
}

export interface NetworkSummary {
  port: number;
  local_url: string;
  lan_url: string;
  lan_qr: string;
  tailscale: {
    installed: boolean;
    ip: string;
    dns_name: string;
    funnel_active: boolean;
    funnel_url: string;
    suggested_funnel_url: string;
  };
  tailscale_url: string;
  cloudflare: {
    installed: boolean;
    active: boolean;
    url: string;
  };
  custom_public_url: string;
  primary_external_url: string;
  primary_external_qr: string;
  apk_available: boolean;
  apk_url: string;
  apk_qr: string;
  apk_connect_url?: string;
  apk_connect_qr?: string;
}

export interface StructuredFormDraft {
  document_title: string;
  fields: Array<{ label: string; value: string }>;
  body_paragraphs: string[];
  date_line: string;
  signer_line: string;
  recipient_line: string;
}

export type FeedbackCategory = 'bug' | 'ux' | 'feature' | 'doc';
export type FeedbackStatus = 'open' | 'reviewing' | 'resolved';

export interface FeedbackItem {
  id: number;
  category: FeedbackCategory;
  title: string;
  description: string;
  reporter_label: string;
  reporter_role: string;
  client_ip: string;
  device_info: string;
  app_version: string;
  context_info: string;
  status: FeedbackStatus;
  creator_note: string;
  relayed_remote: number;
  created_at: string;
  updated_at: string;
}

export interface FeedbackInboxResponse {
  items: FeedbackItem[];
  open_count: number;
  has_custom_creator_pin: boolean;
  creator_relay_token: string;
  creator_relay_url: string;
  creator_relay_token_out: string;
}

export type StdBoardStatus = 'collecting' | 'voting' | 'published';

export interface StdBoard {
  id: string;
  title: string;
  category: string;
  work_type: string;
  description: string;
  guidelines: string;
  status: StdBoardStatus;
  deadline: string;
  vote_visibility: 'named' | 'anonymous';
  submission_anonymous: number;
  allow_vote_change: number;
  auto_route_enabled: number;
  group_id?: string;
  group_name?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  submission_count: number;
  proposal_count: number;
  publication_count: number;
  pending_memory_count: number;
}

export interface StdSubmission {
  id: string;
  board_id: string;
  title: string;
  notes: string;
  author_label: string;
  owner_id: string;
  is_anonymous: number;
  file_name: string;
  file_type: string;
  stored_path: string;
  extracted_text: string;
  char_len: number;
  ai_summary: string;
  ai_tags: string[];
  ai_cluster_key: string;
  source_origin: 'direct' | 'moved' | 'copied' | 'merged';
  origin_submission_id: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface StdCrossMemory {
  id: string;
  submission_id: string;
  source_board_id: string;
  target_board_id: string;
  suggested_category: string;
  action_type: 'move' | 'copy' | 'merge' | 'deferred';
  confidence: number;
  reason: string;
  status: 'pending' | 'applied' | 'auto_applied' | 'dismissed' | 'reverted';
  applied_submission_id: string;
  submission_title: string;
  submission_file_name: string;
  submission_summary: string;
  source_board_title: string;
  source_board_category: string;
  target_board_title: string;
  created_at: string;
  updated_at: string;
}

export interface StdProposalOption {
  id: string;
  proposal_id: string;
  label: string;
  title: string;
  content_md: string;
  source_submission_ids: string[];
  is_ai_improved: number;
  vote_count: number;
  vote_pct: number;
  voters: Array<{ voter_label: string; comment: string; updated_at: string }>;
}

export interface StdProposal {
  id: string;
  board_id: string;
  cluster_title: string;
  category_tag: string;
  summary: string;
  status: 'open' | 'closed' | 'adopted';
  winning_option_id: string;
  total_votes: number;
  my_vote_option_id: string;
  options: StdProposalOption[];
  created_at: string;
  updated_at: string;
}

export interface StdComment {
  id: number;
  board_id: string;
  proposal_id: string;
  submission_id: string;
  author_label: string;
  owner_id: string;
  content: string;
  kind: 'improvement' | 'question' | 'decision';
  created_at: string;
}

export interface StdPublication {
  id: string;
  board_id: string;
  version_label: string;
  title: string;
  pdf_path: string;
  docx_path: string;
  committee_report: {
    ai_engine?: string;
    pdf_engine?: string;
    approval_preset_name?: string;
    approval_slots?: string[];
    submission_count?: number;
    proposal_count?: number;
    comment_count?: number;
    chapter_count?: number;
    form_count?: number;
    pdf_bytes?: number;
  };
  law_audit: Array<{ source: string; status: string; note: string }>;
  published_doc_id: string;
  created_by: string;
  created_at: string;
}

export interface StdBoardDetail {
  board: StdBoard;
  submissions: StdSubmission[];
  proposals: StdProposal[];
  comments: StdComment[];
  memories: StdCrossMemory[];
  publications: StdPublication[];
}

export interface StdCategoryItem {
  name: string;
  keywords: string[];
  approval_preset_id: string;
}

export interface StdApprovalPreset {
  id: string;
  name: string;
  slots: string[];
  basis: string;
}

export interface StdPdfTemplate {
  denomination_header: string;
  church_name: string;
  committee_label: string;
  footer_left: string;
  footer_right: string;
  default_recipient: string;
  default_submit_statement: string;
  accent_color: string;
  default_approval_preset_id: string;
  show_cover_approval_box: boolean;
  show_delegation_footnote: boolean;
  delegation_footnote: string;
}

export interface StdConfig {
  categories: StdCategoryItem[];
  work_types: string[];
  approval_presets: StdApprovalPreset[];
  pdf_template: StdPdfTemplate;
}

export interface CollabGroupMember {
  owner_id: string;
  member_label: string;
  role: 'leader' | 'member';
  joined_at: string;
}

export interface CollabGroup {
  id: string;
  name: string;
  description: string;
  invite_code: string;
  created_by_owner_id: string;
  created_by_label: string;
  created_at: string;
  updated_at: string;
  member_count: number;
  members: CollabGroupMember[];
  is_member?: boolean;
  my_role?: string;
}

export interface MemberDirectoryItem {
  owner_id: string;
  label: string;
  role: 'admin' | 'member';
  can_create_group: boolean | number;
  has_recovery_code?: number;
  group_count?: number;
  last_seen_at: string;
}

export interface GroupsResponse {
  groups: CollabGroup[];
  can_create_group: boolean;
  has_recovery_code: boolean;
  members_directory: MemberDirectoryItem[];
}

export interface QuickSearchResult {
  documents: DocumentItem[];
  forms: FormItem[];
  sessions: ChatSession[];
  boards: StdBoard[];
}
