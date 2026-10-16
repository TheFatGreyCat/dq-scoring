"""Preflight must not certify an unmeasured or permissive deployment."""
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("preflight", Path(__file__).parents[2] / "scripts/k3s/check_protected_processing.py")
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


@pytest.mark.parametrize("rule", [{}, {"toPorts": [{"ports": [{"port": "443"}]}]}, {"toEndpoints": [{}]}, {"toPorts": [{"rules": {"dns": [{"matchPattern": "*.internal"}]}}]}])
def test_permissive_cilium_rules_fail(monkeypatch, rule):
    policies = [{"metadata": {"name": f"dq-dq-scoring-{role}"}, "spec": {"egress": [rule]}} for role in ("api", "import", "driver", "executor")]
    def kubectl(args, **kwargs):
        return 0, json.dumps({"items": policies if args[1] == "ciliumnetworkpolicy" else []}), ""
    monkeypatch.setattr(preflight, "_run_kubectl", kubectl)
    assert not preflight.check_network_policies("synthetic", "dq", None)


def test_exec_failure_cannot_pass_network_probes(monkeypatch):
    monkeypatch.setattr(preflight, "_run_kubectl", lambda *a, **kw: (0, "synthetic-pod", ""))
    monkeypatch.setattr(preflight, "_exec_in_pod", lambda *a, **kw: (1, ""))
    assert not preflight.check_egress_and_canary_probes("synthetic", "dq", "10.0.0.2", 8080, None)


def test_network_exec_error_after_valid_tls_fails(monkeypatch):
    monkeypatch.setattr(preflight, "_run_kubectl", lambda *a, **kw: (0, "synthetic-pod", ""))
    results = iter([(0, "TLS_VERIFIED")] * 3 + [(137, "")])
    monkeypatch.setattr(preflight, "_exec_in_pod", lambda *a, **kw: next(results))
    assert not preflight.check_egress_and_canary_probes("synthetic", "dq", "10.0.0.2", 8080, None)


def test_ready_cilium_endpoint_without_policy_is_not_enforcing(monkeypatch):
    def kubectl(args, **kwargs):
        if args[:2] == ["get", "pods"]:
            return 0, "synthetic-agent", ""
        if "status" in args:
            return 0, "OK", ""
        if args[:2] == ["get", "ciliumendpoints"]:
            return 0, json.dumps({"items": [{"metadata": {"name": "synthetic-pod"}, "status": {"state": "ready"}}]}), ""
        return 0, json.dumps([{ "status": {"external-identifiers": {"k8s-namespace": "synthetic", "k8s-pod-name": "synthetic-pod"}, "policy": {"realized": {"policy-enabled": "none"}}}}]), ""
    monkeypatch.setattr(preflight, "_run_kubectl", kubectl)
    assert not preflight.check_cilium_enforcement("synthetic", "dq", None)


def _create_synthetic_manifests(second_worker_mutator=None):
    api_dep = {
        "metadata": {"name": "dq-dq-scoring-api", "labels": {"app.kubernetes.io/instance": "dq", "app.kubernetes.io/component": "api"}},
        "spec": {
            "template": {
                "spec": {
                    "volumes": [
                        {"name": "scratch", "emptyDir": {"medium": "Memory"}},
                        {
                            "name": "security",
                            "projected": {
                                "sources": [
                                    {"secret": {"name": "custom-api-cert-sec", "items": [{"key": "tls.crt"}, {"key": "tls.key"}]}},
                                    {"secret": {"name": "custom-ca-sec", "items": [{"key": "postgres-ca.pem"}, {"key": "s3-ca.pem"}]}},
                                ]
                            },
                        },
                    ],
                    "containers": [
                        {
                            "name": "api",
                            "env": [
                                {"name": "DQ_POSTGRES_DSN", "valueFrom": {"secretKeyRef": {"name": "custom-api-dsn-sec", "key": "dsn"}}},
                                {"name": "DQ_AUTH_SECRET_KEY", "valueFrom": {"secretKeyRef": {"name": "custom-jwt-sec", "key": "jwt"}}},
                            ],
                        }
                    ],
                }
            }
        },
    }

    def _make_worker(name, lane):
        return {
            "metadata": {"name": name, "labels": {"app.kubernetes.io/instance": "dq", "app.kubernetes.io/component": "worker", "dq-scoring/lane": lane}},
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {"name": "scratch", "emptyDir": {"medium": "Memory"}},
                            {
                                "name": "security",
                                "projected": {
                                    "sources": [
                                        {
                                            "secret": {
                                                "name": "custom-spark-sec",
                                                "items": [
                                                    {"key": "rpc-auth"},
                                                    {"key": "keystore.jks"},
                                                    {"key": "truststore.jks"},
                                                    {"key": "spark-defaults.conf"},
                                                ],
                                            }
                                        },
                                        {"secret": {"name": "custom-ca-sec", "items": [{"key": "postgres-ca.pem"}, {"key": "s3-ca.pem"}]}},
                                    ]
                                },
                            },
                        ],
                        "containers": [
                            {
                                "name": "worker",
                                "env": [
                                    {"name": "DQ_WORKER_POSTGRES_DSN", "valueFrom": {"secretKeyRef": {"name": "custom-worker-dsn-sec", "key": "dsn"}}},
                                    {"name": "DQ_WORKER_LANE", "value": lane},
                                ],
                            }
                        ],
                    }
                }
            },
        }

    worker_fast = _make_worker("dq-dq-scoring-worker-fast", "fast")
    worker_heavy = _make_worker("dq-dq-scoring-worker-heavy", "heavy")
    if second_worker_mutator:
        second_worker_mutator(worker_heavy)

    import_dep = {
        "metadata": {"name": "dq-dq-scoring-import", "labels": {"app.kubernetes.io/instance": "dq", "app.kubernetes.io/component": "import"}},
        "spec": {
            "template": {
                "spec": {
                    "volumes": [
                        {"name": "scratch", "emptyDir": {"medium": "Memory"}},
                        {"name": "security", "projected": {"sources": [{"secret": {"name": "custom-ca-sec", "items": [{"key": "postgres-ca.pem"}, {"key": "s3-ca.pem"}]}}]}},
                    ],
                    "containers": [
                        {
                            "name": "import",
                            "env": [{"name": "DQ_WORKER_POSTGRES_DSN", "valueFrom": {"secretKeyRef": {"name": "custom-worker-dsn-sec", "key": "dsn"}}}],
                        }
                    ],
                }
            }
        },
    }

    return api_dep, [worker_fast, worker_heavy], import_dep


def _setup_cluster_mock(monkeypatch, second_worker_mutator=None):
    api_dep, workers, import_dep = _create_synthetic_manifests(second_worker_mutator)

    def kubectl(args, **kwargs):
        if args[:3] == ["get", "configmap", "dq-dq-scoring-config"]:
            return 0, json.dumps({"data": {"DQ_PROTECTED_PROCESSING_ENABLED": "true"}}), ""
        if args[:2] == ["get", "deployment"]:
            label = args[args.index("-l") + 1]
            if "component=api" in label:
                return 0, json.dumps({"items": [api_dep]}), ""
            if "component=worker" in label:
                return 0, json.dumps({"items": workers}), ""
            if "component=import" in label:
                return 0, json.dumps({"items": [import_dep]}), ""
        return 1, "", "not found"

    monkeypatch.setattr(preflight, "_run_kubectl", kubectl)


def test_secret_isolation_baseline_passes(monkeypatch):
    _setup_cluster_mock(monkeypatch)
    assert preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_second_lane_forbidden_secret_arbitrary_name_volume_fails(monkeypatch):
    def mutate(worker):
        # Mount API TLS secret (arbitrary name custom-api-cert-sec) in second lane volume
        worker["spec"]["template"]["spec"]["volumes"].append({"name": "api-leak", "secret": {"secretName": "custom-api-cert-sec"}})

    _setup_cluster_mock(monkeypatch, second_worker_mutator=mutate)
    assert not preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_second_lane_forbidden_secret_arbitrary_name_env_fails(monkeypatch):
    def mutate(worker):
        # Reference arbitrary-named API TLS secret via secretKeyRef in second lane container env
        worker["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {"name": "LEAKED_CERT", "valueFrom": {"secretKeyRef": {"name": "custom-api-cert-sec", "key": "tls.crt"}}}
        )

    _setup_cluster_mock(monkeypatch, second_worker_mutator=mutate)
    assert not preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_second_lane_forbidden_secret_arbitrary_name_envfrom_fails(monkeypatch):
    def mutate(worker):
        # Reference arbitrary-named API TLS secret via envFrom in second lane container
        worker["spec"]["template"]["spec"]["containers"][0]["envFrom"] = [{"secretRef": {"name": "custom-api-cert-sec"}}]

    _setup_cluster_mock(monkeypatch, second_worker_mutator=mutate)
    assert not preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_second_lane_forbidden_auth_secret_env_fails(monkeypatch):
    def mutate(worker):
        # Reference API JWT auth secret via env in second lane container
        worker["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {"name": "DQ_AUTH_SECRET_KEY", "valueFrom": {"secretKeyRef": {"name": "custom-jwt-sec", "key": "jwt"}}}
        )

    _setup_cluster_mock(monkeypatch, second_worker_mutator=mutate)
    assert not preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_second_lane_unexpected_private_key_item_fails(monkeypatch):
    def mutate(worker):
        # Mount unexpected secret with tls.key item in second lane volume
        worker["spec"]["template"]["spec"]["volumes"].append(
            {"name": "rogue", "secret": {"secretName": "rogue-secret", "items": [{"key": "tls.key", "path": "tls.key"}]}}
        )

    _setup_cluster_mock(monkeypatch, second_worker_mutator=mutate)
    assert not preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_second_lane_missing_memory_scratch_fails(monkeypatch):
    def mutate(worker):
        # Remove memory scratch emptyDir in second lane
        worker["spec"]["template"]["spec"]["volumes"] = [
            v for v in worker["spec"]["template"]["spec"]["volumes"] if v.get("name") != "scratch"
        ]

    _setup_cluster_mock(monkeypatch, second_worker_mutator=mutate)
    assert not preflight.check_secret_isolation_and_config("synthetic", "dq", None)


def test_spark_security_effective_live_and_configured(monkeypatch):
    monkeypatch.setattr(preflight, "_run_kubectl", lambda *a, **kw: (0, "dq-worker-pod", ""))

    # 1. Success case: both configured and live verified
    monkeypatch.setattr(preflight, "_exec_in_pod", lambda *a, **kw: (0, "SPARK_CONFIGURED_VERIFIED\nSPARK_LIVE_VERIFIED\n"))
    assert preflight.check_spark_security_effective("synthetic", "dq", None)

    # 2. Configured settings failure
    monkeypatch.setattr(preflight, "_exec_in_pod", lambda *a, **kw: (1, "AssertionError: spark.ssl.rpc.protocol != TLSv1.3\n"))
    assert not preflight.check_spark_security_effective("synthetic", "dq", None)

    # 3. Live runtime / keystore failure (passes configured, fails live)
    monkeypatch.setattr(preflight, "_exec_in_pod", lambda *a, **kw: (1, "SPARK_CONFIGURED_VERIFIED\nAssertionError: keystore validation failed\n"))
    assert not preflight.check_spark_security_effective("synthetic", "dq", None)


@pytest.mark.parametrize("result, expected", [(0, 1), (11, 0), (110, 0), (111, 1)])
def test_blocked_probe_distinguishes_timeout_from_closed_listener(monkeypatch, result, expected):
    import socket
    class SyntheticSocket:
        def settimeout(self, value):
            pass
        def connect_ex(self, target):
            return result
    monkeypatch.setattr(socket, "socket", SyntheticSocket)
    with pytest.raises(SystemExit) as outcome:
        exec(preflight._blocked_tcp_probe("10.0.0.2", 8080), {})  # noqa: S102 - execute our fixed probe with synthetic sockets
    assert outcome.value.code == expected
