#!/usr/bin/env bash
# Один аккаунт на почту Виталия: живой — самый свежий собственник.
# Ничего не удаляем, только гасим лишние (is_active=false) — вернуть можно одной строкой.
set -u
DB=fo
EM='nekrasivostore@gmail.com'

echo "— было —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "SELECT u.id, u.role_code, u.is_active, u.first_login, u.created_at, o.name
  FROM app_user u JOIN org o ON o.id=u.org_id
  WHERE u.email='$EM' ORDER BY u.created_at;"

echo
echo "— гасим всё, кроме самого свежего аккаунта —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "UPDATE app_user SET is_active=false
  WHERE email='$EM'
    AND id <> (SELECT id FROM app_user WHERE email='$EM' ORDER BY created_at DESC LIMIT 1)
  RETURNING id, role_code, created_at;"

echo
echo "— живой аккаунт: делаем собственником —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "UPDATE app_user SET role_code='owner'
  WHERE id=(SELECT id FROM app_user WHERE email='$EM' ORDER BY created_at DESC LIMIT 1)
  RETURNING id, role_code;"

echo
echo "— стало —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "SELECT u.role_code, u.is_active, u.first_login, u.created_at, o.name
  FROM app_user u JOIN org o ON o.id=u.org_id
  WHERE u.email='$EM' ORDER BY u.created_at;"

echo
echo "— в сервисе сейчас админов: —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "SELECT email, is_active FROM app_user WHERE role_code='admin';"
