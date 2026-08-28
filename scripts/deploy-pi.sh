#!/usr/bin/env bash
# Deploy NRGMon to a Raspberry Pi over SSH. See README.md for prerequisites.
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
config_file=${1:-"$project_root/deploy.env"}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

config_value() {
  local key=$1 value
  value=$(sed -n "s/^${key}=//p" "$config_file" | tail -n 1)
  printf '%s' "$value"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "'$1' is required locally."
}

[ -f "$config_file" ] || fail "Configuration file not found: $config_file"
require_command ssh
require_command scp
require_command docker

deploy_host=$(config_value DEPLOY_HOST)
deploy_user=$(config_value DEPLOY_USER)
deploy_port=$(config_value DEPLOY_PORT)
deploy_password=$(config_value DEPLOY_PASSWORD)
deploy_path=$(config_value DEPLOY_PATH)
grafana_port=$(config_value GRAFANA_PORT)
kiosk_port=$(config_value KIOSK_PORT)
kiosk_port=${kiosk_port:-8080}

[ -n "$deploy_host" ] && [ "$deploy_host" != CHANGE_ME ] || fail "Set DEPLOY_HOST in $config_file."
[ -n "$deploy_user" ] || fail "Set DEPLOY_USER in $config_file."
case "$deploy_port" in
  ''|*[!0-9]*) fail "DEPLOY_PORT must be a number." ;;
esac
case "$deploy_path" in
  /*) ;;
  *) fail "DEPLOY_PATH must be an absolute path on the Pi." ;;
esac
case "$deploy_path" in
  *[!A-Za-z0-9._/-]*) fail "DEPLOY_PATH may contain only letters, numbers, '.', '_', '/', and '-'." ;;
esac
case "$grafana_port" in
  ''|*[!0-9]*) fail "GRAFANA_PORT must be a number." ;;
esac
case "$kiosk_port" in
  ''|*[!0-9]*) fail "KIOSK_PORT must be a number." ;;
esac

if rg -q '^[^#].*CHANGE_ME' "$config_file"; then
  fail "Replace every CHANGE_ME value in $config_file before deploying."
fi

runtime_env=$(mktemp "${TMPDIR:-/tmp}/nrgmon-env.XXXXXX")
askpass_file=
cleanup() {
  rm -f "$runtime_env" "$askpass_file"
}
trap cleanup EXIT
chmod 600 "$runtime_env"
awk '!/^(DEPLOY_|#|$)/ { print }' "$config_file" > "$runtime_env"

# Validate the generated runtime configuration before copying any files.
(cd "$project_root" && ENV_FILE="$runtime_env" docker compose config -q)

target="${deploy_user}@${deploy_host}"
ssh_options=(-p "$deploy_port")
scp_options=(-P "$deploy_port")

run_ssh() {
  if [ -n "$deploy_password" ]; then
    DISPLAY=none SSH_ASKPASS="$askpass_file" SSH_ASKPASS_REQUIRE=force DEPLOY_PASSWORD="$deploy_password" ssh "$@"
  else
    ssh "$@"
  fi
}

run_scp() {
  if [ -n "$deploy_password" ]; then
    DISPLAY=none SSH_ASKPASS="$askpass_file" SSH_ASKPASS_REQUIRE=force DEPLOY_PASSWORD="$deploy_password" scp "$@"
  else
    scp "$@"
  fi
}

if [ -n "$deploy_password" ]; then
  askpass_file=$(mktemp "${TMPDIR:-/tmp}/nrgmon-askpass.XXXXXX")
  chmod 700 "$askpass_file"
  printf '%s\n' '#!/bin/sh' 'printf "%s\\n" "$DEPLOY_PASSWORD"' > "$askpass_file"
fi

printf 'Preparing %s on %s...\n' "$deploy_path" "$target"
run_ssh -tt "${ssh_options[@]}" "$target" "
  set -eu
  if ! command -v docker >/dev/null 2>&1 || { ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; }; then
    command -v apt-get >/dev/null 2>&1 || { echo 'Docker must be installed manually on this host.' >&2; exit 1; }
    sudo apt-get update
    if apt-cache show docker-compose-plugin >/dev/null 2>&1; then
      compose_package=docker-compose-plugin
    elif apt-cache show docker-compose-v2 >/dev/null 2>&1; then
      compose_package=docker-compose-v2
    elif apt-cache show docker-compose >/dev/null 2>&1; then
      compose_package=docker-compose
    else
      echo 'No Docker Compose package is available from this host APT sources.' >&2
      exit 1
    fi
    sudo apt-get install -y docker.io \"\$compose_package\" curl
  fi
  command -v curl >/dev/null
  sudo systemctl start docker
  mkdir -p '$deploy_path'
  if ! docker info >/dev/null 2>&1; then
    sudo usermod -aG docker "\$USER"
    sudo docker info >/dev/null
  fi
  docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null
"

printf 'Copying application files...\n'
run_scp "${scp_options[@]}" "$project_root/Dockerfile" "$project_root/compose.yaml" "$project_root/requirements.txt" "$target:$deploy_path/"
run_scp -r "${scp_options[@]}" "$project_root/collector" "$project_root/grafana" "$project_root/kiosk" "$project_root/prometheus" "$target:$deploy_path/"
run_scp "${scp_options[@]}" "$runtime_env" "$target:$deploy_path/.env"

printf 'Building, starting, and smoke-testing NRGMon...\n'
run_ssh -tt "${ssh_options[@]}" "$target" "
  set -eu
  cd '$deploy_path'
  if docker compose version >/dev/null 2>&1; then
    compose='docker compose'
  else
    compose=docker-compose
  fi
  \$compose config -q
  \$compose up -d --build --remove-orphans >/dev/null

  healthy=0
  for attempt in \$(seq 1 30); do
    running=\$(\$compose ps -q | wc -l | tr -d ' ')
    if [ \"\$running\" = 4 ] && curl --fail --silent --show-error 'http://127.0.0.1:$grafana_port/api/health' >/dev/null && curl --fail --silent --show-error 'http://127.0.0.1:$kiosk_port/' >/dev/null; then
      healthy=1
      break
    fi
    sleep 2
  done

  if [ \"\$healthy\" != 1 ]; then
    echo 'Smoke test failed. Recent container status and logs:' >&2
    \$compose ps >&2
    \$compose logs --tail=100 >&2
    exit 1
  fi

  sudo systemctl enable docker
  echo 'Smoke test passed. Docker is enabled to start NRGMon after reboot.'
"

printf 'Deployment complete: Grafana http://%s:%s; kiosk http://%s:%s\n' "$deploy_host" "$grafana_port" "$deploy_host" "$kiosk_port"
