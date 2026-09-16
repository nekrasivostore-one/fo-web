#!/usr/bin/env bash
# ALTER от владельца таблиц: приложение ходит в базу под ограниченным пользователем.
set -u
DSN=$(/opt/fo/venv/bin/python - <<'PY'
import io
env={}
for line in io.open("/opt/fo/.env", encoding="utf-8"):
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,v=line.split("=",1); env[k.strip()]=v.strip().strip('"').strip("'")
print(env.get("DATABASE_URL") or env.get("DB_DSN") or env.get("POSTGRES_DSN") or "")
PY
)
DB=$(/opt/fo/venv/bin/python - "$DSN" <<'PY'
import sys
from urllib.parse import urlparse
u=urlparse(sys.argv[1]); print((u.path or "/").lstrip("/") or "fo")
PY
)
echo "база: $DB"
sudo -u postgres psql -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE org      ADD COLUMN IF NOT EXISTS trial_extra_days int NOT NULL DEFAULT 0;
ALTER TABLE org      ADD COLUMN IF NOT EXISTS trial_note text;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_ip text;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_seen timestamptz;
CREATE TABLE IF NOT EXISTS ip_log (
  id bigserial PRIMARY KEY, user_id uuid, org_id uuid,
  email text, ip text, ua text, at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ip_log_at_idx  ON ip_log (at DESC);
CREATE INDEX IF NOT EXISTS ip_log_org_idx ON ip_log (org_id, at DESC);
SQL
echo "— выдаём права приложению —"
APPUSER=$(/opt/fo/venv/bin/python - "$DSN" <<'PY'
import sys
from urllib.parse import urlparse
print(urlparse(sys.argv[1]).username or "")
PY
)
echo "пользователь приложения: $APPUSER"
sudo -u postgres psql -d "$DB" -c "GRANT ALL ON ip_log TO \"$APPUSER\";" 2>&1 | tail -2
sudo -u postgres psql -d "$DB" -c "GRANT USAGE, SELECT ON SEQUENCE ip_log_id_seq TO \"$APPUSER\";" 2>&1 | tail -2
echo
echo "— что в базе —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "SELECT o.name, o.created_at::date, o.trial_ends_at,
         (SELECT count(*) FROM app_user u WHERE u.org_id=o.id) AS users,
         (SELECT count(*) FROM client c WHERE c.org_id=o.id)   AS clients,
         (SELECT count(*) FROM fn f WHERE f.org_id=o.id)       AS fns
  FROM org o ORDER BY o.created_at;"
echo
sudo -u postgres psql -d "$DB" -A -F' | ' -c \
 "SELECT u.email, u.role_code, u.first_login, o.name
  FROM app_user u JOIN org o ON o.id=u.org_id ORDER BY u.created_at;"
echo
echo "— роли —"
sudo -u postgres psql -d "$DB" -A -F' | ' -c "SELECT code, title, level FROM role ORDER BY level;"
echo
echo "— main.py —"
sed -n '1,70p' /opt/fo/backend/app/main.py
