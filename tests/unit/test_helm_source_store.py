"""Behavioral Helm render tests for the optional read-only source store (synthetic values only)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/charts/dq-scoring"
HELM = shutil.which("helm") or str(ROOT / ".tools/linux-amd64/helm")

pytestmark = pytest.mark.skipif(not Path(HELM).exists() and not shutil.which("helm"), reason="helm binary unavailable")

SOURCE_SVC = {"name": "source-s3", "namespace": "shared-data", "port": 443, "podSelector": {"app": "source-s3"}}
SOURCE = {
    "enabled": True,
    "endpoint": "https://source-s3.shared-data.svc.cluster.local:443",
    "useSsl": True,
    "bucket": "synthetic-source",
    "tenantPrefixes": {"00000000-0000-0000-0000-000000000001": ["shared/a/"]},
    "existingSecret": "source-ro",
    "caSecret": "source-ca",
    "allowedService": SOURCE_SVC,
}
PROTECTED = {
    "global": {"appEnv": "production"},
    "minio": {"useSsl": True, "endpoint": "https://minio.dq-data.svc.cluster.local:9000"},
    "postgres": {"host": "pg.dq-data.svc.cluster.local"},
    "spark": {"master": "k8s://https://kubernetes.default.svc.cluster.local:443"},
    "ingress": {
        "annotations": {"traefik.ingress.kubernetes.io/router.entrypoints": "websecure"},
        "tls": {"existingSecret": "ingress-tls"},
    },
    "security": {
        "protectedProcessing": {
            "enabled": True,
            "apiTlsSecret": "api-tls",
            "caSecret": "protected-ca",
            "sparkSecuritySecret": "spark-sec",
            "apiServerName": "api.example.test",
            "apiScratchSizeLimit": "256Mi",
            "scratchSizeLimit": "256Mi",
            "kubernetesApiCIDRs": ["10.0.0.0/24"],
            "kubernetesApiPort": 6443,
            "allowedServices": {
                "postgres": {"name": "pg", "namespace": "dq-data", "port": 5432, "podSelector": {"app": "pg"}},
                "minio": {"name": "minio", "namespace": "dq-data", "port": 9000, "podSelector": {"app": "minio"}},
                "ingressController": {"namespace": "traefik", "podSelector": {"app": "traefik"}},
            },
        }
    },
    "workers": {k: {"keda": {"enabled": False}} for k in ("fastLane", "heavyLane", "scheduledLane")},
}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def _render(tmp_path: Path, values: dict) -> subprocess.CompletedProcess[str]:
    f = tmp_path / "values.yaml"
    f.write_text(json.dumps(values))
    return subprocess.run(
        [HELM, "template", "rel", str(CHART), "-n", "dq", "-f", str(f)], capture_output=True, text=True, check=False
    )


def _docs(proc: subprocess.CompletedProcess[str]) -> list[dict]:
    assert proc.returncode == 0, proc.stderr
    parsed = subprocess.run(
        ['bun', '-e', 'console.log(JSON.stringify((await Bun.stdin.text()).split(/^---\\s*$/m).filter(s => s.trim()).map(s => Bun.YAML.parse(s))))'],
        input=proc.stdout, capture_output=True, text=True, check=True,
    )
    return [doc for doc in json.loads(parsed.stdout) if doc]


def _env(doc: dict) -> dict[str, dict]:
    return {e["name"]: e for c in doc["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}


def _by(docs: list[dict], kind: str, suffix: str) -> list[dict]:
    return [d for d in docs if d["kind"] == kind and d["metadata"]["name"].endswith(suffix)]


def test_disabled_source_is_default_and_adds_nothing(tmp_path: Path) -> None:
    docs = _docs(_render(tmp_path, {}))
    cm = _by(docs, "ConfigMap", "-config")[0]["data"]

    assert cm["DQ_SOURCE_S3_ENABLED"] == "false"
    assert not [k for k in cm if k.startswith("DQ_SOURCE_S3_") and k != "DQ_SOURCE_S3_ENABLED"]
    for dep in (d for d in docs if d["kind"] == "Deployment"):
        assert not [n for n in _env(dep) if n.startswith("DQ_SOURCE_S3_")]
        assert "source-ca" not in json.dumps(dep)


def test_enabled_source_wires_secret_refs_ca_and_nonsecret_config(tmp_path: Path) -> None:
    docs = _docs(_render(tmp_path, {"sourceStore": SOURCE}))
    cm = _by(docs, "ConfigMap", "-config")[0]["data"]

    assert cm["DQ_SOURCE_S3_ENABLED"] == "true"
    assert cm["DQ_SOURCE_S3_BUCKET"] == "synthetic-source"
    assert json.loads(cm["DQ_SOURCE_S3_TENANT_PREFIXES"]) == SOURCE["tenantPrefixes"]
    assert cm["DQ_SOURCE_S3_CA_BUNDLE"] == "/opt/dq/source-ca/source-s3-ca.pem"
    assert cm["DQ_SOURCE_S3_EXECUTOR_SECRET"] == "source-ro"
    assert not [k for k in cm if "ACCESS_KEY" in k]

    deployments = [d for d in docs if d["kind"] == "Deployment" and "ui" not in d["metadata"]["name"]]
    assert {d["metadata"]["labels"]["app.kubernetes.io/component"] for d in deployments} == {"api", "import", "worker"}
    for dep in deployments:
        env = _env(dep)
        ref = env["DQ_SOURCE_S3_SECRET_ACCESS_KEY"]["valueFrom"]["secretKeyRef"]
        assert ref == {"name": "source-ro", "key": "secret_key"}
        assert "value" not in env["DQ_SOURCE_S3_ACCESS_KEY_ID"]
        spec = dep["spec"]["template"]["spec"]
        assert any(v["name"] == "source-ca" and v["secret"]["secretName"] == "source-ca" for v in spec["volumes"])
        assert any(
            m["mountPath"] == "/opt/dq/source-ca" and m["readOnly"] for c in spec["containers"] for m in c["volumeMounts"]
        )


@pytest.mark.parametrize("missing", ["endpoint", "bucket", "existingSecret", "tenantPrefixes"])
def test_enabled_source_requires_core_fields(tmp_path: Path, missing: str) -> None:
    empty = {} if missing == "tenantPrefixes" else ""
    proc = _render(tmp_path, {"sourceStore": {**SOURCE, missing: empty}})

    assert proc.returncode != 0
    assert f"sourceStore.{missing}" in proc.stderr


def test_protected_source_policies_allow_exact_service_in_all_four(tmp_path: Path) -> None:
    docs = _docs(_render(tmp_path, _merge(PROTECTED, {"sourceStore": SOURCE})))
    policies = {p["metadata"]["name"].rsplit("-", 1)[-1]: p for p in docs if p["kind"] == "CiliumNetworkPolicy"}
    fqdn = "source-s3.shared-data.svc.cluster.local"

    for role in ("api", "import", "driver", "executor"):
        egress = policies[role]["spec"]["egress"]
        names = {r["matchName"] for e in egress for p in e.get("toPorts", []) for r in p.get("rules", {}).get("dns", [])}
        assert fqdn in names, role
        svc = [
            e for e in egress
            if e.get("toEndpoints", [{}])[0].get("matchLabels", {}).get("k8s:io.kubernetes.pod.namespace") == "shared-data"
        ]
        assert len(svc) == 1 and svc[0]["toEndpoints"][0]["matchLabels"]["app"] == "source-s3", role
        assert svc[0]["toPorts"][0]["ports"] == [{"port": "443", "protocol": "TCP"}]
        assert not any(e.get("toEntities") or e.get("toCIDR") for e in egress if e is svc[0])
        assert not any("*" in n for n in names)


def test_protected_source_sharing_owned_service_is_not_duplicated(tmp_path: Path) -> None:
    same = {"name": "minio", "namespace": "dq-data", "port": 9000, "podSelector": {"app": "minio"}}
    values = _merge(
        PROTECTED,
        {"sourceStore": {**SOURCE, "endpoint": "https://minio.dq-data.svc.cluster.local:9000", "allowedService": same}},
    )
    docs = _docs(_render(tmp_path, values))
    api = next(p for p in docs if p['kind'] == 'CiliumNetworkPolicy' and p['metadata']['name'].endswith('-api'))
    to_minio = [
        e for e in api["spec"]["egress"]
        if e.get("toEndpoints", [{}])[0].get("matchLabels", {}).get("app") == "minio"
    ]

    assert len(to_minio) == 1


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"endpoint": "https://other.shared-data.svc.cluster.local:443"}, "sourceStore.endpoint must equal"),
        ({"endpoint": "http://source-s3.shared-data.svc.cluster.local:443"}, "sourceStore.endpoint must equal"),
        ({"caSecret": ""}, "sourceStore.caSecret is required"),
        ({"caSecret": "protected-ca"}, "dedicated Secret"),
        ({"useSsl": False}, "useSsl must be true"),
        ({"allowedService": {**SOURCE_SVC, "name": "*"}}, "exact service name"),
        ({"allowedService": {**SOURCE_SVC, "podSelector": {}}}, "podSelector"),
    ],
)
def test_protected_source_fails_closed(tmp_path: Path, patch: dict, message: str) -> None:
    proc = _render(tmp_path, _merge(PROTECTED, {"sourceStore": {**SOURCE, **patch}}))

    assert proc.returncode != 0
    assert message in proc.stderr
