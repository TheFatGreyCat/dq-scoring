import type { Dimension, QualityRuleInput } from "../../api/types";

/**
 * UI rule kinds. `apiType` is the canonical value allowed by the quality_rules
 * CHECK constraint (001_initial_schema.sql); range, allowed-values and regex
 * all compile as DOMAIN_RANGE, selected by parameter keys in sql_rule_compiler.py.
 */
export const RULE_TYPES = {
  NOT_NULL: { label: "Not null", dimension: "COMPLETENESS", apiType: "NON_NULL" },
  TYPE_PARSE: { label: "Type parse", dimension: "VALIDITY", apiType: "TYPE_PARSE" },
  RANGE: { label: "Numeric range", dimension: "VALIDITY", apiType: "DOMAIN_RANGE" },
  ALLOWED_VALUES: { label: "Allowed values", dimension: "VALIDITY", apiType: "DOMAIN_RANGE" },
  REGEX: { label: "Pattern (regex)", dimension: "VALIDITY", apiType: "DOMAIN_RANGE" },
  CROSS_FIELD: { label: "Cross-field comparison", dimension: "CONSISTENCY", apiType: "CROSS_FIELD" },
  UNIQUE: { label: "Unique", dimension: "UNIQUENESS", apiType: "UNIQUENESS" },
  TEXT_QUALITY: { label: "Text quality", dimension: "VALIDITY", apiType: "TEXT_QUALITY" },
  SPELLING: { label: "Dictionary membership (advisory)", dimension: "VALIDITY", apiType: "SPELLING" },
  JSON_FIELD: { label: "JSON field", dimension: "VALIDITY", apiType: "JSON_FIELD" },
  JSON_ARRAY: { label: "JSON array", dimension: "VALIDITY", apiType: "JSON_ARRAY" },
} as const satisfies Record<string, { label: string; dimension: Dimension; apiType: string }>;

export type RuleType = keyof typeof RULE_TYPES;

export const DATA_TYPES = ["DOUBLE", "INTEGER", "DATE", "TIMESTAMP"];
export const OPERATORS = [">=", ">", "<=", "<", "==", "!="];
export const DEFAULT_TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss";

export interface RuleDraft {
  key: number;
  rule_code: string;
  dimension: Dimension;
  rule_type: RuleType;
  column: string;
  min: string;
  max: string;
  allowed: string;
  pattern: string;
  data_type: string;
  format: string;
  comparison_column: string;
  operator: string;
  null_policy: "fail" | "ignore";
  is_required: boolean;
  is_critical: boolean;
  is_advisory: boolean;
  weight: string;
  acceptance_threshold: string;
  check: string;
  path: string;
  language: string;
  dictionary_revision: string;
  accepted_terms: string;
  expected_type: string;
  unique_items: boolean;
}

let nextKey = 0;

export function newRule(): RuleDraft {
  return {
    key: nextKey++,
    rule_code: "",
    dimension: "COMPLETENESS",
    rule_type: "NOT_NULL",
    column: "",
    min: "",
    max: "",
    allowed: "",
    pattern: "",
    data_type: "DOUBLE",
    format: DEFAULT_TIMESTAMP_FORMAT,
    comparison_column: "",
    operator: ">=",
    null_policy: "fail",
    is_required: false,
    is_critical: false,
    is_advisory: false,
    weight: "1",
    acceptance_threshold: "",
    check: "REPLACEMENT_CHARACTER",
    path: "",
    language: "vi-en",
    dictionary_revision: "",
    accepted_terms: "",
    expected_type: "STRING",
    unique_items: false,
  };
}

const isNumber = (v: string) => v.trim() !== "" && Number.isFinite(Number(v));
export const isTemporal = (dataType: string) => dataType === "DATE" || dataType === "TIMESTAMP";

/** Field-level problems for one rule; empty when the rule can be submitted. */
export function validateRule(r: RuleDraft): Partial<Record<keyof RuleDraft, string>> {
  const errors: Partial<Record<keyof RuleDraft, string>> = {};
  if (!r.rule_code.trim()) errors.rule_code = "Required";
  if (!r.column.trim()) errors.column = "Required";
  if (r.rule_type === "RANGE") {
    if (!isNumber(r.min) && !isNumber(r.max)) errors.min = "Set a minimum, a maximum, or both";
    if (isNumber(r.min) && isNumber(r.max) && Number(r.min) > Number(r.max)) errors.max = "Must be ≥ minimum";
  }
  if (r.rule_type === "ALLOWED_VALUES" && !r.allowed.split(",").some((v) => v.trim())) errors.allowed = "List at least one value";
  if (r.rule_type === "REGEX" && !r.pattern) errors.pattern = "Required";
  if (r.rule_type === "CROSS_FIELD" && !r.comparison_column.trim()) errors.comparison_column = "Required";
  if (r.rule_type === "JSON_FIELD" || r.rule_type === "JSON_ARRAY") {
    if ((r.path !== "" && !r.path.startsWith("/")) || /~(?![01])/.test(r.path)) errors.path = "Invalid JSON Pointer";
  }
  if (r.rule_type === "SPELLING" && !r.dictionary_revision.trim()) errors.dictionary_revision = "Required";
  if (r.rule_type === "JSON_ARRAY") {
    if (r.min === "" && r.max === "" && !r.unique_items) errors.min = "Set a bound or unique items";
    if (r.min !== "" && (!/^\d+$/.test(r.min))) errors.min = "Nonnegative integer required";
    if (r.max !== "" && (!/^\d+$/.test(r.max))) errors.max = "Nonnegative integer required";
  }
  if ((r.rule_type === "TEXT_QUALITY" && r.check === "LENGTH") || (r.rule_type === "JSON_FIELD" && r.check === "RANGE")) {
    if (r.min === "" && r.max === "") errors.min = "Set a minimum or maximum";
  }
  if (r.rule_type === "JSON_FIELD" && r.check === "REGEX" && !r.pattern) errors.pattern = "Required";
  if (r.rule_type === "JSON_FIELD" && r.check === "ALLOWED_VALUES" && !r.allowed.trim()) errors.allowed = "Required";
  if (r.rule_type !== "SPELLING" && !(r.rule_type === "TEXT_QUALITY" && r.check === "MOJIBAKE") && !(isNumber(r.weight) && Number(r.weight) >= 0)) errors.weight = "Must be ≥ 0";
  if (r.acceptance_threshold !== "" && !(isNumber(r.acceptance_threshold) && +r.acceptance_threshold >= 0 && +r.acceptance_threshold <= 100))
    errors.acceptance_threshold = "0–100";
  return errors;
}

function parameters(r: RuleDraft): Record<string, unknown> {
  const params: Record<string, unknown> = { column: r.column.trim() };
  switch (r.rule_type) {
    case "TEXT_QUALITY":
      params.check = r.check;
      if (r.check === "LENGTH") {
        if (r.min !== "") params.min_length = Number(r.min);
        if (r.max !== "") params.max_length = Number(r.max);
      }
      break;
    case "SPELLING":
      params.language = r.language;
      params.dictionary_revision = r.dictionary_revision;
      params.accepted_terms = r.accepted_terms.split("\n").map(v => v.trim()).filter(Boolean);
      break;
    case "JSON_FIELD":
      params.path = r.path;
      params.check = r.check;
      if (r.check === "TYPE") params.expected_type = r.expected_type;
      if (r.check === "RANGE") {
        if (r.min !== "") params.min = r.min;
        if (r.max !== "") params.max = r.max;
      }
      if (r.check === "REGEX") params.pattern = r.pattern;
      if (r.check === "ALLOWED_VALUES") params.allowed_values = r.allowed.split(",").map(v => v.trim()).filter(Boolean);
      break;
    case "JSON_ARRAY":
      params.path = r.path;
      if (r.min !== "") params.min_items = Number(r.min);
      if (r.max !== "") params.max_items = Number(r.max);
      params.unique_items = r.unique_items;
      break;
    case "TYPE_PARSE":
      params.data_type = r.data_type;
      if (isTemporal(r.data_type)) params.format = r.format;
      break;
    case "RANGE":
      if (isNumber(r.min)) params.min_value = Number(r.min);
      if (isNumber(r.max)) params.max_value = Number(r.max);
      break;
    case "ALLOWED_VALUES":
      params.allowed_values = r.allowed.split(",").map((v) => v.trim()).filter(Boolean);
      break;
    case "REGEX":
      params.pattern = r.pattern;
      break;
    case "CROSS_FIELD":
      params.comparison_column = r.comparison_column.trim();
      params.operator = r.operator;
      params.data_type = r.data_type;
      if (isTemporal(r.data_type)) params.format = r.format;
      break;
  }
  return params;
}

/**
 * Advisory rules are informational only: score_enabled and gate_enabled are off, so they
 * contribute nothing to score or gate (AGENTS.md "Advisory Outlier Isolation"). The stored
 * weight stays positive because quality_rules enforces CHECK (weight > 0).
 */
export function toRuleInput(r: RuleDraft): QualityRuleInput {
  const forcedAdvisory = r.rule_type === "SPELLING" || (r.rule_type === "TEXT_QUALITY" && r.check === "MOJIBAKE");
  const advisory = r.is_advisory || forcedAdvisory;
  return {
    rule_code: r.rule_code.trim(),
    dimension: r.dimension,
    rule_type: RULE_TYPES[r.rule_type].apiType,
    parameters: parameters(r),
    null_policy: r.null_policy,
    is_required: !advisory && r.is_required,
    is_critical: !advisory && r.is_critical,
    gate_enabled: !advisory,
    score_enabled: !advisory,
    contribution_weight: forcedAdvisory ? 0 : Number(r.weight),
    acceptance_threshold: r.acceptance_threshold === "" ? null : Number(r.acceptance_threshold),
    is_advisory: advisory,
  };
}

export function fromRuleInput(input: Partial<QualityRuleInput>): RuleDraft {
  const params = (input.parameters ?? {}) as Record<string, unknown>;
  const rawType = input.rule_type ?? "NON_NULL";

  let ruleType: RuleType = "NOT_NULL";
  if (rawType === "NON_NULL") ruleType = "NOT_NULL";
  else if (rawType === "UNIQUENESS") ruleType = "UNIQUE";
  else if (rawType === "TYPE_PARSE") ruleType = "TYPE_PARSE";
  else if (rawType === "CROSS_FIELD") ruleType = "CROSS_FIELD";
  else if (["TEXT_QUALITY", "SPELLING", "JSON_FIELD", "JSON_ARRAY"].includes(rawType)) ruleType = rawType as RuleType;
  else if (rawType === "DOMAIN_RANGE") {
    if (params.pattern) ruleType = "REGEX";
    else if (Array.isArray(params.allowed_values)) ruleType = "ALLOWED_VALUES";
    else ruleType = "RANGE";
  }

  const col = String(params.column ?? params.target_column ?? "");
  const minVal = params.min_value !== undefined && params.min_value !== null ? String(params.min_value) : "";
  const maxVal = params.max_value !== undefined && params.max_value !== null ? String(params.max_value) : "";
  const allowed = Array.isArray(params.allowed_values)
    ? params.allowed_values.join(", ")
    : typeof params.allowed_values === "string"
      ? params.allowed_values
      : "";
  const pattern = String(params.pattern ?? "");
  const dataType = String(params.data_type ?? "DOUBLE");
  const format = String(params.format ?? DEFAULT_TIMESTAMP_FORMAT);
  const compCol = String(params.comparison_column ?? "");
  const op = String(params.operator ?? ">=");

  return {
    key: nextKey++,
    rule_code: String(input.rule_code ?? ""),
    dimension: (input.dimension as Dimension) ?? RULE_TYPES[ruleType].dimension,
    rule_type: ruleType,
    check: String(params.check ?? (ruleType === "JSON_FIELD" ? "NON_NULL" : "REPLACEMENT_CHARACTER")),
    path: String(params.path ?? ""),
    language: String(params.language ?? "vi-en"),
    dictionary_revision: String(params.dictionary_revision ?? ""),
    accepted_terms: Array.isArray(params.accepted_terms) ? params.accepted_terms.join("\n") : "",
    expected_type: String(params.expected_type ?? "STRING"),
    unique_items: Boolean(params.unique_items),
    column: col,
    min: String(params.min ?? params.min_items ?? params.min_length ?? minVal),
    max: String(params.max ?? params.max_items ?? params.max_length ?? maxVal),
    allowed,
    pattern,
    data_type: dataType,
    format,
    comparison_column: compCol,
    operator: op,
    null_policy: input.null_policy === "ignore" ? "ignore" : "fail",
    is_required: Boolean(input.is_required),
    is_critical: Boolean(input.is_critical),
    is_advisory: Boolean(input.is_advisory),
    weight: input.contribution_weight !== undefined ? String(input.contribution_weight) : "1",
    acceptance_threshold:
      input.acceptance_threshold !== null && input.acceptance_threshold !== undefined
        ? String(input.acceptance_threshold)
        : "",
  };
}

export function normalizeRulesPayload(payload: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(payload)) return payload as Array<Record<string, unknown>>;
  if (payload && typeof payload === "object" && "rules" in payload) {
    const candidate = payload.rules;
    if (Array.isArray(candidate)) {
      return candidate as Array<Record<string, unknown>>;
    }
  }
  return [];
}

export function extractTemplatePlaceholders(rulesPayload: Array<Record<string, unknown>>): string[] {
  const set = new Set<string>();
  for (const r of rulesPayload) {
    const params = (r.parameters ?? {}) as Record<string, unknown>;
    for (const val of Object.values(params)) {
      if (typeof val === "string" && val.startsWith("$")) {
        set.add(val);
      }
    }
  }
  return Array.from(set).sort();
}

export function instantiateTemplateRules(
  rulesPayload: Array<Record<string, unknown>>,
  mapping: Record<string, string>,
): QualityRuleInput[] {
  return rulesPayload.map((r, idx) => {
    const params: Record<string, unknown> = {};
    const origParams = (r.parameters ?? {}) as Record<string, unknown>;
    for (const [k, v] of Object.entries(origParams)) {
      if (typeof v === "string" && v.startsWith("$")) {
        params[k] = mapping[v] ?? v;
      } else {
        params[k] = v;
      }
    }

    const ruleCode = String(r.rule_code || `template_rule_${idx + 1}`);
    const dimension = (r.dimension as Dimension) || "COMPLETENESS";
    const ruleType = String(r.rule_type || "NON_NULL");
    const isAdvisory = Boolean(r.is_advisory);

    return {
      rule_code: ruleCode,
      dimension,
      rule_type: ruleType,
      parameters: params,
      null_policy: String(r.null_policy || "fail"),
      is_required: Boolean(r.is_required),
      is_critical: !isAdvisory && Boolean(r.is_critical),
      gate_enabled: !isAdvisory,
      score_enabled: !isAdvisory,
      contribution_weight: typeof r.contribution_weight === "number" ? r.contribution_weight : 1,
      acceptance_threshold: typeof r.acceptance_threshold === "number" ? r.acceptance_threshold : null,
      is_advisory: isAdvisory,
    };
  });
}

export function mergeAndDedupeRules(existing: RuleDraft[], incoming: QualityRuleInput[]): RuleDraft[] {
  const result = [...existing];
  const isSingleEmpty =
    result.length === 1 &&
    !result[0].rule_code.trim() &&
    !result[0].column.trim();

  if (isSingleEmpty) {
    result.pop();
  }

  for (const inc of incoming) {
    const code = inc.rule_code.trim();
    const existingIdx = result.findIndex((r) => r.rule_code.trim() === code);
    const converted = fromRuleInput(inc);

    if (existingIdx >= 0) {
      const curr = result[existingIdx];
      result[existingIdx] = {
        ...converted,
        key: curr.key,
        null_policy: curr.null_policy,
        weight: curr.weight,
        is_required: curr.is_required,
        is_critical: curr.is_critical,
        is_advisory: curr.is_advisory,
        acceptance_threshold: curr.acceptance_threshold,
      };
    } else {
      result.push(converted);
    }
  }

  return result.length > 0 ? result : [newRule()];
}
