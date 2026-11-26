export type ThemeMode = 'light' | 'dark' | 'system';

const THEME_KEY = 'church_search_theme_mode';

export function loadThemeMode(): ThemeMode {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    // ignore
  }
  return 'light';
}

export function resolveIsDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true;
  if (mode === 'light') return false;
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  return false;
}

export function applyThemeMode(mode: ThemeMode): boolean {
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch {
    // ignore
  }
  const dark = resolveIsDark(mode);
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#141416' : '#18181b');
  }
  return dark;
}
