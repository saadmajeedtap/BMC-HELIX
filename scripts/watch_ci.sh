#!/usr/bin/env bash
# Watch the CI build: the runner pushes build/state.txt to the docs-build branch
# every ~100 s, so progress is readable from anywhere with internet access.
#
#   bash scripts/watch_ci.sh [interval_seconds]
#
# Repo override: REPO=owner/name bash scripts/watch_ci.sh
set -uo pipefail
REPO="${REPO:-saadmajeedtap/BMC-HELIX}"
BRANCH="${BRANCH:-docs-build}"
INTERVAL="${1:-60}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

while :; do
  url="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  if curl -sS --max-time 60 -o "$TMP/t.tgz" "$url" 2>"$TMP/err"; then
    rm -rf "$TMP/x"; mkdir -p "$TMP/x"
    if tar xzf "$TMP/t.tgz" -C "$TMP/x" --strip-components=1 2>/dev/null; then
      clear 2>/dev/null || true
      echo "=== $REPO  branch:$BRANCH   $(date -u +%FT%TZ) ==="
      if [ -f "$TMP/x/build/state.txt" ]; then
        sed -n '1,6p' "$TMP/x/build/state.txt"
        echo
        echo "--- phases ---"
        grep -E "^phase |^--- phase|^state:" "$TMP/x/build/report.md" 2>/dev/null | tail -12
        echo "--- coverage ---"
        grep -E "coverage:|pdf bytes|BUILD INCOMPLETE|NOTE:|release:" \
          "$TMP/x/build/report.md" 2>/dev/null | tail -6
        echo "--- files on the branch ---"
        ls -la "$TMP/x/build" 2>/dev/null | awk 'NR>3 {printf "  %-34s %8.1f MB\n", $9, $5/1048576}'
      else
        echo "no build/state.txt yet (the workflow has not reached a push)"
      fi
    fi
  else
    echo "could not read $url: $(head -c 200 "$TMP/err")"
  fi
  sleep "$INTERVAL"
done
