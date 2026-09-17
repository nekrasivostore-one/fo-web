# -*- coding: utf-8 -*-
"""Шаг на сервере: аккаунт человека и персональные приглашения с ролью.

Механизм доставки односторонний — файлы едут на сервер, а прочитать их
оттуда нечем. Поэтому правки, которые нельзя перевезти файлом целиком,
делает этот скрипт прямо на сервере. Он же собирает отчёт: что нашёл,
что изменил, что не сошлось. Отчёт кладётся в /opt/fo/web/fo-step.txt
и виден в панели админа.

Безопасность: перед правкой делается копия, после — проверка синтаксиса,
перезапуск и health. Не поднялось — возвращаем как было.
"""
import io, os, re, shutil, subprocess, sys, datetime

APP  = "/opt/fo/backend/app"
REFS = APP + "/routers/refs.py"
SIGN = APP + "/routers/signup.py"
MAIN = APP + "/main.py"
PY   = "/opt/fo/venv/bin/python"
MARK = "FO-STEP-ACCOUNT-INVITES"
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
out = []
def p(*a): out.append(" ".join(str(x) for x in a))

def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return "ОШИБКА: %s" % e

# ══ 1. что вообще есть на сервере ═══════════════════════════════
p("== РОЛИ В БАЗЕ ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT code||' | '||level||' | '||coalesce(title,'-') FROM role ORDER BY level\"").strip() or "(пусто)")

p("")
p("== КОЛОНКИ app_user ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='app_user'\"").strip())

p("")
p("== ТАБЛИЦЫ ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(table_name,', ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public'\"").strip())

p("")
p("== ТАБЛИЦА СОТРУДНИКОВ ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT t.table_name||': '||string_agg(c.column_name,', ' ORDER BY c.ordinal_position) FROM information_schema.tables t JOIN information_schema.columns c ON c.table_name=t.table_name WHERE t.table_schema='public' AND t.table_name IN ('employee','employees','emp','staff','person','people','member','members') GROUP BY t.table_name\"").strip() or "(не нашёл)")

p("")
p("== КОЛОНКИ org ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='org'\"").strip())

try:
    refs_src = io.open(REFS, encoding="utf-8").read()
except Exception as e:
    p("НЕ ЧИТАЕТСЯ refs.py:", e); print("\n".join(out)); sys.exit(1)
try:
    sign_src = io.open(SIGN, encoding="utf-8").read()
except Exception as e:
    p("НЕ ЧИТАЕТСЯ signup.py:", e); print("\n".join(out)); sys.exit(1)

p("")
p("== РОУТЕРЫ ==")
for name, src in (("refs.py", refs_src), ("signup.py", sign_src)):
    m = re.search(r"router\s*=\s*APIRouter\((.*?)\)", src, re.S)
    p(name + ": " + (m.group(0).replace("\n", " ") if m else "APIRouter не найден"))
p("refs.py импорты: " + ", ".join(sorted(set(re.findall(r"^from\s+\S+\s+import\s+(.+)$", refs_src, re.M))))[:600])

p("")
p("== register в signup.py ==")
m = re.search(r'@router\.post\("/register"\)[\s\S]{0,2200}?(?=\n@router\.|\nclass\s|\Z)', sign_src)
p(m.group(0) if m else "(не нашёл /register)")

p("")
p("== include_router в main.py ==")
try:
    p("\n".join(l.strip() for l in io.open(MAIN, encoding="utf-8").read().split("\n") if "include_router" in l))
except Exception as e:
    p("main.py не читается:", e)

# какую колонку имени использует сервис
NAME_COL = ""
cols = sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,',') FROM information_schema.columns WHERE table_name='app_user'\"").strip()
have = set(x.strip() for x in cols.split(","))
for cand in ("full_name", "name", "display_name", "first_name", "fio"):
    if cand in have:
        NAME_COL = cand; break
p("")
p("колонка имени в app_user:", NAME_COL or "НЕ НАЙДЕНА")

# ══ 2. база ═════════════════════════════════════════════════════
SQL = """
CREATE TABLE IF NOT EXISTS org_invite (
  token       text PRIMARY KEY,
  org_id      uuid NOT NULL,
  role_code   text NOT NULL,
  name        text,
  email       text,
  person_ref  text,
  created_by  uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  used_at     timestamptz,
  used_by     uuid,
  revoked_at  timestamptz
);
CREATE INDEX IF NOT EXISTS org_invite_org_idx ON org_invite (org_id, created_at DESC);
CREATE TABLE IF NOT EXISTS pwd_code (
  id      bigserial PRIMARY KEY,
  user_id uuid NOT NULL,
  code    text NOT NULL,
  made_at timestamptz NOT NULL DEFAULT now(),
  used_at timestamptz,
  tries   int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pwd_code_user_idx ON pwd_code (user_id, made_at DESC);
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS display_name text;
GRANT SELECT, INSERT, UPDATE, DELETE ON org_invite, pwd_code TO fo;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fo;
"""
io.open("/tmp/fo_step.sql", "w", encoding="utf-8").write(SQL)
p("")
p("== МИГРАЦИЯ ==")
r1 = sh("sudo -u postgres psql -d fo -v ON_ERROR_STOP=1 -f /tmp/fo_step.sql").strip()
p("через postgres:", r1 or "(молча — значит применилось)")

def dsn():
    """Строка подключения приложения — на случай, если sudo не дали."""
    try:
        env = {}
        for line in io.open("/opt/fo/.env", encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
        return (env.get("DATABASE_URL") or env.get("DB_DSN")
                or env.get("POSTGRES_DSN") or "")
    except Exception:
        return ""

def tables_ok():
    """Есть ли уже нужные таблицы — проверяем от имени приложения."""
    code = (
        "import asyncio,asyncpg,sys\n"
        "async def m():\n"
        "    c=await asyncpg.connect(%r)\n"
        "    got=await c.fetchval(\"SELECT count(*) FROM information_schema.tables \"\n"
        "        \"WHERE table_name IN ('org_invite','pwd_code')\")\n"
        "    print('таблиц найдено:', got)\n"
        "    await c.close()\n"
        "asyncio.run(m())\n" % dsn())
    io.open("/tmp/fo_chk.py", "w", encoding="utf-8").write(code)
    return sh("%s /tmp/fo_chk.py" % PY).strip()

chk = tables_ok()
p("проверка:", chk)
if "таблиц найдено: 2" not in chk and dsn():
    p("postgres не сработал — пробую под пользователем приложения")
    code2 = (
        "import asyncio,asyncpg,io\n"
        "SQL=io.open('/tmp/fo_step.sql',encoding='utf-8').read()\n"
        "async def m():\n"
        "    c=await asyncpg.connect(%r)\n"
        "    for stmt in [x.strip() for x in SQL.split(';') if x.strip()]:\n"
        "        try:\n"
        "            await c.execute(stmt)\n"
        "        except Exception as e:\n"
        "            print('  пропущено:', str(e)[:120])\n"
        "    await c.close()\n"
        "    print('готово')\n"
        "asyncio.run(m())\n" % dsn())
    io.open("/tmp/fo_step2.py", "w", encoding="utf-8").write(code2)
    p(sh("%s /tmp/fo_step2.py" % PY).strip()[:1500])
    p("проверка ещё раз:", tables_ok())

# ══ 3. код ══════════════════════════════════════════════════════
def cut(src):
    """Старый блок шага срезаем целиком — он всегда в конце файла."""
    i = src.find("# " + chr(9552)*2 + " " + MARK)
    if i < 0:
        i = src.find(MARK)
        if i >= 0:
            i = src.rfind("\n", 0, i)
    return src[:i] if i >= 0 else src

ADD_REFS = r'''

# ══ FO-STEP-ACCOUNT-INVITES ══════════════════════════════════════
# Мой аккаунт и персональные приглашения с уровнем доступа.
# Дописано шагом деплоя: перевезти refs.py целиком нечем — прочитать
# его с сервера механизм не умеет, поэтому правка идёт дописыванием.
import secrets as _fo_secrets
import importlib as _fo_il
from pydantic import BaseModel as _FoBM

_FO_NAME_COL = "__NAME_COL__"

def _fo_uid(p):
    for n in ("user_id", "uid", "id", "sub"):
        v = getattr(p, n, None)
        if v is not None:
            return v
    raise HTTPException(500, "в токене нет пользователя")

def _fo_hash():
    for mod in ("app.security", "app.auth", "app.deps", "app.utils", "app.hash"):
        try:
            m = _fo_il.import_module(mod)
        except Exception:
            continue
        for n in ("hash_password", "hash_pwd", "make_password", "pwd_hash", "get_password_hash"):
            f = getattr(m, n, None)
            if callable(f):
                return f
        ctx = getattr(m, "pwd_context", None)
        if ctx is not None and hasattr(ctx, "hash"):
            return ctx.hash
    return None

async def _fo_send(email, subject, text):
    """Письмо уходит тем же способом, что и код входа."""
    try:
        n = _fo_il.import_module("app.notify")
    except Exception:
        return False
    f = getattr(n, "send_email", None)
    if not callable(f):
        return False
    try:
        return bool(await f(email, subject, text))
    except Exception:
        return False


@router.get("/roles")
async def fo_roles(p: Principal = Depends(current)):
    """Уровни доступа как они есть в базе — фронт не выдумывает свои."""
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT code, level, __ROLE_TITLE__ AS rtitle FROM role ORDER BY level")
    return [{"code": r["code"], "level": r["level"],
             "title": r["rtitle"] or r["code"]} for r in rows]


# ── Мой аккаунт ──────────────────────────────────────────────────

@router.get("/me/account")
async def fo_me(p: Principal = Depends(current)):
    uid = _fo_uid(p)
    async with pool().acquire() as c:
        u = await c.fetchrow(
            "SELECT u.id, u.email, u.role_code, u.created_at, u.first_login, "
            "       u.phone, u.display_name, u." + _FO_NAME_COL + " AS base_name, "
            "       r.level, r.__ROLE_TITLE__ AS role_title, "
            "       o.name AS org_name, o.invite_code, o.id AS org_id "
            "FROM app_user u JOIN role r ON r.code = u.role_code "
            "JOIN org o ON o.id = u.org_id WHERE u.id = $1", uid)
        if not u:
            raise HTTPException(404, "аккаунт не найден")
        pwd_col = await c.fetchval(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='app_user' AND column_name = ANY($1::text[]) LIMIT 1",
            ["password_hash", "pwd_hash", "hashed_password", "password", "pass_hash"])
        has_pwd = False
        if pwd_col:
            has_pwd = bool(await c.fetchval(
                "SELECT " + pwd_col + " IS NOT NULL AND " + pwd_col + " <> '' "
                "FROM app_user WHERE id=$1", uid))
    return {"id": str(u["id"]), "email": u["email"],
            "name": u["display_name"] or u["base_name"] or "",
            "phone": u["phone"] or "",
            "role_code": u["role_code"], "role_title": u["role_title"] or u["role_code"],
            "level": u["level"], "org_name": u["org_name"],
            "org_id": str(u["org_id"]), "invite_code": u["invite_code"],
            "created_at": u["created_at"], "has_password": has_pwd}


class FoMeIn(_FoBM):
    name:  str | None = None
    phone: str | None = None


@router.post("/me/account")
async def fo_me_save(body: FoMeIn, p: Principal = Depends(current)):
    """Имя и телефон правит сам человек — на любой роли."""
    uid = _fo_uid(p)
    sets, vals = [], []
    if body.name is not None:
        nm = (body.name or "").strip()
        if len(nm) < 2:
            raise HTTPException(400, "Имя короче двух символов")
        vals.append(nm); sets.append("display_name=$%d" % (len(vals) + 1))
        if _FO_NAME_COL and _FO_NAME_COL != "display_name":
            vals.append(nm); sets.append(_FO_NAME_COL + "=$%d" % (len(vals) + 1))
    if body.phone is not None:
        vals.append((body.phone or "").strip()); sets.append("phone=$%d" % (len(vals) + 1))
    if not sets:
        return {"ok": True, "changed": 0}
    async with pool().acquire() as c:
        await c.execute("UPDATE app_user SET " + ", ".join(sets) + " WHERE id=$1", uid, *vals)
    return {"ok": True, "changed": len(sets)}


@router.post("/me/password/code")
async def fo_pwd_code(p: Principal = Depends(current)):
    """Код на рабочую почту — без него пароль не меняется."""
    uid = _fo_uid(p)
    code = "".join(_fo_secrets.choice("0123456789") for _ in range(6))
    async with pool().acquire() as c:
        email = await c.fetchval("SELECT email FROM app_user WHERE id=$1", uid)
        if not email:
            raise HTTPException(404, "аккаунт не найден")
        await c.execute("UPDATE pwd_code SET used_at=now() WHERE user_id=$1 AND used_at IS NULL", uid)
        await c.execute("INSERT INTO pwd_code (user_id, code) VALUES ($1,$2)", uid, code)
    sent = await _fo_send(
        email, "Код для смены пароля " + code + " — Flater Team Service",
        "Код для смены пароля: " + code + "\n\nОн живёт 15 минут. "
        "Если вы не меняли пароль — просто не вводите его.")
    out = {"ok": True, "mail_sent": sent, "email": email}
    if not sent:
        out["code_shown"] = code
    return out


class FoPwdIn(_FoBM):
    code:     str
    password: str


@router.post("/me/password")
async def fo_pwd_set(body: FoPwdIn, p: Principal = Depends(current)):
    uid = _fo_uid(p)
    pwd = (body.password or "").strip()
    if len(pwd) < 8:
        raise HTTPException(400, "Пароль короче восьми символов")
    h = _fo_hash()
    if not h:
        raise HTTPException(500, "на сервере не нашлась функция хеширования")
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "SELECT id, code, made_at, tries FROM pwd_code "
            "WHERE user_id=$1 AND used_at IS NULL ORDER BY made_at DESC LIMIT 1", uid)
        if not row:
            raise HTTPException(400, "Сначала запросите код")
        import datetime as _dt
        age = (_dt.datetime.now(_dt.timezone.utc) - row["made_at"]).total_seconds()
        if age > 900:
            raise HTTPException(400, "Код истёк — запросите новый")
        if row["tries"] >= 5:
            raise HTTPException(429, "Слишком много попыток — запросите новый код")
        if (body.code or "").strip() != row["code"]:
            await c.execute("UPDATE pwd_code SET tries=tries+1 WHERE id=$1", row["id"])
            raise HTTPException(400, "Код неверен")
        pwd_col = await c.fetchval(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='app_user' AND column_name = ANY($1::text[]) LIMIT 1",
            ["password_hash", "pwd_hash", "hashed_password", "password", "pass_hash"])
        if not pwd_col:
            raise HTTPException(500, "в базе нет колонки пароля")
        async with c.transaction():
            await c.execute("UPDATE app_user SET " + pwd_col + "=$2 WHERE id=$1", uid, h(pwd))
            await c.execute("UPDATE pwd_code SET used_at=now() WHERE id=$1", row["id"])
    return {"ok": True}


# ── Персональные приглашения с уровнем доступа ───────────────────

class FoInviteIn(_FoBM):
    role_code:  str
    name:       str | None = None
    email:      str | None = None
    person_ref: str | None = None


@router.post("/invites")
async def fo_invite_new(body: FoInviteIn, p: Principal = Depends(max_level(1))):
    """Собственник и директор выдают приглашение с уровнем доступа.

    Уровень должен быть НИЖЕ того, кто приглашает, и никогда не
    собственник и не админ сервиса."""
    async with pool().acquire() as c:
        me = await c.fetchrow(
            "SELECT r.level FROM app_user u JOIN role r ON r.code=u.role_code WHERE u.id=$1",
            _fo_uid(p))
        want = await c.fetchrow("SELECT code, level FROM role WHERE code=$1", body.role_code)
        if not want:
            raise HTTPException(400, "Такого уровня доступа нет")
        if want["level"] <= 1:
            raise HTTPException(403, "Собственника и администратора так не назначают")
        if me and want["level"] <= me["level"]:
            raise HTTPException(403, "Нельзя выдать уровень выше своего")
        token = _fo_secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")[:12]
        await c.execute(
            "INSERT INTO org_invite (token, org_id, role_code, name, email, person_ref, created_by) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7)",
            token, p.org_id, body.role_code, (body.name or "").strip() or None,
            (body.email or "").strip() or None, (body.person_ref or "").strip() or None,
            _fo_uid(p))
        code = await c.fetchval("SELECT invite_code FROM org WHERE id=$1", p.org_id)
    return {"ok": True, "token": token, "role_code": body.role_code,
            "url": "https://fo.flater.pro/?invite=" + (code or "") + "&i=" + token}


@router.get("/invites")
async def fo_invite_list(p: Principal = Depends(current)):
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT token, role_code, name, email, person_ref, created_at, used_at, revoked_at "
            "FROM org_invite WHERE org_id=$1 ORDER BY created_at DESC LIMIT 200", p.org_id)
    return [dict(r) for r in rows]


@router.post("/invites/{token}/revoke")
async def fo_invite_revoke(token: str, p: Principal = Depends(max_level(1))):
    async with pool().acquire() as c:
        n = await c.execute(
            "UPDATE org_invite SET revoked_at=now() "
            "WHERE token=$1 AND org_id=$2 AND used_at IS NULL AND revoked_at IS NULL",
            token, p.org_id)
    return {"ok": True, "changed": n}


@router.get("/step")
async def fo_step_report(p: Principal = Depends(max_level(0))):
    """Отчёт последнего шага деплоя — чтобы не ходить в консоль."""
    try:
        with open("/opt/fo/step-last.txt", encoding="utf-8") as _f:
            return {"ok": True, "text": _f.read()}
    except Exception as e:
        return {"ok": False, "text": "отчёта нет: %s" % e}
'''

ADD_SIGN = r'''

# ══ FO-STEP-ACCOUNT-INVITES ══════════════════════════════════════
# Вход по персональному приглашению: уровень доступа выдаёт сервер,
# из приглашения, а не браузер. Приглашение одноразовое.
from pydantic import BaseModel as _FoBM2


@router.get("/invite-token/{token}")
async def fo_invite_peek(token: str):
    """Кто и куда зовёт — видно до регистрации."""
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "SELECT o.name AS org_name, i.role_code, i.name, i.used_at, i.revoked_at, "
            "       rl.__ROLE_TITLE__ AS role_title "
            "FROM org_invite i JOIN org o ON o.id=i.org_id "
            "LEFT JOIN role rl ON rl.code=i.role_code WHERE i.token=$1", token.strip())
    if not r:
        raise HTTPException(404, "Приглашение не найдено")
    if r["revoked_at"]:
        raise HTTPException(410, "Приглашение отозвано")
    if r["used_at"]:
        raise HTTPException(410, "Этим приглашением уже воспользовались")
    return {"org_name": r["org_name"], "role_code": r["role_code"],
            "role_title": r["role_title"] or r["role_code"], "name": r["name"]}


async def _fo_link_employee(conn, org_id, uid, name, email):
    """Кто зашёл по приглашению — сразу виден в команде, доступах и задачах.

    Регистрация заводит человека в app_user, а списки команды и
    ответственных сервис берёт из таблицы сотрудников. Без связки
    собственник нового человека просто не увидит."""
    tbl = None
    for cand in ("employee", "employees", "staff", "member", "people", "person"):
        if await conn.fetchval("SELECT to_regclass($1)", "public." + cand):
            tbl = cand
            break
    if not tbl:
        return None
    cols = set(r["column_name"] for r in await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name=$1", tbl))
    if "org_id" not in cols or "name" not in cols:
        return None
    nm = (name or "").strip() or (email or "").split("@")[0]

    if "user_id" in cols:
        got = await conn.fetchval("SELECT id FROM " + tbl + " WHERE user_id=$1", uid)
        if got:
            return got
    row = None
    if email and "email" in cols:
        row = await conn.fetchrow(
            "SELECT id FROM " + tbl + " WHERE org_id=$1 AND lower(email)=lower($2) LIMIT 1",
            org_id, email)
    if not row and nm:
        row = await conn.fetchrow(
            "SELECT id FROM " + tbl + " WHERE org_id=$1 AND lower(name)=lower($2) LIMIT 1",
            org_id, nm)
    if row:
        if "user_id" in cols:
            await conn.execute("UPDATE " + tbl + " SET user_id=$2 WHERE id=$1", row["id"], uid)
        if "is_active" in cols:
            await conn.execute("UPDATE " + tbl + " SET is_active=true WHERE id=$1", row["id"])
        return row["id"]

    names, vals = ["org_id", "name"], [org_id, nm]
    if "user_id" in cols:
        names.append("user_id"); vals.append(uid)
    if "email" in cols and email:
        names.append("email"); vals.append(email)
    if "is_active" in cols:
        names.append("is_active"); vals.append(True)
    q = ("INSERT INTO " + tbl + " (" + ", ".join(names) + ") VALUES (" +
         ", ".join("$%d" % (i + 1) for i in range(len(vals))) + ") RETURNING id")
    return await conn.fetchval(q, *vals)


class FoAcceptIn(_FoBM2):
    token: str
    email: str


@router.post("/invite-accept")
async def fo_invite_accept(body: FoAcceptIn):
    tok = (body.token or "").strip()
    mail = (body.email or "").strip().lower()
    async with pool().acquire() as conn:
        inv = await conn.fetchrow(
            "SELECT i.*, o.name AS org_name FROM org_invite i "
            "JOIN org o ON o.id=i.org_id WHERE i.token=$1", tok)
        if not inv:
            raise HTTPException(404, "Приглашение не найдено")
        if inv["revoked_at"]:
            raise HTTPException(410, "Приглашение отозвано")
        if inv["used_at"]:
            raise HTTPException(410, "Этим приглашением уже воспользовались")

        prev = await conn.fetchrow(
            "SELECT id, first_login FROM app_user WHERE email=$1 AND is_active "
            "ORDER BY created_at DESC LIMIT 1", mail)
        if prev and not prev["first_login"]:
            raise HTTPException(409, "Эта почта уже зарегистрирована — войдите по паролю")

        async with conn.transaction():
            if prev:
                uid = prev["id"]
                await conn.execute(
                    "UPDATE app_user SET org_id=$2, role_code=$3 WHERE id=$1",
                    uid, inv["org_id"], inv["role_code"])
            else:
                uid = await _make_user(conn, inv["org_id"], mail, inv["role_code"],
                                       (inv["name"] or mail.split("@")[0]))
            await conn.execute(
                "UPDATE org_invite SET used_at=now(), used_by=$2 WHERE token=$1", tok, uid)
            code2, sent = await _issue_code(conn, uid, mail, "first_login")

        # связываем с карточкой сотрудника — иначе собственник его не увидит
        linked = None
        try:
            linked = await _fo_link_employee(conn, inv["org_id"], uid, inv["name"] or "", mail)
        except Exception:
            linked = None
    out = {"ok": True, "workspace": inv["org_name"], "role_code": inv["role_code"],
           "linked": bool(linked), "next": "verify", "mail_sent": sent}
    if not sent:
        out["code_shown"] = code2
    return out
'''

if not NAME_COL:
    NAME_COL = "display_name"
ADD_REFS = ADD_REFS.replace("__NAME_COL__", NAME_COL)

has_title = sh("sudo -u postgres psql -d fo -Atc \"SELECT 1 FROM information_schema.columns WHERE table_name='role' AND column_name='title'\"").strip()
ROLE_TITLE = "title" if has_title.startswith("1") else "code"
p("колонка title в role:", "есть" if ROLE_TITLE == "title" else "нет — беру code")
ADD_REFS = ADD_REFS.replace("__ROLE_TITLE__", ROLE_TITLE)
ADD_SIGN = ADD_SIGN.replace("__ROLE_TITLE__", ROLE_TITLE)

H0 = sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip()
p("")
p("health до правки:", H0)

bak = "/opt/fo/backend-step-bak-" + stamp
os.makedirs(bak, exist_ok=True)
shutil.copy(REFS, bak + "/refs.py")
shutil.copy(SIGN, bak + "/signup.py")

io.open(REFS, "w", encoding="utf-8").write(cut(refs_src).rstrip("\n") + "\n" + ADD_REFS)
io.open(SIGN, "w", encoding="utf-8").write(cut(sign_src).rstrip("\n") + "\n" + ADD_SIGN)

p("")
p("== КОД ==")
p("дописано в refs.py и signup.py, копия в", bak)

ok = True
for f in (REFS, SIGN):
    r = sh("%s -m py_compile %s" % (PY, f))
    if r.strip():
        p("синтаксис не сошёлся в", f, ":", r.strip()[:500]); ok = False

if ok:
    sh("systemctl restart fo")
    sh("sleep 4")
    h = sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip()
    p("health после правки:", h)
    if h != "200" and H0 == "200":
        ok = False          # сломали то, что работало — возвращаем
    elif h != "200":
        p("сервис и до правки не отвечал — откатывать нечего, оставляю новую версию")

if not ok:
    shutil.copy(bak + "/refs.py", REFS)
    shutil.copy(bak + "/signup.py", SIGN)
    sh("systemctl restart fo"); sh("sleep 3")
    p("ОТКАТ: вернул как было, health=" + sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip())
    p("ЧТО ПОШЛО НЕ ТАК — смотрите journalctl -u fo -n 40")
    p(sh("journalctl -u fo -n 30 --no-pager")[-2000:])
else:
    p("ГОТОВО: аккаунт и приглашения на сервере")

print("\n".join(out))
