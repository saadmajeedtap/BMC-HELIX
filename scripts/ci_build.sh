#!/usr/bin/env bash
# CI driver for the offline PDF build. Runs the same scripts a local user runs,
# then publishes a machine-checkable report plus small artifacts onto a branch.
set -uo pipefail
W="${WORKDIR:-/tmp/helix-build}"
mkdir -p "$W"
BRANCH="docs-build"
OUT_PDF="$W/$(echo "${PRODUCT:-BMC-Helix-ITSM}" | tr ' ' '-')-${VERSION:-26.3}-complete.pdf"
LOG="$W/build.log"
REPORT="$W/report.md"
BUILD_RC_FILE="$W/build-rc"

phases() { printf '%s\n' "$*"; }

{
echo "# build log"
echo "date: $(date -u +%FT%TZ)  runner: $(uname -m)"

echo "## system deps"
sudo apt-get update -qq >/dev/null 2>&1 || true
sudo apt-get install -y -qq libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 libjpeg62-turbo libopenjp2-7 fonts-dejavu-core \
  fonts-liberation fonts-dejavu-extra >/dev/null 2>&1 || true
fc-list | wc -l

echo "## python deps"
python3 -m pip install -q --upgrade pip >/dev/null
python3 -m pip install -q -r requirements.txt
python3 -c "import weasyprint,sys;pypdf=None
import pypdf, reportlab, bs4, PIL
print('weasyprint',weasyprint.__version__,'| pypdf',pypdf.__version__,
      '| reportlab',reportlab.Version,'| python',sys.version.split()[0])"

echo "## selftest (offline logic check)"
python3 scripts/selftest.py --work /tmp/helix-selftest --with-render 2>&1 | tail -18

echo "## portal diagnostics (raw document-tree fragment)"
python3 - <<'PY' || true
import os,re,requests
base="https://docs.helixops.ai"; sp=os.environ.get("SPACE_PATH","")
sd=sp.replace("/",".")
url=(f"{base}/bin/get/{sp}/WebHome?outputSyntax=plain&sheet=XWiki.ExportDocumentTree"
     f"&filterHiddenDocuments=false&showTranslations=false&limit=50&root=document%3A{sd}.WebHome")
r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=60)
print(f"- fragment http={r.status_code} bytes={len(r.text)}")
print("```")
print(re.sub(r'\s+',' ', r.text)[:1400])
print("```")
PY

echo "## integration test (mock portal, end-to-end)"
python3 scripts/integration_test.py --full 2>&1 | tail -10 || { echo "INTEGRATION FAILED"; echo 3 > "$BUILD_RC_FILE"; }

echo "## live smoke test (real portal page -> cleaner, no writes)"
python3 scripts/build_docs_pdf.py --smoke-page \
  "https://docs.helixops.ai/bin/${SPACE_PATH}/Release-notes-and-notices/" 2>&1 | tail -22 || true

echo "## build"
python3 scripts/build_docs_pdf.py \
  --space-path "${SPACE_PATH}" --product "${PRODUCT}" --version "${VERSION}" \
  --workspace "$W" --out "$OUT_PDF" --phases "${PHASES:-inventory,fetch,render,assemble,verify}" \
  --engine "${ENGINE:-weasyprint}" --workers "${WORKERS:-3}" \
  --http-workers "${HTTP_WORKERS:-8}" --delay "${DELAY:-0.08}" \
  ${ONLY_SECTIONS:+--only-sections "$ONLY_SECTIONS"} \
  ${MAX_DOCS:+--max-docs "$MAX_DOCS"} \
  ${NO_ATTACH:+--no-attachments} ${NO_STAMP:+--no-stamp} \
  --report "$W/coverage-report.md" 2>&1 | tee "$LOG" | tail -80
BUILD_RC=${PIPESTATUS[0]}
echo "build exit code: $BUILD_RC"
echo "$BUILD_RC" > "$BUILD_RC_FILE"
} 2>&1 | tee "$REPORT"

echo
echo "## results" >> "$REPORT"
{
  echo '```'
  [ -f "$W/summary.json" ] && python3 -c "import json;d=json.load(open('$W/summary.json'));print(json.dumps(d,indent=1)[:3000])"
  echo '```'
  echo
  if [ -f "$W/coverage-report.md" ]; then sed -n '1,80p' "$W/coverage-report.md"; fi
  echo
  echo '```'
  ls -la "$W" | head -20; [ -f "$OUT_PDF" ] && du -h "$OUT_PDF"
  echo '```'
} >> "$REPORT"

# small artifacts for human/agent review
python3 - <<PY || true
import json,os
w="$W"; pdf="$OUT_PDF"
if os.path.exists(pdf):
    st=os.path.join(w,"structure.json")
    os.system(f"python3 scripts/make_excerpt.py '{pdf}' --structure '{st}' "
              f"--out '{w}/excerpt.pdf' --pages 16 || true")
    if os.path.exists(os.path.join(w,"samples")):
        os.system(f"cd '{w}' && tar czf samples.tgz samples || true")
PY

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git checkout -B "$BRANCH" >/dev/null 2>&1 || git checkout "$BRANCH"
mkdir -p build
cp "$REPORT" build/report.md
for f in summary.json coverage.md coverage.json inventory.json structure.json page-map.json render-index.json excerpt.pdf samples.tgz; do
  [ -e "$W/$f" ] && cp "$W/$f" "build/$f"
done
if [ -f "$OUT_PDF" ]; then
  sz=$(stat -c%s "$OUT_PDF")
  echo "pdf bytes: $sz" >> build/report.md
  if [ "$sz" -lt 44000000 ] && [ "${COMMIT_PDF:-1}" = "1" ]; then
    cp "$OUT_PDF" "build/$(basename "$OUT_PDF")"
    echo "- full PDF committed to branch $BRANCH" >> build/report.md
  else
    echo "- PDF too big for git ($(python3 -c "print(round($sz/1e6,1))") MB) -> published to a GitHub release instead" >> build/report.md
  fi
fi
git add -f build/ >/dev/null
git commit -qm "docs build: $PRODUCT $VERSION (${ONLY_SECTIONS:-all sections})" || true
git push -f origin "$BRANCH" || true

if [ "${PUBLISH_RELEASE:-0}" = "1" ] && [ -f "$OUT_PDF" ]; then
  tag="docs-$(echo "$PRODUCT" | tr 'A-Z ' 'a-z-')-$VERSION-$(date -u +%Y%m%d-%H%M)"
  gh release create "$tag" --title "$PRODUCT $VERSION - complete documentation (offline PDF)" \
    --notes-file "$W/coverage-report.md" "$OUT_PDF" || {
      echo "release upload failed; retrying with split parts"
      split -C 95m "$OUT_PDF" "$W/part-"
      gh release create "$tag" --title "$PRODUCT $VERSION - complete documentation (parts)" \
        --notes-file "$W/coverage-report.md" "$W"/part-* "$W/coverage.json" || true
    }
fi

tail -c 20000 "$REPORT"
exit "$(cat "$BUILD_RC_FILE" 2>/dev/null || echo 0)" 
