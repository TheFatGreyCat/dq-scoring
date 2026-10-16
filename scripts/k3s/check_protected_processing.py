#!/usr/bin/env python3
"""Read-only preflight checker for protected processing profile on Kubernetes / k3s.

Performs read-only validation (get / list / describe / exec) of CRDs, Cilium enforcement,
policy overlap, secret isolation, Spark security configuration, and egress controls.
Exits 0 if and only if all security invariants are satisfied; exits non-zero on any failure.
Never dumps secrets, tokens, or credentials to standard output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _run_kubectl(args: list[str], *, kubeconfig: str | None = None) -> tuple[int, str, str]:
    """Execute read-only kubectl command and return (exit_code, stdout, stderr)."""
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    cmd.extend(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 1, "", "Kubernetes command unavailable or timed out"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _blocked_tcp_probe(host: str, port: int) -> str:
    return (
        "import socket, errno\n"
        "s=socket.socket(); s.settimeout(3)\n"
        f"result=s.connect_ex(({host!r}, {port}))\n"
        "raise SystemExit(0 if result in (errno.ETIMEDOUT, errno.EAGAIN, errno.EACCES, errno.EPERM) else 1)\n"
    )


def _exec_in_pod(
    namespace: str, pod_name: str, container: str, python_code: str, *, kubeconfig: str | None = None
) -> tuple[int, str]:
    """Execute python snippet inside target container and return (exit_status, stdout)."""
    code, stdout, _ = _run_kubectl(
        [
            "exec",
            "-n",
            namespace,
            pod_name,
            "-c",
            container,
            "--",
            "python3",
            "-c",
            python_code,
        ],
        kubeconfig=kubeconfig,
    )
    return code, stdout


def check_crds(kubeconfig: str | None) -> bool:
    """Verify required CRDs (CiliumNetworkPolicy, Traefik ServersTransport) exist."""
    print("[1/6] Checking required CRDs...")
    code, out, _ = _run_kubectl(["get", "crd", "-o", "jsonpath={.items[*].metadata.name}"], kubeconfig=kubeconfig)
    if code != 0:
        print("  [FAIL] Unable to query Kubernetes CRDs (cluster unreachable or insufficient privileges)")
        return False

    crds = out.split()
    has_cilium = any("ciliumnetworkpolicies" in name for name in crds)
    has_traefik = any("serverstransports" in name for name in crds)

    if not has_cilium:
        print("  [FAIL] Missing CRD: ciliumnetworkpolicies.cilium.io is required for protected processing")
        return False
    if not has_traefik:
        print("  [FAIL] Missing CRD: serverstransports.traefik.io is required for protected processing")
        return False

    print("  [PASS] CiliumNetworkPolicy and Traefik ServersTransport CRDs installed")
    return True


def check_cilium_enforcement(namespace: str, release: str, kubeconfig: str | None) -> bool:
    """Verify Cilium agents are running and actively enforcing on release endpoints."""
    print("[2/6] Checking Cilium agent enforcement and endpoint status...")

    # 1. Inspect Cilium daemonset agent pods
    code, out, _ = _run_kubectl(
        ["get", "pods", "-n", "kube-system", "-l", "k8s-app=cilium", "-o", "jsonpath={.items[*].metadata.name}"],
        kubeconfig=kubeconfig,
    )
    if code != 0 or not out:
        print("  [FAIL] No Cilium agent pods found in kube-system")
        return False

    agent_pod = out.split()[0]
    st_code, st_out, _ = _run_kubectl(
        ["exec", "-n", "kube-system", agent_pod, "-c", "cilium-agent", "--", "cilium", "status", "--brief"],
        kubeconfig=kubeconfig,
    )
    if st_code != 0 or "OK" not in st_out:
        print(f"  [FAIL] Cilium agent {agent_pod} status check failed: {st_out}")
        return False

    # 2. Verify CiliumEndpoints exist and are in 'ready' state in target namespace
    ep_code, ep_out, _ = _run_kubectl(
        ["get", "ciliumendpoints", "-n", namespace, "-o", "json"],
        kubeconfig=kubeconfig,
    )
    if ep_code != 0:
        print(f"  [FAIL] Unable to list CiliumEndpoints in namespace '{namespace}'")
        return False

    try:
        ep_data = json.loads(ep_out)
        endpoints = ep_data.get("items", [])
        if not endpoints:
            print(f"  [FAIL] No CiliumEndpoints found in namespace '{namespace}' (Cilium CNI not managing pods)")
            return False

        for ep in endpoints:
            name = ep.get("metadata", {}).get("name", "")
            state = ep.get("status", {}).get("state")
            if state != "ready":
                print(f"  [FAIL] CiliumEndpoint '{name}' is in state '{state}', expected 'ready'")
                return False
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"  [FAIL] Failed to parse CiliumEndpoints status: {type(exc).__name__}")
        return False

    enforced = set()
    for agent in out.split():
        code, payload, _ = _run_kubectl(
            ["exec", "-n", "kube-system", agent, "-c", "cilium-agent", "--", "cilium", "endpoint", "list", "-o", "json"],
            kubeconfig=kubeconfig,
        )
        if code != 0:
            return False
        try:
            for endpoint in json.loads(payload):
                status = endpoint.get("status", {})
                identifiers = status.get("external-identifiers", {})
                if identifiers.get("k8s-namespace") != namespace:
                    continue
                realized = status.get("policy", {}).get("realized", {})
                options = status.get("realized", {}).get("options", {})
                if realized.get("policy-enabled") != "both" or options.get("PolicyAuditMode") != "Disabled":
                    print("  [FAIL] Workload endpoint is not enforcing ingress and egress")
                    return False
                enforced.add(identifiers.get("k8s-pod-name"))
        except (ValueError, TypeError, AttributeError):
            return False
    if any(endpoint.get("metadata", {}).get("name") not in enforced for endpoint in endpoints):
        print("  [FAIL] Endpoint enforcement could not be measured on its Cilium agent")
        return False

    print("  [PASS] Cilium agents healthy and all namespace endpoints in 'ready' enforcing state")
    return True


def check_network_policies(namespace: str, release: str, kubeconfig: str | None) -> bool:
    """Ensure strict isolation: no permissive union policies (0.0.0.0/0, empty egress, broad namespaces)."""
    print(f"[3/6] Inspecting network policies in namespace '{namespace}'...")

    # 1. Audit standard Kubernetes NetworkPolicies
    code, out, _ = _run_kubectl(["get", "networkpolicy", "-n", namespace, "-o", "json"], kubeconfig=kubeconfig)
    if code != 0:
        print(f"  [FAIL] Unable to query NetworkPolicies in namespace '{namespace}'")
        return False

    try:
        data = json.loads(out)
        for np in data.get("items", []):
            name = np.get("metadata", {}).get("name", "")
            spec = np.get("spec", {})
            for egress in spec.get("egress", []):
                # An empty egress rule ({}) allows ALL egress
                if not egress:
                    print(f"  [FAIL] Permissive egress policy detected: {name} contains empty egress rule (allow-all)")
                    return False
                to_list = egress.get("to", [])
                if not to_list:
                    print(f"  [FAIL] Permissive egress policy detected: {name} has rule without destination restrictions")
                    return False
                for to_rule in to_list:
                    # Check broad namespaceSelector: {} with no podSelector
                    if "namespaceSelector" in to_rule and to_rule["namespaceSelector"] == {} and not to_rule.get("podSelector"):
                        print(f"  [FAIL] Permissive egress policy detected: {name} allows egress to all namespaces")
                        return False
                    # Check broad IP CIDRs (0.0.0.0/0 or ::/0)
                    ip_block = to_rule.get("ipBlock", {})
                    cidr = ip_block.get("cidr", "")
                    if cidr in ("0.0.0.0/0", "::/0"):
                        print(f"  [FAIL] Permissive egress policy detected: {name} allows unrestricted {cidr}")
                        return False
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"  [FAIL] Failed to evaluate NetworkPolicies: {type(exc).__name__}")
        return False

    # 2. Audit CiliumNetworkPolicies
    cnp_code, cnp_out, _ = _run_kubectl(["get", "ciliumnetworkpolicy", "-n", namespace, "-o", "json"], kubeconfig=kubeconfig)
    if cnp_code != 0:
        print(f"  [FAIL] Unable to query CiliumNetworkPolicies in namespace '{namespace}'")
        return False

    try:
        cnp_data = json.loads(cnp_out)
        items = cnp_data.get("items", [])
        if not items:
            print(f"  [FAIL] No CiliumNetworkPolicies found in namespace '{namespace}'")
            return False

        cnp_names = [item.get("metadata", {}).get("name", "") for item in items]
        required_prefixes = [f"{release}-dq-scoring-{role}" for role in ("api", "import", "driver", "executor")]
        for prefix in required_prefixes:
            if not any(name.startswith(prefix) for name in cnp_names):
                print(f"  [FAIL] Missing required CiliumNetworkPolicy with prefix '{prefix}'")
                return False

        for cnp in items:
            name = cnp.get("metadata", {}).get("name", "")
            spec = cnp.get("spec", {})
            for egress in spec.get("egress", []):
                destinations = ("toEndpoints", "toCIDR", "toCIDRSet", "toEntities", "toFQDNs", "toServices")
                if not any(egress.get(key) for key in destinations) or any(not endpoint for endpoint in egress.get("toEndpoints", [])):
                    print(f"  [FAIL] Unrestricted Cilium destination in {name}")
                    return False
                for ports in egress.get("toPorts", []):
                    for dns in ports.get("rules", {}).get("dns", []):
                        if "matchPattern" in dns or not dns.get("matchName") or "*" in dns.get("matchName", ""):
                            print(f"  [FAIL] Non-exact DNS permission in {name}")
                            return False
                # Check for broad entity targets
                for entity in egress.get("toEntities", []):
                    if entity in ("all", "world", "cluster"):
                        print(f"  [FAIL] Permissive Cilium egress detected: {name} allows entity '{entity}'")
                        return False
                # Check for broad CIDRs
                for cidr in egress.get("toCIDR", []):
                    if cidr in ("0.0.0.0/0", "::/0"):
                        print(f"  [FAIL] Permissive Cilium egress detected: {name} allows CIDR '{cidr}'")
                        return False
                for cset in egress.get("toCIDRSet", []):
                    if cset.get("cidr") in ("0.0.0.0/0", "::/0"):
                        print(f"  [FAIL] Permissive Cilium egress detected: {name} allows CIDRSet '{cset.get('cidr')}'")
                        return False
                # Check for wildcard FQDNs
                for fqdn in egress.get("toFQDNs", []):
                    pattern = fqdn.get("matchPattern", "")
                    if pattern:
                        print(f"  [FAIL] Permissive Cilium egress detected: {name} allows wildcard FQDN '{pattern}'")
                        return False
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"  [FAIL] Failed to evaluate CiliumNetworkPolicies: {type(exc).__name__}")
        return False

    print("  [PASS] No permissive 0.0.0.0/0, wildcard DNS, or broad entity egress rules; all required policies present")
    return True


def check_secret_isolation_and_config(namespace: str, release: str, kubeconfig: str | None) -> bool:
    """Verify role secret isolation and configuration invariants across all release workloads."""
    print(f"[4/6] Verifying secret isolation and workload mounts in namespace '{namespace}'...")

    # 1. ConfigMap validation
    code, out, _ = _run_kubectl(["get", "configmap", f"{release}-dq-scoring-config", "-n", namespace, "-o", "json"], kubeconfig=kubeconfig)
    if code != 0:
        print(f"  [FAIL] Unable to inspect ConfigMap '{release}-dq-scoring-config'")
        return False

    try:
        cm_data = json.loads(out).get("data", {})
        if cm_data.get("DQ_PROTECTED_PROCESSING_ENABLED") != "true":
            print("  [FAIL] DQ_PROTECTED_PROCESSING_ENABLED is not 'true' in ConfigMap")
            return False

        for key, value in cm_data.items():
            if any(term in key.lower() for term in ("password", "private_key", "secret_access_key")):
                print(f"  [FAIL] Plaintext credential key '{key}' found rendered in plain ConfigMap")
                return False
            if value and "postgres://" in value and "@" in value:
                print(f"  [FAIL] Connection string with credentials found in ConfigMap key '{key}'")
                return False
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"  [FAIL] Failed to validate ConfigMap: {type(exc).__name__}")
        return False

    # 2. Workload deployment secret isolation audit across all lanes and components
    components = ["api", "worker", "import"]
    deployments_by_comp: dict[str, list[dict]] = {}

    for comp in components:
        dep_code, dep_out, _ = _run_kubectl(
            ["get", "deployment", "-n", namespace, "-l", f"app.kubernetes.io/instance={release},app.kubernetes.io/component={comp}", "-o", "json"],
            kubeconfig=kubeconfig,
        )
        if dep_code != 0:
            print(f"  [FAIL] Unable to query deployment for component '{comp}'")
            return False

        try:
            dep_items = json.loads(dep_out).get("items", [])
            if not dep_items:
                print(f"  [FAIL] No deployment found for release component '{comp}'")
                return False
            deployments_by_comp[comp] = dep_items
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"  [FAIL] Failed to audit deployment for '{comp}': {type(exc).__name__}")
            return False

    def _inspect_dep(dep: dict) -> dict:
        name = dep.get("metadata", {}).get("name", "unknown")
        spec = dep.get("spec", {}).get("template", {}).get("spec", {})
        vols = spec.get("volumes", [])
        containers = spec.get("containers", []) + spec.get("initContainers", [])

        vol_secrets: set[str] = set()
        vol_items: dict[str, set[str]] = {}
        has_memory_scratch = False

        for v in vols:
            if v.get("name") == "scratch":
                ed = v.get("emptyDir", {})
                if ed.get("medium") == "Memory":
                    has_memory_scratch = True
            if "secret" in v:
                sname = v["secret"].get("secretName", "")
                if sname:
                    vol_secrets.add(sname)
                    for item in v["secret"].get("items", []):
                        if "key" in item:
                            vol_items.setdefault(sname, set()).add(item["key"])
            if "projected" in v:
                for src in v["projected"].get("sources", []):
                    if "secret" in src:
                        sname = src["secret"].get("name", "")
                        if sname:
                            vol_secrets.add(sname)
                            for item in src["secret"].get("items", []):
                                if "key" in item:
                                    vol_items.setdefault(sname, set()).add(item["key"])

        env_secrets: set[str] = set()
        env_from_secrets: set[str] = set()
        env_var_names: set[str] = set()
        env_var_to_secret: dict[str, str] = {}
        env_secret_keys: set[str] = set()

        for c in containers:
            for env_item in c.get("env", []):
                var_name = env_item.get("name", "")
                if var_name:
                    env_var_names.add(var_name)
                sec_ref = env_item.get("valueFrom", {}).get("secretKeyRef", {})
                if sec_ref and sec_ref.get("name"):
                    sname = sec_ref.get("name")
                    skey = sec_ref.get("key", "")
                    env_secrets.add(sname)
                    if var_name:
                        env_var_to_secret[var_name] = sname
                    if skey:
                        env_secret_keys.add(skey)
            for ef in c.get("envFrom", []):
                sref = ef.get("secretRef", {})
                if sref and sref.get("name"):
                    env_from_secrets.add(sref.get("name"))

        all_secrets = vol_secrets | env_secrets | env_from_secrets

        return {
            "name": name,
            "has_memory_scratch": has_memory_scratch,
            "vol_secrets": vol_secrets,
            "vol_items": vol_items,
            "env_secrets": env_secrets,
            "env_from_secrets": env_from_secrets,
            "env_var_names": env_var_names,
            "env_var_to_secret": env_var_to_secret,
            "env_secret_keys": env_secret_keys,
            "all_secrets": all_secrets,
        }

    parsed_deps: dict[str, list[dict]] = {
        comp: [_inspect_dep(d) for d in deps]
        for comp, deps in deployments_by_comp.items()
    }

    # 3. Derive role secret identities
    # API private TLS secret: mounts tls.key
    api_tls_secrets: set[str] = set()
    for info in parsed_deps["api"]:
        for sname, keys in info["vol_items"].items():
            if "tls.key" in keys:
                api_tls_secrets.add(sname)
        for sname in info["all_secrets"]:
            if "api-tls" in sname:
                api_tls_secrets.add(sname)

    if not api_tls_secrets:
        print("  [FAIL] API deployment does not mount a TLS private key secret (tls.key)")
        return False

    # Spark security secret: mounts rpc-auth
    spark_security_secrets: set[str] = set()
    for info in parsed_deps["worker"]:
        for sname, keys in info["vol_items"].items():
            if "rpc-auth" in keys:
                spark_security_secrets.add(sname)
        for sname in info["all_secrets"]:
            if "spark-security" in sname or "spark-defaults" in sname:
                spark_security_secrets.add(sname)

    if not spark_security_secrets:
        print("  [FAIL] Worker deployment does not mount a Spark RPC security secret (rpc-auth)")
        return False

    # Role env secrets
    api_auth_secrets: set[str] = set()
    api_dsn_secrets: set[str] = set()
    for info in parsed_deps["api"]:
        if "DQ_AUTH_SECRET_KEY" in info["env_var_to_secret"]:
            api_auth_secrets.add(info["env_var_to_secret"]["DQ_AUTH_SECRET_KEY"])
        if "DQ_POSTGRES_DSN" in info["env_var_to_secret"]:
            api_dsn_secrets.add(info["env_var_to_secret"]["DQ_POSTGRES_DSN"])

    worker_dsn_secrets: set[str] = set()
    for info in parsed_deps["worker"]:
        if "DQ_WORKER_POSTGRES_DSN" in info["env_var_to_secret"]:
            worker_dsn_secrets.add(info["env_var_to_secret"]["DQ_WORKER_POSTGRES_DSN"])

    # 4. Audit all lane deployments across components
    for comp in components:
        for info in parsed_deps[comp]:
            dep_name = info["name"]

            # Scratch memory emptyDir requirement
            if not info["has_memory_scratch"]:
                print(f"  [FAIL] Component '{comp}' deployment '{dep_name}' does not mount a Memory-backed (tmpfs) scratch emptyDir")
                return False

            if comp == "api":
                forbidden_spark = info["all_secrets"] & spark_security_secrets
                if forbidden_spark or any("spark-security" in s for s in info["all_secrets"]):
                    print(f"  [FAIL] API deployment '{dep_name}' mounts forbidden Spark security secret")
                    return False
                if any("rpc-auth" in keys for keys in info["vol_items"].values()) or "rpc-auth" in info["env_secret_keys"]:
                    print(f"  [FAIL] API deployment '{dep_name}' mounts forbidden Spark rpc-auth")
                    return False
                if "DQ_WORKER_POSTGRES_DSN" in info["env_var_names"]:
                    print(f"  [FAIL] API deployment '{dep_name}' defines forbidden Worker DSN environment variable")
                    return False
                if worker_dsn_secrets and (info["all_secrets"] & worker_dsn_secrets):
                    print(f"  [FAIL] API deployment '{dep_name}' references forbidden Worker DSN secret")
                    return False

            elif comp == "worker":
                forbidden_api = info["all_secrets"] & api_tls_secrets
                if forbidden_api or any("api-tls" in s for s in info["all_secrets"]):
                    print(f"  [FAIL] Worker deployment '{dep_name}' mounts forbidden API private TLS secret")
                    return False
                if any("tls.key" in keys for keys in info["vol_items"].values()) or "tls.key" in info["env_secret_keys"]:
                    print(f"  [FAIL] Worker deployment '{dep_name}' mounts forbidden API private key (tls.key)")
                    return False
                if "DQ_AUTH_SECRET_KEY" in info["env_var_names"]:
                    print(f"  [FAIL] Worker deployment '{dep_name}' defines forbidden API auth key environment variable")
                    return False
                if api_auth_secrets and (info["all_secrets"] & api_auth_secrets):
                    print(f"  [FAIL] Worker deployment '{dep_name}' references forbidden API auth secret")
                    return False
                if "DQ_POSTGRES_DSN" in info["env_var_names"]:
                    print(f"  [FAIL] Worker deployment '{dep_name}' defines forbidden API DSN environment variable")
                    return False
                if api_dsn_secrets and (info["all_secrets"] & api_dsn_secrets):
                    print(f"  [FAIL] Worker deployment '{dep_name}' references forbidden API DSN secret")
                    return False

            elif comp == "import":
                forbidden_api = info["all_secrets"] & api_tls_secrets
                if forbidden_api or any("api-tls" in s for s in info["all_secrets"]):
                    print(f"  [FAIL] Import deployment '{dep_name}' mounts forbidden API private TLS secret")
                    return False
                if any("tls.key" in keys for keys in info["vol_items"].values()) or "tls.key" in info["env_secret_keys"]:
                    print(f"  [FAIL] Import deployment '{dep_name}' mounts forbidden API private key (tls.key)")
                    return False
                forbidden_spark = info["all_secrets"] & spark_security_secrets
                if forbidden_spark or any("spark-security" in s for s in info["all_secrets"]):
                    print(f"  [FAIL] Import deployment '{dep_name}' mounts forbidden Spark security secret")
                    return False
                if any("rpc-auth" in keys for keys in info["vol_items"].values()) or "rpc-auth" in info["env_secret_keys"]:
                    print(f"  [FAIL] Import deployment '{dep_name}' mounts forbidden Spark rpc-auth")
                    return False
                if "DQ_AUTH_SECRET_KEY" in info["env_var_names"]:
                    print(f"  [FAIL] Import deployment '{dep_name}' defines forbidden API auth key environment variable")
                    return False
                if api_auth_secrets and (info["all_secrets"] & api_auth_secrets):
                    print(f"  [FAIL] Import deployment '{dep_name}' references forbidden API auth secret")
                    return False
                if "DQ_POSTGRES_DSN" in info["env_var_names"]:
                    print(f"  [FAIL] Import deployment '{dep_name}' defines forbidden API DSN environment variable")
                    return False
                if api_dsn_secrets and (info["all_secrets"] & api_dsn_secrets):
                    print(f"  [FAIL] Import deployment '{dep_name}' references forbidden API DSN secret")
                    return False

    print("  [PASS] Secrets isolated per role, memory-backed scratch enforced, no plaintext credentials in ConfigMaps")
    return True


def check_spark_security_effective(namespace: str, release: str, kubeconfig: str | None) -> bool:
    """Verify Spark driver effective security configuration inside running worker pod."""
    print(f"[5/6] Checking Spark driver security configuration in '{namespace}'...")
    code, out, _ = _run_kubectl(
        [
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"app.kubernetes.io/instance={release},app.kubernetes.io/component=worker",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        kubeconfig=kubeconfig,
    )
    if code != 0 or not out:
        print("  [FAIL] No running worker pod found to inspect Spark effective config")
        return False

    pod_name = out
    probe_code = (
        "import os, shutil, subprocess\n"
        "from dq_scoring.adapters.compute.spark_settings import SparkSettings\n"
        "from dq_scoring.common.protected_transport import validate_protected_runtime\n"
        "s = SparkSettings()\n"
        "conf = s.to_spark_conf()\n"
        "assert conf.get('spark.authenticate') == 'true', 'spark.authenticate != true'\n"
        "assert conf.get('spark.ssl.rpc.enabled') == 'true', 'spark.ssl.rpc.enabled != true'\n"
        "assert conf.get('spark.ssl.rpc.protocol') == 'TLSv1.3', 'spark.ssl.rpc.protocol != TLSv1.3'\n"
        "assert conf.get('spark.io.encryption.enabled') == 'true', 'spark.io.encryption.enabled != true'\n"
        "assert conf.get('spark.io.encryption.keySizeBits') == '256', 'spark.io.encryption.keySizeBits != 256'\n"
        "assert conf.get('spark.ui.enabled') == 'false', 'spark.ui.enabled != false'\n"
        "assert conf.get('spark.eventLog.enabled') == 'false', 'spark.eventLog.enabled != false'\n"
        "assert conf.get('spark.port.maxRetries') == '0', 'spark.port.maxRetries != 0'\n"
        "assert conf.get('spark.driver.port') == '7078', 'spark.driver.port != 7078'\n"
        "assert conf.get('spark.blockManager.port') == '7079', 'spark.blockManager.port != 7079'\n"
        "assert conf.get('spark.kubernetes.executor.label.dq-scoring/protected') == 'true', 'missing protected label'\n"
        "print('SPARK_CONFIGURED_VERIFIED')\n"
        "validate_protected_runtime('worker')\n"
        "sec_dir = os.environ.get('DQ_SECURITY_DIR', '/opt/dq/security')\n"
        "conf_path = os.path.join(sec_dir, 'spark-defaults.conf')\n"
        "passwords = {}\n"
        "with open(conf_path) as f:\n"
        "    for line in f:\n"
        "        line = line.strip()\n"
        "        if not line or line.startswith('#'): continue\n"
        "        parts = line.split(None, 1) if (' ' in line or '\\t' in line) else line.split('=', 1)\n"
        "        if len(parts) == 2:\n"
        "            passwords[parts[0].strip()] = parts[1].strip()\n"
        "ks_pass = passwords.get('spark.ssl.rpc.keyStorePassword') or passwords.get('spark.ssl.keyStorePassword')\n"
        "ts_pass = passwords.get('spark.ssl.rpc.trustStorePassword') or passwords.get('spark.ssl.trustStorePassword')\n"
        "assert ks_pass, 'Missing keystore password in spark-defaults.conf'\n"
        "assert ts_pass, 'Missing truststore password in spark-defaults.conf'\n"
        "for suffix in ('KEY_PASSWORD', 'KEY_STORE_PASSWORD', 'TRUST_STORE_PASSWORD'):\n"
        "    assert os.environ.get('_SPARK_SSL_RPC_' + suffix), 'Missing RPC bootstrap password environment'\n"
        "keytool = shutil.which('keytool') or os.path.join(os.environ.get('JAVA_HOME', ''), 'bin', 'keytool')\n"
        "assert keytool and os.path.isfile(keytool), 'keytool binary not found in worker container'\n"
        "for name, path, pwd in [('keystore', os.path.join(sec_dir, 'keystore.jks'), ks_pass), ('truststore', os.path.join(sec_dir, 'truststore.jks'), ts_pass)]:\n"
        "    assert os.path.isfile(path), f'{name} file missing'\n"
        "    env = os.environ.copy()\n"
        "    env['STORE_PASS'] = pwd\n"
        "    res = subprocess.run([keytool, '-list', '-keystore', path, '-storepass:env', 'STORE_PASS'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)\n"
        "    assert res.returncode == 0, f'{name} validation failed (code {res.returncode})'\n"
        "print('SPARK_LIVE_VERIFIED')\n"
    )
    ret, ret_out = _exec_in_pod(namespace, pod_name, "worker", probe_code, kubeconfig=kubeconfig)
    configured_ok = "SPARK_CONFIGURED_VERIFIED" in ret_out
    live_ok = "SPARK_LIVE_VERIFIED" in ret_out

    if ret != 0 or not configured_ok or not live_ok:
        if not configured_ok:
            print(f"  [FAIL] Worker pod {pod_name} failed Spark configured security verification: {ret_out.strip()}")
        elif not live_ok:
            print(f"  [FAIL] Worker pod {pod_name} passed configured settings but failed actual live Spark runtime/keystore verification: {ret_out.strip()}")
        else:
            print(f"  [FAIL] Worker pod {pod_name} failed Spark security verification: {ret_out.strip()}")
        return False

    print("  [PASS] Configured Spark security settings verified (RPC TLSv1.3, authenticate, 256-bit encryption)")
    print("  [PASS] Actual live mounted Spark runtime and TLS keystores verified without secret leakage")
    return True

def check_egress_and_canary_probes(
    namespace: str,
    release: str,
    canary_host: str | None,
    canary_port: int,
    kubeconfig: str | None,
) -> bool:
    """Execute live TLS verification and network isolation probes against canary and forbidden targets."""
    print("[6/6] Executing TLS endpoint and network isolation probes...")

    # Find running pods
    def _get_pod(component: str) -> str | None:
        c, o, _ = _run_kubectl(
            [
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                f"app.kubernetes.io/instance={release},app.kubernetes.io/component={component}",
                "-o",
                "jsonpath={.items[0].metadata.name}",
            ],
            kubeconfig=kubeconfig,
        )
        return o if c == 0 and o else None

    pod_api = _get_pod("api")
    pod_worker = _get_pod("worker")
    pod_import = _get_pod("import")
    pod_probe = _get_pod("executor-probe")

    pods = [(pod_api, "api"), (pod_worker, "worker"), (pod_import, "import")]
    if not all(p for p, _ in pods) or not pod_probe or not canary_host:
        print("  [FAIL] API, worker, import, executor probe and live canary are required")
        return False

    tls_probe = '''
import os, socket, ssl, urllib.parse
import psycopg
from dq_scoring.common.protected_transport import require_protected_dsn
try:
    dsn = os.environ.get('DQ_WORKER_POSTGRES_DSN') or os.environ['DQ_POSTGRES_DSN']
    with psycopg.connect(require_protected_dsn(dsn), connect_timeout=5) as conn:
        assert conn.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()[0]
    url = urllib.parse.urlparse(os.environ['DQ_S3_ENDPOINT_URL'])
    assert url.scheme == 'https'
    ctx = ssl.create_default_context(cafile=os.environ['DQ_S3_CA_BUNDLE'])
    with socket.create_connection((url.hostname, url.port or 443), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname=url.hostname) as encrypted:
            assert encrypted.version() in ('TLSv1.2', 'TLSv1.3')
except Exception:
    raise SystemExit(1)
print('TLS_VERIFIED')
'''
    for pod, container in pods:
        code, result = _exec_in_pod(namespace, pod, container, tls_probe, kubeconfig=kubeconfig)
        if code != 0 or result != "TLS_VERIFIED":
            print(f"  [FAIL] Verified PostgreSQL/S3 TLS connection failed for {container}")
            return False

    # Resolve a live canary outside the restricted workloads. NXDOMAIN/refused is not proof.
    try:
        import ipaddress
        canary_ip = str(ipaddress.ip_address(canary_host))
    except ValueError:
        print("  [FAIL] Canary must be a verified live listener IP, not an unresolvable hostname")
        return False
    canary_probe = _blocked_tcp_probe(canary_ip, canary_port)
    dns_probe = (
        "import socket\n"
        "try:\n"
        "    socket.getaddrinfo('kubernetes.default.svc.cluster.local',443)\n"
        "except socket.gaierror:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    for pod, container in pods + [(pod_probe, "probe")]:
        code, _ = _exec_in_pod(namespace, pod, container, canary_probe, kubeconfig=kubeconfig)
        if code != 0:
            print(f"  [FAIL] Canary blocking could not be established for {container}")
            return False
    # This real, normally resolvable service is intentionally forbidden to executors.
    code, _ = _exec_in_pod(namespace, pod_probe, "probe", dns_probe, kubeconfig=kubeconfig)
    if code != 0:
        print("  [FAIL] Executor resolved forbidden Kubernetes API DNS")
        return False
    # Resolve protected service IPs through the API pod, not executor DNS (which is denied).
    targets_code = '''
import os, socket, json
print(json.dumps([[socket.gethostbyname(os.environ['DQ_POSTGRES_HOST']),int(os.environ.get('DQ_POSTGRES_PORT','5432'))], [os.environ['KUBERNETES_SERVICE_HOST'],int(os.environ.get('KUBERNETES_SERVICE_PORT','443'))]]))
'''
    code, result = _exec_in_pod(namespace, pod_api, "api", targets_code, kubeconfig=kubeconfig)
    try:
        targets = json.loads(result) if code == 0 else []
        if len(targets) != 2:
            return False
        for host, port in targets:
            ipaddress.ip_address(host)
            code, _ = _exec_in_pod(namespace, pod_probe, "probe", _blocked_tcp_probe(host, int(port)), kubeconfig=kubeconfig)
            if code != 0:
                print("  [FAIL] Executor PostgreSQL/Kubernetes API TCP isolation unverified")
                return False
    except (ValueError, TypeError):
        return False
    print("  [PASS] Live PostgreSQL/S3 TLS and canary isolation probes succeeded")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify protected processing profile invariants on Kubernetes / k3s cluster."
    )
    parser.add_argument("--namespace", default="dq-scoring", help="Namespace of the deployment (default: dq-scoring)")
    parser.add_argument("--release", default="dq-scoring", help="Helm release name (default: dq-scoring)")
    parser.add_argument("--canary-host", default=None, help="Hostname/IP of canary listener in non-allowlisted namespace")
    parser.add_argument("--canary-port", type=int, default=8080, help="Port of canary listener (default: 8080)")
    parser.add_argument("--kubeconfig", default=None, help="Path to kubeconfig file")

    args = parser.parse_args()

    checks = [
        check_crds(args.kubeconfig),
        check_cilium_enforcement(args.namespace, args.release, args.kubeconfig),
        check_network_policies(args.namespace, args.release, args.kubeconfig),
        check_secret_isolation_and_config(args.namespace, args.release, args.kubeconfig),
        check_spark_security_effective(args.namespace, args.release, args.kubeconfig),
        check_egress_and_canary_probes(
            args.namespace, args.release, args.canary_host, args.canary_port, args.kubeconfig
        ),
    ]

    if all(checks):
        print("\nPROTECTED_PROCESSING_PREFLIGHT: SUCCESS - All security profile invariants verified.")
        return 0

    print("\nPROTECTED_PROCESSING_PREFLIGHT: FAILED - Cluster environment does not satisfy protected processing profile.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
