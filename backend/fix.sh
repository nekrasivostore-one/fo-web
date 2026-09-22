#!/usr/bin/env bash
# Одноразовая починка: подменить устаревший /opt/fo/fo-backend-pull.sh
# на актуальный (тот, что умеет прогонять серверный шаг), прогнать его
# и показать результат. Дальше сервер обновляется сам.
set -u
B="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend"
T=$(date +%s)
SELF=/opt/fo/fo-backend-pull.sh

echo "=== 1. ЧТО СЕЙЧАС ==="
ls -la "$SELF" 2>/dev/null || echo "(файла нет)"

echo
echo "=== 2. ИЩУ PYTHON БЭКЕНДА ==="
PY=""
for c in /opt/fo/venv/bin/python /opt/fo/venv/bin/python3; do
  [ -x "$c" ] && PY="$c" && break
done
if [ -z "$PY" ]; then
  E=$(systemctl show -p ExecStart --value fo-backend.service 2>/dev/null)
  [ -z "$E" ] && E=$(systemctl show -p ExecStart --value fo.service 2>/dev/null)
  PY=$(printf '%s' "$E" | grep -oE '/[^ ]*/bin/python[0-9.]*' | head -1)
fi
[ -z "$PY" ] && PY=$(find /opt -maxdepth 5 -type f -name 'python3' -path '*/bin/*' 2>/dev/null | head -1)
echo "python: ${PY:-НЕ НАЙДЕН}"
if [ -z "$PY" ]; then echo "без python шаг не выполнить, останавливаюсь"; exit 1; fi

echo
echo "=== 3. СКАЧИВАЮ АКТУАЛЬНУЮ ВЕРСИЮ ==="
TMP=$(mktemp)
curl -fsSL "$B/fo-backend-pull.sh?t=$T" -o "$TMP" || { echo "не скачалось"; exit 1; }
grep -q "Бэкенд едет из GitHub" "$TMP" || { echo "скачался не тот файл"; exit 1; }
echo "скачано байт: $(wc -c < "$TMP")"

# если python лежит не там, где ждёт скрипт — поправить строку PY=
if [ "$PY" != "/opt/fo/venv/bin/python" ]; then
  sed -i "s#^PY=.*#PY=\"$PY\"#" "$TMP"
  echo "путь к python подставлен: $PY"
fi

cp "$SELF" "/opt/fo/fo-backend-pull.sh.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null
cp "$TMP" "$SELF"; chmod +x "$SELF"; rm -f "$TMP"
echo "заменено, теперь байт: $(wc -c < "$SELF")"

echo
echo "=== 4. ПРОГОН ==="
rm -f /opt/fo/.backend-step.state      # шаг идемпотентный, прогоняем заново
"$SELF"
sleep 3

echo
echo "=== 5. ОТЧЁТ ШАГА ==="
tail -40 /opt/fo/web/fo-step.txt 2>/dev/null || echo "(отчёта нет)"

echo
echo "=== 6. ЭНДПОИНТЫ ==="
for u in /health /refs/roles /refs/cards /refs/tasks/once /refs/invites /refs/me/account; do
  printf '%-22s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000$u)"
done
echo "(401/403 - эндпоинт есть, просто нужен вход. 404 - шага нет)"

echo
echo "=== 7. ПОСЛЕДНИЕ СТРОКИ ЛОГА ==="
tail -12 /opt/fo/backend-pull.log 2>/dev/null
echo "=== КОНЕЦ ==="
