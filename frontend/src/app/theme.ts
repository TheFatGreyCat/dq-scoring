// Theme preference is browser-local by design: it carries no tenant data (APPLICATION_UI_DESIGN §4).
export type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "dq-theme";
const listeners = new Set<() => void>();
let persistenceFailed = false;
export const themeSnapshot = () => document.documentElement.dataset.theme === "dark" ? "dark" : "light";
export const preferenceSaveFailed = () => persistenceFailed;
export function subscribeTheme(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }

export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Storage unavailable (private mode / blocked): fall back to the OS preference.
  }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme, persist = false) {
  document.documentElement.dataset.theme = theme;
  persistenceFailed = false;
  if (persist) {
    try { localStorage.setItem(THEME_STORAGE_KEY, theme); }
    catch { persistenceFailed = true; }
  }
  listeners.forEach(listener => listener());
}
