#!/usr/bin/env bash
set -u
B="https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend"
curl -fsSL "$B/admin_pwd.py?t=$(date +%s)" -o /tmp/admin_pwd.py || { echo "не скачался"; exit 1; }
grep -q "Админ сервиса с готовым паролем" /tmp/admin_pwd.py || { echo "не тот файл"; exit 1; }
cd /tmp && /opt/fo/venv/bin/python /tmp/admin_pwd.py
echo
echo "— админы —"
sudo -u postgres psql -d fo -A -F' | ' -c \
 "SELECT u.email, u.role_code, u.is_active, u.first_login, o.name
  FROM app_user u JOIN org o ON o.id=u.org_id WHERE u.role_code='admin';"
