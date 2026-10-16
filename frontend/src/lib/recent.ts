import { useSyncExternalStore } from "react";

/*
 * IDs created or opened during this browser session, held in memory only.
 * Stand-in for list APIs that do not exist yet (APPLICATION_UI_DESIGN §5 P0);
 * never presented as a full inventory. Cleared on sign-out.
 */
export type RecentKind = "asset" | "snapshot" | "ruleset" | "policy" | "run" | "assessment";

export interface RecentItem {
  kind: RecentKind;
  id: string;
  label: string;
  status?: string;
}

const MAX_RECENT_ITEMS = 50;

let items: RecentItem[] = [];
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((l) => l());

export const recent = {
  remember(item: RecentItem) {
    items = [item, ...items.filter((i) => !(i.kind === item.kind && i.id === item.id))].slice(0, MAX_RECENT_ITEMS);
    emit();
  },
  clear() {
    items = [];
    emit();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function useRecent(kind?: RecentKind): RecentItem[] {
  const all = useSyncExternalStore(recent.subscribe, () => items);
  return kind ? all.filter((i) => i.kind === kind) : all;
}
