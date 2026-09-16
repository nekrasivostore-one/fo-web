#!/bin/bash
set -u
cd /opt/fo
RAW=https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend
curl -fsSL "$RAW/admin_service.py?t=$(date +%s)" -o /tmp/admin_service.py || { echo "не скачался"; exit 1; }
grep -q "service/orgs" /tmp/admin_service.py || { echo "приехал битым"; exit 1; }
python3 /tmp/admin_service.py || exit 1
/opt/fo/venv/bin/python -m py_compile backend/app/routers/admin.py \
  && echo "  admin.py компилируется" || {
      b=$(ls -t backend/app/routers/admin.py.bak-* 2>/dev/null | head -1)
      [ -n "$b" ] && cp "$b" backend/app/routers/admin.py
      echo "  СИНТАКСИС СЛОМАН — откатил"; exit 1; }
systemctl restart fo
sleep 5
printf 'health: '; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
printf 'без токена должно быть 401: '; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/admin/service/orgs
