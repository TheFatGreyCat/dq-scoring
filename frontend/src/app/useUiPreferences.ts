import { useSyncExternalStore } from "react";
import { applyTheme, preferenceSaveFailed, subscribeTheme, themeSnapshot, type Theme } from "./theme";

const key = "dq-sidebar-collapsed";
let collapsed = false;
let saveFailed = false;
try { collapsed = localStorage.getItem(key) === "true"; } catch { /* tab-local fallback */ }
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
const snapshot = () => collapsed;
const failedSnapshot = () => saveFailed;
function setCollapsed(value: boolean) {
  collapsed = value;
  saveFailed = false;
  try { localStorage.setItem(key, String(value)); } catch { saveFailed = true; }
  listeners.forEach(listener => listener());
}
export function useUiPreferences() {
  const theme = useSyncExternalStore(subscribeTheme, themeSnapshot);
  const isCollapsed = useSyncExternalStore(subscribe, snapshot);
  const failed = useSyncExternalStore(subscribe, failedSnapshot);
  const themeFailed = useSyncExternalStore(subscribeTheme, preferenceSaveFailed);
  return {theme, collapsed: isCollapsed, saveFailed: failed || themeFailed, setCollapsed, setTheme: (value: Theme) => applyTheme(value, true)};
}
