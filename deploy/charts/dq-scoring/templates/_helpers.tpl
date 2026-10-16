{{/*
Expand the name of the chart.
*/}}
{{- define "dq-scoring.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "dq-scoring.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "dq-scoring.labels" -}}
helm.sh/chart: {{ include "dq-scoring.chart" . }}
{{ include "dq-scoring.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "dq-scoring.selectorLabels" -}}
app.kubernetes.io/name: {{ include "dq-scoring.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "dq-scoring.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Protected-processing helpers. All fail-closed: no value is defaulted when protectedProcessing.enabled=true.
*/}}
{{- define "dq-scoring.svcFqdn" -}}
{{- printf "%s.%s.svc.%s" .svc.name .svc.namespace .cd -}}
{{- end }}

{{- define "dq-scoring.apiPortName" -}}
{{- if .Values.security.protectedProcessing.enabled -}}https{{- else -}}http{{- end -}}
{{- end }}

{{- define "dq-scoring.ipv4ToInt" -}}
{{- $o := splitList "." . -}}
{{- add (mul (int (index $o 0)) 16777216) (mul (int (index $o 1)) 65536) (mul (int (index $o 2)) 256) (int (index $o 3)) -}}
{{- end }}
{{- define "dq-scoring.memToMiB" -}}
{{- $v := . | toString | lower | trim -}}
{{- if hasSuffix "gi" $v -}}
{{- mul (int (trimSuffix "gi" $v)) 1024 -}}
{{- else if hasSuffix "g" $v -}}
{{- mul (int (trimSuffix "g" $v)) 1024 -}}
{{- else if hasSuffix "mi" $v -}}
{{- int (trimSuffix "mi" $v) -}}
{{- else if hasSuffix "m" $v -}}
{{- int (trimSuffix "m" $v) -}}
{{- else -}}
{{- int $v -}}
{{- end -}}
{{- end }}

{{- define "dq-scoring.protected.validate" -}}
{{- if .Values.security.protectedProcessing.enabled -}}
{{- $p := .Values.security.protectedProcessing -}}
{{- $label := "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$" -}}
{{- $host := "^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$" -}}
{{- if not (regexMatch $host ($p.clusterDomain | default "")) -}}
{{- fail "security.protectedProcessing.clusterDomain must be an exact DNS domain" -}}
{{- end -}}
{{- $master := .Values.spark.master | default "" -}}
{{- if not (hasPrefix "k8s://" $master) -}}
{{- fail "PROTECTED_COMPUTE_CONFIGURATION_REQUIRED: protected processing supports only a k8s:// Spark master (local and standalone masters are rejected)" -}}
{{- end -}}
{{- if ne $master (printf "k8s://https://kubernetes.default.svc.%s:443" $p.clusterDomain) -}}
{{- fail "PROTECTED_COMPUTE_CONFIGURATION_REQUIRED: spark.master must be k8s://https://kubernetes.default.svc.<clusterDomain>:443 so the DNS allowlist matches" -}}
{{- end -}}
{{- range $k, $v := dict "apiTlsSecret" $p.apiTlsSecret "caSecret" $p.caSecret "sparkSecuritySecret" $p.sparkSecuritySecret "apiServerName" $p.apiServerName "apiScratchSizeLimit" $p.apiScratchSizeLimit "scratchSizeLimit" $p.scratchSizeLimit -}}
{{- if not $v -}}
{{- fail (printf "security.protectedProcessing.%s is required when protected processing is enabled" $k) -}}
{{- end -}}
{{- end -}}
{{- $apiScratchMiB := int (include "dq-scoring.memToMiB" $p.apiScratchSizeLimit) -}}
{{- $apiMemLimitMiB := int (include "dq-scoring.memToMiB" (get (get .Values.api.resources "limits" | default dict) "memory" | default "0")) -}}
{{- if and (gt $apiScratchMiB 0) (gt $apiMemLimitMiB 0) (lt $apiMemLimitMiB $apiScratchMiB) -}}
{{- fail (printf "api.resources.limits.memory (%s) must be greater than or equal to apiScratchSizeLimit (%s) because tmpfs counts against memory limits" (get .Values.api.resources.limits "memory") $p.apiScratchSizeLimit) -}}
{{- end -}}
{{- $scratchMiB := int (include "dq-scoring.memToMiB" $p.scratchSizeLimit) -}}
{{- $importMemLimitMiB := int (include "dq-scoring.memToMiB" (get (get .Values.importWorker.resources "limits" | default dict) "memory" | default "0")) -}}
{{- if and (gt $scratchMiB 0) (gt $importMemLimitMiB 0) (lt $importMemLimitMiB $scratchMiB) -}}
{{- fail (printf "importWorker.resources.limits.memory (%s) must be greater than or equal to scratchSizeLimit (%s) because tmpfs counts against memory limits" (get .Values.importWorker.resources.limits "memory") $p.scratchSizeLimit) -}}
{{- end -}}
{{- range $k, $v := dict "apiTlsSecret" $p.apiTlsSecret "caSecret" $p.caSecret "sparkSecuritySecret" $p.sparkSecuritySecret "apiServerName" $p.apiServerName -}}
{{- if not (regexMatch $host $v) -}}
{{- fail (printf "security.protectedProcessing.%s must be an exact DNS name (no wildcard)" $k) -}}
{{- end -}}
{{- end -}}
{{- if or (eq $p.apiTlsSecret $p.caSecret) (eq $p.apiTlsSecret $p.sparkSecuritySecret) (eq $p.caSecret $p.sparkSecuritySecret) -}}
{{- fail "apiTlsSecret, caSecret and sparkSecuritySecret must be three distinct existing Secrets" -}}
{{- end -}}
{{- if not (and .Values.minio.useSsl) -}}
{{- fail "minio.useSsl must be true when protected processing is enabled" -}}
{{- end -}}
{{- if not .Values.networkPolicy.enabled -}}
{{- fail "networkPolicy.enabled must be true when protected processing is enabled" -}}
{{- end -}}
{{- range $lane, $cfg := dict "fastLane" .Values.workers.fastLane "heavyLane" .Values.workers.heavyLane "scheduledLane" .Values.workers.scheduledLane -}}
{{- if $cfg.keda.enabled -}}
{{- fail (printf "workers.%s.keda.enabled must be false: the KEDA trigger cannot reach PostgreSQL under verify-full TLS and an egress allowlist" $lane) -}}
{{- end -}}
{{- end -}}
{{- $svcs := dict "postgres" $p.allowedServices.postgres "minio" $p.allowedServices.minio -}}
{{- range $n, $s := $svcs -}}
{{- if not (and $s.name $s.namespace (regexMatch $label ($s.name | toString)) (regexMatch $label ($s.namespace | toString))) -}}
{{- fail (printf "security.protectedProcessing.allowedServices.%s needs an exact service name and namespace (single DNS labels, no wildcard)" $n) -}}
{{- end -}}
{{- if or (lt (int $s.port) 1) (gt (int $s.port) 65535) -}}
{{- fail (printf "security.protectedProcessing.allowedServices.%s.port must be 1-65535" $n) -}}
{{- end -}}
{{- if not $s.podSelector -}}
{{- fail (printf "security.protectedProcessing.allowedServices.%s.podSelector must select the service pods" $n) -}}
{{- end -}}
{{- end -}}
{{- $ic := $p.allowedServices.ingressController -}}
{{- if not (and $ic.namespace $ic.podSelector (regexMatch $label ($ic.namespace | toString))) -}}
{{- fail "security.protectedProcessing.allowedServices.ingressController needs namespace and podSelector (Traefik pods)" -}}
{{- end -}}
{{- $pg := include "dq-scoring.svcFqdn" (dict "svc" $p.allowedServices.postgres "cd" $p.clusterDomain) -}}
{{- if ne .Values.postgres.host $pg -}}
{{- fail (printf "postgres.host must equal the exact allowed service DNS name %s" $pg) -}}
{{- end -}}
{{- if ne (int .Values.postgres.port) (int $p.allowedServices.postgres.port) -}}
{{- fail "postgres.port must equal allowedServices.postgres.port" -}}
{{- end -}}
{{- $s3 := include "dq-scoring.svcFqdn" (dict "svc" $p.allowedServices.minio "cd" $p.clusterDomain) -}}
{{- if ne .Values.minio.endpoint (printf "https://%s:%d" $s3 (int $p.allowedServices.minio.port)) -}}
{{- fail (printf "minio.endpoint must equal https://%s:%d" $s3 (int $p.allowedServices.minio.port)) -}}
{{- end -}}
{{- if not $p.kubernetesApiCIDRs -}}
{{- fail "security.protectedProcessing.kubernetesApiCIDRs must list the Kubernetes API endpoint CIDRs (explicit, operator provided)" -}}
{{- end -}}
{{- if or (lt (int $p.kubernetesApiPort) 1) (gt (int $p.kubernetesApiPort) 65535) -}}
{{- fail "security.protectedProcessing.kubernetesApiPort must be the API server backend port (443 or 6443)" -}}
{{- end -}}
{{- range $c := $p.kubernetesApiCIDRs -}}
{{- if not (regexMatch "^([0-9]{1,3}(\\.[0-9]{1,3}){3}|[0-9a-fA-F:]*:[0-9a-fA-F:]*)/[0-9]{1,3}$" $c) -}}
{{- fail "kubernetesApiCIDRs entries must be IPv4 or IPv6 CIDRs" -}}
{{- end -}}
{{- $len := int (regexFind "[0-9]+$" $c) -}}
{{- $v4 := contains "." $c -}}
{{- if or (eq $len 0) (and $v4 (lt $len 8)) (and (not $v4) (lt $len 16)) -}}
{{- fail "kubernetesApiCIDRs must not contain /0 or broad ranges" -}}
{{- end -}}
{{- if $v4 -}}
{{- $block := 1 -}}
{{- range until (int (sub 32 $len)) -}}{{- $block = mul $block 2 -}}{{- end -}}
{{- $meta := 2852039166 -}}
{{- if eq (div $meta $block) (div (int (include "dq-scoring.ipv4ToInt" (regexFind "^[0-9.]+" $c))) $block) -}}
{{- fail "kubernetesApiCIDRs must not cover the cloud metadata address" -}}
{{- end -}}
{{- else if and (hasPrefix "fd00:" ($c | lower)) (le $len 32) -}}
{{- fail "kubernetesApiCIDRs must not cover the cloud metadata address" -}}
{{- end -}}
{{- end -}}
{{- if not .Values.ingress.enabled -}}
{{- fail "ingress.enabled must be true: the protected profile exposes only the TLS ingress" -}}
{{- end -}}
{{- if not .Values.ingress.tls.existingSecret -}}
{{- fail "ingress.tls.existingSecret is required when protected processing is enabled" -}}
{{- end -}}
{{- if not .Values.ingress.hosts -}}
{{- fail "ingress.hosts is required when protected processing is enabled" -}}
{{- end -}}
{{- range .Values.ingress.hosts -}}
{{- if not (regexMatch $host .host) -}}
{{- fail "ingress.hosts[].host must be an exact hostname (no wildcard)" -}}
{{- end -}}
{{- end -}}
{{- if ne (index .Values.ingress.annotations "traefik.ingress.kubernetes.io/router.entrypoints") "websecure" -}}
{{- fail "ingress.annotations router.entrypoints must be websecure only" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{- define "dq-scoring.cnpEndpoint" -}}
- matchLabels:
    "k8s:io.kubernetes.pod.namespace": {{ .ns | quote }}
    {{- range $k, $v := .labels }}
    {{ $k | quote }}: {{ $v | quote }}
    {{- end }}
{{- end }}

{{- define "dq-scoring.cnpService" -}}
- toEndpoints:
    {{- include "dq-scoring.cnpEndpoint" (dict "ns" .svc.namespace "labels" .svc.podSelector) | nindent 4 }}
  toPorts:
    - ports:
        - port: {{ .svc.port | int | quote }}
          protocol: TCP
{{- end }}

{{- define "dq-scoring.cnpDns" -}}
- toEndpoints:
    {{- include "dq-scoring.cnpEndpoint" (dict "ns" .p.dns.namespace "labels" .p.dns.podSelector) | nindent 4 }}
  toPorts:
    - ports:
        - port: "53"
          protocol: ANY
      rules:
        dns:
          {{- range $n := .names }}
          {{- range $v := list $n (printf "%s.%s.svc.%s" $n $.ns $.p.clusterDomain) (printf "%s.svc.%s" $n $.p.clusterDomain) (printf "%s.%s" $n $.p.clusterDomain) }}
          - matchName: {{ $v | quote }}
          {{- end }}
          {{- end }}
{{- end }}

{{- define "dq-scoring.projectedSecurity" -}}
- name: security
  projected:
    defaultMode: 0440
    sources:
      {{- if .apiTls }}
      - secret:
          name: {{ .p.apiTlsSecret }}
          items:
            - {key: tls.crt, path: tls.crt}
            - {key: tls.key, path: tls.key}
      {{- end }}
      - secret:
          name: {{ .p.caSecret }}
          items:
            - {key: postgres-ca.pem, path: postgres-ca.pem}
            - {key: s3-ca.pem, path: s3-ca.pem}
            {{- if .apiTls }}
            - {key: tls.ca, path: tls.ca}
            {{- end }}
      {{- if .spark }}
      - secret:
          name: {{ .p.sparkSecuritySecret }}
          items:
            - {key: rpc-auth, path: rpc-auth}
            - {key: keystore.jks, path: keystore.jks}
            - {key: truststore.jks, path: truststore.jks}
            - {key: spark-defaults.conf, path: spark-defaults.conf}
      {{- end }}
{{- end }}
