import { ChevronDown, RotateCcw } from "lucide-react";
import { Fragment, useState } from "react";
import type { MeasurementStatus, RuleResult } from "../../api/types";
import { DIMENSIONS } from "../../api/types";
import { MeasurementBadge } from "../../components/StatusBadge";
import { formatCount, formatScore } from "../../lib/format";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { SurfaceTranslationKey } from "../../lib/surfaceTranslations";

type RuleKey = TranslationKey | SurfaceTranslationKey;
function Flags({ r }: { r: RuleResult }) {
  const { t: rawT } = useI18n();
  const t = rawT as (key: RuleKey) => string;
  const flags = [
    r.is_required && { label: t("rules.flag_required"), critical: false },
    r.is_critical && { label: t("rules.flag_critical"), critical: true },
    r.is_advisory && { label: t("rules.flag_advisory"), critical: false },
  ].filter(Boolean) as { label: string; critical: boolean }[];

  if (flags.length === 0) return <span className="text-fg-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {flags.map((f) => (
        <span
          key={f.label}
          className={`rounded px-1.5 py-0.5 text-xs font-medium ${
            f.critical ? "bg-fail-bg text-fail" : "bg-surface-muted text-fg"
          }`}
        >
          {f.label}
        </span>
      ))}
    </span>
  );
}

const COUNT_KEYS: [keyof RuleResult, RuleKey][] = [
  ["passed_count", "rules.count_passed"],
  ["failed_count", "rules.count_failed"],
  ["missing_count", "rules.count_missing"],
  ["miscast_count", "rules.count_miscast"],
  ["not_applicable_count", "rules.count_not_applicable"],
];

function cellText(value: unknown): string {
  if (value == null) return "null";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Rule drill-down: partition counts, sanitized error, bounded redacted evidence as plain text. */
export function RuleDetail({ r }: { r: RuleResult }) {
  const { lang, t: rawT } = useI18n();
  const t = rawT as (key: RuleKey, params?: Record<string, string | number>) => string;
  const sum = COUNT_KEYS.reduce((acc, [k]) => acc + (r[k] as number), 0);
  const evidence = r.evidence_samples ?? [];
  const evidenceKeys = [...new Set(evidence.flatMap((row) => Object.keys(row)))];
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {COUNT_KEYS.map(([k, labelKey]) => (
          <div key={k} className="rounded-control bg-surface-muted p-2">
            <dt className="text-xs text-fg-muted">{t(labelKey)}</dt>
            <dd className="mono">{formatCount(r[k] as number, lang)}</dd>
          </div>
        ))}
        <div className="rounded-control border border-border p-2">
          <dt className="text-xs text-fg-muted">{t("rules.total_observed")}</dt>
          <dd className="mono font-semibold">{formatCount(r.total_observed, lang)}</dd>
        </div>
      </dl>
      {sum !== r.total_observed && (
        <p className="text-warn font-medium">
          {t("rules.count_reconcile_warn", {
            sum: formatCount(sum, lang),
            total: formatCount(r.total_observed, lang),
          })}
        </p>
      )}
      <p className="text-fg-muted">
        {t("rules.meta_info", {
          type: r.rule_type,
          weight: r.weight,
          violations: formatCount(r.violations_count, lang),
        })}
      </p>
      {r.error_message && (
        <p className="rounded-control bg-error-bg p-3 text-error whitespace-pre-wrap break-words">{r.error_message}</p>
      )}
      {evidence.length > 0 && (
        <div>
          <p className="font-medium mb-1">{t("rules.evidence_title", { count: evidence.length })}</p>
          <div className="overflow-x-auto rounded-control border border-border">
            <table className="w-full text-xs mono">
              <thead className="bg-surface-muted">
                <tr>{evidenceKeys.map((k) => <th key={k} scope="col" className="px-2 py-1.5 text-left font-medium">{k}</th>)}</tr>
              </thead>
              <tbody>
                {evidence.map((row, i) => (
                  <tr key={i} className="border-t border-border">
                    {evidenceKeys.map((k) => <td key={k} className="px-2 py-1.5 whitespace-nowrap">{cellText(row[k])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** Advisory signals have no rule_id; rule_code is unique per result (e.g. OUTLIER_IQR_<column>). */
const rowKey = (r: RuleResult) => r.rule_id ?? r.rule_code;

const MEASUREMENT_STATUSES: MeasurementStatus[] = [
  "MEASURED",
  "NOT_APPLICABLE",
  "NOT_MEASURABLE",
  "FAILED_TO_MEASURE",
  "INSUFFICIENT_DATA",
  "SKIPPED_BY_BUDGET",
];

export function RuleTable({ rules }: { rules: RuleResult[] }) {
  const { lang, t: rawT } = useI18n();
  const t = rawT as (key: RuleKey, params?: Record<string, string | number>) => string;
  const [dimension, setDimension] = useState("ALL");
  const [targetColumn, setTargetColumn] = useState("ALL");
  const [measurementStatus, setMeasurementStatus] = useState("ALL");
  const [flag, setFlag] = useState<"ALL" | "REQUIRED" | "CRITICAL" | "ADVISORY">("ALL");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const columns = [...new Set(rules.map((r) => r.target_column).filter(Boolean))].sort();

  const shown = rules.filter((r) => {
    if (dimension !== "ALL" && r.dimension.toUpperCase() !== dimension.toUpperCase()) return false;
    if (targetColumn !== "ALL" && r.target_column !== targetColumn) return false;
    if (measurementStatus !== "ALL" && r.measurement_status !== measurementStatus) return false;
    if (flag === "REQUIRED" && !r.is_required) return false;
    if (flag === "CRITICAL" && !r.is_critical) return false;
    if (flag === "ADVISORY" && !r.is_advisory) return false;
    if (q.trim() && !r.rule_code.toLowerCase().includes(q.trim().toLowerCase())) return false;
    return true;
  });

  const resetFilters = () => {
    setDimension("ALL");
    setTargetColumn("ALL");
    setMeasurementStatus("ALL");
    setFlag("ALL");
    setQ("");
  };

  return (
    <section aria-labelledby="rules" className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div className="space-y-0.5">
          <h2 id="rules" className="text-lg font-semibold">{t("rules.title")}</h2>
          <p className="text-xs text-fg-muted">
            {t("rules.showing_of_total", { shown: shown.length, total: rules.length })}
          </p>
        </div>
        <button
          type="button"
          onClick={resetFilters}
          className="btn-secondary text-xs flex items-center gap-1.5 px-2.5 py-1"
        >
          <RotateCcw className="size-3.5" />
          {t("rules.reset_filters")}
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 text-sm">
        <div>
          <label className="block text-xs text-fg-muted mb-1">{t("rules.col_rule")}</label>
          <input
            type="search"
            className="input text-xs"
            aria-label={t("rules.col_rule")}
            placeholder={t("rules.search_placeholder")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs text-fg-muted mb-1">{t("rules.filter_dimension")}</label>
          <select aria-label={t("rules.filter_dimension")} className="input text-xs" value={dimension} onChange={(e) => setDimension(e.target.value)}>
            <option value="ALL">{t("common.all")}</option>
            {DIMENSIONS.map((d) => (
              <option key={d} value={d}>
                {t(`dim.${d}`)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-fg-muted mb-1">{t("rules.filter_column")}</label>
          <select aria-label={t("rules.filter_column")} className="input text-xs mono" value={targetColumn} onChange={(e) => setTargetColumn(e.target.value)}>
            <option value="ALL">{t("common.all")}</option>
            {columns.map((col) => (
              <option key={col} value={col}>
                {col}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-fg-muted mb-1">{t("rules.filter_status")}</label>
          <select aria-label={t("rules.filter_status")} className="input text-xs" value={measurementStatus} onChange={(e) => setMeasurementStatus(e.target.value)}>
            <option value="ALL">{t("common.all")}</option>
            {MEASUREMENT_STATUSES.map((st) => (
              <option key={st} value={st}>
                {t(`measurement.${st}`)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-fg-muted mb-1">{t("rules.filter_flag")}</label>
          <select
            aria-label={t("rules.filter_flag")}
            className="input text-xs"
            value={flag}
            onChange={(e) => setFlag(e.target.value as "ALL" | "REQUIRED" | "CRITICAL" | "ADVISORY")}
          >
            <option value="ALL">{t("rules.flag_all")}</option>
            <option value="REQUIRED">{t("rules.flag_required")}</option>
            <option value="CRITICAL">{t("rules.flag_critical")}</option>
            <option value="ADVISORY">{t("rules.flag_advisory")}</option>
          </select>
        </div>
      </div>

      {/* Wide screens: data table with expandable rows. */}
      <table className="hidden md:table w-full text-sm">
        <thead>
          <tr className="text-left text-fg-muted border-b border-border">
            <th scope="col" className="py-2 font-medium">{t("rules.col_rule")}</th>
            <th scope="col" className="py-2 font-medium">{t("rules.col_dimension")}</th>
            <th scope="col" className="py-2 font-medium">{t("rules.col_column")}</th>
            <th scope="col" className="py-2 font-medium">{t("rules.col_status")}</th>
            <th scope="col" className="py-2 font-medium text-right">{t("rules.col_score")}</th>
            <th scope="col" className="py-2 font-medium text-right">{t("rules.col_violations")}</th>
            <th scope="col" className="py-2 font-medium">{t("rules.col_flags")}</th>
            <th scope="col"><span className="sr-only">{t("rules.col_details")}</span></th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const key = rowKey(r);
            const expanded = open === key;
            return (
              <Fragment key={key}>
                <tr className="border-b border-border align-middle">
                  <td className="py-2 mono">{r.rule_code}</td>
                  <td className="py-2">{t(`dim.${r.dimension}` as TranslationKey)}</td>
                  <td className="py-2 mono">{r.target_column}</td>
                  <td className="py-2"><MeasurementBadge status={r.measurement_status} /></td>
                  <td className="py-2 mono text-right">{formatScore(r.computed_score)}</td>
                  <td className="py-2 mono text-right">{formatCount(r.violations_count, lang)}</td>
                  <td className="py-2"><Flags r={r} /></td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      className="btn-secondary min-h-9 px-2"
                      aria-expanded={expanded}
                      aria-label={expanded ? t("rules.hide_details", { code: r.rule_code }) : t("rules.show_details", { code: r.rule_code })}
                      onClick={() => setOpen(expanded ? null : key)}
                    >
                      <ChevronDown aria-hidden className={`size-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
                    </button>
                  </td>
                </tr>
                {expanded && (
                  <tr className="border-b border-border bg-surface-muted/50">
                    <td colSpan={8} className="p-4"><RuleDetail r={r} /></td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>

      {/* Narrow screens: labelled row summaries. */}
      <ul className="md:hidden space-y-3">
        {shown.map((r) => (
          <li key={rowKey(r)}>
            <details className="rounded-control border border-border p-3 group">
              <summary className="cursor-pointer list-none space-y-2 min-h-11">
                <div className="flex items-center justify-between gap-2">
                  <span className="mono font-medium">{r.rule_code}</span>
                  <MeasurementBadge status={r.measurement_status} />
                </div>
                <dl className="grid grid-cols-2 gap-1 text-xs">
                  <dt className="text-fg-muted">{t("rules.col_dimension")}</dt><dd>{t(`dim.${r.dimension}` as TranslationKey)}</dd>
                  <dt className="text-fg-muted">{t("rules.col_column")}</dt><dd className="mono">{r.target_column}</dd>
                  <dt className="text-fg-muted">{t("rules.col_score")}</dt><dd className="mono">{formatScore(r.computed_score)}</dd>
                  <dt className="text-fg-muted">{t("rules.col_violations")}</dt><dd className="mono">{formatCount(r.violations_count, lang)}</dd>
                </dl>
                <Flags r={r} />
              </summary>
              <div className="mt-3 border-t border-border pt-3"><RuleDetail r={r} /></div>
            </details>
          </li>
        ))}
      </ul>
      {shown.length === 0 && <p className="text-sm text-fg-muted">{t("rules.no_matching_rules")}</p>}
    </section>
  );
}
