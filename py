#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
venv_python="${repo_root}/.venv/bin/python"

if [[ ! -x "${venv_python}" ]]; then
  echo "error: venv python not found/executable at: ${venv_python}" >&2
  echo "hint: create it with: python3 -m venv .venv" >&2
  exit 1
fi

exec "${venv_python}" "$@"

