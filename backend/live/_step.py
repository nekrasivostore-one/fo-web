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
-- 220: неделя — переносы, отмены и дополнительные планёрки только на эту неделю
ALTER TABLE fo_meet ADD COLUMN IF NOT EXISTS week_of date;
ALTER TABLE fo_meet ADD COLUMN IF NOT EXISTS pend jsonb;
CREATE TABLE IF NOT EXISTS fo_meet_occ (
  id bigserial PRIMARY KEY, org_id uuid NOT NULL, client_id uuid NOT NULL, day date NOT NULL, time text NOT NULL,
  minutes int NOT NULL DEFAULT 60, host uuid, kind text NOT NULL DEFAULT 'extra', src_day date,
  status text NOT NULL DEFAULT 'agreed', task_id uuid, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS fo_meet_occ_idx ON fo_meet_occ (org_id, day);
CREATE TABLE IF NOT EXISTS fo_task_skip (
  org_id uuid NOT NULL, cabinet_id uuid NOT NULL, fn_id uuid NOT NULL, day date NOT NULL, client_id uuid, reason text,
  created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (cabinet_id, fn_id, day));
CREATE TABLE IF NOT EXISTS fo_meet_rem (
  org_id uuid NOT NULL, client_id uuid NOT NULL, k text NOT NULL, at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, client_id, k));
GRANT SELECT, INSERT, UPDATE, DELETE ON fo_meet_occ, fo_task_skip, fo_meet_rem TO fo;
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
    try:
        _skip = {(str(x["cabinet_id"]), str(x["fn_id"]), x["day"]) for x in await c.fetch(
            "SELECT cabinet_id, fn_id, day FROM fo_task_skip WHERE org_id=$1 AND day >= $2", org_id, horizon[0])}
    except Exception:
        _skip = set()
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
            if due and (str(r["cabinet_id"]), str(r["fn_id"]), d) in _skip:
                due = False
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
_FO_MT_DEF = {"brk": 15, "gap": 180, "from": 10 * 60, "to": 19 * 60, "auto": True, "auto_at": 10 * 60}
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
        st["auto"] = bool(d.get("auto", True))
        st["auto_at"] = _fo_mt_m(d.get("auto_at")) if _fo_mt_m(d.get("auto_at")) is not None else 10 * 60
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
    """Про планёрки пишет только бот планёрок (@planerka_flater_team_bot). Бот сервиса — только задачи (Виталий 28.09)."""
    return _fo_env("TG_MEET_BOT_TOKEN")


_FO_MT_ME = {"t": 0.0, "tok": "", "v": ""}


async def _fo_mt_botname():
    """@имя бота, который пишет клиентам (кэш на час) — проджектам нажать у него Start."""
    tok = _fo_mt_tok()
    if not tok:
        return ""
    if _FO_MT_ME["tok"] == tok and _fo_time.time() - _FO_MT_ME["t"] < 3600:
        return _FO_MT_ME["v"]
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "getMe", {})
    me = (res.get("result") or {}) if res.get("ok") else {}
    _FO_MT_ME.update({"t": _fo_time.time(), "tok": tok, "v": me.get("username") or "", "id": me.get("id")})
    return _FO_MT_ME["v"]


_FO_MT_CM = {}


async def _fo_mt_chatstate(chat_id):
    """Есть ли бот планёрок в чате клиента и может ли закреплять (кэш 10 минут)."""
    if not _fo_mt_tok() or not chat_id:
        return {"in": False, "pin": False, "why": "нет бота планёрок"}
    await _fo_mt_botname()
    bid = _FO_MT_ME.get("id")
    hit = _FO_MT_CM.get(str(chat_id))
    if hit and _fo_time.time() - hit["t"] < 600:
        return hit["v"]
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "getChatMember", {"chat_id": str(chat_id), "user_id": str(bid)})
    r = res.get("result") or {}
    st = r.get("status") or ""
    v = {"in": st in ("administrator", "member", "creator", "restricted"),
         "pin": st == "creator" or (st == "administrator" and bool(r.get("can_pin_messages", True))),
         "why": "" if res.get("ok") else str(res.get("description") or "")[:120]}
    _FO_MT_CM[str(chat_id)] = {"t": _fo_time.time(), "v": v}
    return v


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
    bots = d.get("tg_bots") or []
    tok = _fo_env("TG_MEET_BOT_TOKEN")
    if not d.get("tg_id") or "meet" not in bots or not tok:
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
            meet = bot == "meet"
            if hit:
                old = _fo_mt_load(hit["data"], {}) or {}
                bots = sorted(set((old.get("tg_bots") or (["main"] if old.get("tg_id") else [])) + ["meet" if bot == "meet" else "main"]))
                await c.execute("UPDATE fo_card SET data = data || $2::jsonb, updated_at = now() WHERE kind='employee' AND ref_id=$1",
                                hit["ref_id"], _fo_json.dumps({"tg_id": int(uid), "tg_bots": bots}))
                name = await c.fetchval("SELECT name FROM employee WHERE id=$1::uuid", str(hit["ref_id"])) or ""
                if meet:
                    ans = ("Готово, %s! Сюда будут приходить уведомления о планёрках: кто из клиентов подтвердил время, "
                           "кто просит другое, где нужно ваше решение, и напоминание за час до начала." % name).replace(", !", "!")
                else:
                    mb = await _fo_mt_botname()
                    ans = ("Готово, %s! Это бот задач сервиса Flater: он ставит задачи из чатов с клиентами. "
                           "Уведомления о планёрках присылает другой бот%s — нажмите Start и у него." % (name, (" — @" + mb) if mb else "")).replace(", !", "!")
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


async def _fo_mt_rules(c, org_id):
    d = _fo_mt_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1", "meet:" + str(org_id)), {}) or {}
    return [str(x).strip() for x in (d.get("rules") or []) if str(x).strip()]


async def _fo_mt_parse(text, offer, org_id=None):
    """Агент планёрок — свой ИИ-агент со своим алгоритмом и своими правилами (не агент задач)."""
    rx = _fo_mt_rx(text)
    if rx["yes"]:
        return {"answer": "yes", "slots": [], "by": "правило"}
    if _fo_ai_ready():
        sys_t = _FO_MT_SYS
        if org_id:
            try:
                async with pool().acquire() as c:
                    rl = await _fo_mt_rules(c, org_id)
                if rl:
                    sys_t += "\n\nПравила агента планёрок этого агентства (важнее общих):\n" + "\n".join("- " + r for r in rl[:40])
            except Exception:
                pass
        now = _fo_dt.datetime.now(_FO_MSK)
        usr = "Сейчас: %s.\nАгентство предложило:\n%s\nОтвет клиента: «%s»" % (
            now.strftime("%Y-%m-%d %H:%M"), _fo_mt_lines(offer, {}), str(text or "")[:800])
        try:
            txt, _u = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": sys_t},
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
    wk, items = await _fo_mt_weekitems(c, org_id, client_id, sl, r)
    sent, err = await _fo_mt_card(c, org_id, client_id, "agreed", _fo_mt_caption("agreed", cab, items, names),
                                  reply_to=reply_to, test=test)
    pin = ""
    if sent and not test:
        if r and r["pin_msg_id"] and r["tg_chat_id"] == sent["tg"]:
            await _fo_aio.to_thread(_fo_tg_api_sync, "unpinChatMessage", {"chat_id": sent["tg"], "message_id": int(r["pin_msg_id"])})
        pr = await _fo_aio.to_thread(_fo_tg_api_sync, "pinChatMessage",
                                     {"chat_id": sent["tg"], "message_id": sent["msg_id"], "disable_notification": True})
        pin = "закреплено в чате" if pr.get("ok") else "не закреплено — бот не администратор чата (это не обязательно)"
    elif sent:
        pin = "закреплено в чате (проверка)"
    await c.execute(
        "UPDATE fo_meet SET slots=$3::jsonb, offer=NULL, status='agreed', agreed_at=now(), pin_msg_id=$4, pinned=$5, "
        "tg_chat_id=coalesce($6, tg_chat_id), attn=NULL, log=log||$7::jsonb, week_of=coalesce(week_of, $8), pend=NULL, updated_at=now() "
        "WHERE org_id=$1::uuid AND client_id=$2::uuid",
        str(org_id), str(client_id), _fo_json.dumps(_fo_mt_dump(sl)), sent["msg_id"] if sent else None,
        pin.startswith("закреплено"), sent["tg"] if sent else None,
        _fo_mt_item("назначена: " + how, pin=pin, send=err), wk)
    applied = await _fo_mt_apply(c, org_id, client_id, sl)
    dm = await _fo_mt_notify(c, sl, "✅ %s: планёрка назначена (%s)\n%s\nЗадача — у вас в ганте и в задачах." % (
        cab, how, _fo_mt_lines(sl, names, end=True)), test)
    await c.execute("UPDATE fo_meet SET log=log||$3::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), _fo_mt_item("уведомление проджекту", итог=dm))
    return {"state": "agreed", "pin": pin, "send": err or "отправлено", "задачи": applied, "проджекту": dm}


async def _fo_mt_offer_send(c, org_id, client_id, kind, offer, reply_to=None, test=False, text=None, camp=None, wave=None):
    names = await _fo_mt_names(c, org_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    r0 = await _fo_mt_row(c, org_id, client_id)
    wk, items = await _fo_mt_weekitems(c, org_id, client_id, offer, r0)
    if text:
        txt = text
        sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=reply_to, test=test)
    else:
        txt = _fo_mt_caption("confirm" if kind == "confirm" else "week", cab, items, names)
        sent, err = await _fo_mt_card(c, org_id, client_id, "confirm" if kind == "confirm" else "week", txt,
                                      reply_to=reply_to, test=test)
        txt = re.sub(r"<[^>]+>", "", txt)
    if not sent:
        await c.execute("UPDATE fo_meet SET status=CASE WHEN status IN ('queued','proposed') THEN 'draft' ELSE status END, "
                        "attn=$3, log=log||$4::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                        str(org_id), str(client_id), err, _fo_mt_item("не отправилось", why=err))
        return {"state": "error", "why": err}
    await c.execute(
        "UPDATE fo_meet SET status='proposed', kind=$3, offer=$4::jsonb, tg_chat_id=$5, msg_id=$6, sent_at=now(), "
        "answered_at=CASE WHEN $7::bigint IS NULL THEN NULL ELSE answered_at END, attn=NULL, "
        "camp_id=coalesce($8, camp_id), wave=coalesce($9, wave), log=log||$10::jsonb, week_of=$11, pend=NULL, updated_at=now() "
        "WHERE org_id=$1::uuid AND client_id=$2::uuid",
        str(org_id), str(client_id), kind, _fo_json.dumps(_fo_mt_dump(offer)), sent["tg"], sent["msg_id"],
        reply_to, camp, wave, _fo_mt_item("предложено клиенту" if kind != "confirm" else "спросили, всё ли в силе",
                                          text=txt[:400], test=("да" if test else None)), wk)
    applied = await _fo_mt_apply(c, org_id, client_id, offer)
    return {"state": "proposed", "msg_id": sent["msg_id"], "задачи": applied, "неделя": wk.isoformat()}


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
        if not r or r["status"] == "off":
            return {"state": "нет графика"}
        pend = _fo_mt_load(r["pend"], None)
        if pend:
            return await _fo_mt_pend_answer(c, org_id, client_id, r, pend, text, msg_id, pk, test)
        if r["status"] != "proposed":
            return await _fo_mt_request(c, org_id, client_id, r, text, msg_id, pk, test)
        offer = _fo_mt_slots(r["offer"]) or _fo_mt_slots(r["slots"])
    js = await _fo_mt_parse(text, offer, org_id)
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
    r = await c.fetchrow("SELECT client_id, status, msg_id, sent_at, pend FROM fo_meet WHERE org_id=$1::uuid AND client_id=$2::uuid",
                         str(org_id), str(client_id))
    if not r or r["status"] == "off":
        return None
    cid = str(r["client_id"])
    rep = msg.get("reply_to_message") or {}
    frm = rep.get("from") or {}
    if rep.get("message_id") and r["msg_id"] and int(rep["message_id"]) == int(r["msg_id"]):
        return cid
    if frm.get("is_bot") and _FO_MT_ME.get("v") and frm.get("username") == _FO_MT_ME.get("v"):
        return cid
    if rep.get("message_id") and not frm.get("is_bot"):
        return cid if _FO_MT_REQ_RX.search(str(text or "")) else None
    waiting = r["status"] == "proposed" or bool(_fo_mt_load(r["pend"], None))
    fresh = r["sent_at"] and (_fo_dt.datetime.now(_fo_dt.timezone.utc) - r["sent_at"]).total_seconds() <= 3 * 86400
    if waiting and fresh and _FO_MT_ANS_RX.search(str(text or "")):
        return cid
    return cid if _FO_MT_REQ_RX.search(str(text or "")) else None


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
    """За час до начала: клиенту карточка «через час» (если на эту неделю согласовано), проджекту — в личку."""
    now = _fo_mt_now()
    today = now.date()
    if today.weekday() > 4:
        return 0
    mnow, mon, n = now.hour * 60 + now.minute, _fo_mt_mon(today), 0
    for r in await c.fetch("SELECT * FROM fo_meet WHERE status<>'off'"):
        for x in await _fo_mt_week(c, r["org_id"], r["client_id"], mon, r):
            t = _fo_mt_m(x["time"])
            if x["day"] != today or t is None or not (0 < t - mnow <= 60):
                continue
            k = today.isoformat() + " " + x["time"]
            if not await c.fetchval("INSERT INTO fo_meet_rem (org_id, client_id, k) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING 1",
                                    r["org_id"], r["client_id"], k):
                continue
            test = str(r["tg_chat_id"] or "").startswith("test")
            names = await _fo_mt_names(c, r["org_id"])
            cab = await c.fetchval("SELECT name FROM client WHERE id=$1", r["client_id"]) or ""
            notes = []
            if x["kind"] != "regular" or (r["status"] == "agreed" and r["week_of"] == mon):
                sent, err = await _fo_mt_card(c, r["org_id"], r["client_id"], "remind", _fo_mt_caption("remind", cab, [x], names), test=test)
                notes.append("клиенту: " + ("напомнили" if sent else err))
            notes.append(await _fo_mt_dm(c, x["host"], "⏰ Через час планёрка: %s, %s–%s." % (
                cab, x["time"], _fo_mt_hm(t + int(x["minutes"]))), test))
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
                await _fo_mt_auto(c)
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
                  "week_of": r["week_of"].isoformat() if r["week_of"] else None, "pend": _fo_mt_load(r["pend"], None),
                  "test": str(r["tg_chat_id"] or "").startswith("test")})
    return d


@router.get("/meet")
async def fo_meet_get(p: Principal = Depends(max_level(4))):
    _fo_mt_kick()
    async with pool().acquire() as c:
        await _fo_mt_migrate(c, p.org_id)
        lv = await _fo_mt_levels(c, p.org_id)
        rows = {str(r["client_id"]): r for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(p.org_id))}
        chats = {}
        for r in await c.fetch("SELECT DISTINCT ON (cc.client_id) cc.client_id, ch.chat_id FROM client_chat cc "
                               "JOIN chat ch ON ch.id=cc.chat_pk WHERE cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' "
                               "AND ch.org_id=$1 ORDER BY cc.client_id, ch.id", p.org_id):
            chats[str(r["client_id"])] = r["chat_id"]
        st = await _fo_mt_settings(c, p.org_id)
        camp = await c.fetchrow("SELECT * FROM fo_meet_camp WHERE org_id=$1::uuid ORDER BY id DESC LIMIT 1", str(p.org_id))
        fid = await _fo_mt_fn(c, p.org_id)
        held = {}
        if fid:
            for r in await c.fetch("SELECT client_id, plan_date FROM task WHERE org_id=$1 AND fn_id=$2 AND status='done' "
                                   "AND plan_date >= $3", p.org_id, fid, _fo_msk_today() - _fo_dt.timedelta(days=75)):
                if r["client_id"]:
                    held.setdefault(str(r["client_id"]), []).append(r["plan_date"].isoformat())
    out = []
    for cid in sorted(lv, key=lambda k: lv[k]["rank"]):
        o = _fo_mt_out(cid, rows.get(cid), lv, cid in chats)
        try:
            cs = await _fo_mt_chatstate(chats.get(cid)) if cid in chats else {"in": False, "pin": False, "why": ""}
        except Exception:
            cs = {"in": None, "pin": None, "why": ""}
        o["bot_in"], o["bot_pin"] = cs["in"], cs["pin"]
        out.append(o)
    cp = None
    if camp:
        cp = {"id": camp["id"], "status": camp["status"], "wave": camp["wave"], "gap_min": camp["gap_min"],
              "test": bool(camp["test"]), "started_at": camp["started_at"].isoformat(),
              "wave_at": camp["wave_at"].isoformat() if camp["wave_at"] else None}
    try:
        bname = await _fo_mt_botname()
    except Exception:
        bname = ""
    mon = _fo_mt_mon()
    async with pool().acquire() as c:
        occ = [{"client_id": str(o["client_id"]), "day": o["day"].isoformat(), "time": o["time"], "minutes": int(o["minutes"]),
                "host": str(o["host"] or ""), "kind": o["kind"], "src_day": o["src_day"].isoformat() if o["src_day"] else None}
               for o in await c.fetch("SELECT * FROM fo_meet_occ WHERE org_id=$1::uuid AND status='agreed' AND day BETWEEN $2 AND $3",
                                      str(p.org_id), mon - _fo_dt.timedelta(days=7), mon + _fo_dt.timedelta(days=45))]
        skips = [{"client_id": str(x["client_id"]), "day": x["day"].isoformat(), "reason": x["reason"]}
                 for x in await c.fetch("SELECT client_id, day, reason FROM fo_task_skip WHERE org_id=$1::uuid AND client_id IS NOT NULL "
                                        "AND day BETWEEN $2 AND $3", str(p.org_id), mon - _fo_dt.timedelta(days=7), mon + _fo_dt.timedelta(days=45))]
    return {"rows": out, "camp": cp, "held": held, "fn": bool(fid), "bot": bool(_fo_mt_tok()),
            "own_bot": bool(_fo_env("TG_MEET_BOT_TOKEN")), "bot_name": bname, "occ": occ, "skips": skips,
            "mon": mon.isoformat(), "today": _fo_mt_now().date().isoformat(),
            "settings": {"brk": st["brk"], "gap": st["gap"], "from": _fo_mt_hm(st["from"]), "to": _fo_mt_hm(st["to"]),
                         "auto": st["auto"], "auto_at": _fo_mt_hm(st["auto_at"])},
            "levels": {str(k): {"min": v[0], "max": v[1], "def": v[2]} for k, v in _FO_MT_LVL.items()}}


@router.get("/meet/times")
async def fo_meet_times(p: Principal = Depends(current)):
    """Время планёрок для ганта по датам (эта и следующая неделя, с переносами и дополнительными):
    РМ и выше — все, остальным — где ведут сами."""
    mon = _fo_mt_mon()
    async with pool().acquire() as c:
        await _fo_mt_migrate(c, p.org_id)
        me = None if _fo_st_lvl(p) <= 4 else str(await _fo_my_emp(c, p) or "")
        out = {}
        for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(p.org_id)):
            dates = {}
            for w in (mon, mon + _fo_dt.timedelta(days=7)):
                for x in await _fo_mt_week(c, p.org_id, r["client_id"], w, r):
                    if me is None or x["host"] == me:
                        dates.setdefault(x["day"].isoformat(), []).append({"time": x["time"], "minutes": int(x["minutes"]),
                                                                           "host": x["host"], "kind": x["kind"]})
            if dates:
                out[str(r["client_id"])] = {"status": r["status"], "week_of": r["week_of"].isoformat() if r["week_of"] else None,
                                            "slots": _fo_mt_dump(_fo_mt_eff(r)), "dates": dates}
    return {"times": out, "mon": mon.isoformat()}


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
        if status == "agreed" and body.mark == "agreed":
            await c.execute("UPDATE fo_meet SET week_of=$3 WHERE org_id=$1::uuid AND client_id=$2::uuid",
                            str(p.org_id), client_id, _fo_mt_mon())
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


async def _fo_mt_camp_start(c, org_id, clients=None, all_=True, gap=None, test=False, uid=None, dry=False, auto=False):
    """Рассылка на неделю волнами: 0 — фиксированным «всё в силе?», 1 — высокий приоритет, 2 — средний, 3 — низкий.
    Кому уже согласовано на эту неделю — не пишем. Следующая волна — когда все ответили или прошло gap минут."""
    await _fo_mt_migrate(c, org_id)
    lv = await _fo_mt_levels(c, org_id)
    st = await _fo_mt_settings(c, org_id)
    names = await _fo_mt_names(c, org_id)
    mon = _fo_mt_mon()
    rows = {str(r["client_id"]): r for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(org_id))}
    want = set(clients or rows.keys())
    cand, skip = [], []
    for cid, r in rows.items():
        if cid not in want:
            continue
        sl = _fo_mt_slots(r["slots"])
        if not sl or r["status"] == "off":
            continue
        if r["status"] == "agreed" and r["week_of"] and r["week_of"] >= mon:
            skip.append({"client": lv.get(cid, {}).get("name"), "why": "на эту неделю уже согласовано"})
            continue
        if r["status"] == "agreed" and not all_:
            skip.append({"client": lv.get(cid, {}).get("name"), "why": "уже назначена"})
            continue
        cand.append((cid, r))
    if not cand:
        return {"ok": False, "why": "некому предлагать: у всех на эту неделю согласовано или нет графика", "skip": skip}
    chats = {}
    for r in await c.fetch("SELECT DISTINCT ON (cc.client_id) cc.client_id, ch.chat_id FROM client_chat cc "
                           "JOIN chat ch ON ch.id=cc.chat_pk WHERE cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' "
                           "AND ch.org_id=$1 ORDER BY cc.client_id, ch.id", org_id):
        try:
            if (await _fo_mt_chatstate(r["chat_id"]))["in"]:
                chats[str(r["client_id"])] = r["chat_id"]
        except Exception:
            pass
    wv = lambda cid, r: 0 if r["fixed"] else lv.get(cid, {"level": 3})["level"]
    cand.sort(key=lambda x: (wv(*x), lv.get(x[0], {}).get("rank", 999)))
    busy = await _fo_mt_busy(c, org_id, skip=[x[0] for x in cand])
    preview = []
    for cid, r in cand:
        L = lv.get(cid, {"level": 3, "name": ""})
        offer = _fo_mt_offer(busy, _fo_mt_slots(r["slots"]), L["level"], bool(r["fixed"]), st, cid)
        wk, items = await _fo_mt_weekitems(c, org_id, cid, offer, r)
        preview.append({"client_id": cid, "client": L.get("name"), "wave": wv(cid, r), "level": L["level"],
                        "fixed": bool(r["fixed"]), "chat": cid in chats or test, "week": wk.isoformat(),
                        "offer": _fo_mt_dump(offer),
                        "text": re.sub(r"<[^>]+>", "", _fo_mt_caption("confirm" if r["fixed"] else "week", L.get("name") or "", items, names))})
    if dry:
        return {"dry": True, "waves": preview, "skip": skip, "brk": st["brk"]}
    gap = max(15, min(72 * 60, int(gap or st["gap"])))
    await c.execute("UPDATE fo_meet_camp SET status='stopped' WHERE org_id=$1::uuid AND status='active'", str(org_id))
    camp_id = await c.fetchval("INSERT INTO fo_meet_camp (org_id, started_by, gap_min, test, note) VALUES ($1::uuid, $2, $3, $4, $5) RETURNING id",
                               str(org_id), uid, gap, bool(test), "авто: понедельник" if auto else None)
    for x in preview:
        await c.execute("UPDATE fo_meet SET status='queued', wave=$3, level=$4, camp_id=$5, rounds=0, attn=NULL, pend=NULL, "
                        "log=log||$6::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                        str(org_id), x["client_id"], x["wave"], x["level"], camp_id,
                        _fo_mt_item("в очереди рассылки, волна %s%s" % (x["wave"], " (понедельник, сам)" if auto else "")))
    res = await _fo_mt_advance(c, org_id, camp_id)
    return {"ok": True, "camp_id": camp_id, **res}


@router.post("/meet/campaign")
async def fo_meet_campaign(body: FoMtCampIn, p: Principal = Depends(max_level(4))):
    """dry — только показать, что и кому уйдёт; иначе — запустить рассылку."""
    uid = _fo_uid(p) if re.match(r"^[0-9a-fA-F-]{36}$", str(_fo_uid(p))) else None
    async with pool().acquire() as c:
        if body.dry:
            res = await _fo_mt_camp_start(c, p.org_id, body.clients, True, body.gap_min, body.test, uid, dry=True)
        else:
            if not await c.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", "fo-meet:" + str(p.org_id)):
                raise HTTPException(409, "рассылка уже идёт — попробуйте через минуту")
            try:
                res = await _fo_mt_camp_start(c, p.org_id, body.clients, True, body.gap_min, body.test, uid)
            finally:
                await c.execute("SELECT pg_advisory_unlock(hashtext($1))", "fo-meet:" + str(p.org_id))
    if res.get("ok") is False:
        raise HTTPException(400, res["why"])
    _fo_mt_kick()
    return res


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
    auto: bool | None = None
    auto_at: str | None = None
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
    if body.auto is not None:
        d["auto"] = bool(body.auto)
    if body.auto_at and _fo_mt_m(body.auto_at) is not None:
        d["auto_at"] = _fo_mt_hm(_fo_mt_m(body.auto_at))
    async with pool().acquire() as c:
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
            "meet:" + str(p.org_id), p.org_id, _fo_json.dumps(d))
        st = await _fo_mt_settings(c, p.org_id)
    return {"ok": True, "settings": {"brk": st["brk"], "gap": st["gap"], "from": _fo_mt_hm(st["from"]), "to": _fo_mt_hm(st["to"]),
                                     "auto": st["auto"], "auto_at": _fo_mt_hm(st["auto_at"])}}


class FoMtRuleIn(_FoBM):
    add: str | None = None
    remove: int | None = None


@router.get("/meet/rules")
async def fo_meet_rules_get(p: Principal = Depends(max_level(4))):
    async with pool().acquire() as c:
        return {"rules": await _fo_mt_rules(c, p.org_id)}


@router.post("/meet/rules")
async def fo_meet_rules_set(body: FoMtRuleIn, p: Principal = Depends(max_level(2))):
    """Учим агента планёрок словами собственника — отдельно от агента задач."""
    async with pool().acquire() as c:
        rules = await _fo_mt_rules(c, p.org_id)
        if body.add and body.add.strip() and body.add.strip()[:500] not in rules:
            rules.append(body.add.strip()[:500])
        if body.remove is not None and 0 <= int(body.remove) < len(rules):
            rules.pop(int(body.remove))
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
            "meet:" + str(p.org_id), p.org_id, _fo_json.dumps({"rules": rules}, ensure_ascii=False))
    return {"ok": True, "rules": rules}


# ── 220: неделя. В понедельник бот согласует планёрки на неделю; в течение недели клиент переносит,
#    отменяет или просит дополнительную — меняется только эта неделя; прошедшую планёрку не трогаем.
#    Карточки в чат — картинка «Планёрка» в фирменном цвете и текст под ней (Виталий 28.09) ──
_FO_MT_DOWN = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_FO_MT_IMG = "/opt/fo/meet"
_FO_MT_FILE = {}
_FO_MT_KIMG = {"week": "week", "confirm": "week", "offer": "offer", "move": "offer", "extra": "offer",
               "cancel": "offer", "agreed": "agreed", "remind": "remind"}
_FO_MT_REQ_RX = re.compile(
    r"план[её]рк|созвон|встреч|перенес|перенос|сдвин|отмен|дополнительн|ещ[её]\s+одн|втор(ую|ой|ая)\s+(план|созв|встреч)|"
    r"другое\s+время|давайте\s+(в|на)\s", re.I)
_FO_MT_SYS2 = (
    "Ты — агент планёрок digital-агентства (кабинеты продавцов Wildberries и OZON). Планёрки с клиентом на неделю "
    "уже согласованы. Клиент пишет в чат. Определи, что он хочет по планёркам.\n"
    "intent: move — перенести планёрку на другой день или время; cancel — отменить планёрку; extra — нужна ещё одна, "
    "дополнительная планёрка или созвон; confirm — подтверждает, что всё в силе; not_about — сообщение не про планёрки "
    "(задача, вопрос по товару, цене, рекламе, поставке); unclear — про планёрку, но непонятно, что сделать.\n"
    "from_date — какую планёрку переносят или отменяют: дата YYYY-MM-DD из списка, иначе null.\n"
    "date — на какой день нужна: YYYY-MM-DD («завтра», «в пятницу» переведи в дату; день недели — ближайший будущий), иначе null.\n"
    "time — время HH:MM по Москве, иначе null.\n"
    "Ответь только JSON без пояснений: {\"intent\": \"move\", \"from_date\": null, \"date\": null, \"time\": null}")


def _fo_mt_now():
    return _fo_dt.datetime.now(_FO_MSK)


def _fo_mt_mon(d=None):
    d = d or _fo_mt_now().date()
    return d - _fo_dt.timedelta(days=d.weekday())


def _fo_mt_h(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fo_mt_dd(day):
    return "%02d.%02d · %s" % (day.day, day.month, _FO_MT_DOWN[day.weekday()].capitalize())


def _fo_mt_date(s):
    try:
        return _fo_dt.date.fromisoformat(str(s)[:10]) if s else None
    except Exception:
        return None


def _fo_mt_dated(sl, mon, skip=None, since=None, from_day=None):
    out = []
    for d, s in sorted(sl.items()):
        day = mon + _fo_dt.timedelta(days=d)
        if (from_day and day < from_day) or (since and day < since) or (skip and day in skip):
            continue
        out.append({"day": day, "time": s["time"], "minutes": int(s["minutes"]), "host": s["host"], "kind": "regular", "id": None})
    return out


def _fo_mt_js(x):
    """Пункт недели для JSON."""
    return {"day": x["day"].isoformat(), "time": x["time"], "minutes": int(x["minutes"]), "host": x["host"],
            "kind": x.get("kind") or "regular", "id": x.get("id")}


def _fo_mt_unjs(x):
    x = dict(x or {})
    x["day"] = _fo_mt_date(x.get("day"))
    return x


async def _fo_mt_week(c, org_id, client_id, mon, r=None):
    """Планёрки клиента на неделю: график (или предложение) минус отменённые дни плюс переносы и дополнительные."""
    if r is None:
        r = await _fo_mt_row(c, org_id, client_id)
    end = mon + _fo_dt.timedelta(days=6)
    out = []
    if r and r["status"] != "off":
        skips = {x["day"] for x in await c.fetch(
            "SELECT day FROM fo_task_skip WHERE org_id=$1::uuid AND client_id=$2::uuid AND day BETWEEN $3 AND $4",
            str(org_id), str(client_id), mon, end)}
        out += _fo_mt_dated(_fo_mt_eff(r), mon, skips, r["since"])
    for o in await c.fetch("SELECT * FROM fo_meet_occ WHERE org_id=$1::uuid AND client_id=$2::uuid AND day BETWEEN $3 AND $4 "
                           "AND status='agreed'", str(org_id), str(client_id), mon, end):
        out.append({"day": o["day"], "time": o["time"], "minutes": int(o["minutes"]), "host": str(o["host"] or ""),
                    "kind": o["kind"], "id": o["id"], "src": o["src_day"]})
    return sorted(out, key=lambda x: (x["day"], _fo_mt_m(x["time"]) or 0))


async def _fo_mt_daybusy(c, org_id, day, skip_key=None):
    """Занятость ведущих в конкретный день (с переносами и дополнительными), кроме одной планёрки skip_key."""
    mon, busy = _fo_mt_mon(day), {}
    for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(org_id)):
        for x in await _fo_mt_week(c, org_id, r["client_id"], mon, r):
            if x["day"] != day or not x["host"]:
                continue
            if skip_key and (str(r["client_id"]), x["day"], x["time"]) == skip_key:
                continue
            t = _fo_mt_m(x["time"])
            if t is not None:
                busy.setdefault((x["host"], day.weekday()), []).append((t, t + int(x["minutes"]), str(r["client_id"])))
    return busy


async def _fo_mt_heldset(c, org_id, client_id, a, b):
    fid = await _fo_mt_fn(c, org_id)
    if not fid:
        return set()
    return {x["plan_date"] for x in await c.fetch(
        "SELECT plan_date FROM task WHERE org_id=$1 AND fn_id=$2 AND client_id=$3::uuid AND status='done' "
        "AND plan_date BETWEEN $4 AND $5", org_id, fid, str(client_id), a, b)}


def _fo_mt_cap_item(x, names):
    t = _fo_mt_m(x["time"])
    end = _fo_mt_hm(t + int(x["minutes"])) if t is not None else ""
    return "📅 %s\n🕛 %s (до %s) · ведёт %s" % (_fo_mt_dd(x["day"]), x["time"], end, _fo_mt_h(names.get(x["host"], "проджект")))


def _fo_mt_caption(kind, cab, items, names, note=""):
    head = {"week": "⭐️🟢 <b>Планёрки на неделю</b>", "confirm": "⭐️🟢 <b>Планёрки на неделю</b>",
            "offer": "⭐️🟢 <b>Планёрка</b>", "move": "⭐️🟡 <b>Перенос планёрки</b>",
            "extra": "⭐️🟢 <b>Дополнительная планёрка</b>", "agreed": "✅ <b>Планёрка назначена</b>",
            "remind": "⏰ <b>Планёрка через час</b>", "cancel": "⭐️⚪️ <b>Отмена планёрки</b>"}[kind]
    tail = {"week": "Удобно? Ответьте на это сообщение «да» — или напишите, что поменять.\n"
                    "В течение недели планёрку можно перенести или попросить дополнительную — просто напишите здесь.",
            "confirm": "Всё в силе по нашему постоянному времени? Ответьте «да» — или напишите, что поменять.",
            "offer": "Удобно? Ответьте «да» — или напишите, какое время подходит.",
            "move": "Подходит? Ответьте «да» — или напишите другое время.",
            "extra": "Подходит? Ответьте «да» — или напишите другое время.",
            "agreed": "До встречи!", "remind": "До встречи через час!",
            "cancel": "Отменяем? Ответьте «да» — или напишите, что оставить."}[kind]
    body = "\n\n".join(_fo_mt_cap_item(x, names) for x in items) or "—"
    return "%s\n<b>%s</b>\n\n%s%s\n\n%s" % (head, _fo_mt_h(cab), body, ("\n\n" + note) if note else "", tail)


def _fo_tg_photo_sync(tok, chat_id, img, caption, reply_to=None):
    """Карточка: картинка «Планёрка» и подпись. Картинка грузится один раз, дальше — по file_id."""
    import uuid as _uu
    key = (tok[:14], img)
    prm = {"chat_id": str(chat_id), "caption": caption[:1024], "parse_mode": "HTML"}
    if reply_to:
        prm["reply_parameters"] = _fo_json.dumps({"message_id": int(reply_to), "allow_sending_without_reply": True})
    if _FO_MT_FILE.get(key):
        res = _fo_tg_api_sync("sendPhoto", dict(prm, photo=_FO_MT_FILE[key]), tok)
        if res.get("ok"):
            return res
    try:
        data = open("%s/meet_%s.jpg" % (_FO_MT_IMG, img), "rb").read()
    except Exception:
        return {"ok": False, "description": "на сервере нет картинки " + img}
    b = "----fo" + _uu.uuid4().hex
    body = b"".join([("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8")
                     for k, v in prm.items()])
    body += ("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"planerka.jpg\"\r\n"
             "Content-Type: image/jpeg\r\n\r\n" % b).encode() + data + ("\r\n--%s--\r\n" % b).encode()
    rq = _fo_ur.Request("https://api.telegram.org/bot%s/sendPhoto" % tok, data=body,
                        headers={"Content-Type": "multipart/form-data; boundary=" + b})
    try:
        with _fo_ur.urlopen(rq, timeout=40) as r:
            res = _fo_json.loads(r.read().decode())
    except Exception as e:
        txt = ""
        try:
            txt = e.read().decode()[:300]
        except Exception:
            pass
        try:
            res = _fo_json.loads(txt)
        except Exception:
            res = {"ok": False, "description": (str(e) + " " + txt).replace(tok, "***")[:300]}
    if res.get("ok"):
        ph = ((res.get("result") or {}).get("photo") or [{}])[-1]
        if ph.get("file_id"):
            _FO_MT_FILE[key] = ph["file_id"]
    return res


async def _fo_mt_card(c, org_id, client_id, kind, caption, reply_to=None, test=False):
    """Карточка планёрки в чат клиента от бота планёрок; не ушла картинка — уходит тем же текстом."""
    plain = re.sub(r"<[^>]+>", "", caption).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    if test:
        return await _fo_mt_send(c, org_id, client_id, "[карточка «%s»]\n%s" % (_FO_MT_KIMG.get(kind, "offer"), plain),
                                 reply_to=reply_to, test=True)
    ch = await _fo_mt_chat(c, client_id)
    if not ch:
        return None, "у клиента нет чата с ботом"
    tok = _fo_mt_tok()
    if not tok:
        return None, "бот планёрок не подключён"
    res = await _fo_aio.to_thread(_fo_tg_photo_sync, tok, ch["chat_id"], _FO_MT_KIMG.get(kind, "offer"), caption, reply_to)
    if not res.get("ok"):
        prm = {"chat_id": ch["chat_id"], "text": caption, "parse_mode": "HTML"}
        if reply_to:
            prm["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
        res = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", prm)
    if not res.get("ok"):
        return None, "Telegram: " + str(res.get("description") or "не отправилось")[:200]
    mid = int(res["result"]["message_id"])
    try:
        await c.execute(
            "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at, ai_state, ai_note) "
            "VALUES ($1,$2::uuid,$3,'client',$4,$5,'Бот планёрок','',$6,now(),'skip','сообщение бота планёрок') "
            "ON CONFLICT (tg_chat_id, msg_id) DO NOTHING", org_id, str(client_id), ch["chat_pk"], ch["chat_id"], mid, plain[:4000])
    except Exception:
        pass
    return {"tg": ch["chat_id"], "msg_id": mid}, ""


async def _fo_mt_weekitems(c, org_id, client_id, sl, r):
    """Что предлагать клиенту: оставшиеся дни этой недели; если на этой неделе уже ничего — следующая неделя."""
    today = _fo_mt_now().date()
    mon = _fo_mt_mon(today)
    skips = {x["day"] for x in await c.fetch("SELECT day FROM fo_task_skip WHERE org_id=$1::uuid AND client_id=$2::uuid "
                                            "AND day >= $3", str(org_id), str(client_id), mon)}
    since = r["since"] if r else None
    now = _fo_mt_now()
    items = [x for x in (_fo_mt_dated(sl, mon, skips, since, today) if today.weekday() <= 4 else [])
             if x["day"] > today or (_fo_mt_m(x["time"]) or 0) > now.hour * 60 + now.minute]
    if not items:
        mon = mon + _fo_dt.timedelta(days=7)
        items = _fo_mt_dated(sl, mon, skips, since)
    return mon, items


# ── в течение недели: перенос, отмена, дополнительная ──
async def _fo_mt_req_parse(text, items, now, held, org_id):
    """Агент планёрок: что клиент хочет по планёркам этой недели (ИИ Яндекс + правила агента; без ИИ — по словам)."""
    t = str(text or "").lower().replace("ё", "е")
    rx = _fo_mt_rx(text)
    base = {"intent": "cancel" if re.search(r"отмен|не\s+будет\s+план|без\s+план[её]рк", t) else
            "extra" if re.search(r"дополнительн|ещ[её]\s+одн|втор(ую|ой|ая)\s+(план|созв|встреч)|ещ[её]\s+(план|созв|встреч)", t) else
            "move" if re.search(r"перенес|перенос|сдвин|другое\s+время|давайте\s+(в|на)\s|можно\s+(в|на)\s", t) else
            "unclear" if re.search(r"план[её]рк|созвон|встреч", t) else "not_about",
            "from_date": None, "date": None, "time": rx["time"], "by": "правило"}
    base["from_day"], base["day"] = _fo_mt_daywords(text)
    if not _fo_ai_ready():
        return base
    lst = "\n".join("- %s (%s) %s–%s%s" % (x["day"].isoformat(), _FO_MT_DOWN[x["day"].weekday()][:2], x["time"],
                                          _fo_mt_hm((_fo_mt_m(x["time"]) or 0) + int(x["minutes"])),
                                          " — прошла" if x["day"] in held or x["day"] < now.date() else "") for x in items) or "(нет)"
    usr = "Сегодня: %s, %s, %s (Москва).\nПланёрки клиента:\n%s\nСообщение клиента: «%s»" % (
        now.date().isoformat(), _FO_MT_DOWN[now.weekday()], now.strftime("%H:%M"), lst, str(text or "")[:800])
    sys_t = _FO_MT_SYS2
    try:
        async with pool().acquire() as c:
            rl = await _fo_mt_rules(c, org_id)
        if rl:
            sys_t += "\n\nПравила агента планёрок этого агентства (важнее общих):\n" + "\n".join("- " + r for r in rl[:40])
    except Exception:
        pass
    try:
        txt, _u = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": sys_t}, {"role": "user", "text": usr}], 200)
        js = _fo_ai_json(txt) or {}
    except Exception:
        return base
    if js.get("intent") not in ("move", "cancel", "extra", "confirm", "not_about", "unclear"):
        return base
    js["by"] = "ИИ"
    js["time"] = _fo_mt_hm(_fo_mt_m(js.get("time"))) if _fo_mt_m(js.get("time")) is not None else base["time"]
    js["day"], js["from_day"] = base["day"], base["from_day"]
    return js


_FO_MT_TO_RX = [(0, r"(?:на|в|во)\s+понедельник"), (1, r"(?:на|в|во)\s+вторник"), (2, r"(?:на|в|во)\s+сред[уы]"),
                (3, r"(?:на|в|во)\s+четверг"), (4, r"(?:на|в|во)\s+пятниц")]
_FO_MT_FROM_RX = [(0, r"понедельничн|с\s+понедельника|понедельник\w*\s+(?:перенес|отмен|сдвин)"),
                  (1, r"вторничн|с\s+вторника|вторник\w*\s+(?:перенес|отмен|сдвин)"),
                  (2, r"средов|с\s+среды|сред[аы]\s+(?:перенес|отмен|сдвин)"),
                  (3, r"четвергов|с\s+четверга|четверг\w*\s+(?:перенес|отмен|сдвин)"),
                  (4, r"пятничн|с\s+пятницы|пятниц\w*\s+(?:перенес|отмен|сдвин)")]


def _fo_mt_daywords(text):
    """Куда и откуда: «четверговую перенесём на пятницу» → откуда 3, куда 4."""
    t = str(text or "").lower().replace("ё", "е")
    to = next((d for d, rx in _FO_MT_TO_RX if re.search(rx, t)), None)
    fr = next((d for d, rx in _FO_MT_FROM_RX if re.search(rx, t)), None)
    if to is None and fr is None:
        ds = _fo_mt_rx(text)["days"]
        if len(ds) == 1:
            to = ds[0]
    return fr, to


def _fo_mt_workday(day):
    while day.weekday() > 4:
        day += _fo_dt.timedelta(days=1)
    return day


async def _fo_mt_request(c, org_id, client_id, r, text, msg_id, pk, test):
    now = _fo_mt_now()
    today, mon = now.date(), _fo_mt_mon(now.date())
    items = await _fo_mt_week(c, org_id, client_id, mon, r) + await _fo_mt_week(c, org_id, client_id, mon + _fo_dt.timedelta(days=7), r)
    held = await _fo_mt_heldset(c, org_id, client_id, mon, mon + _fo_dt.timedelta(days=13))
    mnow = now.hour * 60 + now.minute

    def past(x):
        t = _fo_mt_m(x["time"]) or 0
        return x["day"] in held or x["day"] < today or (x["day"] == today and t <= mnow)

    js = await _fo_mt_req_parse(text, items, now, held, org_id)
    it = js.get("intent")
    await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), str(text or "")[:500],
                    _fo_mt_item("сообщение клиента в течение недели", text=str(text or "")[:300], понял=it, by=js.get("by")))
    if it == "not_about":
        if pk and _fo_ai_ready() and not test:
            try:
                await c.execute("UPDATE fo_chat_msg SET ai_state=NULL, ai_note='не про планёрку — в разбор задач' WHERE id=$1", pk)
                _fo_aio.get_running_loop().create_task(_fo_ai_process(pk))
            except Exception:
                pass
        return {"state": "не про планёрку — агенту задач"}
    if it == "confirm":
        return {"state": "подтвердил, ничего не меняем"}
    if it == "unclear":
        sent, err = await _fo_mt_send(c, org_id, client_id, "Уточните, пожалуйста: перенести планёрку, отменить или нужна "
                                      "дополнительная? Напишите день и время — подберём.", reply_to=msg_id, test=test)
        return {"state": "уточняем", "send": err or "отправлено"}
    st = await _fo_mt_settings(c, org_id)
    names = await _fo_mt_names(c, org_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    want_day = _fo_mt_date(js.get("date"))
    if want_day and not (today <= want_day <= today + _fo_dt.timedelta(days=14)):
        want_day = None
    if js.get("day") is not None and (not want_day or want_day.weekday() != int(js["day"])):
        want_day = mon + _fo_dt.timedelta(days=int(js["day"]))      # день недели из слов клиента надёжнее даты от ИИ
        if want_day < today:
            want_day += _fo_dt.timedelta(days=7)
    if want_day:
        want_day = _fo_mt_workday(want_day)
    tgt = None
    if it in ("move", "cancel"):
        fd = _fo_mt_date(js.get("from_date"))
        if js.get("from_day") is not None and (not fd or fd.weekday() != int(js["from_day"])):
            fd = next((x["day"] for x in items if x["day"].weekday() == int(js["from_day"]) and not past(x)),
                      next((x["day"] for x in items if x["day"].weekday() == int(js["from_day"])), None))
        cand = [x for x in items if fd and x["day"] == fd]
        if cand and all(past(x) for x in cand):
            sent, err = await _fo_mt_send(c, org_id, client_id, "Эта планёрка уже прошла ✓ Если нужна ещё одна встреча на этой "
                                          "неделе — напишите день и время, поставим дополнительную.", reply_to=msg_id, test=test)
            return {"state": "планёрка уже прошла"}
        tgt = next((x for x in cand if not past(x)), None) or next((x for x in items if not past(x)), None)
        if not tgt:
            sent, err = await _fo_mt_send(c, org_id, client_id, "Планёрки этой недели уже прошли ✓ Нужна дополнительная встреча? "
                                          "Напишите день и время.", reply_to=msg_id, test=test)
            return {"state": "переносить нечего"}
    if it == "cancel":
        pend = {"type": "cancel", "from": _fo_mt_js(tgt), "rounds": 0}
        cap = _fo_mt_caption("cancel", cab, [tgt], names)
        return await _fo_mt_pend_send(c, org_id, client_id, pend, "cancel", cap, msg_id, test, names, cab)
    sl = _fo_mt_slots(r["slots"]) if r else {}
    if it == "move":
        day = want_day or tgt["day"]
        host, mins = tgt["host"], int(tgt["minutes"])
        pref = _fo_mt_m(js.get("time")) if js.get("time") else _fo_mt_m(tgt["time"])
        skip = (str(client_id), tgt["day"], tgt["time"])
    else:
        day = want_day or _fo_mt_workday(today + _fo_dt.timedelta(days=1))
        src = sl.get(day.weekday()) or (sl[sorted(sl)[0]] if sl else None)
        host = (src or {}).get("host") or ""
        lv = (await _fo_mt_levels(c, org_id)).get(str(client_id), {"level": 3})
        mins = _FO_MT_LVL[lv["level"]][2]
        pref = _fo_mt_m(js.get("time")) if js.get("time") else (_fo_mt_m((src or {}).get("time")) or st["from"])
        skip = None
    if not host:
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "клиент просит: «%s», а ведущего в графике нет" % str(text)[:100])
    busy = await _fo_mt_daybusy(c, org_id, day, skip)
    d = day.weekday()
    ok = _fo_mt_fits(busy, host, d, pref, mins, st) and (not busy.get((host, d)) or _fo_mt_adjacent(busy, host, d, pref, mins, st))
    t = pref if ok else ((_fo_mt_place(busy, host, d, pref, mins, st, 1) or [None])[0])
    if t is None:
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "у ведущего нет окна: «%s»" % str(text)[:120])
    to = {"day": day, "time": _fo_mt_hm(t), "minutes": mins, "host": host, "kind": "moved" if it == "move" else "extra"}
    note = ""
    if it == "move":
        note = "Было: %s в %s" % (_fo_mt_dd(tgt["day"]), tgt["time"])
    if pref is not None and t != pref:
        note = (note + "\n" if note else "") + "На %s поставить не получится: планёрки у нас идут одним блоком с перерывами." % _fo_mt_hm(pref)
    pend = {"type": it, "from": _fo_mt_js(tgt) if tgt else None, "to": _fo_mt_js(to), "rounds": 0}
    cap = _fo_mt_caption("move" if it == "move" else "extra", cab, [to], names, note)
    return await _fo_mt_pend_send(c, org_id, client_id, pend, it, cap, msg_id, test, names, cab)


async def _fo_mt_pend_send(c, org_id, client_id, pend, kind, cap, msg_id, test, names, cab):
    sent, err = await _fo_mt_card(c, org_id, client_id, kind, cap, reply_to=msg_id, test=test)
    if not sent:
        return {"state": "error", "why": err}
    await c.execute("UPDATE fo_meet SET pend=$3::jsonb, msg_id=$4, tg_chat_id=$5, sent_at=now(), log=log||$6::jsonb, updated_at=now() "
                    "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), _fo_json.dumps(pend),
                    sent["msg_id"], sent["tg"], _fo_mt_item({"move": "предложили перенос", "cancel": "спросили про отмену",
                                                            "extra": "предложили дополнительную"}[kind],
                                                           text=re.sub(r"<[^>]+>", "", cap)[:400], test=("да" if test else None)))
    to = _fo_mt_unjs(pend.get("to")) if pend.get("to") else _fo_mt_unjs(pend.get("from"))
    sl = {0: {"host": to.get("host"), "time": to.get("time"), "minutes": to.get("minutes") or 60}}
    dm = await _fo_mt_notify(c, sl, "↔ %s: клиент в чате — «%s». Бот предложил: %s %s. Ждём «да»." % (
        cab, {"move": "перенести планёрку", "cancel": "отменить планёрку", "extra": "дополнительную планёрку"}[kind],
        _fo_mt_dd(to["day"]) if to.get("day") else "", to.get("time") or ""), test)
    return {"state": "ждём ответа", "pend": pend, "проджекту": dm}


async def _fo_mt_pend_apply(c, org_id, client_id, pend, msg_id, test):
    """Клиент ответил «да» на перенос, отмену или дополнительную: меняем только этот день, задачи ведущему — сразу."""
    fid = await _fo_mt_fn(c, org_id)
    cab_id = await c.fetchval("SELECT id FROM cabinet WHERE client_id=$1::uuid ORDER BY name LIMIT 1", str(client_id))
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    names = await _fo_mt_names(c, org_id)
    kind = pend.get("type")
    fr = _fo_mt_unjs(pend.get("from")) if pend.get("from") else None
    to = _fo_mt_unjs(pend.get("to")) if pend.get("to") else None
    async with c.transaction():
        if fr and kind in ("move", "cancel"):
            if (fr.get("kind") or "regular") == "regular":
                if cab_id and fid:
                    await c.execute("INSERT INTO fo_task_skip (org_id, cabinet_id, fn_id, day, client_id, reason) "
                                    "VALUES ($1::uuid, $2, $3, $4, $5::uuid, $6) ON CONFLICT DO NOTHING",
                                    str(org_id), cab_id, fid, fr["day"], str(client_id), kind)
                    await c.execute("DELETE FROM task WHERE org_id=$1 AND cabinet_id=$2 AND fn_id=$3 AND plan_date=$4 "
                                    "AND source='generator' AND status='planned'", org_id, cab_id, fid, fr["day"])
            elif fr.get("id"):
                tid = await c.fetchval("UPDATE fo_meet_occ SET status='cancelled' WHERE id=$1 RETURNING task_id", int(fr["id"]))
                if tid:
                    await c.execute("DELETE FROM task WHERE id=$1 AND status='planned'", tid)
        if to and kind in ("move", "extra"):
            oid = await c.fetchval(
                "INSERT INTO fo_meet_occ (org_id, client_id, day, time, minutes, host, kind, src_day) "
                "VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::uuid, $7, $8) RETURNING id",
                str(org_id), str(client_id), to["day"], to["time"], int(to["minutes"]), to["host"] or None,
                "moved" if kind == "move" else "extra", fr["day"] if fr else None)
            if cab_id and fid:
                try:
                    tid = await c.fetchval(
                        "INSERT INTO task (org_id, kind, fn_id, client_id, cabinet_id, title, source, assignee_id, plan_date, plan_minutes) "
                        "VALUES ($1, 'cyclic', $2, $3::uuid, $4, $5, 'meet', $6::uuid, $7, $8) RETURNING id",
                        org_id, fid, str(client_id), cab_id, "Совещание · " + cab, to["host"] or None, to["day"], int(to["minutes"]))
                    await c.execute("UPDATE fo_meet_occ SET task_id=$2 WHERE id=$1", oid, tid)
                except Exception as e:
                    await c.execute("UPDATE fo_meet SET log=log||$3::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                                    str(org_id), str(client_id), _fo_mt_item("задача ведущему не поставилась", why=str(e)[:200]))
        await c.execute("UPDATE fo_meet SET pend=NULL, attn=NULL, log=log||$3::jsonb, updated_at=now() "
                        "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id),
                        _fo_mt_item({"move": "перенос согласован", "cancel": "отмена согласована",
                                     "extra": "дополнительная согласована"}[kind],
                                    было=("%s %s" % (fr["day"].isoformat(), fr["time"])) if fr else None,
                                    стало=("%s %s" % (to["day"].isoformat(), to["time"])) if to else None))
    if kind == "cancel":
        cap = "⭐️⚪️ <b>Планёрка отменена</b>\n<b>%s</b>\n\n%s\n\nНужна будет встреча — напишите здесь." % (
            _fo_mt_h(cab), _fo_mt_cap_item(fr, names))
        sent, err = await _fo_mt_card(c, org_id, client_id, "cancel", cap, reply_to=msg_id, test=test)
        dm = await _fo_mt_notify(c, {0: {"host": fr["host"]}}, "✖ %s: планёрка %s %s отменена клиентом, задача снята." % (
            cab, _fo_mt_dd(fr["day"]), fr["time"]), test)
    else:
        note = ("Было: %s в %s" % (_fo_mt_dd(fr["day"]), fr["time"])) if fr and kind == "move" else ""
        sent, err = await _fo_mt_card(c, org_id, client_id, "agreed", _fo_mt_caption("agreed", cab, [to], names, note),
                                      reply_to=msg_id, test=test)
        dm = await _fo_mt_notify(c, {0: {"host": to["host"]}}, "✅ %s: %s — %s в %s (%d мин). Задача у вас в ганте." % (
            cab, "перенос" if kind == "move" else "дополнительная планёрка", _fo_mt_dd(to["day"]), to["time"], int(to["minutes"])), test)
    return {"state": "applied", "type": kind, "send": err or "отправлено", "проджекту": dm}


async def _fo_mt_pend_answer(c, org_id, client_id, r, pend, text, msg_id, pk, test):
    to = _fo_mt_unjs(pend.get("to")) if pend.get("to") else _fo_mt_unjs(pend.get("from"))
    offer = {to["day"].weekday(): {"time": to["time"], "minutes": int(to["minutes"]), "host": to["host"]}}
    js = await _fo_mt_parse(text, offer, org_id)
    kind = js.get("answer")
    await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), str(text or "")[:500],
                    _fo_mt_item("ответ клиента", text=str(text or "")[:300], понял=kind, by=js.get("by")))
    if kind == "yes":
        return await _fo_mt_pend_apply(c, org_id, client_id, pend, msg_id, test)
    if kind == "not_about":
        if pk and _fo_ai_ready() and not test:
            await c.execute("UPDATE fo_chat_msg SET ai_state=NULL, ai_note='не про планёрку — в разбор задач' WHERE id=$1", pk)
            _fo_aio.get_running_loop().create_task(_fo_ai_process(pk))
        return {"state": "не про планёрку — агенту задач"}
    if kind == "no" and pend.get("type") != "cancel":
        await c.execute("UPDATE fo_meet SET pend=NULL WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id))
        await _fo_mt_send(c, org_id, client_id, "Хорошо, оставляем как было.", reply_to=msg_id, test=test)
        return {"state": "оставили как было"}
    if kind == "no":
        await c.execute("UPDATE fo_meet SET pend=NULL WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id))
        await _fo_mt_send(c, org_id, client_id, "Хорошо, планёрку оставляем.", reply_to=msg_id, test=test)
        return {"state": "отмену не подтвердили"}
    if int(pend.get("rounds") or 0) >= _FO_MT_ROUNDS:
        await c.execute("UPDATE fo_meet SET pend=NULL WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id))
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "не договорились о переносе: «%s»" % str(text)[:120])
    # другое время / другой день — считаем заново (как новый запрос того же вида)
    r2 = await _fo_mt_row(c, org_id, client_id)
    res = await _fo_mt_request(c, org_id, client_id, r2, ("перенести " if pend.get("type") == "move" else "ещё одна планёрка ") + str(text),
                               msg_id, None, test)
    p2 = _fo_mt_load((await _fo_mt_row(c, org_id, client_id))["pend"], None)
    if p2:
        p2["rounds"] = int(pend.get("rounds") or 0) + 1
        if pend.get("from") and p2.get("type") == "move":
            p2["from"] = pend["from"]
        await c.execute("UPDATE fo_meet SET pend=$3::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                        str(org_id), str(client_id), _fo_json.dumps(p2))
    return res


# ── в понедельник в 10:00 бот сам начинает согласовывать неделю ──
async def _fo_mt_auto(c):
    now = _fo_mt_now()
    if now.weekday() != 0 or not _fo_mt_tok():
        return
    start = _fo_dt.datetime.combine(now.date(), _fo_dt.time(0, 0), tzinfo=_FO_MSK)
    for o in await c.fetch("SELECT DISTINCT org_id FROM fo_meet WHERE status<>'off'"):
        st = await _fo_mt_settings(c, o["org_id"])
        if not st.get("auto") or now.hour * 60 + now.minute < st.get("auto_at", 600):
            continue
        if await c.fetchval("SELECT 1 FROM fo_meet_camp WHERE org_id=$1 AND started_at >= $2 AND NOT test LIMIT 1", o["org_id"], start):
            continue
        if not await c.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", "fo-meet:" + str(o["org_id"])):
            continue
        try:
            if not await c.fetchval("SELECT 1 FROM fo_meet_camp WHERE org_id=$1 AND started_at >= $2 AND NOT test LIMIT 1", o["org_id"], start):
                await _fo_mt_camp_start(c, o["org_id"], None, True, st["gap"], False, None, auto=True)
        finally:
            await c.execute("SELECT pg_advisory_unlock(hashtext($1))", "fo-meet:" + str(o["org_id"]))


@router.post("/meet/{client_id}/week/reset")
async def fo_meet_week_reset(client_id: str, p: Principal = Depends(max_level(4))):
    """Вернуть неделю к графику: снять переносы, отмены и дополнительные с сегодняшнего дня, задачи — как по графику."""
    today = _fo_mt_now().date()
    async with pool().acquire() as c:
        if not await c.fetchval("SELECT 1 FROM client WHERE id=$1::uuid AND org_id=$2", client_id, p.org_id):
            raise HTTPException(404, "клиент не найден")
        n1 = 0
        for o in await c.fetch("UPDATE fo_meet_occ SET status='cancelled' WHERE org_id=$1::uuid AND client_id=$2::uuid "
                               "AND status='agreed' AND day >= $3 RETURNING task_id", str(p.org_id), client_id, today):
            n1 += 1
            if o["task_id"]:
                await c.execute("DELETE FROM task WHERE id=$1 AND status='planned'", o["task_id"])
        n2 = _fo_n(await c.execute("DELETE FROM fo_task_skip WHERE org_id=$1::uuid AND client_id=$2::uuid AND day >= $3",
                                   str(p.org_id), client_id, today))
        await c.execute("UPDATE fo_meet SET pend=NULL, log=log||$3::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                        str(p.org_id), client_id, _fo_mt_item("неделя возвращена к графику", переносов=n1, отмен=n2))
        r = await _fo_mt_row(c, p.org_id, client_id)
        applied = await _fo_mt_apply(c, p.org_id, client_id, _fo_mt_eff(r)) if r else ""
    return {"ok": True, "снято_переносов": n1, "возвращено_дней": n2, "задачи": applied}
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
p("== КАРТОЧКИ ПЛАНЁРОК ==")
_MEET_IMG = {
    "agreed": "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",
    "offer": "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",
    "remind": "/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAIwBQADASIAAhEBAxEB/8QAHQAAAwACAwEBAAAAAAAAAAAAAAECAwgEBgcFCf/EAG4QAAIBAwIEAwIHBgwPCQ0HBQABAgMEEQUGBxIhMRNBUQhhFCJVcYGk0hUXMpGToQkYQkVSVnR1srPR0xYjJzY3U2Jyc4KUorHBwiQzNURUkpWjwyUmKClDRmNmg4Sl4/A0ZbTE1OLxGTh2heH/xAAcAQEBAQEAAwEBAAAAAAAAAAAAAQIDBAUGBwj/xABFEQACAgEBBAYHBQYDBwUBAAAAAQIRAwQFEiExBhNBUWGRUnGBobHB0RYiMtLwFBUzQlNyNOHxIyQlNUNikgc2grLCov/aAAwDAQACEQMRAD8A1BTKTMSkZYKLhJueJLGI47n6wmBplJmNMpM2mDKpFJmOkoymlOXJH9ljOAUjaYMyY0zEpFKRuy2ZMjTJnyxm1GXPH9ljAslsGRSDmMeS3yqEWpZk+6x2LYHzBzEZDJbBfMLmFHlcJNyxJYwsdycksFZFknJVPllNKUuSPrjOCWBZFklyJcjNiynIhyFkKnLGTUZcy9cYMtkE2JsTYmzDYBslsc+VQi1LMn3WOxicjDYHKRDYNglFxk3LEljCx3MNgTZDY28Et4MtgTZDLgoymlKXJHzljODHk5tgTYmwZEmYYE2Sy6ijGTUZc8fXGDGzDAmSxhLlUYtSy33WOxhghkMbZLMMCZLLSi4ybliSxhY7mNs5siEzG+5TYoqMpJSlyL1xkwyEMllMhnNkEyGUxVFGMmoy5l64wYZSGSymSzDIRIhmSaSjFqWW+6x2MbObBLExsEk4yblhrssdzDBjZDKkSzAJZLLik5JSfKvXBjZhglkspks5shLJZdRKMmoy5l64wY2YYJZDKYpJKMWnl+ax2ObIQyWUyWYYFgMFJLlbbw12WO4jIFgYFQSckm+VeoBIAMoEAxyilLCfMvXAoEjAZaAgwU0lFNPL81jsLAoCAeBpLlbbw12XqUCAAADAYKik2svC9RACwAwAEBTST6PK9RACAY2lhdevp6AE4GAAAA0lh9cPyQACAYJJvq8L1AEAwAEAwaSfR5QAhYGAAgKx079RACAY8dH1AJAYACwGBruAAgDAACAbXX1AAWAHgMdCUBAACgIB4AlAQDBLr1AJDAwIBYFgoGuvqATgMDwGACcCwXjsLABOBYKwGACcCKwGACQGl9AACEMABANrDESgIBhggEIYACAeBACAYJfQAIQwAEAA+/qAIBiIBAPHQCFEIYEKIAAA9mTKUjGmUmfoqZsyqRSZhTKUjSYMyY0zEpFKRqwZExpmNMaZqwZFIamY0wTNWDKpj5zDkeRYMvOHOYshktgyc4c5jyLJLBfMLmJyLJLBWRZJyGSWB5FknmJcjNgtyIciXIlszYG2LIsiyZsA2LImyXIw2Bt4IbBsnJhsBkQZIbMNgGyGxtktmGAZLYZE2ZsCbIkxt4IbMMAyRtktmGZE2S2NshnNlE2SxslmGQTZDZTZDZhkEyWNslmGBMlspmORhgTJY2SzmwJkspkMwwSyWNkswwJshlMlmGQlksbJZhkEyJFMmRzYIZLKZJhglkspiMMCAYEoAGBgWgIYYAoAMAMAQDAAQwAAAGGABAMABDAAAwGAwPAAgGAAgGAAgGAAgGAAgwPAYAFgMDwGABAPAACAYACAYACAYACwA8BgAQhgAIBgAIB4AAQhgAIBgALADEAIBgAIBiJQAQwJQEAwAJDAwIBYFgoQAsCwVgWACcAVgWACcAPAAEgMABCGAAgADIEAxACAYACEMABAMQAgGIABDAgEIYEKhAAEKewKRkhCUoSmlmMMcz9MnHUilI/QbNmVMpMxKQ1I1YM9KEqs1CCzJ9kJSMaY0zVgyqY1Iw5HzYLYORUhKjNwmsSXkLmMCmNM0DNzr1KknGEZNYjLOGYE/eMtgyc6DnRjAWUzRi5QlJLMY4y89ieYxZ94uZohDNzDhGVWahFZk+yOPzj5iWC3ITmRkWSWCnIdSEqU3GSw15GPIsmbBWRZJ5ieYlgySjKMIyawpdnkhvBLkTkzYKbBQlKMpJfFjjL9CMiyYsDyS2JywS5GbBcIyqTUYrMn5GNsWRZwYsAyQE2ZsFVISpycZLEl5GNvAN4IbMNgGwlCUYxk10l2ZLYmzDZkGyWwbJbMMIfLKUJSSyo4yzG2DZLMMAwjB1JKMVlvyE2Q2YIDZDG2SzLAmFSDpycZLDQMlmGwSyGym8kM5sDlBqMZNdJdmQxslswwJi5ZSjKSWVHuwbIZhgTJbGyWYYCMXOSjFZb8jGymQ2YbMiZLGxM5soVIOnJxksNeRiZTZDMMgmKUWoxb7PswYmYYJYABANQbi5JdF3FgBgCKhBzkoxWWxAAAAMARUouEsNYaEAABgB4ABwaim10fYQwAEUotpvHRdxAAADAAIxc2kl1FgYACAYAA4uLw+jAMBgtABuLST8n2DACgIBgKAKLab8kIYYLQENJyeF3DAYFAQDwGCUBDcXF4fcMAKAgGBaAsNLPqAwJQEGG1kMAKAgGBAJLLAYACAYACawxDDAAgwMABYAYgAwIYACBLLGIAQDAAQNYYxACAYACxgBiJQEGOgwIBCGBAJLPQWChACwIrAgBNYFgeAwASGOg8CAEAxABgQwJQECWXgAIBCGAAgawxiAEAxABjGBDAAQYAABAAEB6wmNMxKRSkfdJnUyqQ1IxpjTNJgyqQ1IxJhzYNWDLz4BPJiTyXFmkwZF0KRETnaVpV1rN7TtLKhK4uJ9oR/wBLfkvedYxc2opW2DjIeD02w4HXtWlGV3qVG2m+rhSpupj6cxOYuBP/AN9/VP8A957ZbL1lXue9fU8eWfFDmzyfAsHrX3if/vv6p/8AvJlwJfL8XW036O1x/tnN7P1MecfevqePLaGmjzn7n9DyZks7furhnq22KErmShd2cfwq1DPxP75Pqvzr3nT2sHgZISxvdkqZ5WLNjzx3scrRL6C5sA2QzjZ2MnMDkYlPHQOYxYMnMTzEZDJLBXMLJORZM2CsiyTzEuRmwXnBLkS2TkzYKbJyLOBZM2B5ELIm8GbA2yHITkTkzYG2S2GRZMNmQyS2DZLZiwDZLYNktmWwDJbHklsw2QTZLYNktmLANksBMy2BZJkxtkNnNsCbJbGJsw2BMlsbJbMMCbIY2SzIE2SxslmGQTZLY2SzmyCZLGyWYYJbJY2yWYAmS2NiMAQwAAAGAAAAwBAMAAwADAEAwAAAHgtAQDDBaAsBgeB4AEA8BgEFgMDGUpOB4GAILAYHgMAosBgeABBYDAwAEGBgAIMDAAWAwMABYDAwwALAYHgABYFgoACcBgoQAgHgMACwIrAsEKIB4AUBAMRKAgGBAIBiAEAwAEAxACAYACEMABAMQACGAAgGIlAQDAgEIYEAsCwMMAEiwUGACRFCAJAYACEMABAAGQIBiAEAxAAIYACEMABAAAHp6kZIVpQhOCeIyxlY74MKY0z7SzqZFIpSMSY1I1YM9KtKlNTi8SXZkuRjUhc3U0mDNF9DLFmCDMtNnRMHJlUlWm5TeZPuzYThptWltzb1CtKC+G3cI1a02uqT6xj7sJ/jya9U0bZQiqcIxSworCR9bsKEd+eV81Ve2/oeBq8vVxS7xoZz9E0DU9yXsbPSdPutTu2sqhZ0ZVZ49cRTePeejbb9mjfus6xp9teaBe6VZXFaMKt5VpxfgQbw5uHMm8d8dD3mr2hg0/8AFmo+tnzWTJPJ+BN+o8qGbF8QfYy1raui07vQtUq7pvJVlTlZ0bFUHGLTbnzOrLs0ljHmeSbg4Qb12razutU2xqVra01zTr+A504L1lKOUvpZ6HHtfSapb2HIn7n5Omen1mHU4X9+D+PvR06UI1IuMkpRaw01lNGvHEza1Pa+45wto8tncR8alH9jl4cfoa/E0bEnknHqCT0SWOrVZZ+bw/5Tw9XJTjx7DjsLWyW0I4k+E7v2Jv5HkMiI1ZUpqcXiS7MufQ7Two4X6rxj3vZ7W0W4s7XULqFScKl/OcKSUIuTy4xk+y9D0M2km32H6i2lxZ01y6lcxtU/0NziY/182p/ldz/+nPNdJ9ljdmsT4hxo6ho0XseU4al4leqvFcYzk/BxSfN0pv8AC5fL6PB/bMDTakuHH5fM0k38Dx7mHUrSqzcpPMn3Zi5hcx5FkL5hcx6LsDgRr/Ebh9uveGm3mm0NM23TdS7pXdWpGtNKDn/S1GEk+ifeSPN8mN9OTinxXzC4reXL6GSVWUoRi30jnC9CMk5FkWCsjVWUYSinhS7ojJ65wK9mPdPtB2mrXG3b/SLKGmTp06y1StVpuTmm1y8lOefwX3wYlNQi5S4JEbS5nkeRZNr/AP8ApscTfl3af+V3X/6c8S448Ctf4BbjsdF3DeabeXV3aq7hPTKtSpBQ5pRw3OEHnMX5Hjx1OGclGMrbNJN2zz2NWVKSlF4kvMxtk5DJ2bM2DYsiyJsy2QupUlUk5SeW/Mxtg2Q2ZsDbCVSUoxi38WPZENhkw2AyTkGyWzNkK8WUYyin0ljKMbYNktmGAbCE5U5KUXhrzES2ZbAMlsGyWzDYBsVSpKpJyk8t92Jslsw2AYmwbJbMAcpuUYxb6LsjG2NsjJkgMPEcYyin0ljPvE2S2YbKJslsGS2YZkcZuElKLw15kDZLMMCZLY2yGYYHObqScpPLZDGyWYYExuTcVFvouwgMgMAAwBqTUXFPo+4gAACoScJKUXhoQAAABgtACpSc5ZbyxBgtAAHgMAA5NxSb6LsGAGUgsDTaTXk+4YAAAGAARbi010aFgYYAEMAABtyeX3DADAFgbbaS8kAACAYAAm0mvJiGAAhpuLygDAAgGAAhtuTy+4AAIBgALyS9AwMABYDOFj1GLAACGAALKYsDDAAgGIAH1fUWBhgAWBFAASA8BghReQh4AUBAnhjESgIBgQCB9QAAQDEAGRDAAQZ6AAAgGIAF0YhgAIQwMgTeQGIgEAxACwIrAgBdkIYAEgujGIAQAAAgbyxiIBAMRAAhiAAOwAAIQwAPR1PBSmYUzJCcVCacMyeMSz+D9B9fZ1LUikzAmUpGrBlyJPqKlVjGac488fOOcExfVGkwciLM9NnEizk031R2gwcykbZo1NjOMptxjyRfaOc4Nsz6vZE92OT2fM+b2zk6tQ9vyN9/ZE21p+j8ILHUbelD4dqVSpVuayXxpcs5RjHPoku3vfqdB0T2s91a1xZsttvRdMsdOr6nGylGtTqyuYQdTleZc6XN/inl/Ar2lL/hFa1NJvLL7r6DUqOqqUanJVoSf4Tg30af7F+fmup79tr2q9g7y3VpdhR0DVI6pe3FOhSuLi0t8Qm2lFuSquSS9yPiNbo82LWZ82bB1sZ2075f6cvZwPBxa/Dk00MUM3VyXPhz/wBTtvtD8UdV4S7Jt9Y0i3s7m5qXkLdwvoTlDlcZNvEZRefirzOJ7O3GDU+Mm29SutY0uhZ1rSuqPiWsZKjWTjlpKTbyvPq+6Oy8XOIeg8NNtUdU3Dp9fUrKdxGhGlb0adWSm1Jp4nKKxhPrnzPFNwe27oNlpTo7X25eSuVHlpq/VOjRp+/lpyk383T5z5vT4ZajSPHjwXJv8V8uXD9d55ut1uLRauOTPqdyKXGFXfPj+u48B9oHbdhtPi9uLTtNpxo2Ua0asKUPwafPCM3Fe5OT6GsXHrtof/t/+zPadf1293RrV7q2pVncX13VlWrVH0zJvyXkvceLceukdD/9v/2Z9zicoYoY5u2kk/Wkfm+x9XDU9IYzxKoylNpeG7Jnj1R4PefYUf8A4Sm3/wBz3f8AETPBKrPefYTf/hK7e8/9z3f8RM8XO/8AZz/tl8Gfs+X8Hl8T2ri37FHEDcW8N17os962NtYXV1cX9K2lWuFOEG3NRwo4zjp06HVPY0qzrcDuO86k5VKktOzKUnlt/B7jq2a8+0LL+rnv39+rv+NkbA+xa/6hHHX97P8A8vcHoJRmtnzcpWt2NcOXFdvaeXPhninz3jo3so3HDOxWuXW69r6lvjdcIr7laDa6dO8p1o4WcRjlOTb7zWEl0y3g9+35wb2zxY4H7q3FccJXwm3Jo1tUu7NU6cKKrRhBz6xpxgmmouLUoJptNM697G9xc6l7PO7dI4c6lpmk8UpXniSq30YucqPxORpNS+Ly86TaaUm8rrk9Q0Gw3FofBjitYb137R3fvCWj1ri6srW6dalptJ0KihBdEoyk1Jv4q7Lukm+etyNTm06cari/Dklwrvs5YOM432yp/Dj8jqPsy8WNKvfZn33eR2LoVvT25YRp3dtSoQUNXcKDblcLl+M5Yw857s8b4T7R0T2w+OVGU9raZsfbmlacqt9p236caMbjlqdF8WMcSk5pOWM8sfXGOwexDX0zd3C7inw8nqtrpuua7b8tnG6moqfNSnDKXeWJNZSy8MfA2jP2K+P8tu8QNU0xWuv6VGMtQ0+rUnRtm6j8NzlOEHHrCSbxhcyecZx3mlDU5XH8TScfF7rv3nNOsFR7G79Vr9d57HZ7A0DX92S2bd+zTR0vZ9SpK0hueMqMbmMVlRrPliqiTaXXxG1nLz1R5DwL4EaJs72ydw7G1rTrPcej2dhWrW1PVbanXjKElSnTk4yTjzJSxnHdPseiQ9n3fVHc1bXdV9oHVaHDJOpcq/tdy3MLiVJ9YR5pSdKKWUufmecfg9ennfsk6taax7Y+u19P3Dq26tPjptzSttW1us6t1cU4uklKUn1a6dO3THRdl4+Fv71Sv7kr5865u+TN5eEXXK1Xn2ew6N7THEHhdZWGo8O9i7BtLG40u/UKm55Rp/CKs6bkqkE+VzcG/PnS6dIpYNauY7JxOf8AVJ3X++11/HSOtKcVCSccyeMPPY9hpko4ovm3Tfro65eE3Fcl9Tcbio//ABevDb981/CuTiex37Oui7q2VrXEfceh1t2wsKk6Gmbdo4xdVYRTbllpS6yUUn8Xu3nocjio8foenDb981/CuTmeyBxL0rcnBrcPCWvuypsbclzXncaRq1K4dvJynyvlhNSi+ZSj1jlOUZPHZniyc1HU7nPffr7L9x46/Bhvl2+b5+09IXA3S+PW1tf0zWuCNHhFrNpburpWp2E6PJVqdcRn4UIJ9cZUk8ptppo8C9lyrw00LRtfq7g2RqfETf8ARrOnaaDR0yV5S8JNLMUlKCecuUprokuVPrn1nUuE+6eEGzNe13izx93JbzhTf3KtNB3FcudzPHRONXDm28Llikl1bljtl9mOtrG4vZXvdN4T6zpmk8SFqM6uqVb7ldacXN4k3KMu8HFKTTXSS6PqeNGe7DI4u1w5Xwt87d+3/M3LioqXf8vh3eJHGngrtrfvs969vf7174U7q0aHjxs6cYU4VqacW04wUYtNN9XCMk4+nf5WxNK4YbM9jfa+/d3bF0/cd/b3lRQjChTpVrys69WEI1auMygo5eJcy+Kujwj0TWLTV9G9lfirpe6d+U987vo2k6upSt7h1qNi5xShQi8JLpByawur7dm/G93P/wAW5tT99/8A8xXOe9LclBPhvQ5X23dXx/Vmore3N7/u9y4HoOr2XAndXBOz43VuG1KypabOVGWgae4W9G4r+IqcadVQShKKk1Lm5V07p/gnT+KugcN+OXsq6hxL2nsuy2RrGhXSpVbexo06cZfHhGcJOnGKqLlqRkpOKeVj1z8ywlGX6GzqjjHkj92l0zn/AIzTDhS//F4cSv3zf8K2NTjuLI0392Sri+F7r+ZnG3eO/wCZtP1K18jTdslsTkEpxcIpRxJd3nue2syfcvtlavp22LPcFe2UNLu58lKr4kW2+uMxzlZ5X+L5ji7X+5P3fsnrjrLSlPNdW6zNr07ro3jOOuM4OJW1a9r2FGxqXlxUsqMnKnbSqydODfdxjnCfzHcuB1zpdrxEsJ6s6MaXLJUZ18ckauPivr0z3x78GLatmZcInp+jx0jdGtU9Jp8LZW+36z5I6rO1dGpy+U+blTx80s+fuOvcN9l6XpvGHcOi3dnQ1Kys6FV0qd5SjVWOaDi8STWUnjJ2vTdJ3na7zo3u69zU7PS43a8G3pXXKrluXxIRpxxlNtZz16fScLab/wDCE3f+5Z/9keApcHT/AJX+vWblyrxXxOiazxc0C/028tKPD7R7OrWpSpQuKcafNTbWOZYpLqu/c7JtTYtrtXYena69qz3hrWpLnhbThz0qFNrKbjhrtjus9emMHhVWX9Ml8579t/U7niTw90TTdA3HLRdw6VHwalp8Knb/AAiCSSeYdWsJPOHh5XTOTpNbsLj4eRJfip8uPmfN3tsi23FsG93CtrS2hq+nSTq2sYclKvT6ZcVhLpnyXljr0Pk7s2c73hPsu60fQ3Xvqqm7mtZWnNUmvLnlFZf0mff+i6js/Z1WhuDfOo3+vXM1GOl0L6dWi6fn4il1x36vC8sPufU13fGt7J4PbHq6Le/AqleE4VH4UKnMl1X4cXj6Di393g+1Gldr1M+Fp20Vp3A7cd3qmifBtThdwVGvd2nJWjDNNfFlJcyXV9vefd4Q7p0PemuW2hXWytDgqdq5SuvgsJTm4JLLzHuzG946vvTgJua71m7+GXFO7p0oz8KFPEeam8Yiku7Z1v2cpRlxMi4x5V8Eq4Wc+SNcW5736+6Ylwgmu/5nH17cNnxC1az21p219I0KvVv40leWdCMZ4y49cRXTrnHuOz7i3Lsfhdqz23T2bba67aMI3V9eODqOTSbxzQl1w/JxWenvPLNJ13+hnftDVXB1I2l/4soLvKKn1X4snq+8eED4nbgqbm21rOnVdMv1GpWdapJSoywlLok/TOHhp9DmuEY3yfP3Gpfja8vM6hqu5NnbT3hU1DbumWm4NLurZKVjqNBuFtUbTfLzp57e/u+uDvW4916BofD7b+4obF0CrW1OcoyoStKajDGez5OvY8j4k6FoG2tdWn6DqVTVKdKC8evJxcfE81Fx6PH5u2eh3DiA/wCoTsT/AAtT/aMyrq013r5kX46fc/gc7hVU0zW7ff2uVtuaXcSt6Kuraxq2salKk8VHyRTXRdF2wcrS1pfEfYu6K2obQ03blXTaHjW9/ZW3gJzw3yt4Wey6Zf4XZGH2cVqEtG3otKko6m7an8Gk8YVTFTl/C6d8d+h3LSaO7Keia6uJ9exraBO1aiqroxkqieVy+Gl19PPKWDnl4WvBCDt34/Q842Zt7b2y+HkN67i01a5Xu6zoWOn1GlT6NrMspr9TLunhJdD6NGz2txp23rM9L2/R2xuDTKPwinC0a8OtBJ9GoxiurWO2VldX1RG1IWHFThTb7QhqNvp+vabcOrawupcsa8W5P/RJp4Tawuhz9E0CjwD25r97rep2dfXL+3dtaWNrUcnh+byk+7TbxhJd8vBnI/xX7Pl/mSH8te3z+h4AS2VGSUk5R5l6ZwY2zoQGyWwZLMAGSVOSlJuMeVemckmAAwKbTjFJYa7vPcAkBgAAFJpRaay/J57CLQEMCoNKSclzL0zgoJDA0hlAsAMcsOWUuVegIIMDDAAhjbXKklhru/UQAYDAYKTWHldfJ57AEgMAAAqLSabWV6ZFgAQDwAAgKeG+iwvQQABgMDeMLph+bAFgMDwBaAgGsYfTr5P0AUBAMawn1WV6CgSAwFAQDB4b6LC9BQFgMDDBKAsAPphdBYFAQDH5PoASAwwAIBrv6iAEANhkUADAm230DDLRRiDDFgUQYC5Q5WSgMWAx7hYADACwwS92QUYgwLHuJQGAsA117EoAAsP0DAoDEGOi6CwKAwJwGOnYUBgLDFgUBgJLHkLBAUIWAwAMBNde2BYZKAwFhhnsKAALLDmJQAATWOwACwIoS7kBIihACAAff0AEAxEAgGIgEAwAEIYAHoCYJmJSGpn1VnUypjTMakNM1YLyEZE5JUuppMHKhLocilI4UJGenLsdYsH0aMuxtdo+oQ1bSrS8ptShXpRqLHvXY1Lozwz0rhpxLW24rTtQcp6bKWYVIrLot9+nmn6Hu9HqFibT5M+c23pMupwKWFXKPZ3rwPdi6Fepa1oVqNSdGrBqUakJOMotdmmux83Tde07V4RlZX1C5T8qdROS+dd19J9A8zJmTPxzVZpY24zVPxPoahuLVtWoqjfaneXlJPmVO4uJ1Ip+uGz54E1KsKMHOpONOC7yk8JHqJ5FHgj5zUaqU3xdso8Y476jCrqmm2cZZnQpSqSS8udrC/zf9B3fdPFDSNvW1RULinqF7j4lGhLmin/dSXRfN3Nf9Y1a41i/r3t3UdW4rS5pyf5l8y7HjRbb3mfe9DdjaqWsW0c8XGEU92+Dbargu5Jvj38u0+fVkcWcupkqTONKRicj9sCUiFImUhRZ47ZDJkWSciyZsF5FknIuYWC+YWSeYXMZsF5FkjmJ5iWORk5ieYnIsksllZFknIsmbBWRZJciXIzZCnInImyWzNlKbE2TkTZmyDyLImxORlsDyS5EuQsmWwNsnIZJyYbA2xNibJbM2BtktibE2ZsgNktg2S2YbKDZLYNktmLMg2LINiyZbAmxNg2S2YbANktg2S2YAMljYjLAAAyAQwAAAGBoAGB4AoBIYACAAwAAAAAAGAAAMMACGAABgBgWgIMDDAoBgAGUCAYACAYACGGAwAADwAAgwMABAMABAMMACEPAYAEAwAEAwAEAxN4AE+hPceMjSFAnlGolqJagaoGLlHymZQHye4u6DByByHIUPcHhv0LulOPyByHI5H6B4b9Bug43IHIcjkfoHI/QboOPyC5Dk8j9A5H6DdBxuQOQ5HI/QOR+hN0HH5BchyOR+gcj9BusHH5BchyPDfoHI/Qm6Dj8guT3nJ5H6C5H6DdBx+T3i5PecnkfoHJ7hug43J7w5DkcnuDk9w3QcbkFye85PJ7g5PcTdBxuX3i5TlcvuFy+4brBxuUXKcrl9wuT3E3WDjcouU5XIvQnw0TdBxnElxOS6ZDp4M0DA44F2MriQ0ZBKYxYwCZloAIYEBIihACAAAEAAQCAYiAQDEAd3TLiounNufLJYxHHcwqQ8n0lnQycw1Ixphk1YM9JxlNKc+SPnLGcE8xjyJs0mLORGXUy054ZxIzMiqnRSB9LmjCeIT54rtLGMnIp1T5UKxmhWa8zyYTKfZp1sLuZ/GioRanlvusdj40KxkVx7zy1kB9T4QvUiVwvU+f45Eq5p5AcydaLjJuWJLGFjucSpWXqYZ1jBKoeNKdgyTqoxRlCU0pz5Iv9VjODFKeTG5HiykQuUl6jUsI47kNSOTYM/OOo4xm1GXPHyljBx+Zj5zNizJzBzGNTDmRLJZmlyqEWpZk85jjsRkjIcxLBWRpRcJNyw1jCx3MfNgXMSwXnAnIjmFzEsGWnyymlKXJH1xnBj5iciySwU2LJOQyZshdRRjNqMuePrjBGRZJ5jNgrIS5VGLUsyfdY7EOROTLYKciWxZFkzYLSi4SblhrGFjuRkWRZM2B5CHLKSUpcsfXGSGyWzNgpslsWSWzNkHkKmFJqMuZeuMEtktmGwNslsTYmzNkKkkoxallvusdiMhknJiwGRrlcZNyw1jCx3JbIcjNgbZLYnIhsywZI8rklKXKvXBjciWwMgeQyIYoFTwpNRfMvXGBZEMUB5KfKoxallvusdiAAKQ0SNMpC0lytt4a7LHcQk2NNADHBJySk+VeuBAAADAABySUsJ5XrjAAAAAAA2kopp5fmsdhDAoAaSafXDXZeohlAhgAA4pNpN8q9RDAAQYGGAAkkn0eV6gAwBDwsLr1816AAAsBgYAAksPrh+ghgAIaSb6vCAMACAYACG0k+jyvUAAFgMDAAMLC6iGAAgx0YxACwS+rLfYlIoHFFRjkcUZYxwaSBKjg9h4ScEP6KbelrGuOdLS5PNG2g3GdderflH5ur93d+fbJ2+ty7q0vTZZVO4rxjUafXk7yx9CZulb0KdtQp0aUI06VOKhCEVhRSWEkfoXRXYuLXzlqdQrhHgl3vx8F3dtnWEb4s4Oj7a0nQaEaOnabbWcF/aaSi372+7fvZ9VEopH7JGEccVGCpeB5I0USijRARSJRSMFGikSikRgpFIlFIyBopEopGSDGhDRllGikSikRgpDQkNGQUikSikRkKQAgMhDRSJRSMso0UiUUiApFIlFIyCkMSGZZk419pdnqlGVG9tKF3SksShXpRnFr3po8N4tezFpur2dfU9p0YadqUE5ysIvFCv7oL9RL0S+L7l3PfBo9drNBp9djcM8U/HtXqYaT5n5o3FrO3q1KVWEqVWnJxlCaxKLTw015NHHlE9x9qnaNHQOIFLUbaCp0tWoePUiu3ixfLN/SuV/O2eKTgfhOu0ktHqJ4Jfyv/AE9x4rVOjitE46+hlkjHJHriAIcQMAQmsMYiAQihACx0QhgAIAAyBAAAHblIakY0y4U5ShOaXxYYy89sn0Fm7LUxqRhTDnwWy2ZubAnLKIpRlWmoQXNJ9lklSNJgvmwy4zMOcjUsGlIHJjMyQqHHnGVGbhNcsl3WRqZtTBzI1C1V95wlU95b5oQhN9Iyzh59Dopg5fjEuqcTxfeDqe8b4OQ6hDnkxx5pQlJLMY45nntkxufvMuVgyOZDkQ5jpQlWmoQWZPsjFksaQyeYOYxYHkMk8xVSMqU3GaxJeQsCyHMTkWSWCubAc7FKnKMIya+LLOGRnBLBk8QXOY+YqMJShKSXxY4y/QWCuZeocxiyGTNkMmQyRThKpJRisyfYhywSwZWyXIx8xPMZBlcick1IypzcZLEl5E8zM2C8hkx8w5RlGEZPpGXZmWwVkWTHzE83vIDI5CbJUZSjKS6qOMshyZkll5FkhyfqEFKpJRj1b8jLKVzEtkOQnNmWSysibIcmFRSpycZdGvIwQeRNkZ94mzIKciXPISjKMYya6S7e8hsywNslsO4KnKUZSS+LHGWZsEtiYwwZBOB4LhB1JKMVlsACeUfKMBQFyhylzg6cnGSw0IoFy+8OVlDcGoqTXR9gQjDAsACBlqm5Rckui7k8pQIabDlZUIOclFLLYAlIaaJwMUCgJHKLhLDWGi0CgJy/UeWAUAmpKKb7PsGWAMMCyNJtNpdF3KBgLLDIoDwMUcyaS6sOYUBgLLDmFAYA04vD6MWWKBQE5Y8NJPyfYUBhgWWGWKA8BgEm035LuLJaA8ALI45k8JdSUADAZQxQFgMDG4uLw+4BOAHgMACAeMJP1EQCAY8PDYBEgigfcqK6m0C4IzQjlkQjn6TkU4nWKB3vgjTUuJ2i5WUvGfX/AAMza9Gq3BGOOJejf+2/iZm1KP2vocq0E/73/wDWJ5OPkUj7uzdmatv3XaOkaNbq5vKicsSkoxhFd5Sb7JZPhI+ho+uahoFerX029r2NarSlRnUt5uEnB4zHK64eD7TOsjxtYWlLsvlfidHfYdj4lcL9V4V6xa6bq1ezuK9xQVxCVlOc4qPM44fNGLzmL8jt2j+y9vTVtKoXs3punVK8OejZXty4V6i7rEVFpP3Np+uDt3H2nCvxY4d06qU4TtLOMlLqmnXecnWPaV1G6p8c7mca9SM7SNt4DUv96xCMly+nxm387PjdNtDXa3Hp8eOajOcJSbcb/C0kkrXO+JhScuK7k/M8s1/QNQ2vrF1peqW07S/tpclWjPDaffuujWOqa6MNC0O+3Jq1tpmmW07u+uZ8lKjDvJ/T0S977HuftGWmi3HHDRo69XrWek19Pou8uLVZqpZqLK+LLr0S7MwezhaaRS48X0NGrVbvSqNrcOzr3McVJRzFKT6LDw35I8xbYl+7f2zc+91e/wAnu33X6+znRqcqVrw958PVfZe3ppmmVruD03UK1GHPVsbO6criCx1zFxSb9ybz5ZOk7E4d65xF1iWnaLaqrVpx561SrLkp0Y5xmT/1LL9x3r2fdTu6nHy0qyuKkql1UulXk5ZdTMJyfN69Un9B3TQEtM2Jxwq2n+56sb+pSUqfRqHPJYXuw3+M8HNtHW6Nz0+SUZTqDi6pLflu8VfGua4rxL/NueKXn/oeab44Cbn2Jo0tWuHY6lpsGo1bnTa7qRpNvHxk4xffplLB52j2/wBnupKvsXidZ1JOdq9KdTwm/i83JU649ei/EjxBHuNn6jPPJm02oalLG1xSq00nyt8UFxX68PqNFIlFI9wBjQhoyyjRSJRSIwUhoSGjIKRSJRSIyFIAQGQjmadpN9q05QsbK4vJQWZRt6UqjivfhMxStqtO4dCVKcaylyum4tST9Md8nq2iXljoXCvR6tfVr7R4Xl3XdX7lwXj15RliOZNrEYpdfXKM+iaTWsOJkb+vfy1lVdKnqNle3EfjSXhtQck/NYa+g9DLaTTyNx4R3q58XHhzqvp50s8svtE1HSoQne2F1Zxn+BKvRlBS+bK6nER6PtncOpbo2pvG31a8q6hSp2iuqauJc7hUUl1i32+ZdDg8LNp6fu641i2v8QlCz5qFZzaVKq5KMZPD6rL7M7/tjxQyS1C/A1dcedervFnSEUj0HZfDync6Xua91mi4ysLevSoUZScW68IuUpdGsqOF7vjGansGwvKO3bpxdlp33OV5qd1zN5+O0ksvpKWOVJfi6GZbRwRm43y7ezlft7vXwFnnSGeq3XDmzvtX3xp+lac6tzYq3+AUlWlmDk059XLr0z+Fk+HuPYtTa+wrW61KwlaavU1F0nKVTmzR8PKWE3Hun7zMNpYMjjFPi64cL4pSur5U/Mh0caENHszRrZ7Y9OLe0pY+M1drP5H+U1nnHDNnfbDjmO0n6fC/+xNZ60T8W6RL/iWX2f8A1R40/wARwpxwzC0cmouhga6nyckczEu5RLKObAhDBrHQyCRFCAJAeMYEAAhhjoQCEMCA7MpDUjCmDme7s0ZXMOYxcw0zVgy5GmY0xqWBZeRlTwGTHzDTNJkKy0NTZOQXU1ZTIp4DxCOVDwhvF4F+IHiEdA6F3hZXOCeRJjySwNDUvcSmGRZB8wcwsh0JZbDIZEIWQrIZJyLIsheRZJzgWTNgrIsk5FkgKyLJOQyZsDyIWQyLAxCyLJmwPqLAsiyQDYhNiyZslgxBkWTLZQJY2ycksgCBsTZixYmLANhkzZBMWBtiyZbAhA2S2ZFjJDIsmQDYs5AAAGCQ1EAQylEeC0CcByl49wJFBOAwXgMAE4DBeBYBCcDwVgMFKSBWAwQggHgMACwGB4AtAMBgYAC5Q5RjAJ5Q5ShgE8ocpQFBOAwWA4gnAcpQwCeUOUrAFBPKHKVgYBPKHKUABPKHKWGASyMBgvAYBSMBgvAYAIwIvAcoBIZHgWABp5GTgecAgAPuAKIMDFglAnzLgiPMyRNIhliuxyqa7HGj3RyqXdHkQKegcFF/VK0f/wBt/EzNpUal8M9Up6NvjR7qrJQpKvySk+yUk4Nv/nG2iP2bofKL0WSHapX5pfQ8nHyKRSJRSPumdT07jJxRsd/bi0HU9Fp3lpLTbKlQbuoRjLxITcuaPLKXTqv5Dt9xxp4fbuubHXd3bSvbnc9rCEZSs5x+DXDj+C5pzXT3NP06o8DRR6KWxtK8WPErW5aTUmnT5q12Mworl4V7Dv8Ar/Fd7s4n0t161pFDUbSnNJaTOeKbpRTUabk4vPfLeOrz0Rh2/wATp7T4lz3XoumUbChKtOS0uMv6XGlLvSTSXl2eO6XQ6MikeT+79ModVufd3dyrdbvdV17efiaa3rs98ocaeHu1r+83DtfaN7R3Rcxnyu8qR+DUJz/CcEpP8SS6dOiZ07hlxee0dQ1ulrlj929F11NajbtpTlJ5+PHyz8Z9OnzrB5qikeFHY2kjjnjknLepNuTbpcqd2qfFV2irPZdb4t7U0HZ2qaBsHQrzTvusuS9vdSmpVHTxhwjiUumG13WMvpl5XjyJRSPM0ujxaOMljtuTttttt8uLfgXkqGikSikeYQY0IaMso0UiUUiMFIaEhoyCkUiUUiMhSAEBkI7dt7e9rY6J9x9Z0Wnrmn06rr0IuvKjOjJ/hYlFPo/QyVOJV9/Rbba3QtqFCnbUla0bFLNKNBJrw/esN9fVnTkUjwXo8DlKTj+K74uuPPhyV9tcxR3PUd92K0a90/Q9Bp6JG/a+FVfhMq8pxTyoRylyrJ8vbe5nt601ijGg6stQtXbKaqcvhfGT5uzz27dPnPgopCOlwxg8dcG7dtttqu1u+xCj0C74t3eoV3UuLKMlLTKtg4QqcqdSolz138Xu8Lp7u587WOIF1qu2tG0SFH4NaWEV4nLPLryT6N9FhLL6de+fm6kikcYaHTQacYcuK9/1Yo7pqvET7p1d0z+5/hfdxUVjxs+B4bT/AGPxs49x8mpuTxNnUdB+D48O9lefCOfvmHLy8uPpzn6D4aGajpMONJRjyafb2Kl7kQY0IaPKNGuntfrMdp/+9/8AYms9ZdDYL2sdapXe5tI0ynJSnZW0qlRJ/gyqNdPnxBP6Ua/1ex+L7fkp7QyteHuSR40vxM4U10ONM5U/M40+58pLmczE+4xPuNdjiwAhgZBIihAEiKEAIAAAQABkH3ubBOTE59TJC4nCnOCfxZ45l64PbJmislRMSZSkWymVMOYVKtKjNTg8SXZk5NWQypjyY4seS2UyZKWSaleVao5zfNJ92JMtgvI8kpot1pShCD6xjnC9C2AGiMsM+8tkLWBoUasowlBPEZYyvmJyWwXgMIjJVOrKjNTg8SXZiwGMB1ROQUmSwPIZJ5iqlWVWblJ5k/MlgWfeLIhEso8hkJVZShGLeYxzhehOSWQYuwslRqyjCUU8RljKJYET1DIZJYDIZHCpKlNSi8SXmRklgeRCbFklgbYmx1KsqsnKTzJ+ZOSWBZFkeRyqSlGMW8xj2RmwTkWQYiWQGSUqkowlFPpLGV8xJmwJiYwhUdOalHo0ZshORZBiZAGSWxhUqSqScpPLfdmQTkTBgZBI+VluUpRjFvpHsg5RQJURpFYKjKSjKKfxZYyhQIwPBSiNIoJSKSLhJ05KUejQsFoE8rHylYHyigRyj5WZJuVSTlJ5bFyloEcrDDL5Sm5OMYvsuwBiwGC8BgUCMBgyJtRlFPCfdC5QCMBgvDHCThJSXRooMeB4KwGAQnAYKwVJucsvqwDHgMF8ocoBOAwZHlxSb6LsLlKCMD5S+Uayk15PuKJZjwPBePcGBQIwPBcW4tNdGGC0CMDwVgfKARgeC3mTy+4se4oJwGCse4rq0l5LsCGPAYLwGAUjlDBkWUmvJiwCEYDBeAXxXldGQEYDBWBYFAnAmiwbcnl9WSi2Y8CwZHEnBASNDecIWABiGh5eGgDG/wAIyRIa6lxKgZY+Ryab7HGg8djPSl0O8GU59J9UbFcKeKtvrdlQ0rVa0aOp0koU6tR4jcJdF1/Ze7z/ANGuFKRy6U8H0uytp5dmZesx8U+a7/12M3GTizdVFI1V0niPuPSaUadtq9wqcVhQqNVFFei5k8H1Y8Yd2P8AXb6tR+wfo8OlekklvQkn7H80dlkRssijWtcYN2fKv1aj9gpcYN1/K31el9g6fajRejLyX5hvo2SRSNa/vwbr+Vfq1L7A/vw7s+Vfq1L7BPtPo/Rl5L6l30bKIpGtP34d2fK31aj9gX35N2L9dvq1H7BPtNo/Rl5L6jfRsyikayffl3b8rfVqP2A+/Nu/5W+rUfsE+02j9GXkvqOsRs4ikaw/fn3f8rfVaP2A+/PvD5X+rUfsE+0uj9GXkvqTfRs+NGr/AN+jeHyv9Vo/YD79O8Plj6tR+wT7S6P0ZeS+pesRtCikauffp3j8sfVaP2A+/VvH5Y+q0fsE+0mj9GXkvqOsRtKho1Z+/XvJfrz9Vo/YD79m8l+vP1Wj9gz9pNJ6MvJfUdYjahFI1V+/bvNfrz9Vo/YH9+/ea/Xn6rR+wT7SaT0ZeS+pN9G1aA1U+/fvP5Z+q0fsB9/Defy19Vo/YJ9o9J6MvJfUb6NrEUjVH7+G9Plr6rR+wH38t6fLX1Wh9gj6R6T0ZeS+pesRteikanffz3r8tfVKH2A+/pvVfr19UofYJ9otJ6MvJfUdYjbNFI1K+/rvZfr19UofYD7+29/lv6pQ+wZ+0Wk9GXkvqN9G26Gaivjxvhfr39UofYJlx73yv18+qUPsGX0i0noy8l9Sb6NvTp3EbijpPDnTJ1LqrGvqM4/7nsYSXPN+Tf7GPvf0ZfQ1kv8Ajfve+pSp1NfrQi1jNGnTpS/HCKaOh39/XvripXuK1S4rVHzTqVZOUpP1bfVnrdZ0ljuOOmi773XD2cSPJ3GTcuvXe5dYvNUv6ni3d1UdSpLyz5JLySWEl6I+DWfQ5Faq+xwq0z81zTc25SdtnEwz7HHkZakuhhcuvQ9fIhjfcoko5MAIYPqZBIhgASIp+QgCQGGQCQGIgPp8xUWYkyoyPYWbMqY0zHkEypkMykNMxJlJmrKZVIaeTGmWng0mQyLoNMhPJ2Ox4dbs1K0o3VntjWbq1rRU6dehp9WcJxfZxko4a+Y6wjKbqCsp8BPAcx2X7129P2oa9/0ZW+yC4Xbz/ajrv/Rtb7J2WDN6D8mWjrafvGmdkXC/eS/80dd/6NrfZKXDDeX7UtdX/wDra32TXUZvQfkyUdaQI7L97HeX7U9d/wCja32Q+9jvH9qeuf8ARtb7Jeozeg/Jg60HY7L97LeC/wDNTXP+ja32Q+9nvD9qmt/9G1vsjqM3oPyYo61kWTsv3s94ftU1v/o6t9kX3tN3/tU1v/o6t9kfs+b0H5MUzreWgyfT1ja+s7ehSnqukX+mQqtqnK8tp0lNrulzJZPlHCUZQdSVMDygJF2MArOAyTzYDJkhWRCyLJAPoHQWRZRBYCHlCIAxkWB4FggFgMBj3iZAAsDEQCaE0PAmZIITXvHgRlkFgTQ8CwzJRYE0xtCw2QhLF1L5Q5CAjlY1EvlHygEcpSiVyj5UKBKQ0isAjSQEojUR4GaoCwcuw0m91WbhZWdxeTXeNClKbX4kd24L8OYcQ9zyp3blHS7OCrXKi8Op1xGCflnr19E/M290rSbLRLKnZ6fa0rO1prEaVGCjFfi8/efUbL2HPXw66ct2PZ2tngajVLC91K2aMX20tc0uk6l5o2oWlNLLnXtZwWPnaPldT9CMZz6HhvH3hFp1XQ7jcmk20LO8tfj3VKjHlhWg3hywuiku+fNZz5Hl67o7LT4nlwz3q4tNcThh16nJRmqs1p6l0qVSvUjTpwdScnhRist/QcrTNMratqNrY20ee4uasaNOPrKTSX52bocPeGekcPdMpUbShCrfuP8AT76cf6ZUl54flH0S/wBPU9Ps7ZmTaEnTqK5s8jVaqOmStW2afLZG5HR8Zbf1R0v7YrOpy/j5T49ajUtqsqdWnKlUj0lCaw186P0JOsb64c6PxA0upb6hbQVzytUb2EV4tKXk0/Ne59Ge8zdHKg3iyW/Fcz1cNrferJHgaN5DofQ1zRrjb+s3umXSSuLStKjPHZuLxle59zg8p8Y4OLafM+hTTVonCDlK5RcpmgLlDBXVBliik4Hyj+gfT0FEJ5Q5CsIML1JQJ5A5S8L1DHvFAnlDlZWB4LQJ5WHKysDwKBHKPBWB4ZaBGGGGXgMCgTysOVl4AUCeVhyl494Y95aBHKPlKGKIRysMMvAYFAjAsGTAYFAx8oYL5Q5SUDHgWDJgWBQIwLBbQmiAgGimhEIQ0LBbQmiF5kggwAIJjiNkruEUyxZlhLDMCZki8m06COXCeDk06hwITwZoVMHkxlRT6MKpmjWPmxqmRVveeVHIU+iq3vK8f3nzlWH4x0WUH0PG94ncHz3XDxi9YWzn+NnzDxfecFVSlUHWEs5nij8U4iqB4o6wzZy/EDxDi+I/cHiP3DrBZyfFDxTjeIxeIx1hN45XiC8Q43iMPEY6wu8cnxPcHiHG8Ri8T3k6wbyOT4oeKcbxH6i8R+o6xjeOT4oeKcbxH6i8R+o6xjeOT4geIcbxPeLxCdYxvHK8QXinG8T3h4nvHWDeOT4jE6jONzi8TA6wm8ch1DHKqjC6hDqGHkY3ipzbONVmXKZgnI4SmN4w1Hg4lRnKmsnHmjxJMWcWZgkjkzRhlE8ZlsxRbTLTySo4DscmilCBPIzJRCGIAQhiAEIYgAEMADlKRmhUjGnNOHNJ45ZZ/B9ehxovqWmeTZoyqQ+YwplKRuwcmjOMJpzjzx845xkSZijIqL6lsGZPBSZiTKTwbTKZ6k4ym3CPhx8o5zg/Q3gt/Yl2n+91H+CfnZk/RLgr/Yl2l+91H+CfZ9Gf4+T1fM3DmdzZDKZDP0hHQlkspks2gJkMpkM2gSyGUyWaBLJZTJZsGvPtgP8A7j7a/wAPW/gxNY6koym3GHJHyWc4Nm/bAf8A3H23/h638GJrDk/IukH/ADGfs+COUuYCH0Fg+cMFOScIJQxJZzLPcgYskAiouKhJOOZPGJZ7EgQCEMRAOnKMZpyjzx81nBIB9AACH9AjIHOUZSbjHlXpnJORi6EAsjlJOEUo4a7vPcQiABZH9AvoIQalFRknHMnjDz2IyPAiMgZHCSjJOUeaPpnAsBykoCArlDlJQJLm4yk3GPKvTORcvvHyigLAD5R8qLQBtcsUo4a7vPcRSiNL3GqBKRcccsk45b7PPYaiNRLQIUSlH3FqJSRaB7t7Kl/Ro3+4rKUkq9anRrQXm4wc1L8XPH8ZsUjRLbmv321dYttT06t4N3QlmLxlNecWvNNdGjYbbntN6LdW0I6zZXNhdJfGlbxVWk/euqkvmw/nP0LYm1dPi0602aW643V8mm7PTavTzlPfgrs9oR1TixqFHTeG+4aldxjGdnUoxz5ymuSP55I6ve+0htC1pOVGV7eTx0hSt+Xr88mjxPidxd1HiPVp0HRVhpVGXPTtYS5nKXbmm/N98dMLP0nsNobX0uPDKOOSlJqlR4eHSZZTTkqSPgcP9QoaXvzQbutilb0r2lKcpPpGPMk39Hc3iR+f57dw69o2rodhQ03cFrVv6FGKhTvKDTqqK7KSbSlj1yn08z5rYmvxaXexZnSfFM8zaGmnmqePi0bJopdjy9e0Zsx0ud3F2pf2t20s/wAn5zoW/wD2lJ6nYVrDbdrWs41YuE764aVRJ9+SKbw/e39CfVfUZtqaTFHe30/BcT0MNDqMkq3a9Z5lxXv6OqcR9wXFvJTou6lBSj2fLiLa+lM6nymTHvDlPzHLJ5Zym+135n2kIqEVFdhjSXK049fJ+guUycrDBzo2Y+UcElJOUeZemS+UOUlAxcocpl5WHKKIY+UcknLKXKvQvl9wcqFFMfKHKZOVD5RRCGlypJYa7vPcXKZOUOUUDHylJLDTjl+Tz2L5UHKWgY+UOUy8o+UAxRSTTayvQOVmXlDlFAx8ocpk5R8paBDim8pYXoLkMvKHKWiGPkHyrC6YfqZOUOUUDFyBymXlDl9woGNJJPp18n6CwZcC5SUDHgFhPqsr0LcRcooWRjInEvAsGaBjwEkm+iwvQtrJLRkENEtFtCaICX2RLRTEZIS0LyfTqU0SwgCExgQoReH1KTI7AmUGZSKU2jCmNSNJg5KqrPoUqpxucOY2plOUqnvG62EcXmJc8vua3wcpVfeUqvvOIpe8yRl7y75ls5canQ7xww4aXvEbUpxjUdrptu18IunHP+LH1k/zd/RPoMX7zdfhptqltPZOlWFOKjU8GNWu1+qqyScn+Pp8yR9RsDZ0dpah9b+CPF+Pcj1mt1LwY/u82ZNs8OtvbSoQp6fptFVIrrcVoqdaT9XJ9foWF7jsqSjhJYXoheZXmfsWPFjwxUMcUl4HyWSUpu5OwXcoldygzxmNDEhmGcWND8hIfkcmcWP0H6C9B+hyZwYx+Yh+ZzZykNdxoS7jRyZwkNDEhnNnKQ/IYvIZzZwYxiGcmcWNdyvMldyvM5s4sF3GhLuNHNnFlRIq0adeHLUhGpF/qZLKLiByZxZ5hxF9nra2+rOrO2s6Wiarhund2dNQi5f3cFhSXv7+8003ls7UdjbhutH1Sj4d1QfeOeSpF9pxeOsX6n6OLseCe1ztGhf7RsNwQgleWFdUJzXeVGeej+aXLj++kfKbY2djniefGqkufij7Po/tjNj1EdLmlvQlwV9j7PZ2UagyhgxNYOVOJhnE/P2frKZi7FZz2JawOJhmwEMRAD7ElCAJDyGIAQAABkjIrmMMWZIKLpzbnyyWOWOPwjpZotMqLMKkWmbsGVSLTwY6KjOpFTnyRfeWM4DJqwZ4stMwJmSLNpgyZP0T4Kf2JNpfvdR/gn52VFGNRqE+eK/VYwfonwU/sR7S/e6j/BPtui/+Iyer5nSB3NkMtkM/SUdDqG8+K+1eH95Qtdf1T4BXr0/Fpw+D1anNHOM5hFpdV5nXH7SvDj9sf1G5/mzxn2y3jeOgfuCX8YzX2J8Nr9vanSaqeGEY0u9Pu9Zzcmmb0fpk+HD/APOL6jc/zZL9pHh1+2L6jc/zZo7FRcJNyxJYxHHcnJ4P2n1nox8n+Ym+zeJ+0fw6/bD9Ruf5s7ntrdGmbx0elqmj3PwywqylGFXw5Qy4vD6SSfdeh+dWTdX2Zf7D+l/4av8Axsj3ux9s6jaGoeLLGKVXwvvXe33moybZ6myWNks+1NmvPtgPGj7b/dFb+DE1hybO+2C8aRtr/D1v4MTWOcYxm1GXNHyeMH5F0h/5jk9nwRxlzEbWcMOCuxtz7A0PVLzRPHu7i3Tq1PhdePNNNpvCmkuq8kapG53s4XXwjhFpEG8ujUr0/wDrZS/2jyejWLDn1cseaCkt2+KT7V3ljzMr9nfh9+1/67cfzhL9njh8v/N/67cfzh6SyGfpa2bof6EP/FfQ6Ujzd+zzw/8AkD67cfzhD9nrh/8AIH1y4/nD0hkM2tmaH+hD/wAV9C0u485/S97A+QPrlx/OCfs+bAX6wfXLj+cPRmSzS2Zof6EP/FfQlI84fs+7AX6w/XLj+cJfs/bB+Qfrlx/OHozIZpbM0P8AQh/4r6FpGhe87ChpO8NdsbWn4VrbX9ejSp5b5YRqNRWX1eEl3PjHYeInXiBuf99Lr+NkGwtlXu/tyW+k2fxOb49as1lUqaxzSf5kl5to/CZ4ZZdVLDijbcmkl6zgTs7Yus771D4JpNq6vLjxK8/i0qS9ZS8vm7vyRsDtb2ZdA0yjTqa3Xravdd5QhJ0qK9yS+M/nz9CPUdsbX0/Z+i0NL0yiqNtSXV/qpy85Sfm2fTZ+tbL6MaXSwUtSlOfjyXqXb637jrGKXM6la8K9n2UVGntzTpJdvFoKo/xyyYr3hPs6+g41Nu2EU/7TSVJ/jjhnb2Qz6n9h0rW71Ua/tX0OlI8R3d7MulXlCdXb93U0+57xoXMnUov3Z/Cj8/xvmPAdy7U1TaOpTsdVtJ2tddY83WM16xl2a+Y3pZ8Deuy9O31odXTtQp5T+NSrRXx6M/KUX/q8+x8ptXorptVB5NGtyfd/K/Z2ezyOcoJ8jXfgxwi0viHpepXep3F5QVCtGlT+CThFP4uZZ5oy9UeiP2YtrL/j+r/lqX82dj4N7MutjbZvNOvYr4Q76rPnj2nHEYxkvc1HJ3pnlbK6P6NaLH+1YE51xvnZYxVcTyD9LJtf/l+r/lqX82dc4i8C9u7N2bqOr295qVS4t4w8OFarTcXKU4x6pU0/P1NgDy72i7yNDYNOhKfJ8JvKdN9M9EpS/wBMUXaux9m6bQ5s0MKTUXXrrh7zMkka77H25T3XuvTtJrVZUKd1UcJVIJNx+K3/AKj2/wDSt6X8uXf5KJ5VwcjjiZoH+Gf8CRuGfMdGNlaPXaWeTU495qVdvKl3M4M8SXstaU/18u/yUQl7LelqLf3bu+39qie3IU/wH8x9Y+j2y/6K839Tk5M0HUfcPlMnKGD8Ko7Ecp6xwm4M2XEXQLrULnUa9nOjcugoUoRkmlCMs9f778x5a4rli08t91jsbL+zF/WRqX74y/iqZ9DsLS4tXrVizxuNPgcM0nGFo4P6VnS/ly7/ACUSl7LWl/Ll3+Sge3LyA/R3sLZy/wCkvN/U9bLPkXaascWeD1nw50eyvLbUK95K4r+C41YKKS5W89PmPLsGyftQf1qaR+7f+zka3YPzfbWmxabWSx4Y1Glw9h7DBJzhchdDtey+GOv77qr7m2fJa5xK8uMwox+nz+ZJs7rwX4MrdfJrWtQlHSIy/pNv1TuWu7b8oJ9Pf9BsxbW9Kzt6dChShRo04qMKdOKjGKXZJLsj2OzNhS1MVm1DqL5Ltf0R4mo1ixPdhxZ4/tz2ZdEsqUJ6xe3OpV/OFF+DS+bzk/nyvmO72XCDZthFKlt60kv/AEydV/57Z29DPs8ez9JgVQxryt+bPSZNRlm+MmddfDfak4KL23pWF6WdNP8AHg+Lq3ArZerxlnSVZ1H2qWlSVNr/ABc8v5jvqGu4yaXTzVSxp+xHiddli7jJ+Zrju/2Y76xpzuNvXy1CEVn4LdYhV+iS+K38/KeLXthc6bd1bW7oVLa4pS5Z0qsXGUX6NM34OicU+FNjxC06VWEY22tUYPwLpLHN6Qn6x/OvLzT+Y12xMbi56bg+7sfqPZabacoy3c/Fd5p5g+zsrSaGubv0bTrpSdtdXdKjUUJYfLKSTw/I4N/p9xpl7XtLqlKhc0JunUpzXWMk8NH3uGa/qh7b/fCh/DR8fiheWMZLtXxPocsqxylF9jNif0t2zP7Tef5S/wCQP0t2zP7Te/5S/wCQ9SBeR+hPQ6X+mvI/PHrtT/UfmeXfpbdl/wBpvf8AKX/Iav1NEr3m4q2madb1bms7idGjRppylLEml+ZG+Z0nhxwwsdjxurycYXGsXlSdStc4/AjKWVTh6Jefq/oS9Tq9mwyyhHFFRXG2jzdJtWeCM5ZZOT4Un7TzLZHsvKpSp3O572cJSWfgNm1mPulU6/iivpPVtK4Q7N0inGNHbtlUwsc1zT8d/PmeTt67jR5WPRYMKqMV7eLPTanaGp1Duc36lwR8OpsHbFaHLPbmkzj6OypfZOsa9wA2ZrlOXJpr0ys+1WxqODX+K8x/MeiryAuTBimqlFeR6+Or1GJ3DI17Wai8SOAms7Go1L+0n919JhlyrUoYqUV6zh16f3S6euDzDHuP0KlFTi4ySlFrDT7M1Y4/8KKW0L+Gt6VRVPSbyfLUoQXxber3wvSMuuF5NNeh83rdAsS6zFy7UfabI209TNafUfi7H3+D8TxxYNmNtezNtfWdu6Vf1r7Vo1rq0pV5xp1qSipSgpNLNN9Ms1qcVypp5fmsdjfDYv8AWRt797rf+KicdBihklLfVmukWrz6TFjeCTjbfI82XsqbS+UNa/L0v5of6VTaXyhrX5el/NHsq7DPavS4fRPgHtnaH9ZmkfF3ZVjsHedbSNPq3Fa2hRp1FK5lGU8yWX1ikvzHS8e5nqvtKL+qjc/uaj/BPLcHzuaKjkklys/XNnZJ5dHiyTdtxVk4R7Twe9n6G+NInq+u1ruxsKvS0hbOMalXr1m3KLxHyXTr37d/i8EeE1TiDrPwy+hKGhWc140u3jz7qkn/AKX5L3tG4VCjTtqNOjShGlSpxUIQgsRil0SS8keTp9OpffmuB8j0j27LS/7rpZVPtfd4ev4I8bXso7S+Uda/L0f5oa9lHaXyjrX5ej/NHs6Ov763vp2wNv1tU1CfSPxaNCL+PWqeUY/635LLPLlhxJW0fB49sbWzTWPFmk5PgkeCcU+DuxOGmgO5qajrFfUa6cbS0+EUc1Jfsn/SukV5v6O7PB8L0Z97ee7tQ3zuC41XUqviVqjxCEekKUPKEV5JfyvzPQeAfCGO+dTer6pTzodnPHhS/wCM1Vh8v96ujfr0Xrj1ckskqgj9Xw5JbH0Dz7Ryuclxfr7Ir9ePI+Pw24Ga7xDULvl+5ekN/wD2y4i81F/6OPeXz9F7zYDb/s3bK0WnF3FnW1auu9S8rPGfPEY4WPnTPT6VONKEYQioQilGMYrCSXZJFrseSsUYn5FtPpNtDXTe5N44dii683zfw8Dq9LhZs6lHlW19Jax+qs6cn+No+bqvAvY2r05Rqbft7eTWFO0cqLj7/itL8aO9ruPyI0u4+aW0dZjlvQzST/uf1NZOIHssXWnUal5tW6nqFKK5pWN00q3+JJJKXzNJ+9ngt1aVrK4qULijO3r05OM6VWLjKLXdNPsz9F0eT8c+DdDful1NU02jGnuG2hmLisfCoJfgS/uv2L+jt28aUF2H6BsLpjljkjptpO4vgp9q9fevHmu2zqOxvZi25uHZ+japf32rUru9tadxOFCrSjBcy5lhOm32a8z7n6UjZ7/XLW/y9H+aPXtBsPuVoenWWMfBranRx/exS/1HPRhpHxep6TbVeacseoko269V8DxL9KPs9/rlrf5ej/NHkHHzhTofC2totHSLm+uat5GrOr8MqQlyqPIo45YR75l39EbmmpPta6j8K4hWFqn8W20+GV6SlObf5uU5tH0nRTa+09obVhiz53KCUm0/VS97R4dgTWSmKSSfTqYaP3UxtEtGSSIaMAhiLa7dSGQgmSyhNdH1MgkAAMqATRXcRkE5wHMPAsAD5w5iXHD7i5S2C+clSJaaQJdELBli/eZYMwxRmhF9DVnNmemb/wAYqEVGKxFLCSNAqUOhv8fp3QzlqP8A4/8A6Pntpv8AB7fkHmZra3q3lzSoUYOpWqzUIQj3lJvCX4zD5ma2uatnc0bijN061KaqQmu8ZJ5T/Gfo8rrhzPQSO/b04G7j2Bta313WJWVKlWqxou1p1ZTrQlJNrmxHl/UvtJmbTeAu6NQ2TcbpmrOy06lbSu4wuKr8WrSUebmjGMWuqXTmaO27k1O71j2YNNvL65q3l3V1qUqlavNznJ5qd2zLwZ1vUNX4d8SIXt5Wuqdro0aNCFWbcaUFTqpRiuyXTyPiJa/Xx0k8rlHehk3Xw5reS4cfHts9lHBglmhCnUl39vHn5HhCPRdh8CNz8QdGnqtirSz0/r4de9quKqtPD5VGMn0a7tJHX9uWW1q+29craxf3ltrVKCem0KEc060sPKm+R46480eoey5reoXe7bjTq15WqWFrpdd0baU34dNupBtqPbLbfU9ltXV58Gly5NNwcObknTVXw7+6/Wev02LHkywjl4qTrg+POuJ53w74Y6pxKv761025srWVnS8arUvakoQ5c46OMZfnPp724L6nsXQ3ql3rOiXtJVI0/CsLqVSpl+eHBdOnqfS4K7x27taO7LbcVzc2tDU7N20JWtNzm18bmS6NJ9VhtY9Tla9w12lrnD6/3Rsq/wBSn9zZxV5Zamoc0YvCynFLr1z3a79sHhZtZqMWt3MjccVxSe5adr0r4ceBqGDFPE91XPjwunw8O3vPI/QfoL0H6H0LPRMY/MQ/M5s5SGu40Jdxo5M4SGhiQzmzlIfkMXkfa2ft2purcdlpsG4xqzzVmv1FNdZS/En9ODhknHHFzlyRzjFzkox5s+fc6fdWdKhUuLatQp1489KdWm4qpH1i2uq96Po0dm7guaNOtS0PUqtGpFThUhaVHGUWspppdU0dk35H+ie3vNw2taENKsrqGlWlsk+lOMMxkvc+r+k7HLWNG3ZeaVp1hubV9OvZ2lG1oxoxlC2jUjHCjLqm235pYPUT1eRQjJR774N129h5S0sHOUXLurilfmeQruV5n39raFTr76sNI1GkqkPhit69JSaziWJLKafl5HaaXDGk+Jn3Mk86Gv8Adnjczw7dvpHPfPN8T1ydcurxYm4yfZfs+p4MNLlypSiu2vb9Dzddxo9Iu9h2t7b7goaZZOV9R1xWNolUk+Sn8bo8vDSxlt5eF3PprYW3qe4tmWVGHw+2vVcQu63iTSuJU8rKw+i5k8Yx0x3PFlr8S7+33K/9PE1+78zfNdnve78efgeTRA9G03hdfadYbiu9b0qdGhb2FWpazlVXxaqa5X8WXXpnv0POTtjz48zaxu6PXZ9PkwJdYqspdjzT2kIKfBjcGUm4u3a93+6KZ6Wux5v7Razwa3Av3P8A/iKR42t/w2X+1/A3s7/HYP74/FGjE4nHmsHNqxwzi1Efk7P32LONJYJXcuaIfR98nJnZDAAMlEIb8hACEMXkAIAAAxxl0KUjDGXQakRMtmZMtSMKZSkaTKZ4y6lpnHiy4y6m7ByFIpPBhUi1I6JgyqR+jHBL+xFtH97aP8E/ORvofo1wS/sRbR/e2j/BPuOiz/3jJ6vmdIczurIZbMbP0tHQ1H9sx43joH7gl/GM17UjYL2z3jeWgfuCX8YzXlPqj8f2y/8AiGX1/JHGXMyplJmJSHzHprIZU0brezL/AGH9L/w1f+NkaSJm7Xsxf2HtL/w1f+NkfYdF/wDGy/tfxRqHM9TZLKZLP1Q6mu/thf8ABG2v8PW/gxNYMmz3thv/ALj7a/w9b+DE1fyfkHSL/mOT2fBHGXMrJt57LFfxeGE4/wBrv6sP82D/ANZqDk219k1t8Nr7Pb7qVcfkqR5HRh/8QS8H8ix5ntDJZTIZ+wI6nle7vaJ25s3cV7o19Y6rUurSSjOVClTcHmKksN1E+zXkfGftX7S+Tta/IUf508Z9oimqfF/XcdOZUJf9RTPNz8q1nSPX6fVZcUGqjJpcO5nNyaZtrp3tQbV1TULWzpWGsRq3FWNGDnRpKKcmks/03t1PXmaBbR/rr0X920P4yJv4z6zo7tPUbShklqGvutVSo1F2SyGUyGfYo2jRTiI/6oG5/wB9Lr+NkbEezTtKOj7LnrFSC+FapUck2usaUG4xX0vmf0o144hr+qBub987r+NkbnbN02Oj7S0WyiseBZ0ab97UFl/S8n5d0a0yy7TzZpL8F162/pZyiuJ9dkMpkM/VkdUYLq5pWdvUr16sKNGnFznUqSUYxS7tt9keSbg9pTb2m3M6On2t1qvL/wCWglTpt+5y6v58HWPaZ3lWqahabbt6soUKcFcXSi8c8n+BF+5JZx/dL0PCcH5vtvpLn02olptHS3eb58e5dnAxKbTpGzmh+0pt3Ua8aV/a3el83/lZxVSmvn5ev5j1Kx1C21Szp3VncU7q2qrmhVpSUoyXuaNEsHc+GfEi94f6zCanOrpdaSVza56Nfsorykvz9jxtmdLcyyLHrknF/wAy4NetcmvL2kU+83AZDMVlfUNSsqF3a1I1revCNSnUj2lFrKZkZ+sxakrXI7CPDvafvuW10CzT/DnWrSXphRS/hM9yNbvaVvfG3hp9qnlULJSfucpy/wBSR8p0pydXsvIvSaXvT+RxmdT4O/2S9B/wz/gSNwDUDg9n75eg/wCGf8CRt+em6H/4LJ/d8kcGNBP8CXzAuw0sn27OEjQxY9Bm6v3v9r/tb0j/ACGl9kr73+1/2t6R/kNL7J+VfZDOv+qvJleVLsNKTZf2Y/6ydR/fGX8XTO/rh/tf9rekf5BS+yfV0vRtP0ShKjp1jbWFGUueVO1oxpxcsJZail1wl19x7XZewMmztSs8ppqn7zx8uVSjSRzV3ABn17PXSPGvaeWdq6R+7f8As5Hi3DjZ8t7busdMeY28m6lxOPeNOPWX4+iXvaPa/acX/etpP7t/2JHyfZe0qLnrupSS5kqdvB+aTzKX+iJ+c67TLVbaWKXLhfqSs86E+r0zkj3i1tqVlb0rehTjSoUoqEKcFhRilhJGVdgQ12Punw4I9DImrVhQpTq1Jxp04JylOTwopd22a/b49o69qXlW12zSp0LWDwr2vDmnU98Yvol86b+Y9l3ztq43ftu60mhqD0z4TiNSuqXiNwzlxxzR74x37ZPJf0rX/rP/APD/AP5p83tT9vm1j0keHa7Sfq4s8nTfs8blmfHu4nQqPHPe9Kt4j1nxM94TtqXK/o5en0HrXDDj1S3TfUdK1ujTstQrNRo16OVSqy8otNtxk/Lrh+7pn4f6Vn/1n/8Ah/8A80ul7Ls6VSNSnulwnFqUZRsMNNdn/vp6LT4tr4JqTTku1OSfzPIzT0GSLVpPwT+h7yUYbWFWnbUYV6qrVowSqVIx5VOWOrSy8ZflkzH175Hy0jXf2ldlws7603JbU8Run8HusLp4iXxJfTFNf4q9TzPhov6oW2/3wofw0bTcWtFjr3DrW7dxzOnQdxD15qfx+nz8rX0mrfDVf1Qtt/vhQ/ho+F2jgWLXRlHlJp+2+J9Roczy6OUXzja9lcDdYPMENdz69nw8hg5KMeZtJLq2/IDWvjvxauNV1G525pNw6em0G6d3UpvDrzX4Uc/sV297z5YPXarUw00N+XsR20mknrcnVw4d77j0bdntC7Z23XqW1q6us3MHiStMeEn/AH76P/FydbsvaqsKlwo3e37ihQ5utSjcxqSS9eVxj+LJrpyhynyk9p6iUrTpeo+xhsPRqNSTb77fyN6dqbw0nemmq+0i7jc0U+WccYnTl6Si+qf/ANI+yaWcLd63Gxt32d5Gs4WVWcaN3T/UypN9Xj1XdfN72bqHu9Jqv2mFvmuZ8TtbZ/7BlSi7i+X0Gj4+8NtUN37Y1HSK6SjdUnGMmvwJ94y+iST+g+whrseTNKSaZ6FTljkpxdNcT8/Li2qWlxVoVYuFWlJwnF+TTw0b1bF/rJ2/+91v/FRNROL2nLTOJm4qMVhSunW6f3aU/wDaNu9jf1k7f/e+3/i4nz+hjuZJx7j7TpJk67S4Mi7ePmkfdQxDPas/OJGo/tJf2ULn9zUf4J1bhzw/vuIm4qWnWqdOhHE7m5xmNGn5v532S837s473xy0G93NxmWmafRde7uKNGEIrt+D1bfkkurfoj3/hxsCy4d7cpadbYq3EsTubnGHWqevzLsl5L35PQrA8uaTfKz9Lz7XjszZWGMP4koqvDhzfy72fa29oFjtfR7XS9OoqhaW8OWEV3fq2/Nt9W/U+kJDPZPgqR+TZJSnJyk7bPnbh3DYbV0a51TUq6oWlvHmlJ92/KKXm2+iRphxJ4iX3EfcE766zStaeYWtqnmNGH+uT7t/6kseg+1Bf65Lc9pZXb5NEVNVbONPPLOXabl6yT6e5NerPFMI9TqMjlLd7D9Z6MbJxafBHWyalOa4eC7vX3+XfdW1tO7uKVCjBzq1ZqEIru5N4SN89mbYobO2xpuj26XLa0VGUksc8+8pfTJt/Sae8GtMjqvFDbtCSTUblVsP/ANHF1P8AZN3F3JgjwbPQ9N9VLfw6VPhW8/bwXwfmNDXkJDOzPyqR8nc+7tJ2ZpktQ1i8hZ26fLFyy5Tl+xjFdW/mPIr32stGpXLja6HfXFFPHiVKkKba9cdf9J4pxa3tX31vW/vHVlOxo1JULOGfixpReE0vWWOZ/P7jpp4cpu+B+xbL6G6RaeOTXXKcldXSXhw433m5GzfaE2nu64p2s69TSb2b5Y0r5KMZP0U03H8eD0xH514ye/ezrxhr29/Q2prVxKrbVnyWFerLMqc/Kk3+xfl6Pp2axmz0W3+h0dNhlqtA21Hi4vjw70/Dufn2GzC7jQvMa7HNn5FIpdzSL2htR+6XF3XWnmFF0qEfdy04p/nyburufn7xC1D7rb73DeZzGtf15R/ved4/Ng5M/Tf/AE+w72uzZvRhXm19DrbRLLZD6GWfvAmQy2Q+5hglkspksyQRLGJmWCWCBgh2AAADJoQAAAgAABS7BEJdgXkQhkgciHc48DkU+5tHKRyqS7G/JoPS8jeTbGr09f27puo0pc0LmhCp8za6r508r6D9M6GTSlnh2vdflf1R8/tJOov1n1PMrzJ8yvM/S2egkeiXfETTbjgnY7PjRulqdDUHdSquEfBcG59E+bOfjL9SHDTiHp2zdr7z029oXVWvrNl8Ht5W8IuMZcs1mbck0vjrsn5nna7lHqJbPwSxTxNOpS3nx7bT+KNLPOMozXOPBe/6nZtu7o0zR9t63p13t+31O8v4KNvqFWaU7NpPLinF5zn1XY+5wU4g6dw33Rd6lqdG6r0KtlUtoxtIRlLmlKLTfNKKx8V+Z58hlz6PDnx5Mc7qfPi/Vw7uXYePHNPG4yj/AC8V52d54a740fat3qNHXdAoa3peoU/CqZhHx6S69acn1Xfqk15PPQ+/unint2z2ZebX2RotzplhfzU7y6v6ilWqYx8VJSlhdF1z2z065PKEPyPFy7OwZc3XSu+Dq3Ta5NrlaJHVZIRcY128aVq+dPxH6D9Beg/Q85nrWMfmIfmc2cpDXcaEu40cmcJDQxIZzZykPyPo6Hr+obbvfhmm3LtbnlcPEjFPo+66p+h87yGcZxU04yVo5KTi7i6Z3i/4ta3q21bnSL2tO4q3FVSldNxX9Kxh0+VR831zkzWnEy0oVLe+qbbtKuu29KNOlfqrKME4rEZypJYcl65R0IZ696LTpbqjS8LXw7PDkdHq8925W/Hj8fjzPr6HuCppO5rXWa0Hd1aVwricXLldSWcvrh4z8x2OPFO7jp1Ky+CxdOGoK8c/E+M6SqeIqOcdubrn8x0ZdyvMZNPiyNSnG6+R4sdRlxJqEqv5nd1xRuaNluOjaWvwarrF1K4dbxcyoxlnMV0WXh45unzGPSOIf3LrbXqfc/xfuJGsseNjxvEbf7H4uM+86Yu40cHpMNNbvP191fAy9ZntPe5ervv4n3tA3P8AcSOtL4N433StKlr/AL5y+HzNPm7POMduh8MIgdFCMW5LmzwJzlKKi3wRS7HnHtFf2G9wf+7/AP4ikejrseQ+1FrdLTuGcrGUl42oXNOnCC7uMXzt/MuWP40eBr5KOlyN9z+B5ezIOeuwpekn5OzTassHEqHMr9ziVD8qkfu8DjTRhM0zCcmeQigARg0AhiAEIYgBAAAHEXYyRpTnTnNLMYY5nntnsY12Gc0aZUWVFkRKj3KQz0Kc61RQgsyfZCi+pC7lG0UyKWDIpGEtdjaYOTUhKlNwmuWS7rJ+jXBF54Q7Q/e2j/BPzgiz9HuCH9iDaH720f4J910Uf+8ZP7fmdIHdWQy2Qz9PR0NQvbReN56B+4JfxjNeFI2E9tR43pt/9wS/jGa8RZ+N7af/ABDL6/kjjLmciEZSpykl8WGMvPbIkzEikz01mS1I3c9mF/1HdK/w1x/GyNIUbu+zB/Yc0r/DXH8bI+x6Lf46X9r+KNx5nqrJZTJZ+rI6muntivGj7Z/dFb+DA1gqQlSm4yWJLyNnvbG/4H2z+6K38GJrpHaWty0m31SGlXlTTq/N4d1ToylTfLJxfxksLqn0fofkPSCEp7SybqukvgjlLmfKybjey7YytOFVGq44V1eVqyfqk1D/AGGatbX4fbg3fqVGy03S7mrKckpVZU5RpU1+ylLGEl//AB1N6dobaobP2vpujW8uelZ0Y0+fGOeXeUvpbb+k9r0V0mR6iWpkqilXtdfIsV2n1mQy2Qz9SR1NKfaFq+Nxf19+UXQivooUzzuNOUoSkl8WOMv0O2cW9SWq8TNyXCfNH4bUpJ+qg+RfwTqR/P8Ar5rJrM012yl8WeO+Z9baP9dei/u2h/GRN/GaB7R/rr0X920P4yJv4z9C6Hfws3rXwZ0gQyGWyGfoyOiNFuIa/wC//c3753P8bI3d0+SnYW0o/gulFr5sI0j4h9N/7m/fS5/jZG3/AA11iOvbB0G9UuZztIQm/wC7guSf+dFn5z0WyJazVY+18fJv6nOPadjZDLZDP0tHRGo/tA0alPilqcp55alOjKGfTwor/SmeeOnJRjJrEZdmbPceeGFxu+zoavpVN1tTs4OnOhFda1LLfxfWSbeF55fng1hnCVOcozi4yi8OLWGmfhe39Hl0mvySmuE25J998fccJKmTgOUqKcmkllvske1cJuB11e3VvrG4qDt7Om1Uo2NRYnVfdOa8o+59X7l39doNn59o5lhwRvvfYvFkUbPUODmm3ulcOtJo38pOrKMqsISWHTpyk5Rj+J592ceR3JlPoiWf0LpcC02CGBO1FJeSPJXBAau8f7er98mtn4yqW9KUF7sY/wBKZtCjXn2mLLw9xaRd4/320dLPryzb/wBs+V6W43PZrl6Mk/l8zlM6Xwe/slaD/hn/AAJG3xqFwfX9UrQf8M/4Ejb09b0P/wAHk/u+SPHY12KXcQN4Tfofbs4SKKPBP00n/qz9f/8AlD/TS/8Aqx9f/wDlHy76Q7Mf/V//AJl9Dm8cu4968hryPBf00v8A6sfX/wD5R6Zwx4gffG0W51D4B9z/AAbh0PD8bxc4jGWc8sf2XbHkddPtbRazJ1WCdy9TXxR488coq2juA13ENdz2TPDkeOe05/WtpP7t/wBiRHswzX9D2sw/VK6i38zh/wD8ZftOf1raT+7f9iR1f2aNejZ7j1HSqksK9oqpTT85089Pn5ZN/wCKfB5cix7eW92qvNHl7u9pXX64mxyKRKKPsGekkNDPl7l0V7h0K80+NzVsqleGIXFGTjOnLummmn3S6ea6Gpu6Ku7tn6tW0/UtT1KlVg3yz+FVOSpHylF56r/6fU9FtDXvQ03BtPt8Trg037RaUqZuQCNIVu7XflrUP8qqfyj/AKLtd+WtR/yqp/KekfSCD/6b8zyXsmb/AJ/cbvoZo+t3a78taj/lVT+Uy0Nz7iuq0KVHVtTrVZvEYU7mpKUn7kmZ/f0H/wBN+Zyex5V+NeRute20byzr28lzRq05Qa9U1g0y4a9OIW3P3wofw0dxWyN9Wm07/X9T1i/0yhbUvEhb1bqo61Tql1jzfFXXz6+46fw168QdufvhR/ho8DXaiWoy4XKDj6/Fr6HkaPTxwYs27NS4dnqZuqNdxDR9Yz4aQqkHOnKKk4OSaUl3XvNG9zbfvNu7ivtMvFJ3VCrKMpS/Vrup/M1h/SbzI854u8IqPEK1jeWk422t28OWnUl0hVj35Jennh+Wfxej2lpZajGnDnE9rsrWx0mVxyfhl29xqThhk+nru3dS2xfzs9Us6tlcRf4NSOFL3xfZr3o+cfGOLi6aP0GMlNKUXaMlpbVL26o29KLnVqzVOEV3bbwl+M36pxcIRi25NJLL8zW3gPwjvL3V7XcmrW87axtpKra0qixKtUX4Msd+Vd8+bx5Gyi7n0mzsMscHOS5n550i1WPNlhig73bv1vs9xQ0SUe0Z8ZI0748S5+K2uzSxFypR+lUaaf50bV7G/rK2/wDvfb/xcTTHfWsx3BvLWtRpvmpXF3UnTfrDmxH8yRudsb+srb/732/8XE9DpHvZskl2/U+z6QQeLQ6aD5pV5JH3EMSGvI9iz88kfJtNq2FruW+11U+fUbqnCi6sv1FOK/Bj6ZfV+vT0PsIBrscaS5HLJOWR3J3VL2LkNdxmK2uaV3SVWhVhWpNtKdOSlF4eH1XvTRlOTPFla4M6dxX2DS4hbRuLFRir+l/TrOo/1NRLtn0kuj+fPkaVXFvVta9ShWhKlWpycJwmsOMk8NNeuT9CEa0e0tw5+5upQ3TY0sW13JU7yMV+BV8p/NJLr71/dHrtRC/vI+96J7V6nI9Blf3ZcY+vu9vx9Z0/2fmqXF3Q1NdWq6XufgVDcpdzRbhprMdvb+0G/qS5KVK7gqkvSEnyyf4mzelGMP4Wjw+m2NrWY8nY415N/VDXYmvCVSjUjCXJNxajL0eOjKQzTPzVuuJ+eU4SpTlCcXGcW04vumTjJ7Dx+4TXe29cu9wWFGVbRr2o6tVwWfg1STzJSXlFvqn78emfHkzwmqdH9P6DXYdo6eOpwu0/c+1PxQsPDfkj6e2dMvda3DptjpvMr+tcQjRlHvCWViXuS758sGHSdGvtf1CjY6da1by7qvEKVGOW/f7l730RtdwR4KR4fU3qmqOFfXq0OXlg+aFtB94xfnJ+b+hdMt5PUbd23p9j6aTm08jX3Y978fDv8j1qlGUacVOXPNJJyxjL9cFkopGGfy/LiNH5zalRq29/dUaz5q1OrKE2/OSbT/OfoyjQbinp33K4kbltksRjf1pRXpGUnJfmaOZ+r/8Ap3lSz6nF3qL8m/qdUZE008PuUyJEZ+3ksmRRMjmwS1jD9SSmQ+5gCE10z6DYmRkJYkDBDsL2jxkQAZACGIFB9GACAE+w4rCTE+zEpdCEZmg+xng+pxYyM8JM0jmzm0nlZPZuCXFqltZfcXV6jjplSfNRr91Qm+6f9y+/ufzvHilOXvOVSm/U9podbl0GZZ8L4r3ruZ4ObHHLFxkb5UK9K6pQrUakKtKaUozpyUoyXqmu5l8zSvb299d2zHl0zVbm0p5z4UZ5p59eV5X5js0ON+9Ekvu1+O1o/YP0nH0u0sorrcck/Cmvij0E9BO/utG1y7lGqa437z+WfqtH7BX37t5/LX1Wj9g6farRehPyX5jg9Bl71+vYbVoZqn9+/efyz9Vo/YD79+9Plr6rR+wZfSnRP+SXkvzHJ7PyvtXv+htah+Rqj9/Dei7a19VofYD7+G9flr6rQ+wYfSjR+hLyX5jD2bm717/obX+g/Q1P+/jvX5a+q0PsB9/Levy19VofYOf2m0foy8l+Y5vZeZ9q9/0NsR+Zqb9/Pe3y19UofYD7+e9vlv6pQ+wZfSXR+jLyX1Ob2Tnfavf9DbNdxo1L+/pvb5b+qUPsB9/Xe6/Xv6pQ+wYfSTSejLyX1Ob2PqH2r3/Q21QzUn7+291+vf1Sh9gPv7b3+W/qlD7Bj7RaT0ZeS+ph7F1D/mj5v6G2/kM1H+/vvj5c+qUPsC+/xvj5c+qUPsGH0h0noy8l9Tm9h6n0o+b+ht0M1F+/xvj5c+qUPsB9/nfHy59UofYMPpBpfRl5L6nN7B1PpR839DbtdyvM1B+/1vj5d+qUPsB9/vfPy79UofYMfv8A0voy8l9Tm+j+qf8ANHzf0Nvl3GjUD7/m+fl36pQ+wJ8fd9L9ffqdD7Bh7e03oy8l9Tm+jurf80fN/Q3CiBp0+P8Avtdtd+p0PsGCvx+33Vg4vX5Jf3FrRi/xqBze3dN6MvJfUz9mtW/5o+b+ht1uPc+mbS0qrqGrXdOztqa7zfWT/YxXeT9yNL+LvEu44mbld24Soafbp0rO3k+sYZ6yf91Lo39C8jruvbk1PcVz8I1TULjUK6WFO4qObivRZ7L3I+JVm+vU+c2htSesXVxVR+J9XsnYmPZ8utm96fuXq+pgrM4tRmapLLONOR87I+vijDNmNrBU5EZ6nNndFCGIwaDHQQCAAQAAIAAA4i7DEuwzkaY4lLuQu5RpELRZBS7GkUtdiosiLKXQ0gXF4P0g4If2INo/vbR/gn5vI/SHgf8A2H9ofvbR/gn3fRP/ABGT+35nSHM7syGWyGfqCOhp/wC2r/Xnt/8AcEv4xmuqZsR7azxvTb/73y/jGa6p+p+M7b/5jl9fyRxlzMqZSZhTKUj0qZkyI3f9l/8AsOaV/hrj+NkaPKRvB7L3Xg3pX+GuP42R9l0V/wAdL+1/FG4cz1Zkspks/WUdTXT2xv8AgfbP+HrfwYnefZu/sN6F/fXH8fUOi+2R/wAD7Z/w9f8AgwO8+zb/AGGtB/vrj+PqHyGm/wDcGb+xf/kwvxHpjJZTJZ9ojZDPkbr12ltjbep6tWa5LO3nWw/1TS6R+l4X0n1pyUYttpJLLb8jVj2jeMdvuSX9DGi1lWsKFRTu7qnLMK049oR9Yp9c+bSx2y/V7U2hj2dppZZP73JLvf65kbo8Nr3FS6r1K1WTqVaknOcn3k28tmMnmHzH4Rd8WcD7G0f669F/dtD+Mib9s0D2g/8Avs0X920P4yJv4z9Q6Hfws3rXzOsCWQymQz9GR1RovxCf/f8A7m/fO5/jZHs/sxb4hKhdbXuamKkZO5s0/Nfq4L5vwse+XoeL8Q/6/wDc3753X8bI+Tpep3Wjahb31lWlb3VvNVKdSHeLR+E6XXy2dtF6iPFJtNd6b4/rvPHTpm/LJZ0Phfxc03iFYwoznC01qnH+nWcnjnx3nT9Y+7uvP1fe2fuWm1OLV4lmwyuLO64ks67ruwtu7krOtqWj2t1Xaw60oYm/nksP852FkM8ieLHmju5IqS7mrLR8DRdibe27WVbTtHtLWsu1WNNOa+aTyz7jKPOeKnF6y2NaVLSznTu9cqRxCinmNH+6qf6o9383U8bLm0uzcDyTqEF3cPJd5HSPQFOM+blkpYeHh9n6CZ5h7Pet19a2hfzu60q91HUKkpzm8uXNGMsv6XI9PZ20OqjrdNDURVKSsqdqwPF/absufRdEvMf71cTpZ/v4p/7B7Qebe0HZfCuHFerjPwa5pVc+mXyf7Z6zb2Prdm54+F+XH5HKR4dwff8AVK0H/DP+BI29NQeD39krQf8ADP8AgSNvj5rof/g8n93yR48igl+BL5gCX4EvmPtmcJGh+Rkphk/m88ngUbL+zJ/WVqP74S/i6ZrPk2X9mP8ArK1L98JfxdM+p6Nv/iC9TPG1H4D2Aa7iXkNH6uz00jxz2nP61dJ/dv8AsSPANB1u625rFpqVnLkubaoqkG+z9U/c1lP3M9+9p142rpP7t/2JGuOT8n29Jw2i5R5qvge20qTxUzdzZ+7LLemg2+qWMv6XUWJ02/jUprvCXvX51h+Z9s0x4f8AELUeH2rK6s34ttUaVxaSeIVY/wCpryfl83Q2m2VxH0PfdvGWnXSjdKOalnWxGrD16ea96yj6zZu1setgozdZO7v8V9D0+p00sLtcYnaUcLV9D0/cFo7XUrOje2768laCkk/Vej96Oail3PcTSkqatHqm2naPMtS9nfaF/Vc6VO80/P6m2r5X+epHzP0se3ufP3T1Pl9Oann8fIewjR6meztJJ28aN/tmoiqU2eX6Z7OW0bKfNXV9qHX8G4uOVf5ii/znfNB2lo22KThpWm29kn0cqcFzy+eT6v6WfVRx9Q1K00m1nc3tzRtLeHWVWvNQivpZYabBg4wgl4/5niZc+bLwlJs6xxg/saa/+5/9qJq7w1f9UHbn74UP4aPTuLXHax1zS7zQtEt/hNtcLw6t9WTimsp/Ej38u7x83meY8Nf7IO3P3wofw0fIbQ1GPPq4PG7ql7z6HQ4cmHSZFkVXb9xusNdhDXY+uZ8LIa7hGUZxUotSi1lNdmgXc104bcbFtbW73Q9cnKeku6qKhc9W7bM30a84fnXzdvX59TDBKMZ8FLtO2HSZNTCcsfFxrgbC32nWmqUPBvbWjd0c58OvTU45+ZnAtdl7fsq6rW+haZQqxfMqlKzpxkn65SPp2t1RvrelcW9WFehUipQq05KUZJ9mmu6MyNSjGXFo9a5zit1NoY13EvIaObPDkM8/4375hszZVzCnU5dR1CMra2in1WV8ef8Aip9/VxPv7235pGwtKleanXUZtPwbaDzVrS9Ir/X2RqBvvfF/v/X6up3zUE1yUbeLzCjBdor/AEt+bPU63UrFFwi/vM9/sbZk9XmWbIv9nH3vu+p103r2N/WVt/8Ae+3/AIuJoojevYv9ZW3/AN77f+Liet2f+KR7fpX/AAsXrfwPuDENdz27PzGRR4hx64xvQqNXbeiV8ajUji7uab60Iv8AURf7Nru/Je99Pt8bOL1PYenvTdOqRnr1zD4uOqtoP9W/f6L6X6PU6tcVLmtOrVnKrVqScpzm8yk31bb82ep1Wfd+5Hmfb9HtidfJazUr7q/Cu/xfh8fVz989mTiD4FxW2pe1PiVeavYuT7S7zp/T+Evml6mxh+fmn6jcaVf297aVJUbm3qRq0qke8ZJ5TN4eH28rffe1LHV6GIzqR5K9JP8A3uqvwo/j6r3NGNPk3o7j7DxelmzeozLWY192fPwl/n8bOyHA13RLTcmjXml31PxbW6punOPn7mvenhp+qRzxrsd5cT88U5QkpRdNGhu8tq3eytyXukXi/ptvPEaiWFUg+sZr3NY/0eRt7wd3zT33smzupVObULeKt7yL7+JFfhf4yw/pa8jq3tFcOf6KduLWrKlzanpkHKSiutWh3kvnj+Ev8b1NfuGXEW84b7ihf0FKtZ1UoXVrnCqw+0u6f+ps9d/CnXYfq2eC6VbJjkh/Gx9nj2r1SXFePqZvGB8bae79K3rpNPUdJuo3NCXSUe06cv2M4+T/APpdD7R1Z+N5sc8U3jyKmuaYpQjUg4SSlGSw4tZTR1G84P7L1C5dettyy8RvmfhwdNN+9RaR3AaOMjGPU59O28M3G+5tfA+doe2tJ21bujpWnW2n03+Erekoc3ztdX9J9KU404ynKSjGKy5SeEkKc404Oc5KMIrLlJ4SXqzWvjxx5palb3G29t3HiW88wvL+m/i1F506b84vzl59l078WeZs7Zmr23qljx2/Sk+NLvb+C7TZddij4+z9Q+620tEvc83wmyo1W/76EX/rPsHJnz2aDxTljlzTryGuxpZ7Smn/AADi5qs0sRuadGul/wCzjF/nizdNdjVL2vNP8HeWjXqWFXsPCz6uFST/ANE0cj7noLm6vbG56UZL4P5HgzZEmU2Y2+pGf0UHkTIbJk+pzbAmS+42TkyBCYCbIyEjXcTYIyXtGACBQABN4ABvAs5Dux4ISxYElhmRRDk6gw2KCM0ERGJliinNyMsOhng8YMEVkyxbRtM4NnKhMzRn7ziRZkTZtM4ujlKo/UpVGcbmY+c1vGKOT4rF4rOPzi5xZKRyfFYvFZxucOdjeFI5PisXis4/Oxc7G8KRyfFYeIzjc7DmZN4UjkeIw8RnG52LnG8KRyfFYeIzjc4c43hSOR4jDnZxuYOcm8Wjk+IxeI/U43P7w5/eTeFHI5/eHie843P7w5xvCjkOYuf3nH5xOWSbwoyyqGKdTJLkY5SI5GkKpI4tR5Ms22YZI5tnZGCaOPM5M1kwzizkzumcVojHXJnlAjkwZZ2TMYJlOJDWDJuxiBMCFEIYgAABAHEiZI1ZwpzgniM8cyx3x2Ma7lHI0BXckcTRDNQrTozU4PlkuzEn1ITwUUIspPJCeRp4NFMtStKrUc5vmk+7PbNq+1tu/aG29N0Sz03RKtpYUI29KdehWc3GKwnJqqln5kjxDuNPB5mm1efSScsE3FvuKnRsH+nX3u++lbf/AMnr/wA8P9OnvZ/rXoH+T1/5418TyUng9j++tof1mW2d54ocWNX4tanZ32sW1lb1rWi6EI2UJwi48zeXzTl16nTPmMamUnk9blzTzzeTI7k+0yZI1ZwhKCeIyxleuBKQkwM2Ck0erbB9o7cvDvbNvoem2OlV7ShKc4zuqNWVRuUnJ5cakV3foeTjPK0+qzaWfWYJbr5cC3R7x+nE3n8maF/k9b+eD9OHvJ/rZoX+T1v548HTGpM9l++9of1mW2eh8S+NOt8VLawoata2FvCznKdN2VOcW3JJPPNOXoYNlcZd17CzDTNRcrRvLs7mPiUc+6P6n/FaydEUhqR4b12peb9o6x7/AH3xJbNjtN9sa+p0cX+2be5q/sra7lRj+Jxn/pC79sS+qJ/Bds29F+XjXcqmPxRia5KQ+c9r9odp1u9d7o/Qu8z0Pe/HLdm/Ladpe30bWwm/jWllDw4SXpJ5cpL3NtHQlJGJT941M9Nn1OXUz380nJ+Jm7MmV6lxqOMJRTxGWMr1wYeYFJHCwcuwvamnX1vd0WlWoVI1YZWVzRaa/Oj1D9Mxvd/8Ys/8lR5LkaaPO0+u1OlTWDI43zp0VOj1j9Mvvb/lFn/kqF+mV3q/+MWf+TI8pUveNS955f742h/Xl5su8zm6rqdfWdUvNQuWnc3dadeq4rC5pScnheXVs4ykRzD5j1Tk5Nyb4sycmjfV7e5hc0qs6NxBqUatOTjKLXZprseq7U9pHcOiQhR1SlS1u3j05qj8Otj+/XR/Sm/eeQ8w1I83Sa/U6GW9p8jj8PauTKm1yNl7X2pNCqRTudI1GjLzVJ06i/G5RIvPai0WEG7TR7+tPyVaUKa/GnI1s5kCaPoPtVtSq315I1vs9R3b7QG5NxQnQs5Q0W1l05bVt1WvfUfX/mpHmk6kqk5TnJynJ5cpPLb9WYsoMo+f1Wt1Gtnv6ibk/H5LkvYZbb5nddh8VNW4e293Q06jZ16dzKM5q6hKWGk105ZR9fzHaP0y25v+Q6R+Rq/zh5HkeTy8G2NfpsaxYczUVyRbaPW/0y25/wDkOk/kav8AOHztx8eNf3Pol1pd1Z6bTt7iKjKVGlUU1hpprM2u6Xkea5QZRvJtvaOWLhPM2nwfqZLZ9jam4Km1dw2WrUqUa9S1m5xpzeFLo11x856p+me1T5Es/wApI8Uyg5jjpdqazRQePT5N1N32c/IzR7Z+mf1T5Es/ysxP2n9Uaa+4tn1/9JI8U5g5jzPtBtP+s/JfQzuIvIZJ5g5j0FmjI5uUYxfaPY9B4d8Y7zh3o9xp9tp1C7hWruu51ZyTTcYxx0/vTzvm9wc3uPJ0+qy6WfWYZVIzKKkqaPbv00Wq/Iln+UmNe1HqvyJZ/lZniOQyez/fm0P6r8l9Dl1GJ/ynoXEXjBecRdMtbO50+hZxoVvGUqU223hrHX5zoKkQmvUD1ufU5dTPrMsrZ0jGMFUTNCq4SUk8NGS2u6tpXhWoVZ0a0HzQqU5OMov1TXY43UM+44J1xNHp+2/aB3XoUY069elq9BfqbyOZ4/v1h/jyd+0/2pbGcV8N0G4pS83QrxmvzqJrnzDUj2+La2swqo5G148fieHPR4MnOPyNnV7T22+T/g3Veb05KWPx85xbn2pNKjBu30S8qyXZVasIJ/SsmtqmNSPIe29Y/wCZeSOH7u0/d7z2TWfaZ3FexlDT7Oz02LXSbi6tSP0v4v8Amnmeubm1Tctz4+qX9e+qrs6021H5l2S9yPkcw+Y9bm1efUfxZt/ruPMxafFh/hxSMiOy8NH/AFQtt/vhQ/ho6tzHZ+GUv6oe2/3wofw0c8D/ANrH1r4lz/wpep/A3bH5CKP0xn5XIF3NEdcm4a9qDTw1c1P4TN70aGa+/wDu7qP7pqfwmfLba5Q9vyPqOj/48ns+Z9naXEjcGyZr7lajOlQzmVtU+PSl/ivovnWGeq6X7VdxTpKOo6BTrVMdaltcOCb/AL2UX/pPAs+8OY9Di1ebCqhLgfQ59n6XUveywTffyfuNjH7V1rjptyt/la+wdZ3F7Tu4NSpSpaVZW2jxln+mZ8eovmbSj/mnjPMHMdJa/UTVOR40NjaGEt5Y79bb9zZztU1i91y9nd6hd1r25n3q15uUvmy/L3HEyRzBzHgt3xZ7hJRVJcDK5tpJvKXY9X0n2ldz6PpdnYUbDSZUbWjChCVSjVcnGMVFN4qLrhHkeQydIZZY/wADo8bUaTBq0lngpJd57P8App91/J+jfkKv86D9qfdjTSsNHTfmqFXp/wBaeMZ948nT9py+keB+5tn/ANFHO1TVbvWtRuL6+rzubu4m51Ks3lyb/wDrscXJjyvUOZHj3Z7hJRSSXBGWM3Fpp4Z3Ph5xZ1rhqryGmRtq9G65XOjdwlKCkv1S5ZRw8dPxeh0fKHlFUnF2mcc+DFqcbxZo70X2M9p/TV7s+T9G/IVf50a9qzdnydov5Ct/OnivMPmOnWz7z1H7h2Z/QR7S/ar3XJNPTtFafdOhV/nTyG/vFfX1xcKhStlVqSmqNBNU6eXnlim20l5dWcTmDmMOcpc2edpdn6XQtvTY1G+dH2Nu7q1bad8rzSL+tYXHZypS6SXpJdpL3NM9n237WGoW1KNLXNGpX0l08e0qeFJ/PFppv5mjwDmDmCk1yOGu2Rodo/4nEm+/k/NUzaun7WO2HDNTStWjPHaMKTX4+dHzNW9riyhSktL2/Xq1Guk7utGCT96ipZ/GjWbmDIc2eij0P2RGW88bfrkzvG+OMm59+qdG/vvAsZf8StE6dL6V3l/jNnSMk5Fkxdn1en02HSY1i08FGK7EqPWtte0vuja2g2Gk2tlpNa3s6So0516NVzcV2y1US/Mj6f6bbd/ybon5Ct/OniPzibyYbPTZOjuycs3Oeni23bPbv03G8Pk3Q/yFb+dOj8TOLur8U3p71a0sLeVj4nhysqc4t8/LlS5pyz+AsfSdIbIbwZs6abYezdHlWfT4FGa5NeKr4BJkOTk8vuJsDDPfBklsbeCGYZAbyvmJbG2S2QCyJtpNeoNiZgIlscSclR7Ao08MBASwAu7BvoCIQfd9SkgijJFFObZVChOvVhSpwlUqTkoxhBZcm+iSXmzZ7hf7OWn6VaUNQ3RSjqGoSSnGxk80aPukv1cvXPT3PudA9mfatHW981NQuIKdPS6PjQT/ALbJ4g/oXM/nSNr2dYR7WfkHTDb+fBl/YNLLd4XJrnx5Jd3Di++zjWWm2mm0o0rS1o2tKKwoUKahFL3JI5AAdj8gcnJ23bATGJg5kgAFIwBgDBkliGxAyAAAMsliGxFIIAAIwBLKJZSMQAAMgIYgZEIYgRgIYgZATGJgyIQxFIAABTJLJaUlhrKfkymIIjOr7p4abb3jbzp6jpdB1ZLpc0YKnWj8011+h5XuNV+KnCu94b6pCM5u70y4b+D3SjjOP1EvJSX5+/qlugdW4nbYo7t2NqthUgpVFRlWoSf6mrBNxf41h+5s45MSmr7T7noz0l1WytVDFkm5YZNJpu6vtXdXvNHJRMUkcqcTBKJ6w/qKLML9H5CTyVJEeZDqMMgIFAQAQHDKXUkyU5wVOcZQ5pPHLLOOX16eZzNCAAKQoaYUZxhUTnDxI+cc4yIoLKTyQmM1ZSxphUqQnUbhDw4vtHOcCKChpkZwZJVIuEEocslnMs9y2AyUmY8jLYMqmNTIjUioTTjzSeMSz2EpGrBmUkNNGFSMlKpGM05x54+cc4yWwWBjUhqXvLYMmQySpFzqRlNuMOSPlHOS2BZHknm9w1L3FsDyNMHODhBKGJLOZZ7k5RbBSY+b3k9CoygoSTjmTxiWexbA0/eNSI7+YY94sGRSYKRNNxjNOUeePnHOMi6otgyKQ1IxZY1ItkMvMNSInNSm3GPIvTOcC5i2DLzD5jDzFupFwiksSXd57iwXzD5jFze8Ob3lsGXmDmJjOKhJOOZPGJZ7E83vLYMvMHMY+b3lQnGMk5Lmj6ZwLFl8wcxi5kHMLBl5g5veY+Yqc4yk3GPKvTORZCub3j5veYuYfMLKZeYakY3NOMUo4ku7z3FzFshl5hqRh5i4zSjJOOW+zz2FizIpD5kYecfOWwZkxpmOE0pJyXMvTOBcyLYMuR5MSkNMtgyZ9wZRMppyzFcq9O4cwsFhn3k8w3NOKSWGu7z3LYKycrS9TudG1G2v7Or4N3bVI1aVTlUuWSeU8Po/pOHzBzGlJp2iNJqmeiff+358vfU7f7A/v/78+Xvqdv8AzZ54pxUWnHLfZ57C5keV+2aj+pLzZ4v7Hpv6UfJfQ9EXH/fny99TofzZ0K4uZ3VepWqy5qtSTnKWMZbeWYeZDjOKkm1zL0ycp58mX+JJv1uzpjwYsV9XFK+5JD5g5ieYOY5WdyssMsnmHKSb6LC9BYKTYZZGQyN4F5DInJcq6Yfm/UXMhYKyGSeZDU1h5WX5MbwHkfMQpjUhYK5h8xMZpPqsr0DmQ3gVzBzE8wcyLZCuYfMS5pvosL0DmJZSuYMk83uBzWF06+oshWQyRzMOZiwWLmRKkknldfUnmJYLyS5EuRKms9VlehLBTkQ2LIZwZsBnACyKUk30WEYbAm8iYZJbwQgNktjbJbMgCWxkt9H6kKBS7EFEYGIF3AgE+5SIz1LiDLMkVkzQjkxR/EcilEHjTZsN7JkEnumWPjJWqT/K/wAhsGzX/wBk5Yjun/3X/tjYBnkw5H859K3e2M//AMf/AKxEd04dcI9wcTqlf7kU6FK2oPlq3V1U5KcZYyo9E5Nv3JnSz0rgJreoUOIugaZTvK1PT6154tS2hNqE5KDScl5495qV065notnwwZNVjx6hNxbrhwfHlx9fPwOsLh/rNbetfatpQjf6tRryoONu/iNx7y5pJYj07vB2zcns6bt23o1xqT+AajTto81xRsK7qVaKXVuUXFdvdkx7q3tq2w+MO7NQ0etChdVLqvRc504zxFzy8ZXR9F1O78JtJuOFOgavvfddxKzoajayoW2n1G/Gu5SfMpOPv8s+TbeF38N5J9UsifYva+4+i0mz9Bm1WXSzjJ1KScrSjCC5SfB343XcuLNej0fanATdG7dsVdfoqzstOjTlVpyu6rUq0Yp5cVGMvR98HX9NtNq19natc399eUNywqr4FaUo5oVIdMuT5H/dfql2R6n7OGt6hqVPdFpdXlava2miVIW9Cc24UlnL5Y9lk7Zpyjjk4819LPXbI0Om1GsxYdV96ORcN1q07/m7uTdc+XYec8OeFGq8TVqMtNu7CzhYRhKtO/qzhHEs4w4xl+xffBn37wf1Hh9pVG/vNX0a/p1ayoqnp1zKpNNpvLTgunT/AEH3eDm8traDtXd2k7luby2p6rSpwj8Cp81SUVzZUXhpPr+q6BvHhrte64ey3hsu/v69nb11QvLTUVHxKTeEsOKXZuPr379MEyTlHJXKPDs7/wDPgd8Oh0ubZyyYoqeapN/fppJvju1xqPHmeSsQ2I8k+PAAAGWSxDYikEAAEYAllEspGIAAGQEMQMiEMQIwEM5Wk6Xca1qdrYWsOe4uasaVNe9vHX3DkIxcmoxVtk1NOu6VjSvZ2taFnVk4U7iVNqnOS7pS7Nr0Mmn6FqWrwnOx0+6vY0/w5W9GVRR+fCeD0Xfmlw1e31Cy025hDSdnW1K3UOX/AH+rOeKk1js+ZdfmMW59xantXZuyrfR72tptKrayu6itpcjqVHPvJr8L5n0OSm2lR7qezseGc3lk9yKTtVxd7rrjyUr49y8TzGcJU5yhOLjOLw4tYafoSd940QjLd9G55Yxq3dhb3FZxSXNUlDrLHvwfQ39wyp2lHbNxoNBuOo0qFvWoqcpctzOKkm8t4Uk8+i5WVZFwvtPHybNyqeaOP7yxtLxdulw+J5kB7NqfDfb+m7sttMp0fhVvHb9W7nUVWeKtxDnXifhdOsey6e4+Hd8PbDQ+Gep3t9Fz3HSdtVlS5mvglOrLEYtJ45mk20+2V2CyxdHSextTj3ra+6pN8fRV1y5vs9T7FZ5mxHtGo8FLmfEKy+BaHN7WlO3dVqv05HGPidXPn783b6DynctpR0/ceq2tvDw6FC7q0qcMt8sYzaSy+vZGoZIz5HiazZuo0SbzKlbj28a7VaVrxPmilFTi4yWYtYafmMDqeqPz9qQwzj1Ec2tE4tRHpmf2rBnFkjGzNMwy7mTy4iAF2Dy7A2IAAyDhgNrqIwaKTyMhPBQAxp4EBScihpkJ4KTyUeovIZIHkosvmHkjmGWylhlkZHzFsFqQ1IhSGpIAtNDRCAtgyIE2Qh5ZbBkUgUiFJgpFBkUhqRj5g5vcWwZecfN7zFze4OYWDKpe8fMYuYfMLBl5g5jFzD5i2QyqQc3uMSkPm94sGbmDJi5vePmLYsy5948mJSHzFsWZAMakPnLYsyZDJHOHOWwXn3Dz7iOcfMLBWX6Bl+hPMPmFgrLDLI5vePmLY4FZHlkZHkWQrLDPvJyPIsDz7x5JyGRYKyPLJyPJbBXMw5iR5LYK5hqRGQyWwXzD5iMhktgyqfvBTMeQyWwZlMamYcjyLBm5w5jDn3jUmWwZlIOYxczDmYsGbmDmMPMw5mWwZuYOZmHm94c3vJYM3N7w5veYuYOYtkMvMHMYucOYWUy8wcxi5veHMLBl5h8xhTY8sWQy8wcxiyx5YsGXmYczMWWGX6CwZedhzmLLHliwZecOcxZfvDLLYMvOHOYsv0DLJYMnN7w5jHlh19RYL5hcxOfeLIsFZDJOQySwVkQuZEuRmwU5E5FnBLZCFNktibE2SyhkQCyQDbIyDYEQGu5RK6IeSMAACIAz1LiY/MuIMMzx8jk00caD7HKpFR4mQ2I9lH8HdH/uv/bHvzNbfZc1mla7i1bTpy5Z3lvGpDP6p028r58Tb+hmyTPJhyP536VwlHa2VvtUWv8AxS+KEdm4a7mtdm750jWb2nWq2tpV56kKEU5tcrXRNpefqdZA6HyuLJLFOOSPNNNew9Q2/v8A2nT4tavujXNLvL/Tq1apcWlvGnCU4VHNOMpxc1F4WfN9cHbd78U+F2/9Rd9rGm7pubiMOSlFSpxp016RiquF7/U8CEzx3hi0lx4Kke6x7c1OOGTHuwkpy3ncU7f+XZ3HZdN3TpVjs3VtGq7et7vULuqp0NWqTSq20Vy/FS5W3nD/AFS7n3eD3ETTeH1XcEtRoXVZahYStaXwWEZcsn5y5pLC+bJ52B0lBSUk+3n8D12HX59PlxZoVePlwXi+Pfz7TvnDTfGgbbt9T03cu3qes6ZfxSlWpRirmi1+wk8PHbpzLqsn1d78UtDq7Me0dm6PX0nRatZXFzWvJ81avJNNJ4bwui832XY8uBkljjJ7z/VcjeLamow6d6eFVTV7q3qfNb1XTJYhsR1PTgAADLJYhsRSCAACMASyiWUjEAADICGIGRCGIEYHK0rVbvQ9QoX1jWdvd0XzU6iSbi8Y7Pp5nFEBGTg1KLpo9Ct+N+4/uNqtle3VS9q3dONOjXfJD4P1+M8KHxuZdPLBwdL3/YPRLHTde2/T12Gnt/BKquZUJwi3lwk4p80c+R0sTOfVx7Eee9p6yTTnk3qVfeqXC74p3fHv7l3I+tuvc11u7XK+pXUadKc0oQo0liFOEViMV7kjt1HjPeWlzXq21jGmqmm0rKEZ1ebw6tOLjGvH4vdKUunv79DzoRrci6TRyx6/U4pyyQm1KTtvx4/VnoGk8WZ6VrGj6hHS41Z6dpP3MUJ1+lR5b8R/F9/4P5z4v9HNzX0PcVleU5XV1rNejXqXcqmHBwk5fg465zjusYOsgNyK7CS2hqprdc+HHu7Vuvs7uHh2HbtT4gfdHiDabo+AeH4FShU+C+Nnm8OMVjn5emeX06Z8zrWs6h919Yvr7w/C+FV6lbw+bPLzSbxnpnGe5xGI1GKXI8fNqcue+sd23J8ub5v9cAAD5W6dXp6DtvU9QqyUY29vOpnPd46L528L6Tb4HDHjllnHHDm3S9po3VRw6iObVOFU7s9Mz+zcZxpmGRmmjDJGTzokoRSiHKQ2SIvlDlIDhtZHGMHTm5T5ZrHLHH4Xr18gE0YNkjTwIADLRjCc0pz8OL7yxnH0EkZwUnkAYABbFF1VGFRqE/Ej5SxjJPMIAQrJcoxUINTzJ55o47GIMlHAvLDmJ5g5hYMseRwm3LEljEcdxZRGUGQOJkTLpKMqiU58kX3ljODCCKDImxqRjyNNlsWZFIupyxm1CXPHyljGTDzApFFmTmHzIxqQ+YWLMr5VCDUsyecxx2FzGNSGpFsWXzIuPI4SbniSxiOO5iyGRYsvmQ8ohMMlscDLSUJTSnLkj5yxnAskZAAyJgQBQZpqMZtQlzx8pYwLJjyGS2QyJst4UItSzJ9447GHI8sWDJzMOYx8zHzMWDLHDhJuWJLGI47i5jHzMeWWwXzMuniUkpS5F5vGTDljywC+ZhzEZYZ95QZMlTxGbUZc8fXGDFkADJkMmMYsGZ4UYtSy33WOxPMYwFgy8xUeVxk3LDXZY7mEeS2DJkeTHkEygzQw5JSlyr17hzMxZGmAZFIfMY8hzMoM0mlJqL5l69hcxj5hqQsGTmKfKksPL816GLmQZRbBkyh5RjyGfeLBlSi4tt4fkvUXQjIZLYL6FRUXJJvlXqY8hkWC+gZRGQ5i2DJlDk4p9HzL17GLmDmJYMikg5vmMfMHMWwZW0orD6+ax2DmZi5mPmYshk5mNdnl4fkvUw5HkWUyZHn3mLIZFgzRw2svC9RZMeQ5mLIZMhlmPmY+ZiwZX0fR5XqLJj5mHMLBkyN9l1y/QxczDmYsGTIZMeQyLBlTWHl4fkieYjIZFgvmEnlrLwiMhzCwVkTkTkWQCmwk0n0eURkRAU2IQZJYG+iXUlsGxZIAyNLOepJS6ADAQEA1+IQBkAXmXB9TH5lRfUGWciL95yab7HEgzPSkDxZo+/t7XLvbur2mpWNTw7q2mqkJeXvT9U1lNejNwOH3ErS+IGmxqW1SNC/hFePZTl8eD82v2UfevpwaVUp4PoWV7Wsq9Ovb1p0K0HzQqU5OMov1TXVHSMt0+J25sLFtaKbe7OPJ/J96+BvkBqJY8Z95WVONOnrtacUsZrU6dV/jlFtnMjxz3p8tfVaH2Drvo/N5dDtcnwnDzf5Ta8TNU1xx3p8s/VaH2B/fw3n8s/VaP2Bvo5Pohr/Th5v8ptSBqt9+/efyz9Vo/YF9+/efyz9Vo/YLvoj6Ia/04eb/ACm1QM1V+/fvP5Z+q0fsB9+/efyz9Vo/YG+ifY/X+nDzl+U2oYjVf79+8vln6rR+wH37t5fLP1Wj9gdYifY7X+nDzl+U2oA1X+/dvL5Z+q0fsC+/dvL5Z+q0fsDrET7HbQ9OHnL8ptOxGrP37t5fLP1Wj9gX37d5fLP1Wj9gdYifY3aHpw85flNpgNWfv27y+WfqtH7Avv27y+WfqtH7A6yJn7G7Q9OHnL8ptOSzVr79u8vln6rR+wL79u8vlj6rR+wXrYk+xm0PTh5y/KbSgatfft3j8sfVaP2A+/ZvH5Y+q0fsE62JPsZtD04ecvym0ojVr79u8flj6rR+wH37N4/LH1Wj9gdbEn2L2j6cPOX5TaQRq39+zePyx9Vo/YD79m8flj6rR+wOtiT7F7R9OHnL8ptII1b+/ZvH5Y+q0fsB9+zePyx9Vo/YHWxJ9ito+nDzl+U2kEzVz79m8flj6rR+wL79e8flj6rR+wOtiT7E7R9OHnL8ptGI1d+/XvH5Y+q0fsB9+rePyx9Vo/YHWxJ9ido+nDzl+U2iA1d+/VvH5Y+rUfsB9+rePyx9Vo/YL10TP2J2j6cPOX5TaBiNXXxr3j8sfVqP2DHPjXvJrH3Z+rUfsE66JfsPtJ/zw85flNoq9ela0Z1q1SFKlBc0qlSSjGK9W32NceNvFilulLRdIqOWmU581auunjzXZL+5Xf3v5kdG3BvXW9yR5dS1S4uqec+FKeIZ9eVYX5jrlSRyyZt5Uj7XYHRCGzsy1WqkpzXJLkn38eb7uVHFqnDqI5dVnFmeIz9YxnHmjC12M8kY2jJ5SZjS6DwUo4SHgG7MeAwXgCCz5wAVGlOdOc0sxhjmee2exzO5DWSSxNZAJAulRnWqKEFzSfZEADTwPJIAFgFWlOhUcJrlku6yTlgFATzFypyhThNrEZ55X64AEAsoZbFABUaUpwnNLMYY5n6ZJFgExpiLpUpVpqEFzSfZZAEpDySBSFphkkqpSlRm4TXLJd0UWPPvDJAwLLyCB05RhCbWIyzh574JKLLQzGXGnKUJTS+LHGX84sWMaZjGhYsvI0xUoSqzUILMn2RKZRZkyCkRkfMBwL5hqQqkZUpuMukl3RPMUcC+YfMRkpwlGEZNYjLsy2OA0x5IyGRY4F8wcwRhKUJSS+LHGX6EgcC+YMk5KpwlUkoxWW+yKQeQ5iBiwVzD5iC5wlSm4yWJLyADmDmJAtgvmYczE4SjGMmsKXYQsF8wcxJUYSlGUkukcZfoWwPmDmJDIsF8yHzImEXUkoxWWxFBfMh595AAGRMfMROLpycZLDXkLIsGTmHkx8xTUoxUmuj7FsFZHlGPmHzFBeR5Jim4uWOi7i5gC8hlEcxUE5yUY9Wy2CshkjmDmFgvIZIyOScJYfRghWQyRkMgpefePJLTUU2uj7C5hZCsjyRzDWWm/JdxYKyGSOYeS2C8hkmKc2kllsWRYLyGSMjyLBWQyS8xeGsMMiwVkeSMjeUk/J9gCshkjIZFgvIZJSbTfku4siwVkMk5BJyeF3FgeQyLIZJYGIWQl8V4fcgHkTZOQAGAYeE/JjXQAF0HkWR9Wm/QABAAsAGQXViJYBgngH2EmCMzRkZYywzjJ4eDLGQOMkcyEzkU6vqfPjPBmjU6Ip4s4H0YVTLGsfOjV95arFPEliPoqt7x+N7z56rdPcHjL1FnLqj6Hje8PGXqcDx0CrZfcWTqjn+MvUXjL1OB469Q8depLHVHP8b3i8b3nB8deoOvhiy9Uc7xveHje84Hjh44sdUc/wAZeovGXqcHxheOLHVHP8deovH95wfHDxyWOqOd4/vDx/ecDxw8cWOqOf4/vF4/vOCq+ReOLHVHP8f3i8f3nB8cXjsWOpOf8I94eP7zgeMxeMyDqTn/AAj3h45wVWH4rwn0Fjqjm+N7xqt7zhKt7w8YlmeqOb4weN7zhqrleQeKLJ1RzfFE6pw/FXqCqZfQWTqzlOqY5VTjuqiXVFmljMk6nvOPOeRSnkxTl1MnkxiTUlk48jLJmGRk8qPAxS7kNZMso/nJS6kOyYuUMFYBRbQLZHKGC+UOUCz5AAByPMAAAABNZGABPKLBYAEAVgOVAEgPlDlAEA8MWGAGR5YgAHzApCAArmGpEDAK5kPmIGUhXMNSIGKFlcw8kAUF5HkjI8ghYIjIZKDIBGQTAMgEZY8soKGRkfMOILyGSOYfMOILTHkjIZKDJkMojIwC+YMkZGAXkMkZDJQXkeSMgUF5QZRIAF5QZRAwC8oMogCgyZDJAZAMgEZBMAseSMhzFBY8kcw+YWChk8wKRbBQyeZBkWCgFlBktgoCcjyLIMeSeYOYWCgyTzBzCylgRzMOZghYEZAtgyBkxgAZMoMkBkcQXkZjAcQZMgY8jyUFgRkMjiCwIyGQDIBjyGQDIGSMhkArIZJyIAvmFzEgAVkQYHgWBDSGBLAAAAAAgIBgLIZAGIAADImGQADJUZYIfQEwZaM8Z4LUzjKWClMHNxOUqjRSq4OKp+8fie8GHA5SrB43vOL4geIDPVnK8YPGOL4geIB1ZyfGDxjjeILxANw5XjB4xxfEDxCE6s5PjB4xxfE94eILHVnJ8YPGOL4geILL1ZyvHF4xxvEF4nvFjqzleMLxvecbxPeLxPeSydWcrxheMcbxBqYsdWjkeMCqswKYKZBuI5CqjVU46mPmBncOQqo1VOOpoFMGd05HijVQ46lkOYGd05HiAqhgUh8wJumdVA8QwcwcwM7qM/iEuoYuYMkLuopzyQ2GSWwaSE2QyhYIbIwNLBagPlIWzHgMGTlDlAsx4DBkwLAJZ8IAKjVnCnOCeIzxzLHfHY5HsiQAAAAqlVlQqKcHyyXZkgAAAAAFVasq9Rzm+aT7skAAHCEqklGKcpN4SSy2fco7erSpQV9X+CxjnloqPPUWfVZWPpefcAfCA7NDStOpLCoVqz9atXCf0JL/AEmRWtgl/wAGUH89Sr9slg6qB22NKyhCcFptuozxzLnq9cf45PwWw+TLf8pV+2LB1PAYO2fBbD5Mt/ylX7ZVKlZUainDTbdSXZ89X7YsHUcDwjtfwWw+TLf8pV+2Hwaw+TLf8pV+2LB1TCDCO1/BrD5Mt/ylX7ZdSlZVpuc9Nt3J93z1ftiwdSwgwjtfwbT/AJMt/wApV+2HwbT/AJMt/wApV+2WwdVSQYR22VOylCEHptvyxzhc9Xpn/HJ+D2HyZb/lKv2xYOqYQ8I7V8HsPky3/KVftlRhZQhKC0235ZYyuer1x/jiwdTwh4R2nwLD5Mt/ylX7Y1Q0/wCTLf8AKVftlslHVcIeDtlOnY0ZqcNNt1Jdnz1ftk+Bp/yZb/lKv2xYo6rgOU7V4Gn/ACZb/lKv2w8DT/ky3/KVftlsUdV5R8p2ypTsqs3KWm27k+756v2yfAsPky3/AOfV+2WyHVeUMHavAsPky3/59X7ZThZShGL0235Y5wuer0/zxYo6pgeDtPgaf8m2/wCUq/bDwNP+Tbf8pV+2LFHVkh4O1xp2MYSitNt+WWMrnq/bErew+TLf/n1ftlsHVgO0/B7D5Lof8+r9sunTsaU1KOmUE12fPV+2LB1QDtPgWHyZQ/59X7ZEtP02p3talL30qz6f85Mtg61geD7VbbkaibsrjxZf2qtFQk/meWn+Y+TcwrU68414yhVXSUZxw19AsGPA8IQygeEGENzcoxi30j29wgAwh4QFKcoxlFPpLuhYJ5Q5QGWwLlDlZUJunJSi8NeYgBYYdSgKBAXObqScpPLYgCR5HhDcnKKi+y7FBOQyPCDlFgAKTai4p9H3FgoAAwVCThJSi8NCwSMMB0FgAyMcpOcst5bFgQYYZGgAwCiNzbik30XYMlAcoYDI1JpNZ6PuALlHhBkAQMByjjJxaaeGLIAcoYABYDHvDHvKcnJ5fViFgWAwMbk2kn2XYWCcDx7wAWAx7wwNSaTXkxCwGEPCENScXldwADIgAHkMiG5OTy+4AAIABgJttJegADDIgzhNABkBAAMBJ4YADEAAALHp0G3liAFloOYeRN5AoeQ5mTgMEJRXMw5ievqLr6ixRfN7xc3vJ+kFlPuSxRXMLm95OPeGPeLFFc/vDn95GPeNpt9xZaHz+8Of3k494Y94sUVzC5veLHvFggorn94c/vJx7wSfqBQ+f3jUs+ZKj7ylF+oINAmCTXmNRBhjTGmJR948e8GWGRphht9xqL9QYY0wBR948N46gyxJjTBRfqNRfqDIJjBJ+oKPvIZBMaYKL9RqLT7gCyBXKCj9IISIyKI8ZZDJj5RpYLwGCCyMBgv0DAJZHKHKXgazgEsx8ocpeGGALOuAAHI9uAAAAAAAAAAABVOnKrUjCEXOcmoxjFZbb8iT7237b4NQneyWKkm6dH3fspf6l879ADm2VlDRoctNqV41ipWXXk9Yx/1vz+bu8AuxUYSnJRinKT7JLLZkE4DBz46HfSjlW8se9pM4te3q20+WrTlTl6SWBxMLJCTqLTMWAwMAbFgMDAAWAwMABYDAwAFgYAUAAAQAAAaAAAAFYYAnkYAgGAAhgBUBrLHgSYwRBgMAAQYAAGiDyPqSUmAGAwMABYLrUqWpUY0Lp4celKv3dP3P1j7vLy98g+wB1u6tatlcToVo8lSDw1/r+Yx5Ow6vb/DtP8Vda9svplTz2+h/mb9DruTQKyGRJhkAoBDAGAhgDAQFAwACgYCAoKAQADAWRgDAQADGIMgDDIgAGMQADyAsgAMMgGS2BhkWQKB5HkkMgFZDIgAHkeSQyUFALIZAGAshkEHkBZDIKMBZDIAwFkMgDAWQyAMBZDIAwFkMgDAWQyCDAWQyCjyLIsgAPIZFkCAeQ7+ZIAF4X7LH0Byx/Z/mIAWDJyw/tn+aPkp/23/NZiyBAZfDpf27/NY1So/2/wDzGYAyQHIVGh/yj/MY/Bof8p/zGcYADk+Bb/8AKv8Aq2P4Pbf8r/6tnEAA5nwa1/5Z/wBUw+DWn/Lf+qZwwAOb8Fs/+Xf9Sx/BLL/l/wD1MjgBkA5/wOx+UP8AqZD+B2Pyj/1Ej54gD6KsrD5S/wCokP4Dp/yn9XkfNGgD6SsNOf66fV5FLTtNf66/VpHzEikgZs+otO0z5W+rSKWnaX8r/VpHykhpEMWfWWmaU/14+qzKWmaT8s/VZ/ynyENIGLPrrTNJ+Wvqs/5So6VpHy39Un/KfISGgZbPsrSdH+XPqk/5SlpOjP8AX36nP+U+KkNIGbPtLSNF+Xvqc/5Slo+i/L/1Of8AKfESGkDNn3Fo+iftg+pT/lKWjaH+2H6lP+U+EkNIhmz7q0XQv2xfUan8pS0XQv2x/Uan8p8HAYBmz760TQf2x/Uan8pS0PQP2yfUKn8p1/HYaQJvHYFoW3/2y/UKn8pS0Lb37Z//AIfU/lOupDSJRneOxLQdu/tn/wDh9T+Ua0Dbv7af/h9T+U64ojwKM7xCiNRKwCRTNkqIJF4DlISyMBgvlDlBLIDBeAwCWdWKjKCpzThzSeOWWfwfXp5kgcj3wAAAFUpRhUTnDxI+cc4ySAAAAAAVVlGdRuEPDj5RznB22VJW9G3oLtSpQX0tc0vzyZ1A7pqH/wBvuMfg87x82en5iMGCKzhLqzvm1dsV7i4trK0oO41G5koRisZcn5JvsdJscfC7fm7eJHP4zYn2eZW64iR8fHiO1qqhn9n07f4vMbgrdHzO39ZPRaSeWCvdTdd9fLvPuWPsy6jWso1LrWre2umsujCi6kU/Ryyv9B5fvzh/fbSvpabq9GLU05Uq1OWY1I/sovuvmZuqeM+007f+h7R1Ll+F/CpOHrycj5vz8h5c8cVG0fjmwukuv1O0IYc7Uoy7klXC+FfOzTy9tZWV1Uoy6uL6P1XkzaT9Dl4I7K48cZde0LfWi/dzSrXQKt7Rt/hVe35ayuLeClzUZwk/i1JrDeOvbojWvc+Puksd/DWfzm5v6EP/AP3D7o//AMWr/wD4u0PXT4J0f0Jhk5wjJ9pphu2xoaZurWbO2h4dtb3tajShlvljGbSWX1fRLubV7/4CbE0T9Dy2LxNstC8He+pakre71T4ZXl4lPxrqOPCdR010pQWVFPp73n0fcfAX2LLncOqVr/jRuWhfVLqrO4pRrU8QqObcor/cL7PK7s7l7YOhbM2z+h07P0zh7rNzuDZ1vrlJafqV406taLqXTm5NQguk3Nfgrol37vDldHY/ObaXD3dW/wCtWpbY2zrG46tBJ1YaRYVbqVPPbmVOLxnD7nB3DtnWNpalLTtc0m+0XUIJSlaahbToVUn2bhNJ+XofpR7L+v8AH6+9nPbO3+EfDDQ9kWUW6lXduu3ScNSyvjV40HHn5pS687U48qSj0Sx2H289nanuT2KrTcHECW39V4g7fv6MZatt1ydvmdfwpwi5JSScZR5ovpzwyksJJv8AGgfmJuvh5urYcLGW5ts6xt2N/B1LSWrWFW1VxFYzKn4kVzpc0eqz+EvUK3DzdVvtChuyrtnWKe1q83Tpa5OwqqxqS5nDljX5eRvmjKOE+8Wu6N8/0T/QNQ3Lwy4Jbv0u1q323qWl1IVb6hFzp0nVpW06Tk12UlGWH2+KcXfum3ek/oRuyra+ta1ncLVpTdG4punNRlqF1KLw1nDjJNPzTT8y73BMGie09hbn39dVbbbG3NW3Hc0kpVKOk2NW6nBPs2qcW0vnOPuPamt7O1F2Gv6PqGh3yXM7XUrWdvVx68s0ng/Rr2S9wcd6/s5aNt/hDwu0XalGVaVWrvTXLteHqOc81WNGUeeUspJTxOCjHlS6LHePba2drW5PYav9Z4lT25rHEDbV5bzjqm3eZ0YOpd06MopySkm6dXEo4w5RTwsLDfp0D8xNn8JN88QrKvebV2XuHctpQqeDVuNH0qvd06c8J8spU4NJ4aeH1w0fR1vgBxP21pN1qmr8N93aVplrB1Li9vdCuqNGjHzlOcqaUV72zdT2UN/6zwL/AEObidvvQ61O01unuJfAa1WlGpHMvgNDPLJYf4dT8R3HZXHrePtCfoevGzXt631C/wBStKlxY0qlC2hQSpKjbzS5YJJvmqS6+8rk7FH5maJoOp7m1Klp2j6dd6rqFbpTtLGhKtVn80Ipt/Qj6m7eG27tg+D/AET7W1rbnjPFL7radWtfE8/i+JFZ+g/QPg/q9t7G/sA2/FXQNJsrzf27LmNJX13T51TjKtONODw0+SNOk5cqaTnLrnB9/wBjv2ltU9tuW9uE/F3TdN1yzuNKlqFC4t7VUZRhGpCnJYXRSjKrTlCaSacX1fTDffPsB+XR2Dc/DvdWyLTTbrcW2dY0C11KDqWNfVLCrbQuopRblSlOKU0lODzHP4S9UcXd+357T3ZrWh1KirVNMvq9lKoljndOpKDf08pv9+iL6Df7u9nDgBuzSLWrf6HZaW43N1bwc40fHtrWVNya/BT8Gay+mcLzNuVNA0M+97uqO0Fux7Z1j+hVz8Na58Aq/AXLm5OXx+XkzzfFxnv07nH2xtDXt7ag7Dbuiajr18o8zttMtKlzVx68sE3g3x1TTbvS/wBCItaV5a1rSrLVFVjCvTcJOEtSbjJJrs11T8zYrhzwc3fwh9k7Zuk8Grzae2t461bW2o6xru5JSi6kqlLxJ8iVKpzyTlGEedcsYJ9MvJhzoH5Ebq2RuLYt7Cz3JoGqbeu5x5o2+q2dS2qSXqozim0czTuGG8tY0K21uw2lrt9o1zX+C0NRttNrVLerWy14caii4ynlNcqeeh+rnErhxvHf3skb/wBG4465s7c259LtLjVNE1fQKmJxnRoupHmTpU1GblBwbhHEoTaa6dfMeAnHHUPZ7/Q0Vu/R7ahdazDVri0so3UXKlGpUueXnkk02ox5njPVpIb/AAB+eG7OGW8NhUqFXc21Nc27SrvFKeradWtY1HjOIupFZ6eh1+0tK9/dUra1o1Lm4qyUKdGjBynOT6JJLq2/RH6gex57S+r+20t88J+LFhpur2lzo872jc21qqMowVSFOWV1SnGVWnKEkk4uLfXpjifob/AmjtLavE7e1K10q/3zpWq3e3tIudXk4WtvOhTi5TcoqUoRnOpFSlFOXLBpd3lv1dg/PHcnCPfWzdMjqWv7L3DoenSaSu9S0qvb0nnt8ecEuvznX9J0m/17UKNhpllcajfVny0ra0pSq1aj9Ixim39B+0XCLR+PH9FN9a8Y95cN94bD1K2q0bnTbFtVaXNH4qhF20Izg/wZKpJ9G3nKw9E9kcYtc9j/ANoXiTsDh1pOgapLV9aWl6Vf6tSc5WilWxR/psWpThy1EnFvGYqXqpVTvgSjWHdfDndmw1Re5tr61t1Vnik9W0+ta+J0z8XxIrPTr0Pjadp13rGoWthYWta9vrqrGhb21tTdSrWqSajGEIrLlJtpJLq2z9huLGmcQ7X2LuKv39/uHuTVvglepp0dvWc6kbZ8iVCpP4iw4VXzc6WIxWXLvj8qeA2oUNL45cO7y6qRpW1vuPTq1WpJ4UYxuabbfzJFjK1YOvbq2br+xdVel7k0PUtvakoRquz1W0qW1bkfaXJNJ4eHh4OTuTh5urZunabf6/tnWNDsdTh4ljdalYVbeldRwpc1KU4pTWJReY56SXqbc/oquy9bo+0bYaz9zLmppmp6TbUbW6p0pShUqwlUjKmml+Guj5e+JL1O2/ok9rWsuAfs7W9xSnQuKOmTp1KVWLjOEla2icWn1TT6YZVO68SUaQbV4Wb033aVbrbW0Ne3DbUZONStpWmVrqEHjOHKnFpPHqfC1TSr7Q9QrWOo2dxp99Qly1ba6pSpVKb9JRkk0/nP1f4fa77Su4eGGztO4bcOdr8Hdt2FnFOpuK68V14rDU1SUHOlFrMpc8HKTk3zeb6f+iS8NFvLZHBzW76Gk/0c6nqVDQrzVNJy7as6tPL5W/jSpqpFuPN1Sk1nqyLJxplo/OraXDfd2/lWe2Nq63uNUXiq9J06tdeG+/xvDi8fSfM1zQNT2xqdbTtZ0270nUaOPEtL6hKjVhnquaEkmvpR+mXtee0pqfsQ0dkcJuE+madpNC30mF/XvLq2VWU4OpOnFY6JznKlUlOby25Lt1NZfan9sjQvaf4YbVs9U2UtP4g6ZNSuddt6kY0XDElOlCLUpunPMJ4lJcsl0z1bqk3xrgSjVgH2EmDZ1IZrLlldU4T/AAKmacv72XR/mZ1KrB0qs4S7xbi/oO002/Fhy/hZ6HX9Z5fuxfcv4Pjzx83MyoHGcouMUo4a7vPcQgKCslRlFRknHLfZ57EZAAoZOR5ALg0pJyjzL0zgRORgDAQwCptOTcY8q9M5EICgZTacYpRw13fqSBQMBAAWpJRacct9nnsIQFAyoSSknJcy9M4IDIAxiAAeRyacspcq9CcgAMYgyAU2nFJLD836iEAA8jTWGmsvyeexIwBgIACotJrKyvQWRZDIAwEABTab6LC9BABQGRtrCWMPzfqLIZFgYCyGQCk0k8rL9RZFkMlA8jTSfVZROQyAPIZFkMksDyDeX0WELIZFgYCyGS2B5WOwgyGSWAHlYfQQAAAgAGn1DIshkgHkBAANv6BAIAeQ8hAAMQAAHkAgyAME+ogAABZAAYN9fQ+nom1da3LOUdJ0m91NxaUvglvOoov3uKePpOPq+kXug6jWsNRtalneUcKpQrR5ZRyk1lfM0LrgDhgA0gQEs4KSBIaIZbBIpIEhophsENdQSKSBzbCK7eY0CQ0gZsSRSQ0hpAxYsdfQaQ0hpEM2JIryQJDUSmbEkNIpIEiGbEl0HgaQ0gZslIpLGPMeBpAxZKQYLwCQM2SkPHXsVgaQJZCQYLSBRISycdEGC+UMAlkYBR9xeAwQlkcocuC8BgEs6gAFRjB05tz5ZLHLHH4Xr18jkfRkgAAABVKMZ1Epz8OPnLGcEgAAAAB3CpUVxSt7iPatSjL6V8WX54s6jVjGFRqE/Ej5SxjJ93b1z8Jt52T61IZqUfVr9VH/AFr5n6kBzo9MHe9rblrUK9td2td2+o20lOMo91JdpL1R0NdioylCSlFuMl2aeGgnR4mp00dTDckbVWPtNajRso07rRbe5uksOtCs6cW/Vxw/9J5dvzf99uzUJanq9aK5Y8lKjTWIwjnPLFfT3fU8zjrl9GOFcSx70mzi17ircz5qtSVSXrJ5OjyOSpnzGi6MaLQ5nmw41FvtVvyvl7Cry6leXVStLvJ5x6LyRuF+hbb721w+47bj1DdO4tK21YVdt1qFO61e9pWlKdR3VtJQUqkknLEZPHfEX6Gm4HBq1R9ikopJH2d6V6V1vHXq9CpCtRqX9ecKlOSlGUXUk0013TXmbkcSuIe1b/8AQxeHm1bbc2j3G57XVVUuNFpX9KV7Rj494+adFS54rEovLXaS9UaPAGrKfp1xN1XhX7YfBHhvGnxz0vhZR0Kyjb6lt3UK9OHNLw6cJR8CVWm5uDptQkuaLjJ4xlnw+OW/+DWn+wDrHDvhvvCz1NaRqVva0aN5d04X2oTV1Tq1rmFBtVHTcpzxLlSxB4+Kk3+cIGdwtmzHBX9EL4ucD9qWu2tNutL17RLOHh2dtrtrOs7aHlCE6c4T5V5KTaXZYSwe8+0L7TFlx1/Q99Hudf3Pt+txDvdXVW80OxuqULmlCF3XjB/BudzjHwlTeWuqaeep+dwFcVdg/TPdet8MPa39mzhlpEON2l8Jqm3LKnaapoV/Xp041XGjTpSToyq0nUUfDbhJNx5akk0m+nzuKm+uC2g/ofe9+G3Dvelnq1bS7+1toRvrqnSvdVrfDLWvWuKNBtTnS+PKKko4xSlhtR5n+boE3Qb/AHtP65sHgR7GGg8Etpb403fOtX+pK+vrvTqlOS8LxJVnOcac5qn8bwYxi5NtRbPgezjxC2rof6Htxp25qW5tH0/cOoX1zOz0m6v6VK7uYu3tUnTpSkpzTcZLon1i/Q0gAu7wFm+Xsy8c+F3Ff2Z7jgBxe1mW1qdrVlV0jXak1Gmk6rqx/pjTjCcJymvj4jKEsZTO+7E1/gB7AG29z7j2txCtuKW+9Vtfgllb2FalVjGOeZQbouUacHJQlOUpZaglFZ6P80ALuJg5Op6jc6xqV3f3lV17u6qzr1qsu85yblJv522bE8Df0QDizwF2vQ23pN1pmuaFapq1stdtpVlbJttxhOE4T5cvpFyaXkka2gWlyZD9GONftRWnHb9D0u625tz7dfEG91OnKroVldUqdzCnC9+Li253US8OKeXnp1ycXY3Frg97Xvs47X4Z8Vt2LYO7tqRpUrLWLmpGnSrwpw8OM1Un8R5p8qnCTi3KKkmz88QJuLsKbqcbtm+zDwP4J3+29B1ilxY4k305TtNbsbt+HZN4jzSlRn4XJFJtU25uUnl4j29y9mvbGxd5fobEtI4i6wtvbZudTrwnq2cfBKzvEqNTOGl/THFPPTDeWk8n5cm4Nhx82JQ/Q4tS4XT13l31W1JXENK+B1+sPh1OrnxfD8L8CLeOfPTHfoSUXSB7fw21bgR7Aez91bm0DiZp/FPfeq2jtbChpk6c0lnmhTcaU5qnFy5JTlOfVQXKs9H4/wCxP7Ue0tu6JvvhlxbrVY7R3tUrXFbVFFtUbitT8Os6nKm4qcVBqaXxZQWVh5WmGRp5Lud4P0J0zgN7IvBClqu59zcUbXihYStp0rPb1ldU6tdyl26W8+Zz6YUm6cY5bfk15B7OekezVxHhvTR+IVTUNiavqV3OWgahUvZytLC2cuanTU2mvEjjEpVsxlHs4vJqsBd3xB+mmlbl4LexR7P/ABC0fQOKtrxQ1jdVrOha6bYXNK4pwm6U6cc06U5xpR/pjlOUmnJRikm0k/zLTcWmnhrs0AFit0j4m22yv0T7jXs7bFHRqlxom4HRpKlS1DWLKdS6jFLCzOFSCm0sfGnGTfdtvqepe3fx22zvnaXs+a7b6/om7NU0+a1HWtP0y9o1pU6jp2s506tOEn4fNKM44kl2a8j89wyNxXaJbP1B9pXSuDntbartze1x7RmnbY2zSsIU7jbdetCVxFqUpuUbd1YyhVfNytunL8COMpJHSPbY4w8Odc9mHhNY8LtyWdWGg6vSjZaerynLULajb0atKlVq0cucMuEZZnFN8yyk3g/PfIEUKriW7P0r3vr3Ab2/do7W3FuziHZ8Ld/aVa/BL6jfV6VKElnmlFeM4xqQ5uaUHGWUptSWei1+9rmj7PmzNn7a2XwooUtzbosWnqe8KVzUlCpDDbh0kqVScpST5oxahGKinlvGqoGlCu0lgAAdCHIsOVXVOdT/AHunmpP+9iuZ/mR1GrUdarOpLvKTk/pOwavc/ANP8NPFe6X0xp56v6X0+ZP1OuBAYDaioxallvusdhGgMMiKSi4yblhrssdwAyAgyAVkeRQUXJKUuVeuMiAKyMnI8gDGKSUZNRlzL1xgMgDARTSUU85fmsdgBZGLIFAwyNJOLbeGuy9RZAAYhwSckpPlXrgoABZAoHkYhySUsJ8y9cAAGRAAPIDeFFNPLfdeggBgIaw023h+S9QAAWQyAMAjhtZeF6iAGMQADAHhPo8r1EAMBDaSSecvzQAZDIgAHkMgsYfXr6eogB5AQ1hvq8L1ADIZEAA8hkQ3hPo8r1ADIZEAA8gHkuogBgIOmH1AGIAAAAXz4EAMBZDIAwE+j6AAB27hVsiHEPe1lo1avK1tZqdWvVgsyjThHmePe8Y+k6idh2DvS62Buqx1u0hGtOg2p0Z9I1INYlFv3p9yozK64Hp+g6Fw44l6vd7X0PQ9Q0TUlSqOx1Speyq/CJwTf9MpvKinj9T+Y+Dw70Db9nsjd+v7i0Ja5U0utb0KNvK7q265pScZfGg17u6fY+jbcT9ibQur7XNp6DqtHcdzTnCktQqwla2bn+E6ai+aXfpzfmPp0r3ZO3ODml6XrVzrNWtuGr90rqeleBOcZwfKoS55LlXZ4w336nHil5L23x9xvg3XZb8q+pi1XZu09TveF13YaAtKtNwV5RvLNXlaqpRVSMcc8pZXTPVY7mLROC1etxtnp13tXU1tFX1aCnOhXjR8FKXJ/Tu+OkevN19T7Gq7o2jb7N4f69pVbU5Wm29W+DfBrxUVc1Kb/pk5csZY8kk8pdzrGlcer614ry1261bXa22XeVay034TKWKUlLlj4bnydMrpnCwaX4qXfL5Ne4y73fYvPjZihw4stU4f6tcabpsq+urcv3MtHCpNvwmukMZx9LWfedo1rg/tjQfve2cYrUrm91V2Wq3MK1RRrSTipwjhpJRbccxw+nc67t7jjQ2psjcunada11rOpajVurW6qQhyW8Jrlcs5yppZSwsde5wdF4p6XYaHsKzr0b2dfQdUqX13OMItVISmpYg3LLl8+PnJG+H/AMfgr+d95Z9tf93zr5UcrfPBSpYcX7bbmkrGl6nU8W1q8zlGlRy/EzJ5/AxLOXnovU+Rx52jpGyd+y0zRKHgWCtKNRJ1JVOZyXWWZN9/xHYr3j9SnoO6LO3tKzvby6ry0u9qxjz2tvXlmtBvLw3hYxnu+vQ6Zxa3rY783TS1LT6VxRoRs6Fu43MYxlzQjhv4smsfSYjvVFP9cPlw9pt1vN/rmvj7j2vc15tvYm3NpaDfbl13Qbatp1KvK129GNOUpzWZV69TvJN9OVfsfxdDt+FFOz466Tt/V7ievaXf4uo3M5zhK4oOEpJyaeU/i46PyOPR4jbJ3fpGi098aTq89T0mhG0p3WkVKfLc0o/gxqKbWMeq6+9dl9HTeNuj1N+6huvULC7hcWll8D0OxtuV06UeVxXiSbT6J5yvV+iNO1Jy58/Ls9vL3+By/k3fBL28L+ZnlpexN1bL31daVs37iXuhU4uhc/dSvcc7dRxzyyaS6R889zj6jt7YnC3S9Dt9x6Je7l1nU7SF7XlTvJW9O1hPsoKP4TWH39O6OobN3zZbf2dvTSrulcVLvW6FKnQnSjFwjKMm25tyTXfyTOx0+I+zd4aLpFHe+k6rW1PSqKtqV3pNWCVxSj+DGopNY+ddfmFNcPVfvv30VtP317q+Z2bS+CWh/wBH13Y0qFbVdIvtvz1XS4Vqko1YzfLyJ8jWWm+3bqsnX9c4c6Lt5aDsvwYXe+dTr0neXrqz8OwjNrFOMVJRlLHVtp/nWM1jx1tam9NS1a7sa9pp70appOnWdniTt49OTmblH0bbX4j5mocV7LcOhaRe6lRuqe+dFqQdpqtGnCVO5pwacY18yTyvVJ/nZVzV8uHrq38qs5t8H3/Ol7rujstXQ+F9nvSOxZ6LqdW58dWU9f8AhrU1XeFlUvweXmeM4+ge0+BNnquj7+0uulU3BpN0qFhc+JKKm0nJR5c4fOkl1TaycOXFHh/c7hjvCvtvVf6KlJV3aQrw+AyuF/5TP4fdZxjB8jSeMtW00LdE6zrrcWqanb6jRr0oR8KEqc+Zp5lleiWGZqVU+fb5rivZZlySdrl2eT5+4+lwd4SWe49s7n13XbdzoWlrWp2dGVSVNyrwg5Sn0ab5eix2y+vY832htK/3vr1vpGmRpyvK6k4+NNQjiMW3lv3I9cu/aB0u9168qx025stJno9xaUbW3pwyrqviVSpJcyWHLz74XbyPDEjStyt931/1Obrd4d/0/XrPtbZ2tX3Fu6w0GM40q9zdK2c85UfjYb6d8dT1DVYcJNG1y+2zd6PqtFWjnby1+N1KdR1Y9G/B/Bxlen0Hk23taudt63Y6pZyUbq0rRrU3JZWU84fuPVL7iFw21DU7vcVbauo3Gv3MZTnYV6sHYeNJdZ9+d9euMfQiyvdXt+VfMwmrfsr5/I6dwr2/pu5OJejaVfU3e6ZcXEoTg5SpupHlbXWLTXZdmenbY07h5u3d2s7dpbC+AVLOjcyjefdi4qZdLKT5Mrv37/jPKuHG6bXaO/tK1y9o1JWtrWdWdK1inLDTWIptLz82fc2LxD03bPELWdduqF1UtL2ldQpwowi6idV/FynJLp59X9JJpuNLufn2EUkpX4ryvidq2FwjtpbAtNy3G2LzeN7f1pQoadb3Tt6VGlFtc85x+M22nhH1p8E9GtuIOzPhGlXNlpGuRrfCNGu67dS2qQg24+JFptdmnnPTr3wdG0Df+3tS2XabW3hY6jWsrCtKtZX2kzgq9Pm6yg41PitNs7Hww1jb2p8adqUtuaNPS7G2jUpupcVXOvcvwpfHqYfKn7l//Gqbn4fKv1434HNySj+ud/r/AFDb+g8PeIetXm1dI0K90fUI06zstWnfSqutOCbSnTa5Yp4fb8Zm2PweoUti2+4bzbF5vC/va86dLTre6dvSo04txc5yj8ZttPCOJDiBsrYus6vq23NI1b+iWp41GlG+q05WlrKTalKHL8aXnhSPi6FxA0DVdm2m2d5WWo17Syrzr2l9pU4KvT5nmUGp/FabbeTmrcbXcvjxr2f5GpOKlT738O32ncb3gxpFjv7ZDraXc2Ok67KcbjRrus3Ut5wjlx8SLTafRp5z0+g4mj6Dw53rum72dpuhX2l3rlWp2msyvpVHUqQTa5qbXKovlfbr8xwuH+r7e1PjLtCltzRp6XY21R03UuKrnXuXyy+PUw+VP3L/APjmXO/NkbF3drWs6Lo+rS3PGrXpUqd3VpuzoVG3GU4Y+O/Po/X8VfJJ/wDd/l+vMxfNrw+d/ryOHa8FbncPC7TLvRNKjc7gWo16F3Vd3GnmEG0klUmo90uyyfM03hvDTdhb6q69pdS217SJ2saLqzlF0ueWJNJPlkmvPqvQ5Omb62fq3DzTtv7nWvK6tb2reOtplOi1Nzb85y9/ofR3dxt0zc2i7ssY2N3b/dClaW9jzcssQotturLmzzPPkmJb3GvD5cveZThafr+LO0U+G23qFXaFnR4cXmtUdUsrerd6tQvLqMKE5rEm8NwWPwsNo6Zt7Yu3qe+t0actJ1bd9LTqrp2VpYPEKnxsN1a0fwcdsrvh/Mfdnxi2rfW23ZVtR3nptxpdnRt50NLnRp0KsoJZbTqdcvp27HDfGrQtdr7tttW07UtN07XLinXVXR6kFcR5IqOJ82FJSxl/O/nK73nXj8VXuswnFxV+Hw4+85u7uEmj2T2fqcdCudvQ1HVadjeaNcXfjpRcu8aifMspNd8/Ng+DxH4MT0rinZ6HodP/ALm6rUTtHzOapJPFSLk238Rp5z1xgz3fFHa1roO2tH0fTtTt7TR9Zhfudz4c6lamuspNqSXO238VJLCXU5V5x7ou03XTt7OtK4vLmrV0i6rRip2ca3SqniT5W12xnq2TiuK7L9vLh537yNxap9tezn/kfa1HhPtWz4qy0SlY+NpkdvyvEncVPj1kniplSz1xnC6e4+DtnhHpttwx17Wdcg563LT3e2No5yi6FJPEaskmsuT7J9ML8XI03jZodlxD0/X52N9Ws7fRI6bOi6dPmnUSw+nPjkfr39x1+y4s/C574udYjXq3mvWXwW3VCMXTo4fxYvMliKWF0yZalTS7n8ZV58PYFKFpvvXwjflx9vtPM8BgtRBI6njWQojUS8dEGASyOUMF8oKJCWTgMFYDAFnSgADkfTgAAAAAAAAAAAVTqTo1I1IScJxalGUXhp+pIAHa7G+p60viJQvcZnRXTxPWUP8AXH8XupvDw+51JNxaabTXVNeR9q23LNxUb2l8LS6KqpctRfO8Pm+lZ95KB9LIZMUNT06qsq6nR/ua1J9PpjktXVg/1zoL/wBnV+wQFZDIvhVh8p2/5Or9gPhVh8p2/wCTq/YAHkMi+FWHynb/AJOr9gPhVh8p2/5Or9gAeQyL4VYfKdv+Tq/YD4VYfKdv+Tq/YAHkMi+FWHynb/k6v2A+FWHynb/k6v2AB5DIvhVh8p2/5Or9gPhVh8p2/wCTq/YAHkMi+FWHynb/AJOr9gPhVh8p2/5Or9gAeQyL4VYfKdv+Tq/YD4VYfKdv+Tq/YAHkeSfhVh8p2/5Or9gFc2Hypb/k6v2CgoBfCdP+VLf8nV+wHwnT/lO3/J1fsADAXwnT/lO3/J1fsD+E6f8AKdv+Tq/YAAA+E6f8p2/5Or9gPhFh8p2/5Or9goGngeSfhFh8p2/5Or9gPhGn/Klv+Tq/YAKAXwjT/lO3/J1fsD+Eaf8AKdv+Tq/YAAA+Eaf8p2/5Or9gPhGn/Kdv+Tq/YAAeRfCNP+U7f8nV+wHwiw+U7f8AJ1fsFIVljyR8IsPlO3/J1fsEyvtNprMr11MeVKlJt/8AOwAZSritR0umqt0uabWadt+qn736R/0+XqvnV9yRpJqxoeFL+31mpyXzLGF+d+8+LVqzr1JVKk5VKknmUpPLfzspDJd3dW9uJ160uepN5b/1L3GIQygYCAAYxAUDAQygYZEABWQyIMgFZDJOR5AKyBOR5AKyAshkAoMk5HkAYCGAPICyBQMMiAAYxZAoGAgAGAsgUDyPIgAGAgAGAgAHkMiDIA8hkWQyAPIBkAAAAAAAAAAAAAAAAAADIAZDIZFkAeQyLIADAQADAQADyLIAAACAAYCAgAAAAAFkCWBiyAZAAEA0gQaRSQJYGkDDY0NIEhoGGwRSQJDSKc2xpDSBIpAwCRSQJDSBlsEikgSGkDDYJFJAkNIHNsEj6e3dwahtXWLfVNKuPgt/btunV5Iz5cpp9JJp9G+6PnJDSBhsuvWnc16laq+apUk5yljGW3lslIaQ0glRlu+JztB1y+2zq9tqmm1/g19bS56VXkjPleMdpJp9/NGC8u62oXde6uJ+JXrzlUqTwlzSby3hdF1MKRSQ5mbEkCRSQ8AxYkhpDSGkDLZKQ1EpIaQM2SkPBSiCQM2SkNIrAYBLJSHgrlBIEsnAYLwGAZsjlDlLwGCCzohUaU505zSzGGOZ57Z7EgcT60AAACqVKVeooQXNJ9kSAAAAAAVVpSoVHCa5ZLuiQAACpUpQpwm1iM88r9cEgAAAABUaUpwnNLMYY5n6ZJAAAKpUpVqihBZk+yJAAAAAAKq0pUZuE1iS7okAAAAAKlSlGEJtYjLOH64JAAAKjTlKEppZjHGX6ZJAAAAACqdOVWahBZk+yEIABgIYBdSnKlNwksSXkSIACinTlGEZNYjLsyAAGAAAXGnKUJSS+LHGX6EiGUgyqcJVJqMVmT7IgCkGMQZKBlThKlNxksSXkQMAYCAAtwlGMZNfFl2YhAAMpQlKMpJdI4yyBgDAQAFwg6klGKy35EgBQMBAAXOLpycZLDXkIQFA8lOLUYya6PsQABWQEGQC1FuLa7LuGSchkArJUIuclGKyzGPIBWQJyPIAypRcJYfcjIZAKyAsgAU4tJN9n2EIYAZKSbTfku5IZKBgIACoxc5JLqxCAAeQFkMlsFNOLw+jEGQyLAxtNJPyZIADAQAFJNpvyXcQgKBgk5PC7iAgGAgAGDTi8PoxALAwEAsDxhJgIAAHjo36CyGRYABZDJANdWAgFgYCAAb6MWQyGQAH5CEQDDIshkAfvELIZAGC6vp3ENIEGkWiUikDLY0isYYkUinNsaGugl0KSBzbGl2KSwJFJAw2CRaXTIkikgYbBLJSQJDQMNjisjQJZGimGwSKQJFJA5tgo4GkNIaQMNgkNR7DSGkDLYJDSGkNIGGxKOUNIaGkDLYkNRbfQpIaQMWJIaQ0hpFM2SkPlaeGUkNIhmyVEEikh4KZsnl6IMFBghLFgFHoVgFEEsnGAL5Q5QSzz4AA4H2YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADAQADGIABgIYAwEMABiAoGAhlM0MMiAAYxBkoGAhgDAQADAQwBgIAB5GIABgIMgDGIC2BgLIFA8jEAA8hkQAFZDJORgDHknIZAKyPJOQyAVkMk5HkAeR5JyGQCsgTkeQBgLIZAKDJOQyAVkMiyGQBgLIZAGAsgAMBAAMBBkAYCAAYCAAYCyGQBgLIZAHkMiyGQB5AnIZAKELIZAGGRZFkArIsiyGQB5DIsiyAVkWRZDIA8hknI0AUikJdCkDLGi0iV0KQObY0UJDQObGkWkJIaBhjSKSCKKQMNgkUkJIpFObY0NIEikDm2CKSBIpIGGwSKSEkUkU5tgkUkCQ0gZbGkNIEikDDYIaQJFJAw2JIpIEhpFMWJIpIaQ0DLYkhpDSGgYsSQ0hpDUQZsnA1EpIYM2SojSKwCiQlk4AtRHgpmzHgeC8BghLPOCo1ZwpzgniM8cyx3x2JA4H3IAAAFUqsqFRTg+WS7MkAAAAAAqrVlXqOc3zSfdkgAAFSqynThBvMYZ5V6ZJAAAAACo1ZQhOCeIzxzL1wSAAAVSqyo1FODxJdmSAAAAAAVVqyrTc5vMn3ZIAAAAAVKrKUIQbzGOcL0ySAAAVGpKMJQTxGWMr1wSAAAAAFU6kqU1ODxJdmSAAAAAAVUqSqzcpPMn3ZIAABTqSlCMW/ix7L0JAAYCGAVGpKMJRTxGWMr5hCAAZVOpKlNSi8NeZAwBgIABlzqSqTcpPMn5kAUDAQymSnOUoxi38WPZCEAAyo1JRjKKfSWMokCgYCyABcJunJSi8NCEAAwEABc5upJyk8tiEAAynNuMYt9F2IAAY8iDIBSm1FxT6PuIQADyVCbhJSj0aIyPJbAwEAAxyk5yy+rZOQKB5HkQAFObcUm+i7CyIAB5GptJryfckACshknI8gFRm4tNPDFkQAFZDJOQyAW5OTy3liyTkMgFZHzNpLyXYjI8gDyPJOQyAWpNJryfcWSchkArIKTi8ruTkMgFZDJOQyAVkHJyeX3JyGQCsiyLIZAK5nhL0FkWRZAKyPmwmiMhkArIZJyGQCk8MWRZAAeQyLIsgFN5FkWQAHkM9BAAMWQAAaKiiUsFgjGi49H7yUikDmyl0GkJFdgc2NFrv7yYooGGNFxRKRaBzbGn0SGhJFoGGwRURIpA5tjXkUkJIpFObY49PnKSEikgc2xpFISKSBhsa6v3lJYEkUkDDYJFLrgEhophsEhpDSGkUw2NdsDQJDSwDDYJDXRrAJFKIMNiSKURpDSBlsSQ+rY1EpIGLJURqJSBIGbF6AUolKIM2RgaTwUkPAJZCiPlLwHKCWeYgBUZQVOacOaTxyyz+D69PM8c++JAAAACqUowqJzh4kfOOcZJAAAAAAKqyjOo3CHhx8o5zgkAAAqUounBKHLJZ5pZ/CAJAAAACoyioTThmTxyyz2JAAAKpSjConOHiR845xkAkAAAAAqrKMptwhyR8o5zgAkAAAAKlKLhBKGJLOZZ7kgAAFRlFQknHMnjEs9gCQAAAAqnKMZpzjzx845xkkAAAAAAqpKMptxjyR8o5ySAAAVKUXCKUcSWcyz3AJAAAAY4yioSTjmTxiWexIAwEVTlGMk5R54+mcACGIABhkRc5RlJuMeSPks5wAIBAAMBuScYpRw13ee4gBgIpSioyTjlvGHnsWyUIYgKQYDg4xknKPMvTOCQBjEBQMBzkpSbjHlXpnJIAxiG2nFJLDXd57gAAgAGA00otOOW+zz2EAMMiHCSUk5R5l6ZwAACAAeR5EOTTllLlXpkAAEAAwyDa5UksNd3nuIAYANNYeVl+T9C2AAQADAItJptZXpkQsDAQCwMAk030WF6CFgYZENtYXTD82UBkMiAAeQyCaw8rL9fQAB5AQJpPqsgDyGRAAGQyANrPRYQAZDIgAHkAysdhADAQ8rD6EAAIC2BgJPDAlgYCAWAAG+oEsAAh57CwAIRUQColIS6IpAwyl0GhFRKc2UhoSKiimGUhoRa7g5tjRSEVFA5sqKGg8l6jigc2xpYKQkVHsDmxopCKigc2xxRSBdBpFMMcUUkCWEUkDDBIpIBpAw2NFJCSwWuyKc2wSGkCQwc2xjSyEV07FJYBhsEhpAlkuK6lMNiSKSBDSBhsENIaiV59AZbJURpFYGogw2SkNRLS6LoNIGbJURqJSQ0gZsjA8FqI1EEs8pAAPHP0QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABgIABjJHkAYCAAYxAAMBAAMYgAGAgLZKGMQFIMBAAMMgBQMBAAMMiDIAxiyAAwEGQBgLIADDIhgDAQADDIgAHkMiAAeQEGQBgAAAMQADAQADAQADAQADAQADAQADAQADEAAAAAAAZFkMgDyGRAAPICAAYCAAYgEAUu5SJiUgRlIuJKLQMMfdlImJYObGi0TEopzY0ZETEoHNsaLSJSKKc2NdS0SikDk2NItCihoHNlRRa6ExRSBhjRaRMUWgYGikKI0U5saLSFFFIHNsaKSEkMHNsaKSFFFroUw2C6FJCSLSBzbBIaBIpIphsEikhpDSBhsSRSiNIpIGGxJDSKSGogxYkhqJSWBpAzYlEMFKJSiUzZGB4L5R4BLPIioxg6c258sljljj8L16+RIHjH6SAAABVKMZ1Epz8OPnLGcEgAAAAAFVYxhUahPxI+UsYySAAAVKMVTg1Pmk880cfgkgAAAABUYxcJtzxJY5Y47kgAAFUoxnUSnPw4+csZwSAAAAAAVVjGM2oT54+UsYySAAAAAFSjFQg1PMnnMcdiQAACoxi4SbliSxiOO5IAAAAAVTjGU0py5I+csZwSAAAAAAVUjGM2oy54+UsYJAAAKlGKhFqWZPOY47EgAAAABUYxcJNyxJYxHHckAAAdNRlNKUuSPrjIgAAAAACqijGbUZc8fXGCQAAAAApqKjFqWW+6x2EIABlRUXGTcsNYwsdyAAGMQAFQSlJKUuVeuMiEAAxiAAqaUZNRlzL1xgQgAGU0lFNSy33WOxIZAGAgLZKKSXK23hrssdxCDIsUMqCTklJ8q9cZJyBSDyAgAGOSSlhPmXqSAA8jyICgppKKaeX5r0ELIADGsYfXD8l6kgAPIZFkMgFRw2k3yr1ELI8gAMQAFPCfR5XqIQADG8YXXr5r0JAAYCAApYw8vD8kIQADGsN4bwiQAGAgAGN4T6PKJAAYCAAfTHcBAAMOmH1EAAxAAA139BBkMgBkMiyGQBvGQEAAw9BAu4BaKRKKQMsyR7DJRSBhloqPVkroUgcmUikSVEHNlrsUl19USiog5stdBruJFRKc2UsYXUqJKKiinJlIqKJRcQc2UikiV3LigYZUff0GlklFxQMNlIaQi0Dmx9n0KRKLRTk2NFJdiUWkDmxroUkJIuKKYbHFdBpAioopzbGkUl19ASKSBhsEikgSKSBzbBIpR6gkUkDDYJDSyNIpRKYbEo9ilEaQ0gZsWBpFKJSRTNkKI1ErA8AzZ44AFRpTnTnNLMYY5nntnseKfpxIAAAAVSpSr1FCC5pPsiQAAAAACqtKVCo4TXLJd0SAAAVKlKFOE2sRnnlfrgAkAAAAKjSlOE5pZjDHM/TJIAABVKlKtUUILMn2QBIAAAABVWlKjNwmsSXdAEgAAABUqUowhNrEZZw/XBIAABUacpQlNLMY4y/TIBIAAAAVTpyqzUILMn2RIAAAAABVSnKlNxksSXdEgAAFSpyjCMmviyzhgEgAAABUacpQlJL4scZZIAAA6dOVWajFZk/IAQAAAAA6lOVKbjJYkvIAQAAAANwlGMZNdJdmIAAAahKUZSS6R7sAQAAADCEJVJKMVlsQA8gLIADAc4OnJxksNCAGAsjcWoxk10fYAAEABQAotxckuke4gB5AQ4Rc5KMVlsAAEAA8hkByi4Sw1hoAAFkC2ShgDi1FN9n2ELFDAQ0m02uy7lsUAycjBBgEYuTSSyxADyAgAGANOLw+jEAMBDaaSfk+xQACAAYAk2m/JdxADDIhpOTSXcAAEAAwENpxeH3AABAAMAxhZ9REAwEPGU36AAGRAAPICSyAAxAGQAAH0YhYoY0SUlhEsFopEItFMstFIiPUtFOTKRaIRcVlg5spFxIRaBzZSLiQi0sA5MpdSkSikDmyolroTFYwUinNjiWiYlJFObKiWuxMSgYZUS0TFZawUgc2VEpCihoHNsqKKBLHcaKcmVFFCSKS7MHNlRRSQkikinNjSLSwEV0yNIphsaRaQki4rPzg5NgkUkEUUkDDYJFJAkXjBTm2CQ0sgkWkDLYlEtLAYwkUkUw2JIaiNIpRbKYbJSHgpRKUQZs/9k=",
    "week": "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MYtdUunM0dt3Jqd3rHswabeX1zVvLurrUpVK1ebnOTzU7tmXgzreoavw74kQvbytdU7XRo0aEKs240oKnVSjFdkunkfEVa/X06Su7NVO9Rc3Z4c43ojhx8e3L2VNixVeooxOKo7+3jz8nhCPRdh8CNz8QdGnqtirSz0/r4de9quKqtPD5VGMn0a7tJHX9uWW1q+29craxf3ltrVKCem0KEc060sPKm+R46480eoey5reoXe7bjTq15WqWFrpdd0baU34dNupBtqPbLbfU9ltXV37Glu3NNwmjnNUTiYxnh392fW9fprVu5dopu8YqnHCePPHF53w74Y6pxKv761025srWVnS8arUvakoQ5c46OMZfnPp724L6nsXQ3ql3rOiXtJVI0/CsLqVSpl+eHBdOnqfS4K7x27taO7LbcVzc2tDU7N20JWtNzm18bmS6NJ9VhtY9Tla9w12lrnD6/3Rsq/1Kf3NnFXllqahzRi8LKcUuvXPdrv2weFe1mota3cuTNNrNMRO5mJzHpZ4ceDVFi1XandjNfHhnE8PDt73kfoP0F6D9D6GXopMfmIfmc5cqjXcaEu40cpcKjQxIZzlyqPyGLyPtbP27U3VuOy02DcY1Z5qzX6SmuspfiT+nBwuV026Zrq5Q500zXVFNPOXz7nT7qzpUKlxbVqFOvHnpTq03FVI+sW11XvR9Gjs3cFzRp1qWh6lVo1IqcKkLSo4yi1lNNLqmjsm/I/zz295uG1rQhpVldQ0q0tkn0pxhmMl7n1f0nY5axo27LzStOsNzavp17O0o2tGNGMoW0akY4UZdU22/NLB6ivV3IopqinvzwmcdvY8qNLRNdVM1d2OMRnzeQruV5n39raFTr76sNI1GkqkPhit69JSaziWJLKafl5HaaXDGk+Jn3Mk86Gv92eNzPDt2+kc9883xPXJ1u6u1amaap7M+z6vBo0t27EVUx249v0ebruNHpF3sO1vbfcFDTLJyvqOuKxtEqknyU/jdHl4aWMtvLwu59NbC29T3Fsyyow+H216riF3W8SaVxKnlZWH0XMnjGOmO54tWvtR39vujP8Ap4tfu+9M847PfO78efg8miB6NpvC6+06w3Fd63pU6NC3sKtS1nKqvi1U1yv4suvTPfoecna3ft3pmLc5w9df09yxEdZGMqXY809pCCnwY3BlJuLt2vd/uimelrse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",
}
try:
    import base64 as _b64
    os.makedirs("/opt/fo/meet", exist_ok=True)
    os.chmod("/opt/fo/meet", 0o755)
    for _k, _v in _MEET_IMG.items():
        _fp = "/opt/fo/meet/meet_%s.jpg" % _k
        open(_fp, "wb").write(_b64.b64decode(_v))
        os.chmod(_fp, 0o644)
    p("картинки карточек:", ", ".join("%s (%d КБ)" % (k, len(v) * 3 // 4 // 1024) for k, v in sorted(_MEET_IMG.items())))
except Exception as _e:
    p("картинки карточек: ошибка", str(_e)[:200])

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
