#!/usr/bin/env bash
# CI driver for the offline PDF build.
#
# Design notes (learned the hard way on this repo):
#  * one phase per python invocation, so a killed/cancelled run resumes from the
#    workspace and the log names the exact phase that died;
#  * logs are streamed to $W/build.log (never through `tail`, which buffers and
#    hides progress when a job dies);
#  * state (report + progress + artifacts) is pushed to the `docs-build` branch
#    every ~100 s, so even an externally cancelled job leaves a diagnosable trail.
set -uo pipefail
W="${WORKDIR:-/tmp/helix-build}"
mkdir -p "$W"
BRANCH="docs-build"
REPO="${GITHUB_WORKSPACE:-$(pwd)}"
BUILD_RC_FILE="$W/build-rc"
echo 0 > "$BUILD_RC_FILE"
: > "$W/report.md"
: > "$W/build.log"
OUT_PDF="$W/$(echo "${PRODUCT:-BMC-Helix-ITSM}" | tr ' ' '-')-${VERSION:-26.3}-complete.pdf"
export OUT_PDF W

note() { echo "$*" >> "$W/report.md"; }

# built as an array so values with spaces (product names, section lists) survive
ARGS=(--space-path "${SPACE_PATH}" --product "${PRODUCT}" --version "${VERSION}"
      --workspace "$W" --out "$OUT_PDF" --engine "${ENGINE:-weasyprint}"
      --workers "${WORKERS:-3}" --http-workers "${HTTP_WORKERS:-8}"
      --delay "${DELAY:-0.08}" --nav-batch "${NAV_BATCH:-60}"
      --image-max-width "${IMAGE_MAX_WIDTH:-1200}" --image-quality "${IMAGE_QUALITY:-72}")
[ -n "${ONLY_SECTIONS:-}" ] && ARGS+=(--only-sections "${ONLY_SECTIONS}")
[ -n "${MAX_DOCS:-}" ] && [ "${MAX_DOCS}" != "0" ] && ARGS+=(--max-docs "${MAX_DOCS}")
[ "${NO_ATTACH:-0}" = "1" ] && ARGS+=(--no-attachments)
[ "${NO_IMAGE_OPT:-0}" = "1" ] && ARGS+=(--no-image-optimize)
[ "${NO_STAMP:-0}" = "1" ] && ARGS+=(--no-stamp)
[ -n "${TIME_BUDGET:-}" ] && [ "${TIME_BUDGET}" != "0" ] && ARGS+=(--time-budget "${TIME_BUDGET}")

push_state() {
  local msg="$1"
  mkdir -p "$REPO/build"
  { echo "state: $msg"
    echo "at:  $(date -u +%FT%TZ)"
    echo "load: $(uptime 2>/dev/null | sed 's/^ *//')"
    echo "mem:  $(free -m 2>/dev/null | awk '/Mem:/{print $3"/"$2" MB"}')"
    echo "disk: $(df -h /tmp | tail -1 | tr -s ' ')"
    echo; echo "## report"
    tail -c 3000 "$W/report.md" 2>/dev/null
    echo; echo "## live build log (last 40 lines)"
    tail -40 "$W/build.log" 2>/dev/null; } > "$REPO/build/state.txt"
  cp "$W/report.md" "$REPO/build/report.md" 2>/dev/null || true
  for f in summary.json coverage.md coverage.json inventory.json structure.json \
           page-map.json render-index.json tree-probe.json attachments.json \
           excerpt.pdf samples.tgz attachments.zip "$(basename "$OUT_PDF")"; do
    [ -e "$W/$f" ] && cp "$W/$f" "$REPO/build/$f" 2>/dev/null
  done
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
  note "FINAL rc=$rc at $(date -u +%FT%TZ)"
  push_state "exit rc=$rc"
  [ -n "${HB_PID:-}" ] && kill "$HB_PID" 2>/dev/null
  exit "$rc"
}
trap on_exit EXIT INT TERM

( cd "$REPO" && git config user.name "github-actions[bot]" \
    && git config user.email "41898282+github-actions[bot]@users.noreply.github.com" \
    && git checkout -B "$BRANCH" >/dev/null 2>&1 ) || true
push_state "start"
( while :; do sleep 100; push_state "heartbeat"; done ) & HB_PID=$!

note "## build log"
note "date: $(date -u +%FT%TZ)  runner: $(uname -m)  sections=${ONLY_SECTIONS:-ALL}"
note "args: ${ARGS[*]}"

echo "## system deps" | tee -a "$W/report.md"
sudo apt-get update -qq >/dev/null 2>&1 || true
sudo apt-get install -y -qq libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 libjpeg62-turbo libopenjp2-7 fonts-dejavu-core \
  fonts-liberation fonts-dejavu-extra zip >/dev/null 2>&1 || true
note "fonts: $(fc-list 2>/dev/null | wc -l)  mem: $(free -m | awk '/Mem:/{print $2}') MB"

echo "## python deps" | tee -a "$W/report.md"
python3 -m pip install -q --upgrade pip >/dev/null 2>&1
python3 -m pip install -q -r requirements.txt 2>&1 | tail -3 | tee -a "$W/report.md"
python3 -c "
import weasyprint, pypdf, reportlab
print('weasyprint', weasyprint.__version__, '| pypdf', pypdf.__version__,
      '| reportlab', reportlab.Version)" 2>&1 | tee -a "$W/report.md"

echo "## selftest (offline logic + engine semantics)" | tee -a "$W/report.md"
python3 scripts/selftest.py --work /tmp/helix-selftest --with-render >> "$W/build.log" 2>&1
rc=$?; tail -24 "$W/build.log" >> "$W/report.md"
if grep -q "SELFTEST PASSED" "$W/report.md"; then note "selftest: PASSED"; else note "selftest: FAILED rc=$rc"; echo 5 > "$BUILD_RC_FILE"; fi

echo "## integration test (mock portal, end to end)" | tee -a "$W/report.md"
: > "$W/build.log"
python3 scripts/integration_test.py --full >> "$W/build.log" 2>&1
rc=$?; tail -20 "$W/build.log" >> "$W/report.md"
if grep -q "INTEGRATION PASSED" "$W/report.md"; then note "integration: PASSED"; else note "integration: FAILED rc=$rc"; echo 6 > "$BUILD_RC_FILE"; fi
push_state "tests done"

: > "$W/build.log"
note "## build phases"
PASSES=(inventory fetch render assemble verify)
[ -n "${PHASES:-}" ] && read -r -a PASSES <<< "${PHASES//,/ }"
for ph in "${PASSES[@]}"; do
  [ "$(cat "$BUILD_RC_FILE")" != "0" ] && break
  note "--- phase: $ph (started $(date -u +%T)) ---"
  echo "=== phase $ph ===" >> "$W/build.log"
  timeout -k 30 "${PHASE_TIMEOUT:-3000}" python3 scripts/build_docs_pdf.py \
      --phases "$ph" "${ARGS[@]}" >> "$W/build.log" 2>&1
  rc=$?
  echo "$rc" > "$W/last-phase-rc"
  note "phase $ph rc=$rc ended $(date -u +%T)  |  $(tail -3 "$W/build.log" | tr '\n' ' ' | tail -c 400)"
  push_state "phase $ph rc=$rc"
  [ "$rc" != "0" ] && echo "$rc" > "$BUILD_RC_FILE"
done

{
echo; echo "## live log tail"; echo '```'; tail -25 "$W/build.log"; echo '```'
echo; echo "## results"; echo '```'
[ -f "$W/summary.json" ] && python3 -c "import json;print(json.dumps(json.load(open('$W/summary.json')),indent=1)[:2400])"
echo '```'
[ -f "$W/coverage-report.md" ] && sed -n '1,80p' "$W/coverage-report.md"
echo; echo '```'; ls -la "$W" | head -24
[ -f "$OUT_PDF" ] && du -h "$OUT_PDF"
[ -d "$W/attachments" ] && du -sh "$W/attachments"
echo '```'
} >> "$W/report.md"

python3 - <<'PY' >> "$W/report.md" 2>&1 || true
import os, subprocess
w, pdf = os.environ["W"], os.environ["OUT_PDF"]
if os.path.exists(pdf):
    st = os.path.join(w, "structure.json")
    subprocess.run(["python3", "scripts/make_excerpt.py", pdf, "--structure", st,
                    "--out", os.path.join(w, "excerpt.pdf"), "--pages", "16"],
                   check=False, capture_output=True)
    print(f"excerpt: {os.path.getsize(os.path.join(w,'excerpt.pdf')) if os.path.exists(os.path.join(w,'excerpt.pdf')) else 'none'} bytes")
for cmd in (["tar", "czf", "samples.tgz", "samples"], ["zip", "-qr", "attachments.zip", "attachments"]):
    tgt = cmd[2]
    src = cmd[-1]
    if os.path.isdir(os.path.join(w, src)) or os.path.isdir(src):
        subprocess.run(cmd, cwd=w, check=False, capture_output=True)
        if os.path.exists(os.path.join(w, tgt)):
            print(f"{tgt}: {os.path.getsize(os.path.join(w,tgt))//1024} KB")
PY

sz=0; [ -f "$OUT_PDF" ] && sz=$(stat -c%s "$OUT_PDF")
note "pdf bytes: $sz"
for f in "$(basename "$OUT_PDF")" attachments.zip excerpt.pdf page-map.json; do
  p="$W/$f"
  if [ -e "$p" ] && [ "$(stat -c%s "$p" 2>/dev/null || echo 0)" -lt 44000000 ]; then
    cp "$p" "$REPO/build/$f" 2>/dev/null || true
    note "committed to $BRANCH: $f ($(du -h "$p" | cut -f1))"
  else
    [ -e "$p" ] && note "not committed (too big for git): $f ($(du -h "$p" | cut -f1))"
  fi
done
push_state "final"

if [ "${PUBLISH_RELEASE:-0}" = "1" ] && [ -f "$OUT_PDF" ]; then
  tag="docs-$(echo "$PRODUCT" | tr 'A-Z ' 'a-z-')-$VERSION-$(date -u +%Y%m%d-%H%M)"
  mapfile -t ASSETS < <(for f in "$OUT_PDF" "$W/attachments.zip" "$W/coverage.json" \
                              "$W/page-map.json" "$W/inventory.json" "$W/excerpt.pdf"; do
                          [ -e "$f" ] && echo "$f"; done)
  { echo "Complete offline PDF of \`$SPACE_PATH\`, built by the CI workflow."
    echo; echo "Every internal documentation link is an in-document jump - no click leaves the PDF."
    echo "Bookmarks mirror the portal menu; the cover TOC carries real page numbers."
    echo; echo '```'; [ -f "$W/coverage-report.md" ] && sed -n '1,70p' "$W/coverage-report.md"; echo '```';
  } > "$W/notes.md"
  if gh release create "$tag" --title "$PRODUCT $VERSION - complete documentation (offline PDF)" \
       --notes-file "$W/notes.md" "${ASSETS[@]}" 2>&1 | tail -2; then
    note "release: $tag"
  else
    note "single-asset upload failed; splitting into parts"
    split -C 95m "$OUT_PDF" "$W/part-"
    gh release create "$tag" --title "$PRODUCT $VERSION - complete documentation (parts)" \
      --notes-file "$W/notes.md" "$W"/part-* "$W/attachments.zip" 2>&1 | tail -2 || true
    note "release (parts): $tag"
  fi
  push_state "released"
fi

exit "$(cat "$BUILD_RC_FILE" 2>/dev/null || echo 0)"
