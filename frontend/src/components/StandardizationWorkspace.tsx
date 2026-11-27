import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRightLeft,
  BookCheck,
  Calendar,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Columns2,
  Copy,
  Download,
  Eye,
  FileCheck2,
  FileDiff,
  FileEdit,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  FolderKanban,
  GitMerge,
  Image as ImageIcon,
  Layers,
  Loader2,
  MessageSquarePlus,
  Pencil,
  Plus,
  Presentation,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Stamp,
  Trash2,
  Upload,
  Users,
  Vote,
  X,
} from 'lucide-react';
import { api, authHeaders, safeAssetUrl, triggerTicketDownload } from '../api';
import type {
  CollabGroup,
  DocumentItem,
  StdBoard,
  StdBoardDetail,
  StdBoardStatus,
  StdConfig,
  StdCrossMemory,
  StdDiffReport,
  StdManuscriptDraft,
  StdProposal,
  StdPublication,
  StdSubmission,
} from '../types';
import { MarkdownView } from './MarkdownView';
import { StdConfigModal } from './StdConfigModal';
import { StdDiffModal, StdManuscriptEditorModal } from './StdManuscriptEditorModal';
import { StdProposalCompareModal } from './StdProposalCompareModal';

const STD_ACCEPT_ATTR =
  '.pdf,.docx,.hwpx,.xlsx,.pptx,.txt,.md,.png,.jpg,.jpeg,.webp,.bmp,.gif,.tif,.tiff';
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tif', 'tiff']);

function isImageSubmission(s: StdSubmission): boolean {
  return Boolean(s.meta?.is_image) || IMAGE_EXTS.has((s.file_type || '').toLowerCase());
}

function formatFileSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function computeDeadlineInfo(deadline?: string): { label: string; expired: boolean; urgent: boolean } | null {
  const raw = (deadline || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const [y, m, d] = raw.split('-').map(Number);
  const target = new Date(y, m - 1, d).getTime();
  const diffDays = Math.round((target - today) / 86_400_000);
  if (diffDays < 0) return { label: `마감됨 (${raw})`, expired: true, urgent: false };
  if (diffDays === 0) return { label: '오늘 마감 (D-Day)', expired: false, urgent: true };
  if (diffDays <= 3) return { label: `마감 D-${diffDays}`, expired: false, urgent: true };
  return { label: `마감 D-${diffDays} (${raw})`, expired: false, urgent: false };
}

interface Props {
  isAdmin: boolean;
  currentOwnerId: string;
  qaDocuments: DocumentItem[];
  activeNotebookId: string;
  groups?: CollabGroup[];
  refreshTick?: number;
  initialBoardId?: string;
  onOpenGroups?: () => void;
  onQaDocumentsUpdated: () => void;
}

const DEFAULT_CATEGORY_NAMES = [
  '예배선교부',
  '교육선교부',
  '목양사역선교부',
  '장학선교부',
  '세계선교부',
  '사회봉사부',
  '재단관리부',
  '차량관리부',
  '주방관리부',
  '재정부',
  '당회·제직회·공동의회',
  '교역자·유급직원·인사',
];

const DEFAULT_WORK_TYPE_NAMES = [
  '규정·서식 표준화',
  '시행세칙 개정안',
  '부서 업무 매뉴얼',
  '결재·공문 양식 통일',
  '위임전결·절차 점검표',
];

const STATUS_META: Record<StdBoardStatus, { label: string; dot: string; pill: string }> = {
  collecting: { label: '수집 중', dot: 'bg-[#0f4c81]', pill: 'bg-[#0f4c81]/10 text-[#0f4c81]' },
  voting: { label: '투표·개선', dot: 'bg-amber-500', pill: 'bg-amber-50 text-amber-800' },
  published: { label: '편찬 완료', dot: 'bg-emerald-600', pill: 'bg-emerald-50 text-emerald-800' },
};

type SubTab = 'submissions' | 'voting' | 'memory' | 'publish';

export const StandardizationWorkspace: React.FC<Props> = ({
  isAdmin,
  currentOwnerId,
  qaDocuments,
  activeNotebookId,
  groups = [],
  refreshTick = 0,
  initialBoardId = '',
  onOpenGroups,
  onQaDocumentsUpdated,
}) => {
  const [boards, setBoards] = useState<StdBoard[]>([]);
  const [groupFilter, setGroupFilter] = useState<string>('all');
  const [activeBoardId, setActiveBoardId] = useState<string>('');
  const [detail, setDetail] = useState<StdBoardDetail | null>(null);
  const [globalMemories, setGlobalMemories] = useState<StdCrossMemory[]>([]);
  const [showGlobalMemoryView, setShowGlobalMemoryView] = useState(false);
  const [subTab, setSubTab] = useState<SubTab>('submissions');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  // Church Taxonomy / Approval Line / PDF Cover Configuration
  const [stdConfig, setStdConfig] = useState<StdConfig | null>(null);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [compileApprovalPresetId, setCompileApprovalPresetId] = useState('');
  const [compileCustomSlots, setCompileCustomSlots] = useState('');

  const leaderGroups = useMemo(
    () => (isAdmin ? groups : groups.filter((g) => g.my_role === 'leader')),
    [groups, isAdmin]
  );
  const canCreateBoard = isAdmin || leaderGroups.length > 0;

  // Create Board Modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newCat, setNewCat] = useState('재정부');
  const [newWorkType, setNewWorkType] = useState('규정·서식 표준화');
  const [newGroupId, setNewGroupId] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newGuide, setNewGuide] = useState('');
  const [newDeadline, setNewDeadline] = useState('');
  const [newQuorumTarget, setNewQuorumTarget] = useState<number>(0);
  const [newVoteVis, setNewVoteVis] = useState<'named' | 'anonymous'>('named');
  const [newSubAnon, setNewSubAnon] = useState(false);
  const [newAllowChange, setNewAllowChange] = useState(true);
  const [newAutoRoute, setNewAutoRoute] = useState(false);

  // Multi-file Drag & Drop Submission composer
  const fileRef = useRef<HTMLInputElement>(null);
  const [subTitle, setSubTitle] = useState('');
  const [subNotes, setSubNotes] = useState('');
  const [subFiles, setSubFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [uploadProgressText, setUploadProgressText] = useState('');
  const [selectedSubIds, setSelectedSubIds] = useState<string[]>([]);
  const [batchTargetBoardId, setBatchTargetBoardId] = useState('');
  const [batchMergedTitle, setBatchMergedTitle] = useState('');
  const [expandedSubId, setExpandedSubId] = useState('');
  const [lightboxSub, setLightboxSub] = useState<StdSubmission | null>(null);
  const [editingSubId, setEditingSubId] = useState('');
  const [editSubTitle, setEditSubTitle] = useState('');
  const [editSubNotes, setEditSubNotes] = useState('');
  const [editSubCluster, setEditSubCluster] = useState('');

  // Voting, Compare, Option Inline Polish & Comments
  const [commentText, setCommentText] = useState('');
  const [commentKind, setCommentKind] = useState<'improvement' | 'question' | 'decision'>('improvement');
  const [showManualProposal, setShowManualProposal] = useState(false);
  const [propTitle, setPropTitle] = useState('');
  const [propOptA, setPropOptA] = useState('');
  const [propOptB, setPropOptB] = useState('');
  const [voteComments, setVoteComments] = useState<Record<string, string>>({});
  const [expandedVotersOptId, setExpandedVotersOptId] = useState('');
  const [compareProposal, setCompareProposal] = useState<StdProposal | null>(null);
  const [editingOptionId, setEditingOptionId] = useState('');
  const [editOptTitle, setEditOptTitle] = useState('');
  const [editOptContent, setEditOptContent] = useState('');

  // Cross-memory manual target override for deferred items
  const [memTargetOverrides, setMemTargetOverrides] = useState<Record<string, string>>({});

  // Expert Committee Compilation (1-Click + 2-Stage Draft Editor + Revision Diff + Forms Vault Sync)
  const [compileVersion, setCompileVersion] = useState('');
  const [compileDirectives, setCompileDirectives] = useState('');
  const [compileIncludeImages, setCompileIncludeImages] = useState(true);
  const [compileStages, setCompileStages] = useState<Array<{ stage: number; role: string; message: string }>>([]);
  const [compiling, setCompiling] = useState(false);
  const [finalizingDraft, setFinalizingDraft] = useState(false);
  const [draftSession, setDraftSession] = useState<{
    version_label: string;
    manuscript: StdManuscriptDraft;
    law_audit: Array<{ source: string; status: string; note: string }>;
    vote_summary: Array<Record<string, unknown>>;
    ai_engine: string;
  } | null>(null);
  const [diffModalState, setDiffModalState] = useState<{ title: string; diff: StdDiffReport } | null>(null);
  const [previewPub, setPreviewPub] = useState<StdPublication | null>(null);
  const [publishReplaceMap, setPublishReplaceMap] = useState<Record<string, string>>({});

  // Group leader can fully manage their own group's boards (Pass-1 fix!)
  const canManageBoard = useMemo(() => {
    if (isAdmin) return true;
    if (!detail) return false;
    if (detail.can_manage || detail.board.can_manage) return true;
    return Boolean(detail.board.group_id && leaderGroups.some((g) => g.id === detail.board.group_id));
  }, [isAdmin, detail, leaderGroups]);

  const deadlineInfo = useMemo(() => computeDeadlineInfo(detail?.board.deadline), [detail?.board.deadline]);

  const boardMetrics = useMemo(() => {
    if (!detail) return { participants: 0, maxVotes: 0, imageCount: 0 };
    const people = new Set<string>();
    detail.submissions.forEach((s) => people.add(s.owner_id || s.author_label));
    detail.comments.forEach((c) => people.add(c.owner_id || c.author_label));
    let maxVotes = 0;
    detail.proposals.forEach((p) => {
      if (p.total_votes > maxVotes) maxVotes = p.total_votes;
    });
    const imageCount = detail.submissions.filter(isImageSubmission).length;
    return { participants: Math.max(people.size, maxVotes), maxVotes, imageCount };
  }, [detail]);

  const flashNotice = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(''), 4200);
  };

  const loadBoards = useCallback(async (selectId?: string) => {
    setLoading(true);
    try {
      const [list, mems, cfg] = await Promise.all([
        api.stdListBoards(),
        api.stdListCrossMemories('', 'pending'),
        api.stdGetConfig().catch(() => null),
      ]);
      if (cfg) {
        setStdConfig(cfg);
      }
      setBoards(list);
      setGlobalMemories(mems);
      const target =
        selectId && list.some((b) => b.id === selectId)
          ? selectId
          : list.some((b) => b.id === activeBoardId)
            ? activeBoardId
            : list[0]?.id || '';
      setActiveBoardId(target);
      if (target) {
        const d = await api.stdGetBoard(target);
        setDetail(d);
      } else {
        setDetail(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '표준화실 데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, [activeBoardId]);

  const refreshActiveBoard = useCallback(async (bid = activeBoardId) => {
    if (!bid) return;
    try {
      const [d, list, mems] = await Promise.all([
        api.stdGetBoard(bid),
        api.stdListBoards(),
        api.stdListCrossMemories('', 'pending'),
      ]);
      setDetail(d);
      setBoards(list);
      setGlobalMemories(mems);
    } catch {
      // ignore
    }
  }, [activeBoardId]);

  useEffect(() => {
    void loadBoards(initialBoardId || undefined);
  }, []);

  useEffect(() => {
    if (initialBoardId && boards.some((b) => b.id === initialBoardId)) {
      void handleSelectBoard(initialBoardId);
    }
  }, [initialBoardId]);

  useEffect(() => {
    if (refreshTick > 0) {
      if (activeBoardId) {
        void refreshActiveBoard(activeBoardId);
      } else {
        void loadBoards();
      }
    }
  }, [refreshTick]);

  const filteredBoards = useMemo(() => {
    if (groupFilter === 'all') return boards;
    if (groupFilter === 'public') return boards.filter((b) => !b.group_id);
    return boards.filter((b) => b.group_id === groupFilter);
  }, [boards, groupFilter]);

  const openCreateBoardModal = () => {
    if (!isAdmin && leaderGroups.length > 0 && !newGroupId) {
      setNewGroupId(leaderGroups[0].id);
    }
    setShowCreateModal(true);
  };

  const handleSelectBoard = async (bid: string) => {
    setShowGlobalMemoryView(false);
    setActiveBoardId(bid);
    setSelectedSubIds([]);
    setError('');
    try {
      const d = await api.stdGetBoard(bid);
      setDetail(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : '게시글을 불러오지 못했습니다.');
    }
  };

  const handleCreateBoard = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newTitle.trim().length < 2 || busy) return;
    setBusy(true);
    setError('');
    try {
      const created = await api.stdCreateBoard({
        title: newTitle.trim(),
        category: newCat.trim() || '일반 행정',
        work_type: newWorkType.trim() || '규정·서식 표준화',
        group_id: isAdmin ? newGroupId : newGroupId || leaderGroups[0]?.id || '',
        description: newDesc.trim(),
        guidelines: newGuide.trim(),
        deadline: newDeadline.trim(),
        quorum_target: Math.max(0, Number(newQuorumTarget) || 0),
        vote_visibility: newVoteVis,
        submission_anonymous: newSubAnon,
        allow_vote_change: newAllowChange,
        auto_route_enabled: newAutoRoute,
      });
      setShowCreateModal(false);
      setNewTitle('');
      setNewDesc('');
      setNewGuide('');
      setNewDeadline('');
      setNewQuorumTarget(0);
      await loadBoards(created.id);
      const wakeCount = created.matched_memories?.length || 0;
      flashNotice(
        wakeCount > 0
          ? `새 게시글이 개설되었으며, AI가 기억해 둔 연관 파일 ${wakeCount}건을 자동으로 찾아냈습니다.`
          : `새 행정 표준화 모집 게시글 "${created.title}"이 개설되었습니다.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '게시글 생성 실패');
    } finally {
      setBusy(false);
    }
  };

  const addQueuedFiles = (incoming: FileList | File[]) => {
    const arr = Array.from(incoming || []);
    if (arr.length === 0) return;
    setSubFiles((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
      const next = [...prev];
      for (const f of arr) {
        const key = `${f.name}:${f.size}`;
        if (!seen.has(key)) {
          seen.add(key);
          next.push(f);
        }
      }
      return next.slice(0, 12);
    });
  };

  const handleSubmitFile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeBoardId || (subFiles.length === 0 && !subTitle.trim() && !subNotes.trim()) || busy) return;
    setBusy(true);
    setError('');
    setUploadProgressText('');
    try {
      const filesToSend: Array<File | null> = subFiles.length > 0 ? subFiles : [null];
      let totalMem = 0;
      let totalAuto = 0;
      const duplicateNotes: string[] = [];

      for (let idx = 0; idx < filesToSend.length; idx++) {
        const f = filesToSend[idx];
        const perTitle =
          filesToSend.length === 1
            ? subTitle.trim()
            : subTitle.trim()
              ? `${subTitle.trim()} (${idx + 1})`
              : '';
        setUploadProgressText(
          f
            ? `${idx + 1} / ${filesToSend.length} 처리 중: ${f.name} (내용 추출 · AI 분석 중...)`
            : '현장 의견 등록 및 AI 분석 중...'
        );
        const res = await api.stdSubmit(activeBoardId, {
          title: perTitle,
          notes: subNotes.trim(),
          file: f,
          use_ai: true,
        });
        totalMem += res.analysis?.memories?.length || 0;
        totalAuto += res.analysis?.auto_applied_count || 0;
        if (res.duplicate_of) {
          duplicateNotes.push(`${f?.name || res.submission.title} (기존 '${res.duplicate_of.title}'와 동일)`);
        }
      }

      setSubTitle('');
      setSubNotes('');
      setSubFiles([]);
      setUploadProgressText('');
      if (fileRef.current) fileRef.current.value = '';
      await refreshActiveBoard();

      const dupMsg = duplicateNotes.length > 0 ? ` · 참고: 중복 파일 ${duplicateNotes.length}건 감지` : '';
      flashNotice(
        totalAuto > 0
          ? `${filesToSend.length}건 제출 완료 · AI가 고신뢰도 교차 분류 ${totalAuto}건을 자동 배치했습니다(되돌리기 가능)${dupMsg}`
          : totalMem > 0
            ? `${filesToSend.length}건 제출 완료 · AI가 타 분류 추천 ${totalMem}건을 교차 기억함에 기록했습니다${dupMsg}`
            : `${filesToSend.length}건의 행정 자료 제출 및 AI 요약·분류 분석이 완료되었습니다${dupMsg}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '제출 처리 오류');
    } finally {
      setUploadProgressText('');
      setBusy(false);
    }
  };

  const handleSaveSubmissionEdit = async (subId: string, reanalyze = false) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.stdUpdateSubmission(subId, {
        title: editSubTitle.trim() || undefined,
        notes: editSubNotes,
        ai_cluster_key: editSubCluster.trim(),
        reanalyze,
      });
      setEditingSubId('');
      await refreshActiveBoard();
      flashNotice(reanalyze ? '자료 수정 및 AI 재분석이 완료되었습니다.' : '제출 자료 정보가 수정되었습니다.');
    } catch (err) {
      setError(err instanceof Error ? err.message : '제출 자료 수정 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleReanalyzeSubmission = async (sub: StdSubmission) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.stdUpdateSubmission(sub.id, { reanalyze: true, use_ai: true });
      await refreshActiveBoard();
      flashNotice(`"${sub.title}" 자료의 AI 요약·분류 재분석이 완료되었습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 재분석 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleApplyMemory = async (
    mem: StdCrossMemory,
    action: 'move' | 'copy' | 'merge' | 'dismiss' | 'revert'
  ) => {
    const targetId = memTargetOverrides[mem.id] || mem.target_board_id || activeBoardId;
    if (action !== 'dismiss' && action !== 'revert' && !targetId) {
      setError('대상 모집 게시글을 먼저 선택해 주세요.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api.stdApplyMemory(mem.id, { action, target_board_id: targetId });
      await refreshActiveBoard();
      const labels: Record<string, string> = {
        move: '다른 분류로 이동 완료',
        copy: '병행 복사 완료',
        merge: '통합 병합 완료',
        dismiss: '제안 보류 처리됨',
        revert: '작업이 원래대로 되돌려졌습니다',
      };
      flashNotice(labels[action] || '처리 완료');
    } catch (err) {
      setError(err instanceof Error ? err.message : '교차 정리 실행 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleBatchAction = async (action: 'move' | 'copy' | 'merge') => {
    if (selectedSubIds.length === 0 || !batchTargetBoardId || busy) return;
    setBusy(true);
    setError('');
    try {
      await api.stdBatchAction({
        action,
        submission_ids: selectedSubIds,
        target_board_id: batchTargetBoardId,
        merged_title: batchMergedTitle.trim(),
      });
      setSelectedSubIds([]);
      setBatchMergedTitle('');
      await refreshActiveBoard();
      flashNotice(
        action === 'move'
          ? '선택 자료를 대상 게시글로 이동했습니다.'
          : action === 'copy'
            ? '선택 자료를 대상 게시글에 병행 복사했습니다.'
            : '선택 자료를 대상 게시글에 통합 병합했습니다.'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '일괄 작업 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleGenerateProposals = async () => {
    if (!activeBoardId || busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.stdGenerateProposals(activeBoardId, true);
      await refreshActiveBoard();
      setSubTab('voting');
      flashNotice(
        res.count > 0
          ? `유사 규격 ${res.count}개 안건과 AI 통합 개선안이 자동 생성되었습니다.`
          : '새로 묶을 미등록 규격이 없거나 제출 자료가 부족합니다.'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '투표 안건 생성 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleCreateManualProposal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeBoardId || !propTitle.trim() || !propOptA.trim() || busy) return;
    setBusy(true);
    try {
      const opts = [{ label: 'A안', title: propOptA.trim(), content_md: propOptA.trim() }];
      if (propOptB.trim()) opts.push({ label: 'B안', title: propOptB.trim(), content_md: propOptB.trim() });
      await api.stdCreateProposal(activeBoardId, {
        cluster_title: propTitle.trim(),
        category_tag: detail?.board.category || '공통 규격',
        summary: '관리자가 직접 개설한 표준 규격 투표 안건입니다.',
        options: opts,
      });
      setPropTitle('');
      setPropOptA('');
      setPropOptB('');
      setShowManualProposal(false);
      await refreshActiveBoard();
      flashNotice('새 투표 안건이 등록되었습니다.');
    } catch (err) {
      setError(err instanceof Error ? err.message : '안건 등록 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleVote = async (proposalId: string, optionId: string) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const comment = (voteComments[proposalId] || '').trim();
      await api.stdCastVote(proposalId, optionId, comment);
      if (comment) {
        setVoteComments((prev) => ({ ...prev, [proposalId]: '' }));
      }
      await refreshActiveBoard();
      flashNotice('투표가 반영되었습니다.');
    } catch (err) {
      setError(err instanceof Error ? err.message : '투표 처리 오류');
    } finally {
      setBusy(false);
    }
  };

  const handleSaveOptionEdit = async (optionId: string) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.stdUpdateProposalOption(optionId, {
        title: editOptTitle.trim() || undefined,
        content_md: editOptContent,
      });
      setEditingOptionId('');
      await refreshActiveBoard();
      flashNotice('후보안 문구가 저장되었습니다.');
    } catch (err) {
      setError(err instanceof Error ? err.message : '후보안 문구 수정 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeBoardId || commentText.trim().length < 2 || busy) return;
    setBusy(true);
    try {
      await api.stdAddComment(activeBoardId, { content: commentText.trim(), kind: commentKind });
      setCommentText('');
      await refreshActiveBoard();
    } catch (err) {
      setError(err instanceof Error ? err.message : '의견 등록 실패');
    } finally {
      setBusy(false);
    }
  };

  const _buildCompilePayload = () => {
    const customSlotsArr =
      compileApprovalPresetId === '__custom__'
        ? compileCustomSlots
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : undefined;
    return {
      version_label: compileVersion.trim(),
      custom_directives: compileDirectives.trim(),
      approval_preset_id:
        compileApprovalPresetId && compileApprovalPresetId !== '__custom__' ? compileApprovalPresetId : '',
      custom_approval_slots: customSlotsArr,
      include_images: compileIncludeImages,
    };
  };

  const handleCompilePdf = async (mode: 'direct' | 'draft' = 'direct') => {
    if (!activeBoardId || compiling) return;
    setCompiling(true);
    setCompileStages([]);
    setError('');
    try {
      const endpoint =
        mode === 'draft'
          ? `/api/std/boards/${encodeURIComponent(activeBoardId)}/compile/draft-stream`
          : `/api/std/boards/${encodeURIComponent(activeBoardId)}/compile/stream`;
      const res = await fetch(endpoint, {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(_buildCompilePayload()),
      });
      if (!res.ok || !res.body) throw new Error(`편찬 요청 오류 (${res.status})`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let ev = 'message';
          let dataStr = '';
          for (const ln of block.split('\n')) {
            if (ln.startsWith('event:')) ev = ln.slice(6).trim();
            else if (ln.startsWith('data:')) dataStr += ln.slice(5).trim();
          }
          if (!dataStr) continue;
          let payload: Record<string, any>;
          try {
            payload = JSON.parse(dataStr);
          } catch {
            continue;
          }
          if (ev === 'stage') {
            setCompileStages((prev) => [...prev, payload as { stage: number; role: string; message: string }]);
          } else if (ev === 'draft') {
            setDraftSession({
              version_label: payload.version_label || compileVersion.trim() || 'v1.0',
              manuscript: payload.manuscript,
              law_audit: payload.law_audit || [],
              vote_summary: payload.vote_summary || [],
              ai_engine: payload.ai_engine || 'edited-manuscript',
            });
            flashNotice('원고 초안과 v4.0 법규 감사가 준비되었습니다. 검토·수정 후 최종 조판해 주세요.');
          } else if (ev === 'done') {
            setCompileVersion('');
            await refreshActiveBoard();
            if (payload.publication) setPreviewPub(payload.publication);
            flashNotice('4역할 전문가 위원회 정규 PDF · Word · 한글(HWPX) 3종 편찬이 완료되었습니다!');
          } else if (ev === 'error') {
            setError(payload.message || '편찬 오류');
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF 편찬 실패');
    } finally {
      setCompiling(false);
    }
  };

  const handleFinalizeEditedDraft = async (edited: StdManuscriptDraft, version: string) => {
    if (!activeBoardId || !draftSession || finalizingDraft) return;
    setFinalizingDraft(true);
    setError('');
    try {
      const cfg = _buildCompilePayload();
      const res = await api.stdFinalizeManuscript(activeBoardId, {
        version_label: version.trim() || draftSession.version_label,
        manuscript: edited,
        law_audit: draftSession.law_audit,
        vote_summary: draftSession.vote_summary,
        approval_preset_id: cfg.approval_preset_id,
        custom_approval_slots: cfg.custom_approval_slots,
        ai_engine: `${draftSession.ai_engine}+edited`,
        include_images: compileIncludeImages,
      });
      setDraftSession(null);
      setCompileVersion('');
      await refreshActiveBoard();
      if (res.publication) setPreviewPub(res.publication);
      flashNotice('직접 편집한 원고로 PDF · Word · 한글(HWPX) 3종 조판이 완료되었습니다!');
    } catch (err) {
      setError(err instanceof Error ? err.message : '최종 조판 실패');
    } finally {
      setFinalizingDraft(false);
    }
  };

  const handleOpenDiffModal = async (pub: StdPublication) => {
    if (pub.diff_report && (pub.diff_report.rows?.length || 0) > 0) {
      setDiffModalState({ title: `${pub.title} (${pub.version_label})`, diff: pub.diff_report });
      return;
    }
    try {
      const res = await api.stdGetPublicationDiff(pub.id);
      setDiffModalState({ title: `${res.title} (${res.version_label})`, diff: res.diff_report || {} });
    } catch (err) {
      setError(err instanceof Error ? err.message : '신·구조문 대조표를 불러오지 못했습니다.');
    }
  };

  const handleRegisterFormsToVault = async (pub: StdPublication) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.stdRegisterPublicationForms(pub.id, activeNotebookId);
      onQaDocumentsUpdated();
      await refreshActiveBoard();
      flashNotice(`표준 서식 ${res.registered_count}종이 오른쪽 [서식·표 보관함]에 등록되었습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '서식 보관함 등록 실패');
    } finally {
      setBusy(false);
    }
  };

  const handlePublishToQa = async (pub: StdPublication) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const replaceId = publishReplaceMap[pub.id] || '';
      const res = await api.stdPublishToQa(pub.id, {
        notebook_id: activeNotebookId,
        replace_doc_id: replaceId,
        title: `${pub.title} (${pub.version_label})`,
      });
      onQaDocumentsUpdated();
      await refreshActiveBoard();
      flashNotice(`"${res.document.title}"이(가) [행정 Q&A] 검색 자료에 정식 편입·색인되었습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '행정 Q&A 편입 실패');
    } finally {
      setBusy(false);
    }
  };

  const pendingForCurrentBoard = useMemo(
    () => (detail?.memories || []).filter((m) => m.status === 'pending'),
    [detail]
  );

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden bg-white">
      {/* Left Rail: Boards List & Global Cross-Memory */}
      <aside className="flex w-[250px] shrink-0 flex-col border-r border-black/[0.07] bg-[#f7f7f5] max-md:hidden xl:w-[276px]">
        <div className="flex items-center justify-between gap-2 border-b border-black/[0.06] px-3.5 py-3">
          <div className="flex items-center gap-1.5">
            <FolderKanban className="h-4 w-4 text-[#0f4c81]" />
            <span className="text-xs font-semibold text-[#18181b]">행정 표준화 과제</span>
          </div>
          {canCreateBoard && (
            <div className="flex items-center gap-1">
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => setShowConfigModal(true)}
                  title="분류·부서 체계 및 교회 결재선·PDF 표지 설정"
                  aria-label="표준화실 규격 및 결재선 설정"
                  className="rounded-md p-1.5 text-[#52525b] transition hover:bg-black/[0.06] hover:text-[#18181b]"
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                type="button"
                onClick={openCreateBoardModal}
                className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#18181b] px-2 py-1 text-[11px] font-semibold text-white hover:bg-[#27272a]"
              >
                <Plus className="h-3 w-3" />
                <span>새 모집</span>
              </button>
            </div>
          )}
        </div>

        {/* Group Scope Filter Pills */}
        {(groups.length > 0 || onOpenGroups) && (
          <div className="flex flex-wrap items-center gap-1 border-b border-black/[0.06] px-2.5 py-2">
            <button
              type="button"
              onClick={() => setGroupFilter('all')}
              className={`chip-nowrap rounded-md px-2 py-0.5 text-[10.5px] font-semibold transition ${
                groupFilter === 'all' ? 'bg-[#18181b] text-white' : 'bg-white text-[#52525b] hover:bg-black/[0.05]'
              }`}
            >
              전체
            </button>
            <button
              type="button"
              onClick={() => setGroupFilter('public')}
              className={`chip-nowrap rounded-md px-2 py-0.5 text-[10.5px] font-semibold transition ${
                groupFilter === 'public' ? 'bg-[#18181b] text-white' : 'bg-white text-[#52525b] hover:bg-black/[0.05]'
              }`}
            >
              공용
            </button>
            {groups.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => setGroupFilter(g.id)}
                className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10.5px] font-semibold transition ${
                  groupFilter === g.id
                    ? 'bg-[#0f4c81] text-white'
                    : 'bg-white text-[#0f4c81] ring-1 ring-[#0f4c81]/20 hover:bg-[#0f4c81]/5'
                }`}
              >
                <Users className="h-2.5 w-2.5" />
                <span>{g.name}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 space-y-1 overflow-y-auto p-2.5">
          {loading ? (
            <div className="flex justify-center py-8 text-[#8a8a8e]">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : filteredBoards.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-[#8a8a8e]">등록된 모집 게시글이 없습니다</p>
          ) : (
            filteredBoards.map((b) => {
              const active = !showGlobalMemoryView && b.id === activeBoardId;
              const st = STATUS_META[b.status] || STATUS_META.collecting;
              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => void handleSelectBoard(b.id)}
                  className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2.5 text-left transition ${
                    active ? 'bg-white shadow-[0_1px_2px_rgba(0,0,0,0.05)]' : 'hover:bg-black/[0.04]'
                  }`}
                >
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${st.dot}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      <p className={`truncate text-[12.5px] ${active ? 'font-semibold text-[#18181b]' : 'font-medium text-[#3f3f46]'}`}>
                        {b.title}
                      </p>
                    </div>
                    <p className="mt-0.5 truncate text-[10.5px] text-[#8a8a8e]">
                      {b.group_name ? `[${b.group_name}] ` : ''}
                      {b.category} · 자료 {b.submission_count} · 안건 {b.proposal_count}
                    </p>
                  </div>
                  {b.pending_memory_count > 0 && (
                    <span className="chip-nowrap rounded-full bg-[#0f4c81]/12 px-1.5 py-0.5 text-[10px] font-bold text-[#0f4c81]">
                      {b.pending_memory_count}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>

        <div className="border-t border-black/[0.06] p-2.5">
          <button
            type="button"
            onClick={() => setShowGlobalMemoryView(true)}
            className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs font-semibold transition ${
              showGlobalMemoryView ? 'bg-[#18181b] text-white' : 'bg-white text-[#18181b] ring-1 ring-black/[0.08] hover:bg-[#ededeb]'
            }`}
          >
            <span className="inline-flex items-center gap-1.5">
              <ArrowRightLeft className="h-3.5 w-3.5" />
              <span>전체 교차 분류 기억함</span>
            </span>
            <span className={`chip-nowrap rounded-full px-1.5 py-0.5 text-[10px] ${showGlobalMemoryView ? 'bg-white/20 text-white' : 'bg-[#0f4c81]/10 text-[#0f4c81]'}`}>
              {globalMemories.length}
            </span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white">
        {/* Mobile board switcher bar — includes Cross-Memory & Settings access! */}
        <div className="flex items-center justify-between gap-1.5 border-b border-black/[0.07] bg-[#f7f7f5] px-3 py-2 md:hidden">
          <select
            value={activeBoardId}
            onChange={(e) => void handleSelectBoard(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs font-semibold"
          >
            {boards.length === 0 ? (
              <option value="">게시글 없음</option>
            ) : (
              boards.map((b) => (
                <option key={b.id} value={b.id}>
                  [{STATUS_META[b.status]?.label}] {b.title}
                </option>
              ))
            )}
          </select>
          <button
            type="button"
            onClick={() => setShowGlobalMemoryView((v) => !v)}
            title="전체 교차 분류 기억함"
            aria-label="전체 교차 분류 기억함"
            className={`chip-nowrap inline-flex items-center gap-1 rounded-lg border px-2 py-1.5 text-xs font-semibold ${
              showGlobalMemoryView
                ? 'border-[#18181b] bg-[#18181b] text-white'
                : 'border-black/[0.1] bg-white text-[#18181b]'
            }`}
          >
            <ArrowRightLeft className="h-3.5 w-3.5" />
            <span>{globalMemories.length}</span>
          </button>
          {isAdmin && (
            <button
              type="button"
              onClick={() => setShowConfigModal(true)}
              title="표준화실 규격·결재선·표지 설정"
              aria-label="표준화실 설정"
              className="rounded-lg border border-black/[0.1] bg-white p-1.5 text-[#52525b]"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </button>
          )}
          {canCreateBoard && (
            <button
              type="button"
              onClick={openCreateBoardModal}
              className="chip-nowrap rounded-lg bg-[#18181b] px-2.5 py-1.5 text-xs font-semibold text-white"
            >
              + 새 모집
            </button>
          )}
        </div>

        {(notice || error) && (
          <div className="px-4 pt-3 sm:px-6">
            {notice && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-xs font-medium text-emerald-900">
                {notice}
              </div>
            )}
            {error && (
              <div className="mt-1 rounded-lg border border-red-200 bg-red-50 px-3.5 py-2 text-xs font-medium text-red-700">
                {error}
              </div>
            )}
          </div>
        )}

        {showGlobalMemoryView ? (
          <div className="flex-1 overflow-y-auto p-5 sm:p-7">
            <div className="mx-auto max-w-4xl space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-semibold text-[#18181b]">전체 교차 분류 AI 기억함</h2>
                  <p className="mt-0.5 text-xs text-[#71717a]">
                    다른 분류로 이동·병행 복사·통합 병합이 필요하거나 향후 새 분류 개설을 위해 기억해 둔 모든 행정 파일입니다.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowGlobalMemoryView(false)}
                  className="chip-nowrap rounded-lg border border-black/[0.1] px-3 py-1.5 text-xs font-medium text-[#3f3f46]"
                >
                  게시글로 돌아가기
                </button>
              </div>
              {globalMemories.length === 0 ? (
                <div className="rounded-xl border border-dashed border-black/[0.12] p-10 text-center text-xs text-[#8a8a8e]">
                  대기 중인 교차 분류 제안이 없습니다.
                </div>
              ) : (
                <div className="space-y-2.5">
                  {globalMemories.map((m) => (
                    <div key={m.id} className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4 space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-2 py-0.5 text-[11px] font-semibold text-[#0f4c81]">
                            {m.action_type === 'move' ? '이동 추천' : m.action_type === 'copy' ? '병행 복사' : m.action_type === 'merge' ? '병합 추천' : `향후 분류 기억: ${m.suggested_category}`}
                          </span>
                          <span className="text-xs font-semibold text-[#18181b]">{m.submission_title}</span>
                          <span className="text-[11px] text-[#71717a]">신뢰도 {m.confidence}%</span>
                        </div>
                        <span className="text-[11px] text-[#8a8a8e]">
                          출처: {m.source_board_title}
                        </span>
                      </div>
                      <p className="text-xs text-[#3f3f46]">{m.reason}</p>
                      {(isAdmin || boards.some((b) => b.id === m.source_board_id && b.can_manage)) && (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <select
                            value={memTargetOverrides[m.id] || m.target_board_id || ''}
                            onChange={(e) => setMemTargetOverrides({ ...memTargetOverrides, [m.id]: e.target.value })}
                            className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1 text-xs"
                          >
                            <option value="">대상 게시글 선택...</option>
                            {boards
                              .filter((b) => b.id !== m.source_board_id)
                              .map((b) => (
                                <option key={b.id} value={b.id}>
                                  {b.title} ({b.category})
                                </option>
                              ))}
                          </select>
                          <button type="button" onClick={() => void handleApplyMemory(m, 'move')} className="chip-nowrap rounded-md bg-[#18181b] px-2.5 py-1 text-[11px] font-semibold text-white">이동</button>
                          <button type="button" onClick={() => void handleApplyMemory(m, 'copy')} className="chip-nowrap rounded-md border border-black/[0.12] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#18181b]">병행 복사</button>
                          <button type="button" onClick={() => void handleApplyMemory(m, 'merge')} className="chip-nowrap rounded-md bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold text-white">통합 병합</button>
                          <button type="button" onClick={() => void handleApplyMemory(m, 'dismiss')} className="chip-nowrap rounded-md px-2 py-1 text-[11px] text-[#71717a] hover:bg-black/[0.05]">보류</button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : !detail ? (
          <div className="flex flex-1 flex-col items-center justify-center p-8 text-center">
            <div className="max-w-md space-y-4">
              <p className="text-[11px] font-semibold tracking-[0.06em] text-[#0f4c81] uppercase">
                ADMIN STANDARDIZATION STUDIO
              </p>
              <h2 className="text-xl font-semibold tracking-tight text-[#18181b]">
                목포사랑의교회 행정 표준화실
              </h2>
              <p className="text-xs leading-relaxed text-[#71717a]">
                분류별 모집 게시글을 개설해 목사님들의 기존 행정 파일을 수합하고, AI 교차 분류 기억·투표 합의·4역할 전문가 위원회 검수를 거쳐 공식 정규 PDF를 편찬합니다.
              </p>
              {canCreateBoard && (
                <button
                  type="button"
                  onClick={openCreateBoardModal}
                  className="chip-nowrap inline-flex items-center gap-1.5 rounded-xl bg-[#18181b] px-5 py-2.5 text-xs font-semibold text-white hover:bg-[#27272a]"
                >
                  <Plus className="h-4 w-4" />
                  <span>첫 행정 표준화 모집 게시글 만들기</span>
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            {/* Board Header */}
            <div className="border-b border-black/[0.07] px-5 pt-4 pb-0 sm:px-7">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`chip-nowrap rounded-md px-2 py-0.5 text-[11px] font-semibold ${STATUS_META[detail.board.status].pill}`}>
                      {STATUS_META[detail.board.status].label}
                    </span>
                    {detail.board.group_id && (
                      <span className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#0f4c81] px-2 py-0.5 text-[11px] font-semibold text-white">
                        <Users className="h-3 w-3" />
                        <span>{detail.board.group_name || '전용 그룹'}</span>
                      </span>
                    )}
                    <span className="text-xs font-medium text-[#0f4c81]">{detail.board.category}</span>
                    <span className="text-xs text-[#8a8a8e]">· {detail.board.work_type}</span>
                    {detail.board.deadline && (
                      <span
                        className={`chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                          deadlineInfo?.expired
                            ? 'bg-red-50 text-red-700'
                            : deadlineInfo?.urgent
                              ? 'bg-amber-50 text-amber-800'
                              : 'text-[#71717a]'
                        }`}
                      >
                        <Calendar className="h-3 w-3" />
                        <span>{deadlineInfo ? deadlineInfo.label : `마감 ${detail.board.deadline}`}</span>
                      </span>
                    )}
                    {!isAdmin && canManageBoard && (
                      <span className="chip-nowrap rounded-md bg-emerald-50 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-800">
                        그룹장 관리 권한
                      </span>
                    )}
                  </div>
                  <h1 className="text-lg font-semibold tracking-tight text-[#18181b]">{detail.board.title}</h1>
                  {detail.board.description && (
                    <p className="text-xs text-[#52525b]">{detail.board.description}</p>
                  )}
                  {/* Compact Progress Dashboard Strip */}
                  <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-[#52525b]">
                    <span className="chip-nowrap rounded-md bg-[#f7f7f5] px-2 py-0.5 font-medium">
                      수집 자료 <strong className="text-[#18181b]">{detail.submissions.length}건</strong>
                      {boardMetrics.imageCount > 0 ? ` (이미지 ${boardMetrics.imageCount})` : ''}
                    </span>
                    <span className="chip-nowrap rounded-md bg-[#f7f7f5] px-2 py-0.5 font-medium">
                      참여 인원 <strong className="text-[#18181b]">{boardMetrics.participants}명</strong>
                    </span>
                    <span className="chip-nowrap rounded-md bg-[#f7f7f5] px-2 py-0.5 font-medium">
                      투표 안건 <strong className="text-[#18181b]">{detail.proposals.length}건</strong>
                    </span>
                    {(detail.board.quorum_target || 0) > 0 && (
                      <span
                        className={`chip-nowrap rounded-md px-2 py-0.5 font-semibold ${
                          boardMetrics.maxVotes >= (detail.board.quorum_target || 0)
                            ? 'bg-emerald-50 text-emerald-800'
                            : 'bg-[#0f4c81]/10 text-[#0f4c81]'
                        }`}
                      >
                        투표 정족수 {boardMetrics.maxVotes}/{detail.board.quorum_target}명
                      </span>
                    )}
                  </div>
                </div>

                {canManageBoard && (
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    <select
                      aria-label="진행 단계"
                      value={detail.board.status}
                      onChange={(e) =>
                        void api.stdUpdateBoard(detail.board.id, { status: e.target.value }).then(() => refreshActiveBoard())
                      }
                      className="rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1.5 text-xs font-semibold text-[#18181b]"
                    >
                      <option value="collecting">① 수집 중</option>
                      <option value="voting">② 투표·개선 중</option>
                      <option value="published">③ 편찬·확정</option>
                    </select>
                    <button
                      type="button"
                      onClick={() =>
                        void api
                          .stdUpdateBoard(detail.board.id, { auto_route_enabled: !detail.board.auto_route_enabled })
                          .then(() => {
                            void refreshActiveBoard();
                            flashNotice(
                              !detail.board.auto_route_enabled
                                ? 'AI 고신뢰도(85%↑) 자동 이동·복사 배치가 켜졌습니다.'
                                : 'AI 자동 배치가 꺼지고 수동 승인 모드로 전환되었습니다.'
                            );
                          })
                      }
                      className={`chip-nowrap rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition ${
                        detail.board.auto_route_enabled
                          ? 'border-[#0f4c81] bg-[#0f4c81]/10 text-[#0f4c81]'
                          : 'border-black/[0.1] bg-white text-[#52525b]'
                      }`}
                    >
                      AI 자동배치 {detail.board.auto_route_enabled ? 'ON' : 'OFF'}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm(`"${detail.board.title}" 게시글을 삭제할까요?`)) {
                          void api.stdDeleteBoard(detail.board.id).then(() => loadBoards());
                        }
                      }}
                      title="게시글 삭제"
                      className="rounded-lg p-1.5 text-[#8a8a8e] hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </div>

              {/* Sub-Navigation Tabs */}
              <div className="mt-3 flex gap-1 overflow-x-auto">
                {(
                  [
                    { id: 'submissions', label: `수집 · 제출 (${detail.submissions.length})`, icon: <Upload className="h-3.5 w-3.5" /> },
                    { id: 'voting', label: `투표 · 개선 (${detail.proposals.length})`, icon: <Vote className="h-3.5 w-3.5" /> },
                    { id: 'memory', label: `교차 정리 (${pendingForCurrentBoard.length})`, icon: <ArrowRightLeft className="h-3.5 w-3.5" /> },
                    { id: 'publish', label: `전문가 PDF 편찬 (${detail.publications.length})`, icon: <BookCheck className="h-3.5 w-3.5" /> },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setSubTab(t.id)}
                    className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold transition ${
                      subTab === t.id
                        ? 'border-[#18181b] text-[#18181b]'
                        : 'border-transparent text-[#71717a] hover:text-[#18181b]'
                    }`}
                  >
                    {t.icon}
                    <span>{t.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* TAB CONTENT */}
            <div className="flex-1 overflow-y-auto px-5 py-5 sm:px-7">
              <div className="mx-auto max-w-4xl space-y-5">
                {/* 1. SUBMISSIONS TAB */}
                {subTab === 'submissions' && (
                  <>
                    {/* Cross-Board Pending Memory Wake-up Banner */}
                    {pendingForCurrentBoard.length > 0 && canManageBoard && (
                      <div className="rounded-xl border border-[#0f4c81]/25 bg-[#0f4c81]/[0.04] p-3.5 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-[#0f4c81]">
                            <Sparkles className="h-4 w-4 shrink-0" />
                            <span>AI 교차 분류 기억 {pendingForCurrentBoard.length}건 감지 — 이동 · 병행 복사 · 병합 가능</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => setSubTab('memory')}
                            className="chip-nowrap rounded-md bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold text-white"
                          >
                            교차 정리함 열기
                          </button>
                        </div>
                        <p className="text-[11.5px] text-[#3f3f46]">
                          {pendingForCurrentBoard[0].submission_title}: {pendingForCurrentBoard[0].reason}
                        </p>
                      </div>
                    )}

                    {/* Pastor / Member Multi-File Drag & Drop Upload Composer */}
                    <form
                      onSubmit={handleSubmitFile}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragActive(true);
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        setDragActive(false);
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        setDragActive(false);
                        if (e.dataTransfer.files?.length) addQueuedFiles(e.dataTransfer.files);
                      }}
                      className={`space-y-3 rounded-xl border p-4 transition ${
                        dragActive
                          ? 'border-[#0f4c81] bg-[#0f4c81]/[0.05] ring-2 ring-[#0f4c81]/25'
                          : 'border-black/[0.08] bg-[#fafaf9]'
                      }`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-1.5">
                        <span className="text-xs font-semibold text-[#18181b]">
                          행정 파일 및 현장 의견 제출
                        </span>
                        <span className="text-[11px] text-[#71717a]">
                          PDF · Word · 한글(HWPX) · Excel · PPTX · 이미지(사진 자동 글자인식) · 여러 파일 끌어다 놓기 (개당 30MB)
                        </span>
                      </div>

                      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                        <input
                          type="text"
                          value={subTitle}
                          onChange={(e) => setSubTitle(e.target.value)}
                          placeholder="자료 제목 (파일명 자동 사용 시 비워두기)"
                          className="rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-[16px] text-[#18181b] outline-none focus:border-[#18181b] lg:text-xs"
                        />
                        <div className="flex items-center gap-2">
                          <input
                            ref={fileRef}
                            type="file"
                            multiple
                            accept={STD_ACCEPT_ATTR}
                            className="hidden"
                            onChange={(e) => {
                              if (e.target.files?.length) addQueuedFiles(e.target.files);
                            }}
                          />
                          <button
                            type="button"
                            onClick={() => fileRef.current?.click()}
                            className="flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg border border-dashed border-black/[0.18] bg-white px-3 py-2 text-xs font-medium text-[#3f3f46] hover:border-[#18181b]"
                          >
                            <FilePlus2 className="h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                            <span className="truncate">
                              {subFiles.length > 0
                                ? `파일 ${subFiles.length}개 선택됨 (추가 선택 가능)`
                                : '파일 선택 또는 여기에 끌어다 놓기 (문서·PPTX·사진)'}
                            </span>
                          </button>
                        </div>
                      </div>

                      {subFiles.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {subFiles.map((f, fIdx) => (
                            <span
                              key={`${f.name}-${f.size}-${fIdx}`}
                              className="chip-nowrap inline-flex items-center gap-1.5 rounded-md border border-black/[0.08] bg-white px-2 py-1 text-[11px] font-medium text-[#18181b]"
                            >
                              {IMAGE_EXTS.has((f.name.split('.').pop() || '').toLowerCase()) ? (
                                <ImageIcon className="h-3 w-3 text-[#0f4c81]" />
                              ) : f.name.toLowerCase().endsWith('.pptx') ? (
                                <Presentation className="h-3 w-3 text-amber-700" />
                              ) : (
                                <FileText className="h-3 w-3 text-[#52525b]" />
                              )}
                              <span className="max-w-[180px] truncate">{f.name}</span>
                              <span className="text-[10px] text-[#8a8a8e]">{formatFileSize(f.size)}</span>
                              <button
                                type="button"
                                onClick={() => setSubFiles((prev) => prev.filter((_, i) => i !== fIdx))}
                                aria-label="대기 파일 제거"
                                className="text-[#8a8a8e] hover:text-red-600"
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}

                      <textarea
                        rows={2}
                        value={subNotes}
                        onChange={(e) => setSubNotes(e.target.value)}
                        placeholder="현장에서 사용 중인 규격 설명이나 개선이 필요한 점을 적어 주세요..."
                        className="w-full rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-[16px] leading-relaxed text-[#18181b] outline-none focus:border-[#18181b] lg:text-xs"
                      />

                      {uploadProgressText && (
                        <div className="flex items-center gap-2 rounded-lg border border-[#0f4c81]/20 bg-[#0f4c81]/[0.05] px-3 py-2 text-xs font-medium text-[#0f4c81]">
                          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                          <span className="truncate">{uploadProgressText}</span>
                        </div>
                      )}

                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] text-[#8a8a8e]">
                          {detail.board.submission_anonymous ? '익명 제출 게시글' : '실명 기록 게시글'}
                        </span>
                        <button
                          type="submit"
                          disabled={busy || (subFiles.length === 0 && !subTitle.trim() && !subNotes.trim())}
                          className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-40"
                        >
                          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                          <span>{subFiles.length > 1 ? `${subFiles.length}개 일괄 제출 · AI 분석` : '제출 및 AI 분석'}</span>
                        </button>
                      </div>
                    </form>

                    {/* Manager Manual Multi-Select Move / Copy / Merge Bar */}
                    {canManageBoard && selectedSubIds.length > 0 && (
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#18181b]/20 bg-[#18181b] px-4 py-2.5 text-white">
                        <span className="text-xs font-semibold">{selectedSubIds.length}개 자료 선택됨</span>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <select
                            value={batchTargetBoardId}
                            onChange={(e) => setBatchTargetBoardId(e.target.value)}
                            className="rounded-md bg-white px-2.5 py-1 text-xs font-medium text-[#18181b]"
                          >
                            <option value="">대상 분류 게시글 선택...</option>
                            {boards
                              .filter((b) => isAdmin || b.can_manage)
                              .map((b) => (
                                <option key={b.id} value={b.id}>
                                  {b.title} ({b.category})
                                </option>
                              ))}
                          </select>
                          <input
                            type="text"
                            value={batchMergedTitle}
                            onChange={(e) => setBatchMergedTitle(e.target.value)}
                            placeholder="병합 시 새 제목 (선택)"
                            className="w-36 rounded-md bg-white px-2 py-1 text-xs text-[#18181b]"
                          />
                          <button
                            type="button"
                            disabled={!batchTargetBoardId || busy}
                            onClick={() => void handleBatchAction('move')}
                            className="chip-nowrap rounded-md bg-white/15 px-2.5 py-1 text-[11px] font-semibold hover:bg-white/25 disabled:opacity-40"
                          >
                            이동
                          </button>
                          <button
                            type="button"
                            disabled={!batchTargetBoardId || busy}
                            onClick={() => void handleBatchAction('copy')}
                            className="chip-nowrap rounded-md bg-white/15 px-2.5 py-1 text-[11px] font-semibold hover:bg-white/25 disabled:opacity-40"
                          >
                            병행 복사
                          </button>
                          <button
                            type="button"
                            disabled={!batchTargetBoardId || busy}
                            onClick={() => void handleBatchAction('merge')}
                            className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold hover:bg-[#145d9e] disabled:opacity-40"
                          >
                            <GitMerge className="h-3 w-3" />
                            <span>통합 병합</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Submissions List */}
                    <div className="divide-y divide-black/[0.06] rounded-xl border border-black/[0.07] bg-white">
                      {detail.submissions.length === 0 ? (
                        <div className="p-10 text-center text-xs text-[#8a8a8e]">
                          아직 제출된 행정 파일이 없습니다. 위 양식에서 문서·PPTX·사진 파일을 올려보세요.
                        </div>
                      ) : (
                        detail.submissions.map((s) => {
                          const checked = selectedSubIds.includes(s.id);
                          const expanded = expandedSubId === s.id;
                          const isImg = isImageSubmission(s);
                          const isPptx = Boolean(s.meta?.is_pptx) || (s.file_type || '').toLowerCase() === 'pptx';
                          const canEditThis = canManageBoard || s.owner_id === currentOwnerId;
                          const isEditing = editingSubId === s.id;
                          return (
                            <div key={s.id} className="p-4 space-y-2.5">
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex min-w-0 flex-1 items-start gap-2.5">
                                  {canManageBoard && (
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={() =>
                                        setSelectedSubIds((prev) =>
                                          prev.includes(s.id) ? prev.filter((x) => x !== s.id) : [...prev, s.id]
                                        )
                                      }
                                      className="mt-1 h-4 w-4 accent-[#18181b]"
                                    />
                                  )}
                                  {isImg && s.stored_path && (
                                    <button
                                      type="button"
                                      onClick={() => setLightboxSub(s)}
                                      title="이미지 크게 보기"
                                      className="h-14 w-14 shrink-0 overflow-hidden rounded-lg border border-black/[0.1] bg-[#f7f7f5] transition hover:opacity-90"
                                    >
                                      <img
                                        src={safeAssetUrl(`/api/std/submissions/${encodeURIComponent(s.id)}/file`)}
                                        alt={s.title}
                                        className="h-full w-full object-cover"
                                        loading="lazy"
                                      />
                                    </button>
                                  )}
                                  <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-1.5">
                                      <h3 className="text-[13.5px] font-semibold text-[#18181b]">{s.title}</h3>
                                      {s.file_name && (
                                        <span className="chip-nowrap inline-flex items-center gap-1 rounded bg-[#f7f7f5] px-1.5 py-0.5 text-[10.5px] font-medium text-[#52525b]">
                                          {isImg ? (
                                            <ImageIcon className="h-3 w-3 text-[#0f4c81]" />
                                          ) : isPptx ? (
                                            <Presentation className="h-3 w-3 text-amber-700" />
                                          ) : (
                                            <FileText className="h-3 w-3" />
                                          )}
                                          <span>{s.file_name}</span>
                                          {s.file_size ? <span className="text-[#8a8a8e]">({formatFileSize(s.file_size)})</span> : null}
                                        </span>
                                      )}
                                      {isPptx && (s.meta?.slide_count || 0) > 0 && (
                                        <span className="chip-nowrap rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                                          슬라이드 {s.meta?.slide_count}장
                                          {(s.meta?.table_count || 0) > 0 ? ` · 표 ${s.meta?.table_count}` : ''}
                                        </span>
                                      )}
                                      {isImg && (s.meta?.ocr_chars || 0) > 0 && (
                                        <span className="chip-nowrap rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">
                                          사진 글자인식 완료
                                        </span>
                                      )}
                                      {s.source_origin !== 'direct' && (
                                        <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[#0f4c81]">
                                          {s.source_origin === 'moved' ? '이동됨' : s.source_origin === 'copied' ? '병행 복사본' : 'AI 통합 병합본'}
                                        </span>
                                      )}
                                    </div>
                                    <p className="mt-0.5 text-[11px] text-[#8a8a8e]">
                                      {s.author_label} · {s.created_at.slice(0, 16).replace('T', ' ')}
                                      {s.ai_cluster_key ? ` · 묶음: ${s.ai_cluster_key}` : ''}
                                    </p>
                                  </div>
                                </div>

                                <div className="flex shrink-0 flex-wrap items-center gap-1">
                                  {s.stored_path && s.file_name && (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        void triggerTicketDownload(
                                          `/api/std/submissions/${encodeURIComponent(s.id)}/file?download=1`,
                                          s.file_name
                                        )
                                      }
                                      title="원본 파일 다운로드"
                                      className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.08] bg-[#fafaf9] px-2 py-1 text-[11px] font-medium text-[#18181b] hover:bg-black/[0.05]"
                                    >
                                      <Download className="h-3 w-3" />
                                      <span>원본</span>
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => setExpandedSubId(expanded ? '' : s.id)}
                                    className="chip-nowrap inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-[#52525b] hover:bg-black/[0.05]"
                                  >
                                    <Eye className="h-3.5 w-3.5" />
                                    <span>{expanded ? '접기' : '내용'}</span>
                                  </button>
                                  {canEditThis && (
                                    <>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          if (isEditing) {
                                            setEditingSubId('');
                                          } else {
                                            setEditingSubId(s.id);
                                            setEditSubTitle(s.title);
                                            setEditSubNotes(s.notes);
                                            setEditSubCluster(s.ai_cluster_key || '');
                                          }
                                        }}
                                        title="제목·메모·묶음 수정"
                                        className="rounded-md p-1 text-[#71717a] hover:bg-black/[0.05] hover:text-[#18181b]"
                                      >
                                        <Pencil className="h-3.5 w-3.5" />
                                      </button>
                                      <button
                                        type="button"
                                        disabled={busy}
                                        onClick={() => void handleReanalyzeSubmission(s)}
                                        title="AI 요약·분류 다시 분석"
                                        className="rounded-md p-1 text-[#71717a] hover:bg-black/[0.05] hover:text-[#0f4c81] disabled:opacity-40"
                                      >
                                        <RefreshCw className="h-3.5 w-3.5" />
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => void api.stdDeleteSubmission(s.id).then(() => refreshActiveBoard())}
                                        aria-label="제출 삭제"
                                        title="제출 삭제"
                                        className="rounded-md p-1 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                      </button>
                                    </>
                                  )}
                                </div>
                              </div>

                              {isEditing && (
                                <div className="ml-6 space-y-2 rounded-lg border border-[#0f4c81]/25 bg-[#fafaf9] p-3">
                                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                                    <input
                                      type="text"
                                      value={editSubTitle}
                                      onChange={(e) => setEditSubTitle(e.target.value)}
                                      placeholder="자료 제목"
                                      className="rounded-md border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs font-semibold"
                                    />
                                    <input
                                      type="text"
                                      value={editSubCluster}
                                      onChange={(e) => setEditSubCluster(e.target.value)}
                                      placeholder="유사 규격 묶음명 (예: 재정 지출·결의 규격)"
                                      className="rounded-md border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs"
                                    />
                                  </div>
                                  <textarea
                                    rows={2}
                                    value={editSubNotes}
                                    onChange={(e) => setEditSubNotes(e.target.value)}
                                    placeholder="현장 설명 및 메모"
                                    className="w-full rounded-md border border-black/[0.1] bg-white p-2 text-xs"
                                  />
                                  <div className="flex flex-wrap justify-end gap-1.5">
                                    <button
                                      type="button"
                                      onClick={() => setEditingSubId('')}
                                      className="chip-nowrap rounded-md px-2.5 py-1 text-[11px] text-[#71717a]"
                                    >
                                      취소
                                    </button>
                                    <button
                                      type="button"
                                      disabled={busy}
                                      onClick={() => void handleSaveSubmissionEdit(s.id, false)}
                                      className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#18181b] px-2.5 py-1 text-[11px] font-semibold text-white"
                                    >
                                      <Save className="h-3 w-3" />
                                      <span>저장</span>
                                    </button>
                                    <button
                                      type="button"
                                      disabled={busy}
                                      onClick={() => void handleSaveSubmissionEdit(s.id, true)}
                                      className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold text-white"
                                    >
                                      <Sparkles className="h-3 w-3" />
                                      <span>저장 + AI 재분석</span>
                                    </button>
                                  </div>
                                </div>
                              )}

                              {s.ai_summary && (
                                <p className="pl-6 text-xs leading-relaxed text-[#3f3f46]">{s.ai_summary}</p>
                              )}
                              {s.ai_tags.length > 0 && (
                                <div className="flex flex-wrap gap-1 pl-6">
                                  {s.ai_tags.map((tag) => (
                                    <span key={tag} className="chip-nowrap rounded bg-[#f7f7f5] px-2 py-0.5 text-[10.5px] text-[#71717a]">
                                      #{tag}
                                    </span>
                                  ))}
                                </div>
                              )}
                              {expanded && (
                                <div className="ml-6 rounded-lg border border-black/[0.06] bg-[#fafaf9] p-3 text-xs leading-relaxed whitespace-pre-wrap text-[#27272a]">
                                  {s.notes && <p className="mb-2 font-medium text-[#0f4c81]">[제출 메모] {s.notes}</p>}
                                  {s.extracted_text ? s.extracted_text.slice(0, 3200) : '추출된 본문 없음'}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </>
                )}

                {/* 2. VOTING & IMPROVEMENTS TAB */}
                {subTab === 'voting' && (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-black/[0.07] bg-[#fafaf9] px-4 py-3">
                      <div className="text-xs text-[#52525b]">
                        정책:{' '}
                        <strong className="text-[#18181b]">
                          {detail.board.vote_visibility === 'anonymous' ? '완전 익명 투표' : '실명 공개 투표'}
                        </strong>{' '}
                        ·{' '}
                        <strong className="text-[#18181b]">
                          {detail.board.allow_vote_change ? '마감 전 재투표 가능' : '1회 확정 변경 불가'}
                        </strong>
                      </div>
                      {canManageBoard && (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <button
                            type="button"
                            disabled={busy || detail.submissions.length === 0}
                            onClick={() => void handleGenerateProposals()}
                            className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-40"
                          >
                            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                            <span>AI 유사 규격 묶기 · 개선안 자동 생성</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setShowManualProposal((v) => !v)}
                            className="chip-nowrap rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-semibold text-[#18181b]"
                          >
                            + 안건 직접 추가
                          </button>
                        </div>
                      )}
                    </div>

                    {deadlineInfo?.expired && (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2 text-xs font-medium text-amber-900">
                        마감일({detail.board.deadline})이 지나 투표가 자동 마감되었습니다.
                      </div>
                    )}

                    {showManualProposal && canManageBoard && (
                      <form onSubmit={handleCreateManualProposal} className="space-y-2.5 rounded-xl border border-black/[0.1] bg-white p-4">
                        <input
                          type="text"
                          value={propTitle}
                          onChange={(e) => setPropTitle(e.target.value)}
                          placeholder="투표 안건 제목 (예: 주일 사역보고서 표준 양식 선택)"
                          className="w-full rounded-lg border border-black/[0.1] px-3 py-2 text-xs"
                        />
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          <textarea
                            rows={2}
                            value={propOptA}
                            onChange={(e) => setPropOptA(e.target.value)}
                            placeholder="A안 내용 설명"
                            className="rounded-lg border border-black/[0.1] p-2.5 text-xs"
                          />
                          <textarea
                            rows={2}
                            value={propOptB}
                            onChange={(e) => setPropOptB(e.target.value)}
                            placeholder="B안 내용 설명 (선택)"
                            className="rounded-lg border border-black/[0.1] p-2.5 text-xs"
                          />
                        </div>
                        <div className="flex justify-end gap-2">
                          <button type="button" onClick={() => setShowManualProposal(false)} className="rounded-lg px-3 py-1.5 text-xs text-[#71717a]">취소</button>
                          <button type="submit" className="rounded-lg bg-[#18181b] px-4 py-1.5 text-xs font-semibold text-white">안건 등록</button>
                        </div>
                      </form>
                    )}

                    {detail.proposals.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-black/[0.12] p-10 text-center text-xs text-[#8a8a8e]">
                        아직 투표 안건이 없습니다. 자료를 수집한 뒤 [AI 유사 규격 묶기] 또는 [+ 안건 직접 추가]를 실행하세요.
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {detail.proposals.map((prop) => (
                          <div key={prop.id} className="rounded-xl border border-black/[0.08] bg-white p-4 space-y-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <h3 className="text-sm font-semibold text-[#18181b]">{prop.cluster_title}</h3>
                                  <span className="chip-nowrap rounded bg-[#f7f7f5] px-2 py-0.5 text-[10.5px] font-medium text-[#52525b]">
                                    총 {prop.total_votes}표
                                  </span>
                                  {prop.status === 'adopted' && (
                                    <span className="chip-nowrap rounded bg-emerald-50 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-800">
                                      채택 확정됨
                                    </span>
                                  )}
                                </div>
                                {prop.summary && <p className="mt-0.5 text-xs text-[#71717a]">{prop.summary}</p>}
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                {prop.options.length >= 2 && (
                                  <button
                                    type="button"
                                    onClick={() => setCompareProposal(prop)}
                                    className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1 text-[11px] font-semibold text-[#0f4c81] hover:bg-[#0f4c81]/5"
                                  >
                                    <Columns2 className="h-3.5 w-3.5" />
                                    <span>나란히 비교</span>
                                  </button>
                                )}
                                {canManageBoard && (
                                  <button
                                    type="button"
                                    onClick={() => void api.stdDeleteProposal(prop.id).then(() => refreshActiveBoard())}
                                    title="안건 삭제"
                                    className="rounded p-1 text-[#a1a1aa] hover:bg-red-50 hover:text-red-600"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                )}
                              </div>
                            </div>

                            {/* Optional 1-line Vote Rationale Input */}
                            {prop.status === 'open' && !deadlineInfo?.expired && (
                              <input
                                type="text"
                                value={voteComments[prop.id] || ''}
                                onChange={(e) => setVoteComments({ ...voteComments, [prop.id]: e.target.value })}
                                placeholder="투표 이유 한 줄 메모 (선택 — 입력 후 아래 '이 안 투표' 클릭 시 함께 기록)"
                                className="w-full rounded-lg border border-black/[0.08] bg-[#fafaf9] px-3 py-1.5 text-xs text-[#18181b] outline-none focus:border-[#0f4c81]"
                              />
                            )}

                            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                              {prop.options.map((opt) => {
                                const isMine = prop.my_vote_option_id === opt.id;
                                const isWinner = prop.winning_option_id === opt.id;
                                const isEditingOpt = editingOptionId === opt.id;
                                const showVoters = expandedVotersOptId === opt.id;
                                return (
                                  <div
                                    key={opt.id}
                                    className={`flex flex-col justify-between rounded-xl border p-3.5 transition ${
                                      isWinner
                                        ? 'border-emerald-400 bg-emerald-50/40'
                                        : isMine
                                          ? 'border-[#18181b] bg-[#fafaf9]'
                                          : opt.is_ai_improved
                                            ? 'border-[#0f4c81]/30 bg-[#0f4c81]/[0.02]'
                                            : 'border-black/[0.08] bg-white'
                                    }`}
                                  >
                                    <div>
                                      <div className="flex items-center justify-between gap-2">
                                        <span
                                          className={`chip-nowrap rounded px-2 py-0.5 text-[10.5px] font-bold ${
                                            opt.is_ai_improved
                                              ? 'bg-[#0f4c81] text-white'
                                              : 'bg-[#f0f0ee] text-[#18181b]'
                                          }`}
                                        >
                                          {opt.label}
                                        </span>
                                        <div className="flex items-center gap-1.5">
                                          {opt.vote_count > 0 && (
                                            <button
                                              type="button"
                                              onClick={() => setExpandedVotersOptId(showVoters ? '' : opt.id)}
                                              className="text-[11px] font-semibold text-[#0f4c81] hover:underline"
                                            >
                                              {opt.vote_count}표 ({opt.vote_pct}%)
                                            </button>
                                          )}
                                          {opt.vote_count === 0 && (
                                            <span className="text-xs font-semibold text-[#18181b]">0표 (0%)</span>
                                          )}
                                          {canManageBoard && (
                                            <button
                                              type="button"
                                              onClick={() => {
                                                if (isEditingOpt) {
                                                  setEditingOptionId('');
                                                } else {
                                                  setEditingOptionId(opt.id);
                                                  setEditOptTitle(opt.title);
                                                  setEditOptContent(opt.content_md);
                                                }
                                              }}
                                              title="후보안 문구 다듬기"
                                              className="rounded p-1 text-[#71717a] hover:bg-black/[0.06] hover:text-[#18181b]"
                                            >
                                              <Pencil className="h-3 w-3" />
                                            </button>
                                          )}
                                        </div>
                                      </div>

                                      {isEditingOpt ? (
                                        <div className="mt-2 space-y-2">
                                          <input
                                            type="text"
                                            value={editOptTitle}
                                            onChange={(e) => setEditOptTitle(e.target.value)}
                                            className="w-full rounded-md border border-black/[0.12] bg-white px-2.5 py-1 text-xs font-semibold"
                                          />
                                          <textarea
                                            rows={5}
                                            value={editOptContent}
                                            onChange={(e) => setEditOptContent(e.target.value)}
                                            className="w-full rounded-md border border-black/[0.12] bg-white p-2 text-xs leading-relaxed"
                                          />
                                          <div className="flex justify-end gap-1.5">
                                            <button
                                              type="button"
                                              onClick={() => setEditingOptionId('')}
                                              className="chip-nowrap rounded-md px-2.5 py-1 text-[11px] text-[#71717a]"
                                            >
                                              취소
                                            </button>
                                            <button
                                              type="button"
                                              disabled={busy}
                                              onClick={() => void handleSaveOptionEdit(opt.id)}
                                              className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold text-white"
                                            >
                                              <Save className="h-3 w-3" />
                                              <span>문구 저장</span>
                                            </button>
                                          </div>
                                        </div>
                                      ) : (
                                        <>
                                          <h4 className="mt-2 text-xs font-semibold text-[#18181b]">{opt.title}</h4>
                                          <div className="mt-2 max-h-44 overflow-y-auto text-xs text-[#3f3f46]">
                                            <MarkdownView content={opt.content_md} />
                                          </div>
                                        </>
                                      )}

                                      {showVoters && opt.voters.length > 0 && (
                                        <div className="mt-2 space-y-1 rounded-lg border border-black/[0.06] bg-[#fafaf9] p-2 text-[11px]">
                                          {opt.voters.map((v, vi) => (
                                            <div key={vi} className="flex items-start justify-between gap-2 text-[#3f3f46]">
                                              <span>
                                                <strong className="text-[#18181b]">{v.voter_label}</strong>
                                                {v.comment ? ` — ${v.comment}` : ''}
                                              </span>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>

                                    <div className="mt-3 space-y-2 border-t border-black/[0.06] pt-2.5">
                                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-black/[0.06]">
                                        <div
                                          className={`h-full rounded-full transition-all ${opt.is_ai_improved ? 'bg-[#0f4c81]' : 'bg-[#18181b]'}`}
                                          style={{ width: `${opt.vote_pct}%` }}
                                        />
                                      </div>
                                      <div className="flex items-center justify-between gap-1.5">
                                        <button
                                          type="button"
                                          disabled={busy || prop.status !== 'open' || Boolean(deadlineInfo?.expired)}
                                          onClick={() => void handleVote(prop.id, opt.id)}
                                          className={`chip-nowrap inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:opacity-45 ${
                                            isMine
                                              ? 'bg-[#18181b] text-white'
                                              : 'border border-black/[0.12] bg-white text-[#18181b] hover:bg-[#f7f7f5]'
                                          }`}
                                        >
                                          <Check className="h-3.5 w-3.5" />
                                          <span>{isMine ? '내 선택 완료' : '이 안 투표'}</span>
                                        </button>
                                        {canManageBoard && (
                                          <button
                                            type="button"
                                            disabled={busy}
                                            onClick={() =>
                                              void api
                                                .stdUpdateProposal(prop.id, { status: 'adopted', winning_option_id: opt.id })
                                                .then(() => {
                                                  void refreshActiveBoard();
                                                  flashNotice(`"${opt.title}"이(가) 최종 표준안으로 채택되었습니다.`);
                                                })
                                            }
                                            className="chip-nowrap rounded-lg px-2 py-1 text-[11px] font-medium text-emerald-800 hover:bg-emerald-50"
                                          >
                                            {isWinner ? '채택됨' : '최종 채택'}
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Improvement Comments Thread */}
                    <div className="rounded-xl border border-black/[0.07] bg-[#fafaf9] p-4 space-y-3">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-[#18181b]">
                        <MessageSquarePlus className="h-4 w-4 text-[#0f4c81]" />
                        <span>개선 의견 · 수정 제안 ({detail.comments.length}건 — 최종 PDF 편찬 시 자동 반영)</span>
                      </div>
                      <form onSubmit={handleAddComment} className="flex flex-wrap items-center gap-2">
                        <select
                          value={commentKind}
                          onChange={(e) => setCommentKind(e.target.value as 'improvement' | 'question' | 'decision')}
                          className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-xs"
                        >
                          <option value="improvement">개선 제안</option>
                          <option value="question">검토 질문</option>
                          <option value="decision">합의 메모</option>
                        </select>
                        <input
                          type="text"
                          value={commentText}
                          onChange={(e) => setCommentText(e.target.value)}
                          placeholder="규격이나 서식에서 보완할 점을 자유롭게 남겨 주세요..."
                          className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-[16px] outline-none focus:border-[#18181b] lg:text-xs"
                        />
                        <button
                          type="submit"
                          disabled={commentText.trim().length < 2 || busy}
                          className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-40"
                        >
                          <Send className="h-3.5 w-3.5" />
                          <span>등록</span>
                        </button>
                      </form>
                      {detail.comments.length > 0 && (
                        <div className="divide-y divide-black/[0.05] rounded-lg border border-black/[0.06] bg-white">
                          {detail.comments.map((c) => (
                            <div key={c.id} className="px-3.5 py-2.5 text-xs">
                              <div className="flex items-center justify-between gap-2 text-[11px] text-[#8a8a8e]">
                                <span className="font-semibold text-[#18181b]">{c.author_label}</span>
                                <span>{c.created_at.slice(5, 16).replace('T', ' ')}</span>
                              </div>
                              <p className="mt-1 text-[#27272a]">{c.content}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </>
                )}

                {/* 3. CROSS-BOARD MEMORY TAB */}
                {subTab === 'memory' && (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-black/[0.07] bg-[#fafaf9] p-3.5">
                      <div>
                        <p className="text-xs font-semibold text-[#18181b]">AI 교차 분류 기억 및 이동·복사·병합</p>
                        <p className="text-[11px] text-[#71717a]">
                          다른 분류에 속하거나 양쪽에 병행·통합해야 할 파일을 AI가 기억해 두고 1클릭 실행 및 되돌리기를 지원합니다.
                        </p>
                      </div>
                      {canManageBoard && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void api.stdScanMemory(detail.board.id).then((r) => {
                              void refreshActiveBoard();
                              flashNotice(`전체 보류 기억 스캔 완료: 이 게시글과 연관된 항목 ${r.matched.length}건 확인`);
                            })
                          }
                          className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-3 py-1.5 text-xs font-semibold text-[#18181b] hover:bg-[#f7f7f5]"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          <span>보류 기억 다시 스캔</span>
                        </button>
                      )}
                    </div>

                    {detail.memories.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-black/[0.12] p-10 text-center text-xs text-[#8a8a8e]">
                        이 게시글과 연결된 교차 분류 기억 항목이 없습니다.
                      </div>
                    ) : (
                      detail.memories.map((m) => (
                        <div key={m.id} className="rounded-xl border border-black/[0.08] bg-white p-4 space-y-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-2 py-0.5 text-[10.5px] font-semibold text-[#0f4c81]">
                                {m.action_type === 'move' ? '이동 추천' : m.action_type === 'copy' ? '병행 복사' : m.action_type === 'merge' ? '통합 병합' : `향후 분류 기억 (${m.suggested_category})`}
                              </span>
                              <span className="text-xs font-semibold text-[#18181b]">{m.submission_title}</span>
                              <span className="text-[11px] text-[#71717a]">신뢰도 {m.confidence}%</span>
                            </div>
                            <span className="chip-nowrap rounded-full bg-[#f7f7f5] px-2 py-0.5 text-[10.5px] font-semibold text-[#52525b]">
                              {m.status === 'pending'
                                ? '승인 대기'
                                : m.status === 'auto_applied'
                                  ? 'AI 자동 적용됨'
                                  : m.status === 'applied'
                                    ? '적용 완료'
                                    : m.status === 'reverted'
                                      ? '되돌림'
                                      : '보류됨'}
                            </span>
                          </div>
                          <p className="text-xs text-[#3f3f46]">{m.reason}</p>
                          <p className="text-[11px] text-[#8a8a8e]">
                            {m.source_board_title} → {m.target_board_title || `새 '${m.suggested_category}' 게시글 대기`}
                          </p>
                          {canManageBoard && m.status === 'pending' && (
                            <div className="flex flex-wrap items-center gap-1.5 pt-1">
                              <select
                                value={memTargetOverrides[m.id] || m.target_board_id || ''}
                                onChange={(e) => setMemTargetOverrides({ ...memTargetOverrides, [m.id]: e.target.value })}
                                className="rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1 text-xs"
                              >
                                <option value="">대상 게시글 선택...</option>
                                {boards
                                  .filter((b) => b.id !== m.source_board_id && (isAdmin || b.can_manage))
                                  .map((b) => (
                                    <option key={b.id} value={b.id}>
                                      {b.title} ({b.category})
                                    </option>
                                  ))}
                              </select>
                              <button type="button" onClick={() => void handleApplyMemory(m, 'move')} className="chip-nowrap rounded-md bg-[#18181b] px-2.5 py-1 text-[11px] font-semibold text-white">이동</button>
                              <button type="button" onClick={() => void handleApplyMemory(m, 'copy')} className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-black/[0.12] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#18181b]"><Copy className="h-3 w-3" />병행 복사</button>
                              <button type="button" onClick={() => void handleApplyMemory(m, 'merge')} className="chip-nowrap inline-flex items-center gap-1 rounded-md bg-[#0f4c81] px-2.5 py-1 text-[11px] font-semibold text-white"><GitMerge className="h-3 w-3" />통합 병합</button>
                              <button type="button" onClick={() => void handleApplyMemory(m, 'dismiss')} className="chip-nowrap rounded-md px-2 py-1 text-[11px] text-[#71717a] hover:bg-black/[0.05]">보류</button>
                            </div>
                          )}
                          {canManageBoard && (m.status === 'applied' || m.status === 'auto_applied') && (
                            <div className="pt-1">
                              <button
                                type="button"
                                onClick={() => void handleApplyMemory(m, 'revert')}
                                className="chip-nowrap inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-900"
                              >
                                <RotateCcw className="h-3 w-3" />
                                <span>작업 되돌리기 (Undo)</span>
                              </button>
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* 4. 4-ROLE EXPERT PDF/WORD/HWPX PUBLISHER TAB */}
                {subTab === 'publish' && (
                  <div className="space-y-4">
                    {canManageBoard && (
                      <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-4 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <Layers className="h-4 w-4 text-[#0f4c81]" />
                            <h3 className="text-xs font-semibold text-[#18181b]">
                              4역할 전문가 위원회 정규 PDF · Word · 한글(HWPX) 편찬 스튜디오
                            </h3>
                          </div>
                          {isAdmin && (
                            <button
                              type="button"
                              onClick={() => setShowConfigModal(true)}
                              className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#18181b] hover:bg-[#f7f7f5]"
                            >
                              <Stamp className="h-3 w-3 text-[#0f4c81]" />
                              <span>표지 · 결재선 맞춤 설정</span>
                            </button>
                          )}
                        </div>
                        <p className="text-[11.5px] leading-relaxed text-[#52525b]">
                          ① 체계·목차 설계 → ② 총회헌법·정관·시행세칙 수치·결재권자 정밀 충돌 감사 → ③ 표준 서식·체크리스트·신·구조문 대조표 편집 → ④ A4 PDF · Word(.docx) · 한글(.hwpx) 3종 동시 조판
                        </p>
                        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                          <input
                            type="text"
                            value={compileVersion}
                            onChange={(e) => setCompileVersion(e.target.value)}
                            placeholder="판본명 (비우면 자동 v1.0, v1.1...)"
                            className="rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                          />
                          <select
                            value={compileApprovalPresetId}
                            onChange={(e) => setCompileApprovalPresetId(e.target.value)}
                            className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-xs"
                          >
                            <option value="">결재선: 부서 기본 자동 매칭</option>
                            {(stdConfig?.approval_presets || []).map((ap) => (
                              <option key={ap.id} value={ap.id}>
                                {ap.name} ({ap.slots.join('→')})
                              </option>
                            ))}
                            <option value="__custom__">직접 결재선 입력...</option>
                          </select>
                          <input
                            type="text"
                            value={compileDirectives}
                            onChange={(e) => setCompileDirectives(e.target.value)}
                            placeholder="추가 편찬 지침 (선택)"
                            className="rounded-lg border border-black/[0.1] bg-white px-3 py-2 text-xs"
                          />
                        </div>
                        {compileApprovalPresetId === '__custom__' && (
                          <input
                            type="text"
                            value={compileCustomSlots}
                            onChange={(e) => setCompileCustomSlots(e.target.value)}
                            placeholder="결재 칸을 쉼표로 입력 (예: 총무, 부장, 지도교역자, 당회장)"
                            className="w-full rounded-lg border border-[#0f4c81]/35 bg-white px-3 py-2 text-xs"
                          />
                        )}
                        <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
                          <label className="flex cursor-pointer items-center gap-2 text-xs text-[#3f3f46]">
                            <input
                              type="checkbox"
                              checked={compileIncludeImages}
                              onChange={(e) => setCompileIncludeImages(e.target.checked)}
                              className="accent-[#0f4c81]"
                            />
                            <span>제출된 참고 이미지(사진·양식 사본 {boardMetrics.imageCount}장)를 규정집 부록에 함께 수록</span>
                          </label>
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              disabled={compiling}
                              onClick={() => void handleCompilePdf('draft')}
                              className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg border border-[#0f4c81] bg-white px-3.5 py-2 text-xs font-semibold text-[#0f4c81] transition hover:bg-[#0f4c81]/5 disabled:opacity-50"
                            >
                              {compiling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileEdit className="h-3.5 w-3.5" />}
                              <span>초안 먼저 검토 · 직접 편집</span>
                            </button>
                            <button
                              type="button"
                              disabled={compiling}
                              onClick={() => void handleCompilePdf('direct')}
                              className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white transition hover:bg-[#27272a] disabled:opacity-50"
                            >
                              {compiling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookCheck className="h-3.5 w-3.5" />}
                              <span>{compiling ? '전문가 위원회 편찬 중...' : '원클릭 PDF · Word · HWPX 편찬'}</span>
                            </button>
                          </div>
                        </div>

                        {compileStages.length > 0 && (
                          <div className="space-y-1.5 rounded-lg border border-black/[0.07] bg-white p-3">
                            {compileStages.map((st, idx) => (
                              <div key={idx} className="flex items-start gap-2 text-xs">
                                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#0f4c81]" />
                                <div>
                                  <span className="font-semibold text-[#18181b]">[{st.stage}/4 {st.role}]</span>{' '}
                                  <span className="text-[#52525b]">{st.message}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Published Versions List */}
                    {detail.publications.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-black/[0.12] p-10 text-center text-xs text-[#8a8a8e]">
                        아직 편찬된 정규 규정집 판본이 없습니다.
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {detail.publications.map((pub) => {
                          const hasDiff =
                            (pub.diff_report?.rows?.length || 0) > 0 ||
                            (pub.committee_report.diff_change_count || 0) > 0;
                          const hasHwpx = Boolean(pub.hwpx_path || pub.committee_report.has_hwpx);
                          return (
                            <div key={pub.id} className="rounded-xl border border-black/[0.08] bg-white p-4 space-y-3">
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="chip-nowrap rounded bg-[#18181b] px-2 py-0.5 text-[10.5px] font-bold text-white">
                                      {pub.version_label}
                                    </span>
                                    <h4 className="text-sm font-semibold text-[#18181b]">{pub.title}</h4>
                                    {pub.published_doc_id && (
                                      <span className="chip-nowrap inline-flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-800">
                                        <FileCheck2 className="h-3 w-3" />
                                        행정 Q&A 편입 완료
                                      </span>
                                    )}
                                    {(pub.forms_registered || 0) > 0 && (
                                      <span className="chip-nowrap inline-flex items-center gap-1 rounded bg-[#0f4c81]/10 px-2 py-0.5 text-[10.5px] font-semibold text-[#0f4c81]">
                                        <ClipboardCheck className="h-3 w-3" />
                                        서식 보관함 {pub.forms_registered}종 등록됨
                                      </span>
                                    )}
                                  </div>
                                  <p className="mt-1 text-[11px] text-[#8a8a8e]">
                                    편찬일: {pub.created_at.slice(0, 16).replace('T', ' ')} · {pub.committee_report.chapter_count || 0}개 장 · 표준 서식 {pub.committee_report.form_count || 0}종
                                    {(pub.committee_report.image_count || 0) > 0 ? ` · 참고 이미지 ${pub.committee_report.image_count}장` : ''}
                                    {' · '}PDF {Math.round((pub.committee_report.pdf_bytes || 0) / 1024)} KB
                                    {pub.committee_report.approval_slots?.length
                                      ? ` · 결재선: ${pub.committee_report.approval_slots.join('→')}`
                                      : ''}
                                  </p>
                                </div>

                                <div className="flex flex-wrap items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => setPreviewPub(previewPub?.id === pub.id ? null : pub)}
                                    className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1.5 text-xs font-semibold text-[#18181b]"
                                  >
                                    <Eye className="h-3.5 w-3.5" />
                                    <span>{previewPub?.id === pub.id ? '미리보기 닫기' : '미리보기'}</span>
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      void triggerTicketDownload(
                                        `/api/std/publications/${pub.id}/download/pdf`,
                                        `${pub.title}_${pub.version_label}.pdf`
                                      )
                                    }
                                    className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3 py-1.5 text-xs font-semibold text-white"
                                  >
                                    <Download className="h-3.5 w-3.5" />
                                    <span>정규 PDF</span>
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      void triggerTicketDownload(
                                        `/api/std/publications/${pub.id}/download/docx`,
                                        `${pub.title}_${pub.version_label}.docx`
                                      )
                                    }
                                    className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs font-medium text-[#3f3f46]"
                                  >
                                    <FileText className="h-3.5 w-3.5" />
                                    <span>Word</span>
                                  </button>
                                  {hasHwpx && (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        void triggerTicketDownload(
                                          `/api/std/publications/${pub.id}/download/hwpx`,
                                          `${pub.title}_${pub.version_label}.hwpx`
                                        )
                                      }
                                      className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-[#0f4c81]/30 bg-[#0f4c81]/[0.05] px-2.5 py-1.5 text-xs font-semibold text-[#0f4c81]"
                                    >
                                      <FileSpreadsheet className="h-3.5 w-3.5" />
                                      <span>한글(HWPX)</span>
                                    </button>
                                  )}
                                  {hasDiff && (
                                    <button
                                      type="button"
                                      onClick={() => void handleOpenDiffModal(pub)}
                                      className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-900"
                                    >
                                      <FileDiff className="h-3.5 w-3.5" />
                                      <span>신·구조문 대조표</span>
                                    </button>
                                  )}
                                </div>
                              </div>

                              {/* v4.0 Law Hierarchy Conflict Audit Summary */}
                              {pub.law_audit && pub.law_audit.length > 0 && (
                                <div className="rounded-lg border border-black/[0.06] bg-[#fafaf9] p-3 space-y-1.5">
                                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#0f4c81]">
                                    <ShieldCheck className="h-3.5 w-3.5" />
                                    <span>상위 법규 위계 정밀 감사 결과 ({pub.law_audit.length}건 대조)</span>
                                  </div>
                                  {pub.law_audit.slice(0, 4).map((la, i) => {
                                    const isConf = la.status.includes('충돌');
                                    const isWarn = la.status.includes('권고') || la.status.includes('보완');
                                    return (
                                      <p key={i} className="flex items-start gap-1.5 text-[11px] text-[#3f3f46]">
                                        {isConf ? (
                                          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" />
                                        ) : isWarn ? (
                                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
                                        ) : (
                                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                                        )}
                                        <span>
                                          <strong className={isConf ? 'text-red-700' : isWarn ? 'text-amber-800' : 'text-[#18181b]'}>
                                            [{la.status}] {la.source}
                                          </strong>{' '}
                                          — {la.note}
                                        </span>
                                      </p>
                                    );
                                  })}
                                </div>
                              )}

                              {/* 1-Click Publish into Main Q&A Engine + 1-Click Push to Right Forms Vault */}
                              {isAdmin && (
                                <div className="flex flex-wrap items-center gap-2 border-t border-black/[0.06] pt-3">
                                  <select
                                    value={publishReplaceMap[pub.id] || ''}
                                    onChange={(e) => setPublishReplaceMap({ ...publishReplaceMap, [pub.id]: e.target.value })}
                                    className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1.5 text-xs"
                                  >
                                    <option value="">새 공식 규정 문서로 [행정 Q&A]에 등록</option>
                                    {qaDocuments.map((d) => (
                                      <option key={d.id} value={d.id}>
                                        기존 문서 개정 교체: {d.title}
                                      </option>
                                    ))}
                                  </select>
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => void handlePublishToQa(pub)}
                                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#0f4c81] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-45"
                                  >
                                    <FileCheck2 className="h-3.5 w-3.5" />
                                    <span>행정 Q&A 편입</span>
                                  </button>
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => void handleRegisterFormsToVault(pub)}
                                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg border border-[#0f4c81] bg-white px-3 py-1.5 text-xs font-semibold text-[#0f4c81] hover:bg-[#0f4c81]/5 disabled:opacity-45"
                                  >
                                    <ClipboardCheck className="h-3.5 w-3.5" />
                                    <span>서식 보관함 등록</span>
                                  </button>
                                </div>
                              )}

                              {/* Live HTML Publication Preview Frame */}
                              {previewPub?.id === pub.id && (
                                <div className="overflow-hidden rounded-xl border border-black/[0.12] bg-[#f4f4f2] p-2">
                                  <iframe
                                    title={`${pub.title} 미리보기`}
                                    src={`/api/std/publications/${pub.id}/preview`}
                                    className="h-[520px] w-full rounded-lg bg-white"
                                  />
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Create New Board Modal */}
      {showCreateModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-5"
          onClick={() => setShowCreateModal(false)}
        >
          <div
            className="max-h-[92dvh] w-full max-w-lg overflow-y-auto rounded-2xl border border-black/[0.08] bg-white p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-black/[0.07] pb-3">
              <h3 className="text-sm font-semibold text-[#18181b]">새 행정 표준화 모집 게시글 개설</h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                aria-label="닫기"
                className="rounded-lg p-1 text-[#71717a] hover:bg-black/[0.05]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateBoard} className="mt-4 space-y-3.5">
              <div>
                <label className="mb-1 block text-[11.5px] font-semibold text-[#52525b]">모집 게시글 제목</label>
                <input
                  type="text"
                  required
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="예: 2026 재정·지출결의서 행정 표준화"
                  className="w-full rounded-lg border border-black/[0.1] px-3 py-2 text-xs outline-none focus:border-[#18181b]"
                />
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <label className="text-[11.5px] font-semibold text-[#52525b]">교회 부서 · 행정 분류</label>
                  <button
                    type="button"
                    onClick={() => {
                      setShowCreateModal(false);
                      setShowConfigModal(true);
                    }}
                    className="text-[10.5px] font-medium text-[#0f4c81] hover:underline"
                  >
                    분류·결재선 편집
                  </button>
                </div>
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {(stdConfig?.categories.map((c) => c.name) || DEFAULT_CATEGORY_NAMES).map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setNewCat(c)}
                      className={`chip-nowrap rounded-md px-2 py-1 text-[11px] font-medium ${
                        newCat === c ? 'bg-[#18181b] text-white' : 'bg-[#f7f7f5] text-[#52525b]'
                      }`}
                    >
                      {c}
                    </button>
                  ))}
                </div>
                <input
                  type="text"
                  value={newCat}
                  onChange={(e) => setNewCat(e.target.value)}
                  className="w-full rounded-lg border border-black/[0.1] px-3 py-1.5 text-xs"
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <label className="mb-1 block text-[11.5px] font-semibold text-[#52525b]">작업 형태</label>
                  <select
                    value={newWorkType}
                    onChange={(e) => setNewWorkType(e.target.value)}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-xs"
                  >
                    {(stdConfig?.work_types || DEFAULT_WORK_TYPE_NAMES).map((w) => (
                      <option key={w} value={w}>{w}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[11.5px] font-semibold text-[#52525b]">수집·투표 마감일 (선택)</label>
                  <input
                    type="date"
                    value={newDeadline}
                    onChange={(e) => setNewDeadline(e.target.value)}
                    className="w-full rounded-lg border border-black/[0.1] px-2.5 py-2 text-xs"
                  />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[11.5px] font-semibold text-[#52525b]">목표 투표 정족수 인원 (선택 · 0이면 표시 안 함)</label>
                <input
                  type="number"
                  min={0}
                  max={500}
                  value={newQuorumTarget}
                  onChange={(e) => setNewQuorumTarget(Math.max(0, Number(e.target.value) || 0))}
                  placeholder="예: 10 (교역자 10명 이상 참여 목표)"
                  className="w-full rounded-lg border border-black/[0.1] px-3 py-1.5 text-xs"
                />
              </div>

              {/* Group Visibility Scope */}
              {(isAdmin || leaderGroups.length > 0) && (
                <div>
                  <label className="mb-1 block text-[11.5px] font-semibold text-[#52525b]">참여 범위 (공개 / 전용 그룹)</label>
                  <select
                    value={newGroupId}
                    onChange={(e) => setNewGroupId(e.target.value)}
                    className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-2 text-xs"
                  >
                    {isAdmin && <option value="">전체 교역자 공용 (모두 참여)</option>}
                    {leaderGroups.map((g) => (
                      <option key={g.id} value={g.id}>
                        그룹 전용: {g.name} ({g.member_count}명)
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="mb-1 block text-[11.5px] font-semibold text-[#52525b]">수집 안내 및 목표</label>
                <textarea
                  rows={2}
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="각 부서에서 사용 중인 신청서·보고서 파일과 개선 의견을 올려 주세요."
                  className="w-full rounded-lg border border-black/[0.1] p-2.5 text-xs"
                />
              </div>

              {/* Voting & Routing Policies (Supports all 1/2/3 combinations cleanly!) */}
              <div className="space-y-2 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3">
                <p className="text-[11px] font-semibold text-[#18181b]">투표 · 참여 · AI 자동배치 정책</p>
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={newVoteVis}
                    onChange={(e) => setNewVoteVis(e.target.value as 'named' | 'anonymous')}
                    className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs"
                  >
                    <option value="named">투표 실명 공개</option>
                    <option value="anonymous">투표 완전 익명</option>
                  </select>
                  <select
                    value={newAllowChange ? '1' : '0'}
                    onChange={(e) => setNewAllowChange(e.target.value === '1')}
                    className="rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs"
                  >
                    <option value="1">마감 전 재투표 허용</option>
                    <option value="0">1회 확정 변경 불가</option>
                  </select>
                </div>
                <label className="flex cursor-pointer items-center gap-2 text-xs text-[#3f3f46]">
                  <input type="checkbox" checked={newSubAnon} onChange={(e) => setNewSubAnon(e.target.checked)} className="accent-[#18181b]" />
                  <span>제출자 익명 표시 (관리자 외 팀원에게 '익명 교역자'로 표시)</span>
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-xs text-[#3f3f46]">
                  <input type="checkbox" checked={newAutoRoute} onChange={(e) => setNewAutoRoute(e.target.checked)} className="accent-[#0f4c81]" />
                  <span>AI 고신뢰도(85%↑) 타 분류 자동 이동·복사 허용 (언제든 되돌리기 가능)</span>
                </label>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button type="button" onClick={() => setShowCreateModal(false)} className="rounded-lg px-3.5 py-2 text-xs font-medium text-[#71717a]">
                  취소
                </button>
                <button
                  type="submit"
                  disabled={!newTitle.trim() || busy}
                  className="chip-nowrap rounded-lg bg-[#18181b] px-4 py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-45"
                >
                  모집 게시글 개설
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Church Taxonomy / Approval Line / PDF Cover Config Modal */}
      {showConfigModal && stdConfig && (
        <StdConfigModal
          config={stdConfig}
          onSaved={(next) => {
            setStdConfig(next);
            flashNotice('목포사랑의교회 표준화실 분류·결재선·PDF 표지 규격이 저장되었습니다.');
          }}
          onClose={() => setShowConfigModal(false)}
        />
      )}

      {/* Side-by-Side Proposal Diff Comparator Modal */}
      {compareProposal && (
        <StdProposalCompareModal
          proposal={compareProposal}
          onClose={() => setCompareProposal(null)}
        />
      )}

      {/* 2-Stage Manuscript Draft Editor Modal */}
      {draftSession && (
        <StdManuscriptEditorModal
          versionLabel={draftSession.version_label}
          initialManuscript={draftSession.manuscript}
          lawAudit={draftSession.law_audit}
          finalizing={finalizingDraft}
          onFinalize={(edited, ver) => void handleFinalizeEditedDraft(edited, ver)}
          onClose={() => setDraftSession(null)}
        />
      )}

      {/* Revision 신·구조문 대조표 Modal */}
      {diffModalState && (
        <StdDiffModal
          title={diffModalState.title}
          diffReport={diffModalState.diff}
          onClose={() => setDiffModalState(null)}
        />
      )}

      {/* Submitted Image Lightbox Preview Modal */}
      {lightboxSub && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-xs"
          onClick={() => setLightboxSub(null)}
        >
          <div
            className="flex max-h-[90dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-black/[0.12] bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-4 py-3">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold text-[#18181b]">{lightboxSub.title}</h3>
                <p className="text-[11px] text-[#71717a]">
                  {lightboxSub.file_name}
                  {lightboxSub.meta?.width && lightboxSub.meta?.height
                    ? ` · ${lightboxSub.meta.width}×${lightboxSub.meta.height}px`
                    : ''}
                  {lightboxSub.file_size ? ` · ${formatFileSize(lightboxSub.file_size)}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() =>
                    void triggerTicketDownload(
                      `/api/std/submissions/${encodeURIComponent(lightboxSub.id)}/file?download=1`,
                      lightboxSub.file_name || `${lightboxSub.title}.png`
                    )
                  }
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3 py-1.5 text-xs font-semibold text-white"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>원본 저장</span>
                </button>
                <button
                  type="button"
                  onClick={() => setLightboxSub(null)}
                  aria-label="닫기"
                  className="rounded-lg p-1.5 text-[#71717a] hover:bg-black/[0.06]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="grid flex-1 grid-cols-1 overflow-y-auto md:grid-cols-12">
              <div className="flex items-center justify-center bg-[#f4f4f2] p-4 md:col-span-8">
                <img
                  src={safeAssetUrl(`/api/std/submissions/${encodeURIComponent(lightboxSub.id)}/file`)}
                  alt={lightboxSub.title}
                  className="max-h-[68dvh] max-w-full rounded-lg border border-black/[0.08] bg-white object-contain shadow-sm"
                />
              </div>
              <div className="border-t border-black/[0.08] p-4 md:col-span-4 md:border-t-0 md:border-l">
                <p className="mb-2 text-xs font-semibold text-[#0f4c81]">사진 글자인식(OCR) 추출 내용</p>
                <div className="max-h-[60dvh] overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-[#27272a]">
                  {lightboxSub.extracted_text || '추출된 텍스트가 없습니다.'}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
