{{- define "kubeconfig.tpl" }}
apiVersion: v1
kind: Config
clusters:
- name: {{ .Values.conf.capi.clusterName }}
  cluster:
    server: {{ .Values.conf.capi.apiServer }}
    {{- if .Values.conf.capi.certificateAuthorityFile }}
    certificate-authority: {{ .Values.conf.capi.certificateAuthorityFile | quote }}
    {{- else }}
    certificate-authority-data: {{ .Values.conf.capi.certificateAuthorityData | quote }}
    {{- end }}
contexts:
- name: {{ .Values.conf.capi.contextName }}
  context:
    cluster: {{ .Values.conf.capi.clusterName }}
    user: {{ .Values.conf.capi.userName }}
current-context: {{ .Values.conf.capi.contextName }}
users:
- name: {{ .Values.conf.capi.userName }}
  user:
    {{- if .Values.conf.capi.tokenFile }}
    tokenFile: {{ .Values.conf.capi.tokenFile | quote }}
    {{- else }}
    client-certificate-data: {{ .Values.conf.capi.clientCertificateData | quote }}
    client-key-data: {{ .Values.conf.capi.clientKeyData | quote }}
    {{- end }}
{{- end }}
