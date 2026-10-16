"""Typed Spark session settings (env prefix DQ_SPARK_) with the single-node memory budget check."""

from __future__ import annotations

import os
from typing import Annotated, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dq_scoring.common.protected_transport import is_protected_processing_enabled

MemorySize = Annotated[str, Field(pattern=r"^\d+[mMgG]$")]
"""JVM memory size such as '1024m' or '2g'."""
K8S_MASTER_PREFIX = "k8s://"


def _mib(size: str) -> int:
    return int(size[:-1]) * (1024 if size[-1] in "gG" else 1)


class SparkSettings(BaseSettings):
    """Spark driver/executor configuration; total JVM memory must fit DQ_SPARK_MAX_MEMORY_MB."""

    model_config = SettingsConfigDict(env_prefix="DQ_SPARK_", extra="ignore")

    master: str = "local[*]"
    driver_memory: MemorySize = "1024m"
    executor_memory: MemorySize = "1536m"
    driver_memory_overhead: MemorySize = "256m"
    executor_memory_overhead: MemorySize = "384m"
    executor_instances: int = Field(default=1, ge=1)
    executor_cores: int = Field(default=1, ge=1)
    max_memory_mb: int = 4096
    sql_shuffle_partitions: int = Field(default=4, ge=1)
    kubernetes_namespace: str = "dq-scoring"
    kubernetes_executor_image: str = "apache/spark:4.2.0"
    kubernetes_service_account: str = "dq-spark-driver"
    driver_host: str | None = None
    driver_pod_name: str | None = None
    driver_port: int = 7078
    block_manager_port: int = 7079
    # Storage is managed via S3A / MinIO object store; no hostPath mount
    @model_validator(mode="after")
    def _check_memory_budget(self) -> Self:
        total = (
            _mib(self.driver_memory)
            + _mib(self.driver_memory_overhead)
            + self.executor_instances * (_mib(self.executor_memory) + _mib(self.executor_memory_overhead))
        )
        if total > self.max_memory_mb:
            raise ValueError(
                f"Spark memory budget {total} MiB (driver + overhead + executors x (memory + overhead)) "
                f"exceeds DQ_SPARK_MAX_MEMORY_MB={self.max_memory_mb}"
            )
        return self

    def to_spark_conf(self) -> dict[str, str]:
        """Return backend-specific sizing and reachable driver configuration."""
        if is_protected_processing_enabled() and not self.master.startswith(K8S_MASTER_PREFIX):
            raise ValueError(
                "PROTECTED_COMPUTE_CONFIGURATION_REQUIRED: local and standalone Spark masters are forbidden in protected processing mode"
            )
        conf = {
            "spark.driver.memory": self.driver_memory,
            "spark.sql.shuffle.partitions": str(self.sql_shuffle_partitions),
            "spark.ui.enabled": "false",
        }
        standalone = self.master.startswith("spark://")
        if not standalone and not self.master.startswith(K8S_MASTER_PREFIX):
            return conf
        if not self.driver_host:
            raise ValueError("DQ_SPARK_DRIVER_HOST is required for a distributed Spark master")
        conf |= {
            "spark.driver.host": self.driver_host,
            "spark.driver.bindAddress": "0.0.0.0",
            "spark.driver.port": str(self.driver_port),
            "spark.driver.blockManager.port": str(self.block_manager_port),
            "spark.executor.memory": self.executor_memory,
            "spark.executor.cores": str(self.executor_cores),
        }
        if standalone:
            conf |= {
                "spark.cores.max": str(self.executor_instances * self.executor_cores),
                "spark.dynamicAllocation.enabled": "false",
            }
            return conf
        conf |= {
            "spark.driver.memoryOverhead": self.driver_memory_overhead,
            "spark.executor.memoryOverhead": self.executor_memory_overhead,
            "spark.executor.instances": str(self.executor_instances),
            "spark.kubernetes.namespace": self.kubernetes_namespace,
            "spark.kubernetes.executor.request.cores": str(self.executor_cores),
            "spark.kubernetes.container.image": self.kubernetes_executor_image,
            "spark.kubernetes.authenticate.driver.serviceAccountName": self.kubernetes_service_account,
            "spark.kubernetes.executor.deleteOnTermination": "true",
        }
        if self.driver_pod_name:
            conf["spark.kubernetes.driver.pod.name"] = self.driver_pod_name
        if is_protected_processing_enabled():
            sec_dir = os.getenv("DQ_SECURITY_DIR", "/opt/dq/security")
            conf |= {
                "spark.authenticate": "true",
                "spark.authenticate.secret.file": f"{sec_dir}/rpc-auth",
                "spark.ssl.rpc.enabled": "true",
                "spark.ssl.rpc.protocol": "TLSv1.3",
                "spark.ssl.rpc.keyStore": f"{sec_dir}/keystore.jks",
                "spark.ssl.rpc.trustStore": f"{sec_dir}/truststore.jks",
                "spark.network.crypto.enabled": "false",
                "spark.io.encryption.enabled": "true",
                "spark.io.encryption.keySizeBits": "256",
                "spark.ui.enabled": "false",
                "spark.eventLog.enabled": "false",
                "spark.port.maxRetries": "0",
                "spark.driver.port": str(self.driver_port),
                "spark.blockManager.port": str(self.block_manager_port),
                "spark.driver.blockManager.port": str(self.block_manager_port),
                "spark.kubernetes.executor.label.dq-scoring/protected": "true",
                f"spark.kubernetes.executor.secrets.{os.getenv('DQ_SPARK_SECURITY_SECRET', 'spark-security')}": sec_dir,
                "spark.redaction.regex": "(?i)secret|password|token|access[._]?key|authorization",
            }
            secret = os.getenv("DQ_SPARK_SECURITY_SECRET", "spark-security")
            for variable, key in (
                ("_SPARK_AUTH_SECRET", "rpc-auth-base64"),
                ("_SPARK_SSL_RPC_KEY_PASSWORD", "key-password"),
                ("_SPARK_SSL_RPC_KEY_STORE_PASSWORD", "keystore-password"),
                ("_SPARK_SSL_RPC_TRUST_STORE_PASSWORD", "truststore-password"),
            ):
                conf[f"spark.kubernetes.executor.secretKeyRef.{variable}"] = f"{secret}:{key}"
        # End k8s config
        return conf
