// Display-only formatting. Values are never rounded before this point
// (DQ_SCORING_THEORY §17); null stays null and renders as an em dash.

export const EMPTY = "—";

const DISPLAY_DECIMALS = 2;

export function formatScore(value: number | null | undefined): string {
  return value == null ? EMPTY : value.toFixed(DISPLAY_DECIMALS);
}

export function formatRatio(ratio: number | null | undefined): string {
  return ratio == null ? EMPTY : `${(ratio * 100).toFixed(1)}%`;
}

const LOCALE_MAP: Record<string, string> = {
  vi: "vi-VN",
  en: "en-US",
  "vi-VN": "vi-VN",
  "en-US": "en-US",
};

export function resolveLocale(lang?: string): string {
  if (lang && LOCALE_MAP[lang]) return LOCALE_MAP[lang];
  if (typeof document !== "undefined" && document.documentElement.lang) {
    return LOCALE_MAP[document.documentElement.lang] ?? "en-US";
  }
  return "en-US";
}

export function formatCount(value: number, lang?: string): string {
  return new Intl.NumberFormat(resolveLocale(lang)).format(value);
}

/** Local time for reading, with the canonical UTC value available as a tooltip. */
export function formatTimestamp(iso: string | null | undefined, lang?: string): { local: string; utc: string } {
  if (!iso) return { local: EMPTY, utc: "" };
  const date = new Date(iso);
  const locale = resolveLocale(lang);
  return {
    local: new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "medium" }).format(date),
    utc: date.toISOString(),
  };
}

export function humanize(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase().replaceAll("_", " ");
}
