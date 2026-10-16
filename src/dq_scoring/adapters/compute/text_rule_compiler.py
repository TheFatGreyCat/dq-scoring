"""Extended Spark operators; only structured parsing uses Python UDFs."""
from functools import partial

from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from dq_scoring.common.rule_parameters import (
    JsonArrayParameters,
    JsonFieldParameters,
    TextQualityParameters,
)
from dq_scoring.common.structured_values import (
    evaluate_json_array,
    evaluate_json_field,
    extract_json_field,
)
from dq_scoring.core.entities import QualityRule


def compile_text_quality(rule: QualityRule, target: str):
    from dq_scoring.adapters.compute.sql_rule_compiler import (
        _is_missing,
        _rule,
        quoted_col,
    )
    params = TextQualityParameters.model_validate(rule.parameters)
    col = quoted_col(target)
    missing = _is_missing(target)
    if params.check == "REPLACEMENT_CHARACTER":
        failed = col.contains("\ufffd")
    elif params.check == "CONTROL_CHARACTER":
        failed = col.rlike(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
    elif params.check == "MOJIBAKE":
        failed = col.rlike("Ã|Â|â€|ðŸ")
    else:
        failed = F.lit(False)
        if params.min_length is not None:
            failed = failed | (F.length(col) < params.min_length)
        if params.max_length is not None:
            failed = failed | (F.length(col) > params.max_length)
    return _rule(rule, target, missing, failed=(~missing) & failed)


def _compile_label(rule, target, label):
    from dq_scoring.adapters.compute.sql_rule_compiler import _rule
    return _rule(rule, target, label == "missing", miscast=label == "miscast", failed=label == "failed")


def compile_json_field(rule: QualityRule, target: str):
    from dq_scoring.adapters.compute.sql_rule_compiler import _rule, quoted_col
    params = JsonFieldParameters.model_validate(rule.parameters).model_dump(exclude_none=True)
    if params["check"] == "RANGE":
        label = F.udf(partial(evaluate_json_field, parameters=params), StringType())(quoted_col(target))
        return _compile_label(rule, target, label)
    schema = StructType([StructField(name, StringType(), True) for name in ("state", "kind", "text", "number_decimal")])
    field = F.udf(partial(extract_json_field, path=params["path"]), schema)(quoted_col(target))
    missing = field["state"] == "missing"
    miscast = field["state"] == "miscast"
    failed = F.lit(False)
    if params["check"] == "TYPE":
        miscast = miscast | ((field["state"] == "present") & (field["kind"] != params["expected_type"]))
    elif params["check"] in ("REGEX", "ALLOWED_VALUES"):
        miscast = miscast | ((field["state"] == "present") & (field["kind"] != "STRING"))
        matches = field["text"].rlike(params["pattern"]) if params["check"] == "REGEX" else field["text"].isin(params["allowed_values"])
        failed = (field["state"] == "present") & (field["kind"] == "STRING") & (~matches)
    return _rule(rule, target, missing, miscast=miscast, failed=failed)


def compile_json_array(rule: QualityRule, target: str):
    from dq_scoring.adapters.compute.sql_rule_compiler import quoted_col
    params = JsonArrayParameters.model_validate(rule.parameters).model_dump(exclude_none=True)
    label = F.udf(partial(evaluate_json_array, parameters=params), StringType())(quoted_col(target))
    return _compile_label(rule, target, label)


_WORKER_SPELLING_CACHE = {}


def _spell_label(value, broadcast, digest, accepted_terms):
    from dq_scoring.adapters.compute.spelling_dictionary import (
        create_evaluator_from_bundle,
    )
    evaluator = _WORKER_SPELLING_CACHE.get(digest)
    if evaluator is None:
        evaluator = create_evaluator_from_bundle(broadcast.value, accepted_terms)
        if len(_WORKER_SPELLING_CACHE) >= 3:
            _WORKER_SPELLING_CACHE.pop(next(iter(_WORKER_SPELLING_CACHE)))
        _WORKER_SPELLING_CACHE[digest] = evaluator
    return evaluator.evaluate(value)


def compile_spelling(rule: QualityRule, target: str):
    from dataclasses import replace

    from pyspark.sql import SparkSession

    from dq_scoring.adapters.compute.spelling_dictionary import (
        SpellingDictionaryManager,
    )
    from dq_scoring.adapters.compute.sql_rule_compiler import quoted_col
    from dq_scoring.common.hash_utils import compute_deterministic_hash
    from dq_scoring.common.rule_parameters import SpellingParameters
    params = SpellingParameters.model_validate(rule.parameters)
    manager = SpellingDictionaryManager()
    try:
        digests = manager.get_digests(params.dictionary_revision, params.language)
        if params.dictionary_digests != digests:
            raise ValueError("Pinned dictionary digests differ")
        bundle = manager.get_bundle(params.dictionary_revision, params.language)
        manager.create_evaluator(params.dictionary_revision, params.language)
    except (ValueError, OSError) as exc:
        raise ValueError("TEXT_DICTIONARY_UNAVAILABLE") from exc
    session = SparkSession.getActiveSession()
    broadcast = session.sparkContext.broadcast([{key: item[key] for key in ("aff_bytes", "dic_bytes")} for item in bundle])
    digest = compute_deterministic_hash({"digests": digests, "accepted_terms": params.accepted_terms})
    label = F.udf(partial(_spell_label, broadcast=broadcast, digest=digest, accepted_terms=params.accepted_terms), StringType())(quoted_col(target))
    return replace(_compile_label(rule, target, label), scope_expr=label == "not_applicable")
