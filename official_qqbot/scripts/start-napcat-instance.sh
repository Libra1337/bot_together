#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:?instance required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

if [ -z "${LD_PRELOAD:-}" ]; then
  for gnutls_path in /lib/x86_64-linux-gnu/libgnutls.so.30 /usr/lib/x86_64-linux-gnu/libgnutls.so.30; do
    if [ -f "$gnutls_path" ]; then
      export LD_PRELOAD="$gnutls_path"
      break
    fi
  done
fi

exec node "$SCRIPT_DIR/napcat-launcher.cjs" "--instance=$INSTANCE"
