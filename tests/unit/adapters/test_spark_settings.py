"""Unit tests for typed Spark settings and the memory-budget check."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from dq_scoring.adapters.compute.spark_settings import SparkSettings

K8S_MASTER = "k8s://https://kubernetes.default.svc:443"


@pytest.fixture(autouse=True)
def _clean_spark_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [k for k in os.environ if k.startswith("DQ_SPARK_")]:
        monkeypatch.delenv(key)


def test_defaults_fit_budget_and_local_conf() -> None:
    conf = SparkSettings().to_spark_conf()

    assert not [k for k in conf if k.startswith("spark.kubernetes.")]
    assert conf["spark.sql.shuffle.partitions"] == "4"
    assert conf["spark.driver.memory"] == "1024m"
    assert conf["spark.ui.enabled"] == "false"


def test_budget_overrun_is_rejected() -> None:
    with pytest.raises(ValidationError, match="DQ_SPARK_MAX_MEMORY_MB"):
        SparkSettings(executor_memory="3g")


def test_k8s_memory_budget_boundary() -> None:
    # driver 1024m + overhead 512m + 2 * (executor 1536m + overhead 512m) = 5632 MiB
    sizing = {
        "driver_memory": "1024m",
        "driver_memory_overhead": "512m",
        "executor_memory": "1536m",
        "executor_memory_overhead": "512m",
        "executor_instances": 2,
    }

    SparkSettings(**sizing, max_memory_mb=5632)
    with pytest.raises(ValidationError, match="DQ_SPARK_MAX_MEMORY_MB"):
        SparkSettings(**sizing, max_memory_mb=5631)


@pytest.mark.parametrize("cores", [0, -1])
def test_invalid_executor_cores_are_rejected(cores: int) -> None:
    with pytest.raises(ValidationError):
        SparkSettings(executor_cores=cores)


def test_executor_cores_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQ_SPARK_EXECUTOR_CORES", "2")

    assert SparkSettings().executor_cores == 2


def test_k8s_conf_requests_executor_cores_only_on_k8s() -> None:
    conf = SparkSettings(master=K8S_MASTER, driver_host="10.42.0.7", executor_cores=2).to_spark_conf()

    assert conf["spark.executor.cores"] == "2"
    assert conf["spark.kubernetes.executor.request.cores"] == "2"
    assert "spark.executor.cores" not in SparkSettings().to_spark_conf()


def test_k8s_conf_has_no_hostpath_volume() -> None:
    conf = SparkSettings(master=K8S_MASTER, driver_host="10.42.0.7").to_spark_conf()
    assert not any("hostPath" in k for k in conf)

def test_k8s_master_requires_driver_host() -> None:
    with pytest.raises(ValueError, match="DQ_SPARK_DRIVER_HOST"):
        SparkSettings(master=K8S_MASTER).to_spark_conf()


def test_invalid_memory_string_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SparkSettings(driver_memory="1GB")


def test_env_keys_from_env_example_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQ_SPARK_DRIVER_MEMORY", "900m")
    monkeypatch.setenv("DQ_SPARK_SQL_SHUFFLE_PARTITIONS", "8")

    conf = SparkSettings().to_spark_conf()

    assert conf["spark.driver.memory"] == "900m"
    assert conf["spark.sql.shuffle.partitions"] == "8"


def test_k8s_conf_names_driver_pod_when_set() -> None:
    settings = SparkSettings(master=K8S_MASTER, driver_host="10.42.0.7", driver_pod_name="dq-spark-worker-abc")

    assert settings.to_spark_conf()["spark.kubernetes.driver.pod.name"] == "dq-spark-worker-abc"
    assert "spark.kubernetes.driver.pod.name" not in SparkSettings(master=K8S_MASTER, driver_host="h").to_spark_conf()


def test_standalone_requires_reachable_driver() -> None:
    with pytest.raises(ValueError, match="DQ_SPARK_DRIVER_HOST"):
        SparkSettings(master="spark://spark-master:7077").to_spark_conf()


def test_standalone_caps_executor_allocation_without_kubernetes() -> None:
    settings = SparkSettings(
        master="spark://spark-master:7077", driver_host="evaluation-worker",
        driver_memory="2g", driver_memory_overhead="512m",
        executor_memory="4g", executor_memory_overhead="1024m",
        executor_instances=2, executor_cores=4, max_memory_mb=16384,
    )
    conf = settings.to_spark_conf()
    assert conf["spark.driver.host"] == "evaluation-worker"
    assert conf["spark.driver.bindAddress"] == "0.0.0.0"
    assert conf["spark.driver.port"] == "7078"
    assert conf["spark.driver.blockManager.port"] == "7079"
    assert conf["spark.cores.max"] == "8"
    assert conf["spark.executor.memory"] == "4g"
    assert conf["spark.executor.cores"] == "4"
    assert conf["spark.dynamicAllocation.enabled"] == "false"
    assert not any(key.startswith("spark.kubernetes.") for key in conf)
    with pytest.raises(ValidationError, match="DQ_SPARK_MAX_MEMORY_MB"):
        SparkSettings(**{**settings.model_dump(), "max_memory_mb": 12799})


def test_spark_settings_enforces_protected_compute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")

    # Local and standalone masters rejected
    with pytest.raises(ValueError, match="PROTECTED_COMPUTE_CONFIGURATION_REQUIRED"):
        SparkSettings(master="local[*]").to_spark_conf()

    with pytest.raises(ValueError, match="PROTECTED_COMPUTE_CONFIGURATION_REQUIRED"):
        SparkSettings(master="spark://master:7077", driver_host="worker").to_spark_conf()

    # k8s master accepted and emits secure Spark 4.2 settings
    settings = SparkSettings(
        master=K8S_MASTER,
        driver_host="evaluation-worker",
    )
    conf = settings.to_spark_conf()
    assert conf["spark.authenticate"] == "true"
    assert conf["spark.authenticate.secret.file"] == "/opt/dq/security/rpc-auth"
    assert conf["spark.ssl.rpc.enabled"] == "true"
    assert conf["spark.ssl.rpc.protocol"] == "TLSv1.3"
    assert conf["spark.ssl.rpc.keyStore"] == "/opt/dq/security/keystore.jks"
    assert conf["spark.ssl.rpc.trustStore"] == "/opt/dq/security/truststore.jks"
    assert conf["spark.network.crypto.enabled"] == "false"
    assert conf["spark.io.encryption.enabled"] == "true"
    assert conf["spark.io.encryption.keySizeBits"] == "256"
    assert conf["spark.ui.enabled"] == "false"
    assert conf["spark.eventLog.enabled"] == "false"
    assert conf["spark.port.maxRetries"] == "0"
    assert conf["spark.driver.port"] == "7078"
    assert conf["spark.blockManager.port"] == "7079"
    assert conf["spark.driver.blockManager.port"] == "7079"
    assert conf["spark.kubernetes.executor.label.dq-scoring/protected"] == "true"


def test_protected_executor_uses_operator_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQ_PROTECTED_PROCESSING_ENABLED", "true")
    monkeypatch.setenv("DQ_SPARK_SECURITY_SECRET", "synthetic-spark-tls")
    conf = SparkSettings(master=K8S_MASTER, driver_host="worker").to_spark_conf()
    assert conf["spark.kubernetes.executor.secrets.synthetic-spark-tls"] == "/opt/dq/security"
    assert "spark.kubernetes.executor.secrets.spark-security" not in conf
