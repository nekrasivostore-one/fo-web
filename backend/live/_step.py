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
ALTER TABLE fo_ai_task ADD COLUMN IF NOT EXISTS extra jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE TABLE IF NOT EXISTS fo_state (
  org_id uuid NOT NULL, scope text NOT NULL, key text NOT NULL,
  data jsonb NOT NULL DEFAULT 'null'::jsonb, updated_at timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  PRIMARY KEY (org_id, scope, key));
GRANT SELECT, INSERT, UPDATE, DELETE ON fo_state TO fo;
-- 219: планёрки — график и статус по клиенту, рассылка волнами; функция кабинета — по дням свой ведущий
CREATE TABLE IF NOT EXISTS fo_meet (
  org_id uuid NOT NULL, client_id uuid NOT NULL,
  slots jsonb NOT NULL DEFAULT '{}'::jsonb, fixed boolean NOT NULL DEFAULT false, since date,
  status text NOT NULL DEFAULT 'draft', kind text, offer jsonb, wave int, level int, camp_id bigint,
  rounds int NOT NULL DEFAULT 0, attn text, reminded date,
  tg_chat_id text, msg_id bigint, pin_msg_id bigint, pinned boolean NOT NULL DEFAULT false,
  sent_at timestamptz, answered_at timestamptz, agreed_at timestamptz, answer text,
  log jsonb NOT NULL DEFAULT '[]'::jsonb, updated_at timestamptz NOT NULL DEFAULT now(), updated_by uuid,
  PRIMARY KEY (org_id, client_id));
CREATE TABLE IF NOT EXISTS fo_meet_camp (
  id bigserial PRIMARY KEY, org_id uuid NOT NULL, started_by uuid, started_at timestamptz NOT NULL DEFAULT now(),
  wave int NOT NULL DEFAULT -1, wave_at timestamptz, gap_min int NOT NULL DEFAULT 180,
  test boolean NOT NULL DEFAULT false, status text NOT NULL DEFAULT 'active', note text);
CREATE INDEX IF NOT EXISTS fo_meet_camp_org_idx ON fo_meet_camp (org_id, status);
ALTER TABLE fo_cabinet_fn_cfg ADD COLUMN IF NOT EXISTS day_cfg jsonb;
GRANT SELECT, INSERT, UPDATE, DELETE ON fo_meet, fo_meet_camp TO fo;
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
    out = await _fo_cards_scope(p, out)
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
    return await _fo_scope_rows(p, [_fo_once_row(r) for r in rows], "employee_id")


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
    day_cfg: dict | None = None        # 219: по дням свой ответственный и минуты {"0": {"e": "<сотрудник>", "m": 60}}


def _fo_dc_parse(v):
    """219: {"0": {"e": "<uuid>", "m": 60}} → {0: (UUID|None, минуты|None)}."""
    import uuid as _uu
    if isinstance(v, str):
        try:
            v = _fo_json.loads(v)
        except Exception:
            v = None
    out = {}
    if isinstance(v, dict):
        for k, x in v.items():
            try:
                wd = int(k)
            except Exception:
                continue
            if not (0 <= wd <= 6) or not isinstance(x, dict):
                continue
            e = m = None
            try:
                e = _uu.UUID(str(x.get("e"))) if x.get("e") else None
            except Exception:
                e = None
            try:
                m = max(1, min(2880, int(x.get("m")))) if x.get("m") else None
            except Exception:
                m = None
            out[wd] = (e, m)
    return out


async def _fo_daycfg(c, org_id, fid, dc):
    """Проверка: сотрудники по дням — из агентства; генератор их видит (employee_fn). Вернёт JSON или None."""
    if not dc:
        return None
    norm = {}
    for wd, (e, m) in _fo_dc_parse(dc).items():
        if e:
            if not await c.fetchval("SELECT 1 FROM employee WHERE id=$1 AND org_id=$2", e, org_id):
                raise HTTPException(400, "сотрудник на день недели не из этого агентства")
            await c.execute("INSERT INTO employee_fn (employee_id, fn_id, allowed) VALUES ($1, $2::uuid, true) "
                            "ON CONFLICT DO NOTHING", e, str(fid))
        norm[str(wd)] = {"e": str(e) if e else None, "m": m}
    return _fo_json.dumps(norm) if norm else None


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
        _dcold = {}
        for _r in await c.fetch("SELECT fn_id, day_cfg FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1::uuid AND day_cfg IS NOT NULL", cab_id):
            _dcold[str(_r["fn_id"])] = _r["day_cfg"]
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
                _dc = (await _fo_daycfg(c, p.org_id, fid, it.day_cfg)) if it.day_cfg is not None else _dcold.get(fid)
                await c.execute(
                    """INSERT INTO fo_cabinet_fn_cfg
                         (cabinet_id, fn_id, org_id, employee_id, minutes, cycle_kind, cycle_n, cycle_weekdays, day_cfg)
                       VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5, $6, $7, $8, $9::jsonb)""",
                    cab_id, fid, p.org_id, emp,
                    (max(1, min(2880, int(it.minutes))) if it.minutes else None),
                    (it.cycle_kind or None), it.cycle_n, it.cycle_weekdays, _dc)
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
        _dc = await c.fetchval("SELECT day_cfg FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1::uuid AND fn_id=$2::uuid", cab_id, fid)
        if it.day_cfg is not None:
            _dc = await _fo_daycfg(c, p.org_id, fid, it.day_cfg)
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
                     (cabinet_id, fn_id, org_id, employee_id, minutes, cycle_kind, cycle_n, cycle_weekdays, day_cfg)
                   VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5, $6, $7, $8, $9::jsonb)""",
                cab_id, fid, p.org_id, emp,
                (max(1, min(2880, int(it.minutes))) if it.minutes else None),
                (it.cycle_kind or None), it.cycle_n, it.cycle_weekdays, _dc)
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
                  g.employee_id AS wanted, g.day_cfg
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
        dc = _fo_dc_parse(r["day_cfg"])      # 219: по дням свой ответственный — ниже, по каждой задаче
        # сменили ответственного - будущие несделанные задачи переезжают к нему
        if (not dc) and old is not None and key in old and old.get(key) != r["wanted"] and r["wanted"]:
            res = await c.execute(
                """UPDATE task SET assignee_id=$4::uuid
                    WHERE org_id=$1 AND cabinet_id=$2::uuid AND fn_id=$3::uuid
                      AND source='generator' AND status='planned' AND plan_date >= $5
                      AND assignee_id IS DISTINCT FROM $4::uuid""",
                org_id, r["cabinet_id"], r["fn_id"], r["wanted"], start)
            moved += _fo_n(res)
        # норма времени - на будущие несделанные
        if not dc:
          await c.execute(
            """UPDATE task SET plan_minutes=$4
                WHERE org_id=$1 AND cabinet_id=$2::uuid AND fn_id=$3::uuid
                  AND source='generator' AND status='planned' AND plan_date >= $5
                  AND plan_minutes IS DISTINCT FROM $4""",
            org_id, r["cabinet_id"], r["fn_id"], int(r["minutes"] or 30), start)
        have = await c.fetch(
            """SELECT id, plan_date, status, assignee_id, plan_minutes FROM task
                WHERE org_id=$1 AND cabinet_id=$2::uuid AND fn_id=$3::uuid
                  AND source='generator' AND plan_date >= $4 AND plan_date <= $5""",
            org_id, r["cabinet_id"], r["fn_id"], horizon[0], horizon[-1])
        by_day = {}
        for h in have:
            by_day.setdefault(h["plan_date"], []).append(h)
        if dc:
            for h in have:
                if h["status"] != "planned" or h["plan_date"] < start:
                    continue
                _e, _m = dc.get(h["plan_date"].weekday(), (None, None))
                _e = _e or r["wanted"]
                _m = int(_m or r["minutes"] or 30)
                if _e and h["assignee_id"] != _e:
                    await c.execute("UPDATE task SET assignee_id=$2 WHERE id=$1", h["id"], _e)
                    moved += 1
                if h["plan_minutes"] != _m:
                    await c.execute("UPDATE task SET plan_minutes=$2 WHERE id=$1", h["id"], _m)
        for d in horizon:
            due = _fo_due(r["cycle_kind"], r["cycle_n"], r["cycle_weekdays"], d)
            if due and d not in by_day:
                _e, _m = dc.get(d.weekday(), (None, None))
                who = await _fo_pick(c, org_id, r["fn_id"], _e or r["wanted"], d)
                await c.execute(
                    """INSERT INTO task (org_id, kind, fn_id, client_id, cabinet_id, title,
                                         source, assignee_id, plan_date, plan_minutes)
                       VALUES ($1,'cyclic',$2,$3,$4,$5,'generator',$6,$7,$8)
                       ON CONFLICT DO NOTHING""",
                    org_id, r["fn_id"], r["client_id"], r["cabinet_id"],
                    "%s · %s" % (r["fn"], r["cabinet"]), who, d, int(_m or r["minutes"] or 30))
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
        try:
            if await _fo_promise_apply(c, u):
                u = await c.fetchrow(
            "SELECT u.id, u.email, u.role_code, u.created_at, u.first_login, "
            "       u.phone, u.display_name, u." + _FO_NAME_COL + " AS base_name, "
            "       r.level, r.__ROLE_TITLE__ AS role_title, "
            "       o.name AS org_name, o.invite_code, o.id AS org_id "
            "FROM app_user u JOIN role r ON r.code = u.role_code "
            "JOIN org o ON o.id = u.org_id WHERE u.id = $1", uid)
        except Exception:
            pass
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







# ══ СОСТОЯНИЕ АГЕНТСТВА НА СЕРВЕРЕ (123, 25.09) ═════════════════════
# Всё, что жило в браузере или только в памяти вкладки, — здесь:
# настройки ролей, выданные доступы, обещанные уровни, история
# поставленных задач и черновики, замеры скорости и таймеры, регламенты,
# лиды, рекомендации по грейду, прайс тарифов. Браузер — не хранилище.
# Ключ: (где живёт, как сливать, кто пишет — уровень ≤, кто читает — уровень ≤, предел списка)
#   org — общее для агентства; me — своё у каждого человека; svc — общее для сервиса (прайс).
#   obj — целиком; list — по id (add / remove); map — по ключам (set / delete).
from typing import Any as _FoAny
_FO_ST_ZERO = "00000000-0000-0000-0000-000000000000"
_FO_ST_KEYS = {
    "roleCfg":  ("org", "obj",  2, 9, 0),
    "access":   ("org", "list", 3, 3, 500),
    "promised": ("org", "map",  3, 3, 0),
    "speed":    ("org", "list", 9, 9, 3000),
    "regDocs":  ("org", "list", 3, 9, 500),
    "regUniq":  ("org", "map",  3, 9, 0),
    "leads":    ("org", "list", 4, 4, 2000),
    "gradeRec": ("org", "map",  2, 3, 0),
    "placed":   ("me",  "list", 9, 9, 200),
    "drafts":   ("me",  "list", 9, 9, 200),
    "runs":     ("me",  "obj",  9, 9, 0),
    "tariff":   ("svc", "obj",  0, 9, 0),
    # 28.09: нашлось при проверке сборки — жило в браузере или во вкладке
    "meet":     ("org", "map",  4, 4, 0),      # планёрка по кабинету: темы, проблемы и решения, особенности, шпаргалка, история
    "meetPlan": ("org", "map",  4, 4, 0),      # график планёрок: дни, время, длительность, кто ведёт
    "catDays":  ("org", "obj",  4, 9, 0),
    "aodAuto":  ("org", "obj",  4, 9, 0),
    "aodTime":  ("org", "obj",  4, 9, 0),
    "grades":   ("org", "obj",  2, 3, 0),
    "settings": ("org", "obj",  1, 9, 0),
    "tpl":      ("org", "map",  4, 9, 0),
    "log":      ("org", "list", 9, 4, 1000),
}
_FO_ST_FRONT = {"access", "leads", "placed", "drafts", "log"}   # новые записи — в начало списка


def _fo_st_lvl(p):
    try:
        return int(getattr(p, "level", 9))
    except Exception:
        return 9


def _fo_st_where(key, p):
    sc = _FO_ST_KEYS[key][0]
    if sc == "svc":
        return _FO_ST_ZERO, "svc"
    if sc == "me":
        return str(p.org_id), "u:" + str(_fo_uid(p))
    return str(p.org_id), "org"


def _fo_st_load(v):
    if isinstance(v, str):
        try:
            return _fo_json.loads(v)
        except Exception:
            return None
    return v


@router.get("/state")
async def fo_state_get(p: Principal = Depends(current)):
    """Всё сохранённое состояние, которое этому человеку положено видеть."""
    lvl = _fo_st_lvl(p)
    out = {"org": {}, "me": {}, "svc": {}}
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT scope, key, data, updated_at FROM fo_state WHERE (org_id=$1::uuid AND scope IN ('org', $2)) "
            "OR (org_id=$3::uuid AND scope='svc')", str(p.org_id), "u:" + str(_fo_uid(p)), _FO_ST_ZERO)
    for r in rows:
        k = r["key"]
        spec = _FO_ST_KEYS.get(k)
        if not spec or lvl > spec[3]:
            continue
        sc = "me" if str(r["scope"]).startswith("u:") else r["scope"]
        out[sc][k] = _fo_st_load(r["data"])
    out["keys"] = {k: {"scope": v[0], "type": v[1], "write": lvl <= v[2]} for k, v in _FO_ST_KEYS.items() if lvl <= v[3]}
    return out


class FoStIn(_FoBM):
    data: _FoAny = None          # obj — целиком; list — замена целиком (только первая загрузка)
    add: list | None = None      # list: записи с id — добавить или заменить
    remove: list | None = None   # list: id — убрать
    set: dict | None = None      # map: ключ → значение
    delete: list | None = None   # map: ключи — убрать
    only_if_empty: bool = False  # перенос из браузера: записать, только если на сервере ещё пусто


@router.post("/state/{key}")
async def fo_state_put(key: str, body: FoStIn, p: Principal = Depends(current)):
    spec = _FO_ST_KEYS.get(key)
    if not spec:
        raise HTTPException(404, "такого раздела нет")
    lvl = _fo_st_lvl(p)
    if lvl > spec[2]:
        raise HTTPException(403, "этот раздел правят старшие роли")
    kind, cap = spec[1], spec[4]
    raw = _fo_json.dumps({"data": body.data, "add": body.add, "set": body.set}, ensure_ascii=False, default=str)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "слишком большой объём за один раз")
    org, scope = _fo_st_where(key, p)
    uid = _fo_uid(p)
    async with pool().acquire() as c:
        async with c.transaction():
            await c.execute("INSERT INTO fo_state (org_id, scope, key, data) VALUES ($1::uuid, $2, $3, 'null'::jsonb) "
                            "ON CONFLICT (org_id, scope, key) DO NOTHING", org, scope, key)
            cur = _fo_st_load(await c.fetchval("SELECT data FROM fo_state WHERE org_id=$1::uuid AND scope=$2 AND key=$3 "
                                               "FOR UPDATE", org, scope, key))
            empty = cur is None or cur == [] or cur == {}
            if body.only_if_empty and not empty:
                return {"ok": True, "skipped": "на сервере уже есть данные"}
            if kind == "obj":
                new = body.data
            elif kind == "map":
                new = dict(cur) if isinstance(cur, dict) else {}
                if isinstance(body.data, dict):
                    new = dict(body.data)
                for k2 in (body.delete or []):
                    new.pop(str(k2), None)
                for k2, v2 in (body.set or {}).items():
                    new[str(k2)] = v2
            else:
                lst = list(cur) if isinstance(cur, list) else []
                if isinstance(body.data, list):
                    lst = [x for x in body.data if isinstance(x, dict)]
                rm = {str(x) for x in (body.remove or [])}
                if rm:
                    lst = [x for x in lst if str(x.get("id")) not in rm]
                pos = {str(x.get("id")): i for i, x in enumerate(lst) if isinstance(x, dict) and x.get("id") is not None}
                fresh = []
                for it in (body.add or []):
                    if not isinstance(it, dict) or it.get("id") is None:
                        continue
                    i = pos.get(str(it["id"]))
                    if i is not None:
                        lst[i] = it
                    else:
                        fresh.append(it)
                if key in _FO_ST_FRONT:
                    lst = fresh + lst
                    if cap and len(lst) > cap:
                        lst = lst[:cap]
                else:
                    lst = lst + fresh
                    if cap and len(lst) > cap:
                        lst = lst[-cap:]
                new = lst
            await c.execute("UPDATE fo_state SET data=$4::jsonb, updated_at=now(), updated_by=$5 "
                            "WHERE org_id=$1::uuid AND scope=$2 AND key=$3",
                            org, scope, key, _fo_json.dumps(new, ensure_ascii=False, default=str), uid)
    n = len(new) if isinstance(new, (list, dict)) else 1
    return {"ok": True, "n": n}


async def _fo_promise_apply(c, u):
    """Обещанный уровень: начальник завёл карточку и выбрал, каким уровнем человек войдёт.
    Выдаёт сервер при входе человека — не браузер начальника. Только повышение, не выше директора."""
    d = _fo_st_load(await c.fetchval("SELECT data FROM fo_state WHERE org_id=$1::uuid AND scope='org' AND key='promised'",
                                     str(u["org_id"])))
    if not isinstance(d, dict) or not d:
        return False
    em = str(u["email"] or "").lower()
    nm = str(u["display_name"] or u["base_name"] or "").lower()
    keys = [k for k in (em, em.split("@")[0] if em else "", nm) if k]
    want = next((str(d[k]) for k in keys if d.get(k)), None)
    if not want:
        return False
    wl = await c.fetchval("SELECT level FROM role WHERE code=$1", want)
    ok = wl is not None and int(wl) >= 2 and int(u["level"]) > int(wl)
    if ok:
        await c.execute("UPDATE app_user SET role_code=$2 WHERE id=$1", u["id"], want)
    for k in keys:
        d.pop(k, None)
    await c.execute("UPDATE fo_state SET data=$2::jsonb, updated_at=now() WHERE org_id=$1::uuid AND scope='org' AND key='promised'",
                    str(u["org_id"]), _fo_json.dumps(d, ensure_ascii=False))
    return ok


# ══ ПРОВЕРКА РОЛЕЙ (28.09): что каждый человек агентства видит на самом деле ══
# Виталий: «Проверь, чтобы при каждом новом кабинете у каждого менеджера
# отображались задачи; чтобы менеджеры под своим доступом видели все свои задачи.
# Проверь каждую роль». Сервер сам ходит к себе от имени каждого человека
# (его доступ, только чтение, пометка тени — запись отклонится) и сводит:
# связана ли карточка сотрудника с аккаунтом, сколько своих задач на неделе он
# получает, сколько чужих, разовые, согласования, частное в карточках. Плюс по
# каждому кабинету: у каждой назначенной функции есть ли задачи у ответственного.
import urllib.error as _fo_ue


def _fo_diag_get(tok, path):
    rq = _fo_ur.Request("http://127.0.0.1:8000" + path,
                        headers={"Authorization": "Bearer " + str(tok), "x-fo-shadow": "diag"})
    try:
        with _fo_ur.urlopen(rq, timeout=20) as r:
            tx = r.read().decode() or "null"
            try:
                return r.status, _fo_json.loads(tx)
            except Exception:
                return r.status, None
    except _fo_ue.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)[:120]


_FO_DIAG_PRIVATE = re.compile(r"phone|tel|owner|sobst|собств|sum|price|amount|money|pay|salary|oklad|оклад|sheet|table|tg|telegram|inn|email|mail", re.I)


@router.get("/diag/roles")
async def fo_diag_roles(p: Principal = Depends(max_level(2))):
    org = str(p.org_id)
    today = _fo_msk_today()
    mon = today - _fo_dt.timedelta(days=today.weekday())
    week = [mon + _fo_dt.timedelta(days=i) for i in range(5)]
    async with pool().acquire() as c:
        users = await c.fetch(
            "SELECT u.id, u.email, u.org_id, u.role_code, u.display_name, r.level FROM app_user u "
            "JOIN role r ON r.code=u.role_code WHERE u.org_id=$1::uuid AND u.is_active ORDER BY r.level, u.email", org)
        emps = await c.fetch("SELECT id, name, user_id, is_active FROM employee WHERE org_id=$1::uuid", org)
        cabs = await c.fetch("SELECT cb.id, cb.name, cl.name AS client FROM cabinet cb JOIN client cl ON cl.id=cb.client_id "
                             "WHERE cl.org_id=$1::uuid ORDER BY cl.name, cb.name", org)
        cab_ids = [str(x["id"]) for x in cabs]
        cfg = await c.fetch(
            "SELECT g.cabinet_id, g.fn_id, g.employee_id, g.cycle_kind, f.code, f.name, e.name AS emp "
            "FROM fo_cabinet_fn_cfg g JOIN fn f ON f.id=g.fn_id LEFT JOIN employee e ON e.id=g.employee_id "
            "WHERE g.cabinet_id = ANY($1::uuid[])", cab_ids) if cab_ids else []
        tk = await c.fetch(
            "SELECT cabinet_id, fn_id, assignee_id, count(*) AS n, min(plan_date) AS first FROM task "
            "WHERE cabinet_id = ANY($1::uuid[]) AND plan_date BETWEEN $2 AND $3 AND status <> 'removed' GROUP BY 1,2,3",
            cab_ids, today, today + _fo_dt.timedelta(days=14)) if cab_ids else []
    emp_by_user = {str(e["user_id"]): e for e in emps if e["user_id"]}
    emp_name = {str(e["id"]): e["name"] for e in emps}
    # 1) кабинеты: у каждой функции с ответственным — задачи у него на 2 недели
    tmap = {}
    for r in tk:
        tmap.setdefault((str(r["cabinet_id"]), str(r["fn_id"])), {})[str(r["assignee_id"])] = (int(r["n"]), str(r["first"]))
    cab_out = []
    for cb in cabs:
        rows, gaps = [], 0
        for g in [x for x in cfg if str(x["cabinet_id"]) == str(cb["id"])]:
            got = tmap.get((str(cb["id"]), str(g["fn_id"])), {})
            mine = got.get(str(g["employee_id"])) if g["employee_id"] else None
            others = {emp_name.get(k, k): v[0] for k, v in got.items() if k != str(g["employee_id"])}
            state = "ok" if mine else ("нет ответственного" if not g["employee_id"] else "нет задач на 2 недели")
            if state != "ok":
                gaps += 1
            rows.append({"функция": "%s %s" % (g["code"], g["name"]), "ответственный": g["emp"] or "—",
                         "цикл": g["cycle_kind"] or "базовый", "задач_у_него": mine[0] if mine else 0,
                         "первая": mine[1] if mine else None, "у_других": others, "итог": state})
        cab_out.append({"кабинет": "%s · %s" % (cb["client"], cb["name"]), "функций": len(rows), "проблем": gaps, "функции": rows})
    # 2) люди: что сервер отдаёт каждому под его доступом
    ppl = []
    for u in users:
        e = emp_by_user.get(str(u["id"]))
        row = {"имя": u["display_name"] or u["email"], "почта": u["email"], "роль": u["role_code"], "уровень": int(u["level"]),
               "карточка_сотрудника": (e["name"] if e else None), "ошибки": []}
        if not e and int(u["level"]) >= 3:
            row["ошибки"].append("аккаунт не связан с карточкой сотрудника — «мои задачи» будут пустыми")
        try:
            tok = _fo_make_access_for(u)
            if isinstance(tok, (tuple, list)):
                tok = tok[0]
            if isinstance(tok, dict):
                tok = tok.get("access") or tok.get("token") or tok.get("access_token")
        except Exception as ex:
            row["ошибки"].append("доступ не собрался: %s" % str(ex)[:100])
            ppl.append(row)
            continue
        my = str(e["id"]) if e else "-"
        mine = oth = 0
        for d in week:
            st, js = await _fo_aio.to_thread(_fo_diag_get, tok, "/tasks/day?day=" + d.isoformat())
            if st != 200:
                row["ошибки"].append("задачи дня %s: код %s" % (d.isoformat(), st))
                continue
            for t in (js or []):
                if str(t.get("assignee_id")) == my:
                    mine += 1
                else:
                    oth += 1
        row["задач_недели_своих"] = mine
        row["задач_недели_чужих_видно"] = oth
        st, js = await _fo_aio.to_thread(_fo_diag_get, tok, "/refs/tasks/once")
        row["разовых_своих"] = len([x for x in (js or []) if str(x.get("employee_id")) == my]) if st == 200 else "код %s" % st
        st, js = await _fo_aio.to_thread(_fo_diag_get, tok, "/refs/employees")
        row["видит_сотрудников"] = len(js or []) if st == 200 else "код %s" % st
        if st == 200 and e and not any(str(x.get("id")) == my for x in (js or [])):
            row["ошибки"].append("своей карточки нет в списке сотрудников")
        st, js = await _fo_aio.to_thread(_fo_diag_get, tok, "/refs/clients")
        row["видит_клиентов"] = len(js or []) if st == 200 else "код %s" % st
        st, js = await _fo_aio.to_thread(_fo_diag_get, tok, "/refs/tasks/reviews")
        row["согласований"] = len(js or []) if st == 200 and isinstance(js, list) else "код %s" % st
        st, js = await _fo_aio.to_thread(_fo_diag_get, tok, "/refs/cards")
        if st == 200:
            priv = {}
            for cd in (js or []):
                if cd.get("kind") in ("cab", "client", "employee"):
                    ks = [k for k, v in (cd.get("data") or {}).items() if v not in (None, "", [], {}) and _FO_DIAG_PRIVATE.search(k)]
                    if cd.get("kind") == "employee" and str(cd.get("ref_id")) == my:
                        ks = []
                    if ks:
                        priv.setdefault(cd.get("kind"), set()).update(ks)
            row["частное_в_карточках"] = {k: sorted(v)[:12] for k, v in priv.items()}
        else:
            row["частное_в_карточках"] = "код %s" % st
        ppl.append(row)
    return {"неделя": [d.isoformat() for d in week], "люди": ppl, "кабинеты": cab_out}


# ══ КАЖДЫЙ ВИДИТ СВОЁ — НА СЕРВЕРЕ (28.09, Виталий: «частное — только старшим», «чужие задачи не отдавать») ══
# Задачи: проджект и выше — все; главный менеджер — свои и младших с ассистентами;
# младший и ассистент — только свои. Экран и раньше прятал чужое, теперь его не
# отдаёт сервер. Частное клиента (сумма, дата платежа, собственник, телефон,
# Telegram, таблица) — проджект и выше. Оклады и проценты премий/штрафов коллег —
# собственник и директор; свою карточку каждый видит целиком.
_FO_PRIV_CLIENT = {"amount", "owner", "payDate", "phone", "sheet", "tg", "telegram", "mail", "email", "inn",
                   "price", "sum", "contract", "payDay", "ownerName", "ownerPhone", "ownerTg", "table"}
_FO_PRIV_PAY = re.compile(r"^(pay|salary|oklad|rate|prem|bonus|fine|shtraf|penalty)", re.I)


async def _fo_scope_ids(c, p):
    """None — видно всё; иначе множество id сотрудников, чьи задачи можно отдать."""
    lvl = _fo_st_lvl(p)
    if lvl <= 4:
        return None
    me = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2::uuid LIMIT 1", _fo_uid(p), str(p.org_id))
    ids = {str(me)} if me else set()
    if lvl == 5:
        for r in await c.fetch(
                "SELECT e.id FROM employee e JOIN app_user u ON u.id=e.user_id JOIN role r ON r.code=u.role_code "
                "WHERE e.org_id=$1::uuid AND r.level >= 6", str(p.org_id)):
            ids.add(str(r["id"]))
    return ids


def _fo_row_get(x, k):
    if isinstance(x, dict):
        return x.get(k)
    try:
        return getattr(x, k)
    except Exception:
        try:
            return x[k]
        except Exception:
            return None


async def _fo_scope_rows(p, rows, field):
    try:
        async with pool().acquire() as c:
            ids = await _fo_scope_ids(c, p)
    except Exception:
        return rows
    if ids is None:
        return rows
    return [x for x in (rows or []) if str(_fo_row_get(x, field)) in ids]


async def _fo_cards_scope(p, out):
    lvl = _fo_st_lvl(p)
    if lvl <= 2:
        return out
    try:
        async with pool().acquire() as c:
            me = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2::uuid LIMIT 1", _fo_uid(p), str(p.org_id))
    except Exception:
        me = None
    res = []
    for cd in out:
        k = cd.get("kind")
        d = cd.get("data") or {}
        if k in ("cab", "client") and lvl >= 5:
            d = {a: b for a, b in d.items() if a not in _FO_PRIV_CLIENT and not str(a).lower().startswith(("owner", "pay", "phone"))}
        elif k == "employee" and str(cd.get("ref_id")) != str(me):
            d = {a: b for a, b in d.items() if not _FO_PRIV_PAY.search(str(a))}
        res.append(dict(cd, data=d))
    return res

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

# Приветствия, прощания, благодарности, мат (Виталий 24.09): такие сообщения в Яндекс не отправляем.
# Решает остаток: если после их удаления в сообщении не осталось слов — это «шум».
# «Почему цена опять 2500, бл*?!» — остаются слова, сообщение уходит на разбор.
_FO_NOISE_RX = [re.compile(x, re.I) for x in (
    r"\b(добр(ый|ое|ого|ой)\s+(день|утро|утра|вечер|вечера|ночи|дня))\b",
    r"\b(здравствуй(те)?|здрасьте|привет(ствую)?|приветик|хай|hello|hi|салют|доброго\s+времени\s+суток)\b",
    r"\b(до\s+свидания|до\s+встречи|до\s+завтра|всего\s+(доброго|хорошего)|хорошего\s+(дня|вечера|выходных)|спокойной\s+ночи|пока(-пока)?|удачи|счастливо)\b",
    r"\b(спасибо(\s+большое)?|благодарю|спс|пасиб[оа]?|мерси|ок(ей)?|окей|ok|хорошо|понял[аи]?|принято|угу|ага|да|нет|супер|отлично|класс)\b",
    r"\b\w*(ху[йеёия]|пизд|бля|бляд|ебан|ебат|еба[лн]|ёб|заеб|наеб|уеб|муда|мудо|пидор|пидар|залуп|гандон|сук[аиу])\w*\b",
    r"\b\w*[a-zа-я]\*+[a-zа-я]*\w*\b",
    r"\b(ну|вот|эх|ох|ах|ой|блин|черт|е-мое|е-мае|ёмаё|мда|хм+)\b",
)]


def _fo_ai_noise(text):
    t = str(text or "").lower().replace("ё", "е")
    for rx in _FO_NOISE_RX:
        t = rx.sub(" ", t)
    words = re.findall(r"[a-zа-я0-9]{2,}", t)
    return len(words) == 0


_FO_AI_SYS = (
    "Ты — ассистент digital-агентства, которое ведёт кабинеты продавцов на Wildberries и OZON: реклама, цены, "
    "карточки товаров, аналитика, поставки, отзывы. Тебе дают новое сообщение из чата с клиентом и контекст. "
    "Реши, просит ли клиент агентство что-то сделать (это задача), или это вопрос, благодарность, информация без действия.\n"
    "Как решать:\n"
    "1. Решаешь только про НОВОЕ сообщение. Предыдущие сообщения — контекст, чтобы понять размытую просьбу; "
    "просьбы из прошлых сообщений заново задачей не ставь.\n"
    "2. Прямая просьба в новом сообщении (сделайте, поменяйте, поднимите, снизьте, добавьте, проверьте, «нужно …», «участвуем в …») — задача.\n"
    "3. Размытая просьба, которая опирается на обсуждение выше («давайте так», «делайте, как обсуждали», «да, запускайте», "
    "обращение «@ник» без текста) — задача: суть собери из контекста.\n"
    "4. Статус, отчёт, информация, обещание написать позже («как примут — напишу», «остатки отображаются корректно», "
    "«колонку выделил»), вопрос без просьбы — не задача.\n"
    "5. Если новое сообщение просит то же, что уже есть в списке «Уже поставленные задачи», или уточняет её "
    "(срок, цифру, артикул), — новую не создавай: верни is_task=true и same_as = номер той задачи, "
    "а в title коротко напиши, что уточнилось.\n"
    "Если это задача — сформулируй её для менеджера агентства коротко и по делу, в повелительном наклонении "
    "(например: «Снизить цену на артикул 153667602 до 1990 ₽»).\n"
    "function_code — к какой функции (блоку работ) относится задача: код из списка «Функции агентства». "
    "Сначала ищи среди отмеченных ★ — они уже есть в этом кабинете; если подходящей там нет — бери из всего списка. "
    "Сравнивай по смыслу, а не буквально: «аб тест», «A/B», «сплит фото» → функция про A/B тест; "
    "«фото», «обложка», «инфографика» → функции фотоворонки. Если ни одна не подходит — null.\n"
    "executor — кто из команды агентства должен сделать задачу по переписке: тот, кого прямо назвали исполнителем "
    "(«@Ihar_emelyanenka, сделайте», «Игорь, посмотри»), или сотрудник, который сам ответил «сделаю», «беру», «займусь». "
    "Пиши имя или @ник из списка «Команда агентства». Не угадывай: если исполнитель из переписки не ясен — null.\n"
    "urgent=true — только если клиент прямо пишет «срочно», «сегодня», «сейчас», называет ближайший час, "
    "или без этого встают продажи; иначе false.\n"
    "deadline — дата и время по Москве в формате YYYY-MM-DD HH:MM, если срок назван или очевиден; иначе null.\n"
    "why — одно предложение: зачем делается задача, что за ней стоит у клиента.\n"
    "goal — одно предложение: какая конечная цель, какой результат для бизнеса клиента.\n"
    "minutes — сколько минут это займёт у менеджера, число от 5 до 240.\n"
    "Ответь только JSON, без пояснений и без markdown:\n"
    "{\"is_task\": true, \"same_as\": null, \"title\": \"...\", \"function_code\": null, \"executor\": null, \"urgent\": false, \"deadline\": null, "
    "\"why\": \"...\", \"goal\": \"...\", \"minutes\": 30}"
)

_FO_AI_CTX_N = 20      # сколько прошлых сообщений чата видит ИИ (Виталий 28.09: «собирай контекст последних 20 сообщений»)
_FO_AI_DUP_DAYS = 2    # за сколько дней искать уже поставленную такую же задачу


def _fo_ai_stems(s):
    t = str(s or "").lower().replace("ё", "е")
    t = re.sub(r"\bтн\s*вэд\b", "тнвэд", t)
    words = re.findall(r"[a-zа-я]{3,}|\d{3,}", t)
    stop = {"для", "что", "это", "как", "все", "всех", "всем", "всеми", "так", "его", "она", "они", "там", "тут",
            "уже", "еще", "пожалуйста", "нужно", "надо", "товар", "товары", "товаре", "товаров", "товарах"}
    return {w if w.isdigit() else w[:5] for w in words if w not in stop}


def _fo_ai_same(a, b):
    """Похожи ли две формулировки задачи настолько, что это одна задача.
    Разные номера артикулов — всегда разные задачи."""
    A, B = _fo_ai_stems(a), _fo_ai_stems(b)
    na = {w for w in A if w.isdigit() and len(w) >= 5}
    nb = {w for w in B if w.isdigit() and len(w) >= 5}
    if na and nb and not (na & nb):
        return False
    if not A or not B:
        return False
    if A == B:
        return True
    k = len(A & B) / float(min(len(A), len(B)))
    return min(len(A), len(B)) >= 3 and k >= 0.75


def _fo_tg_react_emo_sync(chat_id, msg_id, emos):
    tok = _fo_env("TG_BOT_TOKEN")
    if not tok or not chat_id or str(chat_id).startswith("test") or not msg_id:
        return "без реакции"
    last = ""
    for emo in emos:
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
    return _fo_tg_react_emo_sync(chat_id, msg_id, ("\U0001F9D1\u200D\U0001F4BB", "\U0001F468\u200D\U0001F4BB"))


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


async def _fo_ai_people(c, org_id, cab_id, fn_id, named=None, talked=None, mentioned=None):
    """Кандидаты в ответственные. Порядок Виталия (28.09): 1) кого назвали исполнителем в переписке
    (или кто сам ответил «сделаю»); 2) кто ведёт эту функцию в кабинете; 3) кто переписывался по задаче.
    Дальше — кто умеет функцию, ведёт кабинет, его артикулы; минус нагрузка сегодня.
    Собственник и директор — не исполнители."""
    ppl = {}
    named = {str(x) for x in (named or []) if x}
    talked = {str(x) for x in (talked or []) if x}
    mentioned = {str(x) for x in (mentioned or []) if x}

    def get(eid, name):
        k = str(eid)
        return ppl.setdefault(k, {"employee_id": k, "name": name or "", "score": 0.0, "why": [], "f": set()})

    def flag(d, f, score, why):
        if f in d["f"]:
            return
        d["f"].add(f)
        d["score"] += score
        if why:
            d["why"].append(why)

    emps = {}
    try:
        for r in await c.fetch("SELECT id, name FROM employee WHERE org_id=$1 AND is_active", org_id):
            emps[str(r["id"])] = r["name"]
    except Exception:
        pass
    for k in named:
        if k in emps:
            flag(get(k, emps[k]), "named", 40, "назван(а) исполнителем в переписке")
    for k in mentioned - named:
        if k in emps:
            flag(get(k, emps[k]), "ment", 6, "упомянут(а) в переписке")
    for k in talked - named:
        if k in emps:
            flag(get(k, emps[k]), "talk", 8, "писал(а) в переписке по задаче")
    if cab_id:
        try:
            for r in await c.fetch(
                    "SELECT g.employee_id, g.fn_id, e.name FROM fo_cabinet_fn_cfg g JOIN employee e ON e.id=g.employee_id "
                    "WHERE g.cabinet_id=$1::uuid AND g.employee_id IS NOT NULL", str(cab_id)):
                d = get(r["employee_id"], r["name"])
                if fn_id and str(r["fn_id"]) == str(fn_id):
                    flag(d, "fnown", 20, "ведёт эту функцию в кабинете")
                else:
                    flag(d, "cab", 2, "ведёт функции этого кабинета")
        except Exception:
            pass
        try:
            for r in await c.fetch(
                    "SELECT ao.employee_id, e.name, count(DISTINCT ao.article_id) AS n FROM article_owner ao "
                    "JOIN article a ON a.id=ao.article_id JOIN employee e ON e.id=ao.employee_id "
                    "WHERE a.cabinet_id=$1::uuid AND a.is_active GROUP BY 1,2", str(cab_id)):
                flag(get(r["employee_id"], r["name"]), "art", 1, "ведёт артикулы кабинета: %d" % r["n"])
        except Exception:
            pass
    if fn_id:
        try:
            for r in await c.fetch(
                    "SELECT ef.employee_id, e.name FROM employee_fn ef JOIN employee e ON e.id=ef.employee_id "
                    "WHERE ef.fn_id=$1::uuid AND e.org_id=$2", str(fn_id), org_id):
                if str(r["employee_id"]) in ppl or not ppl:
                    flag(get(r["employee_id"], r["name"]), "knows", 3, "умеет эту функцию")
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
    for d in ppl.values():
        d.pop("f", None)
    return sorted(ppl.values(), key=lambda x: -x["score"])


async def _fo_ai_team(c, org_id):
    """Команда для ИИ: имя, @ник Telegram из карточки сотрудника, основа имени для падежей (Игорь → «игор»)."""
    team = []
    try:
        rows = await c.fetch(
            "SELECT e.id, e.name FROM employee e LEFT JOIN app_user u ON u.id=e.user_id "
            "WHERE e.org_id=$1 AND e.is_active AND coalesce(u.role_code,'') NOT IN ('owner','admin')", org_id)
        tg = {}
        for r in await c.fetch("SELECT ref_id, data FROM fo_card WHERE org_id=$1 AND kind='employee'", org_id):
            d = r["data"]
            if isinstance(d, str):
                try:
                    d = _fo_json.loads(d)
                except Exception:
                    d = {}
            t = str((d or {}).get("tg") or "").strip().lstrip("@").lower()
            if t:
                tg[str(r["ref_id"])] = t
        for r in rows:
            nm = str(r["name"] or "").strip()
            first = (nm.split() or [""])[0].lower().replace("ё", "е")
            stem = first[:max(3, len(first) - 1)] if first else ""
            team.append({"id": str(r["id"]), "name": nm, "tg": tg.get(str(r["id"]), ""), "stem": stem})
    except Exception:
        pass
    return team


def _fo_ai_who(team, s):
    """Кто это из команды: @ник, имя в любом падеже («Игорю», «Лизе»)."""
    s = str(s or "").strip().lstrip("@").lower().replace("ё", "е")
    if not s:
        return None
    for t in team:
        if t["tg"] and s == t["tg"]:
            return t["id"]
    w = (re.findall(r"[a-zа-я]+", s) or [""])[0]
    for t in team:
        if t["stem"] and len(w) >= 3 and w.startswith(t["stem"]):
            return t["id"]
    return None


async def _fo_ai_pick_fn(title, text, fl, incab):
    """Второй короткий запрос: к какой функции агентства относится задача. Ответ — код из списка или null."""
    if not fl:
        return None
    lst = "\n".join("%s%s — %s" % ("★ " if str(f["id"]) in incab else "", f["code"], f["name"]) for f in fl[:150])
    sys_t = ("Ты раскладываешь задачи digital-агентства (кабинеты продавцов Wildberries и OZON) по функциям. "
             "Ответь только кодом одной функции из списка или словом null. Сначала ищи среди отмеченных ★ — "
             "они уже есть в кабинете клиента. Сравнивай по смыслу: цена, скидка, повысить или снизить цену → управление ценой; "
             "ставка, реклама, РК → функции рекламы; фото, обложка, инфографика, A/B, аб тест → фотоворонка и A/B тесты; "
             "поставка, остатки, склад → поставки; акция → акции.")
    usr = "Задача: «%s»\nСообщение: «%s»\nФункции:\n%s" % (str(title)[:300], str(text)[:600], lst)
    try:
        txt, _u = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": sys_t}, {"role": "user", "text": usr}], 40)
    except Exception:
        return None
    t = str(txt or "")
    for f in sorted(fl, key=lambda f: -len(str(f["code"]))):
        if str(f["code"]) and str(f["code"]).lower() in t.lower():
            return f
    return None


def _fo_ai_evidence(team, eid, texts):
    """Есть ли в переписке след этого человека: его @ник или имя в любом падеже."""
    t = next((x for x in team if x["id"] == str(eid)), None)
    if not t:
        return False
    low = " ".join(str(x or "") for x in texts).lower().replace("ё", "е")
    if t["tg"] and ("@" + t["tg"]) in low:
        return True
    return bool(t["stem"]) and re.search(r"(?<![a-zа-я])" + re.escape(t["stem"]), low) is not None


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
    """Разобрать одно сообщение: Яндекс → предложение задачи на согласование.
    ИИ видит 20 прошлых сообщений чата и задачи клиента за 2 дня: повтор или уточнение
    уже поставленной задачи не создаёт новую, а добавляется к ней («уточнение», реакция ✍)."""
    async with pool().acquire() as c:
        m = await c.fetchrow("SELECT * FROM fo_chat_msg WHERE id=$1", msg_pk)
        if not m:
            return {"state": "нет сообщения"}
        cab = await c.fetchrow("SELECT cb.id, cl.name FROM cabinet cb JOIN client cl ON cl.id=cb.client_id "
                               "WHERE cb.client_id=$1::uuid ORDER BY cb.name LIMIT 1", str(m["client_id"]))
        cab_id = cab["id"] if cab else None
        fns = await c.fetch("SELECT f.id, f.code, f.name FROM fn f WHERE f.org_id=$1 ORDER BY f.code", m["org_id"])
        incab = {}
        if cab_id:
            for r in await c.fetch("SELECT cf.fn_id FROM cabinet_fn cf WHERE cf.cabinet_id=$1::uuid", str(cab_id)):
                incab[str(r["fn_id"])] = ""
            for r in await c.fetch("SELECT g.fn_id, e.name FROM fo_cabinet_fn_cfg g LEFT JOIN employee e ON e.id=g.employee_id "
                                   "WHERE g.cabinet_id=$1::uuid", str(cab_id)):
                incab[str(r["fn_id"])] = r["name"] or ""
        team = await _fo_ai_team(c, m["org_id"])
        prev = await c.fetch("SELECT author, author_tg, text FROM fo_chat_msg WHERE tg_chat_id=$1 AND id<$2 AND text<>'' "
                             "ORDER BY id DESC LIMIT %d" % _FO_AI_CTX_N, m["tg_chat_id"], m["id"]) if use_prev else []
        have = []
        if m["client_id"]:
            have = await c.fetch(
                "SELECT id, title, status, quote, task_once_id FROM fo_ai_task WHERE org_id=$1 AND client_id=$2::uuid "
                "AND status IN ('pending','accepted') AND created_at > now() - make_interval(days => $3) "
                "AND coalesce(msg_pk, 0) <> $4 ORDER BY id DESC LIMIT 12",
                m["org_id"], str(m["client_id"]), _FO_AI_DUP_DAYS, msg_pk)
    now = _fo_dt.datetime.now(_FO_MSK)
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    fl = sorted(fns, key=lambda f: (str(f["id"]) not in incab, str(f["code"])))
    ctx = ("Сейчас: %s (Москва), %s.\nКабинет: %s.\nФункции агентства (★ — есть в этом кабинете, в скобках — кто её ведёт):\n%s\n" % (
        now.strftime("%Y-%m-%d %H:%M"), days[now.weekday()], (cab["name"] if cab else "—"),
        "\n".join("%s%s — %s%s" % ("★ " if str(f["id"]) in incab else "", f["code"], f["name"],
                                    (" (%s)" % incab[str(f["id"])]) if incab.get(str(f["id"])) else "") for f in fl[:150]) or "(нет)"))
    if team:
        ctx += "Команда агентства: " + ", ".join(t["name"] + (" (@%s)" % t["tg"] if t["tg"] else "") for t in team) + "\n"
    if have:
        ctx += "Уже поставленные задачи по этому клиенту (за %d дня):\n" % _FO_AI_DUP_DAYS + "\n".join(
            "#%s [%s] %s — клиент писал: «%s»" % (h["id"], "ждёт согласования" if h["status"] == "pending" else "принята",
                                               h["title"], (h["quote"] or "").replace("\n", " ")[:120]) for h in have) + "\n"
    if prev:
        ctx += "Предыдущие сообщения чата (старые сверху):\n" + "\n".join(
            "— %s%s: %s" % (p_["author"] or "?", (" (@%s)" % p_["author_tg"]) if p_["author_tg"] else "",
                            (p_["text"] or "")[:300]) for p_ in reversed(prev)) + "\n"
    ctx += "Новое сообщение (от %s%s): «%s»" % (m["author"] or "клиент", (" (@%s)" % m["author_tg"]) if m["author_tg"] else "",
                                                (m["text"] or "")[:1500])
    sys_txt = _FO_AI_SYS
    try:
        async with pool().acquire() as c:
            st = await _fo_ai_settings(c, m["org_id"])
        rules = [str(r).strip() for r in (st.get("rules") or []) if str(r).strip()]
        if rules:
            sys_txt += "\n\nПравила этого агентства (важнее общих, соблюдай строго):\n" + "\n".join("- " + r for r in rules[:60])
    except Exception:
        pass
    try:
        txt, usage = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": sys_txt},
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
    ctx_list = [p_["text"][:120] for p_ in reversed(prev)]
    title = str(js.get("title") or m["text"] or "")[:300].strip() or "Задача из чата"
    # повтор или уточнение уже поставленной задачи: что сказал ИИ (same_as), затем проверка сервера по формулировке
    dup, dup_how = None, ""
    if js.get("is_task") and have:
        try:
            sa = int(re.sub(r"[^0-9]", "", str(js.get("same_as") or "")) or 0)
        except Exception:
            sa = 0
        dup = next((h for h in have if int(h["id"]) == sa), None) if sa else None
        dup_how = "ИИ" if dup else ""
        if not dup:
            for h in have:
                if _fo_ai_same(title, h["title"]) or _fo_ai_same(m["text"] or "", h["quote"] or ""):
                    dup, dup_how = h, "похожа по формулировке"
                    break
    async with pool().acquire() as c:
        if not js.get("is_task"):
            await c.execute("UPDATE fo_chat_msg SET ai_state='no_task', ai_tokens=$2 WHERE id=$1", msg_pk, tokens)
            return {"state": "no_task", "ai": js, "контекст": ctx_list}
        if dup:
            note = "уточнение к задаче #%s «%s» (%s)" % (dup["id"], (dup["title"] or "")[:80], dup_how)
            if dry:
                await c.execute("UPDATE fo_chat_msg SET ai_state='clarify', ai_note=$3, ai_tokens=$2 WHERE id=$1",
                                msg_pk, tokens, note)
                return {"state": "clarify", "к_задаче": int(dup["id"]), "как_понял": dup_how, "ai": js, "контекст": ctx_list}
            item = {"text": (m["text"] or "")[:1000], "author": m["author"] or "", "what": title[:200],
                    "at": m["msg_at"].isoformat() if m["msg_at"] else None, "msg_pk": int(msg_pk),
                    "link": _fo_msg_link(m["tg_chat_id"], m["msg_id"])}
            await c.execute("UPDATE fo_ai_task SET extra = coalesce(extra, '[]'::jsonb) || $2::jsonb WHERE id=$1",
                            int(dup["id"]), _fo_json.dumps([item], ensure_ascii=False))
            if dup["status"] == "accepted" and dup["task_once_id"]:
                when = m["msg_at"].astimezone(_FO_MSK).strftime("%d.%m %H:%M") if m["msg_at"] else ""
                try:
                    await c.execute("UPDATE fo_task_once SET note = coalesce(note, '') || $2 WHERE id=$1",
                                    dup["task_once_id"], "\nУточнение клиента (%s, %s): «%s»" % (
                                        m["author"] or "клиент", when, (m["text"] or "")[:600]))
                except Exception:
                    pass
            await c.execute("UPDATE fo_chat_msg SET ai_state='clarify', ai_note=$3, ai_tokens=$2 WHERE id=$1",
                            msg_pk, tokens, note)
    if dup:
        try:
            react = await _fo_aio.to_thread(_fo_tg_react_emo_sync, m["tg_chat_id"], m["msg_id"], ("\u270D", "\U0001F440"))
            async with pool().acquire() as c:
                await c.execute("UPDATE fo_chat_msg SET ai_note=$2 WHERE id=$1", msg_pk, (note + " · " + react)[:300])
        except Exception:
            pass
        return {"state": "clarify", "к_задаче": int(dup["id"]), "как_понял": dup_how, "ai": js}
    code = str(js.get("function_code") or "").strip()
    fn = next((f for f in fns if str(f["code"]).lower() == code.lower()), None) if code else None
    if not fn:
        fn = await _fo_ai_pick_fn(title, m["text"] or "", fl, incab)
        if fn:
            js["function_code"] = fn["code"]
            js["fn_by"] = "второй запрос"
    async with pool().acquire() as c:
        fn_id = fn["id"] if fn else None
        named, talked, mentioned = set(), set(), set()
        ex = _fo_ai_who(team, js.get("executor"))
        texts = [p_["text"] for p_ in prev] + [m["text"]]
        authors_ok = set()
        for p_ in list(prev) + [m]:
            who = _fo_ai_who(team, p_["author_tg"]) or _fo_ai_who(team, (str(p_["author"] or "").split() or [""])[0])
            if who:
                talked.add(who)
            for mm in re.findall(r"@([A-Za-z0-9_]{3,})", str(p_["text"] or "")):
                w2 = _fo_ai_who(team, mm)
                if w2:
                    mentioned.add(w2)
        if ex and (ex in talked or _fo_ai_evidence(team, ex, texts)):
            named.add(ex)
        elif js.get("executor"):
            js["executor_rejected"] = js.get("executor")      # ИИ назвал того, кого в переписке нет
        cands = await _fo_ai_people(c, m["org_id"], cab_id, fn_id, named, talked, mentioned)
        if fn and str(fn["id"]) not in incab:
            js["fn_outside"] = True
        emp = cands[0]["employee_id"] if cands else None
        if dry:
            await c.execute("UPDATE fo_chat_msg SET ai_state='task', ai_tokens=$2 WHERE id=$1", msg_pk, tokens)
            return {"state": "task", "ai": js, "ответственный": (cands[0]["name"] if cands else None),
                    "почему": (cands[0]["why"] if cands else []), "функция": (fn["code"] + " " + fn["name"]) if fn else None,
                    "контекст": ctx_list}
        a_uids, a_name, a_emp = await _fo_ai_approvers(c, m["org_id"])
        a_uid = a_uids[0] if a_uids else None
        try:
            mins = max(5, min(240, int(js.get("minutes") or 30)))
        except Exception:
            mins = 30
        dl = _fo_ai_deadline(js.get("deadline"))
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
            _neg = None
            if link["kind"] == "client":
                try:
                    _neg = await _fo_meet_match(c, link["org_id"], str(link["client_id"]), tg, msg, text)
                except Exception:
                    _neg = None
            if _neg:
                why = "ответ по времени планёрки — разбирает бот планёрок"
                _fo_aio.get_running_loop().create_task(
                    _fo_meet_answer(link["org_id"], _neg, text, int(msg.get("message_id") or 0), pk))
            elif link["kind"] != "client":
                why = "не чат с клиентом"
            elif len(text) < 6 or _FO_AI_SKIP.match(text) or _fo_ai_noise(text):
                why = "приветствие / прощание / благодарность / мат — в Яндекс не отправляли"
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
        if (msg.get("chat") or {}).get("type") == "private":
            _fo_aio.get_running_loop().create_task(_fo_mt_private(msg, request.headers.get("x-fo-bot", "")))
        else:
            _fo_aio.get_running_loop().create_task(_fo_ai_on_msg(msg))
    return {"ok": True}


def _fo_ai_row(r):
    d = dict(r)
    for k in ("id", "client_id", "cabinet_id", "fn_id", "employee_id", "approver_employee_id", "approver_user_id",
              "decided_by", "msg_pk", "task_once_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    d["approver_users"] = [str(x) for x in (d.get("approver_users") or [])]
    for k in ("candidates", "ai_raw", "extra"):
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
        ex = a["extra"] if "extra" in a.keys() else None
        if isinstance(ex, str):
            try:
                ex = _fo_json.loads(ex)
            except Exception:
                ex = []
        for it in (ex or [])[:10]:
            try:
                w = _fo_dt.datetime.fromisoformat(it.get("at")).astimezone(_FO_MSK).strftime("%d.%m %H:%M") if it.get("at") else ""
            except Exception:
                w = ""
            full += "\nУточнение клиента (%s, %s): «%s»" % (it.get("author") or "клиент", w, str(it.get("text") or "")[:400])
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
async def fo_ai_status(n: int = 5, p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        msgs = await c.fetchval("SELECT count(*) FROM fo_chat_msg WHERE org_id=$1 AND msg_at > now() - interval '1 day'", p.org_id)
        pend = await c.fetchval("SELECT count(*) FROM fo_ai_task WHERE org_id=$1 AND status='pending'", p.org_id)
        toks = await c.fetchval("SELECT COALESCE(sum(ai_tokens),0) FROM fo_chat_msg WHERE org_id=$1 "
                                "AND msg_at > date_trunc('month', now())", p.org_id)
        last = await c.fetch("SELECT author, left(text, 80) AS text, ai_state, ai_note, msg_at FROM fo_chat_msg "
                             "WHERE org_id=$1 ORDER BY id DESC LIMIT $2", p.org_id, max(1, min(100, int(n or 5))))
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


class FoAiRuleIn(_FoBM):
    add: str | None = None
    remove: int | None = None


@router.get("/ai/rules")
async def fo_ai_rules_get(p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        st = await _fo_ai_settings(c, p.org_id)
    return {"rules": st.get("rules") or []}


@router.post("/ai/rules")
async def fo_ai_rules_set(body: FoAiRuleIn, p: Principal = Depends(max_level(2))):
    """Учим ИИ: правило агентства словами собственника — Яндекс читает их перед каждым разбором."""
    async with pool().acquire() as c:
        st = await _fo_ai_settings(c, p.org_id)
        rules = [str(r) for r in (st.get("rules") or [])]
        if body.add and body.add.strip():
            r = body.add.strip()[:500]
            if r not in rules:
                rules.append(r)
        if body.remove is not None and 0 <= int(body.remove) < len(rules):
            rules.pop(int(body.remove))
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
            "ai:" + str(p.org_id), p.org_id, _fo_json.dumps({"rules": rules}, ensure_ascii=False))
    return {"ok": True, "rules": rules}


# ══ ПЛАНЁРКИ: ГРАФИК, ПРИОРИТЕТ, БОТ СОГЛАСУЕТ ВРЕМЯ (219, 28.09) ══════
# Виталий: «Делегировать договорённость по времени планёрки. Клиенты — на шкалу
# приоритета от большей суммы платежа к меньшей. Сначала уточняем у тех, у кого
# время фиксировано, всё ли в порядке; далее расставляем время приоритетным, далее
# средним, далее низкому. Бот предлагает время в чате, клиент отвечает на сообщение
# или предлагает своё — соглашаться с ним не обязательно: планёрки ведущего идут
# одним блоком, между ними перерыв, тайминг сохраняется. Согласовали — бот
# закрепляет время в чате и меняет статус. В календаре три статуса: предложена на
# согласование → назначена → проведена.» Длительность: высокий приоритет 60–80 мин,
# средний 40–50, низкий 35–40.
# fo_meet — график и статус по клиенту (по дням: время, минуты, ведущий);
# fo_meet_camp — рассылка волнами. График → функция «Совещание» в кабинете
# (по дням свой ведущий — day_cfg) → задачи ведущим рождает _fo_sync_tasks.

_FO_MT_DOWS = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"]
_FO_MT_DOWA = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]
_FO_MT_LVL = {1: (60, 80, 60), 2: (40, 50, 45), 3: (35, 40, 40)}      # мин, макс, по умолчанию
_FO_MT_DEF = {"brk": 15, "gap": 180, "from": 10 * 60, "to": 19 * 60}
_FO_MT_LOOP = {"task": None}
_FO_MT_ROUNDS = 2          # после двух встречных предложений без согласия — решает проджект


def _fo_mt_m(t):
    try:
        h, m = str(t or "").strip().replace(".", ":").split(":")[:2]
        v = int(h) * 60 + int(m)
        return v if 0 <= v < 24 * 60 else None
    except Exception:
        return None


def _fo_mt_hm(v):
    v = int(v)
    return "%02d:%02d" % (v // 60, v % 60)


def _fo_mt_load(v, dflt):
    if isinstance(v, str):
        try:
            v = _fo_json.loads(v)
        except Exception:
            return dflt
    return dflt if v is None else v


def _fo_mt_slots(v):
    """{"0": {"time": "11:00", "minutes": 60, "host": "<сотрудник>"}} → {0: {...}}; только пн–пт."""
    v = _fo_mt_load(v, {})
    out = {}
    if isinstance(v, dict):
        for k, x in v.items():
            try:
                d = int(k)
            except Exception:
                continue
            if not (0 <= d <= 4) or not isinstance(x, dict):
                continue
            t = _fo_mt_m(x.get("time"))
            try:
                mi = max(15, min(180, int(x.get("minutes") or 60)))
            except Exception:
                mi = 60
            out[d] = {"time": _fo_mt_hm(t) if t is not None else "", "minutes": mi, "host": str(x.get("host") or "")}
    return out


def _fo_mt_dump(sl):
    return {str(d): {"time": s["time"], "minutes": int(s["minutes"]), "host": s["host"]} for d, s in sorted(sl.items())}


def _fo_mt_eff(r):
    """Какое время сейчас действует: предложенное (ждём ответа клиента) или график."""
    if r["status"] == "proposed":
        o = _fo_mt_slots(r["offer"])
        if o:
            return o
    return _fo_mt_slots(r["slots"])


def _fo_mt_item(what, **kw):
    it = {"at": _fo_dt.datetime.now(_FO_MSK).strftime("%d.%m %H:%M"), "what": what}
    for k, v in kw.items():
        if v is not None and v != "":
            it[k] = v
    return _fo_json.dumps([it], ensure_ascii=False)


async def _fo_mt_settings(c, org_id):
    d = await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1", "meet:" + str(org_id))
    d = _fo_mt_load(d, {}) or {}
    st = dict(_FO_MT_DEF)
    try:
        st["brk"] = max(0, min(60, int(d.get("brk", st["brk"]))))
        st["gap"] = max(15, min(72 * 60, int(d.get("gap", st["gap"]))))
        f, t = _fo_mt_m(d.get("from")), _fo_mt_m(d.get("to"))
        if f is not None and t is not None and t - f >= 120:
            st["from"], st["to"] = f, t
    except Exception:
        pass
    return st


async def _fo_mt_levels(c, org_id):
    """Шкала приоритета по сумме платежа (карточка клиента), от большей к меньшей:
    верхняя треть — 1 (высокий), средняя — 2, нижняя и без суммы — 3."""
    cls = await c.fetch("SELECT id, name FROM client WHERE org_id=$1", org_id)
    amt = {}
    for r in await c.fetch("SELECT ref_id, data FROM fo_card WHERE org_id=$1 AND kind IN ('client','cab')", org_id):
        d = _fo_mt_load(r["data"], {}) or {}
        try:
            a = float(d.get("amount") or 0)
        except Exception:
            a = 0.0
        k = str(r["ref_id"])
        amt[k] = max(amt.get(k, 0.0), a)
    paid = sorted([x for x in cls if amt.get(str(x["id"]), 0) > 0], key=lambda x: (-amt[str(x["id"])], str(x["name"])))
    n = len(paid)
    out = {}
    for i, x in enumerate(paid):
        lv = 1 if i < -(-n // 3) else (2 if i < -(-2 * n // 3) else 3)
        out[str(x["id"])] = {"level": lv, "rank": i + 1, "amount": amt[str(x["id"])], "name": x["name"]}
    rest = sorted([x for x in cls if str(x["id"]) not in out], key=lambda x: str(x["name"]))
    for j, x in enumerate(rest):
        out[str(x["id"])] = {"level": 3, "rank": n + j + 1, "amount": 0, "name": x["name"]}
    return out


async def _fo_mt_names(c, org_id):
    return {str(r["id"]): r["name"] for r in await c.fetch("SELECT id, name FROM employee WHERE org_id=$1", org_id)}


async def _fo_mt_fn(c, org_id):
    r = await c.fetchval("SELECT id FROM fn WHERE org_id=$1 AND lower(btrim(name))='совещание' ORDER BY code LIMIT 1", org_id)
    if not r:
        r = await c.fetchval("SELECT id FROM fn WHERE org_id=$1 AND name ILIKE '%совещан%' AND name NOT ILIKE '%подготов%' "
                             "ORDER BY code LIMIT 1", org_id)
    return r


async def _fo_mt_migrate(c, org_id):
    """Первый заход: график из прежнего хранилища (fo_state meetPlan) — в fo_meet, статус «не согласована»."""
    if await c.fetchval("SELECT 1 FROM fo_meet WHERE org_id=$1::uuid LIMIT 1", str(org_id)):
        return
    v = await c.fetchval("SELECT data FROM fo_state WHERE org_id=$1::uuid AND scope='org' AND key='meetPlan'", str(org_id))
    plan = _fo_mt_load(v, {}) or {}
    if not isinstance(plan, dict):
        return
    today = _fo_msk_today()
    mon = today - _fo_dt.timedelta(days=today.weekday())
    for pid, pl in plan.items():
        if not isinstance(pl, dict) or not re.match(r"^[0-9a-fA-F-]{36}$", str(pid)):
            continue
        if isinstance(pl.get("slots"), dict):
            sl = _fo_mt_slots(pl["slots"])
        else:
            sl = _fo_mt_slots({str(d): {"time": pl.get("time"), "minutes": pl.get("minutes"), "host": pl.get("host")}
                               for d in (pl.get("days") or [])})
        if not sl:
            continue
        if not await c.fetchval("SELECT 1 FROM client WHERE id=$1::uuid AND org_id=$2", str(pid), org_id):
            continue
        await c.execute("INSERT INTO fo_meet (org_id, client_id, slots, since, status, log) "
                        "VALUES ($1::uuid, $2::uuid, $3::jsonb, $4, 'draft', $5::jsonb) ON CONFLICT DO NOTHING",
                        str(org_id), str(pid), _fo_json.dumps(_fo_mt_dump(sl)), mon,
                        _fo_mt_item("график перенесён из прежнего хранилища"))


async def _fo_mt_apply(c, org_id, client_id, sl):
    """График → функция «Совещание» в кабинете клиента: дни недели, по дням свой ведущий и минуты.
    Задачи ведущим досводит _fo_sync_tasks на две недели вперёд."""
    fid = await _fo_mt_fn(c, org_id)
    if not fid:
        return "в справочнике нет функции «Совещание»"
    cab = await c.fetchval("SELECT id FROM cabinet WHERE client_id=$1::uuid ORDER BY name LIMIT 1", str(client_id))
    if not cab:
        return "у клиента нет кабинета"
    days = sorted(d for d, s in sl.items() if s.get("host"))
    hosts = [sl[d]["host"] for d in days]
    main = max(set(hosts), key=hosts.count) if hosts else None
    old = await c.fetchval("SELECT employee_id FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1 AND fn_id=$2", cab, fid)
    dc = {str(d): {"e": sl[d]["host"], "m": int(sl[d]["minutes"])} for d in days}
    async with c.transaction():
        await c.execute("INSERT INTO cabinet_fn (cabinet_id, fn_id, cycle_n) VALUES ($1, $2, 1) ON CONFLICT DO NOTHING", cab, fid)
        for h in set(hosts):
            await c.execute("INSERT INTO employee_fn (employee_id, fn_id, allowed) VALUES ($1::uuid, $2, true) "
                            "ON CONFLICT DO NOTHING", h, fid)
        await c.execute("DELETE FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1 AND fn_id=$2", cab, fid)
        await c.execute(
            """INSERT INTO fo_cabinet_fn_cfg
                 (cabinet_id, fn_id, org_id, employee_id, minutes, cycle_kind, cycle_n, cycle_weekdays, day_cfg)
               VALUES ($1, $2, $3, $4::uuid, $5, $6, 1, $7, $8::jsonb)""",
            cab, fid, org_id, main, (int(sl[days[0]]["minutes"]) if days else None),
            "weekly" if days else "none", days, _fo_json.dumps(dc) if days else None)
    try:
        res = await _fo_sync_tasks(c, org_id, str(cab), 14, {(cab, fid): old})
        return "задачи: создано %s, снято %s, переведено %s" % (res.get("создано"), res.get("снято"), res.get("переведено"))
    except Exception as e:
        return "задачи не досвелись: " + str(e)[:150]


# ── Telegram: бот планёрок (свой токен TG_MEET_BOT_TOKEN, иначе основной бот) ──
def _fo_mt_tok():
    return _fo_env("TG_MEET_BOT_TOKEN") or _fo_env("TG_BOT_TOKEN")


_FO_MT_ME = {"t": 0.0, "tok": "", "v": ""}


async def _fo_mt_botname():
    """@имя бота, который пишет клиентам (кэш на час) — проджектам нажать у него Start."""
    tok = _fo_mt_tok()
    if not tok:
        return ""
    if _FO_MT_ME["tok"] == tok and _fo_time.time() - _FO_MT_ME["t"] < 3600:
        return _FO_MT_ME["v"]
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "getMe", {})
    _FO_MT_ME.update({"t": _fo_time.time(), "tok": tok, "v": ((res.get("result") or {}).get("username") or "") if res.get("ok") else ""})
    return _FO_MT_ME["v"]


def _fo_tg_api_sync(method, params, tok=None):
    tok = tok or _fo_mt_tok()
    if not tok:
        return {"ok": False, "description": "на сервере нет токена бота"}
    data = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, str):
            data[k] = v
        elif isinstance(v, bool):
            data[k] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            data[k] = str(v)
        else:
            data[k] = _fo_json.dumps(v, ensure_ascii=False)
    try:
        with _fo_ur.urlopen("https://api.telegram.org/bot%s/%s" % (tok, method),
                            data=_fo_up.urlencode(data).encode(), timeout=20) as r:
            return _fo_json.loads(r.read().decode())
    except Exception as e:
        body = ""
        try:
            body = e.read().decode()[:400]
        except Exception:
            pass
        try:
            return _fo_json.loads(body)
        except Exception:
            return {"ok": False, "description": (str(e) + " " + body).replace(tok, "***")[:300]}


async def _fo_mt_chat(c, client_id):
    return await c.fetchrow(
        "SELECT ch.id AS chat_pk, ch.chat_id FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id "
        "WHERE cc.client_id=$1::uuid AND cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' "
        "AND coalesce(ch.is_active, true) ORDER BY ch.id LIMIT 1", str(client_id))


async def _fo_mt_send(c, org_id, client_id, text, reply_to=None, test=False):
    """Бот пишет в чат клиента. Сообщение ложится и в историю чата — ИИ видит контекст.
    test — проверка: в Telegram не уходит, пишется в тестовую переписку."""
    if test:
        tg = "test-meet-" + str(client_id)[:8]
        mid = int(await c.fetchval("SELECT count(*) FROM fo_chat_msg WHERE tg_chat_id=$1", tg) or 0) + 1
        chat_pk = None
    else:
        ch = await _fo_mt_chat(c, client_id)
        if not ch:
            return None, "у клиента нет чата с ботом"
        prm = {"chat_id": ch["chat_id"], "text": text}
        if reply_to:
            prm["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
        res = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", prm)
        if not res.get("ok"):
            return None, "Telegram: " + str(res.get("description") or "не отправилось")[:200]
        tg, mid, chat_pk = ch["chat_id"], int(res["result"]["message_id"]), ch["chat_pk"]
    try:
        await c.execute(
            "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at, ai_state, ai_note) "
            "VALUES ($1,$2::uuid,$3,'client',$4,$5,'Бот планёрок','',$6,now(),'skip','сообщение бота планёрок') "
            "ON CONFLICT (tg_chat_id, msg_id) DO NOTHING",
            org_id, str(client_id), chat_pk, tg, mid, text[:4000])
    except Exception:
        pass
    return {"tg": tg, "msg_id": mid}, ""


def _fo_mt_lines(sl, names, end=False):
    out = []
    for d, s in sorted(sl.items()):
        t = _fo_mt_m(s["time"])
        tt = s["time"] + (("–" + _fo_mt_hm(t + int(s["minutes"]))) if end and t is not None else "")
        out.append("• по %s в %s, %d мин — ведёт %s" % (_FO_MT_DOWS[d], tt, int(s["minutes"]), names.get(s["host"], "проджект")))
    return "\n".join(out)


def _fo_mt_text(kind, cab, sl, names):
    if kind == "confirm":
        return ("Здравствуйте! Сверяем график планёрок по кабинету «%s»:\n%s\n\n"
                "Всё в силе? Ответьте, пожалуйста, на это сообщение: «да» — или напишите, что поменять." % (cab, _fo_mt_lines(sl, names)))
    return ("Здравствуйте! Предлагаем время еженедельной планёрки по кабинету «%s»:\n%s\n\n"
            "Удобно? Ответьте, пожалуйста, на это сообщение: «да» — или напишите, какой день и время вам подходят." % (cab, _fo_mt_lines(sl, names)))


# ── проджекту — в личку от основного бота (сотрудник один раз нажимает /start) ──
async def _fo_mt_dm(c, emp_id, text, test=False):
    """Проджекту в личку: от бота планёрок, если проджект нажал у него Start, иначе от бота сервиса."""
    if not emp_id:
        return "нет ведущего"
    if test:
        return "проверка: проджекту не писали"
    d = _fo_mt_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='employee' AND ref_id=$1", str(emp_id)), {}) or {}
    bots = d.get("tg_bots") or (["main"] if d.get("tg_id") else [])
    if not d.get("tg_id") or not bots:
        return "проджект ещё не нажал Start у бота планёрок"
    tok = _fo_env("TG_MEET_BOT_TOKEN") if ("meet" in bots and _fo_env("TG_MEET_BOT_TOKEN")) else (_fo_env("TG_BOT_TOKEN") if "main" in bots else "")
    if not tok:
        return "проджект ещё не нажал Start у бота планёрок"
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", {"chat_id": str(d["tg_id"]), "text": text}, tok)
    return "проджект уведомлён" if res.get("ok") else "проджекту не дошло: " + str(res.get("description") or "")[:120]


async def _fo_mt_notify(c, sl, text, test=False):
    out = []
    for h in sorted({s["host"] for s in sl.values() if s.get("host")}):
        out.append(await _fo_mt_dm(c, h, text, test))
    return "; ".join(sorted(set(out)))


async def _fo_mt_private(msg, bot=""):
    """Личка с основным ботом: сотрудник пишет /start — привязываем его по нику из карточки сотрудника;
    сюда приходят уведомления о планёрках и напоминание за час до начала."""
    try:
        frm = msg.get("from") or {}
        uid, un = frm.get("id"), str(frm.get("username") or "").lower()
        if not uid or frm.get("is_bot"):
            return
        ans = ""
        async with pool().acquire() as c:
            hit = None
            for r in await c.fetch("SELECT ref_id, org_id, data FROM fo_card WHERE kind='employee'"):
                d = _fo_mt_load(r["data"], {}) or {}
                tg = str(d.get("tg") or "").strip().lstrip("@").lower()
                if (un and tg == un) or str(d.get("tg_id") or "") == str(uid):
                    hit = r
                    break
            if hit:
                old = _fo_mt_load(hit["data"], {}) or {}
                bots = sorted(set((old.get("tg_bots") or (["main"] if old.get("tg_id") else [])) + ["meet" if bot == "meet" else "main"]))
                await c.execute("UPDATE fo_card SET data = data || $2::jsonb, updated_at = now() WHERE kind='employee' AND ref_id=$1",
                                hit["ref_id"], _fo_json.dumps({"tg_id": int(uid), "tg_bots": bots}))
                name = await c.fetchval("SELECT name FROM employee WHERE id=$1::uuid", str(hit["ref_id"])) or ""
                ans = ("Готово, %s! Сюда будут приходить уведомления о планёрках: кто из клиентов подтвердил время, "
                       "кто просит другое, где нужно ваше решение, и напоминание за час до начала." % name).replace(", !", "!")
            else:
                ans = ("Не нашли вас в команде агентства. Попросите руководителя вписать ваш ник @%s в карточку "
                       "сотрудника в сервисе и нажмите /start ещё раз." % (frm.get("username") or "…"))
        await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", {"chat_id": str(uid), "text": ans},
                                (_fo_env("TG_MEET_BOT_TOKEN") if bot == "meet" else "") or _fo_env("TG_BOT_TOKEN"))
    except Exception as e:
        try:
            print("fo_mt_private:", e)
        except Exception:
            pass


# ── расстановка: планёрки ведущего одним блоком, между ними перерыв ──
async def _fo_mt_busy(c, org_id, skip=None, with_queued=False):
    """Занятость ведущих: {(ведущий, день): [(начало, конец, клиент)]} — назначенные, предложенные и график."""
    busy = {}
    skip = set(str(x) for x in (skip or []))
    for r in await c.fetch("SELECT client_id, status, slots, offer FROM fo_meet WHERE org_id=$1::uuid", str(org_id)):
        cid = str(r["client_id"])
        if cid in skip or r["status"] == "off" or (r["status"] == "queued" and not with_queued):
            continue
        for d, s in _fo_mt_eff(r).items():
            t = _fo_mt_m(s["time"])
            if t is None or not s["host"]:
                continue
            busy.setdefault((s["host"], d), []).append((t, t + int(s["minutes"]), cid))
    return busy


def _fo_mt_fits(busy, host, d, t, mins, st):
    if t is None or t < st["from"] or t + mins > st["to"]:
        return False
    b = st["brk"]
    return all(t + mins + b <= x or t >= y + b for x, y, _ in busy.get((host, d), []))


def _fo_mt_place(busy, host, d, pref, mins, st, n=1):
    """Куда поставить планёрку: вплотную к другим планёркам ведущего в этот день (с перерывом), чтобы они шли
    одним блоком; первая в дне — в желаемое время. Варианты — ближайшие к желаемому."""
    have = sorted(busy.get((host, d), []))
    p0 = pref if pref is not None else st["from"]
    if not have:
        t = max(st["from"], min(p0, st["to"] - mins))
        return [t] if _fo_mt_fits(busy, host, d, t, mins, st) else []
    cands = set()
    for x, y, _ in have:
        cands.add(y + st["brk"])
        cands.add(x - st["brk"] - mins)
    good = sorted((t for t in cands if _fo_mt_fits(busy, host, d, t, mins, st)), key=lambda t: (abs(t - p0), t))
    if not good:
        mid = (have[0][0] + have[-1][1]) // 2
        good = sorted((t for t in range(st["from"], st["to"] - mins + 1, 5) if _fo_mt_fits(busy, host, d, t, mins, st)),
                      key=lambda t: (abs(t - mid), t))
    return good[:n]


def _fo_mt_mins(level, m, fixed=False):
    mn, mx, df = _FO_MT_LVL.get(level or 3, _FO_MT_LVL[3])
    if fixed:
        return int(m or df)
    return int(m) if m and mn <= int(m) <= mx else df


def _fo_mt_offer(busy, sl, level, fixed, st, cid):
    """Предложение по графику клиента: фиксированное — как есть; остальное — в блок ведущего."""
    offer = {}
    for d, s in sorted(sl.items()):
        if not s["host"]:
            continue
        mins = _fo_mt_mins(level, s["minutes"], fixed)
        pref = _fo_mt_m(s["time"])
        if fixed and pref is not None:
            t = pref
        else:
            pl = _fo_mt_place(busy, s["host"], d, pref, mins, st, 1)
            t = pl[0] if pl else (pref if pref is not None else st["from"])
        offer[d] = {"time": _fo_mt_hm(t), "minutes": mins, "host": s["host"]}
        busy.setdefault((s["host"], d), []).append((t, t + mins, cid))
    return offer


# ── ответ клиента ──
_FO_MT_YESW = {"да", "ага", "ок", "окей", "ok", "okay", "подходит", "удобно", "договорились", "согласен", "согласна",
               "согласны", "отлично", "хорошо", "супер", "конечно", "давайте", "спасибо", "все", "в", "силе", "норм",
               "нормально", "пойдет", "устраивает", "да,", "идет", "принято", "так", "и", "оставляем", "оставим"}
_FO_MT_YESK = {"да", "ага", "ок", "окей", "ok", "okay", "подходит", "удобно", "договорились", "согласен", "согласна",
               "согласны", "отлично", "хорошо", "супер", "конечно", "силе", "норм", "нормально", "пойдет", "устраивает",
               "идет", "принято", "оставляем", "оставим"}
_FO_MT_DAYRX = [(0, r"понедельн|\bпн\b"), (1, r"вторн|\bвт\b"), (2, r"\bсред[аеуы]\b|\bср\b"), (3, r"четверг|\bчт\b"),
                (4, r"пятниц|\bпт\b")]
_FO_MT_ANS_RX = re.compile(
    r"(^|[\s,.!])(да|ок|окей|ok|ага|подходит|удобно|неудобно|не удобно|договорились|согласн\w*|давайте|норм\w*|хорошо|"
    r"отлично|не могу|не можем|не получится|в силе)([\s,.!)]|$)|\b([01]?\d|2[0-3])[:.][0-5]\d\b|\bв\s*([01]?\d|2[0-3])\b|"
    r"понедельн|вторник|\bсред[уаы]\b|четверг|пятниц|\bпн\b|\bвт\b|\bср\b|\bчт\b|\bпт\b|план[её]рк|созвон|встреч|перенес|врем",
    re.I)

_FO_MT_SYS = (
    "Агентство договаривается с клиентом о времени еженедельной планёрки (созвона по кабинету на маркетплейсе). "
    "Тебе дают, что предложило агентство, и ответ клиента. Определи смысл ответа.\n"
    "answer: yes — клиент согласен с предложенным (да, ок, подходит, удобно, договорились, всё в силе); "
    "other — клиент называет свой день и/или время; no — не может, но своего времени не назвал; "
    "unclear — непонятно; not_about — сообщение вообще не про планёрку (просьба по работе, вопрос по товару).\n"
    "slots — только для other: список {\"day\": 0–4 (0 — понедельник … 4 — пятница; если день не назван — null), "
    "\"time\": \"HH:MM\" (если время не названо — null)}.\n"
    "Ответь только JSON без пояснений: {\"answer\": \"yes\", \"slots\": []}")


def _fo_mt_rx(text):
    t = str(text or "").lower().replace("ё", "е")
    days = [d for d, rx in _FO_MT_DAYRX if re.search(rx, t)]
    tv = None
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", t)
    if m:
        tv = "%02d:%02d" % (int(m.group(1)), int(m.group(2)))
    else:
        m = re.search(r"\b(?:в|на|к|с|после|до)\s*([01]?\d|2[0-3])\s*(?:ч\b|час\w*)?(?![:.]?\d)", t)
        if m and 8 <= int(m.group(1)) <= 20:
            tv = "%02d:00" % int(m.group(1))
    words = re.findall(r"[a-zа-я]+|\+|👍|✅", t)
    yes = bool(words) and all(w in _FO_MT_YESW or w in ("+", "👍", "✅") for w in words) and \
        any(w in _FO_MT_YESK or w in ("+", "👍", "✅") for w in words) and not days and not tv
    neg = bool(re.search(r"\bне\s+(могу|можем|сможем|получится|удобно|подходит|выйдет)|неудобно|не\s+в\s+этот", t))
    return {"days": days, "time": tv, "yes": yes and not neg, "neg": neg}


def _fo_mt_norm(slots, rx):
    """Слоты из ответа ИИ бывают словарями, строками или числами — приводим к [{"day": 0–4|None, "time": "HH:MM"|None}]."""
    out = []
    for x in (slots if isinstance(slots, list) else ([slots] if slots else [])):
        if isinstance(x, dict):
            d, t = x.get("day"), x.get("time")
        else:
            r2 = _fo_mt_rx(str(x))
            d, t = (r2["days"][0] if r2["days"] else None), r2["time"]
        if isinstance(d, str):
            r3 = _fo_mt_rx(d)
            d = r3["days"][0] if r3["days"] else (int(d) if d.strip().isdigit() else None)
        try:
            d = int(d) if d is not None else None
        except Exception:
            d = None
        if d is not None and not (0 <= d <= 4):
            d = None
        tm = _fo_mt_m(t) if t is not None else None
        if tm is None and t is not None:
            try:
                h = int(float(t))
                tm = h * 60 if 8 <= h <= 20 else None
            except Exception:
                tm = None
        if d is not None or tm is not None:
            out.append({"day": d, "time": _fo_mt_hm(tm) if tm is not None else None})
    if not out and (rx["days"] or rx["time"]):
        out = [{"day": d, "time": rx["time"]} for d in (rx["days"] or [None])]
    return out


async def _fo_mt_parse(text, offer):
    rx = _fo_mt_rx(text)
    if rx["yes"]:
        return {"answer": "yes", "slots": [], "by": "правило"}
    if _fo_ai_ready():
        now = _fo_dt.datetime.now(_FO_MSK)
        usr = "Сейчас: %s.\nАгентство предложило:\n%s\nОтвет клиента: «%s»" % (
            now.strftime("%Y-%m-%d %H:%M"), _fo_mt_lines(offer, {}), str(text or "")[:800])
        try:
            txt, _u = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": _FO_MT_SYS},
                                                              {"role": "user", "text": usr}], 200)
            js = _fo_ai_json(txt) or {}
            if js.get("answer") in ("yes", "other", "no", "unclear", "not_about"):
                js["by"] = "ИИ"
                js["slots"] = _fo_mt_norm(js.get("slots"), rx) if js["answer"] == "other" else []
                if js["answer"] == "unclear" and rx["time"] and not rx["neg"]:
                    js["answer"] = "other"
                    js["slots"] = _fo_mt_norm([], rx)
                return js
        except Exception:
            pass
    if rx["neg"] and not rx["time"]:
        return {"answer": "no", "slots": [], "by": "правило"}
    if rx["days"] or rx["time"]:
        return {"answer": "other", "slots": _fo_mt_norm([], rx), "by": "правило"}
    return {"answer": "unclear", "slots": [], "by": "правило"}


async def _fo_mt_row(c, org_id, client_id):
    return await c.fetchrow("SELECT * FROM fo_meet WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id))


async def _fo_mt_agree(c, org_id, client_id, sl, reply_to=None, test=False, how="клиент подтвердил"):
    """Согласовано: бот пишет итог, закрепляет его в чате (прежнее закрепление снимает), статус «назначена»,
    функция «Совещание» в кабинете — по этому времени."""
    names = await _fo_mt_names(c, org_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    r = await _fo_mt_row(c, org_id, client_id)
    txt = "Зафиксировали планёрку по кабинету «%s»:\n%s\n\nЗакрепляем это сообщение в чате. До встречи!" % (
        cab, _fo_mt_lines(sl, names, end=True))
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=reply_to, test=test)
    pin = ""
    if sent and not test:
        if r and r["pin_msg_id"] and r["tg_chat_id"] == sent["tg"]:
            await _fo_aio.to_thread(_fo_tg_api_sync, "unpinChatMessage", {"chat_id": sent["tg"], "message_id": int(r["pin_msg_id"])})
        pr = await _fo_aio.to_thread(_fo_tg_api_sync, "pinChatMessage",
                                     {"chat_id": sent["tg"], "message_id": sent["msg_id"], "disable_notification": True})
        pin = "закреплено в чате" if pr.get("ok") else ("не закрепилось: " + str(pr.get("description") or "")[:150] +
                                                         " — дайте боту в чате право закреплять сообщения")
    elif sent:
        pin = "закреплено в чате (проверка)"
    await c.execute(
        "UPDATE fo_meet SET slots=$3::jsonb, offer=NULL, status='agreed', agreed_at=now(), pin_msg_id=$4, pinned=$5, "
        "tg_chat_id=coalesce($6, tg_chat_id), attn=NULL, log=log||$7::jsonb, updated_at=now() "
        "WHERE org_id=$1::uuid AND client_id=$2::uuid",
        str(org_id), str(client_id), _fo_json.dumps(_fo_mt_dump(sl)), sent["msg_id"] if sent else None,
        pin.startswith("закреплено"), sent["tg"] if sent else None,
        _fo_mt_item("назначена: " + how, pin=pin, send=err))
    applied = await _fo_mt_apply(c, org_id, client_id, sl)
    dm = await _fo_mt_notify(c, sl, "✅ %s: планёрка назначена (%s)\n%s\nЗадача — у вас в ганте и в задачах." % (
        cab, how, _fo_mt_lines(sl, names, end=True)), test)
    await c.execute("UPDATE fo_meet SET log=log||$3::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), _fo_mt_item("уведомление проджекту", итог=dm))
    return {"state": "agreed", "pin": pin, "send": err or "отправлено", "задачи": applied, "проджекту": dm}


async def _fo_mt_offer_send(c, org_id, client_id, kind, offer, reply_to=None, test=False, text=None, camp=None, wave=None):
    names = await _fo_mt_names(c, org_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    txt = text or _fo_mt_text(kind, cab, offer, names)
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=reply_to, test=test)
    if not sent:
        await c.execute("UPDATE fo_meet SET status=CASE WHEN status IN ('queued','proposed') THEN 'draft' ELSE status END, "
                        "attn=$3, log=log||$4::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                        str(org_id), str(client_id), err, _fo_mt_item("не отправилось", why=err))
        return {"state": "error", "why": err}
    await c.execute(
        "UPDATE fo_meet SET status='proposed', kind=$3, offer=$4::jsonb, tg_chat_id=$5, msg_id=$6, sent_at=now(), "
        "answered_at=CASE WHEN $7::bigint IS NULL THEN NULL ELSE answered_at END, attn=NULL, "
        "camp_id=coalesce($8, camp_id), wave=coalesce($9, wave), log=log||$10::jsonb, updated_at=now() "
        "WHERE org_id=$1::uuid AND client_id=$2::uuid",
        str(org_id), str(client_id), kind, _fo_json.dumps(_fo_mt_dump(offer)), sent["tg"], sent["msg_id"],
        reply_to, camp, wave, _fo_mt_item("предложено клиенту" if kind != "confirm" else "спросили, всё ли в силе",
                                          text=txt[:400], test=("да" if test else None)))
    applied = await _fo_mt_apply(c, org_id, client_id, offer)
    return {"state": "proposed", "msg_id": sent["msg_id"], "задачи": applied}


async def _fo_meet_answer(org_id, client_id, text, msg_id=None, pk=None, test=False):
    try:
        return await _fo_meet_answer_do(org_id, client_id, text, msg_id, pk, test)
    except Exception as e:
        import traceback as _tb
        why = (type(e).__name__ + ": " + str(e))[:200]
        try:
            async with pool().acquire() as c:
                await c.execute("UPDATE fo_meet SET attn=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                                str(org_id), str(client_id), "бот не разобрал ответ — нужен проджект",
                                _fo_mt_item("ошибка разбора ответа", why=why, where=_tb.format_exc()[-400:]))
        except Exception:
            pass
        return {"state": "error", "why": why}


async def _fo_meet_answer_do(org_id, client_id, text, msg_id=None, pk=None, test=False):
    """Разбор ответа клиента: «да» — фиксируем и закрепляем; своё время — берём, только если оно встаёт в блок
    ведущего с перерывом, иначе предлагаем ближайшие окна блока; после двух кругов — решает проджект."""
    async with pool().acquire() as c:
        r = await _fo_mt_row(c, org_id, client_id)
        if not r or r["status"] != "proposed":
            return {"state": "не ждём ответа"}
        offer = _fo_mt_slots(r["offer"]) or _fo_mt_slots(r["slots"])
    js = await _fo_mt_parse(text, offer)
    kind = js.get("answer")
    if kind == "not_about":
        if pk and _fo_ai_ready() and not test:
            try:
                async with pool().acquire() as c:
                    await c.execute("UPDATE fo_chat_msg SET ai_state=NULL, ai_note='не про планёрку — в разбор задач' WHERE id=$1", pk)
                await _fo_ai_process(pk)
            except Exception:
                pass
        return {"state": "не про планёрку", "понял": js}
    async with pool().acquire() as c:
        await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb, updated_at=now() "
                        "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), str(text or "")[:500],
                        _fo_mt_item("ответ клиента", text=str(text or "")[:300],
                                    понял={"yes": "согласен", "other": "предлагает своё время", "no": "не может",
                                           "unclear": "непонятно"}.get(kind, kind), by=js.get("by"),
                                    слоты=js.get("slots") or None))
        if kind == "yes":
            return await _fo_mt_agree(c, org_id, client_id, offer, reply_to=msg_id, test=test)
        st = await _fo_mt_settings(c, org_id)
        lv = (await _fo_mt_levels(c, org_id)).get(str(client_id), {"level": 3})
        rounds = int(r["rounds"] or 0)
        if kind == "other":
            want = {}
            for x in _fo_mt_norm(js.get("slots"), _fo_mt_rx(text)):
                t = _fo_mt_m(x["time"]) if x["time"] else None
                ds = [x["day"]] if x["day"] is not None else list(offer.keys())
                for d in ds:
                    want[d] = t
            if want:
                base = [offer[d] for d in sorted(offer)] or [{"time": "", "minutes": 60, "host": ""}]
                if set(want) <= set(offer):
                    new = {d: dict(s) for d, s in offer.items()}
                else:
                    new = {}
                for i, d in enumerate(sorted(want)):
                    src = offer.get(d) or base[min(i, len(base) - 1)]
                    new[d] = {"time": _fo_mt_hm(want[d]) if want[d] is not None else src["time"],
                              "minutes": src["minutes"], "host": src["host"]}
                busy = await _fo_mt_busy(c, org_id, skip=[client_id])
                bad = [d for d in sorted(want) if not _fo_mt_fits(busy, new[d]["host"], d, _fo_mt_m(new[d]["time"]),
                                                                  int(new[d]["minutes"]), st)
                       or (busy.get((new[d]["host"], d)) and not _fo_mt_adjacent(busy, new[d]["host"], d,
                                                                                _fo_mt_m(new[d]["time"]), int(new[d]["minutes"]), st))]
                if not bad:
                    return await _fo_mt_agree(c, org_id, client_id, new, reply_to=msg_id, test=test,
                                              how="время клиента встало в блок ведущего")
                if rounds >= _FO_MT_ROUNDS:
                    return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "клиент просит другое время: «%s»" % str(text)[:120])
                alt = {}
                opts = []
                names = await _fo_mt_names(c, org_id)
                for d in bad:
                    s = new[d]
                    pl = _fo_mt_place(busy, s["host"], d, _fo_mt_m(s["time"]), int(s["minutes"]), st, 3)
                    if not pl:
                        continue
                    alt[d] = pl
                    opts.append("%s — %s" % (_FO_MT_DOWA[d], " или ".join(_fo_mt_hm(t) for t in pl)))
                if not alt:
                    return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "у ведущего нет окна: «%s»" % str(text)[:120])
                for d, pl in alt.items():
                    new[d]["time"] = _fo_mt_hm(pl[0])
                many = sum(len(x) for x in alt.values()) > 1
                txt = ("Спасибо! На это время поставить не получится: в этот день планёрки у нас идут одним блоком "
                       "с перерывами — так мы держим тайминг. Можем предложить: %s.\n%s"
                       % ("; ".join(opts), "Подойдёт первый вариант? Ответьте «да» или выберите другой." if many
                          else "Подойдёт? Ответьте «да» или напишите, какое время вам удобно."))
                await c.execute("UPDATE fo_meet SET rounds=coalesce(rounds,0)+1 WHERE org_id=$1::uuid AND client_id=$2::uuid",
                                str(org_id), str(client_id))
                res = await _fo_mt_offer_send(c, org_id, client_id, "offer", new, reply_to=msg_id, test=test, text=txt)
                res["встречное"] = opts
                cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
                res["проджекту"] = await _fo_mt_notify(c, new, "↔ %s: клиент просит «%s». Бот предложил: %s." % (
                    cab, str(text)[:150], "; ".join(opts)), test)
                return res
        # «не могу» или непонятно — просим назвать удобное время
        if rounds >= _FO_MT_ROUNDS:
            return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "не договорились: «%s»" % str(text)[:120])
        await c.execute("UPDATE fo_meet SET rounds=coalesce(rounds,0)+1 WHERE org_id=$1::uuid AND client_id=$2::uuid",
                        str(org_id), str(client_id))
        txt = "Поняли. Подскажите, пожалуйста, какой день и время вам удобны — подберём ближайшее окно."
        return await _fo_mt_offer_send(c, org_id, client_id, r["kind"] or "offer", offer, reply_to=msg_id, test=test, text=txt)


def _fo_mt_adjacent(busy, host, d, t, mins, st):
    """Встаёт ли время в блок ведущего: вплотную к соседней планёрке (перерыв ±5 минут)."""
    if t is None:
        return False
    for x, y, _ in busy.get((host, d), []):
        if abs(t - (y + st["brk"])) <= 5 or abs((t + mins + st["brk"]) - x) <= 5:
            return True
    return False


async def _fo_mt_handoff(c, org_id, client_id, msg_id, test, why):
    txt = "Спасибо! Передали ваш вопрос проджекту — он свяжется с вами и согласует удобное время."
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=msg_id, test=test)
    r = await _fo_mt_row(c, org_id, client_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    dm = await _fo_mt_notify(c, _fo_mt_eff(r) if r else {}, "⚠ %s: нужно ваше решение по времени планёрки — %s. "
                             "Договоритесь с клиентом и отметьте время в сервисе («Календарь планёрок»)." % (cab, why), test)
    await c.execute("UPDATE fo_meet SET attn=$3, log=log||$4::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), "нужно решение проджекта: " + why, _fo_mt_item("передано проджекту", why=why, итог=dm))
    return {"state": "handoff", "why": why, "проджекту": dm}


async def _fo_meet_match(c, org_id, client_id, tg, msg, text):
    """Сообщение клиента — ответ боту планёрок? Реплай на сообщение бота — да; без реплая — если ждём ответа
    не дольше трёх суток и в тексте есть «да», время, день недели или «планёрка». Ошибиться не страшно:
    сообщение не про планёрку ИИ вернёт в обычный разбор задач."""
    r = await c.fetchrow("SELECT client_id, msg_id, sent_at FROM fo_meet WHERE org_id=$1::uuid AND client_id=$2::uuid "
                         "AND status='proposed' AND tg_chat_id=$3", str(org_id), str(client_id), str(tg))
    if not r:
        return None
    rep = msg.get("reply_to_message") or {}
    if rep.get("message_id") and r["msg_id"] and int(rep["message_id"]) == int(r["msg_id"]):
        return str(r["client_id"])
    if rep.get("message_id") and not (rep.get("from") or {}).get("is_bot"):
        return None
    if r["sent_at"] and (_fo_dt.datetime.now(_fo_dt.timezone.utc) - r["sent_at"]).total_seconds() > 3 * 86400:
        return None
    return str(r["client_id"]) if _FO_MT_ANS_RX.search(str(text or "")) else None


# ── волны: фиксированные «всё в силе?» → высокий → средний → низкий приоритет ──
async def _fo_mt_advance(c, org_id, camp_id):
    camp = await c.fetchrow("SELECT * FROM fo_meet_camp WHERE id=$1", camp_id)
    if not camp or camp["status"] != "active":
        return {"state": "рассылка не идёт"}
    w = int(camp["wave"])
    mem = []
    while w < 3:
        w += 1
        mem = await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid AND camp_id=$2 AND status='queued' AND wave=$3",
                            str(org_id), camp_id, w)
        if mem:
            break
    if not mem:
        await c.execute("UPDATE fo_meet_camp SET status='done', wave=4, wave_at=now() WHERE id=$1", camp_id)
        return {"state": "все волны отправлены"}
    lv = await _fo_mt_levels(c, org_id)
    st = await _fo_mt_settings(c, org_id)
    busy = await _fo_mt_busy(c, org_id)
    mem = sorted(mem, key=lambda r: lv.get(str(r["client_id"]), {}).get("rank", 999))
    out = []
    for r in mem:
        cid = str(r["client_id"])
        L = lv.get(cid, {"level": 3})
        offer = _fo_mt_offer(busy, _fo_mt_slots(r["slots"]), L["level"], bool(r["fixed"]), st, cid)
        if not offer:
            await c.execute("UPDATE fo_meet SET status='draft', attn='нет ведущего в графике', updated_at=now() "
                            "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), cid)
            out.append({"client": L.get("name"), "state": "нет ведущего"})
            continue
        res = await _fo_mt_offer_send(c, org_id, cid, "confirm" if r["fixed"] else "offer", offer,
                                      test=bool(camp["test"]), camp=camp_id, wave=w)
        out.append({"client": L.get("name"), "state": res.get("state"), "why": res.get("why")})
    await c.execute("UPDATE fo_meet_camp SET wave=$2, wave_at=now() WHERE id=$1", camp_id, w)
    return {"волна": w, "клиенты": out}


async def _fo_mt_remind(c):
    """За час до начала: клиенту в чат (если время согласовано) и проджекту в личку."""
    now = _fo_dt.datetime.now(_FO_MSK)
    d, today = now.weekday(), now.date()
    if d > 4:
        return 0
    mnow = now.hour * 60 + now.minute
    n = 0
    for r in await c.fetch("SELECT * FROM fo_meet WHERE status IN ('agreed','draft','proposed') "
                           "AND (reminded IS NULL OR reminded < $1)", today):
        s = _fo_mt_eff(r).get(d)
        t = _fo_mt_m(s["time"]) if s else None
        if t is None or not (0 < t - mnow <= 60) or (r["since"] and r["since"] > today):
            continue
        ok = await c.fetchval("UPDATE fo_meet SET reminded=$3 WHERE org_id=$1 AND client_id=$2 "
                              "AND (reminded IS NULL OR reminded < $3) RETURNING 1", r["org_id"], r["client_id"], today)
        if not ok:
            continue
        test = str(r["tg_chat_id"] or "").startswith("test")
        names = await _fo_mt_names(c, r["org_id"])
        cab = await c.fetchval("SELECT name FROM client WHERE id=$1", r["client_id"]) or ""
        end = _fo_mt_hm(t + int(s["minutes"]))
        notes = []
        if r["status"] == "agreed":
            sent, err = await _fo_mt_send(c, r["org_id"], r["client_id"],
                                          "Напоминаем: сегодня в %s планёрка по кабинету «%s» (до %s), ведёт %s. До встречи через час!"
                                          % (s["time"], cab, end, names.get(s["host"], "проджект")), test=test)
            notes.append("клиенту: " + ("напомнили" if sent else err))
        notes.append(await _fo_mt_dm(c, s["host"], "⏰ Через час планёрка: %s, %s–%s." % (cab, s["time"], end), test))
        await c.execute("UPDATE fo_meet SET log=log||$3::jsonb WHERE org_id=$1 AND client_id=$2", r["org_id"], r["client_id"],
                        _fo_mt_item("напоминание за час", итог="; ".join(notes)))
        n += 1
    return n


async def _fo_mt_loop():
    await _fo_aio.sleep(40)
    while True:
        try:
            async with pool().acquire() as c:
                await _fo_mt_remind(c)
        except Exception as e:
            try:
                print("fo_mt_remind:", e)
            except Exception:
                pass
        try:
            async with pool().acquire() as c:
                camps = await c.fetch("SELECT id, org_id, wave, wave_at, gap_min FROM fo_meet_camp WHERE status='active'")
            for cp in camps:
                try:
                    async with pool().acquire() as c:
                        if not await c.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", "fo-meet:" + str(cp["org_id"])):
                            continue
                        try:
                            left = await c.fetchval("SELECT count(*) FROM fo_meet WHERE org_id=$1::uuid AND camp_id=$2 AND wave=$3 "
                                                    "AND status='proposed' AND attn IS NULL", str(cp["org_id"]), cp["id"], cp["wave"])
                            late = cp["wave_at"] is None or (_fo_dt.datetime.now(_fo_dt.timezone.utc) - cp["wave_at"]).total_seconds() \
                                >= 60 * int(cp["gap_min"] or 180)
                            if int(left or 0) == 0 or late:
                                await _fo_mt_advance(c, cp["org_id"], cp["id"])
                        finally:
                            await c.execute("SELECT pg_advisory_unlock(hashtext($1))", "fo-meet:" + str(cp["org_id"]))
                except Exception as e:
                    try:
                        print("fo_mt_loop:", e)
                    except Exception:
                        pass
        except Exception:
            pass
        await _fo_aio.sleep(120)


def _fo_mt_kick():
    t = _FO_MT_LOOP.get("task")
    if t is not None and not t.done():
        return
    try:
        _FO_MT_LOOP["task"] = _fo_aio.get_running_loop().create_task(_fo_mt_loop())
    except Exception:
        pass


@router.on_event("startup")
async def _fo_mt_boot():
    _fo_mt_kick()


# ── API ──
def _fo_mt_out(cid, r, lv, chat, names=None):
    L = lv.get(cid, {"level": 3, "rank": 999, "amount": 0, "name": ""})
    d = {"client_id": cid, "name": L.get("name"), "level": L["level"], "rank": L["rank"], "amount": L.get("amount") or 0,
         "chat": bool(chat), "slots": {}, "fixed": False, "since": None, "status": "off", "kind": None, "offer": None,
         "sent_at": None, "answered_at": None, "agreed_at": None, "answer": None, "pinned": False, "attn": None,
         "wave": None, "camp_id": None, "log": []}
    if r:
        d.update({"slots": _fo_mt_dump(_fo_mt_slots(r["slots"])), "fixed": bool(r["fixed"]),
                  "since": r["since"].isoformat() if r["since"] else None, "status": r["status"], "kind": r["kind"],
                  "offer": _fo_mt_dump(_fo_mt_slots(r["offer"])) if r["offer"] else None,
                  "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                  "answered_at": r["answered_at"].isoformat() if r["answered_at"] else None,
                  "agreed_at": r["agreed_at"].isoformat() if r["agreed_at"] else None,
                  "answer": r["answer"], "pinned": bool(r["pinned"]), "attn": r["attn"], "wave": r["wave"],
                  "camp_id": r["camp_id"], "log": (_fo_mt_load(r["log"], []) or [])[-12:],
                  "test": str(r["tg_chat_id"] or "").startswith("test")})
    return d


@router.get("/meet")
async def fo_meet_get(p: Principal = Depends(max_level(4))):
    _fo_mt_kick()
    async with pool().acquire() as c:
        await _fo_mt_migrate(c, p.org_id)
        lv = await _fo_mt_levels(c, p.org_id)
        rows = {str(r["client_id"]): r for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(p.org_id))}
        chats = {str(r["client_id"]) for r in await c.fetch(
            "SELECT DISTINCT cc.client_id FROM client_chat cc JOIN chat ch ON ch.id=cc.chat_pk "
            "WHERE cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' AND ch.org_id=$1", p.org_id)}
        st = await _fo_mt_settings(c, p.org_id)
        camp = await c.fetchrow("SELECT * FROM fo_meet_camp WHERE org_id=$1::uuid ORDER BY id DESC LIMIT 1", str(p.org_id))
        fid = await _fo_mt_fn(c, p.org_id)
        held = {}
        if fid:
            for r in await c.fetch("SELECT client_id, plan_date FROM task WHERE org_id=$1 AND fn_id=$2 AND status='done' "
                                   "AND plan_date >= $3", p.org_id, fid, _fo_msk_today() - _fo_dt.timedelta(days=75)):
                if r["client_id"]:
                    held.setdefault(str(r["client_id"]), []).append(r["plan_date"].isoformat())
    out = [_fo_mt_out(cid, rows.get(cid), lv, cid in chats) for cid in sorted(lv, key=lambda k: lv[k]["rank"])]
    cp = None
    if camp:
        cp = {"id": camp["id"], "status": camp["status"], "wave": camp["wave"], "gap_min": camp["gap_min"],
              "test": bool(camp["test"]), "started_at": camp["started_at"].isoformat(),
              "wave_at": camp["wave_at"].isoformat() if camp["wave_at"] else None}
    try:
        bname = await _fo_mt_botname()
    except Exception:
        bname = ""
    return {"rows": out, "camp": cp, "held": held, "fn": bool(fid), "bot": bool(_fo_mt_tok()),
            "own_bot": bool(_fo_env("TG_MEET_BOT_TOKEN")), "bot_name": bname,
            "settings": {"brk": st["brk"], "gap": st["gap"], "from": _fo_mt_hm(st["from"]), "to": _fo_mt_hm(st["to"])},
            "levels": {str(k): {"min": v[0], "max": v[1], "def": v[2]} for k, v in _FO_MT_LVL.items()}}


@router.get("/meet/times")
async def fo_meet_times(p: Principal = Depends(current)):
    """Время планёрок для ганта: РМ и выше — все, остальным — где ведут сами."""
    async with pool().acquire() as c:
        await _fo_mt_migrate(c, p.org_id)
        me = None if _fo_st_lvl(p) <= 4 else str(await _fo_my_emp(c, p) or "")
        out = {}
        for r in await c.fetch("SELECT client_id, status, slots, offer FROM fo_meet WHERE org_id=$1::uuid AND status<>'off'",
                               str(p.org_id)):
            sl = {d: s for d, s in _fo_mt_eff(r).items() if me is None or s["host"] == me}
            if sl:
                out[str(r["client_id"])] = {"status": r["status"], "slots": _fo_mt_dump(sl)}
    return {"times": out}


class FoMtSaveIn(_FoBM):
    slots: dict | None = None
    fixed: bool | None = None
    mark: str | None = None        # agreed — согласовано проджектом вручную; draft — вернуть в «не согласована»


@router.post("/meet/{client_id}/save")
async def fo_meet_save(client_id: str, body: FoMtSaveIn, p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        if not await c.fetchval("SELECT 1 FROM client WHERE id=$1::uuid AND org_id=$2", client_id, p.org_id):
            raise HTTPException(404, "клиент не найден")
        await _fo_mt_migrate(c, p.org_id)
        r = await _fo_mt_row(c, p.org_id, client_id)
        sl = _fo_mt_slots(body.slots) if body.slots is not None else (_fo_mt_slots(r["slots"]) if r else {})
        for d, s in sl.items():
            if not s["time"] or not s["host"]:
                raise HTTPException(400, "%s: укажите время и кто ведёт" % ["пн", "вт", "ср", "чт", "пт"][d])
            ok = await c.fetchval(
                "SELECT 1 FROM employee e WHERE e.id=$1::uuid AND e.org_id=$2 AND e.is_active AND NOT EXISTS "
                "(SELECT 1 FROM app_user u WHERE u.id=e.user_id AND u.role_code IN ('owner','admin'))", s["host"], p.org_id)
            if not ok:
                raise HTTPException(400, "Ведущий на %s не подходит: собственнику задачи не ставятся — выберите проджекта"
                                    % ["пн", "вт", "ср", "чт", "пт"][d])
        fixed = bool(body.fixed) if body.fixed is not None else bool(r and r["fixed"])
        same = bool(r) and _fo_mt_dump(_fo_mt_slots(r["slots"])) == _fo_mt_dump(sl) and bool(r["fixed"]) == fixed
        if not sl:
            status = "off"
        elif body.mark == "agreed":
            status = "agreed"
        elif body.mark == "draft":
            status = "draft"
        elif same and r["status"] in ("agreed", "proposed", "queued"):
            status = r["status"]
        else:
            status = "draft"
        today = _fo_msk_today()
        mon = today - _fo_dt.timedelta(days=today.weekday())
        what = {"agreed": "назначена вручную (проджект согласовал сам)", "off": "снято с графика"}.get(status, "график изменён — ещё не согласован с клиентом")
        await c.execute(
            """INSERT INTO fo_meet (org_id, client_id, slots, fixed, since, status, log, updated_by)
               VALUES ($1::uuid, $2::uuid, $3::jsonb, $4, $5, $6, $7::jsonb, $8)
               ON CONFLICT (org_id, client_id) DO UPDATE SET slots=EXCLUDED.slots, fixed=EXCLUDED.fixed,
                 since=coalesce(fo_meet.since, EXCLUDED.since), status=EXCLUDED.status,
                 offer=CASE WHEN EXCLUDED.status='proposed' THEN fo_meet.offer ELSE NULL END,
                 attn=CASE WHEN EXCLUDED.status IN ('agreed','off') THEN NULL ELSE fo_meet.attn END,
                 rounds=CASE WHEN EXCLUDED.status='proposed' THEN fo_meet.rounds ELSE 0 END,
                 agreed_at=CASE WHEN EXCLUDED.status='agreed' AND fo_meet.status<>'agreed' THEN now() ELSE fo_meet.agreed_at END,
                 log=fo_meet.log || EXCLUDED.log, updated_at=now(), updated_by=EXCLUDED.updated_by""",
            str(p.org_id), client_id, _fo_json.dumps(_fo_mt_dump(sl)), fixed, mon, status,
            _fo_mt_item(what), _fo_uid(p) if re.match(r"^[0-9a-fA-F-]{36}$", str(_fo_uid(p))) else None)
        r = await _fo_mt_row(c, p.org_id, client_id)
        applied = await _fo_mt_apply(c, p.org_id, client_id, _fo_mt_eff(r))
        lv = await _fo_mt_levels(c, p.org_id)
        chat = await _fo_mt_chat(c, client_id)
    return {"ok": True, "row": _fo_mt_out(client_id, r, lv, chat), "задачи": applied}


class FoMtSendIn(_FoBM):
    test: bool = False


@router.post("/meet/{client_id}/send")
async def fo_meet_send(client_id: str, body: FoMtSendIn, p: Principal = Depends(max_level(4))):
    """Предложить время одному клиенту сейчас, вне волн."""
    async with pool().acquire() as c:
        r = await _fo_mt_row(c, p.org_id, client_id)
        if not r or not _fo_mt_slots(r["slots"]):
            raise HTTPException(400, "сначала задайте график: дни, время и кто ведёт")
        lv = (await _fo_mt_levels(c, p.org_id)).get(client_id, {"level": 3})
        st = await _fo_mt_settings(c, p.org_id)
        busy = await _fo_mt_busy(c, p.org_id, skip=[client_id])
        offer = _fo_mt_offer(busy, _fo_mt_slots(r["slots"]), lv["level"], bool(r["fixed"]), st, client_id)
        await c.execute("UPDATE fo_meet SET rounds=0 WHERE org_id=$1::uuid AND client_id=$2::uuid", str(p.org_id), client_id)
        return await _fo_mt_offer_send(c, p.org_id, client_id, "confirm" if r["fixed"] else "offer", offer, test=body.test)


class FoMtReplyIn(_FoBM):
    text: str


@router.post("/meet/{client_id}/reply")
async def fo_meet_reply(client_id: str, body: FoMtReplyIn, p: Principal = Depends(max_level(2))):
    """Проверка без Telegram: как будто клиент ответил боту планёрок (только для тестовой переписки)."""
    async with pool().acquire() as c:
        r = await _fo_mt_row(c, p.org_id, client_id)
        if not r or not str(r["tg_chat_id"] or "").startswith("test"):
            raise HTTPException(400, "проверочный ответ — только для тестовой рассылки")
        tg = str(r["tg_chat_id"])
        mid = int(await c.fetchval("SELECT count(*) FROM fo_chat_msg WHERE tg_chat_id=$1", tg) or 0) + 1
        await c.execute("INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at, ai_state) "
                        "VALUES ($1,$2::uuid,NULL,'client',$3,$4,'Клиент (проверка)','',$5,now(),'skip') ON CONFLICT DO NOTHING",
                        p.org_id, client_id, tg, mid, body.text[:2000])
    return await _fo_meet_answer(p.org_id, client_id, body.text, msg_id=mid, test=True)


class FoMtCampIn(_FoBM):
    clients: list[str] | None = None
    all: bool = False              # и тех, у кого время уже назначено
    gap_min: int | None = None
    dry: bool = True
    test: bool = False


@router.post("/meet/campaign")
async def fo_meet_campaign(body: FoMtCampIn, p: Principal = Depends(max_level(4))):
    """Рассылка волнами: 0 — фиксированным «всё в силе?», 1 — высокий приоритет, 2 — средний, 3 — низкий.
    Следующая волна — когда все ответили или прошло gap минут. dry — только показать, что и кому уйдёт."""
    async with pool().acquire() as c:
        await _fo_mt_migrate(c, p.org_id)
        lv = await _fo_mt_levels(c, p.org_id)
        st = await _fo_mt_settings(c, p.org_id)
        names = await _fo_mt_names(c, p.org_id)
        rows = {str(r["client_id"]): r for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(p.org_id))}
        want = set(body.clients or rows.keys())
        cand, skip = [], []
        for cid, r in rows.items():
            if cid not in want:
                continue
            sl = _fo_mt_slots(r["slots"])
            if not sl or r["status"] == "off":
                continue
            if r["status"] == "agreed" and not body.all:
                skip.append({"client": lv.get(cid, {}).get("name"), "why": "уже назначена"})
                continue
            cand.append((cid, r))
        if not cand:
            raise HTTPException(400, "некому предлагать: задайте график (дни и ведущего) или включите «и назначенным»")
        chats = {str(r["client_id"]) for r in await c.fetch(
            "SELECT DISTINCT cc.client_id FROM client_chat cc JOIN chat ch ON ch.id=cc.chat_pk "
            "WHERE cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' AND ch.org_id=$1", p.org_id)}
        wv = lambda cid, r: 0 if r["fixed"] else lv.get(cid, {"level": 3})["level"]
        cand.sort(key=lambda x: (wv(*x), lv.get(x[0], {}).get("rank", 999)))
        busy = await _fo_mt_busy(c, p.org_id, skip=[x[0] for x in cand])
        preview = []
        for cid, r in cand:
            L = lv.get(cid, {"level": 3, "name": ""})
            offer = _fo_mt_offer(busy, _fo_mt_slots(r["slots"]), L["level"], bool(r["fixed"]), st, cid)
            preview.append({"client_id": cid, "client": L.get("name"), "wave": wv(cid, r), "level": L["level"],
                            "fixed": bool(r["fixed"]), "chat": cid in chats or body.test,
                            "offer": _fo_mt_dump(offer),
                            "text": _fo_mt_text("confirm" if r["fixed"] else "offer", L.get("name") or "", offer, names)})
        if body.dry:
            return {"dry": True, "waves": preview, "skip": skip, "brk": st["brk"]}
        gap = max(15, min(72 * 60, int(body.gap_min or st["gap"])))
        await c.execute("UPDATE fo_meet_camp SET status='stopped' WHERE org_id=$1::uuid AND status='active'", str(p.org_id))
        camp_id = await c.fetchval("INSERT INTO fo_meet_camp (org_id, started_by, gap_min, test) VALUES ($1::uuid, $2, $3, $4) RETURNING id",
                                   str(p.org_id), _fo_uid(p) if re.match(r"^[0-9a-fA-F-]{36}$", str(_fo_uid(p))) else None,
                                   gap, bool(body.test))
        for x in preview:
            await c.execute("UPDATE fo_meet SET status='queued', wave=$3, level=$4, camp_id=$5, rounds=0, attn=NULL, "
                            "log=log||$6::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                            str(p.org_id), x["client_id"], x["wave"], x["level"], camp_id,
                            _fo_mt_item("в очереди рассылки, волна %s" % x["wave"]))
        if not await c.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", "fo-meet:" + str(p.org_id)):
            return {"ok": True, "camp_id": camp_id, "state": "первая волна уйдёт в течение двух минут"}
        try:
            res = await _fo_mt_advance(c, p.org_id, camp_id)
        finally:
            await c.execute("SELECT pg_advisory_unlock(hashtext($1))", "fo-meet:" + str(p.org_id))
    _fo_mt_kick()
    return {"ok": True, "camp_id": camp_id, **res}


@router.post("/meet/campaign/stop")
async def fo_meet_campaign_stop(p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        ids = [r["id"] for r in await c.fetch("UPDATE fo_meet_camp SET status='stopped' WHERE org_id=$1::uuid AND status='active' "
                                             "RETURNING id", str(p.org_id))]
        n = 0
        if ids:
            n = _fo_n(await c.execute("UPDATE fo_meet SET status='draft', log=log||$3::jsonb, updated_at=now() "
                                      "WHERE org_id=$1::uuid AND camp_id = ANY($2::bigint[]) AND status='queued'",
                                      str(p.org_id), ids, _fo_mt_item("рассылка остановлена")))
    return {"ok": True, "остановлено": len(ids), "вернули_из_очереди": n}


class FoMtSetIn(_FoBM):
    brk: int | None = None
    gap: int | None = None
    start: str | None = None
    end: str | None = None


@router.post("/meet/settings")
async def fo_meet_settings(body: FoMtSetIn, p: Principal = Depends(max_level(4))):
    d = {}
    if body.brk is not None:
        d["brk"] = max(0, min(60, int(body.brk)))
    if body.gap is not None:
        d["gap"] = max(15, min(72 * 60, int(body.gap)))
    if body.start and _fo_mt_m(body.start) is not None:
        d["from"] = _fo_mt_hm(_fo_mt_m(body.start))
    if body.end and _fo_mt_m(body.end) is not None:
        d["to"] = _fo_mt_hm(_fo_mt_m(body.end))
    async with pool().acquire() as c:
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
            "meet:" + str(p.org_id), p.org_id, _fo_json.dumps(d))
        st = await _fo_mt_settings(c, p.org_id)
    return {"ok": True, "settings": {"brk": st["brk"], "gap": st["gap"], "from": _fo_mt_hm(st["from"]), "to": _fo_mt_hm(st["to"])}}
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

# Задачи дня — каждому своё (28.09): штатный GET /tasks/day обёрнут —
# младший и ассистент получают только свои задачи, главный менеджер — свои
# и младших, проджект и выше — все. Фильтр живёт в refs (_fo_scope_rows).
def _fo_wrap_tasks_day():
    import inspect as _fo_i, sys as _fo_s
    from fastapi.routing import APIRoute as _FoRoute
    refs = next((m for m in list(_fo_s.modules.values()) if m is not None and hasattr(m, "_fo_scope_rows")), None)
    if refs is None:
        return "нет модуля с фильтром"
    for r in list(app.router.routes):
        if isinstance(r, _FoRoute) and r.path == "/tasks/day" and "GET" in (r.methods or set()):
            if getattr(r.endpoint, "_fo_scoped", False):
                return "уже обёрнут"
            orig = r.endpoint

            async def scoped(*a, **kw):
                res = orig(*a, **kw)
                if _fo_i.isawaitable(res):
                    res = await res
                p = next((v for v in kw.values() if hasattr(v, "org_id") and hasattr(v, "level")), None)
                if p is None or not isinstance(res, list):
                    return res
                return await refs._fo_scope_rows(p, res, "assignee_id")

            scoped.__signature__ = _fo_i.signature(orig)
            scoped.__name__ = getattr(orig, "__name__", "tasks_day")
            scoped.__doc__ = getattr(orig, "__doc__", None)
            scoped._fo_scoped = True
            idx = app.router.routes.index(r)
            app.router.routes.remove(r)
            app.add_api_route("/tasks/day", scoped, methods=["GET"], response_model=r.response_model,
                              tags=r.tags, name=r.name, dependencies=r.dependencies)
            app.router.routes.insert(idx, app.router.routes.pop())
            return "обёрнут"
    return "маршрут не найден"


try:
    _FO_TASKS_DAY = _fo_wrap_tasks_day()
except Exception as _fo_e:
    _FO_TASKS_DAY = "ошибка: %s" % _fo_e
print("FO tasks/day:", _FO_TASKS_DAY, flush=True)
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
_FO_BLOB = "U2FsdGVkX1/DWcWCOllGOpsr+LAQVe/gpW0vY1VIoMNVIFZMqTfSaDe32KgH1hBUPzpgKavU2HTh4WkRdX16FifgSXfl9IiZKQZlkWO/NVhtDeJ99uhJOLNdh/66hm7b"
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
            if _k == "TG_MEET_BOT_TOKEN" and re.match(r"^[0-9]{6,12}:[A-Za-z0-9_\-]{30,}$", _v): _got[_k] = _v
        if _got:
            _envp = "/opt/fo/.env"
            _lines = [l for l in open(_envp, encoding="utf-8").read().splitlines() if l.split("=", 1)[0].strip() not in _got]
            _lines += ["%s=%s" % (k, v) for k, v in _got.items()]
            open(_envp, "w", encoding="utf-8").write("\n".join(_lines) + "\n"); os.chmod(_envp, 0o600)
            sh("systemctl restart fo"); sh("sleep 3")
            p("из «Ключи ФО.txt» записано на сервер:", ", ".join("%s (знаков %d)" % (k, len(v)) for k, v in _got.items()), "· health:",
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
p("== БОТ ПЛАНЁРОК ==")
_tk3 = ""
try:
    for _ln in open("/opt/fo/.env", encoding="utf-8"):
        if _ln.startswith("TG_MEET_BOT_TOKEN="): _tk3 = _ln.split("=", 1)[1].strip().strip('"').strip("'")
    if _tk3:
        _P3 = (_POLL.replace('E.get("TG_BOT_TOKEN", "")', 'E.get("TG_MEET_BOT_TOKEN", "")')
                    .replace('"X-Telegram-Bot-Api-Secret-Token": SEC}', '"X-Telegram-Bot-Api-Secret-Token": SEC, "X-FO-Bot": "meet"}')
                    .replace("fo-tgpoll: старт", "fo-tgpoll-meet: старт"))
        _U3 = _UNIT.replace("/opt/fo/tgpoll.py", "/opt/fo/tgpoll_meet.py").replace("Description=FO: бот", "Description=FO: бот планёрок")
        open("/opt/fo/tgpoll_meet.py", "w", encoding="utf-8").write(_P3)
        open("/etc/systemd/system/fo-tgpoll-meet.service", "w", encoding="utf-8").write(_U3)
        sh("systemctl daemon-reload; systemctl enable fo-tgpoll-meet >/dev/null 2>&1; systemctl restart fo-tgpoll-meet; sleep 4")
        p("служба fo-tgpoll-meet:", sh("systemctl is-active fo-tgpoll-meet").strip())
        import json as _mj, urllib.request as _mu
        with _mu.urlopen("https://api.telegram.org/bot%s/getMe" % _tk3, timeout=15) as _r:
            _me = (_mj.loads(_r.read().decode()) or {}).get("result") or {}
        p("бот планёрок: @%s" % _me.get("username"))
        p(sh("journalctl -u fo-tgpoll-meet -n 6 --no-pager -o cat").replace(_tk3, "***")[-800:])
    else:
        sh("systemctl stop fo-tgpoll-meet >/dev/null 2>&1")
        p("отдельного токена бота планёрок на сервере нет — клиентам пишет бот сервиса")
except Exception as _e:
    p("бот планёрок: ошибка", (str(_e).replace(_tk3, "***") if _tk3 else str(_e))[:200])

p("")
p("== ЧАТЫ КЛИЕНТОВ ==")
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT ch.id||' · '||ch.title||' · '||cc.kind||' · '||CASE WHEN ch.chat_id ~ '^-?[0-9]+$' THEN 'номер Telegram ✓' ELSE 'ссылка, номера нет' END FROM chat ch JOIN client_chat cc ON cc.chat_pk=ch.id ORDER BY ch.id\""))
p(sh("sudo -u postgres psql -d fo -Atc \"SELECT 'сообщений из чатов: '||count(*)||', последнее: '||COALESCE(max(msg_at)::text,'—') FROM fo_chat_msg WHERE tg_chat_id<>'test'\""))

print("\n".join(out))
