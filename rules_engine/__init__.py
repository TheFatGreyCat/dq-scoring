from rules_engine.models import (
    RuleConfig,
    RuleEvaluationResult,
    RuleIssueSample,
    RuleRun,
    RulesEngineResult,
)


def __getattr__(name: str):
    if name == "run_rules":
        from rules_engine.run import run_rules

        return run_rules
    raise AttributeError(name)

__all__ = [
    "RuleConfig",
    "RuleEvaluationResult",
    "RuleIssueSample",
    "RuleRun",
    "RulesEngineResult",
    "run_rules",
]
