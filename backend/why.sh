#!/usr/bin/env bash
# Почему серверный шаг не применился. Ничего не меняет.
set -u
echo "=== 1. МЕТКА ШАГА ==="
echo "на сервере: $(cat /opt/fo/.backend-step.state 2>/dev/null || echo '(нет файла)')"
echo "на GitHub:  $(curl -fsSL --max-time 10 'https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend/live/_step.id' 2>/dev/null || echo '(не скачалось)')"
echo
echo "=== 2. ОТЧЁТ ПОСЛЕДНЕГО ШАГА ==="
tail -30 /opt/fo/web/fo-step.txt 2>/dev/null || echo "(отчёта нет)"
echo
echo "=== 3. ЛОГ ДОСТАВКИ (последние 25 строк) ==="
tail -25 /opt/fo/backend-pull.log 2>/dev/null || echo "(лога нет)"
echo
echo "=== 4. СЛУЖБА ТАЙМЕРА ==="
systemctl is-active fo-backend-pull.timer 2>/dev/null
systemctl status fo-backend-pull.service --no-pager -n 8 2>/dev/null | tail -10
echo
echo "=== 5. ЭНДПОИНТЫ ЛОКАЛЬНО ==="
for u in /health /refs/roles /refs/cards /refs/tasks/once /openapi.json; do
  printf '%-22s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000$u)"
done
echo
echo "=== 6. ФАЙЛЫ БЭКЕНДА ==="
ls -la /opt/fo/backend/app 2>/dev/null | head -20
echo
echo "=== 7. ОТДАЁТ ЛИ СЕРВЕР СТАТИКУ ИЗ web ==="
echo "локально /fo-diag.txt -> $(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/fo-diag.txt)"
grep -rn "StaticFiles\|/opt/fo/web" /opt/fo/backend/app/*.py 2>/dev/null | head -5
echo "=== КОНЕЦ ==="
