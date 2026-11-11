#!/usr/bin/env bash

# -e: End the script immediately if any command or pipe exits with a non-zero status
# -o: option. set the pipefail option
# pipefail: If set, causes the pipeline to return the exit status of the last (rightmost) 
# command to exit with a non-zero status. It returns zero if all commands in the pipeline 
# exit successfully. This option is disabled by default.
set -Eeuo pipefail

readonly namespace="hometag"
readonly image="hometag-ai:local"
readonly script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly repo_root="$(cd -- "${script_dir}/.." && pwd)"

cd "$repo_root"

for command_name in docker kubectl openssl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done

context="$(kubectl config current-context)"
if [[ "$context" != "docker-desktop" ]]; then
  printf 'Warning: current Kubernetes context is "%s", not "docker-desktop".\n' "$context" >&2
  printf 'The local image "%s" must be available to that cluster.\n' "$image" >&2
fi

printf 'Building API image %s...\n' "$image"
docker build --target runtime -t "$image" .

printf 'Applying namespace and local credentials...\n'
kubectl apply -f k8s/namespace.yaml

existing_secret="$(kubectl get secret hometag-secrets -n "$namespace" --ignore-not-found -o name)"
if [[ -z "$existing_secret" ]]; then
  postgres_password="${HOMETAG_POSTGRES_PASSWORD:-$(openssl rand -hex 24)}"
  jwt_secret_key="${HOMETAG_JWT_SECRET_KEY:-$(openssl rand -hex 32)}"
  kubectl create secret generic hometag-secrets -n "$namespace" \
    --from-literal="postgres-password=${postgres_password}" \
    --from-literal="jwt-secret-key=${jwt_secret_key}" \
    >/dev/null
  unset postgres_password jwt_secret_key
  printf 'Created hometag-secrets. It will be retained on subsequent runs.\n'
else
  printf 'Using existing hometag-secrets; credentials were not changed.\n'
fi

printf 'Starting PostgreSQL and Redis...\n'
kubectl apply -f k8s/configmap.yaml -f k8s/postgres.yaml -f k8s/redis.yaml
kubectl rollout status statefulset/postgres -n "$namespace" --timeout=300s
kubectl rollout status deployment/redis -n "$namespace" --timeout=180s

printf 'Applying database migrations...\n'
kubectl delete job hometag-migrate -n "$namespace" --ignore-not-found=true --wait=true
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete job/hometag-migrate -n "$namespace" --timeout=300s

printf 'Deploying API and Ingress...\n'
kubectl apply -f k8s/api.yaml -f k8s/ingress.yaml
kubectl rollout restart deployment/hometag-api -n "$namespace"
kubectl rollout status deployment/hometag-api -n "$namespace" --timeout=300s
kubectl get ingress -n "$namespace"

printf 'Deployment is ready. Test it at http://localhost/health/ready\n'
