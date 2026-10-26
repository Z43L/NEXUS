{{- define "nexus.labels" -}}
app.kubernetes.io/name: nexus-h0
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}
{{- define "nexus.selector" -}}
app.kubernetes.io/name: nexus-h0
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "nexus.imagePullSecrets" -}}
{{- with .Values.images.pullSecrets }}
imagePullSecrets:
{{ toYaml . | indent 2 }}
{{- end }}
{{- end -}}
