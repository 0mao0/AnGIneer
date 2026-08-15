#!/usr/bin/env bash
# Regression test: ensure_htpasswd must recover when .htpasswd is a directory
# (Docker Compose creates a directory at a missing bind-mount source).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/docker/nginx/.htpasswd"
printf 'ADMIN_PASSWORD=testpass\n' > "$TMP_DIR/.env"
cp "$SCRIPT_DIR/deploy.sh" "$TMP_DIR/docker/deploy.sh"

(
    cd "$TMP_DIR/docker"
    bash deploy.sh --prepare
)

if [ ! -f "$TMP_DIR/docker/nginx/.htpasswd" ]; then
    echo "FAIL: .htpasswd was not created as a file" >&2
    exit 1
fi

if ! grep -q '^admin:' "$TMP_DIR/docker/nginx/.htpasswd"; then
    echo "FAIL: .htpasswd does not contain expected credentials" >&2
    cat "$TMP_DIR/docker/nginx/.htpasswd" >&2
    exit 1
fi

echo "PASS: ensure_htpasswd recovers from .htpasswd directory"

# Existing valid file must be preserved (no regeneration/overwrite).
mkdir -p "$TMP_DIR/docker/nginx"
printf 'admin:oldhash\n' > "$TMP_DIR/docker/nginx/.htpasswd"

(
    cd "$TMP_DIR/docker"
    bash deploy.sh --prepare
)

if [ "$(cat "$TMP_DIR/docker/nginx/.htpasswd")" != "admin:oldhash" ]; then
    echo "FAIL: existing .htpasswd file was overwritten" >&2
    exit 1
fi

echo "PASS: existing .htpasswd file is preserved"
