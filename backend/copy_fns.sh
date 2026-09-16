#!/bin/bash
# Шаг 2 после регистрации: переносим 47 функций из старого агентства в новое.
set -u
cd /opt/fo
DB=$(grep -m1 '^DATABASE_URL=' .env | cut -d= -f2-)
NEW=nekrasivostore@gmail.com

SRC=$(psql "$DB" -At -c "select org_id from fn group by org_id order by count(*) desc limit 1")
DST=$(psql "$DB" -At -c "select org_id from app_user where email='$NEW' limit 1")

[ -n "${SRC:-}" ] || { echo "не нашёл агентство-источник с функциями"; exit 1; }
[ -n "${DST:-}" ] || { echo "не нашёл ваше новое агентство — сначала зарегистрируйтесь на $NEW"; exit 1; }
[ "$SRC" = "$DST" ] && { echo "источник и получатель совпадают — переносить нечего"; exit 0; }

HAVE=$(psql "$DB" -At -c "select count(*) from fn where org_id='$DST'")
[ "$HAVE" -gt 0 ] && { echo "в вашем агентстве уже $HAVE функций — ничего не трогаю"; exit 0; }

psql "$DB" -P pager=off -v ON_ERROR_STOP=1 -c \
  "insert into fn (org_id, code, name, minutes)
   select '$DST', code, name, minutes from fn where org_id='$SRC'"

echo
psql "$DB" -P pager=off -c \
  "select o.name as org, count(f.id) as funkcij from org o left join fn f on f.org_id=o.id group by o.name order by 2 desc"
echo "Готово. Обновите страницу сервиса."
