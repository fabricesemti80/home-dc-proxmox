#!/usr/bin/env bash
# macOS Bash 3.2 compatible; never sources environment files.
set -eu
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
python="${PROXMOX_PYTHON:-python3}"
if ! command -v "$python" >/dev/null 2>&1; then
  echo 'standalone-host: controller Python is missing; run task proxmox:init in the control repo' >&2
  exit 2
fi
case "$python" in
  /*) PATH="$(dirname "$python"):$PATH"; export PATH ;;
esac
exec "$python" "$script_dir/../standalone/controller.py" "$@"
