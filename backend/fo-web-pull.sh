#!/bin/bash
# FO: сам забирает свежий index.html из GitHub. Ставится один раз, дальше работает молча.
set -uo pipefail

REPO="nekrasivostore-one/fo-web"
DEST="/opt/fo/web/index.html"
MARK="/opt/fo/web/.index.sha"

SHA=$(curl -fsSL -m 20 -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/commits?path=index.html&per_page=1" \
  | python3 -c "import sys,json
try:
    print(json.load(sys.stdin)[0]['sha'])
except Exception:
    pass" 2>/dev/null)

[ -n "${SHA:-}" ] || { echo "не смог узнать коммит"; exit 0; }

CUR=$(cat "$MARK" 2>/dev/null || echo "")
[ "$SHA" = "$CUR" ] && exit 0

TMP=$(mktemp /tmp/fo-index.XXXXXX)
trap 'rm -f "$TMP"' EXIT

curl -fsSL -m 60 "https://raw.githubusercontent.com/$REPO/$SHA/index.html" -o "$TMP" || {
  echo "не скачался"; exit 0; }

# защита от битого файла: он должен быть похож на нашу сборку
SIZE=$(wc -c < "$TMP")
if [ "$SIZE" -lt 100000 ] || ! grep -q "Flater Team Service" "$TMP"; then
  echo "файл не похож на сборку ФО, оставляю старый"; exit 0
fi

cp -f "$DEST" "${DEST}.bak" 2>/dev/null || true
install -m 0644 "$TMP" "$DEST"
echo "$SHA" > "$MARK"
echo "обновлено до ${SHA:0:10}, $SIZE байт"
