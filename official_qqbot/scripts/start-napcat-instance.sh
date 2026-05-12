#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:?instance required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

prepend_ld_preload() {
  local lib_path="$1"
  if [ ! -f "$lib_path" ]; then
    return
  fi
  case ":${LD_PRELOAD:-}:" in
    *":$lib_path:"*) ;;
    *) export LD_PRELOAD="$lib_path${LD_PRELOAD:+:$LD_PRELOAD}" ;;
  esac
}

ensure_qqmagic_shim() {
  local source_path="$SCRIPT_DIR/napcat-qqmagic-shim.c"
  local build_dir="$PROJECT_ROOT/data/native"
  local shim_path="$build_dir/libnapcat-qqmagic.so"
  local compiler=""

  mkdir -p "$build_dir"
  if [ -f "$shim_path" ] && [ "$shim_path" -nt "$source_path" ]; then
    printf '%s\n' "$shim_path"
    return
  fi

  compiler="$(command -v cc || command -v gcc || true)"
  if [ -z "$compiler" ]; then
    echo "[napcat-launcher] Linux QQ wrapper needs a tiny qq_magic shim, but no C compiler was found. Install build-essential first." >&2
    exit 1
  fi

  "$compiler" -shared -fPIC -O2 -o "$shim_path" "$source_path"
  printf '%s\n' "$shim_path"
}

prepend_ld_preload "$(ensure_qqmagic_shim)"

for gnutls_path in /lib/x86_64-linux-gnu/libgnutls.so.30 /usr/lib/x86_64-linux-gnu/libgnutls.so.30; do
  if [ -f "$gnutls_path" ]; then
    prepend_ld_preload "$gnutls_path"
    break
  fi
done

exec node "$SCRIPT_DIR/napcat-launcher.cjs" "--instance=$INSTANCE"
