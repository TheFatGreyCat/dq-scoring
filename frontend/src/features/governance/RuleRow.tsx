import { Trash2 } from "lucide-react";
import { useId, type ReactNode } from "react";
import { DIMENSIONS } from "../../api/types";
import { humanize } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { DATA_TYPES, OPERATORS, RULE_TYPES, isTemporal, validateRule, type RuleDraft, type RuleType } from "./ruleForm";
function Cell({ label, error, children, className = "" }: { label: string; error?: string; children: (id: string, errId?: string) => ReactNode; className?: string }) {
  const id = useId();
  const errId = error ? `${id}-err` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="label">{label}</label>
      {children(id, errId)}
      {error && <p id={errId} className="mt-1 text-xs font-medium text-fail">{error}</p>}
    </div>
  );
}

export function RuleRow({
  index,
  rule,
  showErrors,
  columns = [],
  onChange,
  onRemove,
}: {
  index: number;
  rule: RuleDraft;
  showErrors: boolean;
  columns?: string[];
  onChange: (patch: Partial<RuleDraft>) => void;
  onRemove?: () => void;
}) {
  const { t } = useI18n();
  const columnListId = useId();
  const errors = showErrors ? validateRule(rule) : {};
  const forcedAdvisory = rule.rule_type === "SPELLING" || (rule.rule_type === "TEXT_QUALITY" && rule.check === "MOJIBAKE");
  const text = (
    key: keyof RuleDraft,
    label: string,
    props: { mono?: boolean; className?: string; placeholder?: string; inputMode?: "decimal"; list?: string } = {},
  ) => (
    <Cell label={label} error={errors[key]} className={props.className}>
      {(id, errId) => (
        <input
          id={id}
          aria-describedby={errId}
          aria-invalid={!!errors[key]}
          className={`input ${props.mono ? "mono" : ""}`}
          placeholder={props.placeholder}
          inputMode={props.inputMode}
          list={props.list}
          spellCheck={false}
          value={String(rule[key])}
          onChange={(e) => onChange({ [key]: e.target.value })}
        />
      )}
    </Cell>
  );
  const select = (key: keyof RuleDraft, label: string, options: readonly string[], render: (o: string) => string = (o) => o) => (
    <Cell label={label}>
      {(id) => (
        <select id={id} className="input" value={String(rule[key])} onChange={(e) => onChange({ [key]: e.target.value })}>
          {options.map((o) => <option key={o} value={o}>{render(o)}</option>)}
        </select>
      )}
    </Cell>
  );
  const flag = (key: "is_required" | "is_critical" | "is_advisory", label: string, disabled = false) => (
    <label className="inline-flex items-center gap-2 min-h-11 cursor-pointer">
      <input type="checkbox" className="size-5 accent-[var(--action)]" checked={forcedAdvisory ? key === "is_advisory" : rule[key]} disabled={disabled || forcedAdvisory}
        onChange={(e) => onChange({ [key]: e.target.checked })} />
      {label}
    </label>
  );

  return (
    <fieldset className="rounded-card border border-border p-4 space-y-4">
      <legend className="px-2 font-semibold">
        {t("gov.rule.title_num", { index: index + 1 })}
        {rule.rule_code && <span className="mono font-normal text-fg-muted"> · {rule.rule_code}</span>}
      </legend>
      {columns.length > 0 && (
        <datalist id={columnListId}>
          {columns.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {text("rule_code", t("gov.rule.rule_code"), { mono: true, placeholder: "R_COMP_01" })}
        <Cell label={t("gov.rule.rule_type")}>
          {(id) => (
            <select
              id={id}
              className="input"
              value={rule.rule_type}
              onChange={(e) => {
                const type = e.target.value as RuleType;
                onChange({ rule_type: type, dimension: RULE_TYPES[type].dimension, check: type === "JSON_FIELD" ? "NON_NULL" : "REPLACEMENT_CHARACTER" });
              }}
            >
              {Object.entries(RULE_TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          )}
        </Cell>
        {select("dimension", t("gov.rule.dimension"), DIMENSIONS, (d) => {
          const key = `dim.${d}` as "dim.ACCURACY" | "dim.COMPLETENESS" | "dim.CONSISTENCY" | "dim.TIMELINESS" | "dim.VALIDITY" | "dim.UNIQUENESS";
          return t(key) || humanize(d);
        })}
        {text("column", t("gov.rule.target_column"), { mono: true, list: columns.length > 0 ? columnListId : undefined })}
      </div>
      {rule.rule_type !== "NOT_NULL" && rule.rule_type !== "UNIQUE" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {rule.rule_type === "TEXT_QUALITY" && select("check", t("gov.rule.check"), ["REPLACEMENT_CHARACTER", "CONTROL_CHARACTER", "MOJIBAKE", "LENGTH"])}
          {(rule.rule_type === "JSON_FIELD" || rule.rule_type === "JSON_ARRAY") && text("path", t("gov.rule.path"), { mono: true })}
          {rule.rule_type === "JSON_FIELD" && select("check", t("gov.rule.check"), ["NON_NULL", "TYPE", "RANGE", "REGEX", "ALLOWED_VALUES"])}
          {rule.rule_type === "JSON_FIELD" && rule.check === "TYPE" && select("expected_type", t("gov.rule.expected_type"), ["STRING", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"])}
          {(rule.rule_type === "JSON_ARRAY" || (rule.rule_type === "JSON_FIELD" && rule.check === "RANGE") || (rule.rule_type === "TEXT_QUALITY" && rule.check === "LENGTH")) && <>
            {text("min", t("gov.rule.minimum"), { mono: true })}
            {text("max", t("gov.rule.maximum"), { mono: true })}
          </>}
          {rule.rule_type === "JSON_ARRAY" && <label className="inline-flex items-center gap-2 min-h-11"><input type="checkbox" className="size-5" checked={rule.unique_items} onChange={e => onChange({ unique_items: e.target.checked })} />{t("gov.rule.unique_items")}</label>}
          {rule.rule_type === "JSON_FIELD" && rule.check === "REGEX" && text("pattern", t("gov.rule.pattern"), { mono: true })}
          {rule.rule_type === "JSON_FIELD" && rule.check === "ALLOWED_VALUES" && text("allowed", t("gov.rule.allowed_values"))}
          {rule.rule_type === "SPELLING" && <>
            {select("language", t("gov.rule.language"), ["vi", "en", "vi-en"])}
            {text("dictionary_revision", t("gov.rule.dictionary_revision"))}
            <Cell label={t("gov.rule.accepted_terms")}>{id => <textarea id={id} className="input" value={rule.accepted_terms} onChange={e => onChange({ accepted_terms: e.target.value })} />}</Cell>
            <p className="text-sm text-fg-muted sm:col-span-2">{t("gov.rule.spelling_notice")}</p>
          </>}
          {rule.rule_type === "RANGE" && (
            <>
              {text("min", t("gov.rule.minimum"), { mono: true, inputMode: "decimal" })}
              {text("max", t("gov.rule.maximum"), { mono: true, inputMode: "decimal" })}
            </>
          )}
          {rule.rule_type === "ALLOWED_VALUES" && text("allowed", t("gov.rule.allowed_values"), { className: "sm:col-span-2" })}
          {rule.rule_type === "REGEX" && text("pattern", t("gov.rule.pattern"), { mono: true, className: "sm:col-span-2", placeholder: "^[A-Z]{3}$" })}
          {rule.rule_type === "CROSS_FIELD" && (
            <>
              {select("operator", t("gov.rule.operator"), OPERATORS)}
              {text("comparison_column", t("gov.rule.compare_column"), {
                mono: true,
                list: columns.length > 0 ? columnListId : undefined,
              })}
            </>
          )}
          {(rule.rule_type === "TYPE_PARSE" || rule.rule_type === "CROSS_FIELD") && (
            <>
              {select("data_type", t("gov.rule.data_type"), DATA_TYPES)}
              {isTemporal(rule.data_type) && text("format", t("gov.rule.format"), { mono: true })}
            </>
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Cell label={t("gov.rule.weight")} error={errors.weight}>
          {(id, errId) => (
            <input id={id} aria-describedby={errId} aria-invalid={!!errors.weight} className="input mono" inputMode="decimal"
              value={forcedAdvisory ? "0" : rule.weight} disabled={forcedAdvisory} onChange={(e) => onChange({ weight: e.target.value })} />
          )}
        </Cell>
        {text("acceptance_threshold", t("gov.rule.acceptance_threshold"), { mono: true, inputMode: "decimal" })}
        {select("null_policy", t("gov.rule.null_policy"), ["fail", "ignore"], (o) => (o === "fail" ? t("gov.rule.null_fail") : t("gov.rule.null_ignore")))}
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        {flag("is_required", t("gov.rule.required"))}
        {flag("is_critical", t("gov.rule.critical"), rule.is_advisory)}
        {flag("is_advisory", t("gov.rule.advisory"))}
        {onRemove && (
          <button type="button" className="btn-secondary ml-auto" onClick={onRemove}>
            <Trash2 aria-hidden className="size-4" /> {t("gov.rule.remove")}
          </button>
        )}
      </div>
    </fieldset>
  );
}
