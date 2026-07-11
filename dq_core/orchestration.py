from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class DqRepository(Protocol):
    def save_dataset(self, csv_content: bytes, metadata: dict[str, Any]) -> str: ...
    def save_rule_bindings(self, dataset_version_id: str, bindings: list[dict[str, Any]], exceptions: list[dict[str, Any]]) -> str: ...
    def get_run_result(self, score_run_id: str | None = None) -> dict[str, Any]: ...
    def get_pipeline_logs(self) -> list[dict[str, Any]]: ...


class DqProfiler(Protocol):
    def run_profile(self, dataset_version_id: str) -> str: ...


class DqRuleRecommender(Protocol):
    def recommend_rules(self, dataset_version_id: str) -> list[dict[str, Any]]: ...


class DqValidator(Protocol):
    def run_validation(self, dataset_version_id: str, ruleset_hash: str | None = None) -> str: ...


class DqScorer(Protocol):
    def calculate_scores(self, validation_run_id: str, scoring_policy_id: str | None = None) -> str: ...


@dataclass(frozen=True)
class DqScoringOrchestrator:
    repository: DqRepository
    profiler: DqProfiler
    recommender: DqRuleRecommender
    validator: DqValidator
    scorer: DqScorer

    def register_dataset(self, csv_content: bytes, metadata: dict[str, Any]) -> str:
        return self.repository.save_dataset(csv_content, metadata)

    def onboard_dataset(self, csv_content: bytes, metadata: dict[str, Any]) -> str:
        return self.register_dataset(csv_content, metadata)

    def profile_dataset(self, dataset_version_id: str) -> str:
        return self.profiler.run_profile(dataset_version_id)

    def run_profile(self, dataset_version_id: str) -> str:
        return self.profile_dataset(dataset_version_id)

    def recommend_rules(self, dataset_version_id: str) -> list[dict[str, Any]]:
        return self.recommender.recommend_rules(dataset_version_id)

    def save_rule_bindings(
        self,
        dataset_version_id: str,
        bindings: list[dict[str, Any]],
        exceptions: list[dict[str, Any]] | None = None,
    ) -> str:
        return self.repository.save_rule_bindings(dataset_version_id, bindings, exceptions or [])

    def run_validation(self, dataset_version_id: str, ruleset_hash: str | None = None) -> str:
        return self.validator.run_validation(dataset_version_id, ruleset_hash)

    def calculate_score(self, validation_run_id: str, scoring_policy_id: str | None = None) -> str:
        return self.scorer.calculate_scores(validation_run_id, scoring_policy_id)

    def calculate_scores(self, validation_run_id: str, scoring_policy_id: str | None = None) -> str:
        return self.calculate_score(validation_run_id, scoring_policy_id)

    def get_run_result(self, score_run_id: str | None = None) -> dict[str, Any]:
        return self.repository.get_run_result(score_run_id)

    def get_pipeline_logs(self) -> list[dict[str, Any]]:
        return self.repository.get_pipeline_logs()
