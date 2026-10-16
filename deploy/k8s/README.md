# Spark & Import Workers on k3s (single node, 8 GB)

The evaluation worker daemon (`python -m dq_scoring.workers.daemon`) runs in k3s as the **Spark driver in client mode**. For each run it asks the Kubernetes API (in-cluster service account) for executor pods in the same namespace. Driver and executors use the **same baked image** (`dq-scoring-spark:dev`), resolving data purely via S3/S3A object storage on MinIO. No Spark Operator, no `spark-submit`, no Helm, and no `hostPath` volumes.

The import worker daemon (`python -m dq_scoring.workers.import_daemon`) runs alongside in the same namespace as `dq-import-worker`, processing chunked parquet ingestion with local temporary scratch space backed by an `emptyDir` volume with `fsGroup: 10001`.

## Files (`deploy/k8s/spark-worker/`, plain kustomize)

- `namespace.yaml`: namespace `dq-scoring`.
- `rbac.yaml`: ServiceAccount `dq-spark-driver` + Role/RoleBinding (pods, services, configmaps, persistentvolumeclaims) so the driver can manage executor pods.
- `quota.yaml`: ResourceQuota `limits.memory: 4096Mi`, `pods: "3"`; LimitRange default memory limit for containers that set none.
- `configmap.yaml`:
  - `dq-spark-config`: environment variables (`DQ_SPARK_*`, `DQ_S3_*`) consumed via `envFrom`.
  - `dq-spark-defaults`: `spark-defaults.conf` file mounted read-only to `/opt/spark/conf/spark-defaults.conf` for S3A executor credential secret references.
- `deployment.yaml`: `dq-spark-worker`, 1 replica, `Recreate` (max 1 concurrent Spark run), image `dq-scoring-spark:dev` (`imagePullPolicy: Never`), uid 10001. Ports 7078 (driver) and 7079 (block manager). Downward API provides `DQ_SPARK_DRIVER_HOST` and `DQ_SPARK_DRIVER_POD_NAME`.
- `import-deployment.yaml`: `dq-import-worker`, 1 replica, image `dq-scoring:dev` (`imagePullPolicy: Never`), uid 10001, `fsGroup: 10001` with `emptyDir` volume at `/scratch` for chunk staging.
- `kustomization.yaml`: aggregates namespace, rbac, quota, configmap, deployment, and import-deployment.

## Memory budget

| Pod | Memory | From |
| :--- | ---: | :--- |
| Driver (worker) | 1280 MiB | `DQ_SPARK_DRIVER_MEMORY=1024m` + `DQ_SPARK_DRIVER_MEMORY_OVERHEAD=256m` |
| Executor (x1) | 1920 MiB | `DQ_SPARK_EXECUTOR_MEMORY=1536m` + `DQ_SPARK_EXECUTOR_MEMORY_OVERHEAD=384m` |
| **Total** | **3200 MiB** | must be <= `DQ_SPARK_MAX_MEMORY_MB=4096`; the worker refuses to start otherwise |

## Secrets & Least Privilege

Credentials reach the cluster via Secret manifests applied by the deploy script piped through stdin; no credentials appear in CLI args, environment logs, or git:
- `dq-scoring-worker-db`: Secret containing `DQ_WORKER_POSTGRES_DSN` (dedicated worker role credentials, independent from API DSN).
- `dq-minio-secret`: Secret containing `access_key` and `secret_key`.

### MinIO Scoping & Operator Provisioning
- **Sandbox / Dev:** A shared `dq-minio-secret` provides access to staging, snapshots, and artifacts buckets.
- **Production Operator Provisioning:** Production operators provision scoped credentials rather than administrative keys:
  - *Evaluation Worker (`dq-spark-worker`):* Read-only on `snapshots` (`s3:GetObject`, `s3:ListBucket`), read-write on `artifacts` (`s3:PutObject`, `s3:GetObject`, `s3:ListBucket`).
  - *Import Worker (`dq-import-worker`):* Read-write on `staging` and `snapshots` (`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket`), no access to `artifacts`.
  - *API Service:* Read-write on `staging` (upload targets), read-only on `artifacts`.

## Deploy

Prerequisites: k3s running, `kubectl` access (`KUBECONFIG` defaults to `~/.kube/config`), PostgreSQL and MinIO reachable from the node.

```bash
# 1. Build application and Spark runner images
docker build -t dq-scoring:dev -f Dockerfile .
docker build -t dq-scoring-spark:dev -f Dockerfile.spark .

# 2. Import into k3s containerd
docker save dq-scoring:dev | sudo k3s ctr images import -
docker save dq-scoring-spark:dev | sudo k3s ctr images import -

# 3. Deploy workers via stdin (reads .env or DQ_ENV_FILE / environment variables)
bash scripts/k3s/deploy_spark_worker.sh
```

The deploy script:
1. Resolves worker DSN and S3 credentials from environment or `.env` and adapts `localhost`/`127.0.0.1` endpoints to the node's InternalIP for in-cluster routing;
2. Applies namespace `dq-scoring` and pipes Secret manifests (`dq-scoring-worker-db`, `dq-minio-secret`) directly to `kubectl apply --server-side` without echoing;
3. Applies `kubectl kustomize deploy/k8s/spark-worker` without `hostPath` bindings;
4. Patches `DQ_S3_ENDPOINT_URL` on `dq-spark-config` with the node-routable endpoint;
5. Waits for rollout completion of `dq-spark-worker` and `dq-import-worker`.

## Operations

- **Check:**
  ```bash
  kubectl -n dq-scoring get pods
  kubectl -n dq-scoring logs -f deploy/dq-spark-worker
  kubectl -n dq-scoring logs -f deploy/dq-import-worker
  ```
- **Restart:**
  ```bash
  kubectl -n dq-scoring rollout restart deploy/dq-spark-worker deploy/dq-import-worker
  ```
- **Stop:**
  ```bash
  kubectl delete -k deploy/k8s/spark-worker
  ```

## Protected Processing Profile

The raw manifests in `deploy/k8s/spark-worker` and `scripts/k3s/deploy_spark_worker.sh` provide a minimal single-node sandbox configuration for development. They do **not** provide TLS termination, verified CA transport, egress network isolation, or Spark RPC/shuffle encryption.

To deploy the protected processing profile (Kubernetes/k3s with Cilium egress filtering and Traefik HTTPS termination), use the Helm chart with the secure profile overlay:

```bash
helm upgrade --install dq-scoring deploy/charts/dq-scoring \
  --namespace dq-scoring \
  -f deploy/charts/dq-scoring/values-secure.yaml \
  -f <operator-values>.yaml
```

To verify cluster prerequisites, enforcement, and TLS configuration before running protected workloads, run the read-only preflight checker:

```bash
python scripts/k3s/check_protected_processing.py \
  --namespace dq-scoring \
  --release dq-scoring \
  --canary-host <synthetic-canary-service> \
  --canary-port 8080
```
