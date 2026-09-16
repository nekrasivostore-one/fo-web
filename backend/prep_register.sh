#!/bin/bash
# Шаг 1 перед регистрацией: освобождаем почту владельца.
# Старый аккаунт не удаляем — он держит 47 функций и пятерых сотрудников.
# Просто переименовываем его почту, чтобы вы могли зарегистрироваться заново.
set -u
cd /opt/fo
DB=$(grep -m1 '^DATABASE_URL=' .env | cut -d= -f2-)
OLD=nekrasivostore@gmail.com
NEW=nekrasivostore+seed@gmail.com

echo "── до правки ──"
psql "$DB" -P pager=off -c \
  "select o.name as org, u.email, u.role_code from app_user u join org o on o.id=u.org_id order by o.created_at"

psql "$DB" -P pager=off -v ON_ERROR_STOP=1 -c \
  "update app_user set email='$NEW' where email='$OLD'"

echo
echo "── после правки ──"
psql "$DB" -P pager=off -c \
  "select o.name as org, u.email, u.role_code from app_user u join org o on o.id=u.org_id order by o.created_at"
echo
echo "Готово. Почта $OLD свободна."
echo "Идите на https://fo.flater.pro → «Зарегистрироваться» и заводите агентство на неё."
echo "Когда зарегистрируетесь — запустите второй скрипт, он перенесёт 47 функций:"
echo "  curl -fsSL https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend/copy_fns.sh | bash"
