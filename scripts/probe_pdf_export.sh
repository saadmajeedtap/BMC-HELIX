#!/usr/bin/env bash
# Validate: can BMC's own PDF export produce the whole space? And how do we
# enumerate the page tree + count pages for a completeness guarantee.
BASE="https://docs.helixops.ai"
S="Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
W=/tmp/w; mkdir -p $W
h() { printf '\n%s\n' "## $*"; }

pdf_stats () { # label file
  python3 scripts/pdfstat.py "$1" "$2" 2>&1 | sed 's/^/- /'
}

get () { # outfile url [method] [data]
  local out=$1 url=$2 m=${3:-GET} d=${4:-}
  if [ "$m" = POST ]; then
    curl -sS -A "$UA" --max-time 300 -o "$out" -w "%{http_code} %{content_type} %{size_download}\n" -X POST --data "$d" "$url"
  else
    curl -sS -A "$UA" --max-time 300 -o "$out" -w "%{http_code} %{content_type} %{size_download}\n" "$url"
  fi
}

h "1. PDF action: parameter sensitivity (section = Navigating common interfaces)"
SEC="Navigating-common-interfaces"
for q in "" "?includeAllChildren=true" "?includeAllChildren=true&contentVisibility=all" "?includeAllChildren=true&contentVisibility=all&includeAttachments=true" "?includeAllChildren=true&includeAttachments=true&paper=A4&linkRemoval=false" "?xpage=pdf&includeAllChildren=true"; do
  printf '%-70s ' "[$q]"
  get "$W/a.pdf" "$BASE/bin/pdf/$S/$SEC/WebHome$q" > "$W/meta.txt" 2>&1
  echo -n "$(cat $W/meta.txt) "; pdf_stats "$SEC$q" "$W/a.pdf" 2>/dev/null | sed 's/^- /  /'
done

h "2. Whole-space PDF export from space root"
printf 'root '; get "$W/root.pdf" "$BASE/bin/pdf/$S/WebHome?includeAllChildren=true&contentVisibility=all&includeAttachments=true" 2>&1
pdf_stats "SPACE-ROOT-all-children" "$W/root.pdf"

h "3. All top-level sections: per-section export (this is the full-doc coverage test)"
for SEC in Release-notes-and-notices Getting-started Agentic-AI-capabilities-in-BMC-Helix-ITSM Planning Setting-up-and-going-live Integrating Navigating-common-interfaces Using-reports-and-flashboards Administering Developing Troubleshooting FAQ Related-documentation Legal-notices; do
  meta=$(get "$W/$SEC.pdf" "$BASE/bin/pdf/$S/$SEC/WebHome?includeAllChildren=true&contentVisibility=all&includeAttachments=true" 2>&1)
  st=$(python3 scripts/pdfstat.py "$SEC" "$W/$SEC.pdf" 2>&1 | tail -1)
  echo "- $SEC :: http/ct/bytes=$meta :: $st"
  sleep 1
done
echo "TOTAL bytes: $(du -sh $W | cut -f1)"
echo "sum of pages: $(python3 - <<'PY'
import glob,sys
sys.path.insert(0,'scripts')
from pdfstat import stats
tot=0
for f in sorted(glob.glob('/tmp/w/*.pdf')):
    s=stats(f)
    if 'pages' in s: tot+=s['pages']
print(tot)
PY
)"

h "4. Enumeration API discovery"
for u in "bin/view/$S/WebHome?xpage=rdf" "bin/view/$S/Getting-started/?xpage=rdf" "bin/view/$S/Getting-started/WebHome?xpage=rdf"; do
  echo "### $u"; get "$W/e.txt" "$BASE/$u" 2>&1
  python3 - <<'PY'
import re
d=open('/tmp/w/e.txt',encoding='utf8',errors='replace').read()
print(f"  bytes={len(d)}")
print("  rdf props:", sorted(set(re.findall(r'<wiki:(\w+)', d)))[:20])
print("  contains/child refs:", re.findall(r'<wiki:(?:contains|child|parent)>\s*<wiki:(?:Space|Page)[^>]*rdf:about="([^"]+)"', d)[:8])
print("  href count:", len(re.findall(r'href=', d)))
print("  head:", d[:260].replace('\n',' '))
PY
done

h "5. PageTree / nav AJAX endpoint used by the theme"
get "$W/page.html" "$BASE/bin/$S/Getting-started/" 2>&1
python3 - <<'PY'
import re
d=open('/tmp/w/page.html',encoding='utf8',errors='replace').read()
print("  script srcs:", sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', d)))[:14])
print("  ajax-ish urls in html:", sorted(set(re.findall(r'["\'](/[^"\']*(?:tree|children|navigation|nav|expand|ajax)[^"\']*)["\']', d, re.I)))[:20])
print("  data-* attrs:", sorted(set(re.findall(r'\bdata-([a-z-]+)=', d)))[:40])
print("  child links in this page:", len(set(re.findall(r'/bin/Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263/[A-Za-z0-9._-]+/', d))))
print("  inline json cfg:", (re.findall(r'(?:documenttree|treeData|navData|JSON.parse)\([^)]{0,120}', d) or ['none'])[:4])
PY

h "6. Export-panel form fields (what the browser UI posts)"
get "$W/exp.html" "$BASE/bin/export/$S/WebHome?format=pdf&language=English" 2>&1
python3 - <<'PY'
import re
d=open('/tmp/w/exp.html',encoding='utf8',errors='replace').read()
for m in re.finditer(r'<(form|input|select|textarea|option)\b([^>]*)>', d, re.I):
    tag=m.group(1).lower(); a=m.group(2)
    nm=re.search(r'name="([^"]+)"',a); ty=re.search(r'type="([^"]+)"',a); vl=re.search(r'value="([^"]+)"',a)
    ac=re.search(r'action="([^"]+)"',a)
    if tag=='form': print("  FORM:", ac.group(1) if ac else '?', re.search(r'method="([^"]+)"',a).group(1) if re.search(r'method="([^"]+)"',a) else '')
    elif nm: print(f"  {tag}: name={nm.group(1)} type={ty.group(1) if ty else ''} value={vl.group(1) if vl else ''}")
PY

h "7. Do the ready-made PDFs leak through attachments (login-gated page)?"
for u in "bin/view/$S/PDFs-and-videos/" "bin/viewattachments/$S/PDFs-and-videos/"; do
  echo "### $u"; get "$W/pv.html" "$BASE/$u" 2>&1
  grep -oE 'href="[^"]*[^" ]*\.pdf[^"]*"' $W/pv.html | sort -u | head -20
  grep -oiE '(attachment|download)[^<]{0,80}\.pdf' $W/pv.html | head -10
  grep -oiE 'you must[^<]{0,60}log in[^<]{0,60}' $W/pv.html | head -2
done

h "8. Link style inside an exported PDF (internal vs external)"
python3 - <<'PY'
import re
try:
    from pypdf import PdfReader
    r=PdfReader('/tmp/w/Getting-started.pdf')
    uris=[]
    for pg in r.pages[:25]:
        for a in (pg.get('/Annots') or []):
            o=a.get_object()
            u=o.get('/A',{}).get_object().get('/URI') if '/A' in o else None
            if u: uris.append(str(u))
    print(f"  total uri annots in first 25 pages: {len(uris)}")
    print("  sample:", uris[:6])
    print(f"  pointing at docs.helixops.ai: {sum(1 for u in uris if 'helixops' in u)}")
    dests=[str(p.get('/Contents')) for p in r.pages[:1]]
    print("  named dests present:", bool(re.findall(rb'/Dests|/Names\s*<</D', open('/tmp/w/Getting-started.pdf','rb').read())))
except Exception as e: print("  skip:",e)
PY
echo; echo "PROBE2 COMPLETE"
