#!/usr/bin/env bash
# CI driver for the offline PDF build. Runs the same scripts a local user runs,
# and keeps publishing state + reports to the `docs-build` branch while it works,
# so a failure (even a killed job) is still diagnosable from the repository.
set -uo pipefail
W="${WORKDIR:-/tmp/helix-build}"
mkdir -p "$W"
BRANCH="docs-build"
REPO="${GITHUB_WORKSPACE:-$(pwd)}"
: > "$W/report.md"
: > "$W/progress.txt"
BUILD_RC_FILE="$W/build-rc"
echo 0 > "$BUILD_RC_FILE"

note() { echo "$*" | tee -a "$W/report.md" >> "$W/progress.txt"; }

push_state() {
  local msg="$1"
  mkdir -p "$REPO/build"
  cp "$W/report.md" "$REPO/build/report.md" 2>/dev/null || true
  { echo "state: $msg"; echo "at:  $(date -u +%FT%TZ)"; echo;
    tail -c 6000 "$W/report.md" 2>/dev/null; } > "$REPO/build/state.txt"
  for f in summary.json coverage.md coverage.json inventory.json structure.json \
           page-map.json render-index.json tree-probe.json attachments.json \
           excerpt.pdf samples.tgz "$(basename "${OUT_PDF:-none}")"; do
    [ -e "$W/$f" ] && cp "$W/$f" "$REPO/build/$f" 2>/dev/null
  done
  # a lock keeps the heartbeat and the main flow from tripping over each other
  mkdir -p /tmp/gitlock 2>/dev/null
  if mkdir /tmp/gitlock/lock 2>/dev/null; then
    ( cd "$REPO" && git add -f build >/dev/null 2>&1 \
        && git commit -qm "state: $msg" >/dev/null 2>&1 \
        && git push -f origin "HEAD:$BRANCH" >/dev/null 2>&1 ) || true
    rmdir /tmp/gitlock/lock 2>/dev/null
  fi
}

on_exit() {
  local rc=$?
  echo "FINAL rc=$rc" >> "$W/report.md"
  push_state "exit rc=$rc"
  [ -n "${HB_PID:-}" ] && kill "$HB_PID" 2>/dev/null
  exit "$rc"
}
trap on_exit EXIT INT TERM

echo "## build log" >> "$W/report.md"
OUT_PDF="$W/$(echo "${PRODUCT:-BMC-Helix-ITSM}" | tr ' ' '-')-${VERSION:-26.3}-complete.pdf"
export OUT_PDF

( cd "$REPO" && git config user.name "github-actions[bot]" \
    && git config user.email "41898282+github-actions[bot]@users.noreply.github.com" \
    && git checkout -B "$BRANCH" >/dev/null 2>&1 ) || true
push_state "start"
( while :; do sleep 100; push_state "heartbeat"; done ) & HB_PID=$!

{
note "date: $(date -u +%FT%TZ)  runner: $(uname -m)  sections=${ONLY_SECTIONS:-ALL}"
note "disk: $(df -h /tmp | tail -1 | tr -s ' ')"

note "## system deps"
sudo apt-get update -qq >/dev/null 2>&1 || true
sudo apt-get install -y -qq libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 libjpeg62-turbo libopenjp2-7 fonts-dejavu-core \
  fonts-liberation fonts-dejavu-extra zip >/dev/null 2>&1 || true
note "fonts: $(fc-list 2>/dev/null | wc -l)"

note "## python deps"
python3 -m pip install -q --upgrade pip >/dev/null 2>&1
python3 -m pip install -q -r requirements.txt
note "$(python3 -c "
import weasyprint, sys, pypdf, reportlab, bs4, PIL
print('weasyprint', weasyprint.__version__, '| pypdf', pypdf.__version__,
      '| reportlab', reportlab.Version, '| python', sys.version.split()[0])" 2>&1 | tail -2)"

note "## selftest (offline logic + engine semantics)"
python3 scripts/selftest.py --work /tmp/helix-selftest --with-render 2>&1 \
  | tail -22 | tee -a "$W/report.md"
grep -q "SELFTEST PASSED" "$W/report.md" || echo 5 > "$BUILD_RC_FILE"

note "## integration test (mock portal, end to end)"
python3 scripts/integration_test.py --full 2>&1 | tail -12 | tee -a "$W/report.md"
grep -q "INTEGRATION PASSED" "$W/report.md" || echo 6 > "$BUILD_RC_FILE"

note "## portal diagnostics (tree fragment as the site serves it)"
python3 - <<'PY' 2>&1 | tee -a "$W/report.md" || true
import os, re, requests
base = "https://docs.helixops.ai"; sp = os.environ.get("SPACE_PATH", "")
sd = sp.replace("/", ".")
url = (f"{base}/bin/get/{sp}/WebHome/?outputSyntax=plain&sheet=XWiki.ExportDocumentTree"
       f"&filterHiddenDocuments=false&showTranslations=false&limit=50&root=document%3Axwiki%3A{sd}.WebHome")
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
print(f"- fragment http={r.status_code} bytes={len(r.text)}")
print("```")
print(re.sub(r"\s+", " ", r.text)[:1200])
print("```")
PY
push_state "pre-build"

note "## build"
python3 scripts/build_docs_pdf.py \
  --space-path "${SPACE_PATH}" --product "${PRODUCT}" --version "${VERSION}" \
  --workspace "$W" --out "$OUT_PDF" --phases "${PHASES:-inventory,fetch,render,assemble,verify}" \
  --engine "${ENGINE:-weasyprint}" --workers "${WORKERS:-3}" \
  --http-workers "${HTTP_WORKERS:-8}" --delay "${DELAY:-0.08}" \
  ${ONLY_SECTIONS:+--only-sections "$ONLY_SECTIONS"} \
  ${MAX_DOCS:+--max-docs "$MAX_DOCS"} \
  ${NO_ATTACH:+--no-attachments} ${NO_STAMP:+--no-stamp} \
  --report "$W/coverage-report.md" 2>&1 | tail -120 | tee -a "$W/report.md"
echo "${PIPESTATUS[0]}" > "$BUILD_RC_FILE"
note "build exit code: $(cat "$BUILD_RC_FILE")"
} 2>&1 | tee -a "$W/report.md"

{
echo; echo "## results"; echo '```'
[ -f "$W/summary.json" ] && python3 -c "import json;print(json.dumps(json.load(open('$W/summary.json')),indent=1)[:2600])"
echo '```'
[ -f "$W/coverage-report.md" ] && sed -n '1,70p' "$W/coverage-report.md"
echo; echo '```'; ls -la "$W" | head -22; [ -f "$OUT_PDF" ] && du -h "$OUT_PDF"
[ -d "$W/attachments" ] && du -sh "$W/attachments"
echo '```'
} >> "$W/report.md"

# small review artifacts
python3 - <<PY 2>&1 | tail -3 || true
import json, os
w, pdf = "$W", "$OUT_PDF"
if os.path.exists(pdf):
    st = os.path.join(w, "structure.json")
    os.system(f"python3 scripts/make_excerpt.py '{pdf}' --structure '{st}' "
              f"--out '{w}/excerpt.pdf' --pages 16 || true")
if os.path.isdir(os.path.join(w, "samples")):
    os.system(f"cd '{w}' && tar czf samples.tgz samples || true")
if os.path.isdir(os.path.join(w, "attachments")):
    os.system(f"cd '{w}' && zip -qr attachments.zip attachments || true")
PY

sz=0; [ -f "$OUT_PDF" ] && sz=$(stat -c%s "$OUT_PDF")
echo "pdf bytes: $sz" >> "$W/report.md"
if [ "$sz" -gt 0 ] && [ "$sz" -lt 40000000 ] && [ "${COMMIT_PDF:-1}" = "1" ]; then
  cp "$OUT_PDF" "$W/$(basename "$OUT_PDF")" 2>/dev/null || true
  echo "- full PDF committed to branch $BRANCH" >> "$W/report.md"
fi
for f in "$(basename "$OUT_PDF")" attachments.zip; do
  p="$W/$f"
  if [ -e "$p" ] && [ "$(stat -c%s "$p" 2>/dev/null || echo 0)" -lt 40000000 ]; then
    cp "$p" "$REPO/build/$f" 2>/dev/null || true
  fi
done
push_state "final"

if [ "${PUBLISH_RELEASE:-0}" = "1" ] && [ -f "$OUT_PDF" ]; then
  tag="docs-$(echo "$PRODUCT" | tr 'A-Z ' 'a-z-')-$VERSION-$(date -u +%Y%m%d-%H%M)"
  mapfile -t ASSETS < <(for f in "$OUT_PDF" "$W/attachments.zip" "$W/coverage.json" \
                              "$W/page-map.json" "$W/inventory.json" "$W/excerpt.pdf"; do
                          [ -e "$f" ] && echo "$f"; done)
  { echo "## What this is"; echo; echo "Complete offline PDF of \`$SPACE_PATH\` built by"
    echo "\`.github/workflows/build-docs-pdf.yml\`. Every internal documentation link is an";
    echo "in-document jump (no redirects to docs.helixops.ai). See the coverage report below.";
    echo; echo '```'; [ -f "$W/coverage-report.md" ] && sed -n '1,60p' "$W/coverage-report.md"; echo '```';
  } > "$W/notes.md"
  gh release create "$tag" --title "$PRODUCT $VERSION - complete documentation (offline PDF)" \
    --notes-file "$W/notes.md" "${ASSETS[@]}" 2>&1 | tail -2 \
    || { note "single-asset upload failed; splitting"; split -C 95m "$OUT_PDF" "$W/part-"; \
         gh release create "$tag" --title "$PRODUCT $VERSION - complete documentation (parts)" \
           --notes-file "$W/notes.md" "$W"/part-* "$W/attachments.zip" 2>&1 | tail -2 || true; }
  echo "release: $tag" >> "$W/report.md"
  push_state "released $tag"
fi

RC=$(cat "$BUILD_RC_FILE" 2>/dev/null || echo 0)
exit "$RC"
