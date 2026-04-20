{{/*
Expand the name of the chart.
*/}}
{{- define "styrmin.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "styrmin.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "styrmin.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "styrmin.labels" -}}
helm.sh/chart: {{ include "styrmin.chart" . }}
{{ include "styrmin.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "styrmin.selectorLabels" -}}
app.kubernetes.io/name: {{ include "styrmin.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Selector labels for styrmin-server
*/}}
{{- define "styrmin.server.selectorLabels" -}}
{{ include "styrmin.selectorLabels" . }}
app.kubernetes.io/component: server
{{- end }}

{{/*
Selector labels for styrmin-task-worker
*/}}
{{- define "styrmin.taskWorker.selectorLabels" -}}
{{ include "styrmin.selectorLabels" . }}
app.kubernetes.io/component: task-worker
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "styrmin.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "styrmin.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the styrmin-server
*/}}
{{- define "styrmin.server.fullname" -}}
{{- printf "%s-server" (include "styrmin.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create the name of the styrmin-task-worker
*/}}
{{- define "styrmin.taskWorker.fullname" -}}
{{- printf "%s-task-worker" (include "styrmin.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create the name of the secret
*/}}
{{- define "styrmin.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "styrmin.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Create the name of the configmap
*/}}
{{- define "styrmin.configMapName" -}}
{{- printf "%s-config" (include "styrmin.fullname" .) }}
{{- end }}

{{/*
Create the PostgreSQL host
*/}}
{{- define "styrmin.postgresql.host" -}}
{{- if .Values.styrmin.database.host }}
{{- .Values.styrmin.database.host }}
{{- else }}
{{- printf "%s-postgresql" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Create the PostgreSQL connection URL for Styrmin
*/}}
{{- define "styrmin.postgresql.url" -}}
{{- $host := include "styrmin.postgresql.host" . -}}
{{- $port := .Values.styrmin.database.port | default 5432 -}}
{{- $database := .Values.styrmin.database.name | default "styrmin" -}}
{{- printf "postgresql+asyncpg://$(STYRMIN_DB_USERNAME):$(STYRMIN_DB_PASSWORD)@%s:%d/%s" $host (int $port) $database }}
{{- end }}

{{/*
Create the PostgreSQL connection URL for Prefect
*/}}
{{- define "styrmin.prefect.postgresql.url" -}}
{{- $host := include "styrmin.postgresql.host" . -}}
{{- $port := .Values.styrmin.database.port | default 5432 -}}
{{- printf "postgresql+asyncpg://$(PREFECT_DB_USERNAME):$(PREFECT_DB_PASSWORD)@%s:%d/prefect" $host (int $port) }}
{{- end }}

{{/*
Create the Prefect API URL
*/}}
{{- define "styrmin.prefect.apiUrl" -}}
{{- if .Values.styrmin.workflow.address }}
{{- $scheme := ternary "https" "http" .Values.styrmin.workflow.tlsEnabled -}}
{{- printf "%s://%s:%d/api" $scheme .Values.styrmin.workflow.address (int .Values.styrmin.workflow.port) }}
{{- else if (index .Values "prefect-server" "enabled") }}
{{- printf "http://prefect-server:%d/api" (int .Values.styrmin.workflow.port) }}
{{- else }}
{{- fail "Prefect server address must be specified when prefect-server.enabled is false" }}
{{- end }}
{{- end }}

{{/*
Create the base API URL
*/}}
{{- define "styrmin.apiUrl" -}}
{{- if .Values.styrmin.url.api }}
{{- .Values.styrmin.url.api }}
{{- else }}
{{- printf "http://%s:%d" (include "styrmin.server.fullname" .) (int .Values.service.port) }}
{{- end }}
{{- end }}

{{/*
Create the base API URL for Kubernetes (full DNS name)
*/}}
{{- define "styrmin.apiUrlK8s" -}}
{{- if .Values.styrmin.url.apiK8s }}
{{- .Values.styrmin.url.apiK8s }}
{{- else }}
{{- printf "http://%s.%s.svc.%s:%d" (include "styrmin.server.fullname" .) .Release.Namespace .Values.styrmin.kubernetes.clusterDomain (int .Values.service.port) }}
{{- end }}
{{- end }}

{{/*
Create the image name
*/}}
{{- define "styrmin.image" -}}
{{- $registry := .Values.image.registry -}}
{{- $repository := .Values.image.repository -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- else }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}
