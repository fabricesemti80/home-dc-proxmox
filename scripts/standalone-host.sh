#!/usr/bin/env bash
# macOS Bash 3.2 compatible; never sources environment files.
set -eu
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
  echo 'standalone-host: Python 3 is required in the controller environment' >&2
  exit 2
fi
exec python3 "$script_dir/../standalone/controller.py" "$@"
