#!/usr/bin/env bash
# Prove the Kubernetes scaffold renders. This is not a cluster or a release.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fail() {
	printf '%s\n' "$*" >&2
	exit 1
}

command -v helm >/dev/null || fail "helm is required"
command -v terraform >/dev/null || fail "terraform is required"
command -v ansible-playbook >/dev/null || fail "ansible-playbook is required"

assert_no_local_images() {
	local file="$1"
	if grep -E '^[[:space:]]+(frontend|backend|worker):[[:space:]].*:(local|latest)[[:space:]]*$' "$file"; then
		fail "$file must not pin :local or :latest"
	fi
}

assert_no_passwords() {
	local file="$1"
	if grep -Ei 'password|change-me|secret_key' "$file"; then
		fail "$file must not contain secret material"
	fi
}

helm lint "$ROOT/ops/helm/agentium"

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	>/tmp/agentium-helm.yaml
grep -q 'name: DATABASE_URL' /tmp/agentium-helm.yaml ||
	fail "backend must receive DATABASE_URL, not a host the process never reads"
grep -q 'name: CELERY_BROKER_URL' /tmp/agentium-helm.yaml ||
	fail "workers must receive CELERY_BROKER_URL"
grep -q 'KEYCLOAK_URL:' /tmp/agentium-helm.yaml ||
	fail "pods must receive KEYCLOAK_URL"
grep -q 'CELERY_QUEUES: "cpu,recipes"' /tmp/agentium-helm.yaml ||
	fail "the general worker must consume cpu,recipes only"
# Revisions before DataOps have no dedicated worker; keep the historical
# scaffold check runnable there. A chart declaring DataOps must render it.
if grep -q '^dataopsWorker:' "$ROOT/ops/helm/agentium/values.yaml"; then
	dataops="$(helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		--show-only templates/worker-dataops.yaml)"
	grep -q 'kind: Deployment' <<<"$dataops" || fail "DataOps requires its own Deployment"
	grep -q 'name: agentium-worker-dataops$' <<<"$dataops" || fail "DataOps worker missing"
	grep -A1 'name: CELERY_QUEUES' <<<"$dataops" | grep -q 'value: dataops$' ||
		fail "the dedicated worker must consume dataops"
	grep -A1 'name: CELERY_CONCURRENCY' <<<"$dataops" | grep -q 'value: "1"' ||
		fail "DataOps requires one task per worker"
	grep -A1 'name: CELERY_BEAT' <<<"$dataops" | grep -q 'value: "0"' ||
		fail "DataOps must not start another scheduler"
	if helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		--set-string 'worker.queues=cpu\,recipes\,dataops' >/dev/null 2>&1; then
		fail "the general worker must refuse the dataops queue"
	fi
fi
grep -q -- '--import-realm' /tmp/agentium-helm.yaml ||
	fail "keycloak must import the realm its readiness probe requests"
cmp -s "$ROOT/backend/keycloak/realm-export.json" \
	"$ROOT/ops/helm/agentium/files/realm-export.json" ||
	fail "chart realm export drifted from backend/keycloak/realm-export.json"
for app in backend worker migrate p4-maintenance; do
	if helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		--show-only "templates/${app}.yaml" | grep -q 'MINIO_ROOT_PASSWORD'; then
		fail "$app must not receive the MinIO root password"
	fi
	# The application Secret is loaded whole: API keys and client secrets reach
	# the pods that way, not through a list someone has to keep in sync.
	helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		-f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
		--show-only "templates/${app}.yaml" |
		grep -A1 -- '- secretRef:' | grep -q 'name: agentium-lab$' ||
		fail "$app must load the whole application Secret through envFrom"
done
# The generated root password sits in a Secret of its own, and only MinIO and
# its init Job read it.
helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	--show-only templates/secret.yaml |
	awk '/^  name: /{name=$2} /MINIO_ROOT_PASSWORD:/{print name}' |
	grep -qv -- '-minio-root$' &&
	fail "the MinIO root password must not sit in the application Secret"
for app in minio minio-init; do
	helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		-f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
		--show-only "templates/${app}.yaml" | grep -q 'name: agentium-lab-minio-root' ||
		fail "$app must read the MinIO root password from minio.existingRootSecret"
done
if helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	-f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
	--set minio.existingRootSecret= >/dev/null 2>&1; then
	fail "without a generated Secret, a missing minio.existingRootSecret must be refused"
fi

# The chart imports a realm derived from the development one, never the
# development accounts or its placeholder client secret.
for denied in alice-demo bob-demo change-me-in-production '"users"'; do
	if grep -qF -- "$denied" /tmp/agentium-helm.yaml; then
		fail "the imported realm must not carry $denied"
	fi
done
# shellcheck disable=SC2016 # a literal Keycloak placeholder, not a shell variable
grep -qF '"secret": "${AGENTIUM_REALM_CLIENT_SECRET}"' /tmp/agentium-helm.yaml ||
	fail "the realm client secret must come from the application Secret"
grep -qF '"http://agentium.example/*"' /tmp/agentium-helm.yaml ||
	fail "the realm redirect URIs must follow ingress.host"
grep -q 'name: KC_DB$' /tmp/agentium-helm.yaml ||
	fail "keycloak must persist to Postgres, or every restart loses its users"
helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	--set keycloak.bootstrapAdmin.email=ops@example.test \
	>/tmp/agentium-helm-bootstrap.yaml
grep -qF '"username": "ops@example.test"' /tmp/agentium-helm-bootstrap.yaml ||
	fail "bootstrapAdmin.email must create the first organization admin"
# shellcheck disable=SC2016 # a literal Keycloak placeholder, not a shell variable
grep -qF '"value": "${AGENTIUM_BOOTSTRAP_ADMIN_PASSWORD}"' /tmp/agentium-helm-bootstrap.yaml ||
	fail "the bootstrap admin password must come from the application Secret"

# Admin kubeconfig and the plan stay inside the pipeline. Project members
# must not be able to download them.
access_none="$(grep -c 'access: none' "$ROOT/.gitlab/ci/agentium-k8s.yml" || true)"
[ "$access_none" -ge 2 ] || fail "tfplan and kubeconfig artifacts must set access: none"

grep -q 'name: agentium-backend' /tmp/agentium-helm.yaml || fail "backend missing from helm template"
grep -q 'name: agentium-frontend' /tmp/agentium-helm.yaml || fail "frontend missing from helm template"
grep -q 'name: agentium-worker' /tmp/agentium-helm.yaml || fail "worker missing from helm template"
grep -q 'kind: Ingress' /tmp/agentium-helm.yaml || fail "ingress missing from helm template"
grep -q 'path: /health/live' /tmp/agentium-helm.yaml || fail "ingress /health/live missing"
grep -q 'wait-postgres' /tmp/agentium-helm.yaml || fail "migrate must wait for Postgres"
grep -q 'post-install' /tmp/agentium-helm.yaml || fail "migrate hook must be post-install, not pre-upgrade"
grep -q 'server-snippet' /tmp/agentium-helm.yaml || fail "hidden-path ingress snippet missing"

# One rendered "image:" line per container, one "cpu:" line per container's
# request block. A container added without requests breaks the equality, so
# the QoS hole cannot come back unnoticed.
tpl_containers="$(grep -cE '^ +image: ' /tmp/agentium-helm.yaml || true)"
request_cpus() {
	# CPU limits are independent of CPU requests; counting both would reject a
	# correctly bounded DataOps worker. Track indentation of requests blocks.
	awk '
	/^[ ]+requests:/ {
	  match($0, /[^ ]/); indent=RSTART; active=1
	  if ($0 ~ /\{.*cpu:/) {count++; active=0}
	  next
	}
	active && /^[ ]*[^ ]/ {
	  match($0, /[^ ]/)
	  if (RSTART <= indent) active=0
	  else if ($0 ~ /^[ ]+cpu:/) {count++; active=0}
	}
	END {print count+0}' "$1"
}
tpl_sized="$(request_cpus /tmp/agentium-helm.yaml)"
[ "$tpl_containers" -gt 0 ] || fail "helm template rendered no container"
[ "$tpl_containers" = "$tpl_sized" ] ||
	fail "every container must declare cpu and memory requests ($tpl_sized/$tpl_containers)"
# Single-replica stateful services must refuse a voluntary eviction.
tpl_pdbs="$(grep -c 'kind: PodDisruptionBudget' /tmp/agentium-helm.yaml || true)"
[ "$tpl_pdbs" = "4" ] ||
	fail "postgres, qdrant, minio and rabbitmq each need a PodDisruptionBudget (got $tpl_pdbs)"
for svc in postgres qdrant minio rabbitmq; do
	helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		--show-only "templates/$svc.yaml" | grep -q 'livenessProbe:' ||
		fail "$svc must declare a liveness probe"
done
if grep -qE '^resources: \{\}' "$ROOT/ops/helm/agentium/values.yaml"; then
	fail "values.yaml must not ship a resources key no template consumes"
fi

# The artifact store is S3, so no pod mounts a shared filesystem for it. The
# emptyDirs that used to stand in for one were never written to anyway: the
# chart set no storage path, so the application used its relative defaults.
grep -q 'OBJECT_STORE_BACKEND: "s3"' /tmp/agentium-helm.yaml ||
	fail "the chart must configure the S3 artifact store"
grep -q 'OBJECT_STORE_S3_ENDPOINT_URL' /tmp/agentium-helm.yaml ||
	fail "the S3 endpoint must be configured"
for target in /data/object_store /data/faiss_db /data/secure_deposit; do
	if grep -q "mountPath: $target" /tmp/agentium-helm.yaml; then
		fail "$target must not be mounted: it cannot be shared ReadWriteOnce"
	fi
done
grep -q 'mountPath: /data/recipe_envs' /tmp/agentium-helm.yaml ||
	fail "the worker still needs its node-local recipe env cache"
grep -q 'ephemeral-storage' /tmp/agentium-helm.yaml ||
	fail "the worker must reserve room for that cache on the node"
grep -q 'minio-init' /tmp/agentium-helm.yaml ||
	fail "nothing creates the bucket and the scoped application user"
if helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	--set objectStore.backend=local >/dev/null 2>&1; then
	fail "a local artifact store must be refused, not silently configured"
fi
if grep -q 'name: agentium-ollama' /tmp/agentium-helm.yaml; then
	fail "default chart must not start Ollama"
fi
if grep -q 'DEFAULT_PROVIDER: ollama' /tmp/agentium-helm.yaml; then
	fail "default chart must keep the cloud routing default"
fi

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	--set ollama.enabled=true \
	>/tmp/agentium-helm-ollama.yaml
grep -q 'name: agentium-ollama' /tmp/agentium-helm-ollama.yaml || fail "ollama service missing when enabled"
grep -q 'nomic-embed-text' /tmp/agentium-helm-ollama.yaml || fail "ollama embed model missing"
grep -q 'DEFAULT_PROVIDER: ollama' /tmp/agentium-helm-ollama.yaml || fail "local chart must default chat to ollama"
grep -q 'EMBEDDING_PROVIDER: ollama' /tmp/agentium-helm-ollama.yaml || fail "local chart must default embeddings to ollama"

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	--set vllm.enabled=true \
	>/tmp/agentium-helm-vllm.yaml
grep -q 'name: agentium-vllm' /tmp/agentium-helm-vllm.yaml || fail "vllm service missing when enabled"
grep -q 'nvidia.com/gpu' /tmp/agentium-helm-vllm.yaml || fail "vllm must request a GPU"
if grep -q 'DEFAULT_PROVIDER: vllm' /tmp/agentium-helm-vllm.yaml; then
	fail "enabling vllm must not replace the routing default"
fi

# The stack beyond the first cut (model-family workers, Hugging Face, secret
# registry, OpenBao) is off by default and wired through Secret names only.
for absent in agentium-hub-fetch agentium-worker-ml-ts agentium-worker-ml-deep agentium-openbao; do
	if grep -q "name: ${absent}\$" /tmp/agentium-helm.yaml; then
		fail "default chart must not start $absent"
	fi
done
grep -q 'SECRET_REGISTRY_DEFAULT_BACKEND: "db"' /tmp/agentium-helm.yaml ||
	fail "the secret registry must default to the db backend"
grep -q 'name: SECRET_REGISTRY_FERNET_KEY' /tmp/agentium-helm.yaml ||
	fail "application pods must read the registry key by reference"

cat >/tmp/agentium-full-stack.yaml <<'EOF'
mlTs: {enabled: true}
mlDeep: {enabled: true, modelsClaim: agentium-lab-ml-deep-models}
huggingface:
  enabled: true
  hubFetch: {existingSecret: agentium-lab-hub-fetch}
  cache: {storageClass: rwx-class}
  bundles: {storageClass: rwx-class}
  bundleSigning: {existingSecret: agentium-lab-hf-bundle-keys, keyId: lab-1}
secretRegistry: {defaultBackend: openbao}
openbao:
  enabled: true
  appRoleSecrets:
    backend: agentium-lab-openbao-backend
    worker: agentium-lab-openbao-worker
    hubFetch: agentium-lab-openbao-hub-fetch
  server: {enabled: true, unsealKeySecret: agentium-lab-openbao-unseal}
EOF
full() {
	helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		-f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
		-f /tmp/agentium-full-stack.yaml "$@"
}
full >/tmp/agentium-helm-full.yaml
for present in agentium-hub-fetch agentium-worker-ml-ts agentium-worker-ml-ts-serve \
	agentium-worker-ml-deep agentium-worker-ml-deep-serve agentium-openbao; do
	grep -q "name: ${present}\$" /tmp/agentium-helm-full.yaml || fail "full stack must render $present"
done
if grep -q '^kind: Secret$' /tmp/agentium-helm-full.yaml; then
	fail "the full stack must reference Secrets, never create them"
fi
# The Hub writer's credentials and the application Secret never meet.
if full --show-only templates/hub-fetch.yaml | grep -A1 -- '- secretRef:' | grep -q 'name: agentium-lab$'; then
	fail "hub-fetch must not load the application Secret whole"
fi
for app in backend worker migrate p4-maintenance ml-workers; do
	if full --show-only "templates/${app}.yaml" | grep -q 'agentium-lab-hub-fetch'; then
		fail "$app must not receive the hub-fetch credentials"
	fi
done
# One AppRole per role: the worker never holds the API's write role.
for app in backend migrate; do
	full --show-only "templates/${app}.yaml" | grep -q 'name: agentium-lab-openbao-backend' ||
		fail "$app must load the backend AppRole"
done
full --show-only templates/worker.yaml | grep -q 'name: agentium-lab-openbao-worker' ||
	fail "worker must load the worker AppRole"
full --show-only templates/hub-fetch.yaml | grep -q 'name: agentium-lab-openbao-hub-fetch' ||
	fail "hub-fetch must load its own AppRole"
for app in worker hub-fetch ml-workers p4-maintenance; do
	if full --show-only "templates/${app}.yaml" | grep -q 'agentium-lab-openbao-backend'; then
		fail "$app must not receive the backend AppRole"
	fi
done
grep -q 'ReadWriteMany' /tmp/agentium-helm-full.yaml ||
	fail "the Hub cache and bundle spool are shared and must be ReadWriteMany"
full --show-only templates/backend.yaml | grep -A1 'mountPath: /data/hub-cache' | grep -q 'readOnly: true' ||
	fail "only hub-fetch may write the Hub cache"
full --show-only templates/hub-fetch.yaml | grep -q 'HF_HUB_OFFLINE' &&
	fail "hub-fetch is the one Hub client and must not be offline"
full --show-only templates/backend.yaml | grep -q 'HF_BUNDLE_SIGNING_KEY_PATH' &&
	fail "the API must not hold the bundle signing key"
grep -q 'kind: NetworkPolicy' /tmp/agentium-helm-full.yaml ||
	fail "the in-cluster OpenBao must only accept its clients"
full_containers="$(grep -cE '^ +image: ' /tmp/agentium-helm-full.yaml || true)"
full_sized="$(request_cpus /tmp/agentium-helm-full.yaml)"
[ "$full_containers" = "$full_sized" ] ||
	fail "every full-stack container must declare requests ($full_sized/$full_containers)"
refuse() {
	local why="$1"
	shift
	if full "$@" >/dev/null 2>&1; then
		fail "$why"
	fi
}
refuse "openbao as default backend without OpenBao must be refused" --set openbao.enabled=false
refuse "hub-fetch without its own Secret must be refused" --set huggingface.hubFetch.existingSecret=
refuse "hub-fetch on the application Secret must be refused" --set huggingface.hubFetch.existingSecret=agentium-lab
refuse "a Hub cache without a shared volume must be refused" --set huggingface.cache.storageClass=
refuse "OpenBao without the worker AppRole must be refused" --set openbao.appRoleSecrets.worker=
refuse "an in-cluster OpenBao without its unseal key Secret must be refused" --set openbao.server.unsealKeySecret=

# Realtime (Compose profile realtime) is off everywhere until a release turns
# it on, and then it names Secrets only.
for values in "" values-local.yaml values-lab-ovh.yaml values-lab-aks.yaml; do
	args=()
	[ -n "$values" ] && args=(-f "$ROOT/ops/helm/agentium/$values")
	rendered="$(helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium ${args[@]+"${args[@]}"})"
	if grep -qE 'agentium-livekit|LIVEKIT_|/livekit|hostNetwork|protocol: UDP' <<<"$rendered"; then
		fail "${values:-values.yaml} must not render LiveKit by default"
	fi
done
lk() {
	local values="$1"
	shift
	helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
		-f "$ROOT/ops/helm/agentium/$values" --set livekit.enabled=true "$@"
}
lk_lb() {
	lk values-lab-aks.yaml --set livekit.network.loadBalancer.ip=203.0.113.10 "$@"
}
lk values-lab-ovh.yaml >/tmp/agentium-helm-lk-host.yaml
lk_lb >/tmp/agentium-helm-lk-lb.yaml
for out in /tmp/agentium-helm-lk-host.yaml /tmp/agentium-helm-lk-lb.yaml; do
	for present in agentium-livekit agentium-livekit-agent; do
		grep -q "name: ${present}\$" "$out" || fail "realtime must render $present ($out)"
	done
	if grep -q '^kind: Secret$' "$out"; then
		fail "realtime must reference the LiveKit Secret, never create it ($out)"
	fi
	grep -A3 'name: LIVEKIT_API_SECRET' "$out" | grep -q 'name: agentium-lab-livekit' ||
		fail "the LiveKit secret must come from livekit.existingSecret by key ($out)"
	if grep -qE 'nginx\.ingress\.kubernetes\.io/(use-regex|rewrite-target)|ImplementationSpecific' "$out"; then
		fail "no Ingress may use a regex or a rewrite: ingress-nginx applies it to every path of the host ($out)"
	fi
	grep -q 'LIVEKIT_URL: "ws://livekit.lab-agentium.example"' "$out" ||
		fail "the browser must reach LiveKit at livekit.host ($out)"
	grep -q 'LIVEKIT_AGENT_DISPATCH_URL: http://agentium-livekit-agent:8090/dispatch' "$out" ||
		fail "the API must dispatch to the in-cluster sidecar ($out)"
	grep -q 'LIVEKIT_INTERNAL_URL: http://agentium-livekit:7880' "$out" ||
		fail "the API must reach LiveKit in-cluster ($out)"
	containers="$(grep -cE '^ +image: ' "$out" || true)"
	sized="$(request_cpus "$out")"
	[ "$containers" = "$sized" ] || fail "every realtime container must declare requests ($sized/$containers)"
done
for values in values-lab-ovh.yaml values-lab-aks.yaml; do
	ingress="$(lk "$values" --set livekit.network.mode=hostNetwork --show-only templates/ingress.yaml)"
	main_host="$(sed -n '/^  name: agentium$/,/^---/p' <<<"$ingress" | sed -n 's/^ *- host: "\(.*\)"$/\1/p')"
	livekit="$(sed -n '/^  name: agentium-livekit$/,$p' <<<"$ingress")"
	livekit_host="$(sed -n 's/^ *- host: "\(.*\)"$/\1/p' <<<"$livekit")"
	[ -n "$livekit_host" ] && [ "$livekit_host" != "$main_host" ] ||
		fail "$values: LiveKit needs its own host on the ingress (got '$livekit_host', main '$main_host')"
	[ "$(grep -E '^ +- path: ' <<<"$livekit")" = "          - path: /" ] ||
		fail "$values: the LiveKit Ingress must serve / alone"
	grep -q 'pathType: Prefix' <<<"$livekit" || fail "$values: the LiveKit path must be a plain prefix"
	grep -q 'proxy-read-timeout: "3600"' <<<"$livekit" || fail "$values: LiveKit WebSockets need a long read timeout"
done
rendered="$(lk values-lab-ovh.yaml --set 'ingress.tls[0].secretName=agentium-lab-tls' \
	--set 'livekit.tls[0].secretName=agentium-lab-livekit-tls' --set 'livekit.tls[0].hosts[0]=livekit.lab-agentium.example' \
	--set 'ingress.annotations.cert-manager\.io/cluster-issuer=letsencrypt' --show-only templates/ingress.yaml \
	--show-only templates/configmap.yaml)"
grep -q 'LIVEKIT_URL: "wss://livekit.lab-agentium.example"' <<<"$rendered" ||
	fail "with TLS the browser must reach LiveKit over wss://"
grep -q 'secretName: agentium-lab-livekit-tls' <<<"$(sed -n '/^  name: agentium-livekit$/,$p' <<<"$rendered")" ||
	fail "the LiveKit Ingress must carry livekit.tls"
[ "$(grep -c 'cert-manager.io/cluster-issuer: letsencrypt' <<<"$rendered")" = 2 ] ||
	fail "both Ingresses must get the certificate issuer from ingress.annotations"
for app in livekit livekit-agent; do
	for out in "$(lk values-lab-ovh.yaml --show-only "templates/${app}.yaml")" \
		"$(lk_lb --show-only "templates/${app}.yaml")"; do
		if grep -A1 -- '- secretRef:' <<<"$out" | grep -q 'name: agentium-lab$'; then
			fail "$app must not load the application Secret whole"
		fi
		grep -q 'readOnlyRootFilesystem: true' <<<"$out" || fail "$app must run on a read-only root filesystem"
		grep -q 'runAsNonRoot: true' <<<"$out" || fail "$app must not run as root"
	done
done
agent="$(lk values-lab-ovh.yaml --show-only templates/livekit-agent.yaml)"
if grep -qE 'hostPath|hostNetwork|volumes:|volumeMounts:' <<<"$agent"; then
	fail "the sidecar mounts nothing and stays off the host network, as in Compose"
fi
grep -A4 'name: OPENAI_API_KEY' <<<"$agent" | grep -q 'name: agentium-lab$' ||
	fail "the sidecar must read OPENAI_API_KEY from the application Secret by key"
if grep -q 'LIVEKIT_API' <<<"$agent"; then
	fail "the sidecar gets its room token from the dispatch, not the LiveKit keys"
fi
grep -q 'path: /healthz' <<<"$agent" || fail "the sidecar probes must match the Compose healthcheck"
for app in worker migrate p4-maintenance; do
	if grep -q 'agentium-lab-livekit' <<<"$(lk values-lab-ovh.yaml --show-only "templates/${app}.yaml")"; then
		fail "$app must not receive the LiveKit keys"
	fi
done
# hostNetwork: media on the node, no LoadBalancer, no UDP Service port.
grep -q 'hostNetwork: true' /tmp/agentium-helm-lk-host.yaml || fail "hostNetwork mode must run LiveKit on the host network"
grep -q 'dnsPolicy: ClusterFirstWithHostNet' /tmp/agentium-helm-lk-host.yaml ||
	fail "a host-network LiveKit must still resolve agentium-backend"
grep -q 'port_range_start: 50000' /tmp/agentium-helm-lk-host.yaml || fail "hostNetwork mode must use the UDP port range"
grep -q 'agentium.io/media: livekit' /tmp/agentium-helm-lk-host.yaml || fail "lab-ovh LiveKit must land on media nodes"
if grep -qE 'type: LoadBalancer|protocol: UDP|udp_port:' /tmp/agentium-helm-lk-host.yaml; then
	fail "hostNetwork mode must not expose UDP through a Service"
fi
# loadBalancer: one UDP port on a reserved address, never the host network.
grep -q 'type: LoadBalancer' /tmp/agentium-helm-lk-lb.yaml || fail "loadBalancer mode must render the LoadBalancer Service"
grep -q 'udp_port: 7882' /tmp/agentium-helm-lk-lb.yaml || fail "loadBalancer mode must use one UDP port"
grep -A1 'name: NODE_IP' /tmp/agentium-helm-lk-lb.yaml | grep -q '203.0.113.10' ||
	fail "loadBalancer mode must advertise the LoadBalancer address"
grep -q 'azure-pip-name' /tmp/agentium-helm-lk-lb.yaml || fail "lab-aks must carry its LoadBalancer annotation"
grep -q 'name: agentium-livekit$' <(grep -A3 'kind: NetworkPolicy' /tmp/agentium-helm-lk-lb.yaml) ||
	fail "loadBalancer mode must restrict LiveKit signalling"
if grep -qE 'hostNetwork|port_range_start' /tmp/agentium-helm-lk-lb.yaml; then
	fail "loadBalancer mode must not use the host network"
fi
rendered="$(lk values-lab-ovh.yaml --set livekit.network.mode=loadBalancer \
	--set livekit.network.loadBalancer.ip=198.51.100.7)"
grep -q 'loadbalancer.ovhcloud.com/class: octavia' <<<"$rendered" ||
	fail "lab-ovh must carry its LoadBalancer annotation"
rendered="$(lk values-lab-ovh.yaml --set livekit.turn.enabled=true --set livekit.turn.domain=turn.example.test \
	--set livekit.turn.tlsSecret=agentium-lab-livekit-turn)"
grep -q 'secretName: agentium-lab-livekit-turn' <<<"$rendered" ||
	fail "TURN must read its certificate from livekit.turn.tlsSecret"
grep -q 'port: 5349' <<<"$rendered" || fail "TURN/TLS must listen when TURN is enabled"
refuse_lk() {
	local why="$1"
	shift
	if lk "$@" >/dev/null 2>&1; then
		fail "$why"
	fi
}
refuse_lk "LiveKit without its Secret must be refused" values-lab-ovh.yaml --set livekit.existingSecret=
refuse_lk "LiveKit on the application Secret must be refused" values-lab-ovh.yaml --set livekit.existingSecret=agentium-lab
refuse_lk "an unknown LiveKit network mode must be refused" values-lab-ovh.yaml --set livekit.network.mode=nodePort
refuse_lk "loadBalancer mode without its address must be refused" values-lab-aks.yaml
refuse_lk "several LiveKit replicas without Redis must be refused" values-lab-ovh.yaml --set livekit.replicas=2
refuse_lk "several LiveKit replicas behind one LoadBalancer must be refused" values-lab-aks.yaml \
	--set livekit.network.loadBalancer.ip=203.0.113.10 --set livekit.replicas=2 --set livekit.redis.address=redis:6379
refuse_lk "TURN without a certificate must be refused" values-lab-ovh.yaml \
	--set livekit.turn.enabled=true --set livekit.turn.domain=turn.example.test
refuse_lk "LiveKit without its host must be refused" values-lab-ovh.yaml --set livekit.host=
refuse_lk "LiveKit on the main host must be refused" values-lab-ovh.yaml --set livekit.host=lab-agentium.example
refuse_lk "an https app with a ws:// LiveKit must be refused" values-lab-ovh.yaml \
	--set 'ingress.tls[0].secretName=agentium-lab-tls'
if helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	--set 'ingress.annotations.nginx\.ingress\.kubernetes\.io/use-regex=true' >/dev/null 2>&1; then
	fail "a regex annotation on the main Ingress must be refused"
fi

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	-f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
	>/tmp/agentium-helm-lab-ovh.yaml
grep -q 'name: agentium-lab' /tmp/agentium-helm-lab-ovh.yaml || fail "lab-ovh must use existingSecret agentium-lab"
if grep -q '^kind: Secret$' /tmp/agentium-helm-lab-ovh.yaml; then
	fail "lab-ovh must not create a Secret"
fi
grep -q 'storageClassName: "csi-cinder-high-speed"' /tmp/agentium-helm-lab-ovh.yaml ||
	fail "lab-ovh must set OVH CSI storage class"
grep -q 'ingressClassName: "nginx"' /tmp/agentium-helm-lab-ovh.yaml || fail "lab-ovh ingress class"
assert_no_local_images "$ROOT/ops/helm/agentium/values-lab-ovh.yaml"
assert_no_passwords "$ROOT/ops/helm/agentium/values-lab-ovh.yaml"

helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	-f "$ROOT/ops/helm/agentium/values-lab-aks.yaml" \
	>/tmp/agentium-helm-lab-aks.yaml
grep -q 'name: agentium-lab' /tmp/agentium-helm-lab-aks.yaml || fail "lab-aks must use existingSecret"
if grep -q '^kind: Secret$' /tmp/agentium-helm-lab-aks.yaml; then
	fail "lab-aks must not create a Secret"
fi
grep -q 'storageClassName: "managed-csi"' /tmp/agentium-helm-lab-aks.yaml ||
	fail "lab-aks must set Azure CSI storage class"
assert_no_local_images "$ROOT/ops/helm/agentium/values-lab-aks.yaml"
assert_no_passwords "$ROOT/ops/helm/agentium/values-lab-aks.yaml"

terraform fmt -check -recursive "$ROOT/ops/terraform" "$ROOT/ops/instance"

validate_tf() {
	local dir="$1"
	terraform -chdir="$dir" init -backend=false -input=false >/tmp/tf-init.log
	terraform -chdir="$dir" validate
}

validate_tf "$ROOT/ops/terraform/modules/cluster-ovh-mks"
validate_tf "$ROOT/ops/terraform/modules/cluster-aks"
validate_tf "$ROOT/ops/terraform/envs/lab-ovh"
validate_tf "$ROOT/ops/terraform/envs/lab-aks"
# The OpenStack fallback is fmt-checked above; validate it too, and
# require the backend so no Terraform in this repo keeps local state.
validate_tf "$ROOT/ops/instance"
grep -q 'backend "http" {}' "$ROOT/ops/instance/versions.tf" ||
	fail "ops/instance must keep remote, lockable state"
validate_tf "$ROOT/ops/instance"

DIGEST_A="$(printf 'a%.0s' {1..64})"
DIGEST_B="$(printf 'b%.0s' {1..64})"
DIGEST_C="$(printf 'c%.0s' {1..64})"
cat >/tmp/values-ci-images.yaml <<EOF
image:
  pullPolicy: IfNotPresent
  frontend: registry.example/agentium-frontend@sha256:${DIGEST_A}
  backend: registry.example/agentium-backend@sha256:${DIGEST_B}
  worker: registry.example/agentium-worker@sha256:${DIGEST_C}
EOF
helm template agentium "$ROOT/ops/helm/agentium" --namespace agentium \
	-f "$ROOT/ops/helm/agentium/values-lab-ovh.yaml" \
	-f /tmp/values-ci-images.yaml \
	>/tmp/agentium-helm-ci.yaml
grep -q "agentium-frontend@sha256:${DIGEST_A}" /tmp/agentium-helm-ci.yaml ||
	fail "CI digest overlay must win over :local"
if grep -q 'agentium-frontend:local' /tmp/agentium-helm-ci.yaml; then
	fail "CI overlay left a :local frontend image"
fi
grep -q 'name: agentium-lab' /tmp/agentium-helm-ci.yaml || fail "CI render must keep existingSecret"

# Every job that reaches the lab must stay behind the one switch. Without
# this, landing the track on demo/agentic would deploy on the next push.
CI_K8S="$ROOT/.gitlab/ci/agentium-k8s.yml"
gated="$(grep -c 'AGENTIUM_LAB_ENABLED == "true"' "$CI_K8S" || true)"
reaching="$(grep -cE "^ +- if: '.*(OVH_APPLICATION_KEY|AGENTIUM_LAB_REGISTRY|AGENTIUM_LAB_INGRESS_URL)" "$CI_K8S" || true)"
[ "$gated" -ge 6 ] || fail "lab jobs must stay behind AGENTIUM_LAB_ENABLED"
[ "$gated" -eq "$reaching" ] ||
	fail "a lab-reaching rule is missing the AGENTIUM_LAB_ENABLED gate"
grep -q 'rules: \*ops-k8s-rules-ops-tree' "$CI_K8S" ||
	fail "validate must stay on without the switch"

export ANSIBLE_CONFIG="$ROOT/ops/ansible/ansible.cfg"
ansible-playbook --syntax-check "$ROOT/ops/ansible/playbooks/provision-cluster.yml"
ansible-playbook --syntax-check -i "$ROOT/ops/ansible/inventories/ci" \
	"$ROOT/ops/ansible/playbooks/deploy-agentium.yml"

printf 'ops scaffold ok\n'
