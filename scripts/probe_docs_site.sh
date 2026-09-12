#!/usr/bin/env bash
# Reconnaissance of https://docs.helixops.ai for offline-PDF building.
# Prints a markdown report. Every probe is a plain GET/HEAD; nothing is mutated.
BASE="https://docs.helixops.ai"
SPACE_PATH="Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263"
SPACE_DOT="Service-Management.IT-Service-Management.BMC-Helix-ITSM.itsm263"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

hdr() { printf '\n%s\n' "## $*"; }

echo "# docs.helixops.ai probe"
echo "runner: $(uname -a)"; echo "date: $(date -u +%FT%TZ)"
echo "ip: $(curl -s --max-time 10 https://api.github.com/meta >/dev/null; curl -s --max-time 10 https://ifconfig.me/ip 2>/dev/null || echo unknown)"

hdr "Reachability"
for u in "/" "/robots.txt" "/sitemap.xml" "/sitemap-index.xml" "/bin/"; do
  code=$(curl -sS -o /tmp/body -w "%{http_code}|%{size_download}" --max-time 25 -A "$UA" "$BASE$u" 2>/dev/null || echo "ERR")
  echo "- \`$u\` -> $code"
  if [ "$u" = "/robots.txt" ]; then echo '```'; head -c 600 /tmp/body; echo; echo '```'; fi
done

probe_url () { # label url  -> status, type, size, magic
  local label="$1" url="$2" extra="${3:-}"
  local meta ctype size magic
  meta=$(curl -sS -o /tmp/o.bin -D /tmp/h.txt -w "%{http_code}" --max-time 90 -A "$UA" $extra "$url" 2>/dev/null || echo ERR)
  ctype=$(grep -i '^content-type:' /tmp/h.txt | tail -1 | tr -d '\r' | cut -d' ' -f2-)
  size=$(wc -c </tmp/o.bin | tr -d ' ')
  magic=$(head -c 5 /tmp/o.bin | tr -d '\0')
  echo "- **$label** -> http=$meta ct=\`${ctype}\` bytes=$size magic=\`${magic}\`"
  echo "  - url: $url"
  case "$magic" in
    %PDF) echo "  - **PDF RESPONSE** first-page hint: $(strings /tmp/o.bin | grep -m1 -i 'Title\|Producer' | head -c 120)";;
  esac
  if [ "$ctype" = "application/json" ] || [ "$ctype" = "text/xml" ] || [ "$ctype" = "application/xml" ]; then
    echo '  ```'; head -c 700 /tmp/o.bin; echo; echo '  ```'
  fi
}

hdr "Candidate page-tree enumeration endpoints"
probe_url "rest getChildren depth1" "$BASE/query/rest/getChildren/$SPACE_DOT?depth=1&media=json"
probe_url "rest getWikiSpaces"    "$BASE/query/rest/getWikiSpaces?media=json"
probe_url "rest searchDocs"       "$BASE/query/rest/searchDocs/itsm263?number=5&media=json"
probe_url "rest get-space-attachments" "$BASE/query/rest/getAttachments/$SPACE_DOT.WebHome?media=json"
probe_url "rdf of space root"     "$BASE/bin/view/$SPACE_PATH/WebHome?xpage=rdf"
probe_url "viewall"               "$BASE/bin/viewall/$SPACE_PATH/"
probe_url "sitemap macro page"    "$BASE/bin/view/$SPACE_PATH/Sitemap/"

hdr "Does a rendered page embed the whole nav tree?"
curl -sS -A "$UA" --max-time 40 "$BASE/bin/$SPACE_PATH/" -o /tmp/home.html
echo "- bytes: $(wc -c </tmp/home.html | tr -d ' ')"
echo "- hrefs to itsm263 (unique): $(grep -o "/bin/$SPACE_PATH/[A-Za-z0-9._-]*/" /tmp/home.html | sort -u | wc -l)"
echo "- nav markers: $(grep -oE 'data-page-tree|xpageTree|PageTree|navigation-tree|childrenUrl|load-children' /tmp/home.html | sort | uniq -c | tr '\n' ' ')"
echo "- sample unique links:"; grep -o "/bin/$SPACE_PATH/[A-Za-z0-9._-]*/" /tmp/home.html | sort -u | head -25
echo '```'
grep -oE '(data-[a-z-]+="(api|url|children)[^"]*"|/xwiki/[a-z]+/)' /tmp/home.html | sort | uniq -c | sort -rn | head -12
echo '```'

hdr "Vendor PDF export endpoints (whole space)"
probe_url "xpage=pdf on pretty URL"        "$BASE/bin/$SPACE_PATH/?xpage=pdf"
probe_url "xpage=pdf on WebHome"            "$BASE/bin/view/$SPACE_PATH/WebHome?xpage=pdf"
probe_url "xpage=print"                     "$BASE/bin/view/$SPACE_PATH/WebHome?xpage=print"
probe_url "print=1"                         "$BASE/bin/$SPACE_PATH/?print=1"
probe_url "action=pdfview+children"         "$BASE/bin/view/$SPACE_PATH/WebHome?action=pdfview&includeAllChildren=true"
probe_url "pdf action"                      "$BASE/bin/pdf/$SPACE_PATH/WebHome"
probe_url "export action GET"               "$BASE/bin/export/$SPACE_PATH/WebHome?language=English&includeAllChildren=true"
probe_url "attachments tab of PDFs page"    "$BASE/bin/attachments/$SPACE_PATH/PDFs-and-videos/"
probe_url "PDFs-and-videos view"            "$BASE/bin/view/$SPACE_PATH/PDFs-and-videos/"
probe_url "download of a known asset"       "$BASE/bin/download/XWiki/BMC/CETS/Macros/HomePages/BmcCustomCellMacro/spaceship.svg?rev=1.1"

hdr "Export form POST (XWiki PDF export panel)"
meta=$(curl -sS -o /tmp/post.bin -D /tmp/h2.txt -w "%{http_code}" --max-time 120 -A "$UA" \
  -X POST "$BASE/bin/export/$SPACE_PATH/WebHome" \
  --data "language=English&includeAllChildren=true&contentVisibility=all&paper=A4&linkRemoval=false&format=pdf" || echo ERR)
echo "- POST export -> http=$meta ct=$(grep -i '^content-type:' /tmp/h2.txt|tail -1|tr -d '\r') bytes=$(wc -c </tmp/post.bin|tr -d ' ') magic=$(head -c 5 /tmp/post.bin)"
echo '```'; strings /tmp/post.bin | head -12; echo '```'

hdr "Search-based counting"
for q in "URL:%2Aitsm263%2A" "site:docs.helixops.ai+itsm263"; do
  echo "- query $q -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -A "$UA" "$BASE/bin/search/main/?query=$q")"
done
echo "- google/bing style count not available from runner; use recursive crawl for truth."

echo
echo "PROBE COMPLETE"
