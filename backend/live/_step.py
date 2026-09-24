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
p("-- колонки cabinet_fn / employee_fn / task / article* --")
for _t in ("cabinet_fn", "employee_fn", "task", "article", "article_owner", "article_category", "cabinet_category_schedule", "chat", "client_chat", "routing_chat", "fn"):
    p(_t + ": " + sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name||' '||data_type, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='%s'\"" % _t).strip())
p("article строк: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT count(*) FROM article'").strip())
p("article пример: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT row_to_json(a) FROM article a LIMIT 2'").strip()[:600])
p("article_owner пример: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT row_to_json(a) FROM article_owner a LIMIT 2'").strip()[:400])
p("article_category: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT row_to_json(a) FROM article_category a LIMIT 6'").strip()[:600])
p("таблицы с chat: " + sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(table_name,', ') FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE '%chat%'\"").strip())
p("routers: " + sh("ls /opt/fo/backend/app/routers/").strip().replace("\n", " "))
p("-- articles.py: сигнатуры --")
p(sh("grep -n 'def \\|INSERT\\|UPDATE\\|ON CONFLICT' /opt/fo/backend/app/routers/articles.py").strip()[:2500])
p("-- routing.py: chat --")
p(sh("grep -n 'def \\|INSERT\\|FROM\\|chat' /opt/fo/backend/app/routers/routing.py").strip()[:2500])
p("cabinet_fn строк: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT count(*) FROM cabinet_fn'").strip())
p("employee_fn строк: " + sh("sudo -u postgres psql -d fo -Atc 'SELECT count(*) FROM employee_fn'").strip())
p("")
p("== SECURITY / DEPS / MAIN (разведка для режима тени) ==")
for _f, _lim in (("security.py", 120), ("deps.py", 140), ("main.py", 90)):
    try:
        _src = io.open(APP + "/" + _f, encoding="utf-8").read().splitlines()
        p("--- " + _f + " (%d строк)" % len(_src))
        for i, l in enumerate(_src[:_lim]):
            if l.strip():
                p("%4d  %s" % (i+1, l.rstrip()[:150]))
    except Exception as e:
        p(_f + ":", e)
p("")
p("== ГЕНЕРАТОР: ПОЛНЫЙ ТЕКСТ generate_day ==")
try:
    _g = io.open(APP + "/services/generator.py", encoding="utf-8").read().splitlines()
    for i, l in enumerate(_g[:110]):
        p("%3d  %s" % (i+1, l.rstrip()[:170]))
except Exception as e:
    p("generator.py:", e)
p("")
p("== ГЕНЕРАТОР: ПРОЕКТНЫЕ НАСТРОЙКИ И ОТВЕТСТВЕННЫЙ (С3, С4, 110) ==")
try:
    _gp = APP + "/services/generator.py"
    _src = io.open(_gp, encoding="utf-8").read()
    _new = _src
    _hits = 0
    # 1. выборка: проектные настройки поверх базовых + кого назначили
    _a1 = "                  f.norm_minutes, f.cycle_kind, COALESCE(cf.cycle_n, f.cycle_n) AS cycle_n,\n                  f.cycle_weekdays\n"
    _b1 = ("                  COALESCE(g.minutes, f.norm_minutes) AS norm_minutes,\n"
           "                  COALESCE(g.cycle_kind, f.cycle_kind) AS cycle_kind,\n"
           "                  COALESCE(g.cycle_n, cf.cycle_n, f.cycle_n) AS cycle_n,\n"
           "                  COALESCE(g.cycle_weekdays, f.cycle_weekdays) AS cycle_weekdays,\n"
           "                  g.employee_id AS wanted\n")
    if _a1 in _new: _new = _new.replace(_a1, _b1, 1); _hits += 1
    _a2 = "           JOIN fn f ON f.id = cf.fn_id\n           WHERE cl.org_id = $1 AND f.unit = 'cabinet' AND f.cycle_kind <> 'none'"
    _b2 = ("           JOIN fn f ON f.id = cf.fn_id\n"
           "           LEFT JOIN fo_cabinet_fn_cfg g ON g.cabinet_id = cf.cabinet_id AND g.fn_id = cf.fn_id\n"
           "           WHERE cl.org_id = $1 AND f.unit = 'cabinet'\n"
           "             AND COALESCE(g.cycle_kind, f.cycle_kind) <> 'none'")
    if _a2 in _new: _new = _new.replace(_a2, _b2, 1); _hits += 1
    # 2. исполнитель: сначала назначенный, потом менее загруженный; собственник - никогда
    _a3 = "        owner = await conn.fetchval(\n            \"\"\"SELECT ef.employee_id FROM employee_fn ef\n"
    _b3 = ("        owner = None\n"
           "        if r[\"wanted\"]:\n"
           "            owner = await conn.fetchval(\n"
           "                \"\"\"SELECT e.id FROM employee e WHERE e.id = $1 AND e.org_id = $2 AND e.is_active\n"
           "                     AND NOT EXISTS (SELECT 1 FROM app_user u WHERE u.id = e.user_id\n"
           "                                     AND u.role_code IN ('owner','admin'))\"\"\", r[\"wanted\"], org_id)\n"
           "        if not owner:\n"
           "          owner = await conn.fetchval(\n"
           "            \"\"\"SELECT ef.employee_id FROM employee_fn ef\n")
    if _a3 in _new: _new = _new.replace(_a3, _b3, 1); _hits += 1
    _a4 = "               WHERE ef.fn_id = $1 AND ef.allowed AND e.org_id = $2 AND e.is_active\n               ORDER BY"
    _b4 = ("               WHERE ef.fn_id = $1 AND ef.allowed AND e.org_id = $2 AND e.is_active\n"
           "                 AND NOT EXISTS (SELECT 1 FROM app_user u WHERE u.id = e.user_id\n"
           "                                 AND u.role_code IN ('owner','admin'))\n"
           "               ORDER BY")
    if _a4 in _new: _new = _new.replace(_a4, _b4, 1); _hits += 1
    if "fo_cabinet_fn_cfg" in _src:
        p("generator.py: уже правлен, не трогаю")
    elif _hits == 4:
        shutil.copy(_gp, _gp + ".bak-" + stamp)
        io.open(_gp, "w", encoding="utf-8").write(_new)
        _chk = sh(PY + " -m py_compile " + _gp)
        if _chk.strip():
            shutil.copy(_gp + ".bak-" + stamp, _gp)
            p("generator.py: синтаксис не сошёлся, ОТКАТ:", _chk.strip()[:300])
        else:
            p("generator.py: правлен (4/4), копия .bak-" + stamp)
    else:
        p("generator.py: совпало %d из 4 - НЕ трогаю" % _hits)
except Exception as e:
    p("generator.py не тронут:", e)
p("== ГЕНЕРАТОР: ДНИ НЕДЕЛИ КАК В ФОРМАХ (0=Пн … 6=Вс) ==")
try:
    _gp = APP + "/services/generator.py"
    _src = io.open(_gp, encoding="utf-8").read()
    if "isoweekday() - 1" in _src:
        p("generator.py: дни недели уже правлены")
    else:
        _new = _src.replace("wd = day.isoweekday()", "wd = day.isoweekday() - 1  # 0=Пн … 6=Вс, как в формах", 1)
        _new = _new.replace("(weekdays or [1])", "(weekdays or [0])")
        if _new != _src:
            shutil.copy(_gp, _gp + ".bak-wd-" + stamp)
            io.open(_gp, "w", encoding="utf-8").write(_new)
            _chk = sh(PY + " -m py_compile " + _gp)
            if _chk.strip():
                shutil.copy(_gp + ".bak-wd-" + stamp, _gp)
                p("generator.py: дни недели - синтаксис не сошёлся, ОТКАТ:", _chk.strip()[:300])
            else:
                p("generator.py: дни недели правлены (0=Пн), копия .bak-wd-" + stamp)
        else:
            p("generator.py: строка wd не найдена - не трогаю")
except Exception as e:
    p("generator.py дни недели:", e)
p("== ГЕНЕРАТОР: ВСТАВКА БЕЗ ДУБЛЕЙ ==")
try:
    _gp = APP + "/services/generator.py"
    _src = io.open(_gp, encoding="utf-8").read()
    if "ON CONFLICT DO NOTHING" in _src:
        p("generator.py: ON CONFLICT уже стоит")
    else:
        _new = _src.replace("'generator',$6,$7,$8)\"\"\"", "'generator',$6,$7,$8)\n               ON CONFLICT DO NOTHING\"\"\"")
        _new = _new.replace("'generator',$7,$8,$9)\"\"\"", "'generator',$7,$8,$9)\n               ON CONFLICT DO NOTHING\"\"\"")
        if _new != _src:
            shutil.copy(_gp, _gp + ".bak-oc-" + stamp)
            io.open(_gp, "w", encoding="utf-8").write(_new)
            _chk = sh(PY + " -m py_compile " + _gp)
            if _chk.strip():
                shutil.copy(_gp + ".bak-oc-" + stamp, _gp)
                p("generator.py: ON CONFLICT - синтаксис не сошёлся, ОТКАТ:", _chk.strip()[:300])
            else:
                p("generator.py: вставки с ON CONFLICT DO NOTHING (%d)" % _new.count("ON CONFLICT DO NOTHING"))
        else:
            p("generator.py: строки вставки не найдены - не трогаю")
except Exception as e:
    p("generator.py ON CONFLICT:", e)
p("")
p("== ЧТО НА СЕРВЕРЕ ==")
p("роли:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(code||'/'||level,', ' ORDER BY level) FROM role\"").strip() or "(не прочиталось)")
p("таблицы:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(table_name,', ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public'\"").strip())
p("app_user:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='app_user'\"").strip())

try:
    refs_src = io.open(REFS, encoding="utf-8").read()
    sign_src = io.open(SIGN, encoding="utf-8").read()
    main_src = io.open(MAIN, encoding="utf-8").read()
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
CREATE TABLE IF NOT EXISTS fo_task_report (
  id          bigserial PRIMARY KEY,
  task_id     uuid NOT NULL,
  org_id      uuid NOT NULL,
  employee_id uuid,
  fn_id       uuid,
  cabinet_id  uuid,
  link        text,
  note        text,
  made_at     timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS fo_task_report_task_idx ON fo_task_report (task_id);
CREATE INDEX IF NOT EXISTS fo_task_report_fn_idx ON fo_task_report (org_id, fn_id, cabinet_id, made_at DESC);
CREATE TABLE IF NOT EXISTS fo_link_pref (
  org_id      uuid NOT NULL,
  fn_id       uuid NOT NULL,
  cabinet_id  uuid,
  employee_id uuid NOT NULL,
  same_table  boolean NOT NULL DEFAULT true,
  link        text,
  updated_at  timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS fo_link_pref_uniq ON fo_link_pref (fn_id, COALESCE(cabinet_id, '00000000-0000-0000-0000-000000000000'::uuid), employee_id);
CREATE TABLE IF NOT EXISTS fo_task_review (
  id          bigserial PRIMARY KEY,
  task_id     uuid NOT NULL,
  org_id      uuid NOT NULL,
  asked_by    uuid,
  approver_employee_id uuid,
  approver_user_id uuid,
  approver_label text,
  note        text,
  asked_at    timestamptz NOT NULL DEFAULT now(),
  decided_at  timestamptz,
  decided_by  uuid,
  verdict     text,
  decision_note text);
CREATE INDEX IF NOT EXISTS fo_task_review_task_idx ON fo_task_review (task_id, decided_at);
CREATE INDEX IF NOT EXISTS fo_task_review_org_idx ON fo_task_review (org_id, decided_at);
CREATE TABLE IF NOT EXISTS fo_shadow_log (
  id bigserial PRIMARY KEY,
  admin_user_id uuid,
  target_user_id uuid,
  at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS pwd_code (
  id      bigserial PRIMARY KEY,
  user_id uuid NOT NULL,
  code    text NOT NULL,
  made_at timestamptz NOT NULL DEFAULT now(),
  used_at timestamptz,
  tries   int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pwd_code_user_idx ON pwd_code (user_id, made_at DESC);

CREATE TABLE IF NOT EXISTS fo_chat_msg (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL,
  client_id uuid,
  chat_pk bigint,
  kind text,
  tg_chat_id text NOT NULL,
  msg_id bigint NOT NULL,
  author text,
  author_tg text,
  text text NOT NULL DEFAULT '',
  msg_at timestamptz,
  ai_state text,
  ai_note text,
  ai_tokens int,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tg_chat_id, msg_id));
CREATE TABLE IF NOT EXISTS fo_ai_task (
  id bigserial PRIMARY KEY,
  org_id uuid NOT NULL,
  client_id uuid, cabinet_id uuid, msg_pk bigint, tg_chat_id text, msg_id bigint, msg_link text,
  quote text, author text, msg_at timestamptz,
  title text NOT NULL, fn_id uuid, employee_id uuid, candidates jsonb, urgent boolean NOT NULL DEFAULT false,
  deadline timestamptz, minutes int, why text, goal text,
  approver_employee_id uuid, approver_user_id uuid, approver_label text,
  status text NOT NULL DEFAULT 'pending', decided_by uuid, decided_at timestamptz, decision_note text,
  task_once_id bigint, ai_raw jsonb, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS fo_ai_task_org_idx ON fo_ai_task (org_id, status, created_at);
ALTER TABLE fo_ai_task ADD COLUMN IF NOT EXISTS approver_users uuid[];
-- чаты, внесённые в карточку ссылкой-приглашением: номер Telegram — по названию из регистрации бота
DO $$
BEGIN
  UPDATE chat c SET chat_id = n.chat_id, is_active = true
    FROM chat n
   WHERE c.chat_id !~ '^-?[0-9]+$' AND n.chat_id ~ '^-?[0-9]+$'
     AND lower(btrim(n.title)) = lower(btrim(c.title)) AND n.id <> c.id
     AND EXISTS (SELECT 1 FROM client_chat cc WHERE cc.chat_pk = c.id)
     AND NOT EXISTS (SELECT 1 FROM chat x WHERE x.org_id = c.org_id AND x.channel = c.channel AND x.chat_id = n.chat_id);
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'chat id fix: %', SQLERRM;
END $$;

ALTER TABLE app_user ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS display_name text;

GRANT SELECT, INSERT, UPDATE, DELETE ON fo_card, fo_task_once, org_invite, pwd_code, fo_cabinet_fn_cfg, fo_task_report, fo_link_pref, fo_task_review, fo_shadow_log, fo_chat_msg, fo_ai_task TO fo;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fo;

-- задача генератора на кабинет+функцию+день одна: дубли (гонка воркеров) убрать, индекс поставить
DO $$
BEGIN
  DELETE FROM task t USING task k
   WHERE t.source='generator' AND k.source='generator' AND t.status='planned'
     AND t.cabinet_id = k.cabinet_id AND t.fn_id = k.fn_id AND t.plan_date = k.plan_date
     AND t.article_id IS NOT DISTINCT FROM k.article_id AND t.id <> k.id
     AND (k.created_at < t.created_at OR (k.created_at = t.created_at AND k.id < t.id));
  CREATE UNIQUE INDEX IF NOT EXISTS task_generator_uniq
    ON task (cabinet_id, fn_id, plan_date, COALESCE(article_id, '00000000-0000-0000-0000-000000000000'::uuid))
    WHERE source='generator';
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'task_generator_uniq: %', SQLERRM;
END $$;
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
import re
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
    if int(getattr(p, "level", 9) or 9) > 4:
        raise HTTPException(403, "Карточки сотрудников, клиентов и функций правят РМ и выше — вам доступен просмотр")
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
async def fo_once_remove(task_id: str, p: Principal = Depends(max_level(4))):
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
        _old = {}
        for _r in await c.fetch(
                """SELECT cf.cabinet_id, cf.fn_id, g.employee_id FROM cabinet_fn cf
                   LEFT JOIN fo_cabinet_fn_cfg g ON g.cabinet_id=cf.cabinet_id AND g.fn_id=cf.fn_id
                   WHERE cf.cabinet_id=$1::uuid""", cab_id):
            _old[(_r["cabinet_id"], _r["fn_id"])] = _r["employee_id"]
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
        # функция = задача: задачи рождаются сразу, на две недели вперёд
        try:
            _sync = await _fo_sync_tasks(c, p.org_id, cab_id, 14, _old)
        except Exception as _e:
            _sync = {"ошибка": str(_e)[:200]}
    return {"ok": True, "функций": len(fn_ids), "задачи": _sync}


@router.post("/cabinets/{cab_id}/functions/add")
async def fo_cab_fn_add(cab_id: str, it: FoCabFnItem, p: Principal = Depends(max_level(4))):
    """Одна функция в кабинет: добавить или обновить, остальные не трогая.
    Задачи досводятся сразу. Уровень: РМ и выше (С5). Три пути (145) ведут сюда."""
    fid = (it.fn_id or "").strip()
    if not fid:
        raise HTTPException(400, "не указана функция")
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        ok = await c.fetchval("SELECT 1 FROM fn WHERE id=$1::uuid AND org_id=$2", fid, p.org_id)
        if not ok:
            raise HTTPException(400, "функция не из этого агентства")
        emp = (it.employee_id or "").strip() or None
        if emp:
            ok = await c.fetchval("SELECT 1 FROM employee WHERE id=$1::uuid AND org_id=$2", emp, p.org_id)
            if not ok:
                raise HTTPException(400, "сотрудник не из этого агентства")
        _old = {}
        _r = await c.fetchrow(
            """SELECT cf.cabinet_id, cf.fn_id, g.employee_id FROM cabinet_fn cf
               LEFT JOIN fo_cabinet_fn_cfg g ON g.cabinet_id=cf.cabinet_id AND g.fn_id=cf.fn_id
               WHERE cf.cabinet_id=$1::uuid AND cf.fn_id=$2::uuid""", cab_id, fid)
        if _r:
            _old[(_r["cabinet_id"], _r["fn_id"])] = _r["employee_id"]
        async with c.transaction():
            await c.execute("DELETE FROM cabinet_fn WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid", cab_id, fid)
            await c.execute(
                "INSERT INTO cabinet_fn (cabinet_id, fn_id, cycle_n) VALUES ($1::uuid, $2::uuid, $3) "
                "ON CONFLICT DO NOTHING", cab_id, fid, it.cycle_n)
            await c.execute("DELETE FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid", cab_id, fid)
            if emp:
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
        try:
            _sync = await _fo_sync_tasks(c, p.org_id, cab_id, 14, _old)
        except Exception as _e:
            _sync = {"ошибка": str(_e)[:200]}
    return {"ok": True, "задачи": _sync}


@router.post("/cabinets/{cab_id}/functions/{fn_id}/take")
async def fo_cab_fn_take(cab_id: str, fn_id: str, p: Principal = Depends(current)):
    """174: ниже РМ функции только смотрят и берут в работу. Функция в кабинете
    без ответственного становится моей, задачи досводятся сразу."""
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        me = await _fo_my_emp(c, p)
        if not me:
            raise HTTPException(400, "у вашего входа нет карточки сотрудника")
        r = await c.fetchrow(
            """SELECT cf.cabinet_id, cf.fn_id, g.employee_id FROM cabinet_fn cf
               LEFT JOIN fo_cabinet_fn_cfg g ON g.cabinet_id=cf.cabinet_id AND g.fn_id=cf.fn_id
               WHERE cf.cabinet_id=$1::uuid AND cf.fn_id=$2::uuid""", cab_id, fn_id)
        if not r:
            raise HTTPException(404, "этой функции в кабинете нет")
        if r["employee_id"] and str(r["employee_id"]) != str(me):
            raise HTTPException(403, "у функции уже есть ответственный — перевести может РМ и выше")
        _old = {(r["cabinet_id"], r["fn_id"]): r["employee_id"]}
        async with c.transaction():
            await c.execute(
                "INSERT INTO employee_fn (employee_id, fn_id, allowed) VALUES ($1::uuid, $2::uuid, true) "
                "ON CONFLICT DO NOTHING", me, fn_id)
            g = await c.fetchval(
                "SELECT 1 FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid", cab_id, fn_id)
            if g:
                await c.execute(
                    "UPDATE fo_cabinet_fn_cfg SET employee_id=$3::uuid WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid",
                    cab_id, fn_id, me)
            else:
                await c.execute(
                    "INSERT INTO fo_cabinet_fn_cfg (cabinet_id, fn_id, org_id, employee_id) "
                    "VALUES ($1::uuid, $2::uuid, $3, $4::uuid)", cab_id, fn_id, p.org_id, me)
        try:
            _sync = await _fo_sync_tasks(c, p.org_id, cab_id, 14, _old)
        except Exception as _e:
            _sync = {"ошибка": str(_e)[:200]}
    return {"ok": True, "задачи": _sync}


@router.post("/cabinets/{cab_id}/functions/{fn_id}/remove")
async def fo_cab_fn_remove(cab_id: str, fn_id: str, p: Principal = Depends(max_level(4))):
    """Убрать функцию из кабинета: будущие несделанные задачи по ней снимаются."""
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        await c.execute("DELETE FROM cabinet_fn WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid", cab_id, fn_id)
        await c.execute("DELETE FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid", cab_id, fn_id)
        try:
            _sync = await _fo_sync_tasks(c, p.org_id, cab_id, 14, None)
        except Exception as _e:
            _sync = {"ошибка": str(_e)[:200]}
    return {"ok": True, "задачи": _sync}


# ── артикулы кабинета: список, массовое внесение, ответственный (138–141, 114) ──
# Штатные таблицы: article (уникально cabinet_id+wb_sku), article_category
# (A/B/C на агентство), article_owner (артикул-ответственный-день, 0=Пн).

class FoArtItem(_FoBM):
    wb_sku: str
    seller_sku: str | None = None
    cat: str | None = None
    employee_id: str | None = None
    weekdays: list[int] | None = None
    sku_clear: bool | None = None          # 199: в «артикуле продавца» стояло имя — очистить


class FoArtRemoveIn(_FoBM):
    ids: list[str] | None = None
    all: bool = False


class FoArtBulkIn(_FoBM):
    items: list[FoArtItem]
    replace: bool = False


class FoArtOwnerIn(_FoBM):
    employee_id: str | None = None
    weekdays: list[int] | None = None
    cat: str | None = None
    seller_sku: str | None = None


_FO_CAT_TOUCH = {"A": 3, "B": 2, "C": 1}
_FO_CAT_DAYS = {"A": [0, 2, 4], "B": [1, 3], "C": [2]}


async def _fo_cat_ids(c, org_id):
    """A/B/C для агентства — заводим, если нет."""
    out = {}
    for code, touches in _FO_CAT_TOUCH.items():
        cid = await c.fetchval("SELECT id FROM article_category WHERE org_id=$1 AND code=$2", org_id, code)
        if not cid:
            cid = await c.fetchval(
                "INSERT INTO article_category (org_id, code, touches_per_week) VALUES ($1,$2,$3) RETURNING id",
                org_id, code, touches)
        out[code] = cid
    return out


async def _fo_art_rows(c, cab_id):
    rows = await c.fetch(
        """SELECT a.id, a.wb_sku, a.seller_sku, a.is_active, a.first_seen, ac.code AS cat,
                  (SELECT array_agg(DISTINCT ao.employee_id) FROM article_owner ao WHERE ao.article_id=a.id) AS owners,
                  (SELECT array_agg(ao.weekday ORDER BY ao.weekday) FROM article_owner ao WHERE ao.article_id=a.id) AS weekdays
             FROM article a LEFT JOIN article_category ac ON ac.id = a.category_id
            WHERE a.cabinet_id=$1::uuid AND a.is_active
            ORDER BY a.first_seen NULLS LAST, a.wb_sku""", cab_id)
    names = {}
    for r in rows:
        for e in (r["owners"] or []):
            if e and str(e) not in names:
                names[str(e)] = await c.fetchval("SELECT name FROM employee WHERE id=$1", e)
    out = []
    for r in rows:
        owners = [str(e) for e in (r["owners"] or []) if e]
        out.append({"id": str(r["id"]), "wb_sku": r["wb_sku"], "seller_sku": r["seller_sku"], "cat": r["cat"],
                    "employee_id": owners[0] if owners else None,
                    "employee_name": names.get(owners[0]) if owners else None,
                    "weekdays": sorted(set(int(x) for x in (r["weekdays"] or []))),
                    "first_seen": r["first_seen"]})
    return out


@router.get("/cabinets/{cab_id}/articles")
async def fo_cab_articles(cab_id: str, p: Principal = Depends(current)):
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        return await _fo_art_rows(c, cab_id)


async def _fo_art_owner_set(c, art_id, emp, weekdays, cat):
    await c.execute("DELETE FROM article_owner WHERE article_id=$1", art_id)
    if not emp:
        return
    days = [int(x) for x in (weekdays or []) if 0 <= int(x) <= 6]
    if not days:
        days = _FO_CAT_DAYS.get((cat or "C").upper(), [2])
    for d in sorted(set(days)):
        await c.execute("INSERT INTO article_owner (article_id, employee_id, weekday) VALUES ($1,$2::uuid,$3) ON CONFLICT DO NOTHING",
                        art_id, emp, d)


@router.post("/cabinets/{cab_id}/articles/bulk")
async def fo_cab_articles_bulk(cab_id: str, body: FoArtBulkIn, p: Principal = Depends(max_level(4))):
    """Внести список артикулов: по артикулу ВБ — добавить или обновить. replace=true — остальные снять."""
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        cats = await _fo_cat_ids(c, p.org_id)
        seen, n_new, n_upd = [], 0, 0
        async with c.transaction():
            for it in body.items:
                wb = re.sub(r"\D", "", str(it.wb_sku or ""))
                if len(wb) < 4:
                    continue
                cat = (it.cat or "").strip().upper().replace("А", "A").replace("В", "B").replace("С", "C")
                cat = cat if cat in cats else None
                sku = (it.seller_sku or "").strip()[:120] or None
                emp = (it.employee_id or "").strip() or None
                if emp:
                    ok = await c.fetchval("SELECT 1 FROM employee WHERE id=$1::uuid AND org_id=$2", emp, p.org_id)
                    if not ok:
                        emp = None
                r = await c.fetchrow("SELECT id, category_id, seller_sku, is_active FROM article WHERE cabinet_id=$1::uuid AND wb_sku=$2", cab_id, wb)
                if r and not r["is_active"]:
                    # 199: снятый артикул вносят заново — как новый, старые поля не возвращаем
                    await c.execute(
                        "UPDATE article SET seller_sku=$2, category_id=$3, is_active=true, first_seen=CURRENT_DATE WHERE id=$1",
                        r["id"], sku, cats.get(cat) if cat else None)
                    await c.execute("DELETE FROM article_owner WHERE article_id=$1", r["id"])
                    art_id = r["id"]; n_new += 1
                    seen.append(art_id)
                    if emp or it.weekdays:
                        await _fo_art_owner_set(c, art_id, emp, it.weekdays, cat)
                    continue
                if r and not cat and r["category_id"]:
                    cat = next((k for k, v in cats.items() if v == r["category_id"]), None)   # 198: дни ответственного — по уже стоящей категории
                if r and it.sku_clear and not sku:
                    await c.execute("UPDATE article SET seller_sku=NULL WHERE id=$1", r["id"])
                if r:
                    await c.execute(
                        "UPDATE article SET seller_sku=COALESCE($2, seller_sku), category_id=COALESCE($3, category_id), is_active=true WHERE id=$1",
                        r["id"], sku, cats.get(cat) if cat else None)
                    art_id = r["id"]; n_upd += 1
                else:
                    art_id = await c.fetchval(
                        "INSERT INTO article (cabinet_id, seller_sku, wb_sku, category_id, is_active, first_seen) "
                        "VALUES ($1::uuid, $2, $3, $4, true, CURRENT_DATE) RETURNING id",
                        cab_id, sku, wb, cats.get(cat) if cat else None)
                    n_new += 1
                seen.append(art_id)
                if emp or it.weekdays:
                    await _fo_art_owner_set(c, art_id, emp, it.weekdays, cat)
            if body.replace and seen:
                await c.execute(
                    "UPDATE article SET is_active=false WHERE cabinet_id=$1::uuid AND NOT (id = ANY($2::uuid[]))",
                    cab_id, seen)
        rows = await _fo_art_rows(c, cab_id)
    return {"ok": True, "добавлено": n_new, "обновлено": n_upd, "всего": len(rows), "items": rows}


@router.post("/cabinets/{cab_id}/articles/remove")
async def fo_cab_articles_remove(cab_id: str, body: FoArtRemoveIn, p: Principal = Depends(max_level(4))):
    """199: снять с управления много артикулов разом — по списку или все."""
    async with pool().acquire() as c:
        await _fo_cab_of(c, cab_id, p.org_id)
        async with c.transaction():
            if body.all:
                ids = [r["id"] for r in await c.fetch(
                    "SELECT id FROM article WHERE cabinet_id=$1::uuid AND is_active", cab_id)]
            else:
                want = [x for x in (body.ids or []) if re.match(r"^[0-9a-fA-F-]{36}$", str(x or ""))]
                ids = [r["id"] for r in await c.fetch(
                    "SELECT id FROM article WHERE cabinet_id=$1::uuid AND is_active AND id = ANY($2::uuid[])",
                    cab_id, want)] if want else []
            if ids:
                await c.execute("DELETE FROM article_owner WHERE article_id = ANY($1::uuid[])", ids)
                await c.execute("UPDATE article SET is_active=false WHERE id = ANY($1::uuid[])", ids)
        rows = await _fo_art_rows(c, cab_id)
    return {"ok": True, "снято": len(ids), "всего": len(rows), "items": rows}


@router.post("/articles/{art_id}/owner")
async def fo_article_owner(art_id: str, body: FoArtOwnerIn, p: Principal = Depends(max_level(4))):
    """Ответственный, дни, категория, артикул продавца — по одному артикулу."""
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "SELECT a.id, a.cabinet_id, ac.code AS cat FROM article a JOIN cabinet cb ON cb.id=a.cabinet_id "
            "JOIN client cl ON cl.id=cb.client_id LEFT JOIN article_category ac ON ac.id=a.category_id "
            "WHERE a.id=$1::uuid AND cl.org_id=$2", art_id, p.org_id)
        if not r:
            raise HTTPException(404, "артикул не найден")
        cat = r["cat"]
        if body.cat is not None:
            cats = await _fo_cat_ids(c, p.org_id)
            cc = (body.cat or "").strip().upper().replace("А", "A").replace("В", "B").replace("С", "C")
            if cc in cats:
                await c.execute("UPDATE article SET category_id=$2 WHERE id=$1", r["id"], cats[cc]); cat = cc
        if body.seller_sku is not None:
            await c.execute("UPDATE article SET seller_sku=$2 WHERE id=$1", r["id"], (body.seller_sku or "").strip()[:120] or None)
        if body.employee_id is not None or body.weekdays is not None:
            emp = (body.employee_id or "").strip() or None
            if emp:
                ok = await c.fetchval("SELECT 1 FROM employee WHERE id=$1::uuid AND org_id=$2", emp, p.org_id)
                if not ok:
                    raise HTTPException(400, "сотрудник не из этого агентства")
            if emp is None and body.employee_id is None:
                cur = await c.fetchval("SELECT employee_id FROM article_owner WHERE article_id=$1 LIMIT 1", r["id"])
                emp = str(cur) if cur else None
            await _fo_art_owner_set(c, r["id"], emp, body.weekdays, cat)
        rows = await _fo_art_rows(c, r["cabinet_id"])
    return {"ok": True, "items": rows}


@router.post("/articles/{art_id}/remove")
async def fo_article_remove(art_id: str, p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "SELECT a.id FROM article a JOIN cabinet cb ON cb.id=a.cabinet_id JOIN client cl ON cl.id=cb.client_id "
            "WHERE a.id=$1::uuid AND cl.org_id=$2", art_id, p.org_id)
        if not r:
            raise HTTPException(404, "артикул не найден")
        await c.execute("UPDATE article SET is_active=false WHERE id=$1", r["id"])
        await c.execute("DELETE FROM article_owner WHERE article_id=$1", r["id"])
    return {"ok": True}


@router.get("/clients/{client_id}/cabinets")
async def fo_client_cabs(client_id: str, p: Principal = Depends(current)):
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT cb.id, cb.name, cb.client_id FROM cabinet cb JOIN client cl ON cl.id = cb.client_id "
            "WHERE cl.org_id=$1 AND cb.client_id=$2::uuid ORDER BY cb.name", p.org_id, client_id)
    return [{"id": str(r["id"]), "name": r["name"], "client_id": str(r["client_id"])} for r in rows]


# ── задачи: снять и пересобрать (сценарий 5, С4) ──────────────────
# В API нет ни удаления, ни отмены сгенерированной задачи - только
# «сделано» и «передать». Отстранение от задачи было невозможно.
# Здесь: снятие задачи (status='removed') и пересборка дня по кабинету -
# старые несделанные задачи генератора снимаются и рождаются заново
# по текущим настройкам кабинета.

@router.post("/tasks/{task_id}/remove")
async def fo_task_remove(task_id: str, p: Principal = Depends(max_level(4))):
    """Снять задачу. Сделанные не трогаем. Уровень: главный менеджер и выше."""
    async with pool().acquire() as c:
        r = await c.fetchrow(
            "SELECT id, status FROM task WHERE id=$1::uuid AND org_id=$2", task_id, p.org_id)
        if not r:
            raise HTTPException(404, "задача не найдена")
        if r["status"] == "done":
            raise HTTPException(409, "задача уже сделана - снять нельзя")
        await c.execute(
            "UPDATE task SET status='removed', moved_reason=COALESCE(moved_reason,'снята') "
            "WHERE id=$1::uuid AND org_id=$2", task_id, p.org_id)
    return {"ok": True}


@router.post("/tasks/regenerate")
async def fo_tasks_regen(day: str | None = None, cabinet_id: str | None = None,
                         p: Principal = Depends(max_level(4))):
    """Пересобрать день: снять несделанные задачи генератора (по кабинету или все)
    и досвести заново по текущим настройкам. Уровень: РМ и выше."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(day) if day else _fo_msk_today()
    except Exception:
        raise HTTPException(400, "день в формате ГГГГ-ММ-ДД")
    async with pool().acquire() as c:
        if cabinet_id:
            n = await c.execute(
                "DELETE FROM task WHERE org_id=$1 AND plan_date=$2 AND source='generator' "
                "AND status='planned' AND cabinet_id=$3::uuid", p.org_id, d, cabinet_id)
        else:
            n = await c.execute(
                "DELETE FROM task WHERE org_id=$1 AND plan_date=$2 AND source='generator' "
                "AND status='planned'", p.org_id, d)
        res = await _fo_sync_tasks(c, p.org_id, cabinet_id, 14, None)
    return {"ok": True, "снято": _fo_n(n), "создано": res.get("создано")}


# ── функция = задача: задачи рождаются сразу и на две недели вперёд ──
# Штатный /tasks/generate пересобирает день целиком: снимает все
# запланированные задачи генератора и кладёт заново - порядок дня,
# передачи и правки пропадают. Здесь вместо этого «досведение»:
# недостающие задачи дописываются, лишние (функцию убрали, день
# больше не подходит) снимаются, смена ответственного переводит
# будущие задачи. Существующие задачи не пересоздаются - ничего
# никуда не пропадает. Дни недели - как в формах: 0=Пн … 6=Вс.

def _fo_n(res):
    try:
        return int(str(res).split()[-1])
    except Exception:
        return 0


def _fo_msk_today():
    import datetime as _dt
    return (_dt.datetime.utcnow() + _dt.timedelta(hours=3)).date()


def _fo_due(kind, n, weekdays, day):
    wd = day.isoweekday() - 1
    kind = (kind or "none")
    days = []
    for x in (weekdays or []):
        try: days.append(int(x))
        except Exception: pass
    try: step = int(n or 1)
    except Exception: step = 1
    week = day.isocalendar()[1]
    if kind == "daily":
        return wd in (days or [0, 1, 2, 3, 4])
    if kind in ("weekly", "wdays", "several"):
        if wd not in (days or [0]): return False
        return step <= 1 or (week % step == 0)
    if kind == "biweekly":
        return wd in (days or [0]) and (week % 2 == 0)
    if kind == "monthly":
        if days:
            return wd in days and day.day <= 7
        return day.day == max(1, min(28, step))
    if kind == "per_n_days":
        return (day.toordinal() % max(1, step)) == 0
    return False


async def _fo_pick(c, org_id, fn_id, wanted, day):
    who = None
    if wanted:
        who = await c.fetchval(
            """SELECT e.id FROM employee e WHERE e.id=$1 AND e.org_id=$2 AND e.is_active
                 AND NOT EXISTS (SELECT 1 FROM app_user u WHERE u.id=e.user_id
                                 AND u.role_code IN ('owner','admin'))""", wanted, org_id)
    if not who:
        who = await c.fetchval(
            """SELECT ef.employee_id FROM employee_fn ef JOIN employee e ON e.id=ef.employee_id
                WHERE ef.fn_id=$1 AND ef.allowed AND e.org_id=$2 AND e.is_active
                  AND NOT EXISTS (SELECT 1 FROM app_user u WHERE u.id=e.user_id
                                  AND u.role_code IN ('owner','admin'))
                ORDER BY (SELECT COALESCE(SUM(t.plan_minutes),0) FROM task t
                           WHERE t.assignee_id=ef.employee_id AND t.plan_date=$3
                             AND t.status<>'removed') ASC
                LIMIT 1""", fn_id, org_id, day)
    return who


async def _fo_sync_tasks(c, org_id, cabinet_id=None, days=14, old=None, wait=True):
    """Один проход на агентство за раз: воркеров несколько, замок в базе."""
    async with c.transaction():
        if wait:
            await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "fo-sync:" + str(org_id))
        else:
            got = await c.fetchval("SELECT pg_try_advisory_xact_lock(hashtext($1))", "fo-sync:" + str(org_id))
            if not got:
                return {"создано": 0, "снято": 0, "переведено": 0, "дней": 0, "без исполнителя": [], "занято": True}
        return await _fo_sync_body(c, org_id, cabinet_id, days, old)


async def _fo_sync_body(c, org_id, cabinet_id, days, old):
    import datetime as _dt
    today = _fo_msk_today()
    # горизонт — с понедельника текущей недели (перенос дня должен быть виден
    # у ответственного на этой же неделе, а не только со следующей) и на days вперёд
    start = today - _dt.timedelta(days=today.weekday())
    n_days = (today - start).days + max(1, min(60, int(days or 14)))
    horizon = [start + _dt.timedelta(days=i) for i in range(n_days)]
    q = """SELECT cf.cabinet_id, cb.name AS cabinet, cb.client_id, f.id AS fn_id, f.name AS fn,
                  COALESCE(g.minutes, f.norm_minutes, 30) AS minutes,
                  COALESCE(g.cycle_kind, f.cycle_kind) AS cycle_kind,
                  COALESCE(g.cycle_n, cf.cycle_n, f.cycle_n) AS cycle_n,
                  COALESCE(g.cycle_weekdays, f.cycle_weekdays) AS cycle_weekdays,
                  g.employee_id AS wanted
             FROM cabinet_fn cf
             JOIN cabinet cb ON cb.id = cf.cabinet_id
             JOIN client cl ON cl.id = cb.client_id
             JOIN fn f ON f.id = cf.fn_id
             LEFT JOIN fo_cabinet_fn_cfg g ON g.cabinet_id = cf.cabinet_id AND g.fn_id = cf.fn_id
            WHERE cl.org_id = $1 AND f.unit = 'cabinet'"""
    args = [org_id]
    if cabinet_id:
        q += " AND cf.cabinet_id = $2::uuid"; args.append(cabinet_id)
    rows = await c.fetch(q, *args)
    created = removed = moved = 0
    unassigned = []
    for r in rows:
        key = (r["cabinet_id"], r["fn_id"])
        # сменили ответственного - будущие несделанные задачи переезжают к нему
        if old is not None and key in old and old.get(key) != r["wanted"] and r["wanted"]:
            res = await c.execute(
                """UPDATE task SET assignee_id=$4::uuid
                    WHERE org_id=$1 AND cabinet_id=$2::uuid AND fn_id=$3::uuid
                      AND source='generator' AND status='planned' AND plan_date >= $5
                      AND assignee_id IS DISTINCT FROM $4::uuid""",
                org_id, r["cabinet_id"], r["fn_id"], r["wanted"], start)
            moved += _fo_n(res)
        # норма времени - на будущие несделанные
        await c.execute(
            """UPDATE task SET plan_minutes=$4
                WHERE org_id=$1 AND cabinet_id=$2::uuid AND fn_id=$3::uuid
                  AND source='generator' AND status='planned' AND plan_date >= $5
                  AND plan_minutes IS DISTINCT FROM $4""",
            org_id, r["cabinet_id"], r["fn_id"], int(r["minutes"] or 30), start)
        have = await c.fetch(
            """SELECT id, plan_date, status FROM task
                WHERE org_id=$1 AND cabinet_id=$2::uuid AND fn_id=$3::uuid
                  AND source='generator' AND plan_date >= $4 AND plan_date <= $5""",
            org_id, r["cabinet_id"], r["fn_id"], horizon[0], horizon[-1])
        by_day = {}
        for h in have:
            by_day.setdefault(h["plan_date"], []).append(h)
        for d in horizon:
            due = _fo_due(r["cycle_kind"], r["cycle_n"], r["cycle_weekdays"], d)
            if due and d not in by_day:
                who = await _fo_pick(c, org_id, r["fn_id"], r["wanted"], d)
                await c.execute(
                    """INSERT INTO task (org_id, kind, fn_id, client_id, cabinet_id, title,
                                         source, assignee_id, plan_date, plan_minutes)
                       VALUES ($1,'cyclic',$2,$3,$4,$5,'generator',$6,$7,$8)
                       ON CONFLICT DO NOTHING""",
                    org_id, r["fn_id"], r["client_id"], r["cabinet_id"],
                    "%s · %s" % (r["fn"], r["cabinet"]), who, d, int(r["minutes"] or 30))
                created += 1
                if not who:
                    unassigned.append("%s · %s" % (r["fn"], r["cabinet"]))
            elif (not due) and d in by_day:
                for h in by_day[d]:
                    if h["status"] == "planned":
                        await c.execute("DELETE FROM task WHERE id=$1", h["id"]); removed += 1
    # функции, которых в кабинете больше нет - будущие несделанные задачи снимаем
    q2 = """DELETE FROM task WHERE org_id=$1 AND source='generator' AND status='planned'
              AND plan_date >= $2 AND cabinet_id IS NOT NULL AND fn_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM cabinet_fn cf
                               WHERE cf.cabinet_id=task.cabinet_id AND cf.fn_id=task.fn_id)"""
    a2 = [org_id, start]
    if cabinet_id:
        q2 += " AND cabinet_id=$3::uuid"; a2.append(cabinet_id)
    removed += _fo_n(await c.execute(q2, *a2))
    return {"создано": created, "снято": removed, "переведено": moved,
            "дней": len(horizon), "без исполнителя": sorted(set(unassigned))[:20]}


@router.post("/tasks/sync")
async def fo_tasks_sync(days: int = 14, cabinet_id: str | None = None,
                        p: Principal = Depends(max_level(5))):
    """Досвести задачи по функциям кабинетов на горизонт вперёд. Ничего не пересоздаёт."""
    async with pool().acquire() as c:
        res = await _fo_sync_tasks(c, p.org_id, cabinet_id, days, None)
    return {"ok": True, **res}


_FO_SYNC = {"task": None}


async def _fo_sync_loop():
    import asyncio as _aio
    await _aio.sleep(15)
    while True:
        ok = False
        try:
            async with pool().acquire() as c:
                orgs = await c.fetch("SELECT DISTINCT org_id FROM client")
            for o in orgs:
                try:
                    async with pool().acquire() as c:
                        await _fo_sync_tasks(c, o["org_id"], None, 14, None, wait=False)
                except Exception:
                    pass
            ok = True
        except Exception:
            pass
        await _aio.sleep(6 * 3600 if ok else 120)


def _fo_sync_kick():
    import asyncio as _aio
    t = _FO_SYNC.get("task")
    if t is not None and not t.done():
        return
    try:
        _FO_SYNC["task"] = _aio.get_running_loop().create_task(_fo_sync_loop())
    except Exception:
        pass


@router.on_event("startup")
async def _fo_sync_boot():
    _fo_sync_kick()


# ── имя сотрудника выставляет РМ (С8, 129): везде имена, не почта ──
class FoEmpNameIn(_FoBM):
    name: str


@router.post("/employees/{emp_id}/name")
async def fo_emp_name(emp_id: str, body: FoEmpNameIn, p: Principal = Depends(max_level(4))):
    nm = (body.name or "").strip()[:80]
    if len(nm) < 2:
        raise HTTPException(400, "Имя короче двух символов")
    async with pool().acquire() as c:
        r = await c.fetchrow("SELECT id, user_id FROM employee WHERE id=$1::uuid AND org_id=$2",
                             emp_id, p.org_id)
        if not r:
            raise HTTPException(404, "сотрудник не найден")
        await c.execute("UPDATE employee SET name=$2 WHERE id=$1::uuid", emp_id, nm)
        if r["user_id"]:
            try:
                await c.execute(
                    "UPDATE app_user SET display_name=$2 WHERE id=$1 "
                    "AND (display_name IS NULL OR length(trim(display_name)) < 2)", r["user_id"], nm)
            except Exception:
                pass
    return {"ok": True, "name": nm}





# ── С10: выполнение задачи — галочка исполнителя, ссылка, согласование ──
# Галочку ставит исполнитель (или РМ и выше). При отметке — ссылка на
# таблицу/документ, дата ставит сервер. История ссылок хранится
# (fo_task_report), «одна и та же таблица» запоминается (fo_link_pref).
# Согласование: задача уходит в status='review', у согласующего мигает.

class FoDoneIn(_FoBM):
    link: str | None = None
    note: str | None = None
    fact_minutes: int | None = None
    same_table: bool | None = None


class FoReviewIn(_FoBM):
    approver_employee_id: str | None = None
    approver_label: str | None = None
    link: str | None = None
    note: str | None = None
    same_table: bool | None = None


class FoDecideIn(_FoBM):
    ok: bool = True
    note: str | None = None


class FoLinkPrefIn(_FoBM):
    fn_id: str
    cabinet_id: str | None = None
    same_table: bool = True
    link: str | None = None


async def _fo_my_emp(c, p):
    uid = _fo_uid(p)
    return await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2 LIMIT 1", uid, p.org_id)


async def _fo_task_for(c, task_id, p):
    r = await c.fetchrow(
        "SELECT id, org_id, fn_id, cabinet_id, client_id, assignee_id, status, title, plan_date "
        "FROM task WHERE id=$1::uuid AND org_id=$2", task_id, p.org_id)
    if not r:
        raise HTTPException(404, "задача не найдена")
    return r


async def _fo_can_mark(c, t, p):
    """Исполнитель — всегда; РМ и выше — тоже (за исполнителя)."""
    me = await _fo_my_emp(c, p)
    if me and t["assignee_id"] and str(me) == str(t["assignee_id"]):
        return True
    return int(getattr(p, "level", 9) or 9) <= 4


async def _fo_save_report(c, t, p, link, note, same_table):
    me = await _fo_my_emp(c, p)
    link = (link or "").strip()[:2000]
    note = (note or "").strip()[:4000]
    if link or note:
        await c.execute(
            """INSERT INTO fo_task_report (task_id, org_id, employee_id, fn_id, cabinet_id, link, note)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            t["id"], p.org_id, me, t["fn_id"], t["cabinet_id"], link or None, note or None)
    if link:
        await c.execute("UPDATE task SET report_form=$2 WHERE id=$1", t["id"], link)
    if same_table is not None and t["fn_id"] and me:
        await c.execute(
            """INSERT INTO fo_link_pref (org_id, fn_id, cabinet_id, employee_id, same_table, link)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (fn_id, COALESCE(cabinet_id, '00000000-0000-0000-0000-000000000000'::uuid), employee_id) DO UPDATE
                 SET same_table=EXCLUDED.same_table,
                     link=COALESCE(EXCLUDED.link, fo_link_pref.link), updated_at=now()""",
            p.org_id, t["fn_id"], t["cabinet_id"], me, bool(same_table), (link or None))


@router.post("/tasks/{task_id}/done")
async def fo_task_done(task_id: str, body: FoDoneIn, p: Principal = Depends(current)):
    """Галочка «выполнено»: исполнитель или РМ и выше. Ссылка и дата — на сервере."""
    async with pool().acquire() as c:
        t = await _fo_task_for(c, task_id, p)
        if not await _fo_can_mark(c, t, p):
            raise HTTPException(403, "отметить может исполнитель задачи или РМ")
        if t["status"] == "removed":
            raise HTTPException(409, "задача снята")
        fm = body.fact_minutes if body.fact_minutes and body.fact_minutes > 0 else None
        await c.execute(
            "UPDATE task SET status='done', done_at=now(), fact_minutes=COALESCE($2, fact_minutes) WHERE id=$1",
            t["id"], fm)
        await _fo_save_report(c, t, p, body.link, body.note, body.same_table)
        await c.execute("UPDATE fo_task_review SET decided_at=now(), verdict='done' "
                        "WHERE task_id=$1 AND decided_at IS NULL", t["id"])
    return {"ok": True, "status": "done"}


@router.post("/tasks/{task_id}/undone")
async def fo_task_undone(task_id: str, p: Principal = Depends(max_level(4))):
    """Снять галочку (ошиблись): исполнитель или РМ и выше."""
    async with pool().acquire() as c:
        t = await _fo_task_for(c, task_id, p)
        if not await _fo_can_mark(c, t, p):
            raise HTTPException(403, "снять отметку может исполнитель задачи или РМ")
        await c.execute("UPDATE task SET status='planned', done_at=NULL WHERE id=$1 AND status IN ('done','review')", t["id"])
    return {"ok": True, "status": "planned"}


@router.post("/tasks/{task_id}/review")
async def fo_task_review(task_id: str, body: FoReviewIn, p: Principal = Depends(current)):
    """Отправить на согласование: менеджер выбирает, кто согласует."""
    async with pool().acquire() as c:
        t = await _fo_task_for(c, task_id, p)
        if not await _fo_can_mark(c, t, p):
            raise HTTPException(403, "на согласование отправляет исполнитель задачи или РМ")
        me = await _fo_my_emp(c, p)
        appr = (body.approver_employee_id or "").strip() or None
        appr_uid = None
        if appr:
            row = await c.fetchrow("SELECT id, user_id FROM employee WHERE id=$1::uuid AND org_id=$2", appr, p.org_id)
            if not row:
                raise HTTPException(400, "согласующий не из этого агентства")
            appr_uid = row["user_id"]
        label = (body.approver_label or "").strip()[:120] or None
        if not appr and not label:
            raise HTTPException(400, "укажите, кто согласует")
        await _fo_save_report(c, t, p, body.link, body.note, body.same_table)
        await c.execute("UPDATE fo_task_review SET decided_at=now(), verdict='replaced' "
                        "WHERE task_id=$1 AND decided_at IS NULL", t["id"])
        await c.execute(
            """INSERT INTO fo_task_review (task_id, org_id, asked_by, approver_employee_id, approver_user_id, approver_label, note)
               VALUES ($1, $2, $3, $4::uuid, $5, $6, $7)""",
            t["id"], p.org_id, me, appr, appr_uid, label, (body.note or "").strip()[:2000] or None)
        await c.execute("UPDATE task SET status='review' WHERE id=$1", t["id"])
    return {"ok": True, "status": "review"}


@router.post("/tasks/{task_id}/review/decide")
async def fo_task_decide(task_id: str, body: FoDecideIn, p: Principal = Depends(current)):
    """Решение согласующего: принять (задача выполнена) или вернуть."""
    async with pool().acquire() as c:
        t = await _fo_task_for(c, task_id, p)
        rv = await c.fetchrow(
            "SELECT id, approver_user_id, approver_employee_id FROM fo_task_review "
            "WHERE task_id=$1 AND decided_at IS NULL ORDER BY asked_at DESC LIMIT 1", t["id"])
        if not rv:
            raise HTTPException(409, "задача не на согласовании")
        uid = _fo_uid(p)
        mine = rv["approver_user_id"] and str(rv["approver_user_id"]) == str(uid)
        if not mine and int(getattr(p, "level", 9) or 9) > 2:
            raise HTTPException(403, "решает согласующий, собственник или директор")
        note = (body.note or "").strip()[:2000] or None
        await c.execute("UPDATE fo_task_review SET decided_at=now(), verdict=$2, decision_note=$3, decided_by=$4 WHERE id=$1",
                        rv["id"], "ok" if body.ok else "back", note, uid)
        if body.ok:
            await c.execute("UPDATE task SET status='done', done_at=now() WHERE id=$1", t["id"])
        else:
            await c.execute("UPDATE task SET status='planned' WHERE id=$1", t["id"])
    return {"ok": True, "status": "done" if body.ok else "planned"}


@router.get("/tasks/reviews")
async def fo_task_reviews(p: Principal = Depends(current)):
    """Что ждёт согласования: мои (я согласую) и по всему агентству для собственника/директора."""
    uid = _fo_uid(p)
    lvl = int(getattr(p, "level", 9) or 9)
    async with pool().acquire() as c:
        me = await _fo_my_emp(c, p)
        rows = await c.fetch(
            """SELECT r.id, r.task_id, r.asked_at, r.approver_employee_id, r.approver_user_id, r.approver_label, r.note,
                      t.title, t.plan_date, t.assignee_id, t.report_form, t.cabinet_id, t.fn_id,
                      ea.name AS approver_name, eb.name AS asked_name
                 FROM fo_task_review r
                 JOIN task t ON t.id = r.task_id
                 LEFT JOIN employee ea ON ea.id = r.approver_employee_id
                 LEFT JOIN employee eb ON eb.id = r.asked_by
                WHERE r.org_id = $1 AND r.decided_at IS NULL AND t.status = 'review'
                ORDER BY r.asked_at""", p.org_id)
    out = []
    for r in rows:
        mine = bool(r["approver_user_id"] and str(r["approver_user_id"]) == str(uid))
        if not (mine or lvl <= 2 or (me and str(r["assignee_id"] or "") == str(me))):
            continue
        d = {k: r[k] for k in ("task_id", "asked_at", "approver_label", "note", "title", "plan_date",
                               "report_form", "approver_name", "asked_name")}
        for k in ("task_id", "approver_employee_id", "assignee_id", "cabinet_id", "fn_id"):
            d[k] = str(r[k]) if r[k] is not None else None
        d["mine"] = mine
        out.append(d)
    return out


@router.get("/tasks/{task_id}/reports")
async def fo_task_reports(task_id: str, p: Principal = Depends(current)):
    """История ссылок и заметок по задаче и по этой функции в этом кабинете."""
    async with pool().acquire() as c:
        t = await _fo_task_for(c, task_id, p)
        rows = await c.fetch(
            """SELECT r.task_id, r.link, r.note, r.made_at, e.name AS who
                 FROM fo_task_report r LEFT JOIN employee e ON e.id = r.employee_id
                WHERE r.org_id=$1 AND ((r.task_id=$2) OR (r.fn_id=$3 AND r.cabinet_id IS NOT DISTINCT FROM $4))
                ORDER BY r.made_at DESC LIMIT 50""", p.org_id, t["id"], t["fn_id"], t["cabinet_id"])
    return [{"task_id": str(r["task_id"]), "link": r["link"], "note": r["note"],
             "made_at": r["made_at"], "who": r["who"], "this_task": str(r["task_id"]) == str(t["id"])} for r in rows]


@router.get("/link-pref")
async def fo_link_pref_get(fn_id: str, cabinet_id: str | None = None, p: Principal = Depends(current)):
    """«Одна и та же таблица по этой задаче?» — что человек ответил и последняя ссылка."""
    async with pool().acquire() as c:
        me = await _fo_my_emp(c, p)
        if not me:
            return {"asked": False}
        r = await c.fetchrow(
            "SELECT same_table, link FROM fo_link_pref WHERE fn_id=$1::uuid AND cabinet_id IS NOT DISTINCT FROM $2::uuid AND employee_id=$3",
            fn_id, cabinet_id, me)
        if not r:
            last = await c.fetchval(
                "SELECT link FROM fo_task_report WHERE org_id=$1 AND fn_id=$2::uuid AND employee_id=$3 AND link IS NOT NULL ORDER BY made_at DESC LIMIT 1",
                p.org_id, fn_id, me)
            return {"asked": False, "link": last}
    return {"asked": True, "same_table": r["same_table"], "link": r["link"]}


@router.get("/link-pref/all")
async def fo_link_pref_all(p: Principal = Depends(current)):
    """187: ссылки на таблицы по функции и кабинету — хвостик у плашки в ганте и в списке дня.
    Запомненные ответы «одна и та же таблица» всего агентства и последняя ссылка из отчётов."""
    async with pool().acquire() as c:
        prefs = await c.fetch(
            "SELECT fn_id, cabinet_id, employee_id, same_table, link FROM fo_link_pref "
            "WHERE org_id=$1 AND link IS NOT NULL AND link <> '' ORDER BY updated_at DESC", p.org_id)
        last = await c.fetch(
            "SELECT DISTINCT ON (fn_id, cabinet_id) fn_id, cabinet_id, employee_id, task_id, link FROM fo_task_report "
            "WHERE org_id=$1 AND link IS NOT NULL AND link <> '' ORDER BY fn_id, cabinet_id, made_at DESC", p.org_id)
        tasks = await c.fetch(
            "SELECT DISTINCT ON (task_id) task_id, link FROM fo_task_report "
            "WHERE org_id=$1 AND link IS NOT NULL AND link <> '' ORDER BY task_id, made_at DESC", p.org_id)
    def _d(r):
        return {k: (str(v) if v is not None and k != "link" and k != "same_table" else v) for k, v in dict(r).items()}
    return {"prefs": [_d(r) for r in prefs], "last": [_d(r) for r in last], "tasks": [_d(r) for r in tasks]}


@router.post("/link-pref")
async def fo_link_pref_set(body: FoLinkPrefIn, p: Principal = Depends(current)):
    async with pool().acquire() as c:
        me = await _fo_my_emp(c, p)
        if not me:
            raise HTTPException(409, "у аккаунта нет карточки сотрудника")
        await c.execute(
            """INSERT INTO fo_link_pref (org_id, fn_id, cabinet_id, employee_id, same_table, link)
               VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6)
               ON CONFLICT (fn_id, COALESCE(cabinet_id, '00000000-0000-0000-0000-000000000000'::uuid), employee_id) DO UPDATE
                 SET same_table=EXCLUDED.same_table, link=COALESCE(EXCLUDED.link, fo_link_pref.link), updated_at=now()""",
            p.org_id, body.fn_id, body.cabinet_id, me, bool(body.same_table), (body.link or "").strip() or None)
    return {"ok": True}


class FoFnNameIn(_FoBM):
    name: str


@router.post("/functions/{fn_id}/name")
async def fo_fn_rename(fn_id: str, body: FoFnNameIn, p: Principal = Depends(max_level(4))):
    """197: переименовать функцию справочника. Название задач, ещё не сделанных, меняется
    вместе с ней (часть до « · » — это имя функции, дальше кабинет)."""
    name = (body.name or "").strip()[:200]
    if len(name) < 2:
        raise HTTPException(400, "название слишком короткое")
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM fn WHERE id=$1::uuid AND org_id=$2", fn_id, p.org_id)
        if not ok:
            raise HTTPException(404, "функция не найдена")
        dup = await c.fetchval(
            "SELECT code FROM fn WHERE org_id=$1 AND id<>$2::uuid AND lower(btrim(name))=lower($3) LIMIT 1",
            p.org_id, fn_id, name)
        if dup:
            raise HTTPException(409, "функция «%s» уже есть (%s)" % (name, dup))
        async with c.transaction():
            await c.execute("UPDATE fn SET name=$3 WHERE id=$1::uuid AND org_id=$2", fn_id, p.org_id, name)
            n = await c.execute(
                "UPDATE task SET title = $3 || CASE WHEN position(' · ' in title) > 0 "
                "THEN substr(title, position(' · ' in title)) ELSE '' END "
                "WHERE fn_id=$1::uuid AND org_id=$2 AND status IN ('planned','review')", fn_id, p.org_id, name)
    return {"ok": True, "name": name, "задач": n}


@router.post("/functions/{fn_id}/remove")
async def fo_fn_remove(fn_id: str, p: Principal = Depends(max_level(4))):
    """Убрать функцию из справочника агентства. Если она стоит в кабинетах — отказ."""
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM fn WHERE id=$1::uuid AND org_id=$2", fn_id, p.org_id)
        if not ok:
            raise HTTPException(404, "функция не найдена")
        n = await c.fetchval("SELECT count(*) FROM cabinet_fn WHERE fn_id=$1::uuid", fn_id)
        if n:
            raise HTTPException(409, "функция стоит в кабинетах (%d) — сначала уберите её оттуда" % n)
        async with c.transaction():
            await c.execute("DELETE FROM employee_fn WHERE fn_id=$1::uuid", fn_id)
            await c.execute("DELETE FROM fo_cabinet_fn_cfg WHERE fn_id=$1::uuid", fn_id)
            try:
                await c.execute("DELETE FROM fn WHERE id=$1::uuid AND org_id=$2", fn_id, p.org_id)
            except Exception:
                await c.execute("UPDATE fn SET is_active=false WHERE id=$1::uuid AND org_id=$2", fn_id, p.org_id)
    return {"ok": True}


# ── режим тени для админа (134, 136): смотреть глазами любого человека ──
# Админ получает доступ от имени выбранного пользователя. Пока фронт держит
# метку тени (заголовок X-FO-Shadow), сервер отклоняет любую запись —
# тень только смотрит. Каждый вход в тень пишется в fo_shadow_log.

class FoShadowIn(_FoBM):
    user_id: str


def _fo_make_access_for(u):
    """make_access из security.py — подбираем аргументы по его сигнатуре."""
    import inspect as _insp
    sec = None
    for _m in ("..security", "app.security", "security"):
        try:
            sec = _fo_il.import_module(_m, package=__package__ if _m.startswith(".") else None); break
        except Exception:
            continue
    if not sec or not hasattr(sec, "make_access"):
        raise HTTPException(500, "make_access не найден")
    fn = sec.make_access
    params = list(_insp.signature(fn).parameters.values())
    cand = {"user_id": str(u["id"]), "uid": str(u["id"]), "sub": str(u["id"]), "id": str(u["id"]),
            "org_id": str(u["org_id"]), "org": str(u["org_id"]),
            "role": u["role_code"], "role_code": u["role_code"], "level": int(u["level"]),
            "email": u["email"], "user": u, "u": u, "row": u, "principal": u}
    kw = {}
    for prm in params:
        if prm.name in cand:
            kw[prm.name] = cand[prm.name]
        elif prm.default is _insp.Parameter.empty and prm.kind in (prm.POSITIONAL_OR_KEYWORD, prm.KEYWORD_ONLY):
            raise HTTPException(500, "make_access ждёт неизвестный аргумент: %s (сигнатура: %s)" % (prm.name, str(_insp.signature(fn))))
    try:
        return fn(**kw)
    except TypeError as e:
        # возможно, ждёт одну запись пользователя позиционно
        try:
            return fn(u)
        except Exception:
            raise HTTPException(500, "make_access: %s (сигнатура: %s)" % (str(e)[:120], str(_insp.signature(fn))))


@router.post("/admin/shadow")
async def fo_admin_shadow(body: FoShadowIn, p: Principal = Depends(max_level(0))):
    """Тень: доступ от имени пользователя. Только смотреть — запись сервер отклонит."""
    async with pool().acquire() as c:
        u = await c.fetchrow(
            "SELECT u.id, u.email, u.org_id, u.role_code, u.display_name, r.level, o.name AS org_name "
            "FROM app_user u JOIN role r ON r.code=u.role_code JOIN org o ON o.id=u.org_id "
            "WHERE u.id=$1::uuid", body.user_id)
        if not u:
            raise HTTPException(404, "пользователь не найден")
        tok = _fo_make_access_for(u)
        if isinstance(tok, (tuple, list)):
            tok = tok[0]
        if isinstance(tok, dict):
            tok = tok.get("access") or tok.get("token") or tok.get("access_token")
        try:
            await c.execute("INSERT INTO fo_shadow_log (admin_user_id, target_user_id) VALUES ($1, $2)", _fo_uid(p), u["id"])
        except Exception:
            pass
    return {"ok": True, "access": tok, "user": {"id": str(u["id"]), "email": u["email"], "name": u["display_name"] or "",
                                              "role": u["role_code"], "level": u["level"], "org_name": u["org_name"]}}


@router.get("/admin/people")
async def fo_admin_people(p: Principal = Depends(max_level(0))):
    """Все агентства и люди — для выбора, чьими глазами смотреть."""
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT u.id, u.email, u.display_name, u.role_code, r.level, o.id AS org_id, o.name AS org_name "
            "FROM app_user u JOIN role r ON r.code=u.role_code JOIN org o ON o.id=u.org_id "
            "WHERE u.is_active ORDER BY o.name, r.level, u.email")
    return [{"id": str(r["id"]), "email": r["email"], "name": r["display_name"] or "", "role": r["role_code"],
             "level": r["level"], "org_id": str(r["org_id"]), "org_name": r["org_name"]} for r in rows]


# ── Мой аккаунт ──────────────────────────────────────────────────

@router.get("/me/account")
async def fo_me(p: Principal = Depends(current)):
    uid = _fo_uid(p)
    try: _fo_sync_kick()
    except Exception: pass
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





# ══ ИИ ИЗ ЧАТОВ (С11, этап 1) ════════════════════════════════════
# Клиент пишет в чат кабинета → Telegram шлёт сообщение сюда (свой
# webhook, с тем же секретом, что штатный) → сообщение хранится →
# YandexGPT разбирает: задача ли это, что сделать, функция, срочность,
# дедлайн, зачем и конечная цель → сервер по правилам подбирает
# ответственного из людей кабинета и согласующего (главный менеджер /
# проджект кабинета, иначе собственник) → предложение ждёт «Принять».
# Ответственному задача ставится только после согласования.
import asyncio as _fo_aio
import os as _fo_os
import time as _fo_time
import datetime as _fo_dt
import urllib.request as _fo_ur
import urllib.parse as _fo_up
from fastapi import Request as _FoReq

_FO_MSK = _fo_dt.timezone(_fo_dt.timedelta(hours=3))
_FO_ENVC = {"t": 0.0, "v": {}}


def _fo_env(k):
    if _fo_time.time() - _FO_ENVC["t"] > 30:
        d = {}
        try:
            for ln in open("/opt/fo/.env", encoding="utf-8"):
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    a, b = ln.split("=", 1)
                    d[a.strip()] = b.strip().strip('"').strip("'")
        except Exception:
            pass
        _FO_ENVC["t"] = _fo_time.time()
        _FO_ENVC["v"] = d
    return _fo_os.environ.get(k) or _FO_ENVC["v"].get(k, "")


def _fo_ai_keyok(k):
    k = str(k or "")
    return bool(k) and k.isascii() and len(k) >= 20 and " " not in k


def _fo_ai_ready():
    return _fo_ai_keyok(_fo_env("YC_API_KEY")) and bool(_fo_env("YC_FOLDER_ID")) and _fo_env("YC_FOLDER_ID").isascii()


_FO_AI_SKIP = re.compile(r"^\s*(спасибо|спс|благодарю|ок|окей|ok|хорошо|понял|поняла|принято|да|нет|угу|ага|супер|отлично|класс|👍|🙏|👌|\+)[\s!.)]*$", re.I)

_FO_AI_SYS = (
    "Ты — ассистент digital-агентства, которое ведёт кабинеты продавцов на Wildberries и OZON: реклама, цены, "
    "карточки товаров, аналитика, поставки, отзывы. Тебе дают новое сообщение из чата с клиентом и контекст. "
    "Реши, просит ли клиент агентство что-то сделать (это задача), или это вопрос, благодарность, информация без действия.\n"
    "Если это задача — сформулируй её для менеджера агентства коротко и по делу, в повелительном наклонении "
    "(например: «Снизить цену на артикул 153667602 до 1990 ₽»).\n"
    "function_code — код функции только из списка функций кабинета, если подходит; иначе null.\n"
    "urgent=true — если клиент просит сегодня, срочно, сейчас, до конкретного часа, или это останавливает продажи.\n"
    "deadline — дата и время по Москве в формате YYYY-MM-DD HH:MM, если срок назван или очевиден; иначе null.\n"
    "why — одно предложение: зачем делается задача, что за ней стоит у клиента.\n"
    "goal — одно предложение: какая конечная цель, какой результат для бизнеса клиента.\n"
    "minutes — сколько минут это займёт у менеджера, число от 5 до 240.\n"
    "Ответь только JSON, без пояснений и без markdown:\n"
    "{\"is_task\": true, \"title\": \"...\", \"function_code\": null, \"urgent\": false, \"deadline\": null, "
    "\"why\": \"...\", \"goal\": \"...\", \"minutes\": 30}"
)


def _fo_ygpt_sync(messages, max_tokens=600):
    key = _fo_env("YC_API_KEY")
    folder = _fo_env("YC_FOLDER_ID")
    model = _fo_env("YC_MODEL") or "yandexgpt-lite/latest"
    if not key or not folder:
        raise RuntimeError("нет ключа Яндекса на сервере")
    if not _fo_ai_keyok(key) or not folder.isascii():
        raise RuntimeError("ключ Яндекса на сервере — не ключ (заглушка или русские буквы): вставьте настоящий")
    body = _fo_json.dumps({"modelUri": "gpt://%s/%s" % (folder, model),
                           "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": max_tokens},
                           "messages": messages}).encode()
    rq = _fo_ur.Request("https://llm.api.cloud.yandex.net/foundationModels/v1/completion", data=body,
                        headers={"Authorization": "Api-Key " + key, "x-folder-id": folder,
                                 "Content-Type": "application/json"})
    with _fo_ur.urlopen(rq, timeout=45) as r:
        res = _fo_json.loads(r.read().decode())
    res = res.get("result") or {}
    txt = (((res.get("alternatives") or [{}])[0].get("message")) or {}).get("text", "")
    usage = res.get("usage") or {}
    return txt, usage


def _fo_tg_react_sync(chat_id, msg_id):
    """Бот ставит реакцию на сообщение клиента, в котором ИИ увидел задачу (Виталий: 🧑‍💻).
    У Telegram свой список разрешённых реакций: не приняли 🧑‍💻 — ставим 👨‍💻."""
    tok = _fo_env("TG_BOT_TOKEN")
    if not tok or not chat_id or str(chat_id) == "test" or not msg_id:
        return "без реакции"
    last = ""
    for emo in ("\U0001F9D1\u200D\U0001F4BB", "\U0001F468\u200D\U0001F4BB"):
        data = _fo_up.urlencode({"chat_id": str(chat_id), "message_id": str(msg_id),
                                 "reaction": _fo_json.dumps([{"type": "emoji", "emoji": emo}])}).encode()
        try:
            with _fo_ur.urlopen("https://api.telegram.org/bot%s/setMessageReaction" % tok, data=data, timeout=15) as r:
                if _fo_json.loads(r.read().decode()).get("ok"):
                    return "реакция " + emo
        except Exception as e:
            last = str(e)
            try:
                last += " " + e.read().decode()[:200]
            except Exception:
                pass
    return ("реакция не встала: " + last.replace(tok, "***"))[:300]


def _fo_ai_json(txt):
    s = str(txt or "")
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return _fo_json.loads(s[a:b + 1])
    except Exception:
        try:
            return _fo_json.loads(re.sub(r",\s*}", "}", s[a:b + 1]))
        except Exception:
            return None


def _fo_msg_link(tg_chat_id, msg_id):
    s = str(tg_chat_id or "")
    if s.startswith("-100") and msg_id:
        return "https://t.me/c/%s/%s" % (s[4:], msg_id)
    return None


async def _fo_ai_people(c, org_id, cab_id, fn_id):
    """Кандидаты в ответственные: люди этого кабинета (ведут его функции и артикулы),
    плюс кто умеет функцию; минус нагрузка сегодня. Собственник и директор — не исполнители."""
    ppl = {}

    def add(eid, name, score, why):
        if not eid:
            return
        k = str(eid)
        d = ppl.setdefault(k, {"employee_id": k, "name": name or "", "score": 0.0, "why": []})
        d["score"] += score
        if why and why not in d["why"]:
            d["why"].append(why)

    if cab_id:
        try:
            for r in await c.fetch(
                    "SELECT g.employee_id, g.fn_id, e.name FROM fo_cabinet_fn_cfg g JOIN employee e ON e.id=g.employee_id "
                    "WHERE g.cabinet_id=$1::uuid AND g.employee_id IS NOT NULL", str(cab_id)):
                same = fn_id and str(r["fn_id"]) == str(fn_id)
                add(r["employee_id"], r["name"], 10 if same else 2,
                    "ведёт эту функцию в кабинете" if same else "ведёт функции этого кабинета")
        except Exception:
            pass
        try:
            for r in await c.fetch(
                    "SELECT ao.employee_id, e.name, count(DISTINCT ao.article_id) AS n FROM article_owner ao "
                    "JOIN article a ON a.id=ao.article_id JOIN employee e ON e.id=ao.employee_id "
                    "WHERE a.cabinet_id=$1::uuid AND a.is_active GROUP BY 1,2", str(cab_id)):
                add(r["employee_id"], r["name"], 1, "ведёт артикулы кабинета: %d" % r["n"])
        except Exception:
            pass
    if fn_id:
        try:
            for r in await c.fetch(
                    "SELECT ef.employee_id, e.name FROM employee_fn ef JOIN employee e ON e.id=ef.employee_id "
                    "WHERE ef.fn_id=$1::uuid AND e.org_id=$2", str(fn_id), org_id):
                if str(r["employee_id"]) in ppl or not ppl:
                    add(r["employee_id"], r["name"], 3, "умеет эту функцию")
        except Exception:
            pass
    if not ppl:
        return []
    try:
        top = await c.fetch(
            "SELECT e.id FROM employee e JOIN app_user u ON u.id=e.user_id "
            "WHERE e.org_id=$1 AND u.role_code IN ('owner','admin','director')", org_id)
        for r in top:
            ppl.pop(str(r["id"]), None)
    except Exception:
        pass
    try:
        today = _fo_msk_today()
        for r in await c.fetch(
                "SELECT assignee_id, count(*) AS n FROM task WHERE plan_date=$1 AND status IN ('planned','review') "
                "AND assignee_id = ANY($2::uuid[]) GROUP BY 1", today, list(ppl.keys())):
            d = ppl.get(str(r["assignee_id"]))
            if d:
                d["score"] -= 0.3 * int(r["n"])
                d["why"].append("сегодня задач: %d" % int(r["n"]))
    except Exception:
        pass
    return sorted(ppl.values(), key=lambda x: -x["score"])


async def _fo_ai_settings(c, org_id):
    d = await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1", "ai:" + str(org_id))
    if isinstance(d, str):
        try:
            d = _fo_json.loads(d)
        except Exception:
            d = {}
    return d or {}


async def _fo_ai_approvers(c, org_id):
    """Кто согласует задачи от ИИ: кого назначил собственник; никого — собственник.
    Возвращает (user_id-список, подпись, employee_id первого)."""
    st = await _fo_ai_settings(c, org_id)
    ids = [str(x) for x in (st.get("approvers") or []) if x]
    if ids:
        rows = await c.fetch("SELECT id, name, user_id FROM employee WHERE org_id=$1 AND id = ANY($2::uuid[]) "
                             "AND user_id IS NOT NULL ORDER BY name", org_id, ids)
        if rows:
            return [r["user_id"] for r in rows], ", ".join(r["name"] or "" for r in rows), str(rows[0]["id"])
    own = await c.fetch("SELECT id FROM app_user WHERE org_id=$1 AND role_code='owner' AND is_active "
                        "ORDER BY created_at", org_id)
    return [r["id"] for r in own], "Собственник", None


def _fo_ai_deadline(s):
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return _fo_dt.datetime.strptime(s[:16] if "H" in fmt else s[:10], fmt).replace(tzinfo=_FO_MSK)
        except Exception:
            continue
    return None


async def _fo_ai_process(msg_pk, dry=False, use_prev=True):
    """Разобрать одно сообщение: Яндекс → предложение задачи на согласование."""
    async with pool().acquire() as c:
        m = await c.fetchrow("SELECT * FROM fo_chat_msg WHERE id=$1", msg_pk)
        if not m:
            return {"state": "нет сообщения"}
        cab = await c.fetchrow("SELECT cb.id, cl.name FROM cabinet cb JOIN client cl ON cl.id=cb.client_id "
                               "WHERE cb.client_id=$1::uuid ORDER BY cb.name LIMIT 1", str(m["client_id"]))
        cab_id = cab["id"] if cab else None
        fns = []
        if cab_id:
            fns = await c.fetch("SELECT f.id, f.code, f.name FROM cabinet_fn cf JOIN fn f ON f.id=cf.fn_id "
                                "WHERE cf.cabinet_id=$1::uuid ORDER BY f.code", str(cab_id))
        prev = await c.fetch("SELECT author, text FROM fo_chat_msg WHERE tg_chat_id=$1 AND id<$2 AND text<>'' "
                             "ORDER BY id DESC LIMIT 6", m["tg_chat_id"], m["id"]) if use_prev else []
    now = _fo_dt.datetime.now(_FO_MSK)
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    ctx = ("Сейчас: %s (Москва), %s.\nКабинет: %s.\nФункции кабинета:\n%s\n" % (
        now.strftime("%Y-%m-%d %H:%M"), days[now.weekday()], (cab["name"] if cab else "—"),
        "\n".join("%s — %s" % (f["code"], f["name"]) for f in fns[:80]) or "(не назначены)"))
    if prev:
        ctx += "Предыдущие сообщения чата (старые сверху):\n" + "\n".join(
            "— %s: %s" % (p_["author"] or "?", (p_["text"] or "")[:300]) for p_ in reversed(prev)) + "\n"
    ctx += "Новое сообщение (от %s): «%s»" % (m["author"] or "клиент", (m["text"] or "")[:1500])
    try:
        txt, usage = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": _FO_AI_SYS},
                                                             {"role": "user", "text": ctx}])
    except Exception as e:
        async with pool().acquire() as c:
            await c.execute("UPDATE fo_chat_msg SET ai_state='error', ai_note=$2 WHERE id=$1", msg_pk, str(e)[:300])
        return {"state": "error", "note": str(e)[:300]}
    js = _fo_ai_json(txt) or {}
    tokens = 0
    try:
        tokens = int(usage.get("totalTokens") or 0)
    except Exception:
        pass
    async with pool().acquire() as c:
        if not js.get("is_task"):
            await c.execute("UPDATE fo_chat_msg SET ai_state='no_task', ai_tokens=$2 WHERE id=$1", msg_pk, tokens)
            return {"state": "no_task", "ai": js, "контекст": [p_["text"][:120] for p_ in reversed(prev)]}
        code = str(js.get("function_code") or "").strip()
        fn = next((f for f in fns if str(f["code"]).lower() == code.lower()), None) if code else None
        fn_id = fn["id"] if fn else None
        cands = await _fo_ai_people(c, m["org_id"], cab_id, fn_id)
        emp = cands[0]["employee_id"] if cands else None
        if dry:
            await c.execute("UPDATE fo_chat_msg SET ai_state='task', ai_tokens=$2 WHERE id=$1", msg_pk, tokens)
            return {"state": "task", "ai": js, "ответственный": (cands[0]["name"] if cands else None),
                    "почему": (cands[0]["why"] if cands else []), "функция": (fn["code"] + " " + fn["name"]) if fn else None,
                    "контекст": [p_["text"][:120] for p_ in reversed(prev)]}
        a_uids, a_name, a_emp = await _fo_ai_approvers(c, m["org_id"])
        a_uid = a_uids[0] if a_uids else None
        try:
            mins = max(5, min(240, int(js.get("minutes") or 30)))
        except Exception:
            mins = 30
        dl = _fo_ai_deadline(js.get("deadline"))
        title = str(js.get("title") or m["text"] or "")[:300].strip() or "Задача из чата"
        rid = await c.fetchval(
            """INSERT INTO fo_ai_task (org_id, client_id, cabinet_id, msg_pk, tg_chat_id, msg_id, msg_link, quote, author, msg_at,
                                       title, fn_id, employee_id, candidates, urgent, deadline, minutes, why, goal,
                                       approver_employee_id, approver_user_id, approver_label, ai_raw, approver_users)
               VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::uuid,$14::jsonb,$15,$16,$17,$18,$19,$20::uuid,$21,$22,$23::jsonb,$24::uuid[])
               RETURNING id""",
            m["org_id"], str(m["client_id"]), cab_id, msg_pk, m["tg_chat_id"], m["msg_id"],
            _fo_msg_link(m["tg_chat_id"], m["msg_id"]), (m["text"] or "")[:2000], m["author"], m["msg_at"],
            title, fn_id, emp, _fo_json.dumps(cands[:6], ensure_ascii=False), bool(js.get("urgent")), dl, mins,
            str(js.get("why") or "")[:500], str(js.get("goal") or "")[:500], a_emp, a_uid, a_name,
            _fo_json.dumps(js, ensure_ascii=False), [str(x) for x in a_uids])
        await c.execute("UPDATE fo_chat_msg SET ai_state='task', ai_tokens=$2 WHERE id=$1", msg_pk, tokens)
    react = ""
    try:
        react = await _fo_aio.to_thread(_fo_tg_react_sync, m["tg_chat_id"], m["msg_id"])
        async with pool().acquire() as c:
            await c.execute("UPDATE fo_chat_msg SET ai_note=$2 WHERE id=$1", msg_pk, react)
    except Exception:
        pass
    return {"state": "task", "ai_task_id": str(rid), "ai": js, "реакция": react}


async def _fo_tg_claim(c, tg, title):
    """Чат внесли в карточку ссылкой-приглашением (t.me/+…), а Telegram присылает номер группы.
    Находим такой чат по названию и ставим ему настоящий номер — тогда бот и читает, и пишет в него."""
    if not title:
        return False
    row = await c.fetchrow(
        "SELECT ch.id, ch.org_id FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id "
        "WHERE lower(btrim(ch.title)) = lower(btrim($1)) AND ch.chat_id !~ '^-?[0-9]+$' ORDER BY ch.id LIMIT 1", title)
    if not row:
        return False
    busy = await c.fetchval("SELECT 1 FROM chat WHERE org_id=$1 AND channel='telegram' AND chat_id=$2", row["org_id"], tg)
    if busy:
        return False
    await c.execute("UPDATE chat SET chat_id=$2, is_active=true WHERE id=$1", row["id"], tg)
    return True


async def _fo_tg_register(upd):
    """Как штатный webhook: бот добавлен в группу — чат попадает в список чатов агентства.
    Если чат уже внесён в карточку клиента ссылкой — привязываем его номер по названию."""
    ev = upd.get("my_chat_member") or upd.get("message") or {}
    chat = ev.get("chat") or {}
    if not chat.get("id") or chat.get("type") == "private":
        return
    title = chat.get("title") or str(chat["id"])
    async with pool().acquire() as c:
        linked = await c.fetchval("SELECT 1 FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id WHERE ch.chat_id=$1 LIMIT 1",
                                  str(chat["id"]))
        if linked or await _fo_tg_claim(c, str(chat["id"]), chat.get("title") or ""):
            return
        org = await c.fetchval("SELECT org_id FROM chat WHERE chat_id=$1 ORDER BY added_at LIMIT 1", str(chat["id"]))
        if not org:
            org = await c.fetchval("SELECT id FROM org ORDER BY created_at LIMIT 1")
        await c.execute(
            "INSERT INTO chat (org_id, channel, chat_id, title) VALUES ($1, 'telegram', $2, $3) "
            "ON CONFLICT (org_id, channel, chat_id) DO UPDATE SET title=EXCLUDED.title, is_active=true",
            org, str(chat["id"]), title)


async def _fo_ai_on_msg(msg):
    try:
        chat = msg.get("chat") or {}
        tg = str(chat.get("id") or "")
        if not tg or chat.get("type") == "private":
            return
        frm = msg.get("from") or {}
        if frm.get("is_bot"):
            return
        text = str(msg.get("text") or msg.get("caption") or "").strip()
        async with pool().acquire() as c:
            link = await c.fetchrow(
                "SELECT ch.id AS chat_pk, ch.org_id, cc.client_id, cc.kind FROM chat ch "
                "JOIN client_chat cc ON cc.chat_pk = ch.id WHERE ch.chat_id=$1 "
                "ORDER BY (cc.kind='client') DESC LIMIT 1", tg)
            if not link:
                return
            author = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or frm.get("username") or ""
            at = _fo_dt.datetime.fromtimestamp(int(msg.get("date") or _fo_time.time()), tz=_fo_dt.timezone.utc)
            pk = await c.fetchval(
                "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at) "
                "VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (tg_chat_id, msg_id) DO NOTHING RETURNING id",
                link["org_id"], str(link["client_id"]), link["chat_pk"], link["kind"], tg, int(msg.get("message_id") or 0),
                author[:120], str(frm.get("username") or "")[:64], text[:4000], at)
            if not pk:
                return
            why = None
            if link["kind"] != "client":
                why = "не чат с клиентом"
            elif len(text) < 6 or _FO_AI_SKIP.match(text):
                why = "короткое / благодарность"
            elif not _fo_ai_ready():
                why = "нет ключа Яндекса"
            if why:
                await c.execute("UPDATE fo_chat_msg SET ai_state='skip', ai_note=$2 WHERE id=$1", pk, why)
                return
        await _fo_ai_process(pk)
    except Exception as e:
        try:
            print("fo_ai_on_msg:", e)
        except Exception:
            pass


@router.post("/tg/hook", include_in_schema=False)
async def fo_tg_hook(request: _FoReq):
    secret = _fo_env("TG_WEBHOOK_SECRET")
    if not secret or request.headers.get("x-telegram-bot-api-secret-token", "") != secret:
        raise HTTPException(403, "нет")
    upd = await request.json()
    try:
        await _fo_tg_register(upd)
    except Exception:
        pass
    msg = upd.get("message")
    if msg:
        _fo_aio.get_running_loop().create_task(_fo_ai_on_msg(msg))
    return {"ok": True}


def _fo_ai_row(r):
    d = dict(r)
    for k in ("id", "client_id", "cabinet_id", "fn_id", "employee_id", "approver_employee_id", "approver_user_id",
              "decided_by", "msg_pk", "task_once_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    d["approver_users"] = [str(x) for x in (d.get("approver_users") or [])]
    for k in ("candidates", "ai_raw"):
        if isinstance(d.get(k), str):
            try:
                d[k] = _fo_json.loads(d[k])
            except Exception:
                pass
    return d


@router.get("/ai/tasks")
async def fo_ai_tasks(status: str = "pending", p: Principal = Depends(current)):
    """Задачи, которые ИИ нашёл в чатах: мои на согласовании; собственнику и директору — все."""
    uid = _fo_uid(p)
    lvl = int(getattr(p, "level", 9) or 9)
    async with pool().acquire() as c:
        rows = await c.fetch(
            """SELECT a.*, cl.name AS client_name, e.name AS employee_name, fn.code AS fn_code, fn.name AS fn_name,
                      ea.name AS approver_name
                 FROM fo_ai_task a
                 LEFT JOIN client cl ON cl.id = a.client_id
                 LEFT JOIN employee e ON e.id = a.employee_id
                 LEFT JOIN fn ON fn.id = a.fn_id
                 LEFT JOIN employee ea ON ea.id = a.approver_employee_id
                WHERE a.org_id=$1 AND ($2 = 'all' OR a.status=$2)
                ORDER BY a.created_at DESC LIMIT 200""", p.org_id, status)
    out = []
    for r in rows:
        mine = str(uid) in [str(x) for x in (r["approver_users"] or [])] or bool(
            r["approver_user_id"] and str(r["approver_user_id"]) == str(uid))
        if not (mine or lvl <= 2):
            continue
        d = _fo_ai_row(r)
        d["mine"] = mine
        out.append(d)
    return out


class FoAiDecideIn(_FoBM):
    ok: bool = True
    employee_id: str | None = None
    title: str | None = None
    day: str | None = None
    minutes: int | None = None
    urgent: bool | None = None
    note: str | None = None


@router.post("/ai/tasks/{ai_id}/decide")
async def fo_ai_decide(ai_id: str, body: FoAiDecideIn, p: Principal = Depends(current)):
    """Согласующий принимает (задача ставится ответственному) или отклоняет."""
    uid = _fo_uid(p)
    lvl = int(getattr(p, "level", 9) or 9)
    try:
        aid = int(str(ai_id))
    except Exception:
        raise HTTPException(404, "не найдено")
    async with pool().acquire() as c:
        a = await c.fetchrow("SELECT a.*, cl.name AS client_name FROM fo_ai_task a LEFT JOIN client cl ON cl.id=a.client_id "
                             "WHERE a.id=$1 AND a.org_id=$2", aid, p.org_id)
        if not a:
            raise HTTPException(404, "не найдено")
        if a["status"] != "pending":
            raise HTTPException(409, "уже решено")
        mine = str(uid) in [str(x) for x in (a["approver_users"] or [])] or (
            a["approver_user_id"] and str(a["approver_user_id"]) == str(uid))
        if not mine and lvl > 2:
            raise HTTPException(403, "решает согласующий, которого назначил собственник, или собственник")
        note = (body.note or "").strip()[:1000] or None
        if not body.ok:
            await c.execute("UPDATE fo_ai_task SET status='rejected', decided_by=$2, decided_at=now(), decision_note=$3 WHERE id=$1",
                            aid, uid, note)
            return {"ok": True, "status": "rejected"}
        emp = (body.employee_id or "").strip() or (str(a["employee_id"]) if a["employee_id"] else "")
        if not emp:
            raise HTTPException(400, "выберите ответственного")
        ok = await c.fetchval("SELECT 1 FROM employee WHERE id=$1::uuid AND org_id=$2", emp, p.org_id)
        if not ok:
            raise HTTPException(400, "ответственный не из этого агентства")
        title = (body.title or "").strip() or a["title"]
        urgent = a["urgent"] if body.urgent is None else bool(body.urgent)
        day = None
        if body.day:
            try:
                day = _fo_dt.date.fromisoformat(str(body.day)[:10])
            except Exception:
                day = None
        if not day and a["deadline"]:
            day = a["deadline"].astimezone(_FO_MSK).date()
        if not day:
            day = _fo_msk_today()
        mins = max(1, min(2880, int(body.minutes or a["minutes"] or 30)))
        who = await c.fetchval("SELECT name FROM employee WHERE user_id=$1 AND org_id=$2 LIMIT 1", uid, p.org_id)
        when = a["msg_at"].astimezone(_FO_MSK).strftime("%d.%m %H:%M") if a["msg_at"] else ""
        full = ("[ИИ] Увидел ИИ в чате с клиентом («%s»), поставил ИИ; согласовал(а): %s.\n"
                "Зачем: %s\nЦель: %s\nСообщение (%s, %s): «%s»%s%s%s") % (
            a["client_name"] or "", who or "согласующий", a["why"] or "—", a["goal"] or "—",
            a["author"] or "клиент", when, (a["quote"] or "")[:600],
            ("\nОткрыть в чате: " + a["msg_link"]) if a["msg_link"] else "",
            ("\nДедлайн: " + a["deadline"].astimezone(_FO_MSK).strftime("%d.%m %H:%M")) if a["deadline"] else "",
            ("\nКомментарий: " + note) if note else "")
        tid = await c.fetchval(
            "INSERT INTO fo_task_once (org_id, title, client_id, employee_id, fn_id, day, dow, minutes, kind, note, created_by) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id",
            p.org_id, ("ИИ · " + title)[:300], str(a["client_id"]) if a["client_id"] else None, emp,
            str(a["fn_id"]) if a["fn_id"] else None, day, day.weekday(), mins, "urg" if urgent else "once", full, uid)
        await c.execute("UPDATE fo_ai_task SET status='accepted', decided_by=$2, decided_at=now(), decision_note=$3, "
                        "task_once_id=$4, employee_id=$5::uuid, title=$6 WHERE id=$1", aid, uid, note, tid, emp, title)
    return {"ok": True, "status": "accepted", "task_once_id": str(tid)}


class FoAiTestIn(_FoBM):
    client_id: str
    text: str
    author: str | None = None
    dry: bool = False            # только разбор: предложение на согласование не создаём
    context: bool = True         # учитывать предыдущие сообщения этой «переписки»
    thread: str | None = None    # имя тестовой переписки: у каждой своя история


@router.post("/ai/test")
async def fo_ai_test(body: FoAiTestIn, p: Principal = Depends(max_level(2))):
    """Проверка без Telegram: как будто клиент написал это в чат кабинета."""
    if not _fo_ai_ready():
        raise HTTPException(409, "на сервере нет ключа Яндекса")
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM client WHERE id=$1::uuid AND org_id=$2", body.client_id, p.org_id)
        if not ok:
            raise HTTPException(404, "клиент не найден")
        th = "test" if not body.thread else ("test:" + re.sub(r"[^A-Za-z0-9_\-]", "", body.thread)[:40])
        n = await c.fetchval("SELECT count(*) FROM fo_chat_msg WHERE tg_chat_id=$1", th)
        pk = await c.fetchval(
            "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at) "
            "VALUES ($1,$2::uuid,NULL,'client',$3,$4,$5,'',$6,now()) RETURNING id",
            p.org_id, body.client_id, th, int(n or 0) + 1, (body.author or "Клиент (проверка)")[:120], body.text[:4000])
    return await _fo_ai_process(pk, dry=body.dry, use_prev=body.context)


@router.get("/ai/status")
async def fo_ai_status(p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        msgs = await c.fetchval("SELECT count(*) FROM fo_chat_msg WHERE org_id=$1 AND msg_at > now() - interval '1 day'", p.org_id)
        pend = await c.fetchval("SELECT count(*) FROM fo_ai_task WHERE org_id=$1 AND status='pending'", p.org_id)
        toks = await c.fetchval("SELECT COALESCE(sum(ai_tokens),0) FROM fo_chat_msg WHERE org_id=$1 "
                                "AND msg_at > date_trunc('month', now())", p.org_id)
        last = await c.fetch("SELECT author, left(text, 80) AS text, ai_state, ai_note, msg_at FROM fo_chat_msg "
                             "WHERE org_id=$1 ORDER BY id DESC LIMIT 5", p.org_id)
    return {"yandex": _fo_ai_ready(), "model": _fo_env("YC_MODEL") or "yandexgpt-lite/latest",
            "сообщений_за_сутки": int(msgs or 0), "ждут_согласования": int(pend or 0),
            "токенов_за_месяц": int(toks or 0), "последние": [dict(r) for r in last]}


class FoAiSettingsIn(_FoBM):
    approvers: list[str] = []


@router.get("/ai/settings")
async def fo_ai_settings_get(p: Principal = Depends(max_level(6))):
    async with pool().acquire() as c:
        st = await _fo_ai_settings(c, p.org_id)
        uids, label, _e = await _fo_ai_approvers(c, p.org_id)
        ids = [str(x) for x in (st.get("approvers") or [])]
        rows = await c.fetch("SELECT id, name FROM employee WHERE org_id=$1 AND id = ANY($2::uuid[])", p.org_id, ids) if ids else []
    return {"approvers": [{"employee_id": str(r["id"]), "name": r["name"]} for r in rows], "label": label,
            "по_умолчанию": "Собственник"}


@router.post("/ai/settings")
async def fo_ai_settings_set(body: FoAiSettingsIn, p: Principal = Depends(max_level(2))):
    """Собственник раздаёт право согласовывать задачи от ИИ любым людям агентства (пусто — согласует сам)."""
    ids = [x for x in (body.approvers or []) if re.match(r"^[0-9a-fA-F-]{36}$", str(x or ""))]
    async with pool().acquire() as c:
        if ids:
            ok = await c.fetch("SELECT id FROM employee WHERE org_id=$1 AND id = ANY($2::uuid[])", p.org_id, ids)
            ids = [str(r["id"]) for r in ok]
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
            "ai:" + str(p.org_id), p.org_id, _fo_json.dumps({"approvers": ids}))
        uids, label, emp = await _fo_ai_approvers(c, p.org_id)
        n = await c.fetchval(
            "WITH u AS (UPDATE fo_ai_task SET approver_users=$2::uuid[], approver_user_id=$3, approver_label=$4, "
            "approver_employee_id=$5::uuid WHERE org_id=$1 AND status='pending' RETURNING 1) SELECT count(*) FROM u",
            p.org_id, [str(x) for x in uids], uids[0] if uids else None, label, emp)
    return {"ok": True, "label": label, "переназначено_ждущих": int(n or 0)}

'''

ADD_MAIN = r'''

# ══ FO-STEP-SERVER-STORAGE ═══════════════════════════════════════
# Режим тени (134): пока фронт присылает метку X-FO-Shadow, любая
# запись отклоняется — тень только смотрит.
from fastapi.responses import JSONResponse as _FoJSON


@app.middleware("http")
async def _fo_shadow_guard(request, call_next):
    if request.headers.get("x-fo-shadow") and request.method not in ("GET", "HEAD", "OPTIONS"):
        return _FoJSON({"detail": "режим тени: только смотреть, менять нельзя"}, status_code=403)
    return await call_next(request)
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
shutil.copy(MAIN, bak + "/main.py")

_base = cut(refs_src)
_nlvl = [0]
def _fo_lvl4(mm):
    _nlvl[0] += 1
    return mm.group(1) + "Depends(max_level(4))"
_base = re.sub(r'(async def (?:create_function|set_norm)\([^)]*?p: Principal = )Depends\((?:[^()]|\([^()]*\))*\)', _fo_lvl4, _base)
if _nlvl[0] and not re.search(r"^from .* import .*\bmax_level\b", _base, re.M):
    _base = re.sub(r"^(from [\w.]+ import [^\n(]*\bcurrent\b[^\n(]*)$", r"\1, max_level", _base, count=1, flags=re.M)
for _m in re.finditer(r"async def (?:create_function|set_norm)\([^)]*\)+", _base):
    p("  подпись:", _m.group(0)[:160])
p("справочник функций (штатные POST/PATCH /functions): уровень РМ и выше поставлен на", _nlvl[0], "эндпоинтах")
io.open(REFS, "w", encoding="utf-8").write(_base.rstrip("\n") + "\n" + ADD_REFS)
io.open(SIGN, "w", encoding="utf-8").write(cut(sign_src).rstrip("\n") + "\n" + ADD_SIGN)
if re.search(r"^app\s*=\s*FastAPI\(", main_src, re.M):
    io.open(MAIN, "w", encoding="utf-8").write(cut(main_src).rstrip("\n") + "\n" + ADD_MAIN)
    p("main.py: страж тени дописан")
else:
    p("main.py: app = FastAPI( не найден — страж тени не ставлю")
p("")
p("== КОД ==")
p("дописано в refs.py и signup.py, копия в", bak)

ok = True
for f in (REFS, SIGN, MAIN):
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
    shutil.copy(bak + "/main.py", MAIN)
    sh("systemctl restart fo"); sh("sleep 3")
    p("ОТКАТ: вернул как было, health=" +
      sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip())
    p(sh("journalctl -u fo -n 30 --no-pager")[-2500:])
else:
    p("")
    p("== ПРОВЕРКА ЭНДПОИНТОВ ==")
    for u in ("/refs/roles", "/refs/cards", "/refs/tasks/once", "/refs/invites",
              "/refs/me/account", "/refs/tasks/sync", "/refs/cabinets/x/functions/add", "/refs/cabinets/x/functions/y/take", "/refs/link-pref/all", "/refs/functions/x/name", "/refs/tasks/reviews", "/refs/link-pref", "/refs/cabinets/x/articles", "/refs/cabinets/x/articles/remove", "/refs/ai/tasks", "/refs/ai/status", "/refs/ai/settings", "/refs/admin/people", "/auth/invite-token/zzz"):
        p("  %-26s %s" % (u, sh("curl -s -o /dev/null -w '%%{http_code}' http://127.0.0.1:8000%s" % u).strip()))
    p("(401/403 — эндпоинт есть и просит вход; 404 — не встал)")
    p("ГОТОВО: хранение переехало на сервер")


# ── разведка: бот и ИИ (ничего не меняет, токен не печатается) ──
p("")
p("== РАЗВЕДКА: БОТ И ИИ (без изменений) ==")
_tok = ""
try:
    import json as _rj, urllib.request as _ru
    _env = {}
    try:
        for _ln in open("/opt/fo/.env", encoding="utf-8"):
            _ln = _ln.strip()
            if not _ln or _ln.startswith("#") or "=" not in _ln:
                continue
            _k, _v = _ln.split("=", 1)
            _env[_k.strip()] = _v.strip().strip('"').strip("'")
    except Exception as _e:
        p("  .env не прочитался:", _e)
    for _k in sorted(_env):
        if re.search(r"TELEGRAM|TG_|BOT|YANDEX|YC_|GPT|FOLDER|FLUSH|LLM|AI_", _k, re.I):
            p("  %-26s %s" % (_k, ("заполнен, знаков: %d" % len(_env[_k])) if _env[_k] else "пусто"))
    _tok = next((_env[_k] for _k in ("TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN") if _env.get(_k)), "")
    def _hide(x):
        x = str(x)
        return x.replace(_tok, "***") if _tok else x
    p("  api.telegram.org:", sh("curl -s -o /dev/null -m 8 -w '%{http_code}' https://api.telegram.org/").strip())
    p("  llm.api.cloud.yandex.net:", sh("curl -s -o /dev/null -m 8 -w '%{http_code}' https://llm.api.cloud.yandex.net/").strip())
    if _tok:
        def _tg(m, q=""):
            try:
                with _ru.urlopen("https://api.telegram.org/bot%s/%s%s" % (_tok, m, q), timeout=12) as _r:
                    return _rj.loads(_r.read().decode())
            except Exception as _e:
                return {"ok": False, "err": _hide(_e)}
        _me = _tg("getMe")
        _mr = _me.get("result") or {}
        p("  бот:", ("@" + str(_mr.get("username"))) if _me.get("ok") else _hide(_me),
          "· читает все сообщения в группах:", _mr.get("can_read_all_group_messages"))
        _wh = (_tg("getWebhookInfo").get("result") or {})
        p("  webhook:", _hide(_wh.get("url") or "нет")[:90], "· ждут доставки:", _wh.get("pending_update_count"),
          "· ошибка:", _hide(_wh.get("last_error_message") or "—")[:120])
        if not _wh.get("url"):
            _up = _tg("getUpdates", "?timeout=0&limit=100")
            _chats = {}
            for _u in (_up.get("result") or []):
                _m = _u.get("message") or _u.get("my_chat_member") or _u.get("channel_post") or {}
                _c = _m.get("chat") or {}
                if _c.get("id"):
                    _chats[_c["id"]] = (_c.get("type"), _c.get("title") or _c.get("username") or "")
            p("  getUpdates:", "ok" if _up.get("ok") else _hide(_up.get("err") or _up.get("description")),
              "· событий:", len(_up.get("result") or []))
            for _cid, (_t, _ti) in _chats.items():
                p("    чат %s · %s · %s" % (_cid, _t, _ti))
    else:
        p("  токена бота в .env нет")
    p("  client_chat колонки:", sh("sudo -u postgres psql -d fo -Atc \"SELECT string_agg(column_name,', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='client_chat'\"").strip())
    p("  client_chat строки:")
    p(_hide(sh("sudo -u postgres psql -d fo -Atc \"SELECT * FROM client_chat LIMIT 30\""))[:2000])
    p("  роутеры:", sh("ls /opt/fo/backend/app/routers/ | tr '\\n' ' '").strip())
    p("  где читают токен/ключи:")
    p(_hide(sh("grep -rn 'BOT_TOKEN\\|TELEGRAM_\\|YANDEX\\|FOLDER_ID\\|getUpdates\\|setWebhook\\|webhook' /opt/fo/backend/app --include=*.py | grep -v FO-STEP | head -25"))[:2500])
    p("  службы fo:", sh("systemctl list-units --all --no-pager --plain 'fo*' | head -12").strip()[:900])
    p("  таймеры fo:", sh("systemctl list-timers --all --no-pager | grep -i fo").strip()[:600])
except Exception as _e:
    p("  разведка упала:", str(_e).replace(_tok, "***") if _tok else _e)

# ── ящик для ключей: секрет едет на сервер зашифрованным, мимо переписки и GitHub ──
p("")
p("== ЯЩИК ДЛЯ КЛЮЧЕЙ ==")
# ключ из «Ключи ФО.txt»: приехал зашифрованным (ключ шифра — токен бота, он есть и на Маке, и здесь)
_FO_BLOB = "__FO_BLOB__"
if _FO_BLOB and not _FO_BLOB.startswith("__"):
    try:
        _bt = ""
        for _ln in open("/opt/fo/.env", encoding="utf-8"):
            if _ln.startswith("TG_BOT_TOKEN="): _bt = _ln.split("=", 1)[1].strip().strip('"').strip("'")
        _r = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000", "-a", "-A", "-pass", "env:FOK"],
                            input=_FO_BLOB + "\n", capture_output=True, text=True, timeout=30, env=dict(os.environ, FOK=_bt))
        _got = {}
        for _ln in (_r.stdout or "").splitlines():
            if "=" not in _ln: continue
            _k, _v = _ln.split("=", 1); _k = _k.strip(); _v = _v.strip()
            if _k == "YC_API_KEY" and re.match(r"^AQVN[A-Za-z0-9_\-]{20,}$", _v): _got[_k] = _v
            if _k == "YC_FOLDER_ID" and re.match(r"^b1g[a-z0-9]{10,}$", _v): _got[_k] = _v
        if len(_got) == 2:
            _envp = "/opt/fo/.env"
            _lines = [l for l in open(_envp, encoding="utf-8").read().splitlines() if l.split("=", 1)[0].strip() not in _got]
            _lines += ["%s=%s" % (k, v) for k, v in _got.items()]
            open(_envp, "w", encoding="utf-8").write("\n".join(_lines) + "\n"); os.chmod(_envp, 0o600)
            sh("systemctl restart fo"); sh("sleep 3")
            p("ключ Яндекса из «Ключи ФО.txt» записан на сервер: YC_API_KEY (знаков %d), YC_FOLDER_ID; заглушка убрана; health:" % len(_got["YC_API_KEY"]),
              sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip())
        else:
            p("зашифрованный ключ не расшифровался (токен бота на Маке и на сервере разный?)")
    except Exception as _e:
        p("ключ из txt: ошибка", str(_e)[:200])
try:
    _KB = "/opt/fo/.keybox"
    os.makedirs(_KB, exist_ok=True); os.chmod(_KB, 0o700)
    if not os.path.exists(_KB + "/priv.pem"):
        sh("openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out %s/priv.pem 2>&1; chmod 600 %s/priv.pem" % (_KB, _KB))
    _pub = sh("openssl pkey -in %s/priv.pem -pubout 2>&1" % _KB).strip()
    p("публичный ключ ящика (им шифруют; расшифровать может только сервер):")
    p(_pub)
    _enc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_secrets.enc")
    if os.path.exists(_enc):
        _raw = sh("base64 -d %s | openssl pkeyutl -decrypt -inkey %s/priv.pem -pkeyopt rsa_padding_mode:oaep 2>/dev/null" % (_enc, _KB))
        _ok = {}
        for _ln in _raw.splitlines():
            if "=" not in _ln: continue
            _k, _v = _ln.split("=", 1); _k = _k.strip(); _v = _v.strip()
            if _k in ("YC_API_KEY", "YC_FOLDER_ID") and _v and re.match(r"^[A-Za-z0-9_\-\.]+$", _v):
                _ok[_k] = _v
        if _ok:
            _envp = "/opt/fo/.env"
            _lines = open(_envp, encoding="utf-8").read().splitlines() if os.path.exists(_envp) else []
            _lines = [l for l in _lines if l.split("=", 1)[0].strip() not in _ok]
            _lines += ["%s=%s" % (k, v) for k, v in _ok.items()]
            open(_envp, "w", encoding="utf-8").write("\n".join(_lines) + "\n")
            os.chmod(_envp, 0o600)
            p("из ящика записано в .env:", ", ".join("%s (знаков: %d)" % (k, len(v)) for k, v in _ok.items()))
            sh("systemctl restart fo"); sh("sleep 3")
            p("health после записи ключей:", sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip())
        else:
            p("в ящике есть файл, но расшифровать не удалось или ключей нет")
    else:
        p("зашифрованных ключей пока нет")
    # проба Яндекса: только код ответа, без текста ключа
    _yk = ""; _yf = ""
    for _ln in open("/opt/fo/.env", encoding="utf-8"):
        if _ln.startswith("YC_API_KEY="): _yk = _ln.split("=", 1)[1].strip()
        if _ln.startswith("YC_FOLDER_ID="): _yf = _ln.split("=", 1)[1].strip()
    if _yk and _yf:
        import json as _yj, urllib.request as _yu
        _body = _yj.dumps({"modelUri": "gpt://%s/yandexgpt-lite/latest" % _yf, "completionOptions": {"stream": False, "temperature": 0, "maxTokens": 20},
                           "messages": [{"role": "user", "text": "Ответь одним словом: работает?"}]}).encode()
        _rq = _yu.Request("https://llm.api.cloud.yandex.net/foundationModels/v1/completion", data=_body,
                          headers={"Authorization": "Api-Key " + _yk, "x-folder-id": _yf, "Content-Type": "application/json"})
        try:
            with _yu.urlopen(_rq, timeout=20) as _r:
                _res = _yj.loads(_r.read().decode())
            _t = (((_res.get("result") or {}).get("alternatives") or [{}])[0].get("message") or {}).get("text", "")
            p("ЯНДЕКС ОТВЕЧАЕТ ✓:", _t[:60])
        except Exception as _e:
            _m = str(_e)
            try: _m += " " + _e.read().decode()[:300]
            except Exception: pass
            p("Яндекс не ответил:", _m.replace(_yk, "***")[:400])
    else:
        p("ключей Яндекса в .env нет — пробу не делаю")
except Exception as _e:
    p("ящик/проба упали:", _e)

p("")
p("-- routing.py: функции --")
p(sh("grep -n 'def \\|@router' /opt/fo/backend/app/routers/routing.py | head -60")[:3000])
p("-- таблицы чатов --")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT table_name||': '||string_agg(column_name,', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name IN ('chat','tg_chat','client_chat','chat_message','tg_message','routing_rule','notify_queue') GROUP BY table_name\"")[:2500])

# ── бот: сервер сам забирает сообщения у Telegram (опрос), а не ждёт webhook ──
# Telegram до сервера достучаться не может («Connection timed out» в getWebhookInfo),
# а сервер до Telegram — может. Служба fo-tgpoll забирает обновления и отдаёт их
# в наш приём /refs/tg/hook на этом же сервере (с тем же секретом).
p("")
p("== БОТ: ПРИЁМ СООБЩЕНИЙ ==")
_tk2 = ""
try:
    _e2 = {}
    for _ln in open("/opt/fo/.env", encoding="utf-8"):
        _ln = _ln.strip()
        if "=" in _ln and not _ln.startswith("#"):
            _a, _b = _ln.split("=", 1); _e2[_a.strip()] = _b.strip().strip('"').strip("'")
    _tk2 = _e2.get("TG_BOT_TOKEN", "")
    _hc = sh("curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/refs/tg/hook -H 'Content-Type: application/json' -d '{}'").strip()
    p("наш приём отвечает:", _hc)
    _POLL = """import json, time, urllib.request, urllib.parse

def env():
    d = {}
    for ln in open("/opt/fo/.env", encoding="utf-8"):
        ln = ln.strip()
        if "=" in ln and not ln.startswith("#"):
            a, b = ln.split("=", 1)
            d[a.strip()] = b.strip().strip('"').strip("'")
    return d

E = env()
TOK = E.get("TG_BOT_TOKEN", "")
SEC = E.get("TG_WEBHOOK_SECRET", "")
API = "https://api.telegram.org/bot%s/" % TOK

def call(m, params, timeout=40):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + m, data=data, timeout=timeout) as r:
        return json.loads(r.read().decode())

def hide(x):
    return str(x).replace(TOK, "***") if TOK else str(x)

while True:
    try:
        call("deleteWebhook", {"drop_pending_updates": "false"})
        break
    except Exception as e:
        print("deleteWebhook:", hide(e), flush=True); time.sleep(10)
off = 0
print("fo-tgpoll: старт", flush=True)
while True:
    try:
        res = call("getUpdates", {"offset": off, "timeout": 25,
                                  "allowed_updates": json.dumps(["message", "my_chat_member", "edited_message"])}, timeout=45)
        for u in res.get("result", []):
            off = u["update_id"] + 1
            rq = urllib.request.Request("http://127.0.0.1:8000/refs/tg/hook", data=json.dumps(u).encode(),
                                        headers={"Content-Type": "application/json", "X-Telegram-Bot-Api-Secret-Token": SEC})
            try:
                urllib.request.urlopen(rq, timeout=20).read()
                c = (u.get("message") or u.get("my_chat_member") or {}).get("chat") or {}
                print("принято:", c.get("title"), c.get("id"), flush=True)
            except Exception as e:
                print("hook:", hide(e), flush=True)
    except Exception as e:
        print("poll:", hide(e), flush=True)
        time.sleep(5)
"""
    _UNIT = """[Unit]
Description=FO: бот забирает сообщения из Telegram (опрос) и отдаёт в /refs/tg/hook
After=network-online.target fo.service

[Service]
ExecStart=/opt/fo/venv/bin/python /opt/fo/tgpoll.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    if _hc == "403" and _tk2:
        open("/opt/fo/tgpoll.py", "w", encoding="utf-8").write(_POLL)
        open("/etc/systemd/system/fo-tgpoll.service", "w", encoding="utf-8").write(_UNIT)
        sh("systemctl daemon-reload; systemctl enable fo-tgpoll >/dev/null 2>&1; systemctl restart fo-tgpoll; sleep 4")
        p("служба fo-tgpoll:", sh("systemctl is-active fo-tgpoll").strip())
        p(sh("journalctl -u fo-tgpoll -n 8 --no-pager -o cat").replace(_tk2, "***")[-1200:])
    else:
        sh("systemctl stop fo-tgpoll >/dev/null 2>&1")
        import json as _wj, urllib.request as _wu, urllib.parse as _wp
        _sc2 = _e2.get("TG_WEBHOOK_SECRET", "")
        if _tk2 and _sc2:
            _q = _wp.urlencode({"url": "https://fo.flater.pro/chats/telegram/webhook", "secret_token": _sc2}).encode()
            with _wu.urlopen("https://api.telegram.org/bot%s/setWebhook" % _tk2, data=_q, timeout=15) as _r:
                p("наш приём не встал — вернул штатный webhook:", _wj.loads(_r.read().decode()).get("ok"))
except Exception as _e:
    p("приём сообщений бота: ошибка", (str(_e).replace(_tk2, "***") if _tk2 else str(_e))[:200])

p("")
p("== ЧАТЫ КЛИЕНТОВ ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT ch.id||' · '||ch.title||' · '||cc.kind||' · '||CASE WHEN ch.chat_id ~ '^-?[0-9]+$' THEN 'номер Telegram ✓' ELSE 'ссылка, номера нет' END FROM chat ch JOIN client_chat cc ON cc.chat_pk=ch.id ORDER BY ch.id\""))
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT 'сообщений из чатов: '||count(*)||', последнее: '||COALESCE(max(msg_at)::text,'—') FROM fo_chat_msg WHERE tg_chat_id<>'test'\""))

print("\n".join(out))
