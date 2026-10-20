"""RunSparkObserver: publishes only truthful, fenced, run-scoped observations."""

from __future__ import annotations

import threading
from uuid import uuid4

from dq_scoring.workers.monitoring import RunSparkObserver, spark_group_id


class FakeCompute:
    def __init__(self, observation=None, fail=False):
        self.observation, self.fail = observation, fail
        self.bound, self.cleared = [], 0

    def bind_run_group(self, group):
        self.bound.append(group)

    def clear_run_group(self):
        self.cleared += 1

    def observe_group(self, group):
        if self.fail:
            raise RuntimeError("synthetic spark failure password=hunter2")
        return self.observation


class FakeQueue:
    def __init__(self, accept=True):
        self.accept, self.calls, self.seen = accept, [], threading.Event()

    def record_spark_observation(self, run_id, lease_generation, tenant_id, observation):
        self.calls.append((run_id, lease_generation, tenant_id, observation))
        self.seen.set()
        return self.accept


class Lease:
    def __init__(self, generation=3):
        self.run_id, self.lease_generation = uuid4(), generation

        class Spec:
            tenant_id = uuid4()

        self.spec = Spec()


OBS = {"application_id": "app-1", "jobs": [{"job_id": 4, "status": "RUNNING", "stages": 1, "tasks": 2,
                                           "active_tasks": 1, "completed_tasks": 1, "failed_tasks": 0}]}


def test_group_id_binds_run_and_generation():
    lease = Lease(3)
    assert spark_group_id(lease.run_id, 3) == f"dq-run-{lease.run_id}-g3"
    assert spark_group_id(lease.run_id, 3) != spark_group_id(lease.run_id, 4)


def test_publishes_run_scoped_observation_with_lease_and_clears_binding():
    lease, compute, queue = Lease(), FakeCompute(dict(OBS)), FakeQueue()
    observer = RunSparkObserver(compute, queue, interval_seconds=0.01)
    observer.start(lease)
    assert queue.seen.wait(2)
    observer.stop()
    run_id, generation, tenant_id, payload = queue.calls[0]
    assert (run_id, generation, tenant_id) == (lease.run_id, 3, lease.spec.tenant_id)
    assert compute.bound == [spark_group_id(lease.run_id, 3)]
    assert payload["group_id"] == compute.bound[0] and payload["jobs"] == OBS["jobs"]
    assert compute.cleared == 1


def test_unchanged_observation_is_not_republished_before_keepalive():
    queue = FakeQueue()
    observer = RunSparkObserver(FakeCompute(dict(OBS)), queue, interval_seconds=0.01, keepalive_seconds=60)
    observer.start(Lease())
    assert queue.seen.wait(2)
    threading.Event().wait(0.15)
    observer.stop()
    assert len(queue.calls) == 1


def test_spark_failure_publishes_nothing():
    queue = FakeQueue()
    observer = RunSparkObserver(FakeCompute(fail=True), queue, interval_seconds=0.01)
    observer.start(Lease())
    threading.Event().wait(0.15)
    observer.stop()
    assert queue.calls == []


def test_fenced_rejection_stops_publishing():
    queue = FakeQueue(accept=False)
    observer = RunSparkObserver(FakeCompute(dict(OBS)), queue, interval_seconds=0.01, keepalive_seconds=0.01)
    observer.start(Lease())
    assert queue.seen.wait(2)
    threading.Event().wait(0.15)
    observer.stop()
    assert len(queue.calls) == 1


def test_stop_without_start_and_double_stop_are_safe():
    observer = RunSparkObserver(FakeCompute(), FakeQueue())
    observer.stop()


def test_stalled_observer_is_not_revived_by_next_run():
    entered, release = threading.Event(), threading.Event()

    class BlockedCompute(FakeCompute):
        def observe_group(self, group):
            entered.set()
            assert release.wait(5)
            return dict(OBS)

    compute, queue = BlockedCompute(), FakeQueue()
    observer = RunSparkObserver(compute, queue, interval_seconds=0.01)
    observer.start(Lease())
    assert entered.wait(1)
    old_thread = observer._thread
    try:
        observer.stop()
        observer.start(Lease())
        assert observer._thread is old_thread
        release.set()
        old_thread.join(1)
        assert not old_thread.is_alive()
        assert queue.calls == []
        assert len(compute.bound) == 2
    finally:
        release.set()
        observer.stop()
