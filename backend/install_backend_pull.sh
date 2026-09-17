#!/usr/bin/env bash
# Одна команда: переустановить механизм доставки бэкенда, прогнать шаг
# и напечатать отчёт. Больше в консоль ходить не нужно.
set -u
B="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend"
T=$(date +%s)

echo "— скачиваю механизм —"
curl -fsSL "$B/fo-backend-pull.sh?t=$T"      -o /opt/fo/fo-backend-pull.sh || { echo "не скачался"; exit 1; }
grep -q "Бэкенд едет из GitHub" /opt/fo/fo-backend-pull.sh || { echo "не тот файл"; exit 1; }
chmod +x /opt/fo/fo-backend-pull.sh
curl -fsSL "$B/fo-backend-pull.service?t=$T" -o /etc/systemd/system/fo-backend-pull.service || exit 1
curl -fsSL "$B/fo-backend-pull.timer?t=$T"   -o /etc/systemd/system/fo-backend-pull.timer   || exit 1
systemctl daemon-reload
systemctl enable --now fo-backend-pull.timer

echo "— таймер —"
systemctl is-active fo-backend-pull.timer
systemctl list-timers fo-backend-pull.timer --no-pager | head -3

echo "— прогон (шаг, если он новый) —"
mkdir -p /opt/fo/web
rm -f /opt/fo/.backend-step.state       # прогоняем шаг заново, он идемпотентный
/opt/fo/fo-backend-pull.sh
sleep 2

echo "— health —"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health

echo "— проверка эндпоинтов —"
for u in /refs/roles /refs/invites /auth/invite-token/zzz; do
  printf '%-28s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000$u)"
done
echo "(401/403 и 404 на invite-token — это нормально: эндпоинт есть. 404 на /refs/roles — шага нет)"

echo
echo "════════ ОТЧЁТ ШАГА ════════"
cat /opt/fo/web/fo-step.txt 2>/dev/null || echo "(отчёта нет — шаг не запускался)"
echo "════════ КОНЕЦ ════════"
echo
echo "Отчёт также лежит по адресу: https://fo.flater.pro/fo-step.txt"
