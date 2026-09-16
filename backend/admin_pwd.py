# Админ сервиса с готовым паролем: человек входит сразу, без кода из письма.
# Пароль генерируется здесь, на сервере, и печатается ровно один раз.
import asyncio, io, secrets, string, sys, uuid, importlib

EMAIL = "politicalhelp@yandex.ru"
LEN   = 30
ALPH  = string.ascii_letters + string.digits + "!@#%^*_+-=?.:"

def gen():
    while True:
        p = "".join(secrets.choice(ALPH) for _ in range(LEN))
        if (any(c.islower() for c in p) and any(c.isupper() for c in p)
            and any(c.isdigit() for c in p) and any(c in "!@#%^*_+-=?.:" for c in p)):
            return p

def dsn():
    env = {}
    for line in io.open("/opt/fo/.env", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env.get("DATABASE_URL") or env.get("DB_DSN") or env.get("POSTGRES_DSN") or ""

def hasher():
    """Берём ту же функцию хеширования, что и сам сервис, иначе вход не сойдётся."""
    sys.path.insert(0, "/opt/fo/backend")
    for mod in ("app.security", "app.auth", "app.deps", "app.utils", "app.hash"):
        try:
            m = importlib.import_module(mod)
        except Exception:
            continue
        for name in ("hash_password", "hash_pwd", "make_password", "pwd_hash", "get_password_hash"):
            f = getattr(m, name, None)
            if callable(f):
                return ("%s.%s" % (mod, name)), f
        ctx = getattr(m, "pwd_context", None) or getattr(m, "pwd", None)
        if ctx is not None and hasattr(ctx, "hash"):
            return ("%s.pwd_context.hash" % mod), ctx.hash
    try:
        from passlib.context import CryptContext
        return "passlib bcrypt", CryptContext(schemes=["bcrypt"], deprecated="auto").hash
    except Exception:
        return None, None

async def main():
    import asyncpg
    where, h = hasher()
    if not h:
        print("не нашёл функцию хеширования пароля — покажите app/security.py"); sys.exit(3)
    print("хеширую так же, как сервис:", where)

    # пароль можно передать первым аргументом — тогда он не зависит от того,
    # правильно ли кто-то прочитал его с экрана консоли
    pwd = sys.argv[1] if len(sys.argv) > 1 and len(sys.argv[1]) >= 12 else gen()
    c = await asyncpg.connect(dsn())

    cols = {r["column_name"]: r for r in await c.fetch(
        """SELECT column_name, is_nullable, column_default FROM information_schema.columns
           WHERE table_name='app_user'""")}
    pcol = None
    for cand in ("password_hash", "pwd_hash", "hashed_password", "password", "pass_hash"):
        if cand in cols: pcol = cand; break
    if not pcol:
        print("не нашёл колонку пароля; есть:", sorted(cols)); await c.close(); sys.exit(4)
    print("колонка пароля:", pcol)

    org = await c.fetchrow("SELECT id, name FROM org WHERE name='Flater' ORDER BY created_at LIMIT 1")
    if not org:
        org = await c.fetchrow("SELECT id, name FROM org ORDER BY created_at LIMIT 1")

    cur = await c.fetchrow("SELECT id FROM app_user WHERE email=$1", EMAIL)
    if cur:
        await c.execute(
            "UPDATE app_user SET role_code='admin', is_active=true, first_login=false, %s=$2 WHERE id=$1"
            % pcol, cur["id"], h(pwd))
        uid = cur["id"]; what = "обновлён"
    else:
        known = {"email": EMAIL, "org_id": org["id"], "role_code": "admin",
                 "is_active": True, "first_login": False, pcol: h(pwd)}
        names, vals = [], []
        if not cols["id"]["column_default"]:
            names.append("id"); vals.append(uuid.uuid4())
        missing = []
        for n, r in cols.items():
            if n in known:
                names.append(n); vals.append(known[n])
            elif n != "id" and r["is_nullable"] == "NO" and not r["column_default"]:
                missing.append(n)
        if missing:
            print("обязательные поля без умолчания, не знаю чем заполнить:", missing)
            await c.close(); sys.exit(5)
        q = "INSERT INTO app_user (%s) VALUES (%s) RETURNING id" % (
            ", ".join(names), ", ".join("$%d" % (i+1) for i in range(len(vals))))
        uid = await c.fetchval(q, *vals); what = "создан"

    await c.close()
    print("админ %s: %s" % (what, EMAIL))
    print("агентство:", org["name"] if org else "—")
    print("пароль длиной %d символов установлен" % len(pwd))
    print("первые 3 символа для сверки: %s…" % pwd[:3])

asyncio.run(main())
