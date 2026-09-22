# -*- coding: utf-8 -*-
"""Основательный шаг: всё, что сервис хранил в браузере, переезжает на сервер.

Правило проекта: браузер — не хранилище. Значит на сервере должно быть
место для всего, что человек вносит руками:

  fo_card       — карточки клиента, сотрудника, функции и агентства
                  (одна таблица, поля в jsonb: их состав меняется вместе
                  с интерфейсом и не требует новой миграции каждый раз)
  fo_task_once  — разовые задачи: в штатном API их создать нечем,
                  задачи там рождаются только из функций
  org_invite    — персональные приглашения с уровнем доступа
  pwd_code      — смена пароля по коду с рабочей почты

Скрипт идемпотентный: свой блок в файлах он срезает и кладёт заново,
поэтому его можно гонять сколько угодно раз.

Безопасность: копия до правки, проверка синтаксиса, перезапуск, health.
Не поднялось — вернули как было.
"""
import re
import io, os, re, shutil, subprocess, sys, datetime

APP  = "/opt/fo/backend/app"
REFS = APP + "/routers/refs.py"
SIGN = APP + "/routers/signup.py"
MAIN = APP + "/main.py"
PY   = "/opt/fo/venv/bin/python"
MARK = "FO-STEP-SERVER-STORAGE"
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
out = []
def p(*a): out.append(" ".join(str(x) for x in a))

def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return "ОШИБКА: %s" % e

def dsn():
    try:
        env = {}
        for line in io.open("/opt/fo/.env", encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
        return env.get("DATABASE_URL") or env.get("DB_DSN") or env.get("POSTGRES_DSN") or ""
    except Exception:
        return ""

p("== СРОКИ ТОКЕНОВ (разведка) ==")
for _f in ("security.py", "config.py", "deps.py", "routers/auth.py", "main.py"):
    try:
        _src = io.open(APP + "/" + _f, encoding="utf-8").read().splitlines()
        _hits = [ (i+1, l.rstrip()) for i, l in enumerate(_src)
                  if re.search(r"timedelta|TTL|EXPIRE|expire|_MIN\b|_DAYS\b|_HOURS\b|minutes=|days=|hours=", l) ]
        if _hits:
            p(_f + ":")
            for _n, _l in _hits[:12]:
                p("  %4d  %s" % (_n, _l[:140]))
    except Exception:
        pass
p("")
p("== ТОКЕНЫ: ТОЧНЫЕ СТРОКИ ==")
try:
    _c = io.open(APP + "/config.py", encoding="utf-8").read().splitlines()
    for i, l in enumerate(_c):
        if re.search(r"ttl|TTL|expire|days|hours|min", l): p("config.py %3d  %s" % (i+1, l.rstrip()[:140]))
except Exception as e: p("config.py:", e)
try:
    _a = io.open(APP + "/routers/auth.py", encoding="utf-8").read().splitlines()
    for i in list(range(26, 44)) + list(range(100, 118)):
        if i < len(_a): p("auth.py %3d  %s" % (i+1, _a[i].rstrip()[:150]))
except Exception as e: p("auth.py:", e)
p("")
p("== СЕССИЯ: 30 ДНЕЙ (правка 127) ==")
try:
    _cfg = APP + "/config.py"
    _src = io.open(_cfg, encoding="utf-8").read()
    _new = _src
    _new = re.sub(r"(refresh_ttl_days\s*:\s*int\s*=\s*)\d+", r"\g<1>30", _new, count=1)
    _new = re.sub(r"(access_ttl_min\s*:\s*int\s*=\s*)\d+", r"\g<1>120", _new, count=1)
    if _new != _src:
        shutil.copy(_cfg, _cfg + ".bak-" + stamp)
        io.open(_cfg, "w", encoding="utf-8").write(_new)
        p("config.py: refresh_ttl_days -> 30, access_ttl_min -> 120 (копия config.py.bak-" + stamp + ")")
    else:
        p("config.py: уже 30/120 или строки не нашлись - ничего не менял")
    for l in _new.splitlines():
        if "refresh_ttl_days" in l or "access_ttl_min" in l: p("  " + l.strip())
except Exception as e:
    p("config.py не тронут:", e)
p("")
p("== ГЕНЕРАТОР ЗАДАЧ: РАЗВЕДКА ==")
import glob as _glob
for _f in sorted(_glob.glob(APP + "/routers/*.py") + _glob.glob(APP + "/services/*.py")):
    try:
        _src = io.open(_f, encoding="utf-8").read()
    except Exception:
        continue
    if not re.search(r"cabinet_fn|employee_fn|def generate|tasks/generate|day_plan", _src):
        continue
    p("--- " + _f.replace(APP + "/", ""))
    _lines = _src.splitlines()
    for i, l in enumerate(_lines):
        if re.search(r"cabinet_fn|employee_fn|INSERT INTO task|FROM task|def generate|def _gen|unit|cycle_kind|cycle_weekdays|weekday|is_active", l):
            p("%4d  %s" % (i+1, l.rstrip()[:160]))
p("-- колонки cabinet_fn / employee_fn / task --")
for _t in ("cabinet_fn", "employee_fn", "task"):
    p(_t + ": " + sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name||' '||data_type, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='%s'\"" % _t).strip())
p("cabinet_fn строк: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT count(*) FROM cabinet_fn'").strip())
p("employee_fn строк: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT count(*) FROM employee_fn'").strip())
p("")
p("== ГЕНЕРАТОР: ПОЛНЫЙ ТЕКСТ generate_day ==")
try:
    _g = io.open(APP + "/services/generator.py", encoding="utf-8").read().splitlines()
    for i, l in enumerate(_g[:80]):
        p("%3d  %s" % (i+1, l.rstrip()[:170]))
except Exception as e:
    p("generator.py:", e)
p("")
p("== ЧТО НА СЕРВЕРЕ ==")
p("роли:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(code||'/'||level,', ' ORDER BY level) FROM role\"").strip() or "(не прочиталось)")
p("таблицы:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(table_name,', ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public'\"").strip())
p("app_user:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='app_user'\"").strip())

try:
    refs_src = io.open(REFS, encoding="utf-8").read()
    sign_src = io.open(SIGN, encoding="utf-8").read()
except Exception as e:
    p("файлы роутеров не читаются:", e); print("\n".join(out)); sys.exit(1)

m = re.search(r"router\s*=\s*APIRouter\((.*?)\)", refs_src, re.S)
p("refs router:", (m.group(0).replace("\n"," ") if m else "не найден"))
m2 = re.search(r"router\s*=\s*APIRouter\((.*?)\)", sign_src, re.S)
p("signup router:", (m2.group(0).replace("\n"," ") if m2 else "не найден"))

NAME_COL = ""
cols = sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,',') FROM information_schema.columns WHERE table_name='app_user'\"").strip()
have = set(x.strip() for x in cols.split(","))
for cand in ("full_name", "name", "display_name", "first_name"):
    if cand in have: NAME_COL = cand; break
if not NAME_COL: NAME_COL = "display_name"
p("колонка имени:", NAME_COL)

has_title = sh("sudo -u postgres psql -d fo -Atc \"SELECT 1 FROM information_schema.columns WHERE table_name='role' AND column_name='title'\"").strip()
ROLE_TITLE = "title" if has_title.startswith("1") else "code"
p("role.title:", "есть" if ROLE_TITLE == "title" else "нет, беру code")

SQL = """
CREATE TABLE IF NOT EXISTS fo_card (
  kind       text NOT NULL,
  ref_id     text NOT NULL,
  org_id     uuid NOT NULL,
  data       jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, ref_id)
);
CREATE INDEX IF NOT EXISTS fo_card_org_idx ON fo_card (org_id, kind);

CREATE TABLE IF NOT EXISTS fo_task_once (
  id          bigserial PRIMARY KEY,
  org_id      uuid NOT NULL,
  title       text NOT NULL,
  client_id   text,
  employee_id text,
  fn_id       text,
  day         date,
  dow         int,
  minutes     int NOT NULL DEFAULT 30,
  kind        text NOT NULL DEFAULT 'once',
  note        text,
  done_at     timestamptz,
  created_by  uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  removed_at  timestamptz
);
CREATE INDEX IF NOT EXISTS fo_task_once_org_idx ON fo_task_once (org_id, day);

CREATE TABLE IF NOT EXISTS org_invite (
  token      text PRIMARY KEY,
  org_id     uuid NOT NULL,
  role_code  text NOT NULL,
  name       text,
  email      text,
  person_ref text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  used_at    timestamptz,
  used_by    uuid,
  revoked_at timestamptz
);
CREATE INDEX IF NOT EXISTS org_invite_org_idx ON org_invite (org_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fo_cabinet_fn_cfg (
  cabinet_id  uuid NOT NULL,
  fn_id       uuid NOT NULL,
  org_id      uuid NOT NULL,
  employee_id uuid,
  minutes     int,
  cycle_kind  text,
  cycle_n     int,
  cycle_weekdays int[],
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cabinet_id, fn_id));
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

GRANT SELECT, INSERT, UPDATE, DELETE ON fo_card, fo_task_once, org_invite, pwd_code, fo_cabinet_fn_cfg TO fo;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fo;
"""
io.open("/tmp/fo_step.sql", "w", encoding="utf-8").write(SQL)
p("")
p("== МИГРАЦИЯ ==")
p(sh("sudo -u postgres psql -d fo -v ON_ERROR_STOP=1 -f /tmp/fo_step.sql").strip() or "(применилось молча)")

chk = sh("sudo -u postgres psql -d fo -Atc \"SELECT count(*) FROM information_schema.tables WHERE table_name IN ('fo_card','fo_task_once','org_invite','pwd_code')\"").strip()
p("таблиц на месте:", chk, "из 4")
if chk != "4":
    d = dsn()
    if d:
        p("пробую под пользователем приложения")
        code2 = ("import asyncio,asyncpg,io\n"
                 "SQL=io.open('/tmp/fo_step.sql',encoding='utf-8').read()\n"
                 "async def m():\n"
                 "    c=await asyncpg.connect(%r)\n"
                 "    for s in [x.strip() for x in SQL.split(';') if x.strip()]:\n"
                 "        try: await c.execute(s)\n"
                 "        except Exception as e: print('  пропущено:', str(e)[:110])\n"
                 "    await c.close(); print('готово')\n"
                 "asyncio.run(m())\n" % d)
        io.open("/tmp/fo_step2.py", "w", encoding="utf-8").write(code2)
        p(sh("%s /tmp/fo_step2.py" % PY).strip()[:1200])

ADD_REFS = r'''

# ══ FO-STEP-SERVER-STORAGE ═══════════════════════════════════════
# Всё, что человек вносит руками, живёт на сервере. Браузер только
# показывает. Карточки клиента, сотрудника и функции лежат в fo_card
# полями jsonb — состав полей меняется вместе с интерфейсом и не
# требует новой миграции. Разовые задачи — в fo_task_once: в штатном
# API их создать нечем, там задачи рождаются только из функций.
import secrets as _fo_secrets
import json as _fo_json
import importlib as _fo_il
from pydantic import BaseModel as _FoBM

_FO_NAME_COL = "__NAME_COL__"
_FO_KINDS = ("client", "employee", "fn", "org", "cab")


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
    """Уровни доступа как они есть в базе — фронт своих не выдумывает."""
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT code, level, __ROLE_TITLE__ AS rtitle FROM role ORDER BY level")
    return [{"code": r["code"], "level": r["level"], "title": r["rtitle"] or r["code"]} for r in rows]


# ── Карточки: клиент, сотрудник, функция, агентство ──────────────

class FoCardIn(_FoBM):
    kind:   str
    ref_id: str
    data:   dict


@router.get("/cards")
async def fo_cards(kind: str = "", p: Principal = Depends(current)):
    """Все карточки агентства. Без kind — сразу все, одним запросом."""
    async with pool().acquire() as c:
        if kind:
            rows = await c.fetch(
                "SELECT kind, ref_id, data, updated_at FROM fo_card "
                "WHERE org_id=$1 AND kind=$2", p.org_id, kind)
        else:
            rows = await c.fetch(
                "SELECT kind, ref_id, data, updated_at FROM fo_card WHERE org_id=$1", p.org_id)
    out = []
    for r in rows:
        d = r["data"]
        if isinstance(d, str):
            try: d = _fo_json.loads(d)
            except Exception: d = {}
        out.append({"kind": r["kind"], "ref_id": r["ref_id"],
                    "data": d or {}, "updated_at": r["updated_at"]})
    return out


@router.post("/cards")
async def fo_card_save(body: FoCardIn, p: Principal = Depends(current)):
    """Правка карточки. Присланные поля дописываются к тем, что есть."""
    kind = (body.kind or "").strip()
    ref = (body.ref_id or "").strip()
    if kind not in _FO_KINDS:
        raise HTTPException(400, "неизвестный вид карточки")
    if not ref:
        raise HTTPException(400, "не сказано, чья карточка")
    data = body.data if isinstance(body.data, dict) else {}
    async with pool().acquire() as c:
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ($1,$2,$3,$4::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE "
            "SET data = fo_card.data || EXCLUDED.data, updated_at = now() "
            "WHERE fo_card.org_id = EXCLUDED.org_id",
            kind, ref, p.org_id, _fo_json.dumps(data))
        row = await c.fetchrow(
            "SELECT data FROM fo_card WHERE kind=$1 AND ref_id=$2 AND org_id=$3",
            kind, ref, p.org_id)
    d = row["data"] if row else {}
    if isinstance(d, str):
        try: d = _fo_json.loads(d)
        except Exception: d = {}
    return {"ok": True, "kind": kind, "ref_id": ref, "data": d or {}}


# ── Разовые задачи ───────────────────────────────────────────────

class FoOnceIn(_FoBM):
    title:       str
    client_id:   str | None = None
    employee_id: str | None = None
    fn_id:       str | None = None
    day:         str | None = None
    dow:         int | None = None
    minutes:     int | None = 30
    kind:        str | None = "once"
    note:        str | None = None


class FoOncePatch(_FoBM):
    title:       str | None = None
    employee_id: str | None = None
    day:         str | None = None
    dow:         int | None = None
    minutes:     int | None = None
    note:        str | None = None
    done:        bool | None = None


def _fo_once_row(r):
    return {"id": str(r["id"]), "title": r["title"], "client_id": r["client_id"],
            "employee_id": r["employee_id"], "fn_id": r["fn_id"],
            "day": r["day"].isoformat() if r["day"] else None, "dow": r["dow"],
            "minutes": r["minutes"], "kind": r["kind"], "note": r["note"],
            "done": bool(r["done_at"]), "done_at": r["done_at"],
            "created_at": r["created_at"]}


@router.get("/tasks/once")
async def fo_once_list(p: Principal = Depends(current)):
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM fo_task_once WHERE org_id=$1 AND removed_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1000", p.org_id)
    return [_fo_once_row(r) for r in rows]


@router.post("/tasks/once")
async def fo_once_new(body: FoOnceIn, p: Principal = Depends(current)):
    t = (body.title or "").strip()
    if len(t) < 2:
        raise HTTPException(400, "Напишите, что сделать")
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "INSERT INTO fo_task_once (org_id, title, client_id, employee_id, fn_id, "
            "day, dow, minutes, kind, note, created_by) "
            "VALUES ($1,$2,$3,$4,$5,$6::date,$7,$8,$9,$10,$11) RETURNING *",
            p.org_id, t, body.client_id or None, body.employee_id or None,
            body.fn_id or None, body.day or None, body.dow,
            max(1, min(2880, int(body.minutes or 30))), (body.kind or "once"),
            body.note or None, _fo_uid(p))
    return _fo_once_row(r)


def _fo_task_id(v):
    """Номер разовой задачи приходит из адреса строкой. База ждёт число.
    Без этого преобразования драйвер падал с 500 на удалении и правке."""
    try:
        return int(str(v).strip())
    except Exception:
        raise HTTPException(404, "задача не найдена")

@router.post("/tasks/once/{task_id}")
async def fo_once_patch(task_id: str, body: FoOncePatch, p: Principal = Depends(current)):
    sets, vals = [], []
    def add(col, v):
        vals.append(v); sets.append("%s=$%d" % (col, len(vals) + 1))
    if body.title is not None:       add("title", body.title.strip())
    if body.employee_id is not None: add("employee_id", body.employee_id or None)
    if body.day is not None:         sets.append("day=$%d::date" % (len(vals) + 2)); vals.append(body.day or None)
    if body.dow is not None:         add("dow", body.dow)
    if body.minutes is not None:     add("minutes", max(1, min(2880, int(body.minutes))))
    if body.note is not None:        add("note", body.note)
    if body.done is not None:
        sets.append("done_at=" + ("now()" if body.done else "NULL"))
    if not sets:
        return {"ok": True, "changed": 0}
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "UPDATE fo_task_once SET " + ", ".join(sets) +
            " WHERE id=$1 AND org_id=$%d RETURNING *" % (len(vals) + 2),
            _fo_task_id(task_id), *vals, p.org_id)
    if not r:
        raise HTTPException(404, "задача не найдена")
    return _fo_once_row(r)


@router.post("/tasks/once/{task_id}/remove")
async def fo_once_remove(task_id: str, p: Principal = Depends(current)):
    async with pool().acquire() as c:
        await c.execute(
            "UPDATE fo_task_once SET removed_at=now() WHERE id=$1 AND org_id=$2",
            _fo_task_id(task_id), p.org_id)
    return {"ok": True}


# ── удаление клиента вместе с кабинетами ─────────────────────────
# В сервисе не было ни одного способа убрать заведённого клиента:
# DELETE /refs/clients/{id}, /remove и /archive отдавали 404.
# Имя таблицы в разных сборках отличается, поэтому подбираем.

_FO_CLI_T = None
_FO_CAB_T = None


async def _fo_tbl(c, names, need):
    for t in names:
        try:
            r = await c.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name=$1 AND column_name=$2", t, need)
            if r:
                return t
        except Exception:
            pass
    return None


@router.post("/clients/{client_id}/remove")
async def fo_client_remove(client_id: str, p: Principal = Depends(current)):
    """Убрать клиента и его кабинеты. Если мешают связи — прячем в архив."""
    global _FO_CLI_T, _FO_CAB_T
    async with pool().acquire() as c:
        if not _FO_CLI_T:
            _FO_CLI_T = await _fo_tbl(c, ["client", "clients"], "org_id")
        if not _FO_CAB_T:
            _FO_CAB_T = await _fo_tbl(c, ["cabinet", "cabinets"], "client_id")
        if not _FO_CLI_T:
            raise HTTPException(500, "таблица клиентов не найдена")

        row = await c.fetchrow(
            "SELECT id FROM " + _FO_CLI_T + " WHERE id=$1::uuid AND org_id=$2",
            client_id, p.org_id)
        if not row:
            raise HTTPException(404, "клиент не найден")

        how = "удалён"
        try:
            async with c.transaction():
                if _FO_CAB_T:
                    await c.execute(
                        "DELETE FROM " + _FO_CAB_T + " WHERE client_id=$1::uuid",
                        client_id)
                await c.execute(
                    "DELETE FROM " + _FO_CLI_T + " WHERE id=$1::uuid AND org_id=$2",
                    client_id, p.org_id)
        except Exception:
            try:
                await c.execute(
                    "UPDATE " + _FO_CLI_T + " SET status='archived' "
                    "WHERE id=$1::uuid AND org_id=$2", client_id, p.org_id)
                how = "в архиве (есть связанные записи)"
            except Exception:
                raise HTTPException(409, "клиента нельзя убрать: на нём висят задачи")

        try:
            await c.execute(
                "DELETE FROM fo_card WHERE org_id=$1 AND ref_id=$2 "
                "AND kind IN ('client','cab')", p.org_id, str(client_id))
        except Exception:
            pass
        try:
            await c.execute(
                "UPDATE fo_task_once SET removed_at=now() "
                "WHERE org_id=$1 AND client_id=$2", p.org_id, str(client_id))
        except Exception:
            pass
    return {"ok": True, "как": how}


# ── функции кабинета: то, что рождает задачи (С3, С4) ────────────
# Генератор берёт задачи ТОЛЬКО из cabinet_fn (кабинет ↔ функция), а
# эндпоинта для неё в API не было: форма «Задачи кабинета» никуда не
# писала. Здесь: чтение и полная замена набора функций кабинета.
# Проектные настройки (время, цикличность, ответственный) — в
# fo_cabinet_fn_cfg; базовые остаются в fn. Ответственный дублируется
# в employee_fn, чтобы генератор его увидел.

class FoCabFnItem(_FoBM):
    fn_id: str
    employee_id: str | None = None
    minutes: int | None = None
    cycle_kind: str | None = None
    cycle_n: int | None = None
    cycle_weekdays: list[int] | None = None


async def _fo_cab_of(c, cab_id, org_id):
    r = await c.fetchrow(
        "SELECT cb.id, cb.client_id FROM cabinet cb JOIN client cl ON cl.id = cb.client_id "
        "WHERE cb.id=$1::uuid AND cl.org_id=$2", cab_id, org_id)
    if not r:
        raise HTTPException(404, "кабинет не найден")
    return r


@router.get("/cabinets/{cab_id}/functions")
async def fo_cab_fns(cab_id: str, p: Principal = Depends(current)):
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        rows = await c.fetch(
            """SELECT f.id AS fn_id, f.code, f.name, f.block_id, f.norm_minutes,
                      f.cycle_kind AS base_cycle_kind, f.cycle_n AS base_cycle_n,
                      f.cycle_weekdays AS base_cycle_weekdays,
                      g.employee_id, g.minutes, g.cycle_kind, g.cycle_n, g.cycle_weekdays,
                      e.name AS employee_name
                 FROM cabinet_fn cf
                 JOIN fn f ON f.id = cf.fn_id
                 LEFT JOIN fo_cabinet_fn_cfg g ON g.cabinet_id = cf.cabinet_id AND g.fn_id = cf.fn_id
                 LEFT JOIN employee e ON e.id = g.employee_id
                WHERE cf.cabinet_id = $1::uuid
                ORDER BY f.block_id, f.code""", cab_id)
    out = []
    for r in rows:
        d = dict(r)
        for k in ("fn_id", "employee_id"):
            if d.get(k) is not None: d[k] = str(d[k])
        out.append(d)
    return out


@router.put("/cabinets/{cab_id}/functions")
async def fo_cab_fns_put(cab_id: str, body: list[FoCabFnItem], p: Principal = Depends(max_level(4))):
    """Полная замена набора функций кабинета. Уровень: РМ и выше (С5)."""
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        fn_ids = []
        for it in body:
            fid = (it.fn_id or "").strip()
            if not fid: continue
            ok = await c.fetchval("SELECT 1 FROM fn WHERE id=$1::uuid AND org_id=$2", fid, p.org_id)
            if not ok:
                raise HTTPException(400, "функция не из этого агентства: " + fid[:8])
            fn_ids.append(fid)
        async with c.transaction():
            await c.execute("DELETE FROM cabinet_fn WHERE cabinet_id=$1::uuid", cab_id)
            await c.execute("DELETE FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1::uuid", cab_id)
            for it in body:
                fid = (it.fn_id or "").strip()
                if not fid: continue
                await c.execute(
                    "INSERT INTO cabinet_fn (cabinet_id, fn_id, cycle_n) VALUES ($1::uuid, $2::uuid, $3) "
                    "ON CONFLICT DO NOTHING", cab_id, fid, it.cycle_n)
                emp = (it.employee_id or "").strip() or None
                if emp:
                    ok = await c.fetchval("SELECT 1 FROM employee WHERE id=$1::uuid AND org_id=$2", emp, p.org_id)
                    if not ok:
                        raise HTTPException(400, "сотрудник не из этого агентства")
                    # чтобы генератор отдал задачу именно этому человеку
                    await c.execute(
                        "INSERT INTO employee_fn (employee_id, fn_id, allowed) VALUES ($1::uuid, $2::uuid, true) "
                        "ON CONFLICT DO NOTHING", emp, fid)
                await c.execute(
                    """INSERT INTO fo_cabinet_fn_cfg
                         (cabinet_id, fn_id, org_id, employee_id, minutes, cycle_kind, cycle_n, cycle_weekdays)
                       VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5, $6, $7, $8)""",
                    cab_id, fid, p.org_id, emp,
                    (max(1, min(2880, int(it.minutes))) if it.minutes else None),
                    (it.cycle_kind or None), it.cycle_n, it.cycle_weekdays)
    return {"ok": True, "функций": len(fn_ids)}


@router.get("/clients/{client_id}/cabinets")
async def fo_client_cabs(client_id: str, p: Principal = Depends(current)):
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT cb.id, cb.name, cb.client_id FROM cabinet cb JOIN client cl ON cl.id = cb.client_id "
            "WHERE cl.org_id=$1 AND cb.client_id=$2::uuid ORDER BY cb.name", p.org_id, client_id)
    return [{"id": str(r["id"]), "name": r["name"], "client_id": str(r["client_id"])} for r in rows]


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
    return {"id": str(u["id"]), "email": u["email"],
            "name": u["display_name"] or u["base_name"] or "",
            "phone": u["phone"] or "", "role_code": u["role_code"],
            "role_title": u["role_title"] or u["role_code"], "level": u["level"],
            "org_name": u["org_name"], "org_id": str(u["org_id"]),
            "invite_code": u["invite_code"], "created_at": u["created_at"]}


class FoMeIn(_FoBM):
    name:  str | None = None
    phone: str | None = None


@router.post("/me/account")
async def fo_me_save(body: FoMeIn, p: Principal = Depends(current)):
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
        if body.name is not None:
            await _fo_employee_rename(c, uid, (body.name or "").strip())
    return {"ok": True, "changed": len(sets)}


# ── имена людей: везде показываем имя, а не кусок почты (С8) ─────
async def _fo_employee_rename(conn, uid, nm):
    """Имя из аккаунта становится именем сотрудника - его видит вся команда."""
    if not nm:
        return
    for tbl in ("employee", "employees", "staff", "member", "people", "person"):
        try:
            if not await conn.fetchval("SELECT to_regclass($1)", "public." + tbl):
                continue
            cols = set(r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name=$1", tbl))
            if "user_id" not in cols or "name" not in cols:
                continue
            await conn.execute("UPDATE " + tbl + " SET name=$2 WHERE user_id=$1", uid, nm)
            return
        except Exception:
            continue


@router.post("/me/names/sync")
async def fo_names_sync(p: Principal = Depends(max_level(1))):
    """Разово: у всех, кто уже назвал себя, имя сотрудника = имя из аккаунта."""
    n = 0
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT id, display_name FROM app_user "
            "WHERE display_name IS NOT NULL AND length(trim(display_name)) >= 2")
        for r in rows:
            await _fo_employee_rename(c, r["id"], r["display_name"].strip())
            n += 1
    return {"ok": True, "обновлено": n}

@router.post("/me/password/code")
async def fo_pwd_code(p: Principal = Depends(current)):
    uid = _fo_uid(p)
    code = "".join(_fo_secrets.choice("0123456789") for _ in range(6))
    async with pool().acquire() as c:
        email = await c.fetchval("SELECT email FROM app_user WHERE id=$1", uid)
        if not email:
            raise HTTPException(404, "аккаунт не найден")
        await c.execute("UPDATE pwd_code SET used_at=now() WHERE user_id=$1 AND used_at IS NULL", uid)
        await c.execute("INSERT INTO pwd_code (user_id, code) VALUES ($1,$2)", uid, code)
    sent = await _fo_send(email, "Код для смены пароля " + code + " — Flater Team Service",
                          "Код для смены пароля: " + code + "\n\nОн живёт 15 минут.")
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
    import datetime as _dt
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "SELECT id, code, made_at, tries FROM pwd_code "
            "WHERE user_id=$1 AND used_at IS NULL ORDER BY made_at DESC LIMIT 1", uid)
        if not row:
            raise HTTPException(400, "Сначала запросите код")
        if (_dt.datetime.now(_dt.timezone.utc) - row["made_at"]).total_seconds() > 900:
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
        await c.execute(
            "UPDATE org_invite SET revoked_at=now() "
            "WHERE token=$1 AND org_id=$2 AND used_at IS NULL AND revoked_at IS NULL",
            token, p.org_id)
    return {"ok": True}


@router.get("/step")
async def fo_step_report(p: Principal = Depends(max_level(1))):
    try:
        with open("/opt/fo/step-last.txt", encoding="utf-8") as _f:
            return {"ok": True, "text": _f.read()}
    except Exception as e:
        return {"ok": False, "text": "отчёта нет: %s" % e}
'''

ADD_SIGN = r'''

# ══ FO-STEP-SERVER-STORAGE ═══════════════════════════════════════
# Вход по персональному приглашению: уровень доступа выдаёт сервер,
# из самого приглашения. Приглашение одноразовое.
from pydantic import BaseModel as _FoBM2


@router.get("/invite-token/{token}")
async def fo_invite_peek(token: str):
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
    """Кто зашёл по приглашению — сразу виден в команде и в задачах."""
    tbl = None
    for cand in ("employee", "employees", "staff", "member", "people", "person"):
        if await conn.fetchval("SELECT to_regclass($1)", "public." + cand):
            tbl = cand; break
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
        return row["id"]
    names, vals = ["org_id", "name"], [org_id, nm]
    if "user_id" in cols: names.append("user_id"); vals.append(uid)
    if "email" in cols and email: names.append("email"); vals.append(email)
    if "is_active" in cols: names.append("is_active"); vals.append(True)
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
                await conn.execute("UPDATE app_user SET org_id=$2, role_code=$3 WHERE id=$1",
                                   uid, inv["org_id"], inv["role_code"])
            else:
                uid = await _make_user(conn, inv["org_id"], mail, inv["role_code"],
                                       (inv["name"] or mail.split("@")[0]))
            await conn.execute(
                "UPDATE org_invite SET used_at=now(), used_by=$2 WHERE token=$1", tok, uid)
            code2, sent = await _issue_code(conn, uid, mail, "first_login")
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

ADD_REFS = ADD_REFS.replace("__NAME_COL__", NAME_COL).replace("__ROLE_TITLE__", ROLE_TITLE)
ADD_SIGN = ADD_SIGN.replace("__ROLE_TITLE__", ROLE_TITLE)


def cut(src):
    i = src.find("# " + chr(9552) * 2 + " " + MARK)
    if i < 0:
        j = src.find(MARK)
        if j >= 0:
            i = src.rfind("\n", 0, j)
    return src[:i] if i >= 0 else src


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
        p("синтаксис не сошёлся в", f, ":", r.strip()[:600]); ok = False

if ok:
    sh("systemctl restart fo"); sh("sleep 4")
    h = sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip()
    p("health после правки:", h)
    if h != "200" and H0 == "200":
        ok = False

if not ok:
    shutil.copy(bak + "/refs.py", REFS)
    shutil.copy(bak + "/signup.py", SIGN)
    sh("systemctl restart fo"); sh("sleep 3")
    p("ОТКАТ: вернул как было, health=" +
      sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip())
    p(sh("journalctl -u fo -n 30 --no-pager")[-2500:])
else:
    p("")
    p("== ПРОВЕРКА ЭНДПОИНТОВ ==")
    for u in ("/refs/roles", "/refs/cards", "/refs/tasks/once", "/refs/invites",
              "/refs/me/account", "/auth/invite-token/zzz"):
        p("  %-26s %s" % (u, sh("curl -s -o /dev/null -w '%%{http_code}' http://127.0.0.1:8000%s" % u).strip()))
    p("(401/403 — эндпоинт есть и просит вход; 404 — не встал)")
    p("ГОТОВО: хранение переехало на сервер")

print("\n".join(out))
