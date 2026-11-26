export interface UserProfileExtra {
  label: string;
  value: string;
}

export interface UserProfile {
  name: string;
  position: string;
  department: string;
  birthDate: string;
  phone: string;
  address: string;
  email: string;
  recipient: string;
  autoApply: boolean;
  extras: UserProfileExtra[];
}

const STORAGE_KEY = 'mokpo_sarang_user_profile_v1';

export const DEFAULT_PROFILE: UserProfile = {
  name: '',
  position: '',
  department: '',
  birthDate: '',
  phone: '',
  address: '',
  email: '',
  recipient: '목포사랑의교회 당회장 귀하',
  autoApply: true,
  extras: [],
};

export function loadUserProfile(): UserProfile {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PROFILE };
    const parsed = JSON.parse(raw) as Partial<UserProfile>;
    return {
      ...DEFAULT_PROFILE,
      ...parsed,
      extras: Array.isArray(parsed.extras) ? parsed.extras : [],
    };
  } catch {
    return { ...DEFAULT_PROFILE };
  }
}

export function saveUserProfile(profile: UserProfile): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
  } catch {
    // ignore storage quota errors
  }
}

export function hasSavedProfile(profile: UserProfile): boolean {
  return Boolean(
    profile.name.trim() ||
      profile.position.trim() ||
      profile.department.trim() ||
      profile.phone.trim() ||
      profile.birthDate.trim() ||
      profile.address.trim() ||
      profile.extras.some((e) => e.label.trim() && e.value.trim())
  );
}

export function profileToFlatMap(profile: UserProfile): Record<string, string> {
  const out: Record<string, string> = {};
  if (profile.name.trim()) out['성명'] = profile.name.trim();
  if (profile.position.trim()) out['직분'] = profile.position.trim();
  if (profile.department.trim()) out['소속'] = profile.department.trim();
  if (profile.birthDate.trim()) out['생년월일'] = profile.birthDate.trim();
  if (profile.phone.trim()) out['연락처'] = profile.phone.trim();
  if (profile.address.trim()) out['주소'] = profile.address.trim();
  if (profile.email.trim()) out['이메일'] = profile.email.trim();
  if (profile.recipient.trim()) out['수신'] = profile.recipient.trim();
  for (const ex of profile.extras) {
    if (ex.label.trim() && ex.value.trim()) {
      out[ex.label.trim()] = ex.value.trim();
    }
  }
  return out;
}

export function matchProfileToFieldLabel(label: string, profile: UserProfile): string {
  const compact = label.replace(/\s+/g, '').toLowerCase();
  // Check custom extras first for exact/substring match
  for (const ex of profile.extras) {
    const exKey = ex.label.replace(/\s+/g, '').toLowerCase();
    if (exKey && ex.value.trim() && (compact === exKey || compact.includes(exKey) || exKey.includes(compact))) {
      return ex.value.trim();
    }
  }
  if (/성명|이름|신청인|청원인|제출자|지원자|대상자|작성자|보고자/.test(compact)) {
    return profile.name.trim();
  }
  if (/직분|직책|직위|직함/.test(compact)) {
    return profile.position.trim();
  }
  if (/소속|부서|교구|셀|기관|위원회/.test(compact)) {
    return profile.department.trim();
  }
  if (/생년월일|출생|생일/.test(compact)) {
    return profile.birthDate.trim();
  }
  if (/연락처|전화|휴대|핸드폰|폰/.test(compact)) {
    return profile.phone.trim();
  }
  if (/주소|거주지/.test(compact)) {
    return profile.address.trim();
  }
  if (/이메일|메일|email/.test(compact)) {
    return profile.email.trim();
  }
  return '';
}

export function todayKoreanDate(): string {
  const d = new Date();
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
}
