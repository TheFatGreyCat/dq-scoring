"""Profile-based suggestions (SAMPLE or FULL); never infer business constraints from observations."""

from __future__ import annotations

import re

from dq_scoring.common.llm_context import parse_spec, profile_scope


def recommend_rules(
    schema: dict, profile: dict, domain: str, priorities: tuple[str, ...], templates: list[dict], confirmed: dict[str, str] | None = None,
) -> dict:
    confirmed = confirmed or {}
    stats = {column["name"]: column for column in profile.get("columns", [])}
    scope = profile_scope(profile)
    prefix = "FULL" if scope["mode"] == "FULL" else "SAMPLE"
    rules = []
    for index, column in enumerate(schema.get("columns", [])):
        name = column["name"] if isinstance(column, dict) else column
        stat = stats.get(name, {})
        nonnull = stat.get("non_null_count", 0)
        candidates = []
        if "COMPLETENESS" in priorities:
            candidates.append(("COMPLETENESS", "NON_NULL", {"column": name}, f"{prefix}_NULL_STATISTICS"))
        spec = parse_spec(stat)
        parsed = stat.get("parse_success_count")
        if "VALIDITY" in priorities and spec and nonnull and parsed is not None and parsed / nonnull >= .95:
            params = {"column": name, "data_type": spec[0]}
            if spec[1]:
                params["format"] = spec[1]
            candidates.append(("VALIDITY", "TYPE_PARSE", params, f"{prefix}_PARSE_SUCCESS"))
        tokens = re.split(r"[^a-z0-9]+", name.casefold())
        # A user-confirmed label overrides the name hint; unconfirmed columns keep the existing heuristic.
        identifier = confirmed[name] == "IDENTIFIER" if name in confirmed else "id" in tokens
        if "UNIQUENESS" in priorities and identifier and nonnull and stat.get("distinct_count") is not None and stat["distinct_count"] == nonnull:
            candidates.append(("UNIQUENESS", "UNIQUENESS", {"column": name}, f"{prefix}_UNIQUENESS_NOT_PROOF"))
        for dimension, rule_type, params, reason in candidates:
            rules.append({"rule": {
                "rule_code": f"suggested_{index}_{rule_type.lower()}", "dimension": dimension,
                "rule_type": rule_type, "parameters": params, "null_policy": "fail",
                "is_required": False, "is_critical": False, "gate_enabled": True,
                "score_enabled": True, "is_advisory": False, "contribution_weight": 1,
            }, "reason_code": reason, "reason_params": {"column": name, "null_count": stat.get("null_count", 0)},
            "semantic": confirmed.get(name), **_provenance(scope)})
    rules.sort(key=lambda item: (item["rule"]["dimension"], item["reason_params"]["column"], item["rule"]["rule_type"]))
    columns = {str(c["name"] if isinstance(c, dict) else c).casefold().replace(" ", "_") for c in schema.get("columns", [])}
    ruleset_templates, policy_templates = [], []
    for template in templates:
        if template.get("domain") not in (domain, "GENERAL"):
            continue
        if "rules_payload" not in template:
            policy_templates.append({"template_id": template["template_id"], "reason_code": "DOMAIN_POLICY_REVIEW_REQUIRED"})
            continue
        payload = template["rules_payload"]
        if isinstance(payload, dict):
            payload = payload.get("rules", [])
        placeholders = sorted({value[1:] for rule in payload for value in rule.get("parameters", {}).values() if isinstance(value, str) and value.startswith("$")})
        matched = [name for name in placeholders if name.casefold().replace(" ", "_") in columns]
        ruleset_templates.append({"template_id": template["template_id"], "score": len(matched) / len(placeholders) if placeholders else 1,
                                  "matched_columns": matched, "missing_columns": [n for n in placeholders if n not in matched],
                                  "_domain": template.get("domain") != domain, "_code": template.get("template_code", "")})
    ruleset_templates.sort(key=lambda item: (item["_domain"], -item["score"], item["_code"]))
    for item in ruleset_templates:
        item.pop("_domain")
        item.pop("_code")
    return {"rules": rules, "ruleset_templates": ruleset_templates, "policy_templates": policy_templates, "warnings": [f"{prefix}_RECOMMENDATIONS_REQUIRE_REVIEW"]}


def _provenance(scope: dict) -> dict:
    """Per-candidate evidence scope, taken from the profile actually used."""
    return {"sample_rows": scope["rows"] or 0, "is_sample": scope["is_sample"], "profile_mode": scope["mode"],
            "profile_id": scope["profile_id"], "profile_fingerprint": scope["fingerprint"]}
