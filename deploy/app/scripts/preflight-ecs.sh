#!/usr/bin/env bash
set -euo pipefail

log() {
	printf '[preflight] %s\n' "$*"
}

die() {
	printf '[preflight:error] %s\n' "$*" >&2
	exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -n "${AI_BIOWORKFLOW_DEPLOY_DIR:-}" ]]; then
	deploy_dir="$AI_BIOWORKFLOW_DEPLOY_DIR"
elif [[ -f "$script_dir/../docker-compose.prod.yml" ]]; then
	deploy_dir="$(cd "$script_dir/.." && pwd -P)"
else
	deploy_dir="$(pwd -P)"
fi

compose_file="${AI_BIOWORKFLOW_COMPOSE_FILE:-docker-compose.prod.yml}"
deploy_env_file="${AI_BIOWORKFLOW_DEPLOY_ENV_FILE:-.env.deploy}"
images_env_file="${AI_BIOWORKFLOW_IMAGES_ENV_FILE:-.env.images}"
min_free_mb="${AI_BIOWORKFLOW_PREFLIGHT_MIN_FREE_MB:-512}"
temp_images_env=""

cleanup() {
	if [[ -n "$temp_images_env" && -f "$temp_images_env" ]]; then
		rm -f "$temp_images_env"
	fi
}
trap cleanup EXIT

resolve_deploy_path() {
	local value="$1"
	if [[ "$value" = /* ]]; then
		printf '%s' "$value"
	else
		printf '%s/%s' "$deploy_dir" "${value#./}"
	fi
}

read_env_value() {
	local file="$1"
	local name="$2"
	local value
	value="$(grep -E "^${name}=" "$file" | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
	value="${value%\"}"
	value="${value#\"}"
	value="${value%\'}"
	value="${value#\'}"
	printf '%s' "$value"
}

require_command() {
	local name="$1"
	command -v "$name" >/dev/null 2>&1 || die "Required command not found: $name"
}

require_file() {
	local path="$1"
	local label="$2"
	[[ -f "$path" ]] || die "$label not found: $path"
}

validate_positive_integer() {
	local name="$1"
	local value="$2"
	[[ "$value" =~ ^[1-9][0-9]*$ ]] || die "$name must be a positive integer"
}

validate_port() {
	local name="$1"
	local value="$2"
	validate_positive_integer "$name" "$value"
	(( 10#$value <= 65535 )) || die "$name must be between 1 and 65535"
}

validate_image_ref() {
	local name="$1"
	local value="$2"
	[[ -n "$value" ]] || die "$name is required"
	[[ "$value" != *[[:space:]]* ]] || die "$name must not contain whitespace"
}

compose_path="$(resolve_deploy_path "$compose_file")"
deploy_env_path="$(resolve_deploy_path "$deploy_env_file")"
images_env_path="$(resolve_deploy_path "$images_env_file")"

log "Checking deployment directory: $deploy_dir"
[[ -d "$deploy_dir" ]] || die "Deploy directory not found: $deploy_dir"
[[ -w "$deploy_dir" ]] || die "Deploy directory is not writable by the current user: $deploy_dir"
require_file "$compose_path" "Compose file"
require_file "$deploy_env_path" "Deploy env file"

runtime_env_file="$(read_env_value "$deploy_env_path" AI_BIOWORKFLOW_RUNTIME_ENV_FILE)"
runtime_env_file="${runtime_env_file:-./.env.prod}"
if [[ "$runtime_env_file" = /* ]]; then
	runtime_env_path="$runtime_env_file"
else
	runtime_env_path="$deploy_dir/${runtime_env_file#./}"
fi
require_file "$runtime_env_path" "Runtime env file"

site_address="$(read_env_value "$deploy_env_path" AI_BIOWORKFLOW_SITE_ADDRESS)"
tls_email="$(read_env_value "$deploy_env_path" AI_BIOWORKFLOW_TLS_EMAIL)"
[[ -n "$site_address" ]] || die "AI_BIOWORKFLOW_SITE_ADDRESS must be set in $deploy_env_path"
[[ -n "$tls_email" ]] || die "AI_BIOWORKFLOW_TLS_EMAIL must be set in $deploy_env_path"

http_port="$(read_env_value "$deploy_env_path" AI_BIOWORKFLOW_HTTP_PORT)"
https_port="$(read_env_value "$deploy_env_path" AI_BIOWORKFLOW_HTTPS_PORT)"
validate_port AI_BIOWORKFLOW_HTTP_PORT "${http_port:-80}"
validate_port AI_BIOWORKFLOW_HTTPS_PORT "${https_port:-443}"

validate_positive_integer AI_BIOWORKFLOW_PREFLIGHT_MIN_FREE_MB "$min_free_mb"
df_line="$(df -Pk "$deploy_dir" | tail -n 1)"
read -r _fs _blocks _used available_kb _capacity _mount <<< "$df_line"
available_mb=$((available_kb / 1024))
if (( available_mb < min_free_mb )); then
	die "Only ${available_mb}MB free under $deploy_dir; require at least ${min_free_mb}MB"
fi
log "Free space check passed: ${available_mb}MB available"

require_command docker
require_command curl
docker info >/dev/null 2>&1 || die "Docker daemon is not available to the current user"
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is not available"

compose_images_env_path=""
if [[ -f "$images_env_path" ]]; then
	api_image="$(read_env_value "$images_env_path" AI_BIOWORKFLOW_API_IMAGE)"
	web_image="$(read_env_value "$images_env_path" AI_BIOWORKFLOW_WEB_IMAGE)"
	validate_image_ref AI_BIOWORKFLOW_API_IMAGE "$api_image"
	validate_image_ref AI_BIOWORKFLOW_WEB_IMAGE "$web_image"
	compose_images_env_path="$images_env_path"
elif [[ -n "${AI_BIOWORKFLOW_API_IMAGE:-}" || -n "${AI_BIOWORKFLOW_WEB_IMAGE:-}" ]]; then
	validate_image_ref AI_BIOWORKFLOW_API_IMAGE "${AI_BIOWORKFLOW_API_IMAGE:-}"
	validate_image_ref AI_BIOWORKFLOW_WEB_IMAGE "${AI_BIOWORKFLOW_WEB_IMAGE:-}"
	temp_images_env="$(mktemp "${deploy_dir}/.env.images.preflight.XXXXXX")"
	{
		printf 'AI_BIOWORKFLOW_API_IMAGE=%s\n' "$AI_BIOWORKFLOW_API_IMAGE"
		printf 'AI_BIOWORKFLOW_WEB_IMAGE=%s\n' "$AI_BIOWORKFLOW_WEB_IMAGE"
	} > "$temp_images_env"
	compose_images_env_path="$temp_images_env"
else
	die "Set AI_BIOWORKFLOW_API_IMAGE and AI_BIOWORKFLOW_WEB_IMAGE, or create $images_env_path"
fi

if [[ -n "$compose_images_env_path" ]]; then
	log "Validating Compose configuration"
	docker compose --env-file "$deploy_env_path" --env-file "$compose_images_env_path" -f "$compose_path" config >/dev/null
fi

log "Preflight checks passed"
