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
- name: OBJECT_STORE_S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "agentium.secretName" . }}
      key: OBJECT_STORE_S3_SECRET_KEY
{{- end -}}

{{- define "agentium.storageClassName" -}}
{{- $explicit := index . 0 -}}
{{- $root := index . 1 -}}
{{- $sc := default $root.Values.storageClass $explicit -}}
{{- if $sc }}
storageClassName: {{ $sc | quote }}
{{- end }}
{{- end -}}
