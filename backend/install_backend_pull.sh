#!/usr/bin/env bash
# Ставится один раз. Дальше бэкенд едет из GitHub сам.
set -u
B="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend"
T=$(date +%s)
curl -fsSL "$B/fo-backend-pull.sh?t=$T"      -o /opt/fo/fo-backend-pull.sh || exit 1
grep -q "Бэкенд едет из GitHub" /opt/fo/fo-backend-pull.sh || { echo "не тот файл"; exit 1; }
chmod +x /opt/fo/fo-backend-pull.sh
curl -fsSL "$B/fo-backend-pull.service?t=$T" -o /etc/systemd/system/fo-backend-pull.service || exit 1
curl -fsSL "$B/fo-backend-pull.timer?t=$T"   -o /etc/systemd/system/fo-backend-pull.timer   || exit 1
systemctl daemon-reload
systemctl enable --now fo-backend-pull.timer
echo "— таймер —"
systemctl is-active fo-backend-pull.timer
systemctl list-timers fo-backend-pull.timer --no-pager | head -3
echo "— первый прогон —"
/opt/fo/fo-backend-pull.sh
tail -12 /opt/fo/backend-pull.log 2>/dev/null || echo "(лог пока пуст — значит менять нечего)"
echo "— health —"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
