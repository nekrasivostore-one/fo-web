#!/usr/bin/env bash
set -u
B="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend"
T=$(date +%s)
curl -fsSL "$B/ip_log.py?t=$T" -o /tmp/ip_log.py || { echo "не скачался"; exit 1; }
grep -q "адрес, с которого зашли" /tmp/ip_log.py || { echo "не тот файл"; exit 1; }
echo "— строка импорта до правки —"
grep -n "^from fastapi import" /opt/fo/backend/app/deps.py
echo "— кто вызывает current() вручную —"
grep -rn "current(" /opt/fo/backend/app --include=*.py | grep -v "Depends(current)" | grep -v "def current" | head
echo "— поехали —"
cd /tmp && /opt/fo/venv/bin/python /tmp/ip_log.py || exit 1
if ! /opt/fo/venv/bin/python -m py_compile /opt/fo/backend/app/deps.py; then
  LAST=$(ls -t /opt/fo/backend/app/deps.py.bak-* | head -1)
  echo "синтаксис сломался — откат на $LAST"; cp "$LAST" /opt/fo/backend/app/deps.py; exit 2
fi
systemctl restart fo && sleep 3
H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)
echo "health: $H"
if [ "$H" != "200" ]; then
  LAST=$(ls -t /opt/fo/backend/app/deps.py.bak-* | head -1)
  echo "сервис не поднялся — откат на $LAST"; cp "$LAST" /opt/fo/backend/app/deps.py
  systemctl restart fo; sleep 3; echo "после отката: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
  journalctl -u fo -n 20 --no-pager | tail -20
  exit 3
fi
echo "без токена 401: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/refs/org)"
echo "— как стало —"
grep -n "^from fastapi import" /opt/fo/backend/app/deps.py
grep -n "async def current" /opt/fo/backend/app/deps.py
