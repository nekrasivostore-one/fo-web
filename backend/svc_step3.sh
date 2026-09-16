#!/usr/bin/env bash
# Триал до 25.09 живому агентству Виталия + проверка, что фикс регистрации на месте.
set -u
DB=fo
echo "— агентства Виталия —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "SELECT o.id, o.name, o.created_at, o.trial_ends_at,
         (SELECT count(*) FROM app_user u WHERE u.org_id=o.id) AS users
  FROM org o
  WHERE EXISTS (SELECT 1 FROM app_user u WHERE u.org_id=o.id
                AND u.email='nekrasivostore@gmail.com')
  ORDER BY o.created_at;"
echo
echo "— ставим пробный период до 25.09.2026 всем агентствам Виталия —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "UPDATE org SET trial_ends_at='2026-09-25',
                 trial_extra_days=trial_extra_days+GREATEST(0,(DATE '2026-09-25'-CURRENT_DATE)),
                 trial_note='поставлено вручную до 25.09'
  WHERE EXISTS (SELECT 1 FROM app_user u WHERE u.org_id=org.id
                AND u.email='nekrasivostore@gmail.com')
  RETURNING name, trial_ends_at, trial_extra_days;"
echo
echo "— фикс регистрации на месте? —"
grep -c "ORDER BY u.created_at DESC" /opt/fo/backend/app/routers/auth.py 2>/dev/null \
  && echo "auth.py: сортировка есть" || echo "auth.py: сортировки НЕТ"
grep -c "уже зарегистрирована" /opt/fo/backend/app/routers/signup.py 2>/dev/null \
  && echo "signup.py: защита от второго агентства есть" || echo "signup.py: защиты НЕТ"
echo
echo "— эндпоинты сервиса —"
grep -n "service/" /opt/fo/backend/app/routers/admin.py | head -12
echo
echo "— main.py целиком —"
cat -n /opt/fo/backend/app/main.py
