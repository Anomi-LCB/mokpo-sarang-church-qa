import React, { useEffect, useState } from 'react';
import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  LogOut,
  Plus,
  QrCode,
  RefreshCw,
  Shield,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import { api } from '../api';
import type { CollabGroup, MemberDirectoryItem } from '../types';

interface Props {
  isAdmin: boolean;
  currentOwnerId: string;
  onGroupsChanged: () => void;
  onIdentityRecovered?: () => void;
  onClose: () => void;
}

type GroupTab = 'groups' | 'permissions' | 'recovery';

export const GroupsModal: React.FC<Props> = ({
  isAdmin,
  currentOwnerId,
  onGroupsChanged,
  onIdentityRecovered,
  onClose,
}) => {
  const [tab, setTab] = useState<GroupTab>('groups');
  const [groups, setGroups] = useState<CollabGroup[]>([]);
  const [canCreate, setCanCreate] = useState(isAdmin);
  const [hasRecovery, setHasRecovery] = useState(false);
  const [membersDir, setMembersDir] = useState<MemberDirectoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [copiedId, setCopiedId] = useState('');

  // Join & Create forms
  const [joinCode, setJoinCode] = useState('');
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [inviteSelectMap, setInviteSelectMap] = useState<Record<string, string>>({});
  const [qrMap, setQrMap] = useState<Record<string, { join_url: string; qr_data_url: string }>>({});

  // Personal Recovery Code
  const [newRecovery, setNewRecovery] = useState('');
  const [claimRecovery, setClaimRecovery] = useState('');

  const loadAll = async () => {
    setLoading(true);
    try {
      const res = await api.listGroups();
      setGroups(res.groups);
      setCanCreate(res.can_create_group);
      setHasRecovery(res.has_recovery_code);
      if (isAdmin) {
        const allM = await api.listMembersAdmin().catch(() => res.members_directory);
        setMembersDir(allM);
      } else {
        setMembersDir(res.members_directory || []);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '그룹 정보를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  const copyText = (key: string, val: string) => {
    navigator.clipboard?.writeText(val).catch(() => {});
    setCopiedId(key);
    setTimeout(() => setCopiedId(''), 1800);
  };

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!joinCode.trim() || busy) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const res = await api.joinGroup(joinCode.trim());
      setJoinCode('');
      await loadAll();
      onGroupsChanged();
      setMsg(`"${res.group.name}" 그룹에 참여했습니다. 이제 그룹 채팅방과 표준화 과제를 함께 이용할 수 있습니다.`);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '초대 코드 확인 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || busy) return;
    setBusy(true);
    setErr('');
    setMsg('');
    try {
      const g = await api.createGroup(newName.trim(), newDesc.trim());
      setNewName('');
      setNewDesc('');
      await loadAll();
      onGroupsChanged();
      setMsg(`"${g.name}" 그룹이 개설되었습니다. 초대 코드(${g.invite_code})를 팀원에게 공유하세요.`);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '그룹 개설 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleInviteMember = async (groupId: string) => {
    const targetOwnerId = inviteSelectMap[groupId];
    if (!targetOwnerId || busy) return;
    const found = membersDir.find((m) => m.owner_id === targetOwnerId);
    setBusy(true);
    setErr('');
    try {
      await api.inviteGroupMember(groupId, targetOwnerId, found?.label || '');
      setInviteSelectMap((prev) => ({ ...prev, [groupId]: '' }));
      await loadAll();
      onGroupsChanged();
      setMsg(`${found?.label || '멤버'}님을 그룹에 직접 초대했습니다.`);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '멤버 초대 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleShowQr = async (groupId: string) => {
    if (qrMap[groupId]) {
      setQrMap((prev) => {
        const cp = { ...prev };
        delete cp[groupId];
        return cp;
      });
      return;
    }
    try {
      const data = await api.getGroupInviteQr(groupId);
      setQrMap((prev) => ({ ...prev, [groupId]: { join_url: data.join_url, qr_data_url: data.qr_data_url } }));
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '초대 QR 생성 실패');
    }
  };

  const handleToggleCreatorGrant = async (member: MemberDirectoryItem) => {
    setBusy(true);
    setErr('');
    try {
      const next = !Boolean(member.can_create_group);
      await api.setMemberGroupPermission(member.owner_id, next);
      await loadAll();
      setMsg(`${member.label}님에게 그룹 개설 권한을 ${next ? '부여' : '회수'}했습니다.`);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '권한 변경 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleSetRecovery = async () => {
    if (newRecovery.trim().length < 4 || busy) return;
    setBusy(true);
    setErr('');
    try {
      await api.setRecoveryCode(newRecovery.trim());
      setNewRecovery('');
      setHasRecovery(true);
      setMsg('개인 복구 코드가 저장되었습니다. 다른 PC·스마트폰에서 이 코드를 입력하면 내 그룹과 비공개 대화가 그대로 연결됩니다.');
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '복구 코드 저장 실패');
    } finally {
      setBusy(false);
    }
  };

  const handleClaimRecovery = async () => {
    if (claimRecovery.trim().length < 4 || busy) return;
    setBusy(true);
    setErr('');
    try {
      const res = await api.claimRecoveryCode(claimRecovery.trim());
      setClaimRecovery('');
      onIdentityRecovered?.();
      await loadAll();
      onGroupsChanged();
      setMsg(`${res.label}님의 그룹 및 대화 프로필이 이 기기와 연결되었습니다.`);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '복구 코드 연결 실패');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-xs sm:p-5"
      onClick={onClose}
    >
      <div
        data-modal="groups"
        className="flex h-[min(86dvh,720px)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-black/[0.08] bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-black/[0.08] bg-[#fafaf9] px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#18181b] text-white">
              <Users className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#18181b]">그룹 · 초대 협업 관리</h3>
              <p className="text-[11px] text-[#71717a]">
                초대된 그룹 멤버끼리 <strong className="text-[#18181b]">공동 채팅방</strong>과{' '}
                <strong className="text-[#18181b]">행정 표준화 과제</strong>를 실시간으로 함께 작업합니다.
              </p>
            </div>
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

        {/* Sub-tabs */}
        <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-black/[0.07] bg-[#f7f7f5] px-4 pt-2">
          <button
            type="button"
            onClick={() => setTab('groups')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'groups' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <Users className="h-3.5 w-3.5" />
            <span>내 그룹 · 초대 ({groups.length})</span>
          </button>
          {isAdmin && (
            <button
              type="button"
              onClick={() => setTab('permissions')}
              className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
                tab === 'permissions' ? 'border-[#0f4c81] text-[#0f4c81]' : 'border-transparent text-[#71717a]'
              }`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              <span>그룹 개설 권한 관리</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setTab('recovery')}
            className={`chip-nowrap inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold ${
              tab === 'recovery' ? 'border-[#18181b] text-[#18181b]' : 'border-transparent text-[#71717a]'
            }`}
          >
            <KeyRound className="h-3.5 w-3.5" />
            <span>기기 간 내 그룹 연결</span>
          </button>
        </div>

        {/* Body */}
        <div className="settings-scroll flex-1 overflow-y-auto p-5">
          {msg && (
            <div className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-xs font-medium text-emerald-900">
              {msg}
            </div>
          )}
          {err && (
            <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2 text-xs font-medium text-red-700">
              {err}
            </div>
          )}

          {loading ? (
            <div className="flex h-40 items-center justify-center text-[#8a8a8e]">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : tab === 'groups' ? (
            <div className="space-y-4">
              {/* Join by 6-char invite code */}
              <form
                onSubmit={handleJoin}
                className="flex flex-wrap items-center gap-2 rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-[#18181b]">초대 코드로 그룹 참여하기</p>
                  <p className="text-[11px] text-[#71717a]">전달받은 6자리 초대 코드를 입력하면 즉시 그룹에 참여됩니다.</p>
                </div>
                <input
                  type="text"
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
                  placeholder="초대 코드 (예: AB3K9P)"
                  maxLength={12}
                  className="w-40 rounded-lg border border-black/[0.12] bg-white px-3 py-2 font-mono text-xs font-semibold tracking-widest uppercase outline-none focus:border-[#0f4c81]"
                />
                <button
                  type="submit"
                  disabled={joinCode.trim().length < 4 || busy}
                  className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#0f4c81] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#0c3d68] disabled:opacity-45"
                >
                  <UserPlus className="h-3.5 w-3.5" />
                  <span>참여</span>
                </button>
              </form>

              {/* Create Group (Admin or Authorized Grantee ONLY!) */}
              {canCreate ? (
                <form onSubmit={handleCreate} className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="text-xs font-semibold text-[#18181b]">새 협업 그룹 개설</h4>
                    <span className="chip-nowrap rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                      개설 권한 보유
                    </span>
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <input
                      type="text"
                      required
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="그룹 이름 (예: 재정부 실무팀, 교역자 전체, 교육선교부)"
                      className="rounded-lg border border-black/[0.1] px-3 py-2 text-xs outline-none focus:border-[#18181b]"
                    />
                    <input
                      type="text"
                      value={newDesc}
                      onChange={(e) => setNewDesc(e.target.value)}
                      placeholder="간단한 설명 (선택)"
                      className="rounded-lg border border-black/[0.1] px-3 py-2 text-xs outline-none focus:border-[#18181b]"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={newName.trim().length < 2 || busy}
                    className="chip-nowrap inline-flex items-center gap-1.5 rounded-lg bg-[#18181b] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#27272a] disabled:opacity-45"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    <span>그룹 만들기</span>
                  </button>
                </form>
              ) : (
                <div className="flex items-center gap-2 rounded-xl border border-black/[0.07] bg-[#fafaf9] px-3.5 py-2.5 text-[11.5px] text-[#52525b]">
                  <Shield className="h-4 w-4 shrink-0 text-[#0f4c81]" />
                  <span>
                    새 그룹 개설은 <strong>관리자 또는 그룹 개설 권한을 부여받은 담당자</strong>만 가능합니다. 위에서 초대 코드로 그룹에 참여하거나 관리자에게 권한 부여를 요청하세요.
                  </span>
                </div>
              )}

              {/* Joined / Managed Groups List */}
              {groups.length === 0 ? (
                <div className="rounded-xl border border-dashed border-black/[0.12] p-8 text-center text-xs text-[#8a8a8e]">
                  아직 참여 중인 그룹이 없습니다. 초대 코드를 입력하거나 새 그룹을 개설해 보세요.
                </div>
              ) : (
                <div className="space-y-3">
                  {groups.map((g) => {
                    const isLeaderOrAdmin = isAdmin || g.my_role === 'leader';
                    const existingIds = new Set(g.members.map((m) => m.owner_id));
                    const invitable = membersDir.filter((m) => !existingIds.has(m.owner_id));
                    return (
                      <div key={g.id} className="space-y-3 rounded-xl border border-black/[0.08] bg-white p-4">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <h4 className="text-sm font-semibold text-[#18181b]">{g.name}</h4>
                              <span className="chip-nowrap rounded-full bg-[#f7f7f5] px-2 py-0.5 text-[10.5px] font-semibold text-[#52525b]">
                                멤버 {g.member_count}명
                              </span>
                              {g.my_role === 'leader' && (
                                <span className="chip-nowrap rounded bg-[#0f4c81]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[#0f4c81]">
                                  그룹장
                                </span>
                              )}
                            </div>
                            {g.description && <p className="mt-0.5 text-xs text-[#71717a]">{g.description}</p>}
                          </div>

                          <div className="flex flex-wrap items-center gap-1.5">
                            <div className="inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1">
                              <span className="text-[10.5px] text-[#71717a]">초대코드</span>
                              <code className="font-mono text-xs font-bold tracking-wider text-[#0f4c81]">
                                {g.invite_code}
                              </code>
                              <button
                                type="button"
                                onClick={() => copyText(g.id, g.invite_code)}
                                title="초대 코드 복사"
                                className="rounded p-0.5 text-[#52525b] hover:bg-black/[0.06]"
                              >
                                {copiedId === g.id ? (
                                  <Check className="h-3 w-3 text-emerald-600" />
                                ) : (
                                  <Copy className="h-3 w-3" />
                                )}
                              </button>
                            </div>
                            <button
                              type="button"
                              onClick={() => void handleShowQr(g.id)}
                              title="초대 QR / 링크 보기"
                              className="chip-nowrap inline-flex items-center gap-1 rounded-lg border border-black/[0.1] bg-white px-2 py-1 text-[11px] font-medium text-[#3f3f46] hover:bg-[#f7f7f5]"
                            >
                              <QrCode className="h-3.5 w-3.5" />
                              <span>QR</span>
                            </button>
                            {isLeaderOrAdmin && (
                              <>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() =>
                                    void api.regenerateGroupCode(g.id).then(() => loadAll())
                                  }
                                  title="초대 코드 재발급"
                                  className="rounded-lg border border-black/[0.1] bg-white p-1.5 text-[#71717a] hover:bg-[#f7f7f5] hover:text-[#18181b]"
                                >
                                  <RefreshCw className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => {
                                    if (window.confirm(`"${g.name}" 그룹을 삭제할까요? (기존 대화/문서 내용은 보존됩니다)`)) {
                                      void api.deleteGroup(g.id).then(() => {
                                        void loadAll();
                                        onGroupsChanged();
                                      });
                                    }
                                  }}
                                  title="그룹 삭제"
                                  className="rounded-lg border border-black/[0.1] bg-white p-1.5 text-[#8a8a8e] hover:bg-red-50 hover:text-red-600"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </>
                            )}
                          </div>
                        </div>

                        {/* QR Invite Box */}
                        {qrMap[g.id] && (
                          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-black/[0.07] bg-[#fafaf9] p-3">
                            <img
                              src={qrMap[g.id].qr_data_url}
                              alt="그룹 초대 QR"
                              className="h-24 w-24 rounded-lg border border-black/[0.08] bg-white p-1"
                            />
                            <div className="min-w-0 flex-1 space-y-1.5">
                              <p className="text-xs font-semibold text-[#18181b]">초대 링크 · QR로 바로 참여</p>
                              <div className="flex items-center gap-1.5">
                                <code className="min-w-0 flex-1 truncate rounded bg-white px-2 py-1 text-[11px] ring-1 ring-black/[0.07]">
                                  {qrMap[g.id].join_url}
                                </code>
                                <button
                                  type="button"
                                  onClick={() => copyText(`url_${g.id}`, qrMap[g.id].join_url)}
                                  className="chip-nowrap rounded-md bg-[#18181b] px-2.5 py-1 text-[11px] font-semibold text-white"
                                >
                                  {copiedId === `url_${g.id}` ? '복사됨' : '링크 복사'}
                                </button>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Members Pills */}
                        <div className="flex flex-wrap items-center gap-1.5">
                          {g.members.map((m) => (
                            <span
                              key={m.owner_id}
                              className="chip-nowrap inline-flex items-center gap-1 rounded-full border border-black/[0.08] bg-[#fafaf9] px-2.5 py-1 text-[11px] text-[#27272a]"
                            >
                              <span className="font-medium">{m.member_label}</span>
                              {m.role === 'leader' && <span className="text-[10px] text-[#0f4c81]">(장)</span>}
                              {(isLeaderOrAdmin || m.owner_id === currentOwnerId) && m.role !== 'leader' && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    void api.removeGroupMember(g.id, m.owner_id).then(() => {
                                      void loadAll();
                                      onGroupsChanged();
                                    })
                                  }
                                  title={m.owner_id === currentOwnerId ? '그룹 나가기' : '멤버 제외'}
                                  className="text-[#a1a1aa] hover:text-red-600"
                                >
                                  {m.owner_id === currentOwnerId ? (
                                    <LogOut className="h-3 w-3" />
                                  ) : (
                                    <X className="h-3 w-3" />
                                  )}
                                </button>
                              )}
                            </span>
                          ))}
                        </div>

                        {/* Direct Invite Dropdown for Leaders/Admins */}
                        {isLeaderOrAdmin && invitable.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 border-t border-black/[0.06] pt-2.5">
                            <select
                              value={inviteSelectMap[g.id] || ''}
                              onChange={(e) => setInviteSelectMap({ ...inviteSelectMap, [g.id]: e.target.value })}
                              className="min-w-0 flex-1 rounded-lg border border-black/[0.1] bg-[#fafaf9] px-2.5 py-1.5 text-xs"
                            >
                              <option value="">접속 이력이 있는 교역자·팀원 직접 초대...</option>
                              {invitable.map((im) => (
                                <option key={im.owner_id} value={im.owner_id}>
                                  {im.label} ({im.role === 'admin' ? '관리자' : '팀원'})
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              disabled={!inviteSelectMap[g.id] || busy}
                              onClick={() => void handleInviteMember(g.id)}
                              className="chip-nowrap inline-flex items-center gap-1 rounded-lg bg-[#18181b] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                            >
                              <UserPlus className="h-3.5 w-3.5" />
                              <span>직접 초대</span>
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : tab === 'permissions' && isAdmin ? (
            <div className="space-y-3">
              <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3.5 text-xs text-[#3f3f46]">
                <strong>그룹 개설 권한 관리 (관리자 전용):</strong> 아래에서 승인된 담당자·교역자만 새 협업 그룹을 개설할 수 있습니다. 권한이 없는 팀원은 초대 코드로 참여만 가능합니다.
              </div>
              {membersDir.length === 0 ? (
                <p className="py-8 text-center text-xs text-[#8a8a8e]">아직 접속한 팀원 기록이 없습니다.</p>
              ) : (
                <div className="divide-y divide-black/[0.06] rounded-xl border border-black/[0.08] bg-white">
                  {membersDir.map((m) => (
                    <div key={m.owner_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold text-[#18181b]">{m.label}</span>
                          <span className="chip-nowrap rounded bg-[#f7f7f5] px-1.5 py-0.5 text-[10px] font-medium text-[#52525b]">
                            {m.role === 'admin' ? '관리자' : '교역자/팀원'}
                          </span>
                        </div>
                        <p className="mt-0.5 text-[10.5px] text-[#8a8a8e]">
                          참여 그룹 {m.group_count || 0}개 · 최근 접속 {m.last_seen_at.slice(0, 16).replace('T', ' ')}
                        </p>
                      </div>
                      {m.role === 'admin' ? (
                        <span className="chip-nowrap rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-800">
                          관리자 기본 보유
                        </span>
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleToggleCreatorGrant(m)}
                          className={`chip-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                            m.can_create_group
                              ? 'border border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-red-50 hover:border-red-200 hover:text-red-700'
                              : 'bg-[#18181b] text-white hover:bg-[#27272a]'
                          }`}
                        >
                          {m.can_create_group ? '개설 권한 보유 중 (회수)' : '그룹 개설 권한 부여'}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-xl border border-black/[0.08] bg-[#fafaf9] p-3.5 text-xs leading-relaxed text-[#3f3f46]">
                별도 회원가입 없이 기기마다 식별되는 환경에서, <strong>개인 복구 코드</strong>를 한 번 정해 두면 다른 PC나 스마트폰으로 옮겨도 내가 참여한 그룹과 비공개 대화를 그대로 이어서 사용할 수 있습니다.
              </div>

              <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-[#18181b]">1. 내 기기 복구 코드 등록 · 변경</h4>
                  {hasRecovery && (
                    <span className="chip-nowrap rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                      등록됨
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="password"
                    value={newRecovery}
                    onChange={(e) => setNewRecovery(e.target.value)}
                    placeholder="나만의 복구 코드 입력 (4~32자)"
                    className="min-w-0 flex-1 rounded-lg border border-black/[0.1] px-3 py-2 text-xs"
                  />
                  <button
                    type="button"
                    disabled={newRecovery.trim().length < 4 || busy}
                    onClick={() => void handleSetRecovery()}
                    className="chip-nowrap rounded-lg bg-[#18181b] px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-40"
                  >
                    코드 저장
                  </button>
                </div>
              </div>

              <div className="space-y-2.5 rounded-xl border border-black/[0.08] p-4">
                <h4 className="text-xs font-semibold text-[#18181b]">2. 다른 기기에서 등록한 내 그룹 불러오기</h4>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="password"
                    value={claimRecovery}
                    onChange={(e) => setClaimRecovery(e.target.value)}
                    placeholder="기존 기기에서 정해둔 복구 코드 입력"
                    className="min-w-0 flex-1 rounded-lg border border-black/[0.1] px-3 py-2 text-xs"
                  />
                  <button
                    type="button"
                    disabled={claimRecovery.trim().length < 4 || busy}
                    onClick={() => void handleClaimRecovery()}
                    className="chip-nowrap rounded-lg bg-[#0f4c81] px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-40"
                  >
                    내 그룹 연결
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
