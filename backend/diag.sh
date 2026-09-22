#!/usr/bin/env bash
# Разведка: где на сервере лежит бэкенд, фронт, venv, какие есть службы и таймеры.
# Ничего не меняет. Пишет отчёт рядом с index.html фронта, чтобы его было видно по http.
set -u
OUT=$(mktemp)
{
echo "=== FO DIAG $(date '+%F %T') ==="
echo
echo "-- службы (fo/uvicorn/gunicorn) --"
systemctl list-units --type=service --all --no-legend --no-pager 2>/dev/null \
  | awk '{print $1}' | grep -iE 'fo|uvicorn|gunicorn' | head -10
echo
echo "-- параметры этих служб --"
for u in $(systemctl list-units --type=service --all --no-legend --no-pager 2>/dev/null \
  | awk '{print $1}' | grep -iE 'fo|uvicorn|gunicorn' | head -6); do
  echo "[$u]"
  echo "  ExecStart: $(systemctl show -p ExecStart --value "$u" 2>/dev/null | head -c 400)"
  echo "  WorkDir:   $(systemctl show -p WorkingDirectory --value "$u" 2>/dev/null)"
  echo "  Active:    $(systemctl is-active "$u" 2>/dev/null)"
done
echo
echo "-- каталоги-кандидаты --"
for d in /opt/fo /opt/fo/backend /opt/fo/web /srv/fo /root/fo /var/www/fo /home/fo; do
  [ -e "$d" ] && echo "есть: $d" || echo "нет:  $d"
done
echo
echo "-- venv с python --"
find /opt /srv /root /home -maxdepth 4 -type f -path '*/bin/python3' 2>/dev/null | head -5
echo
echo "-- index.html (фронт) --"
find /opt /srv /var/www /root /home -maxdepth 5 -name index.html 2>/dev/null | head -5
echo
echo "-- nginx: root и proxy_pass --"
grep -rhE '^[[:space:]]*(root|proxy_pass)[[:space:]]' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ /etc/nginx/nginx.conf 2>/dev/null | head -10
echo
echo "-- таймеры --"
systemctl list-timers --all --no-pager 2>/dev/null | head -12
echo
echo "-- файлы механизма доставки --"
ls -la /opt/fo/*.sh /etc/systemd/system/fo-*.timer /etc/systemd/system/fo-*.service 2>/dev/null
echo
echo "-- health --"
echo "127.0.0.1:8000/health -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/health)"
echo
echo "-- место на диске --"
df -h / | tail -1
echo "=== КОНЕЦ ==="
} > "$OUT" 2>&1

cat "$OUT"

# положить отчёт рядом с index.html, чтобы он открывался по http
W=$(find /opt /srv /var/www /root /home -maxdepth 5 -name index.html 2>/dev/null | head -1)
if [ -n "$W" ]; then
  cp "$OUT" "$(dirname "$W")/fo-diag.txt" 2>/dev/null && \
    echo && echo ">>> отчёт также лежит здесь: $(dirname "$W")/fo-diag.txt"
fi
rm -f "$OUT"
