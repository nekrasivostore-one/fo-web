#!/usr/bin/env bash
# Бэкенд едет из GitHub так же, как фронт: раз в две минуты сервер
# сам смотрит манифест и, если что-то изменилось, забирает файлы,
# проверяет синтаксис, перезапускает сервис и сверяет health.
# Не поднялось — откат из резервной копии. Консоль для этого не нужна.
set -u
RAW="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend/live"
APP="/opt/fo/backend/app"
PY="/opt/fo/venv/bin/python"
STATE="/opt/fo/.backend-pull.state"
LOG="/opt/fo/backend-pull.log"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say(){ echo "$(date '+%F %T') $*" >> "$LOG"; }

# сначала — не появилась ли новая версия самого этого скрипта
SELF="/opt/fo/fo-backend-pull.sh"
if curl -fsSL "${RAW%/live}/fo-backend-pull.sh?t=$(date +%s)" -o "$TMP/self.sh" 2>/dev/null; then
  if grep -q "Бэкенд едет из GitHub" "$TMP/self.sh" && ! cmp -s "$TMP/self.sh" "$SELF"; then
    cp "$TMP/self.sh" "$SELF"; chmod +x "$SELF"
    say "обновил сам себя — следующий прогон пойдёт по новой версии"
    exit 0
  fi
fi

# ── разовый шаг: скрипт, который правит то, что целиком не перевезёшь ──
# Механизм односторонний: файлы едут на сервер, прочитать их отсюда нечем.
# Поэтому есть _step.py — он правит файлы НА сервере и пишет отчёт, который
# видно в панели админа. Запускается один раз на каждую новую метку _step.id.
STEPSTATE="/opt/fo/.backend-step.state"
REPORT="/opt/fo/web/fo-step.txt"
if curl -fsSL "$RAW/_step.id?t=$(date +%s)" -o "$TMP/step.id" 2>/dev/null; then
  SID=$(tr -d " \t\r\n" < "$TMP/step.id")
  CUR=$(cat "$STEPSTATE" 2>/dev/null || echo "")
  if [ -n "$SID" ] && [ "$SID" != "$CUR" ]; then
    if curl -fsSL "$RAW/_step.py?t=$(date +%s)" -o "$TMP/step.py" 2>/dev/null; then
      echo "$SID" > "$STEPSTATE"        # метку пишем ДО запуска: шаг не повторяется
      say "шаг $SID: запускаю"
      mkdir -p /opt/fo/web
      {
        echo "шаг $SID"
        echo "запуск $(date '+%F %T')"
        echo "---"
        "$PY" "$TMP/step.py" 2>&1
        echo "---"
        echo "код выхода: $?"
      } > "$REPORT" 2>&1
      cp "$REPORT" /opt/fo/step-last.txt 2>/dev/null
      sed -n '1,200p' "$REPORT" >> "$LOG"
      say "шаг $SID: завершён"
    else
      say "шаг $SID: сам скрипт не скачался"
    fi
  fi
fi

curl -fsSL "$RAW/manifest.txt?t=$(date +%s)" -o "$TMP/manifest.txt" 2>/dev/null || { say "манифест не скачался"; exit 0; }
# комментарии и пустые строки выкидываем, остальное должно быть путями
grep -vE '^[[:space:]]*(#|$)' "$TMP/manifest.txt" > "$TMP/list.txt" || true
if [ -s "$TMP/list.txt" ] && grep -qvE '^[A-Za-z0-9_./-]+$' "$TMP/list.txt"; then
  say "манифест выглядит не так"; exit 0
fi
if [ ! -s "$TMP/list.txt" ]; then exit 0; fi   # нечего везти

# качаем всё, что перечислено, и считаем общий отпечаток
FP=""
while read -r f; do
  [ -z "$f" ] && continue
  case "$f" in \#*) continue;; esac
  curl -fsSL "$RAW/$f?t=$(date +%s)" -o "$TMP/$(basename "$f")" 2>/dev/null || { say "не скачался $f"; exit 0; }
  FP="$FP$(sha256sum "$TMP/$(basename "$f")" | cut -c1-16)"
done < "$TMP/list.txt"
FP=$(printf '%s' "$FP" | sha256sum | cut -c1-32)

OLD=$(cat "$STATE" 2>/dev/null || echo "")
[ "$FP" = "$OLD" ] && exit 0          # ничего не менялось

say "новая версия бэкенда: $FP"
BAK="/opt/fo/backend-bak-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BAK"

# кладём файлы, сохраняя старые
while read -r f; do
  [ -z "$f" ] && continue
  case "$f" in \#*) continue;; esac
  b=$(basename "$f")
  [ -f "$APP/$f" ] && { mkdir -p "$BAK/$(dirname "$f")"; cp "$APP/$f" "$BAK/$f"; }
  mkdir -p "$APP/$(dirname "$f")"
  cp "$TMP/$b" "$APP/$f"
  say "  положен $f"
done < "$TMP/list.txt"

rollback(){
  say "  ОТКАТ из $BAK"
  (cd "$BAK" && find . -type f -exec cp --parents {} "$APP/" \;)
  systemctl restart fo; sleep 3
  say "  после отката health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
}

# синтаксис
while read -r f; do
  [ -z "$f" ] && continue
  case "$f" in \#*) continue;; esac
  case "$f" in *.py) "$PY" -m py_compile "$APP/$f" 2>>"$LOG" || { say "  синтаксис не сошёлся: $f"; rollback; exit 0; };; esac
done < "$TMP/list.txt"

systemctl restart fo; sleep 4
H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)
if [ "$H" != "200" ]; then say "  сервис не поднялся (health=$H)"; rollback; exit 0; fi

echo "$FP" > "$STATE"
say "  выкачено, health=200"
# держим только пять последних резервных копий
ls -dt /opt/fo/backend-bak-* 2>/dev/null | tail -n +6 | xargs -r rm -rf
