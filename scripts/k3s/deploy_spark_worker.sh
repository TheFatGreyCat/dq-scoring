#!/usr/bin/env bash
# Explicit single-node sandbox deployment; credentials travel through stdin only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
for arg in "$@"; do
    case "$arg" in
        --protected*|--secure*)
            echo "ERROR: deploy_spark_worker.sh does not support the protected processing profile." >&2
            echo "Use Helm with values-secure.yaml instead:" >&2
            echo "  helm upgrade --install <release> deploy/charts/dq-scoring -n <ns> -f deploy/charts/dq-scoring/values-secure.yaml -f <operator-values>.yaml" >&2
            exit 1
            ;;
    esac
done
if [[ "${DQ_PROTECTED_PROCESSING_ENABLED:-false}" =~ ^(1|true|TRUE|yes|YES)$ ]]; then
    echo "ERROR: DQ_PROTECTED_PROCESSING_ENABLED is enabled. deploy_spark_worker.sh does not support protected processing." >&2
    echo "Use Helm with values-secure.yaml instead:" >&2
    echo "  helm upgrade --install <release> deploy/charts/dq-scoring -n <ns> -f deploy/charts/dq-scoring/values-secure.yaml -f <operator-values>.yaml" >&2
    exit 1
fi
[[ $# == 0 ]] || { echo "No data-root argument: runtime uses MinIO only." >&2; exit 1; }
node_ip="$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
[[ -n "$node_ip" ]] || { echo "Node InternalIP unavailable" >&2; exit 1; }
kubectl apply -f "$ROOT/deploy/k8s/spark-worker/namespace.yaml"
ROOT="$ROOT" NODE_IP="$node_ip" uv run --project "$ROOT" --locked python - <<'PY' | kubectl apply --server-side --field-manager=dq-deploy-script -f -
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from dotenv import dotenv_values
root_dir = Path(os.environ.get('ROOT', Path.cwd()))
env_file = Path(os.environ.get('DQ_ENV_FILE', root_dir / '.env'))
env_vals = dotenv_values(env_file) if env_file.is_file() else {}
values = {**env_vals, **os.environ}
required = ['DQ_WORKER_POSTGRES_DSN', 'DQ_S3_ENDPOINT_URL', 'DQ_S3_ACCESS_KEY_ID', 'DQ_S3_SECRET_ACCESS_KEY']
if any(not values.get(key) for key in required):
    raise SystemExit('Worker DSN and S3 environment are required.')
def routable(value):
    url = urlsplit(value)
    if url.hostname in ('localhost','127.0.0.1'):
        auth = url.netloc.rsplit('@',1)[0]+'@' if '@' in url.netloc else ''
        return urlunsplit(url._replace(netloc=auth+os.environ['NODE_IP']+(f':{url.port}' if url.port else '')))
    return value
for name, data in [('dq-scoring-worker-db',{'DQ_WORKER_POSTGRES_DSN':routable(values['DQ_WORKER_POSTGRES_DSN'])}), ('dq-minio-secret',{'access_key':values['DQ_S3_ACCESS_KEY_ID'],'secret_key':values['DQ_S3_SECRET_ACCESS_KEY']})]:
    print(json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':'dq-scoring'},'type':'Opaque','data':{k:base64.b64encode(v.encode()).decode() for k,v in data.items()}}))
PY
kubectl kustomize "$ROOT/deploy/k8s/spark-worker" | kubectl apply -f -
ROOT="$ROOT" NODE_IP="$node_ip" uv run --project "$ROOT" --locked python - <<'PY' | kubectl apply --server-side --field-manager=dq-deploy-script -f -
import json
import os
from pathlib import Path
from dotenv import dotenv_values
from urllib.parse import urlsplit, urlunsplit
root_dir = Path(os.environ.get('ROOT', Path.cwd()))
env_file = Path(os.environ.get('DQ_ENV_FILE', root_dir / '.env'))
env_vals = dotenv_values(env_file) if env_file.is_file() else {}
values = {**env_vals, **os.environ}
url = urlsplit(values['DQ_S3_ENDPOINT_URL'])
if url.hostname in ('localhost','127.0.0.1'):
    url = url._replace(netloc=os.environ['NODE_IP']+(f':{url.port}' if url.port else ''))
print(json.dumps({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'dq-spark-config','namespace':'dq-scoring'},'data':{'DQ_S3_ENDPOINT_URL':urlunsplit(url)}}))
PY
kubectl -n dq-scoring rollout status deployment/dq-spark-worker --timeout=180s
kubectl -n dq-scoring rollout status deployment/dq-import-worker --timeout=180s
