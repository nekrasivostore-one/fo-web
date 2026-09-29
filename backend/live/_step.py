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
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "getMe", {}, None, 8)
    me = (res.get("result") or {}) if res.get("ok") else {}
    _FO_MT_ME.update({"t": _fo_time.time(), "tok": tok, "v": me.get("username") or "", "id": me.get("id")})
    return _FO_MT_ME["v"]


_FO_MT_CM = {}


_FO_MT_BG = set()


def _fo_mt_chatstate_fast(chat_id):
    """Для страницы: только кэш; устарел или нет — обновляем в фоне, Telegram не ждём."""
    if not chat_id:
        return {"in": False, "pin": False, "why": ""}
    hit = _FO_MT_CM.get(str(chat_id))
    if (not hit or _fo_time.time() - hit["t"] >= 600) and str(chat_id) not in _FO_MT_BG:
        _FO_MT_BG.add(str(chat_id))

        async def _bg():
            try:
                await _fo_mt_chatstate(chat_id)
            except Exception:
                pass
            finally:
                _FO_MT_BG.discard(str(chat_id))
        try:
            _fo_aio.get_running_loop().create_task(_bg())
        except Exception:
            _FO_MT_BG.discard(str(chat_id))
    return hit["v"] if hit else {"in": None, "pin": None, "why": "проверяю"}


async def _fo_mt_chatstate(chat_id):
    """Есть ли бот планёрок в чате клиента и может ли закреплять (кэш 10 минут)."""
    if not _fo_mt_tok() or not chat_id:
        return {"in": False, "pin": False, "why": "нет бота планёрок"}
    await _fo_mt_botname()
    bid = _FO_MT_ME.get("id")
    hit = _FO_MT_CM.get(str(chat_id))
    if hit and _fo_time.time() - hit["t"] < 600:
        return hit["v"]
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "getChatMember", {"chat_id": str(chat_id), "user_id": str(bid)}, None, 8)
    r = res.get("result") or {}
    st = r.get("status") or ""
    v = {"in": st in ("administrator", "member", "creator", "restricted"),
         "pin": st == "creator" or (st == "administrator" and bool(r.get("can_pin_messages", True))),
         "why": "" if res.get("ok") else str(res.get("description") or "")[:120]}
    _FO_MT_CM[str(chat_id)] = {"t": _fo_time.time(), "v": v}
    return v


def _fo_tg_api_sync(method, params, tok=None, timeout=20):
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
                            data=_fo_up.urlencode(data).encode(), timeout=timeout) as r:
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
    sent, err = await _fo_mt_card(c, org_id, client_id, "agreed", _fo_mt_parts("agreed", cab, items, names),
                                  reply_to=reply_to, test=test, pin=True)
    pin = (sent or {}).get("pin") or ""
    await c.execute(
        "UPDATE fo_meet SET slots=$3::jsonb, offer=NULL, status='agreed', agreed_at=now(), pin_msg_id=$4, pinned=$5, "
        "tg_chat_id=coalesce($6, tg_chat_id), attn=NULL, log=log||$7::jsonb, week_of=coalesce(week_of, $8), pend=NULL, updated_at=now() "
        "WHERE org_id=$1::uuid AND client_id=$2::uuid",
        str(org_id), str(client_id), _fo_json.dumps(_fo_mt_dump(sl)),
        (sent.get("card_id") if sent and sent.get("pinned") else (r["pin_msg_id"] if r else None)),
        bool(sent and sent.get("pinned")), sent["tg"] if sent else None,
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
        sent, err = await _fo_mt_card(c, org_id, client_id, "confirm" if kind == "confirm" else "week",
                                      _fo_mt_parts("confirm" if kind == "confirm" else "week", cab, items, names),
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
    txt = ("⭐️🔴 Планёрка пока не согласована.\n"
           "Спасибо! Передали ваш вопрос проджекту — он свяжется с вами и согласует удобное время.")
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
        cs = _fo_mt_chatstate_fast(chats.get(cid)) if cid in chats else {"in": False, "pin": False, "why": ""}
        o["bot_in"], o["bot_pin"] = cs["in"], cs["pin"]
        out.append(o)
    cp = None
    if camp:
        cp = {"id": camp["id"], "status": camp["status"], "wave": camp["wave"], "gap_min": camp["gap_min"],
              "test": bool(camp["test"]), "started_at": camp["started_at"].isoformat(),
              "wave_at": camp["wave_at"].isoformat() if camp["wave_at"] else None}
    bname = _FO_MT_ME.get("v") or ""
    if not bname or _fo_time.time() - _FO_MT_ME.get("t", 0) > 3600:
        try:
            _fo_aio.get_running_loop().create_task(_fo_mt_botname())
        except Exception:
            pass
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
                 pinned=CASE WHEN EXCLUDED.status='agreed' THEN fo_meet.pinned ELSE false END,
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
# одна картинка на все сообщения: логотип справа сверху и «Планёрка» (Виталий 29.09 — без статуса и времени)
_FO_MT_KIMG = {k: "plan" for k in ("week", "confirm", "offer", "move", "extra", "cancel", "agreed", "remind")}
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


def _fo_mt_parts(kind, cab, items, names, note=""):
    """Две части: карточка (картинка и данные планёрки) и отдельным сообщением — вопрос или пояснение бота."""
    full = _fo_mt_caption(kind, cab, items, names, note)
    head, _sep, tail = full.rpartition("\n\n")
    return head, tail


def _fo_mt_caption(kind, cab, items, names, note=""):
    # кружок — статус (Виталий 29.09): 🟡 на согласовании, 🟢 согласована, 🔴 не согласована / отменена
    head = {"week": "⭐️🟡 <b>Планёрки на неделю</b>", "confirm": "⭐️🟡 <b>Планёрки на неделю</b>",
            "offer": "⭐️🟡 <b>Планёрка</b>", "move": "⭐️🟡 <b>Перенос планёрки</b>",
            "extra": "⭐️🟡 <b>Дополнительная планёрка</b>", "agreed": "⭐️🟢 <b>Планёрка назначена</b>",
            "remind": "⭐️🟢 <b>Планёрка через час</b>", "cancel": "⭐️🟡 <b>Отмена планёрки</b>"}[kind]
    tail = {"week": "Удобно? Ответьте на это сообщение «да» — или напишите, что поменять.\n"
                    "В течение недели планёрку можно перенести или попросить дополнительную — просто напишите здесь.",
            "confirm": "Всё в силе по нашему постоянному времени? Ответьте «да» — или напишите, что поменять.",
            "offer": "Удобно? Ответьте «да» — или напишите, какое время подходит.",
            "move": "Подходит? Ответьте «да» — или напишите другое время.",
            "extra": "Подходит? Ответьте «да» — или напишите другое время.",
            "agreed": "Зафиксировали ✅ {pin}До встречи!", "remind": "До встречи через час!",
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


async def _fo_mt_card(c, org_id, client_id, kind, caption, reply_to=None, test=False, pin=False):
    """Карточка планёрки в чат клиента от бота планёрок: картинка с данными планёрки, а вопрос или пояснение бота —
    отдельным сообщением (Виталий 29.09). pin — закрепить карточку (прежнюю открепить); без прав администратора
    Telegram боту закреплять не даёт. Не ушла картинка — уходит тем же текстом."""
    info, ask = caption if isinstance(caption, tuple) else (caption, None)
    strip = lambda t: re.sub(r"<[^>]+>", "", t or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    if test:
        s1, e1 = await _fo_mt_send(c, org_id, client_id, "[карточка «%s»]\n%s" % (_FO_MT_KIMG.get(kind, "plan"), strip(info)),
                                   reply_to=reply_to, test=True)
        if not s1:
            return None, e1
        res = {"tg": s1["tg"], "msg_id": s1["msg_id"], "card_id": s1["msg_id"], "pinned": bool(pin), "pin": "закреплено (проверка)" if pin else ""}
        if ask:
            s2, e2 = await _fo_mt_send(c, org_id, client_id, strip(ask.replace("{pin}", "Карточку закрепили в чате 📌 " if pin else "")),
                                       test=True)
            if s2:
                res["msg_id"] = s2["msg_id"]
        return res, ""
    ch = await _fo_mt_chat(c, client_id)
    if not ch:
        return None, "у клиента нет чата с ботом"
    tok = _fo_mt_tok()
    if not tok:
        return None, "бот планёрок не подключён"
    res = await _fo_aio.to_thread(_fo_tg_photo_sync, tok, ch["chat_id"], _FO_MT_KIMG.get(kind, "plan"), info, reply_to)
    if not res.get("ok"):
        prm = {"chat_id": ch["chat_id"], "text": info, "parse_mode": "HTML"}
        if reply_to:
            prm["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
        res = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", prm)
    if not res.get("ok"):
        return None, "Telegram: " + str(res.get("description") or "не отправилось")[:200]
    card = int(res["result"]["message_id"])
    out = {"tg": ch["chat_id"], "msg_id": card, "card_id": card, "pinned": False, "pin": ""}

    async def _store(mid, txt):
        try:
            await c.execute(
                "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at, ai_state, ai_note) "
                "VALUES ($1,$2::uuid,$3,'client',$4,$5,'Бот планёрок','',$6,now(),'skip','сообщение бота планёрок') "
                "ON CONFLICT (tg_chat_id, msg_id) DO NOTHING", org_id, str(client_id), ch["chat_pk"], ch["chat_id"], mid, strip(txt)[:4000])
        except Exception:
            pass
    await _store(card, info)
    if pin:
        old = await c.fetchval("SELECT pin_msg_id FROM fo_meet WHERE org_id=$1::uuid AND client_id=$2::uuid AND tg_chat_id=$3",
                               str(org_id), str(client_id), ch["chat_id"])
        if old and int(old) != card:
            await _fo_aio.to_thread(_fo_tg_api_sync, "unpinChatMessage", {"chat_id": ch["chat_id"], "message_id": int(old)}, None, 10)
        pr = await _fo_aio.to_thread(_fo_tg_api_sync, "pinChatMessage",
                                     {"chat_id": ch["chat_id"], "message_id": card, "disable_notification": True}, None, 10)
        out["pinned"] = bool(pr.get("ok"))
        out["pin"] = "закреплено в чате" if pr.get("ok") else ("не закреплено: " + str(pr.get("description") or "")[:120] +
                                                              " — Telegram даёт боту закреплять, только если он администратор (достаточно одного права «Закреплять сообщения»)")
        if out["pinned"]:
            await c.execute("UPDATE fo_meet SET pin_msg_id=$3, pinned=true WHERE org_id=$1::uuid AND client_id=$2::uuid",
                            str(org_id), str(client_id), card)
    if ask:
        txt = ask.replace("{pin}", "Карточку с планёркой закрепили в чате 📌 " if out["pinned"] else "")
        r2 = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", {"chat_id": ch["chat_id"], "text": txt, "parse_mode": "HTML"})
        if r2.get("ok"):
            out["msg_id"] = int(r2["result"]["message_id"])
            await _store(out["msg_id"], txt)
    return out, ""


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
        cap = _fo_mt_parts("cancel", cab, [tgt], names)
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
    cap = _fo_mt_parts("move" if it == "move" else "extra", cab, [to], names, note)
    return await _fo_mt_pend_send(c, org_id, client_id, pend, it, cap, msg_id, test, names, cab)


async def _fo_mt_pend_send(c, org_id, client_id, pend, kind, cap, msg_id, test, names, cab):
    sent, err = await _fo_mt_card(c, org_id, client_id, kind, cap, reply_to=msg_id, test=test)
    if not sent:
        return {"state": "error", "why": err}
    await c.execute("UPDATE fo_meet SET pend=$3::jsonb, msg_id=$4, tg_chat_id=$5, sent_at=now(), log=log||$6::jsonb, updated_at=now() "
                    "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), _fo_json.dumps(pend),
                    sent["msg_id"], sent["tg"], _fo_mt_item({"move": "предложили перенос", "cancel": "спросили про отмену",
                                                            "extra": "предложили дополнительную"}[kind],
                                                           text=re.sub(r"<[^>]+>", "", "\n\n".join(cap))[:400], test=("да" if test else None)))
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
    now = _fo_mt_now()
    rr = await _fo_mt_row(c, org_id, client_id)
    mon = _fo_mt_mon(now.date())
    plan = [x for x in await _fo_mt_week(c, org_id, client_id, mon, rr)
            if x["day"] > now.date() or (x["day"] == now.date() and (_fo_mt_m(x["time"]) or 0) > now.hour * 60 + now.minute)]
    if kind == "cancel":
        note = "🔴 Отменили: %s в %s" % (_fo_mt_dd(fr["day"]), fr["time"])
        dm = await _fo_mt_notify(c, {0: {"host": fr["host"]}}, "✖ %s: планёрка %s %s отменена клиентом, задача снята." % (
            cab, _fo_mt_dd(fr["day"]), fr["time"]), test)
    else:
        note = ("Перенесли: было %s в %s" % (_fo_mt_dd(fr["day"]), fr["time"])) if fr and kind == "move" else \
            ("Добавили дополнительную: %s в %s" % (_fo_mt_dd(to["day"]), to["time"]))
        dm = await _fo_mt_notify(c, {0: {"host": to["host"]}}, "✅ %s: %s — %s в %s (%d мин). Задача у вас в ганте." % (
            cab, "перенос" if kind == "move" else "дополнительная планёрка", _fo_mt_dd(to["day"]), to["time"], int(to["minutes"])), test)
    info, ask = _fo_mt_parts("agreed", cab, plan, names, note)
    if not plan:
        info = info.replace("✅ <b>Планёрка назначена</b>", "✅ <b>Планёрки на этой неделе</b>")
    sent, err = await _fo_mt_card(c, org_id, client_id, "agreed", (info, ask), reply_to=msg_id, test=test, pin=True)
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
        at = st.get("auto_at", 600)
        if not st.get("auto") or not (at <= now.hour * 60 + now.minute < at + 240):      # только утром понедельника, не вдогонку вечером
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
    "plan": "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",
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
