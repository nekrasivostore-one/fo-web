#!/usr/bin/env bash
set -u
B="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend"
T=$(date +%s)
cd /tmp
curl -fsSL "$B/me_org.py?t=$T" -o /tmp/me_org.py || { echo "не скачался"; exit 1; }
grep -q "Карточка своего агентства" /tmp/me_org.py || { echo "скачался не тот файл"; exit 1; }
echo "— что сейчас в refs.py —"
head -12 /opt/fo/backend/app/routers/refs.py
echo "…"
/opt/fo/venv/bin/python /tmp/me_org.py || exit 1
if ! /opt/fo/venv/bin/python -m py_compile /opt/fo/backend/app/routers/refs.py; then
  LAST=$(ls -t /opt/fo/backend/app/routers/refs.py.bak-* 2>/dev/null | head -1)
  echo "синтаксис сломался — откатываю на $LAST"
  cp "$LAST" /opt/fo/backend/app/routers/refs.py
  exit 2
fi
systemctl restart fo && sleep 3
echo "health: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo "без токена должно быть 401: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/refs/org)"
echo
echo "— deps.py: как устроен current —"
grep -n "def current\|Request\|last_ip\|client.host" /opt/fo/backend/app/deps.py | head -20
