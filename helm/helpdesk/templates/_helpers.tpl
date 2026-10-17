{{- define "helpdesk.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- define "helpdesk.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "helpdesk.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- required "serviceAccount.name must be set when serviceAccount.create is false" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
