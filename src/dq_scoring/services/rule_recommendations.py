"""Sample-based suggestions; never infer business constraints from observations."""

from __future__ import annotations

import re


def recommend_rules(schema: dict, profile: dict, domain: str, priorities: tuple[str, ...], templates: list[dict]) -> dict:
    stats = {column["name"]: column for column in profile.get("columns", [])}
    rules = []
    for index, column in enumerate(schema.get("columns", [])):
        name = column["name"] if isinstance(column, dict) else column
        stat = stats.get(name, {})
        nonnull = stat.get("non_null_count", 0)
        candidates = []
        if "COMPLETENESS" in priorities:
            candidates.append(("COMPLETENESS", "NON_NULL", {"column": name}, "SAMPLE_NULL_STATISTICS"))
        kind = stat.get("type_hint", "STRING")
        if "VALIDITY" in priorities and kind in ("INTEGER", "DOUBLE", "DATE", "TIMESTAMP") and nonnull and stat.get("parse_success_count", 0) / nonnull >= .95:
            params = {"column": name, "data_type": kind}
            if kind in ("DATE", "TIMESTAMP"):
                fmt = stat.get("timestamp_format", "yyyy-MM-dd" if kind == "DATE" else None)
                if not fmt:
                    continue
                params["format"] = fmt
            candidates.append(("VALIDITY", "TYPE_PARSE", params, "SAMPLE_PARSE_SUCCESS"))
        tokens = re.split(r"[^a-z0-9]+", name.casefold())
        if "UNIQUENESS" in priorities and "id" in tokens and nonnull and stat.get("distinct_count") == nonnull:
            candidates.append(("UNIQUENESS", "UNIQUENESS", {"column": name}, "SAMPLE_UNIQUENESS_NOT_PROOF"))
        for dimension, rule_type, params, reason in candidates:
            rules.append({"rule": {
                "rule_code": f"suggested_{index}_{rule_type.lower()}", "dimension": dimension,
                "rule_type": rule_type, "parameters": params, "null_policy": "fail",
                "is_required": False, "is_critical": False, "gate_enabled": True,
                "score_enabled": True, "is_advisory": False, "contribution_weight": 1,
            }, "reason_code": reason, "reason_params": {"column": name, "null_count": stat.get("null_count", 0)},
            "sample_rows": profile.get("sample_rows", 0), "is_sample": True})
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
    return {"rules": rules, "ruleset_templates": ruleset_templates, "policy_templates": policy_templates, "warnings": ["SAMPLE_RECOMMENDATIONS_REQUIRE_REVIEW"]}
