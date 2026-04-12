#!/bin/bash
set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/bin:$PATH"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBSITE_DIR="$ROOT_DIR/website"
TAURI_MANIFEST="$ROOT_DIR/website/src-tauri/Cargo.toml"
DEBUG_BIN="$ROOT_DIR/website/src-tauri/target/debug/poker-master-shell"
RELEASE_BIN="$ROOT_DIR/website/src-tauri/target/release/poker-master-shell"
DIST_DIR="$ROOT_DIR/website/dist"

build_mode=""
skip_build=0

case "${1:-}" in
  --build-debug)
    build_mode="debug"
    shift
    ;;
  --build-release)
    build_mode="release"
    shift
    ;;
esac

if [[ "${1:-}" == "--no-build" ]]; then
  skip_build=1
  shift
fi

ensure_node_build_tools() {
  if ! command -v node >/dev/null 2>&1; then
    printf '%s\n' "node is required to build the PokerMaster V2 frontend."
    exit 1
  fi
}

ensure_python_deps() {
  printf '%s\n' "Checking and installing Python dependencies..."
  if command -v pip3 >/dev/null 2>&1; then
    pip3 install -r "$ROOT_DIR/requirements_2026.txt" --quiet
  elif command -v pip >/dev/null 2>&1; then
    pip install -r "$ROOT_DIR/requirements_2026.txt" --quiet
  fi
}

latest_mtime_ms() {
  ROOT_FOR_NODE="$1" \
  PATHS_FOR_NODE="$2" \
  node - <<'NODE'
const fs = require("fs");
const path = require("path");

const root = process.env.ROOT_FOR_NODE;
const relPaths = (process.env.PATHS_FOR_NODE || "")
  .split("|")
  .map((value) => value.trim())
  .filter(Boolean);

let latest = 0;

function visit(targetPath) {
  if (!fs.existsSync(targetPath)) {
    return;
  }

  const stat = fs.statSync(targetPath);
  latest = Math.max(latest, stat.mtimeMs);

  if (!stat.isDirectory()) {
    return;
  }

  for (const entry of fs.readdirSync(targetPath, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".git") {
      continue;
    }
    visit(path.join(targetPath, entry.name));
  }
}

for (const relPath of relPaths) {
  visit(path.join(root, relPath));
}

process.stdout.write(String(Math.trunc(latest)));
NODE
}

run_frontend_build() {
  ensure_node_build_tools
  printf '%s\n' "Building PokerMaster V2 frontend..."
  (
    cd "$WEBSITE_DIR"
    node node_modules/typescript/bin/tsc -p tsconfig.json
    node node_modules/typescript/bin/tsc -p tsconfig.node.json
    node node_modules/vite/bin/vite.js build
  )
}

run_tauri_build() {
  local target_mode="$1"
  printf '%s\n' "Building PokerMaster V2 shell (${target_mode})..."
  if [[ "$target_mode" == "release" ]]; then
    cargo build --release --manifest-path "$TAURI_MANIFEST"
  else
    cargo build --manifest-path "$TAURI_MANIFEST"
  fi
}

select_target_mode() {
  if [[ "$build_mode" == "release" ]]; then
    printf '%s' "release"
    return
  fi

  if [[ "$build_mode" == "debug" ]]; then
    printf '%s' "debug"
    return
  fi

  if [[ -x "$RELEASE_BIN" ]]; then
    printf '%s' "release"
  else
    printf '%s' "debug"
  fi
}

TARGET_MODE="$(select_target_mode)"

if [[ "$TARGET_MODE" == "release" ]]; then
  APP_BIN="$RELEASE_BIN"
else
  APP_BIN="$DEBUG_BIN"
fi

FRONTEND_SOURCE_MTIME="$(latest_mtime_ms "$ROOT_DIR" "website/src|website/index.html|website/package.json|website/tsconfig.json|website/tsconfig.node.json|website/vite.config.ts|website/src-tauri/tauri.conf.json")"
TAURI_SOURCE_MTIME="$(latest_mtime_ms "$ROOT_DIR" "website/src-tauri/src|website/src-tauri/Cargo.toml|website/src-tauri/build.rs|website/src-tauri/tauri.conf.json")"
DIST_MTIME="$(latest_mtime_ms "$ROOT_DIR" "website/dist")"
BIN_MTIME="$(latest_mtime_ms "$ROOT_DIR" "${APP_BIN#$ROOT_DIR/}")"

needs_frontend_build=0
needs_tauri_build=0

if [[ "$skip_build" -eq 0 ]]; then
  if [[ "$DIST_MTIME" -eq 0 || "$FRONTEND_SOURCE_MTIME" -gt "$DIST_MTIME" ]]; then
    needs_frontend_build=1
  fi

  if [[ "$build_mode" == "release" || "$build_mode" == "debug" ]]; then
    needs_frontend_build=1
    needs_tauri_build=1
  fi

  if [[ "$BIN_MTIME" -eq 0 || "$TAURI_SOURCE_MTIME" -gt "$BIN_MTIME" || "$DIST_MTIME" -gt "$BIN_MTIME" ]]; then
    needs_tauri_build=1
  fi

  if [[ "$needs_frontend_build" -eq 1 ]]; then
    run_frontend_build
    DIST_MTIME="$(latest_mtime_ms "$ROOT_DIR" "website/dist")"
    if [[ "$BIN_MTIME" -eq 0 || "$DIST_MTIME" -gt "$BIN_MTIME" ]]; then
      needs_tauri_build=1
    fi
  fi

  if [[ "$needs_tauri_build" -eq 1 ]]; then
    run_tauri_build "$TARGET_MODE"
  fi
fi

if [[ "$TARGET_MODE" == "release" && -x "$RELEASE_BIN" ]]; then
  APP_BIN="$RELEASE_BIN"
elif [[ -x "$DEBUG_BIN" ]]; then
  APP_BIN="$DEBUG_BIN"
else
  if [[ "$skip_build" -eq 1 ]]; then
    printf '%s\n' "No existing PokerMaster V2 binary found for --no-build. Run without --no-build once to create it."
    exit 1
  fi
  printf '%s\n' "No PokerMaster V2 binary found. Building the debug shell first..."
  run_frontend_build
  run_tauri_build "debug"
  APP_BIN="$DEBUG_BIN"
fi

if [[ "$skip_build" -eq 1 ]]; then
  printf '%s\n' "Skipping build checks (--no-build)."
fi

printf '%s\n' "Launching PokerMaster V2 from: $APP_BIN"
exec "$APP_BIN" "$@"
