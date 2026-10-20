"""observe_group must read the real pyspark StatusTracker tuple shapes (fields drift between versions)."""

from __future__ import annotations

from types import SimpleNamespace

from pyspark.status import SparkJobInfo, SparkStageInfo

from dq_scoring.adapters.compute.spark_compute import (
    MAX_OBSERVED_JOBS,
    PySparkComputeAdapter,
)


class Tracker:
    def __init__(self, job_ids):
        self.job_ids = job_ids

    def getJobIdsForGroup(self, group):
        assert group == "g"
        return self.job_ids

    def getJobInfo(self, job_id):
        return None if job_id == 404 else SparkJobInfo(job_id, [job_id * 10], "RUNNING")

    def getStageInfo(self, stage_id):
        return SparkStageInfo(stage_id, 0, "stage", 8, 3, 4, 1)


def adapter(job_ids):
    compute = PySparkComputeAdapter.__new__(PySparkComputeAdapter)
    context = SimpleNamespace(applicationId="app-1", statusTracker=lambda: Tracker(job_ids))
    compute._spark = SimpleNamespace(sparkContext=context)
    return compute


def test_observation_aggregates_real_stage_fields():
    [job] = adapter([7]).observe_group("g")["jobs"]
    assert job == {"job_id": 7, "status": "RUNNING", "stages": 1, "tasks": 8, "active_tasks": 3, "completed_tasks": 4, "failed_tasks": 1}


def test_missing_jobs_are_skipped_and_count_is_bounded():
    assert adapter([404]).observe_group("g")["jobs"] == []
    jobs = adapter(list(range(MAX_OBSERVED_JOBS + 10))).observe_group("g")["jobs"]
    assert len(jobs) == MAX_OBSERVED_JOBS
    assert jobs[-1]["job_id"] == MAX_OBSERVED_JOBS + 9
