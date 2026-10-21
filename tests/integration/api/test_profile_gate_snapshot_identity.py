import pytest

from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.common.profiling import ProfileRequiredError
from tests.support.run_seed import seed_run_prerequisites


def test_same_snapshot_id_with_other_object_cannot_reuse_complete_profile(pg_dsn,sample_run_spec):
    spec=seed_run_prerequisites(pg_dsn,sample_run_spec)
    descriptor={**spec.snapshot.source_descriptor,"canonical":{**spec.snapshot.source_descriptor['canonical'],"version_id":"other-version"}}
    spoof=spec.model_copy(update={"snapshot":spec.snapshot.model_copy(update={"source_descriptor":descriptor})})
    with pytest.raises(ProfileRequiredError):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(spoof,"spoofed-object")
