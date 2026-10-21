"""Demand in both classes must make progress, including an empty preferred queue."""
from collections import deque

from dq_scoring.workers.snapshot_profile_worker import FairProfileScheduler


class Work:
    def __init__(self, name, pending, completed):
        self.name, self.pending, self.completed = name, deque(pending), completed

    def run_once(self):
        if not self.pending:
            return None
        item = self.pending.popleft()
        self.completed.append((self.name, item))
        return item


def test_both_classes_make_progress_without_starvation():
    completed = []
    profiles = Work("profile", [1, 2, 3], completed)
    evaluations = Work("evaluation", [4, 5, 6], completed)
    scheduler = FairProfileScheduler(evaluations, profiles)
    for _ in range(6):
        assert scheduler.run_once()
    assert completed == [("profile", 1), ("evaluation", 4), ("profile", 2), ("evaluation", 5), ("profile", 3), ("evaluation", 6)]
    assert not scheduler.run_once()


def test_empty_preferred_queue_does_not_delay_evaluation():
    completed = []
    scheduler = FairProfileScheduler(Work("evaluation", [1], completed), Work("profile", [], completed))
    assert scheduler.run_once()
    assert completed == [("evaluation", 1)]


def test_failing_evaluation_cannot_starve_profile_queue():
    import pytest
    completed = []

    class FailingEvaluation:
        def run_once(self):
            completed.append(("evaluation", "failed"))
            raise RuntimeError("synthetic failed claimed job")

    scheduler = FairProfileScheduler(FailingEvaluation(), Work("profile", [1,2,3], completed))
    assert scheduler.run_once()
    with pytest.raises(RuntimeError):
        scheduler.run_once()
    assert scheduler.run_once()
    assert completed == [("profile",1),("evaluation","failed"),("profile",2)]
