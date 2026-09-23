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
never lands in the ConfigMap. The MinIO root password is not here: the
application uses OBJECT_STORE_S3_SECRET_KEY only.
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
