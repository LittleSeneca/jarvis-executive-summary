#!/usr/bin/env bash
# Reads the project-root .env file and writes each KEY=VALUE as a SecureString
# to AWS SSM Parameter Store under /jarvis/<KEY>.
#
# Usage (called by terraform null_resource, or directly):
#   bash scripts/sync_env_to_ssm.sh [--region REGION] [--profile PROFILE]
#
# The .env path is always <repo_root>/.env (i.e. ../.env relative to this
# script). If it is missing, the script errors out — add a .env to the root
# of the project before running.
#
# --region defaults to us-east-1.
# --profile defaults to the default AWS credential chain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
AWS_REGION="us-east-1"
AWS_PROFILE=""

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      AWS_REGION="${2:?--region requires a value}"
      shift 2
      ;;
    --region=*)
      AWS_REGION="${1#--region=}"
      shift
      ;;
    --profile)
      AWS_PROFILE="${2:?--profile requires a value}"
      shift 2
      ;;
    --profile=*)
      AWS_PROFILE="${1#--profile=}"
      shift
      ;;
    -h|--help)
      usage 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "sync_env_to_ssm: unexpected argument '$1'" >&2
      usage 2
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "sync_env_to_ssm: no .env file found at '$ENV_FILE'" >&2
  echo "sync_env_to_ssm: you first need to add a .env to the root of the project" >&2
  exit 1
fi

echo "sync_env_to_ssm: syncing '$ENV_FILE' → SSM /jarvis/* (region: $AWS_REGION)"

PROFILE_ARGS=()
if [[ -n "$AWS_PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$AWS_PROFILE")
fi

SYNCED=0
FAILED=0

while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip blank lines and comment-only lines
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

  # Strip trailing inline comments (everything from first # after a space)
  line="${line%%  #*}"
  line="${line%% #*}"

  # Must contain = to be a variable
  [[ "$line" != *=* ]] && continue

  key="${line%%=*}"
  value="${line#*=}"

  # Trim whitespace from key
  key="$(echo "$key" | tr -d '[:space:]')"
  [[ -z "$key" ]] && continue

  if aws ssm put-parameter \
    --name "/jarvis/${key}" \
    --value "${value}" \
    --type SecureString \
    --overwrite \
    --region "$AWS_REGION" \
    "${PROFILE_ARGS[@]}" \
    --no-cli-pager \
    > /dev/null 2>&1; then
    SYNCED=$((SYNCED + 1))
  else
    echo "sync_env_to_ssm: WARN — failed to sync /jarvis/${key}" >&2
    FAILED=$((FAILED + 1))
  fi

done < "$ENV_FILE"

echo "sync_env_to_ssm: done — ${SYNCED} synced, ${FAILED} failed"
[[ "$FAILED" -eq 0 ]] || exit 1
