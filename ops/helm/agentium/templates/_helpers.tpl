{{- define "agentium.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "agentium.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "agentium.labels" -}}
app.kubernetes.io/name: {{ include "agentium.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "agentium.secretName" -}}
{{- if .Values.existingSecret -}}
{{- .Values.existingSecret -}}
{{- else -}}
{{- printf "%s-secret" (include "agentium.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
The MinIO root credential lives in its own Secret. The application Secret is
loaded whole into every application pod, so anything in it reaches them; the
root password must not be in it.
*/}}
{{- define "agentium.minioRootSecretName" -}}
{{- if .Values.minio.existingRootSecret -}}
{{- .Values.minio.existingRootSecret -}}
{{- else if .Values.createSecret -}}
{{- printf "%s-minio-root" (include "agentium.fullname" .) -}}
{{- else -}}
{{- fail "minio.existingRootSecret is required when createSecret is false: the MinIO root password must not live in the application Secret" -}}
{{- end -}}
{{- end -}}

{{/*
An existing application Secret that still carries the MinIO root password
would hand it to every application pod. Refuse the release. lookup is empty
under `helm template`, so this only bites on a real install or upgrade.
*/}}
{{- define "agentium.assertAppSecretScoped" -}}
{{- if .Values.existingSecret -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace .Values.existingSecret -}}
{{- $data := dict -}}
{{- if $existing -}}
{{- $data = default dict $existing.data -}}
{{- end -}}
{{- range $key := list "MINIO_ROOT_PASSWORD" "AGENTIUM_MINIO_ROOT_PASSWORD" -}}
{{- if hasKey $data $key -}}
{{- fail (printf "Secret %s holds %s. Move it to minio.existingRootSecret: every application pod loads that Secret whole." $.Values.existingSecret $key) -}}
{{- end -}}
{{- end -}}
{{/* Role credentials belong to the one role that uses them. */}}
{{- range $key := list "OPENBAO_ROLE_ID" "OPENBAO_SECRET_ID" "HF_TABULAR_DELETE_SECRET_KEY" "LIVEKIT_API_SECRET" -}}
{{- if hasKey $data $key -}}
{{- fail (printf "Secret %s holds %s. Move it to its role Secret (openbao.appRoleSecrets, huggingface.hubFetch.existingSecret, livekit.existingSecret): every application pod loads that Secret whole." $.Values.existingSecret $key) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Public URL of the web app, as a browser reaches it through the ingress. */}}
{{- define "agentium.appUrl" -}}
{{- if .Values.keycloak.appUrl -}}
{{- trimSuffix "/" .Values.keycloak.appUrl -}}
{{- else -}}
{{- printf "%s://%s" (ternary "https" "http" (not (empty .Values.ingress.tls))) .Values.ingress.host -}}
{{- end -}}
{{- end -}}

{{/* Signalling URL as a browser reaches it: /livekit on the ingress. */}}
{{- define "agentium.livekitPublicUrl" -}}
{{- if .Values.livekit.publicUrl -}}
{{- trimSuffix "/" .Values.livekit.publicUrl -}}
{{- else -}}
{{- printf "%s://%s/livekit" (ternary "wss" "ws" (not (empty .Values.ingress.tls))) .Values.ingress.host -}}
{{- end -}}
{{- end -}}

{{/* LiveKit keys, by key from livekit.existingSecret: LiveKit and the API only. */}}
{{- define "agentium.livekitApiEnv" -}}
{{- if .Values.livekit.enabled }}
- name: LIVEKIT_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.livekit.existingSecret }}
      key: LIVEKIT_API_KEY
- name: LIVEKIT_API_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ .Values.livekit.existingSecret }}
      key: LIVEKIT_API_SECRET
{{- end }}
{{- end -}}

{{- define "agentium.imagePullSecrets" -}}
{{- if .Values.imagePullSecrets }}
imagePullSecrets:
{{- range .Values.imagePullSecrets }}
  - name: {{ . }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Connection URLs the process actually reads. The password is expanded by the
kubelet from a secret key already required by Postgres or RabbitMQ, so it
never lands in the ConfigMap; it must be URL-safe. Application pods also load
the application Secret whole through envFrom, which is how API keys and
client secrets reach them. The keys named here are the ones a pod cannot run
without, so a Secret missing one fails at pod creation instead of at the
first request.
*/}}
{{- define "agentium.appSecretEnv" -}}
{{ include "agentium.dbBrokerEnv" . }}
- name: OBJECT_STORE_S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "agentium.secretName" . }}
      key: OBJECT_STORE_S3_SECRET_KEY
{{ include "agentium.secretRegistryEnv" . }}
{{- end -}}

{{/*
Database and broker URLs alone. hub-fetch takes these and nothing else from
the application Secret: its object-store identity is its own.
*/}}
{{- define "agentium.dbBrokerEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "agentium.secretName" . }}
      key: POSTGRES_PASSWORD
- name: DATABASE_URL
  value: {{ printf "postgresql://%s:$(POSTGRES_PASSWORD)@agentium-pg:5432/%s" .Values.postgres.user .Values.postgres.database | quote }}
- name: RABBITMQ_DEFAULT_PASS
  valueFrom:
    secretKeyRef:
      name: {{ include "agentium.secretName" . }}
      key: RABBITMQ_DEFAULT_PASS
- name: CELERY_BROKER_URL
  value: {{ printf "amqp://%s:$(RABBITMQ_DEFAULT_PASS)@agentium-rabbitmq:5672//" .Values.rabbitmq.user | quote }}
{{- end -}}

{{/*
The registry key decrypts every db-backend secret. It is read by key, so a
pod whose Secret lacks it fails at creation instead of at the first resolve.
*/}}
{{- define "agentium.secretRegistryEnv" -}}
- name: SECRET_REGISTRY_FERNET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ default (include "agentium.secretName" .) .Values.secretRegistry.fernetKey.secretName }}
      key: {{ .Values.secretRegistry.fernetKey.key }}
{{- end -}}

{{- define "agentium.openbaoAddr" -}}
{{- if .Values.openbao.addr -}}
{{- .Values.openbao.addr -}}
{{- else if .Values.openbao.server.enabled -}}
http://agentium-openbao:8200
{{- else -}}
{{- fail "openbao.addr is required when openbao.server.enabled is false" -}}
{{- end -}}
{{- end -}}

{{/* OpenBao client env. Call with (list $ "<role>"); empty when disabled. */}}
{{- define "agentium.openbaoEnv" -}}
{{- $root := index . 0 -}}
{{- if $root.Values.openbao.enabled }}
- name: OPENBAO_ADDR
  value: {{ include "agentium.openbaoAddr" $root | quote }}
- name: OPENBAO_MOUNT
  value: {{ $root.Values.openbao.mount | quote }}
- name: OPENBAO_TIMEOUT_SECONDS
  value: {{ $root.Values.openbao.timeoutSeconds | quote }}
{{- end }}
{{- end -}}

{{/*
Each role loads its own AppRole Secret, after the application Secret, so a
worker never holds the API's write role.
*/}}
{{- define "agentium.openbaoEnvFrom" -}}
{{- $root := index . 0 -}}
{{- $role := index . 1 -}}
{{- if $root.Values.openbao.enabled }}
- secretRef:
    name: {{ index $root.Values.openbao.appRoleSecrets $role | required (printf "openbao.appRoleSecrets.%s is required when openbao.enabled is true" $role) }}
{{- end }}
{{- end -}}

{{- define "agentium.hubCacheClaim" -}}
{{- default (printf "%s-hub-cache" (include "agentium.fullname" .)) .Values.huggingface.cache.existingClaim -}}
{{- end -}}

{{- define "agentium.hubBundlesClaim" -}}
{{- default (printf "%s-hub-bundles" (include "agentium.fullname" .)) .Values.huggingface.bundles.existingClaim -}}
{{- end -}}

{{/*
Hugging Face mounts per role, as in docker/compose.agentium.huggingface.yml:
the cache is written by hub-fetch only, the bundle spool by the API, the CPU
worker and hub-fetch, and the signing key is read by the exporters.
Call with (list $ "<role>"), role in backend, worker, mlDeep, hubFetch.
*/}}
{{- define "agentium.hfVolumeMounts" -}}
{{- $root := index . 0 -}}
{{- $role := index . 1 -}}
{{- if $root.Values.huggingface.enabled }}
- name: hub-cache
  mountPath: /data/hub-cache
  readOnly: {{ ne $role "hubFetch" }}
{{- if has $role (list "backend" "worker" "hubFetch") }}
- name: hub-bundles
  mountPath: /data/hub-bundles
{{- end }}
{{- if and $root.Values.huggingface.bundleSigning.existingSecret (has $role (list "worker" "hubFetch")) }}
- name: hf-bundle-keys
  mountPath: /run/hf-bundle-keys
  readOnly: true
{{- end }}
{{- end }}
{{- end -}}

{{- define "agentium.hfVolumes" -}}
{{- $root := index . 0 -}}
{{- $role := index . 1 -}}
{{- if $root.Values.huggingface.enabled }}
- name: hub-cache
  persistentVolumeClaim:
    claimName: {{ include "agentium.hubCacheClaim" $root }}
    readOnly: {{ ne $role "hubFetch" }}
{{- if has $role (list "backend" "worker" "hubFetch") }}
- name: hub-bundles
  persistentVolumeClaim:
    claimName: {{ include "agentium.hubBundlesClaim" $root }}
{{- end }}
{{- if and $root.Values.huggingface.bundleSigning.existingSecret (has $role (list "worker" "hubFetch")) }}
- name: hf-bundle-keys
  secret:
    secretName: {{ $root.Values.huggingface.bundleSigning.existingSecret }}
    defaultMode: 0440
{{- end }}
{{- end }}
{{- end -}}

{{/* Signing key location, for the pods that mount it. */}}
{{- define "agentium.hfSigningEnv" -}}
{{- $root := index . 0 -}}
{{- if and $root.Values.huggingface.enabled $root.Values.huggingface.bundleSigning.existingSecret }}
- name: HF_BUNDLE_SIGNING_KEY_PATH
  value: {{ printf "/run/hf-bundle-keys/%s" $root.Values.huggingface.bundleSigning.keyFile | quote }}
- name: HF_BUNDLE_SIGNING_KEY_ID
  value: {{ $root.Values.huggingface.bundleSigning.keyId | required "huggingface.bundleSigning.keyId is required with a signing key" | quote }}
{{- end }}
{{- end -}}

{{/* Runtimes read local files only; hub-fetch is the one Hub client. */}}
{{- define "agentium.hfOfflineEnv" -}}
- name: HF_HUB_OFFLINE
  value: "1"
- name: TRANSFORMERS_OFFLINE
  value: "1"
{{- end -}}

{{/*
Refuse a release that cannot work or that would widen a credential's reach.
Rendered once, from the ConfigMap.
*/}}
{{- define "agentium.validate" -}}
{{- if not (has .Values.secretRegistry.defaultBackend (list "db" "openbao")) -}}
{{- fail "secretRegistry.defaultBackend must be db or openbao" -}}
{{- end -}}
{{- if and (eq .Values.secretRegistry.defaultBackend "openbao") (not .Values.openbao.enabled) -}}
{{- fail "secretRegistry.defaultBackend=openbao needs openbao.enabled" -}}
{{- end -}}
{{- if .Values.openbao.enabled -}}
{{- $_ := include "agentium.openbaoAddr" . -}}
{{- $_ := .Values.openbao.appRoleSecrets.backend | required "openbao.appRoleSecrets.backend is required when openbao.enabled is true" -}}
{{- $_ := .Values.openbao.appRoleSecrets.worker | required "openbao.appRoleSecrets.worker is required when openbao.enabled is true" -}}
{{- if .Values.huggingface.enabled -}}
{{- $_ := .Values.openbao.appRoleSecrets.hubFetch | required "openbao.appRoleSecrets.hubFetch is required when openbao and huggingface are enabled" -}}
{{- end -}}
{{- end -}}
{{- if .Values.openbao.server.enabled -}}
{{- $_ := .Values.openbao.server.unsealKeySecret | required "openbao.server.unsealKeySecret is required: the chart never generates the unseal key" -}}
{{- end -}}
{{- if .Values.huggingface.enabled -}}
{{- $_ := .Values.huggingface.hubFetch.existingSecret | required "huggingface.hubFetch.existingSecret is required: the Hub writer has its own credentials" -}}
{{- if eq .Values.huggingface.hubFetch.existingSecret (include "agentium.secretName" .) -}}
{{- fail "huggingface.hubFetch.existingSecret must not be the application Secret" -}}
{{- end -}}
{{- range $name := list "cache" "bundles" -}}
{{- $volume := index $.Values.huggingface $name -}}
{{- if not (or $volume.existingClaim $volume.storageClass) -}}
{{- fail (printf "huggingface.%s needs existingClaim or a ReadWriteMany storageClass: several pods share it" $name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if .Values.livekit.enabled -}}
{{- $lk := .Values.livekit -}}
{{- $_ := $lk.existingSecret | required "livekit.existingSecret is required: the chart never creates the LiveKit keys" -}}
{{- if eq $lk.existingSecret (include "agentium.secretName" .) -}}
{{- fail "livekit.existingSecret must not be the application Secret: every application pod loads that Secret whole" -}}
{{- end -}}
{{- if not (has $lk.network.mode (list "hostNetwork" "loadBalancer")) -}}
{{- fail "livekit.network.mode must be hostNetwork or loadBalancer" -}}
{{- end -}}
{{- if eq $lk.network.mode "loadBalancer" -}}
{{- $_ := $lk.network.loadBalancer.ip | required "livekit.network.loadBalancer.ip is required: LiveKit advertises that address to clients" -}}
{{- if gt (int $lk.replicas) 1 -}}
{{- fail "one LoadBalancer address cannot front several LiveKit nodes: use livekit.network.mode=hostNetwork for more than one replica" -}}
{{- end -}}
{{- else if gt (int $lk.network.hostNetwork.portRangeStart) (int $lk.network.hostNetwork.portRangeEnd) -}}
{{- fail "livekit.network.hostNetwork.portRangeStart must not exceed portRangeEnd" -}}
{{- end -}}
{{- if and (gt (int $lk.replicas) 1) (not $lk.redis.address) -}}
{{- fail "livekit.redis.address is required for more than one LiveKit replica" -}}
{{- end -}}
{{- if $lk.turn.enabled -}}
{{- $_ := $lk.turn.domain | required "livekit.turn.domain is required when TURN is enabled" -}}
{{- $_ := $lk.turn.tlsSecret | required "livekit.turn.tlsSecret is required when TURN is enabled" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "agentium.storageClassName" -}}
{{- $explicit := index . 0 -}}
{{- $root := index . 1 -}}
{{- $sc := default $root.Values.storageClass $explicit -}}
{{- if $sc }}
storageClassName: {{ $sc | quote }}
{{- end }}
{{- end -}}
