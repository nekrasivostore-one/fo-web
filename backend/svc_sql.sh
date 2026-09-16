#!/usr/bin/env bash
# Схема под панель админа: пометки о триале, журнал входов, адрес последнего входа.
# Плюс диагностика: какие роутеры подключены и что сейчас в org.
set -u
cd /tmp
/opt/fo/venv/bin/python - <<'PY'
import asyncio, io, os, re, sys
env = {}
for line in io.open("/opt/fo/.env", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip().strip('"').strip("'")
dsn = env.get("DATABASE_URL") or env.get("DB_DSN") or env.get("POSTGRES_DSN") or ""
if not dsn:
    print("не нашёл строку подключения в .env; ключи:", ", ".join(sorted(env))); sys.exit(2)

SQL = [
 "ALTER TABLE org ADD COLUMN IF NOT EXISTS trial_extra_days int NOT NULL DEFAULT 0",
 "ALTER TABLE org ADD COLUMN IF NOT EXISTS trial_note text",
 "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_ip text",
 "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_seen timestamptz",
 """CREATE TABLE IF NOT EXISTS ip_log (
      id bigserial PRIMARY KEY, user_id uuid, org_id uuid,
      email text, ip text, ua text,
      at timestamptz NOT NULL DEFAULT now())""",
 "CREATE INDEX IF NOT EXISTS ip_log_at_idx ON ip_log (at DESC)",
 "CREATE INDEX IF NOT EXISTS ip_log_org_idx ON ip_log (org_id, at DESC)",
]

async def main():
    import asyncpg
    c = await asyncpg.connect(dsn)
    for q in SQL:
        await c.execute(q)
        print("ok:", " ".join(q.split())[:72])
    print("\n— роли в справочнике —")
    for r in await c.fetch("SELECT code, title, level FROM role ORDER BY level"):
        print("  %-18s %-28s уровень %s" % (r["code"], r["title"], r["level"]))
    print("\n— агентства —")
    for r in await c.fetch("""SELECT o.id, o.name, o.created_at::date AS d, o.trial_ends_at,
                                     (SELECT count(*) FROM app_user u WHERE u.org_id=o.id) AS users,
                                     (SELECT count(*) FROM client cl WHERE cl.org_id=o.id) AS cl,
                                     (SELECT count(*) FROM fn f WHERE f.org_id=o.id) AS fns
                              FROM org o ORDER BY o.created_at"""):
        print("  %-38s %s  людей %-3s клиентов %-3s функций %-4s триал %s"
              % (r["name"][:38], r["d"], r["users"], r["cl"], r["fns"], r["trial_ends_at"]))
    print("\n— люди —")
    for r in await c.fetch("""SELECT u.email, u.role_code, u.first_login, o.name
                              FROM app_user u JOIN org o ON o.id=u.org_id
                              ORDER BY u.created_at"""):
        print("  %-34s %-16s %s  %s" % (r["email"], r["role_code"],
              "не вошёл" if r["first_login"] else "работает", r["name"][:26]))
    await c.close()

asyncio.run(main())
PY
echo "— роутеры в main.py —"
grep -n "include_router" /opt/fo/backend/app/main.py | sed 's/^/  /'
echo "— префикс роутера admin.py —"
grep -n "APIRouter(" /opt/fo/backend/app/routers/admin.py | sed 's/^/  /'
