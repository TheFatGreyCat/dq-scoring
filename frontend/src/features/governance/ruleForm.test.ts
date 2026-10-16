import {
  extractTemplatePlaceholders,
  fromRuleInput,
  instantiateTemplateRules,
  mergeAndDedupeRules,
  newRule,
  toRuleInput,
  validateRule,
} from "./ruleForm";

it("serializes a range rule with compiler parameter keys", () => {
  const input = toRuleInput({ ...newRule(), rule_code: "R1", rule_type: "RANGE", dimension: "VALIDITY", column: "fare", min: "0", max: "500" });
  expect(input.rule_type).toBe("DOMAIN_RANGE");
  expect(input.parameters).toEqual({ column: "fare", min_value: 0, max_value: 500 });
  expect(input.contribution_weight).toBe(1);
});


it("disables score and gate for advisory rules while keeping a DB-valid positive weight", () => {
  const input = toRuleInput({ ...newRule(), rule_code: "OUT", column: "x", is_advisory: true, is_critical: true, weight: "5" });
  expect(input).toMatchObject({ score_enabled: false, gate_enabled: false, is_critical: false, is_advisory: true });
  expect(input.contribution_weight).toBeGreaterThan(0);
});

it("keeps an unset acceptance threshold null rather than 0", () => {
  expect(toRuleInput({ ...newRule(), rule_code: "R", column: "c" }).acceptance_threshold).toBeNull();
});

it("rejects incomplete rules per type", () => {
  expect(validateRule(newRule())).toMatchObject({ rule_code: "Required", column: "Required" });
  expect(validateRule({ ...newRule(), rule_code: "R", column: "c", rule_type: "RANGE", min: "9", max: "1" })).toHaveProperty("max");
  expect(validateRule({ ...newRule(), rule_code: "R", column: "c", rule_type: "CROSS_FIELD" })).toHaveProperty("comparison_column");
  expect(validateRule({ ...newRule(), rule_code: "R", column: "c" })).toEqual({});
});

it("deserializes rule input back to a valid draft", () => {
  const draft = fromRuleInput({
    rule_code: "R_TEST",
    dimension: "VALIDITY",
    rule_type: "DOMAIN_RANGE",
    parameters: { column: "amount", min_value: 10, max_value: 100 },
    null_policy: "ignore",
    is_required: true,
    is_critical: false,
    is_advisory: false,
    contribution_weight: 2,
    acceptance_threshold: 95,
  });
  expect(draft.rule_code).toBe("R_TEST");
  expect(draft.rule_type).toBe("RANGE");
  expect(draft.column).toBe("amount");
  expect(draft.min).toBe("10");
  expect(draft.max).toBe("100");
  expect(draft.null_policy).toBe("ignore");
  expect(draft.is_required).toBe(true);
  expect(draft.weight).toBe("2");
  expect(draft.acceptance_threshold).toBe("95");
});

it("round-trips JSON decimal bounds without numeric conversion", () => {
  const parameters = { column: "payload", path: "/amount", check: "RANGE", min: "1234567890.1234567890123456789" };
  const draft = fromRuleInput({ rule_code: "JSON", dimension: "VALIDITY", rule_type: "JSON_FIELD", parameters });
  expect(toRuleInput(draft).parameters).toEqual(parameters);
});

it("forces spelling advisory independently of draft flags", () => {
  const draft = fromRuleInput({ rule_code: "SPELL", dimension: "VALIDITY", rule_type: "SPELLING", parameters: { column: "text", language: "vi-en", dictionary_revision: "synthetic-v1", accepted_terms: ["fintech"] } });
  expect(toRuleInput(draft)).toMatchObject({ is_advisory: true, is_required: false, is_critical: false, score_enabled: false, gate_enabled: false, contribution_weight: 0 });
});

it("extracts placeholders and instantiates template rules with column mapping", () => {
  const rawPayload = [
    {
      rule_code: "nonnull_ts",
      dimension: "COMPLETENESS",
      rule_type: "NON_NULL",
      parameters: { column: "$timestamp" },
    },
    {
      rule_code: "range_amt",
      dimension: "VALIDITY",
      rule_type: "DOMAIN_RANGE",
      parameters: { column: "$amount", min_value: 0 },
    },
  ];
  const placeholders = extractTemplatePlaceholders(rawPayload);
  expect(placeholders).toEqual(["$amount", "$timestamp"]);

  const mapped = instantiateTemplateRules(rawPayload, {
    "$timestamp": "tx_time",
    "$amount": "fare",
  });
  expect(mapped).toHaveLength(2);
  expect(mapped[0].parameters.column).toBe("tx_time");
  expect(mapped[1].parameters.column).toBe("fare");
});

it("merges and dedupes rules while preserving existing controls on duplicates", () => {
  const existing = [
    {
      ...newRule(),
      rule_code: "R_EXISTING",
      column: "old_col",
      null_policy: "ignore" as const,
      weight: "3",
      is_required: true,
      is_critical: true,
    },
  ];

  const incoming = [
    {
      rule_code: "R_EXISTING",
      dimension: "COMPLETENESS" as const,
      rule_type: "NON_NULL",
      parameters: { column: "new_col" },
      null_policy: "fail",
      is_required: false,
      is_critical: false,
      gate_enabled: true,
      score_enabled: true,
      contribution_weight: 1,
      acceptance_threshold: null,
      is_advisory: false,
    },
    {
      rule_code: "R_NEW",
      dimension: "VALIDITY" as const,
      rule_type: "DOMAIN_RANGE",
      parameters: { column: "fare", min_value: 0 },
      null_policy: "fail",
      is_required: false,
      is_critical: false,
      gate_enabled: true,
      score_enabled: true,
      contribution_weight: 1,
      acceptance_threshold: null,
      is_advisory: false,
    },
  ];

  const merged = mergeAndDedupeRules(existing, incoming);
  expect(merged).toHaveLength(2);
  const updated = merged.find((r) => r.rule_code === "R_EXISTING");
  expect(updated?.column).toBe("new_col");
  // Preserved controls:
  expect(updated?.null_policy).toBe("ignore");
  expect(updated?.weight).toBe("3");
  expect(updated?.is_required).toBe(true);
  expect(updated?.is_critical).toBe(true);
});
