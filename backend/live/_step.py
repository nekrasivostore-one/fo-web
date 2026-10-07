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
-- 225: одно сообщение клиента — один разбор (копии от двух ботов)
CREATE TABLE IF NOT EXISTS fo_meet_seen (
  tg_chat_id text NOT NULL, from_id bigint NOT NULL, at bigint NOT NULL, h text NOT NULL,
  by text, verdict text, main_pk bigint, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tg_chat_id, from_id, at, h));
GRANT SELECT, INSERT, UPDATE, DELETE ON fo_meet_seen TO fo;
-- 234: привязка Telegram собственника/директора по почте и коду
CREATE TABLE IF NOT EXISTS fo_tg_link (tg_id bigint PRIMARY KEY, user_id uuid NOT NULL, code text NOT NULL, bot text,
  created_at timestamptz NOT NULL DEFAULT now());
GRANT SELECT, INSERT, UPDATE, DELETE ON fo_tg_link TO fo;
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


def _fo_lvl(p):
    """264: уровень аккаунта одним способом везде. admin = 0 (раньше `0 or 9` давал 9), нет уровня = 9."""
    try:
        v = getattr(p, "level", None)
        return 9 if v is None else int(v)
    except Exception:
        return 9


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


# ── грейд = уровень доступа (239, Виталий 30.09) ──
_FO_GRADE_ROLE = {"pm": "project", "head": "manager_senior", "mid": "manager_senior", "jun": "manager_junior", "assist": "assistant"}
_FO_ROLE_GRADE = {"project": "pm", "manager_senior": "head", "manager_junior": "jun", "assistant": "assist"}


async def _fo_grade_role(c, p, emp_ref, grade):
    """Грейд в карточке сотрудника меняет роль его аккаунта. Только собственник и директор; не выше себя;
    собственника и админа не трогаем; без аккаунта — только подпись в карточке."""
    want = _FO_GRADE_ROLE.get(str(grade or ""))
    if not want:
        return "грейд без роли"
    if _fo_lvl(p) > 2:
        return "роль меняет собственник или директор"
    u = await c.fetchrow("SELECT u.id, u.role_code, r.level FROM employee e JOIN app_user u ON u.id=e.user_id "
                         "JOIN role r ON r.code=u.role_code WHERE e.id=$1::uuid AND e.org_id=$2::uuid", str(emp_ref), str(p.org_id))
    if not u:
        return "у сотрудника нет аккаунта — роль выдаст приглашение"
    wl = await c.fetchval("SELECT level FROM role WHERE code=$1", want)
    if int(u["level"]) <= 1 or wl is None:
        return "собственника и админа так не меняют"
    if int(wl) <= _fo_lvl(p):
        return "нельзя выдать уровень не ниже своего"
    if u["role_code"] == want:
        return "роль уже " + want
    await c.execute("UPDATE app_user SET role_code=$2 WHERE id=$1", u["id"], want)
    return "роль: %s → %s" % (u["role_code"], want)


async def _fo_cards_grade(c, p, out):
    """В карточке сотрудника показываем текущую роль аккаунта как грейд."""
    try:
        rows = await c.fetch("SELECT e.id, u.role_code FROM employee e JOIN app_user u ON u.id=e.user_id "
                             "WHERE e.org_id=$1::uuid", str(p.org_id))
    except Exception:
        return out
    m = {str(r["id"]): _FO_ROLE_GRADE.get(r["role_code"]) for r in rows}
    for cd in out:
        if cd.get("kind") == "employee" and m.get(str(cd.get("ref_id"))):
            cd["data"] = dict(cd.get("data") or {}, grade=m[str(cd["ref_id"])])
    return out


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
    try:
        async with pool().acquire() as c:
            out = await _fo_cards_grade(c, p, out)
    except Exception:
        pass
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
    _lvl = _fo_lvl(p)
    if _lvl > 4 and kind != "cab":
        raise HTTPException(403, "Карточки сотрудников, клиентов и функций правят РМ и выше — вам доступен просмотр")
    data = body.data if isinstance(body.data, dict) else {}
    if kind == "employee" and "money" in data and _lvl > 2:
        raise HTTPException(403, "«Видит деньги» в карточке меняют собственник и директор")
    if kind == "employee" and "canFns" in data and _lvl > 4:
        raise HTTPException(403, "«Может заполнять функции кабинета» ставят РМ и выше")
    if kind == "org" and _lvl > 2:
        raise HTTPException(403, "Настройки агентства (ИИ, планёрки, карточка организации) меняют собственник и директор")
    async with pool().acquire() as c:
        # 260: карточку кабинета ниже РМ правит только сотрудник с галочкой — и только поля функций (fn_…)
        if _lvl > 4:
            await _fo_need_fns(c, p)
            _bad0 = [str(k) for k in data.keys() if not str(k).startswith("fn_")]
            if _bad0:
                raise HTTPException(403, "С галочкой «Может заполнять функции кабинета» правятся только функции кабинета — не сохранено: " + ", ".join(_bad0))
        # 259/262 (Виталий 01.10): «проджект не может менять суммы проектов и суммы зп — может либо видеть, либо
        # не видеть по желанию собственника». Суммы и даты платежей клиентов и кабинетов, оклады, дни выплат,
        # премии и штрафы — принимаем только от собственника и директора, что бы ни было видно.
        if _lvl > 2:
            _bad = []
            for _k in data.keys():
                _kl = str(_k).lower()
                if kind in ("client", "cab") and (_k in _FO_PRIV_MONEY or _kl.startswith("pay")):
                    _bad.append(str(_k))
                elif kind == "client" and _k in ("pm", "since"):          # 282: закрепление проджекта и «работаем с»
                    _bad.append({"pm": "проджект клиента", "since": "«работаем с»"}[_k])
                elif kind == "employee" and _FO_PRIV_PAY.search(str(_k)):
                    _bad.append(str(_k))
            if _bad:
                raise HTTPException(403, ("Оклады, дни выплат, премии и штрафы" if kind == "employee" else "Суммы и даты платежей клиентов") +
                                    " меняют собственник и директор — не сохранено: " + ", ".join(_bad))
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ($1,$2,$3,$4::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE "
            "SET data = fo_card.data || EXCLUDED.data, updated_at = now() "
            "WHERE fo_card.org_id = EXCLUDED.org_id",
            kind, ref, p.org_id, _fo_json.dumps(data))
        row = await c.fetchrow(
            "SELECT data FROM fo_card WHERE kind=$1 AND ref_id=$2 AND org_id=$3",
            kind, ref, p.org_id)
        role_note = None
        if kind == "employee" and "grade" in data:
            try:
                role_note = await _fo_grade_role(c, p, ref, data.get("grade"))
            except Exception as e:
                role_note = "роль не поменялась: " + str(e)[:100]
    d = row["data"] if row else {}
    if isinstance(d, str):
        try: d = _fo_json.loads(d)
        except Exception: d = {}
    return {"ok": True, "kind": kind, "ref_id": ref, "data": d or {}, "роль": role_note}


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
        if _fo_lvl(p) > 4:                 # 264: ниже РМ — задачу только себе (если нет права «ставить другим»)
            _me = await _fo_my_emp(c, p)
            if not (await _fo_can(c, p, "tasks_set_others")) and (not _me or str(body.employee_id or "") != str(_me)):
                raise HTTPException(403, "Задачи другим ставят РМ и выше — себе поставить можно")
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
        if _fo_lvl(p) > 4:                 # 264: ниже РМ — только свою разовую задачу, и не переназначать
            _me = await _fo_my_emp(c, p)
            _own = await c.fetchval("SELECT employee_id FROM fo_task_once WHERE id=$1 AND org_id=$2", _fo_task_id(task_id), p.org_id)
            if not _me or str(_own or "") != str(_me) or (body.employee_id is not None and str(body.employee_id or "") != str(_me)):
                raise HTTPException(403, "Чужие разовые задачи правят РМ и выше")
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
async def fo_client_remove(client_id: str, p: Principal = Depends(max_level(4))):
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


async def _fo_can_fns(c, p):
    """260: функции кабинета заполняют РМ и выше — или сотрудник с галочкой «Может заполнять функции кабинета»
    в карточке (fo_card employee.canFns = "1")."""
    if _fo_lvl(p) <= 4:
        return True
    try:
        me = await _fo_my_emp(c, p)
        if not me:
            return False
        d = _fo_st_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='employee' AND ref_id=$1 AND org_id=$2",
                                         str(me), p.org_id)) or {}
        return bool(isinstance(d, dict) and str(d.get("canFns") or "").strip().lower() in ("1", "yes", "true", "да"))
    except Exception:
        return False


async def _fo_need_fns(c, p):
    if not await _fo_can_fns(c, p):
        raise HTTPException(403, "Функции кабинета заполняют РМ и выше — или сотрудник, кому в карточке включили «Может заполнять функции кабинета»")


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
async def fo_cab_fns_put(cab_id: str, body: list[FoCabFnItem], p: Principal = Depends(current)):
    """Полная замена набора функций кабинета. Уровень: РМ и выше (С5) или сотрудник с галочкой (260)."""
    async with pool().acquire() as c:
        await _fo_need_fns(c, p)
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
async def fo_cab_fn_add(cab_id: str, it: FoCabFnItem, p: Principal = Depends(current)):
    """Одна функция в кабинет: добавить или обновить, остальные не трогая.
    Задачи досводятся сразу. Уровень: РМ и выше (С5) или сотрудник с галочкой (260). Три пути (145) ведут сюда."""
    fid = (it.fn_id or "").strip()
    if not fid:
        raise HTTPException(400, "не указана функция")
    async with pool().acquire() as c:
        await _fo_need_fns(c, p)
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
async def fo_cab_fn_remove(cab_id: str, fn_id: str, p: Principal = Depends(current)):
    """Убрать функцию из кабинета: будущие несделанные задачи по ней снимаются. РМ и выше или с галочкой (260)."""
    async with pool().acquire() as c:
        await _fo_need_fns(c, p)
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


# ── 248 (Виталий 30.09): перераспределение задач и «интеллект менеджера» ──
class FoReasItem(_FoBM):
    task_id: str
    assignee_id: str | None = None
    plan_date: str | None = None


class FoReasIn(_FoBM):
    items: list[FoReasItem]
    permanent: bool = False
    why: str | None = None


@router.post("/tasks/reassign")
async def fo_tasks_reassign(body: FoReasIn, p: Principal = Depends(max_level(4))):
    """Пачка: задача → новый ответственный и/или день этой или следующей недели. permanent — ещё и ответственный
    за функцию в кабинете (если у функции ответственные по дням — только этот день недели), будущие задачи
    функции переезжают. Сделанные не трогаем; планёрки — через бота планёрок. РМ и выше."""
    import datetime as _dt
    today = _fo_msk_today()
    mon = today - _dt.timedelta(days=today.weekday())
    moved = dated = perm = 0
    skipped = []
    why = (body.why or "перераспределение")[:80]
    async with pool().acquire() as c:
        emps = {str(r["id"]) for r in await c.fetch("SELECT id FROM employee WHERE org_id=$1 AND is_active", p.org_id)}
        async with c.transaction():
            for it in (body.items or [])[:500]:
                t = await c.fetchrow("SELECT id, status, source, cabinet_id, fn_id, assignee_id, plan_date FROM task "
                                     "WHERE id=$1::uuid AND org_id=$2", it.task_id, p.org_id)
                if not t:
                    skipped.append(it.task_id[:8] + ": не найдена"); continue
                if t["status"] == "done":
                    skipped.append(it.task_id[:8] + ": уже сделана"); continue
                if t["source"] == "meet":
                    skipped.append(it.task_id[:8] + ": планёрка — меняется через бота планёрок"); continue
                to = (it.assignee_id or "").strip() or None
                if to and to not in emps:
                    skipped.append(it.task_id[:8] + ": сотрудник не из агентства"); continue
                d = None
                if it.plan_date:
                    try:
                        d = _dt.date.fromisoformat(str(it.plan_date)[:10])
                    except Exception:
                        d = None
                    if d and (d < mon or d > mon + _dt.timedelta(days=13)):
                        skipped.append(it.task_id[:8] + ": день вне этой и следующей недели"); d = None
                sets, args = [], [t["id"]]
                if to and str(t["assignee_id"]) != to:
                    args.append(to); sets.append("assignee_id=$%d::uuid" % len(args)); moved += 1
                if d and d != t["plan_date"]:
                    args.append(d); sets.append("plan_date=$%d" % len(args)); dated += 1
                if sets:
                    args.append(why)
                    await c.execute("UPDATE task SET %s, moved_reason=$%d WHERE id=$1" % (", ".join(sets), len(args)), *args)
                if body.permanent and to and t["cabinet_id"] and t["fn_id"] and t["source"] == "generator":
                    cfg = await c.fetchrow("SELECT employee_id, day_cfg FROM fo_cabinet_fn_cfg WHERE cabinet_id=$1 AND fn_id=$2",
                                           t["cabinet_id"], t["fn_id"])
                    wd = (d or t["plan_date"]).weekday()
                    dc = _fo_dc_parse(cfg["day_cfg"]) if cfg else {}
                    if cfg and dc and wd in dc:
                        raw = cfg["day_cfg"]
                        if isinstance(raw, str):
                            try: raw = _fo_json.loads(raw)
                            except Exception: raw = {}
                        raw = dict(raw or {})
                        raw[str(wd)] = dict(raw.get(str(wd)) or {}, e=to)
                        await c.execute("UPDATE fo_cabinet_fn_cfg SET day_cfg=$3::jsonb, updated_at=now() WHERE cabinet_id=$1 AND fn_id=$2",
                                        t["cabinet_id"], t["fn_id"], _fo_json.dumps(raw))
                        await c.execute("UPDATE task SET assignee_id=$4::uuid, moved_reason=$6 WHERE org_id=$1 AND cabinet_id=$2 AND fn_id=$3 "
                                        "AND source='generator' AND status='planned' AND plan_date > $5 "
                                        "AND extract(isodow FROM plan_date) = %d AND assignee_id IS DISTINCT FROM $4::uuid" % (wd + 1),
                                        p.org_id, t["cabinet_id"], t["fn_id"], to, today, why)
                    else:
                        if cfg:
                            await c.execute("UPDATE fo_cabinet_fn_cfg SET employee_id=$3::uuid, updated_at=now() WHERE cabinet_id=$1 AND fn_id=$2",
                                            t["cabinet_id"], t["fn_id"], to)
                        else:
                            await c.execute("INSERT INTO fo_cabinet_fn_cfg (cabinet_id, fn_id, org_id, employee_id) VALUES ($1, $2, $3, $4::uuid) "
                                            "ON CONFLICT (cabinet_id, fn_id) DO UPDATE SET employee_id=EXCLUDED.employee_id, updated_at=now()",
                                            t["cabinet_id"], t["fn_id"], p.org_id, to)
                        await c.execute("UPDATE task SET assignee_id=$4::uuid, moved_reason=$6 WHERE org_id=$1 AND cabinet_id=$2 AND fn_id=$3 "
                                        "AND source='generator' AND status='planned' AND plan_date > $5 AND assignee_id IS DISTINCT FROM $4::uuid",
                                        p.org_id, t["cabinet_id"], t["fn_id"], to, today, why)
                    await c.execute("INSERT INTO employee_fn (employee_id, fn_id, allowed) VALUES ($1::uuid, $2, true) ON CONFLICT DO NOTHING",
                                    to, t["fn_id"])
                    perm += 1
    return {"ok": True, "переведено": moved, "перенесено_дней": dated, "навсегда": perm, "пропущено": skipped[:30]}


@router.get("/team/intel")
async def fo_team_intel(weeks: int = 8, p: Principal = Depends(max_level(4))):
    """«Интеллект менеджера» (248): кто какие категории функций (A / B / C по карточке функции) реально закрывает
    за N недель, сколько просрочил; роль аккаунта — для сверки с грейдом. РМ и выше."""
    import datetime as _dt
    today = _fo_msk_today()
    weeks = max(1, min(26, int(weeks or 8)))
    since = today - _dt.timedelta(days=7 * weeks)
    out = {}
    async with pool().acquire() as c:
        for r in await c.fetch("SELECT e.id, e.name, u.role_code FROM employee e LEFT JOIN app_user u ON u.id=e.user_id "
                               "WHERE e.org_id=$1 AND e.is_active", p.org_id):
            out[str(r["id"])] = {"employee_id": str(r["id"]), "имя": r["name"], "роль": r["role_code"],
                                 "закрыто": {"A": 0, "B": 0, "C": 0, "-": 0}, "в_плане": {"A": 0, "B": 0, "C": 0, "-": 0}, "просрочено": 0, "всего": 0}
        rows = await c.fetch(
            """SELECT t.assignee_id::text AS eid, COALESCE(NULLIF(upper(cd.data->>'cat'), ''), '-') AS cat, t.status,
                      count(*) FILTER (WHERE t.plan_date < $3 AND t.status='planned') AS late, count(*) AS n
                 FROM task t LEFT JOIN fo_card cd ON cd.kind='fn' AND cd.ref_id = t.fn_id::text AND cd.org_id::text = t.org_id::text
                WHERE t.org_id=$1 AND t.plan_date BETWEEN $2 AND $3 AND t.assignee_id IS NOT NULL
                  AND COALESCE(t.source, '') <> 'meet' AND t.status IN ('done', 'planned')
                GROUP BY 1, 2, 3""", p.org_id, since, today + _dt.timedelta(days=6))
        for r in rows:
            o = out.get(r["eid"])
            if not o:
                continue
            cat = r["cat"] if r["cat"] in ("A", "B", "C") else "-"
            key = "закрыто" if r["status"] == "done" else "в_плане"
            o[key][cat] += int(r["n"])
            o["всего"] += int(r["n"])
            o["просрочено"] += int(r["late"] or 0)
    return {"недель": weeks, "с": since.isoformat(), "люди": list(out.values())}


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


async def _fo_resolve_emp(c, p):
    """264: кто я как сотрудник. 1) employee.user_id; 2) e-mail аккаунта = колонка email или поле «mail»
    карточки сотрудника (без привязанного аккаунта); 3) имя аккаунта = имя сотрудника. Найденное по 2/3 —
    привязывается (UPDATE employee.user_id), чтобы дальше всё решалось одинаково. Возвращает (id, как)."""
    uid = _fo_uid(p)
    org = str(p.org_id)
    try:
        me = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2::uuid LIMIT 1", uid, org)
    except Exception:
        me = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2 LIMIT 1", uid, p.org_id)
    if me:
        return str(me), "user_id"
    try:
        u = await c.fetchrow("SELECT email, display_name, " + _FO_NAME_COL + " AS base_name FROM app_user WHERE id=$1", uid)
    except Exception:
        u = None
    if not u:
        return None, None
    em = str(u["email"] or "").strip().lower()
    cand, how = None, None
    if em:
        try:
            cand = await c.fetchval("SELECT id FROM employee WHERE org_id=$1::uuid AND user_id IS NULL AND lower(trim(email))=$2 LIMIT 1", org, em)
            if cand: how = "email"
        except Exception:
            cand = None
        if not cand:
            try:
                cand = await c.fetchval(
                    "SELECT e.id FROM employee e JOIN fo_card cd ON cd.kind='employee' AND cd.ref_id=e.id::text AND cd.org_id::text=e.org_id::text "
                    "WHERE e.org_id=$1::uuid AND e.user_id IS NULL "
                    "AND lower(trim(coalesce(cd.data->>'mail', cd.data->>'email', ''))) = $2 LIMIT 1", org, em)
                if cand: how = "mail"
            except Exception:
                cand = None
    if not cand:
        nm = str(u["display_name"] or u["base_name"] or "").strip().lower()
        if nm:
            try:
                cand = await c.fetchval("SELECT id FROM employee WHERE org_id=$1::uuid AND user_id IS NULL AND lower(trim(name))=$2 LIMIT 1", org, nm)
                if cand: how = "name"
            except Exception:
                cand = None
    if cand:
        try:
            await c.execute("UPDATE employee SET user_id=$2 WHERE id=$1 AND user_id IS NULL", cand, uid)
        except Exception:
            pass
        return str(cand), how
    return None, None


async def _fo_my_emp(c, p):
    me, _how = await _fo_resolve_emp(c, p)
    return me


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
    return _fo_lvl(p) <= 4


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


# ── бот отчётов (235–236, Виталий 30.09): третий бот только пишет клиенту — выполненные функции и уведомления.
# Правила «Куда сообщать» (chat_route) и очередь outbox — из routers/routing.py; здесь подменяем ему отправку
# на токен бота отчётов и вешаем хук на галочку «выполнено».
def _fo_rp_tok():
    return _fo_env("TG_REPORT_BOT_TOKEN") or ""


_FO_RP_ME = {"t": 0.0, "v": "", "id": 0}


def _fo_rp_me():
    tok = _fo_rp_tok()
    if not tok:
        return {}
    if _fo_time.time() - _FO_RP_ME["t"] < 3600 and _FO_RP_ME["v"]:
        return _FO_RP_ME
    me = (_fo_tg_api_sync("getMe", {}, tok, 10) or {}).get("result") or {}
    if me.get("username"):
        _FO_RP_ME.update({"t": _fo_time.time(), "v": me.get("username"), "id": me.get("id")})
    return _FO_RP_ME


async def _fo_rp_send_telegram(chat_id, text, _noimg=False):
    """Замена notify.send_telegram: шлёт бот отчётов (если подключён), иначе бот сервиса; сообщение ложится
    в историю чата (ИИ задач видит, что клиенту отправили)."""
    tok = _fo_rp_tok() or _fo_env("TG_BOT_TOKEN")
    if not tok:
        return False
    res = None
    _fi = None
    if not _noimg:
        try:
            _fi = await _fo_fi_for_text(chat_id, text)      # 289: выполненная функция — картинкой с подписью
        except Exception as _e:
            print("бот отчётов, картинка:", str(_e)[:200])
            _fo_fi_why(chat_id, str(text)[:60], "ошибка: " + str(_e)[:120], False)
    if _fi:
        _fid = await _fo_fi_fid(tok, _fi[0])
        if not _fid:                                          # первая отправка этой картинки — в фоне, галочка не ждёт
            _fo_aio.get_running_loop().create_task(_fo_fi_bg(tok, chat_id, _fi, str(text)))
            return True
        res = await _fo_aio.to_thread(_fo_fi_photo_sync, tok, chat_id, _fi, str(text), _fid)
        if not res.get("ok"):
            print("бот отчётов, картинка не ушла:", str(res.get("description") or res)[:200])
            res = None
    if res is None:
        res = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", {"chat_id": str(chat_id), "text": str(text)[:4000],
                                                                        "disable_web_page_preview": True}, tok, 20)
    if not res.get("ok"):
        try:
            print("бот отчётов:", str(res.get("description") or res)[:200])
        except Exception:
            pass
        return False
    try:
        mid = int((res.get("result") or {}).get("message_id") or 0)
        async with pool().acquire() as c:
            ch = await c.fetchrow("SELECT ch.id, ch.org_id, cc.client_id, cc.kind FROM chat ch "
                                  "JOIN client_chat cc ON cc.chat_pk = ch.id WHERE ch.chat_id=$1 "
                                  "ORDER BY (cc.kind='client') DESC LIMIT 1", str(chat_id))
            if ch and mid:
                await c.execute(
                    "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at, ai_state, ai_note) "
                    "VALUES ($1,$2::uuid,$3,$4,$5,$6,'Бот отчётов','',$7,now(),'skip','сообщение бота отчётов') "
                    "ON CONFLICT (tg_chat_id, msg_id) DO NOTHING",
                    ch["org_id"], str(ch["client_id"]), ch["id"], ch["kind"], str(chat_id), -(1000000 + mid), str(text)[:4000])
    except Exception:
        pass
    return True


def _fo_rp_install():
    """Подменить отправку в notify и routing на бота отчётов."""
    import sys as _s
    n = 0
    for name, m in list(_s.modules.items()):
        if m is None or not (name.endswith(".notify") or name.endswith(".routing")):
            continue
        if hasattr(m, "send_telegram") and getattr(m, "send_telegram") is not _fo_rp_send_telegram:
            try:
                setattr(m, "send_telegram", _fo_rp_send_telegram)
                n += 1
            except Exception:
                pass
    return n


@router.on_event("startup")
async def _fo_rp_boot():
    try:
        _fo_rp_install()
    except Exception:
        pass


def _fo_rp_routing():
    import sys as _s
    _fo_rp_install()
    return next((m for name, m in list(_s.modules.items()) if m is not None and name.endswith(".routing")
                 and hasattr(m, "dispatch")), None)


async def _fo_rp_task_done(c, t, p, link, note):
    """Отчёт клиенту о выполненной функции — по правилам «Куда сообщать» кабинета (клиенту по умолчанию — да,
    сразу; отложенно — если так настроено)."""
    if not t["client_id"]:
        return "у задачи нет клиента"
    fn = await c.fetchval("SELECT name FROM fn WHERE id=$1", t["fn_id"]) if t["fn_id"] else None
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1", t["client_id"]) or ""
    me = await _fo_my_emp(c, p)
    who = await c.fetchval("SELECT name FROM employee WHERE id=$1", me or t["assignee_id"]) or ""
    d = t["plan_date"] or _fo_msk_today()
    when = "%02d.%02d · %s" % (d.day, d.month, _FO_MT_DOWN[d.weekday()].capitalize())
    head = "✅ Выполнено: %s" % (fn or t["title"] or "задача")
    lines = [head, cab, "📅 %s%s" % (when, (" · " + who.split(" ")[0]) if who else "")]
    link = (link or "").strip()
    note = (note or "").strip()
    if link:
        lines.append("🔗 " + link)
    if note:
        lines.append("💬 " + note[:1500])
    txt_client = "\n".join(x for x in lines if x)
    txt_mpv = txt_client + (("\nЗадача: " + t["title"]) if t["title"] and fn and t["title"] != fn else "")
    rt = _fo_rp_routing()
    if rt is None:
        return "модуль «Куда сообщать» не найден"
    _fi_tok = _FO_FI_CTX.set({"org": t["org_id"], "fn": t["fn_id"], "name": fn}) if t["fn_id"] and fn else None
    try:
        res = await rt.dispatch(t["org_id"], t["client_id"], "task_form", {"client": txt_client, "mpv": txt_mpv, "internal": txt_mpv})
    except Exception as e:
        return "не отправилось: " + str(e)[:150]
    finally:
        if _fi_tok is not None:
            _FO_FI_CTX.reset(_fi_tok)
    return "клиенту: отправлено %s, отложено %s" % (res.get("отправлено"), res.get("отложено"))


class FoRpTestIn(_FoBM):
    client_id: str
    text: str | None = None


@router.post("/report/test")
async def fo_report_test(body: FoRpTestIn, p: Principal = Depends(max_level(4))):
    """Проверка бота отчётов: сообщение в чат клиента от @flater_report_bot (РМ и выше)."""
    async with pool().acquire() as c:
        ch = await c.fetchrow("SELECT ch.chat_id FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id "
                              "WHERE cc.client_id=$1::uuid AND ch.org_id=$2 AND cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' "
                              "ORDER BY ch.id LIMIT 1", body.client_id, p.org_id)
    if not ch:
        raise HTTPException(404, "у клиента нет чата")
    me = _fo_rp_me()
    ok = await _fo_rp_send_telegram(ch["chat_id"], body.text or "Проверка связи: это бот отчётов агентства. Сюда будут приходить выполненные работы.")
    return {"ok": ok, "бот": ("@" + me["v"]) if me.get("v") else "не подключён", "чат": ch["chat_id"]}


@router.get("/report/status")
async def fo_report_status(p: Principal = Depends(max_level(4))):
    """Бот отчётов: подключён ли, в каких чатах клиентов состоит, очередь."""
    me = _fo_rp_me()
    out = {"бот": ("@" + me["v"]) if me.get("v") else "не подключён", "чаты": [], "подменено": _fo_rp_install()}
    async with pool().acquire() as c:
        for r in await c.fetch("SELECT cl.name, ch.chat_id FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id "
                               "JOIN client cl ON cl.id = cc.client_id WHERE ch.org_id=$1 AND cc.kind='client' "
                               "AND ch.chat_id ~ '^-?[0-9]+$' ORDER BY cl.name", p.org_id):
            st = "?"
            if me.get("id"):
                cm = await _fo_aio.to_thread(_fo_tg_api_sync, "getChatMember", {"chat_id": r["chat_id"], "user_id": me["id"]}, _fo_rp_tok(), 10)
                st = ((cm.get("result") or {}).get("status") or str(cm.get("description") or "")[:60]) if cm else "?"
            out["чаты"].append({"клиент": r["name"], "бот_в_чате": st})
        try:
            out["очередь"] = dict(await c.fetchrow("SELECT count(*) FILTER (WHERE sent_at IS NULL) AS ждут, count(*) FILTER (WHERE error IS NOT NULL) AS ошибок FROM outbox WHERE org_id=$1", p.org_id))
        except Exception:
            pass
    return out


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
        try:
            rp = await _fo_rp_task_done(c, t, p, body.link, body.note)     # 236: отчёт клиенту от бота отчётов
        except Exception as e:
            rp = "ошибка: " + str(e)[:120]
    return {"ok": True, "status": "done", "клиенту": rp}


@router.post("/tasks/{task_id}/undone")
async def fo_task_undone(task_id: str, p: Principal = Depends(current)):
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
        if not mine and _fo_lvl(p) > 2:
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
    lvl = _fo_lvl(p)
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
                "SELECT link FROM fo_task_report WHERE org_id=$1 AND fn_id=$2::uuid AND employee_id=$3 AND link IS NOT NULL "
                "AND cabinet_id IS NOT DISTINCT FROM $4::uuid ORDER BY made_at DESC LIMIT 1",
                p.org_id, fn_id, me, cabinet_id)
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
async def fo_admin_shadow(body: FoShadowIn, p: Principal = Depends(max_level(2))):
    """Тень: доступ от имени пользователя. Только смотреть — запись сервер отклонит.
    Админ — на кого угодно; собственник и директор (234, Виталий 30.09) — на людей своего агентства ниже по роли."""
    async with pool().acquire() as c:
        u = await c.fetchrow(
            "SELECT u.id, u.email, u.org_id, u.role_code, u.display_name, r.level, o.name AS org_name "
            "FROM app_user u JOIN role r ON r.code=u.role_code JOIN org o ON o.id=u.org_id "
            "WHERE u.id=$1::uuid", body.user_id)
        if not u:
            raise HTTPException(404, "пользователь не найден")
        if int(getattr(p, "level", 9) or 0) > 0 and (str(u["org_id"]) != str(p.org_id) or int(u["level"]) <= int(p.level)):
            raise HTTPException(403, "тень: только на сотрудников своего агентства ниже по роли")
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
async def fo_admin_people(p: Principal = Depends(max_level(2))):
    """Кого можно посмотреть глазами: админу — все агентства и люди; собственнику и директору — своё агентство,
    роли ниже своей (234)."""
    async with pool().acquire() as c:
        if int(getattr(p, "level", 9) or 0) > 0:
            rows = await c.fetch(
                "SELECT u.id, u.email, u.display_name, u.role_code, r.level, o.id AS org_id, o.name AS org_name "
                "FROM app_user u JOIN role r ON r.code=u.role_code JOIN org o ON o.id=u.org_id "
                "WHERE u.is_active AND u.org_id=$1 AND r.level > $2 ORDER BY r.level, u.email", p.org_id, int(p.level))
        else:
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
    out = {"id": str(u["id"]), "email": u["email"],
            "name": u["display_name"] or u["base_name"] or "",
            "phone": u["phone"] or "", "role_code": u["role_code"],
            "role_title": u["role_title"] or u["role_code"], "level": u["level"],
            "org_name": u["org_name"], "org_id": str(u["org_id"]),
            "invite_code": u["invite_code"] if _fo_lvl(p) <= 2 else None, "created_at": u["created_at"]}
    try:                                   # 264: права — сразу, одним ответом
        async with pool().acquire() as c:
            out["perms"] = await _fo_perms(c, p)
    except Exception as _e:
        out["perms_error"] = str(_e)[:200]
    return out


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
async def fo_invite_list(p: Principal = Depends(max_level(1))):
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
    "promised": ("org", "map",  1, 3, 0),      # 264: обещанные уровни пишет только собственник
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
    "svc":      ("org", "map",  9, 9, 0),      # 245: часы в сервисе, сотрудник → часы (свои — каждый, только вверх)
    "rkDone":   ("org", "map",  9, 9, 0),      # 263: «Работа с РК выполнена»: сотрудник|проект|дата → отметка (ниже РМ — свои)
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
        if key == "svc" and lvl > 2:
            # 245: часы в сервисе — только свои, только числом; целиком и удаление — старшим
            me = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2::uuid LIMIT 1", uid, str(p.org_id))
            body.data, body.delete = None, None
            body.set = {k2: v2 for k2, v2 in (body.set or {}).items() if str(k2) == str(me) and isinstance(v2, (int, float))}
        if key == "rkDone" and lvl > 4:
            # 263: отметки РК — ниже РМ только свои строки (ключ начинается со своего id сотрудника)
            me = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND org_id=$2::uuid LIMIT 1", uid, str(p.org_id))
            _pre = str(me) + "|"
            body.data = None
            body.set = {k2: v2 for k2, v2 in (body.set or {}).items() if str(k2).startswith(_pre)}
            body.delete = [k2 for k2 in (body.delete or []) if str(k2).startswith(_pre)]
        if key in ("log", "speed") and lvl > 4:
            # 264: журнал и замеры ниже РМ — только дописывать, не заменять и не стирать
            body.data, body.remove = None, None
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
                    if key == "svc" and lvl > 2:
                        try:
                            v2 = max(float(new.get(str(k2)) or 0), min(float(v2), 24 * 366 * 20))   # часы только растут
                        except Exception:
                            continue
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
    ok = wl is not None and int(wl) >= 2 and int(u["level"]) > int(wl) and str(want) not in ("owner", "admin")
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
# Задачи: проджект и выше — все; главный менеджер, младший и ассистент — только свои (238, 30.09;
# раньше главный менеджер видел и младших). Экран и раньше прятал чужое, теперь его не
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
    me = await _fo_my_emp(c, p)
    # 238 (Виталий 30.09): все роли ниже проджекта — главный менеджер, младший, ассистент — только свои задачи
    return {str(me)} if me else set()


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


# ── 242 (Виталий 30.09): что закрыто по деньгам — решают галочки роли, выключатель и карточка проджекта ──
_FO_LVL_FRONT = {3: "head", 4: "pm", 5: "mgr", 6: "jun", 7: "asst"}
_FO_PRIV_MONEY = {"amount", "payDate", "price", "sum", "contract", "payDay"}
_FO_PRIV_SUM = {"amount", "price", "sum", "contract"}


async def _fo_money_lims(c, p, me):
    """Множество: "money" — суммы и даты платежей клиентов (оклады коллег и так закрыты с уровня 3);
    "pay" — только суммы платежей клиентов. Уровень ≤ 2 — пусто; ≥ 5 — всё (238).
    Между — галочки роли в «Доступы → Роли» (fo_state.roleCfg), выключатель «Проджект видит стоимость
    контрактов» (fo_state.settings.pmMoney) и переключатель «Видит деньги» в карточке проджекта (money = no)."""
    lvl = _fo_st_lvl(p)
    if lvl <= 2:
        return set()
    if lvl >= 5:
        return {"money", "pay"}
    try:                                   # 264: единая матрица
        pr = await _fo_perms(c, p, with_emp=bool(me))
        out = set()
        if not pr["can"]["money_client_read"]:
            out.update({"money", "pay"})
        elif not pr["can"]["money_sum_read"]:
            out.add("pay")
        return out
    except Exception:
        pass
    out = set()
    rid = _FO_LVL_FRONT.get(lvl, "")
    try:
        rows = await c.fetch("SELECT key, data FROM fo_state WHERE org_id=$1::uuid AND scope='org' AND key IN ('roleCfg', 'settings')",
                             str(p.org_id))
        for r in rows:
            d = _fo_st_load(r["data"]) or {}
            if not isinstance(d, dict):
                continue
            if r["key"] == "roleCfg":
                lim = ((d.get(rid) or {}).get("lim") or {}) if isinstance(d.get(rid), dict) else {}
                if lim.get("money"):
                    out.add("money")
                if lim.get("pay"):
                    out.add("pay")
            elif r["key"] == "settings" and rid == "pm" and d.get("pmMoney") is False:
                out.add("money")
        if rid == "pm" and me:
            cd = _fo_st_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='employee' AND ref_id=$1 AND org_id=$2",
                                              str(me), p.org_id)) or {}
            if isinstance(cd, dict) and str(cd.get("money") or "").strip().lower() in ("no", "false", "0", "нет"):
                out.add("money")
    except Exception:
        pass
    return out


async def _fo_cards_scope(p, out):
    lvl = _fo_st_lvl(p)
    if lvl <= 2:
        return out
    me, lims = None, set()
    try:
        async with pool().acquire() as c:
            me = await _fo_my_emp(c, p)
            lims = await _fo_money_lims(c, p, me)
    except Exception:
        pass
    res = []
    for cd in out:
        k = cd.get("kind")
        d = cd.get("data") or {}
        if k in ("cab", "client"):
            if lvl >= 5:
                d = {a: b for a, b in d.items() if a not in _FO_PRIV_CLIENT and not str(a).lower().startswith(("owner", "pay", "phone"))}
            elif "money" in lims:
                d = {a: b for a, b in d.items() if a not in _FO_PRIV_MONEY and not str(a).lower().startswith("pay")}
            elif "pay" in lims:
                d = {a: b for a, b in d.items() if a not in _FO_PRIV_SUM}
        elif k == "employee" and str(cd.get("ref_id")) != str(me):
            d = {a: b for a, b in d.items() if not _FO_PRIV_PAY.search(str(a))}
        res.append(dict(cd, data=d))
    return res

# ══ 266: ПЛАН РАБОТЫ В ГРУППУ TELEGRAM (Виталий 01.10) ═════════════════
_FO_PLAN_DEF = {"morning": "09:00", "eve_cut": "17:40", "eve_send": "17:55"}
_FO_PLAN_LOOP = {"task": None}
_FO_DOW_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_FO_DOW_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _fo_plan_date(d):
    return "📅 %02d.%02d.%d, %s" % (d.day, d.month, d.year, _FO_DOW_RU[d.weekday()])


async def _fo_plan_cfg(c, org_id):
    d = _fo_st_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1 AND org_id=$2",
                                     "plan:" + str(org_id), org_id)) or {}
    return d if isinstance(d, dict) else {}


async def _fo_plan_cfg_set(c, org_id, patch):
    await c.execute(
        "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
        "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now() "
        "WHERE fo_card.org_id = EXCLUDED.org_id",
        "plan:" + str(org_id), org_id, _fo_json.dumps(patch, ensure_ascii=False, default=str))


async def _fo_plan_chat(c, org_id):
    """Чат планов: из настройки; иначе — группа агентства с «план» в названии (бота добавили — чат уже в списке)."""
    cfg = await _fo_plan_cfg(c, org_id)
    if cfg.get("chat_id"):
        return str(cfg["chat_id"]), str(cfg.get("title") or "")
    r = None
    try:
        r = await c.fetchrow("SELECT chat_id, title FROM chat WHERE org_id=$1 AND channel='telegram' AND is_active "
                             "AND chat_id ~ '^-?[0-9]+$' AND title ILIKE '%план%' ORDER BY added_at DESC LIMIT 1", org_id)
    except Exception:
        r = None
    if r:
        await _fo_plan_cfg_set(c, org_id, {"chat_id": str(r["chat_id"]), "title": r["title"] or ""})
        return str(r["chat_id"]), str(r["title"] or "")
    return None, None


async def _fo_plan_send(chat_id, text):
    tok = _fo_env("TG_BOT_TOKEN")
    if not tok or not chat_id or not text:
        return {"ok": False, "description": "нет токена бота или чата"}
    res = await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage",
                                  {"chat_id": str(chat_id), "text": str(text)[:4000], "disable_web_page_preview": True}, tok, 20)
    return res


def _fo_plan_chunks(lines, limit=3800):
    out, cur = [], ""
    for ln in lines:
        if len(cur) + len(ln) + 1 > limit and cur:
            out.append(cur); cur = ""
        cur += (ln + "\n")
    if cur:
        out.append(cur.rstrip("\n"))
    return out


async def _fo_plan_people(c, org_id):
    try:
        rows = await c.fetch("SELECT id, name FROM employee WHERE org_id=$1::uuid AND coalesce(is_active, true) ORDER BY name", str(org_id))
    except Exception:
        rows = await c.fetch("SELECT id, name FROM employee WHERE org_id=$1::uuid ORDER BY name", str(org_id))
    return {str(r["id"]): (r["name"] or "") for r in rows}


async def _fo_plan_clients(c, org_id):
    out = {}
    try:
        for r in await c.fetch("SELECT id, name FROM client WHERE org_id=$1", org_id):
            out[str(r["id"])] = r["name"] or ""
    except Exception:
        pass
    return out


async def _fo_plan_tasks(c, org_id, day):
    """Задачи дня по людям: функции (task) + разовые (fo_task_once). → {emp: [{client, title, dl, done}]}"""
    by = {}
    rows = await c.fetch("SELECT * FROM task WHERE org_id=$1 AND plan_date=$2 AND status <> 'removed' ORDER BY assignee_id, client_id, title",
                         org_id, day)
    fnn = {}
    for r in rows:
        e = str(r["assignee_id"] or "")
        if not e:
            continue
        d = dict(r)
        title = d.get("title") or ""
        fid = d.get("fn_id")
        if fid:
            if str(fid) not in fnn:
                fnn[str(fid)] = await c.fetchval("SELECT name FROM fn WHERE id=$1", fid) or ""
            if fnn[str(fid)]:
                title = fnn[str(fid)]
        dl = None
        for k in ("deadline", "due", "due_at", "due_date", "deadline_at"):
            if d.get(k):
                dl = d[k]; break
        if str(d.get("kind") or "") in ("fix", "deadline", "urgent", "urg") and not dl:
            dl = d.get("kind")
        by.setdefault(e, []).append({"client": str(d.get("client_id") or ""), "title": title, "dl": dl,
                                     "done": str(d.get("status") or "") == "done", "done_at": d.get("done_at"), "src": "task"})
    try:
        once = await c.fetch("SELECT * FROM fo_task_once WHERE org_id=$1 AND day=$2 AND removed_at IS NULL", org_id, day)
    except Exception:
        once = []
    for r in once:
        e = str(r["employee_id"] or "")
        if not e:
            continue
        d = dict(r)
        dl = "дедлайн" if str(d.get("kind") or "") == "fix" else ("срочно" if str(d.get("kind") or "") == "urg" else None)
        by.setdefault(e, []).append({"client": str(d.get("client_id") or ""), "title": d.get("title") or "", "dl": dl,
                                     "done": bool(d.get("done_at")), "done_at": d.get("done_at"), "src": "once"})
    return by


async def _fo_plan_arts(c, org_id, day):
    """Артикулы в работу на день по людям: {emp: {cabinet_id: {"client": id, "skus": [...]}}}"""
    by = {}
    try:
        rows = await c.fetch(
            """SELECT ao.employee_id, a.cabinet_id, a.wb_sku, cb.client_id FROM article_owner ao
                 JOIN article a ON a.id = ao.article_id JOIN cabinet cb ON cb.id = a.cabinet_id JOIN client cl ON cl.id = cb.client_id
                WHERE cl.org_id=$1 AND a.is_active AND ao.weekday=$2 ORDER BY ao.employee_id, a.cabinet_id, a.wb_sku""",
            org_id, day.weekday())
    except Exception:
        rows = []
    for r in rows:
        e = str(r["employee_id"] or "")
        if not e:
            continue
        cab = by.setdefault(e, {}).setdefault(str(r["cabinet_id"]), {"client": str(r["client_id"] or ""), "skus": []})
        cab["skus"].append(str(r["wb_sku"] or ""))
    return by


def _fo_plan_dl(dl):
    if not dl:
        return ""
    if hasattr(dl, "strftime"):
        try:
            return " · дедлайн " + dl.strftime("%d.%m")
        except Exception:
            return ""
    x = str(dl)
    return " · " + ({"fix": "дедлайн", "deadline": "дедлайн", "urgent": "срочно", "urg": "срочно"}.get(x, x))


async def _fo_plan_morning_msgs(c, org_id, day, by_emp=None):
    people, clients = await _fo_plan_people(c, org_id), await _fo_plan_clients(c, org_id)
    cfg = await _fo_plan_cfg(c, org_id)
    tasks = (await _fo_plan_tasks(c, org_id, day)) if cfg.get("send_morning", True) else {}
    arts = (await _fo_plan_arts(c, org_id, day)) if cfg.get("send_arts", True) else {}
    msgs = []
    head = _fo_plan_date(day)
    for e in sorted(set(list(tasks) + list(arts)), key=lambda x: people.get(x, "я")):
        name = people.get(e)
        if not name:
            continue
        tl = tasks.get(e) or []
        if tl:
            lines = [head, "👤 " + name + " — план на день"]
            bycl = {}
            for t in tl:
                bycl.setdefault(t["client"], []).append(t)
            for cid in sorted(bycl, key=lambda k: clients.get(k, "я")):
                lines.append("")
                lines.append("🏪 " + (clients.get(cid) or "Без кабинета"))
                for t in bycl[cid]:
                    lines.append("— " + (t["title"] or "задача") + _fo_plan_dl(t["dl"]))
            lines.append("")
            lines.append("Всего задач: %d" % len(tl))
            msgs += _fo_plan_chunks(lines)
            if by_emp is not None:
                by_emp.setdefault(e, []).extend(_fo_plan_chunks(lines))
        al = arts.get(e) or {}
        if al:
            lines = [head, "👤 " + name + " — 📦 артикулы в работу"]
            for cab, x in sorted(al.items(), key=lambda kv: clients.get(kv[1]["client"], "я")):
                sk = x["skus"]
                lines.append("")
                lines.append("🏪 " + (clients.get(x["client"]) or "Кабинет") + " · %d арт." % len(sk))
                lines.append(", ".join(sk[:80]) + (" … и ещё %d" % (len(sk) - 80) if len(sk) > 80 else ""))
            msgs += _fo_plan_chunks(lines)
            if by_emp is not None:
                by_emp.setdefault(e, []).extend(_fo_plan_chunks(lines))
    if not msgs:
        msgs = [head + "\n🤷 На этот день задач нет."]
    return msgs


async def _fo_plan_evening_msgs(c, org_id, day, cut_hm, by_emp=None):
    people, clients = await _fo_plan_people(c, org_id), await _fo_plan_clients(c, org_id)
    tasks, arts = await _fo_plan_tasks(c, org_id, day), await _fo_plan_arts(c, org_id, day)
    rk = {}
    try:
        rk = _fo_st_load(await c.fetchval("SELECT data FROM fo_state WHERE org_id=$1::uuid AND scope='org' AND key='rkDone'", str(org_id))) or {}
    except Exception:
        rk = {}
    hh, mm = [int(x) for x in str(cut_hm or "17:40").split(":")[:2]]
    cut = _fo_dt.datetime.combine(day, _fo_dt.time(hh, mm)).replace(tzinfo=_FO_MSK)
    msgs = []
    head = _fo_plan_date(day) + " — 📊 итоги дня"
    tot_ok = tot_all = 0
    for e in sorted(set(list(tasks) + list(arts)), key=lambda x: people.get(x, "я")):
        name = people.get(e)
        if not name:
            continue
        tl = tasks.get(e) or []
        lines = [head, "👤 " + name]
        ok = 0
        bycl = {}
        for t in tl:
            bycl.setdefault(t["client"], []).append(t)
        for cid in sorted(bycl, key=lambda k: clients.get(k, "я")):
            lines.append("")
            lines.append("🏪 " + (clients.get(cid) or "Без кабинета"))
            for t in bycl[cid]:
                done = bool(t["done"])
                da = t.get("done_at")
                if done and da is not None:
                    try:
                        if da.tzinfo is None:
                            da = da.replace(tzinfo=_fo_dt.timezone.utc)
                        done = da <= cut
                    except Exception:
                        pass
                ok += 1 if done else 0
                lines.append(("✅ " if done else "❌ ") + (t["title"] or "задача") + _fo_plan_dl(t["dl"]))
        al = arts.get(e) or {}
        if al:
            lines.append("")
            lines.append("📦 Артикулы — работа с РК:")
            for cab, x in sorted(al.items(), key=lambda kv: clients.get(kv[1]["client"], "я")):
                k1, k2 = "%s|%s|%s" % (e, cab, day.isoformat()), "%s|%s|%s" % (e, x["client"], day.isoformat())
                done = bool(rk.get(k1) or rk.get(k2)) if isinstance(rk, dict) else False
                lines.append(("✅ " if done else "❌ ") + (clients.get(x["client"]) or "Кабинет") + " · %d арт." % len(x["skus"]))
        if tl:
            lines.append("")
            lines.append("📊 Выполнено %d из %d" % (ok, len(tl)))
            tot_ok += ok; tot_all += len(tl)
        msgs += _fo_plan_chunks(lines)
        if by_emp is not None:
            by_emp.setdefault(e, []).extend(_fo_plan_chunks(lines))
    if not msgs:
        msgs = [head + "\n🤷 Задач на день не было."]
    elif tot_all:
        msgs.append(head + "\n📊 Итого по команде: выполнено %d из %d (%d%%)" % (tot_ok, tot_all, round(tot_ok * 100 / tot_all)))
    return msgs


async def _fo_plan_week_msgs(c, org_id, mon):
    people, clients = await _fo_plan_people(c, org_id), await _fo_plan_clients(c, org_id)
    items = []
    try:
        await _fo_mt_migrate(c, org_id)
        for r in await c.fetch("SELECT * FROM fo_meet WHERE org_id=$1::uuid", str(org_id)):
            for x in await _fo_mt_week(c, org_id, r["client_id"], mon, r):
                items.append((x["day"], str(x["time"]), str(r["client_id"]), str(x.get("host") or ""), int(x.get("minutes") or 60)))
    except Exception as _e:
        items = []
    items.sort(key=lambda t: (t[0], t[1]))
    sun = mon + _fo_dt.timedelta(days=6)
    lines = ["🗓 План планёрок на неделю %02d.%02d–%02d.%02d" % (mon.day, mon.month, sun.day, sun.month)]
    if not items:
        lines.append("Согласованных планёрок на неделю пока нет.")
    last = None
    for d, tm, cid, host, mins in items:
        if d != last:
            lines.append("")
            lines.append("📅 %s %02d.%02d" % (_FO_DOW_SHORT[d.weekday()], d.day, d.month))
            last = d
        lines.append("🕐 %s — 🏪 %s%s" % (tm, clients.get(cid) or "кабинет", (" · 👤 " + people[host]) if host in people else ""))
    return _fo_plan_chunks(lines)


async def _fo_plan_run(c, org_id, what, day=None, force=False):
    """Отправка в чат планов. what: morning | evening | week. Возвращает {sent, chat, errors}."""
    chat, title = await _fo_plan_chat(c, org_id)
    if not chat:
        return {"ok": False, "sent": 0, "chat": None, "why": "в агентстве нет группы с «план» в названии, куда добавлен бот"}
    cfg = await _fo_plan_cfg(c, org_id)
    day = day or _fo_mt_now().date()
    if what == "morning":
        msgs = await _fo_plan_morning_msgs(c, org_id, day)
    elif what == "evening":
        msgs = await _fo_plan_evening_msgs(c, org_id, day, cfg.get("eve_cut") or _FO_PLAN_DEF["eve_cut"])
    else:
        msgs = await _fo_plan_week_msgs(c, org_id, _fo_mt_mon(day))
    sent, errs = 0, []
    for m in msgs:
        r = await _fo_plan_send(chat, m)
        if r.get("ok"):
            sent += 1
        else:
            errs.append(str(r.get("description") or r)[:160])
        await _fo_aio.sleep(0.4)
    await _fo_plan_log(c, org_id, {"what": what, "day": day.isoformat(), "sent": sent, "of": len(msgs),
                                   "err": (errs[0] if errs else ""), "chat": title or chat})
    return {"ok": not errs, "sent": sent, "chat": title or chat, "errors": errs, "messages": len(msgs)}


async def _fo_plan_team_tg(c, org_id):
    """280: сотрудник → его Telegram (привязан через бота: почта + код). Только им бот может писать в личку."""
    out = {}
    try:
        for r in await c.fetch("SELECT e.id, cd.data->>'tg_id' AS tg_id FROM employee e JOIN fo_card cd ON cd.kind='employee' "
                               "AND cd.ref_id=e.id::text AND cd.org_id::text=e.org_id::text WHERE e.org_id=$1::uuid "
                               "AND coalesce(cd.data->>'tg_id','') ~ '^[0-9]+$'", str(org_id)):
            out[str(r["id"])] = str(r["tg_id"])
    except Exception:
        pass
    return out


async def _fo_plan_team_run(c, org_id, what, day=None):
    """280: «Разослать команде» — каждому сотруднику в личку его план дня (what=morning) или его итоги (evening)."""
    day = day or _fo_mt_now().date()
    cfg = await _fo_plan_cfg(c, org_id)
    by = {}
    if what == "evening":
        await _fo_plan_evening_msgs(c, org_id, day, cfg.get("eve_cut") or _FO_PLAN_DEF["eve_cut"], by_emp=by)
    else:
        what = "morning"
        await _fo_plan_morning_msgs(c, org_id, day, by_emp=by)
    tg, names = await _fo_plan_team_tg(c, org_id), await _fo_plan_people(c, org_id)
    sent, people, errs, miss = 0, 0, [], []
    for e, msgs in by.items():
        t = tg.get(e)
        if not t:
            miss.append(names.get(e) or e)
            continue
        ok1 = False
        for m in msgs:
            r = await _fo_plan_send(t, m)
            if r.get("ok"):
                sent += 1; ok1 = True
            else:
                errs.append((names.get(e) or "") + ": " + str(r.get("description") or r)[:120])
            await _fo_aio.sleep(0.35)
        people += 1 if ok1 else 0
    await _fo_plan_log(c, org_id, {"what": "team_" + what, "day": day.isoformat(), "sent": sent,
                                   "of": sum(len(v) for v in by.values()), "err": (errs[0] if errs else ""),
                                   "chat": "в личку: %d чел." % people + (" · без Telegram: " + ", ".join(miss[:6]) if miss else "")})
    return {"ok": not errs, "sent": sent, "people": people, "miss": miss, "errors": errs[:5], "chat": "личка сотрудников"}


async def _fo_plan_team_tick(c, org, cfg, today, hm):
    """280: расписание рассылки команде: каждый день в своё время или разово (дата + время)."""
    if not cfg.get("team_on"):
        return
    if (cfg.get("team_mode") or "daily") == "once":
        on = cfg.get("team_once") or {}
        if isinstance(on, dict) and on.get("day") and on.get("at") and (today.isoformat(), hm) >= (str(on["day"]), str(on["at"])):
            await _fo_plan_cfg_set(c, org, {"team_once": {}, "team_once_done": dict(on, done=today.isoformat() + " " + hm)})
            for w in (["morning", "evening"] if on.get("what") == "both" else [on.get("what") or "morning"]):
                await _fo_plan_team_run(c, org, w, today)
        return
    if today.weekday() >= 5 and not cfg.get("team_wkend"):
        return
    tm = cfg.get("team_morning") or cfg.get("morning") or _FO_PLAN_DEF["morning"]
    te = cfg.get("team_eve") or cfg.get("eve_send") or _FO_PLAN_DEF["eve_send"]
    if cfg.get("team_send_m", True) and hm >= tm and cfg.get("last_team_morning") != today.isoformat():
        await _fo_plan_cfg_set(c, org, {"last_team_morning": today.isoformat()})
        await _fo_plan_team_run(c, org, "morning", today)
    if cfg.get("team_send_e", True) and hm >= te and cfg.get("last_team_evening") != today.isoformat():
        await _fo_plan_cfg_set(c, org, {"last_team_evening": today.isoformat()})
        await _fo_plan_team_run(c, org, "evening", today)


async def _fo_plan_tick():
    now = _fo_mt_now()
    today = now.date()
    hm = now.strftime("%H:%M")
    async with pool().acquire() as c:
        orgs = [r["id"] for r in await c.fetch("SELECT id FROM org")]
    for org in orgs:
        try:
            async with pool().acquire() as c:
                chat, _t = await _fo_plan_chat(c, org)
                if not chat and not (await _fo_plan_cfg(c, org)).get("team_on"):     # 280
                    continue
                # 270: сервис в несколько процессов — замок на агентство, настройки читаем после замка
                if not await c.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", "fo-plan:" + str(org)):
                    continue
                try:
                    await _fo_plan_tick_org(c, org, today, hm)
                finally:
                    try:
                        await c.execute("SELECT pg_advisory_unlock(hashtext($1))", "fo-plan:" + str(org))
                    except Exception:
                        pass
        except Exception as e:
            try:
                print("fo_plan:", str(e)[:200])
            except Exception:
                pass


async def _fo_plan_tick_org(c, org, today, hm):
                if not await _fo_bots_enabled(c, org):          # 275: модуль «Чат-боты» не подключён
                    return
                cfg = await _fo_plan_cfg(c, org)
                # 268: очередь ручных отправок (ставит собственник кнопкой или шаг при выкладке)
                sn = cfg.get("send_now") or []
                if isinstance(sn, list) and sn:
                    left = []
                    for it in sn:
                        what = (it or {}).get("what") if isinstance(it, dict) else str(it)
                        at = (it or {}).get("at") if isinstance(it, dict) else None
                        if what not in ("morning", "evening", "week"):
                            continue
                        if at and hm < str(at):
                            left.append(it); continue
                        dday = today                        # 269: send_now day — день, за который слать
                        try:
                            if isinstance(it, dict) and it.get("day"):
                                dday = _fo_dt.date.fromisoformat(str(it["day"]))
                        except Exception:
                            dday = today
                        try:
                            await _fo_plan_run(c, org, what, dday, force=True)
                        except Exception as _e:
                            try: print("fo_plan send_now:", str(_e)[:200])
                            except Exception: pass
                    await _fo_plan_cfg_set(c, org, {"send_now": left})
                    cfg["send_now"] = left
                if cfg.get("off"):
                    return
                if today.weekday() < 5:
                    if hm >= (cfg.get("morning") or _FO_PLAN_DEF["morning"]) and cfg.get("last_morning") != today.isoformat():
                        await _fo_plan_cfg_set(c, org, {"last_morning": today.isoformat()})
                        if cfg.get("send_morning", True) or cfg.get("send_arts", True):
                            await _fo_plan_run(c, org, "morning", today)
                    if hm >= (cfg.get("eve_send") or _FO_PLAN_DEF["eve_send"]) and cfg.get("last_evening") != today.isoformat():
                        await _fo_plan_cfg_set(c, org, {"last_evening": today.isoformat()})
                        if cfg.get("send_evening", True):
                            await _fo_plan_run(c, org, "evening", today)
                try:                                             # 280: рассылка команде — каждому в личку
                    await _fo_plan_team_tick(c, org, cfg, today, hm)
                except Exception as _e:
                    try: print("fo_plan team:", str(_e)[:200])
                    except Exception: pass
                mon = _fo_mt_mon(today)
                if today.weekday() == 0 and hm >= (cfg.get("morning") or _FO_PLAN_DEF["morning"]) and cfg.get("last_week") != mon.isoformat() and cfg.get("send_week", True):
                    await _fo_plan_cfg_set(c, org, {"last_week": mon.isoformat()})
                    await _fo_plan_run(c, org, "week", today)


async def _fo_plan_loop():
    await _fo_aio.sleep(50)
    while True:
        try:
            await _fo_plan_tick()
        except Exception:
            pass
        await _fo_aio.sleep(60)


@router.on_event("startup")
async def _fo_plan_boot():
    t = _FO_PLAN_LOOP.get("task")
    if t is None or t.done():
        try:
            _FO_PLAN_LOOP["task"] = _fo_aio.get_running_loop().create_task(_fo_plan_loop())
        except Exception:
            pass


# ── 275: модуль «Чат-боты» ──
_FO_BOT_ME = {}


async def _fo_bots_cfg(c, org):
    d = _fo_st_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1 AND org_id=$2",
                                     "bots:" + str(org), org)) or {}
    return d if isinstance(d, dict) else {}


async def _fo_bots_set(c, org, patch):
    await c.execute(
        "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
        "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now() "
        "WHERE fo_card.org_id = EXCLUDED.org_id",
        "bots:" + str(org), org, _fo_json.dumps(patch, ensure_ascii=False, default=str))


async def _fo_bots_enabled(c, org):
    try:
        d = await _fo_bots_cfg(c, org)
        if "enabled" in d:
            return bool(d.get("enabled"))
        # 276: агентство уже работает с ботами (группа плана или сообщения из чатов клиентов) — модуль подключён
        used = await c.fetchval("SELECT 1 FROM fo_card WHERE kind='org' AND ref_id=$1 AND coalesce(data->>'chat_id','') <> ''",
                                "plan:" + str(org))
        if not used:
            try:
                used = await c.fetchval("SELECT 1 FROM fo_chat_msg WHERE org_id=$1 AND tg_chat_id<>'test' LIMIT 1", org)
            except Exception:
                used = None
        if used:
            await _fo_bots_set(c, org, {"enabled": True})
            return True
        return False
    except Exception:
        return False


async def _fo_plan_log(c, org, item):
    try:
        cfg = await _fo_plan_cfg(c, org)
        log = cfg.get("log") if isinstance(cfg.get("log"), list) else []
        item = dict(item); item["at"] = _fo_mt_now().strftime("%d.%m %H:%M")
        log = [item] + log
        await _fo_plan_cfg_set(c, org, {"log": log[:40]})
    except Exception:
        pass


async def _fo_bot_me(tok):
    if not tok:
        return {}
    x = _FO_BOT_ME.get(tok)
    if x and _fo_time.time() - x[0] < 3600:
        return x[1]
    r = await _fo_aio.to_thread(_fo_tg_api_sync, "getMe", {}, tok, 10)
    me = (r.get("result") or {}) if r.get("ok") else {}
    _FO_BOT_ME[tok] = (_fo_time.time(), me)
    return me


def _fo_bot_toks():
    main = _fo_env("TG_BOT_TOKEN")
    return {"main": main, "meet": _fo_env("TG_MEET_BOT_TOKEN") or "", "report": _fo_env("TG_REPORT_BOT_TOKEN") or ""}


@router.get("/bots")
async def fo_bots(p: Principal = Depends(max_level(1))):
    toks = _fo_bot_toks()
    bots = []
    for k in ("main", "meet", "report"):
        me = await _fo_bot_me(toks[k]) if toks[k] else {}
        bots.append({"key": k, "username": me.get("username") or "", "name": me.get("first_name") or "",
                     "online": bool(me.get("id")), "token": bool(toks[k])})
    since = _fo_dt.datetime.now(_fo_dt.timezone.utc) - _fo_dt.timedelta(days=7)
    out = {"bots": bots}
    async with pool().acquire() as c:
        out["enabled"] = await _fo_bots_enabled(c, p.org_id)
        bc = await _fo_bots_cfg(c, p.org_id)
        out["requested_at"] = bc.get("requested_at")
        main = {}
        try:
            main["msgs"] = int(await c.fetchval("SELECT count(*) FROM fo_chat_msg WHERE org_id=$1 AND msg_at >= $2 AND tg_chat_id<>'test'",
                                                p.org_id, since) or 0)
        except Exception:
            main["msgs"] = None
        try:
            ai = {}
            for r in await c.fetch("SELECT status, count(*) AS n FROM fo_ai_task WHERE org_id=$1 AND created_at >= $2 GROUP BY status",
                                   p.org_id, since):
                ai[str(r["status"])] = int(r["n"])
            main["ai"] = ai
        except Exception:
            main["ai"] = {}
        try:
            cc = await c.fetchrow("SELECT count(DISTINCT cc.client_id) AS clients, count(*) FILTER (WHERE ch.chat_id ~ '^-?[0-9]+$') AS num, "
                                  "count(*) AS total FROM chat ch JOIN client_chat cc ON cc.chat_pk=ch.id "
                                  "WHERE ch.org_id=$1 AND cc.kind='client'", p.org_id)
            main["chats"] = {"clients": int(cc["clients"] or 0), "with_number": int(cc["num"] or 0), "total": int(cc["total"] or 0)}
        except Exception:
            main["chats"] = {}
        try:
            _ids, label, _e = await _fo_ai_approvers(c, p.org_id)
            main["approvers"] = label
        except Exception:
            main["approvers"] = ""
        try:
            pc = await _fo_plan_cfg(c, p.org_id)
            chat, title = await _fo_plan_chat(c, p.org_id)
            main["plan"] = {"chat": title or chat, "morning": pc.get("morning") or _FO_PLAN_DEF["morning"],
                            "eve_send": pc.get("eve_send") or _FO_PLAN_DEF["eve_send"], "off": bool(pc.get("off")),
                            "cmds_on": not pc.get("cmds_off")}
            main["log"] = (pc.get("log") or [])[:40] if isinstance(pc.get("log"), list) else []
        except Exception:
            main["plan"], main["log"] = {}, []
        try:
            main["owner_tg"] = bool(await _fo_plan_owner_tg(c, p.org_id))
        except Exception:
            main["owner_tg"] = False
        out["main"] = main
        meet = {}
        try:
            for r in await c.fetch("SELECT status, count(*) AS n FROM fo_meet WHERE org_id=$1::uuid GROUP BY status", str(p.org_id)):
                meet[str(r["status"])] = int(r["n"])
        except Exception:
            pass
        try:
            meet["week_agreed"] = int(await c.fetchval("SELECT count(*) FROM fo_meet_occ WHERE org_id=$1::uuid AND status='agreed' "
                                                       "AND day BETWEEN $2 AND $3", str(p.org_id), _fo_mt_mon(),
                                                       _fo_mt_mon() + _fo_dt.timedelta(days=6)) or 0)
        except Exception:
            pass
        out["meet"] = meet
        rep = {}
        try:
            rep["reports"] = int(await c.fetchval("SELECT count(*) FROM fo_task_report WHERE org_id=$1 AND made_at >= $2", p.org_id, since) or 0)
        except Exception:
            rep["reports"] = None
        try:
            q = await c.fetchrow("SELECT count(*) FILTER (WHERE sent_at IS NULL) AS wait, count(*) FILTER (WHERE error IS NOT NULL) AS err "
                                 "FROM outbox WHERE org_id=$1", p.org_id)
            rep["queue"] = {"wait": int(q["wait"] or 0), "err": int(q["err"] or 0)}
        except Exception:
            pass
        out["report"] = rep
    return out


@router.get("/bots/ai")
async def fo_bots_ai(p: Principal = Depends(max_level(1))):
    """279: чему научен ИИ — для чтения собственником."""
    since = _fo_dt.datetime.now(_fo_dt.timezone.utc) - _fo_dt.timedelta(days=7)
    out = {"model": _fo_env("YC_MODEL") or "yandexgpt-lite/latest", "ready": _fo_ai_ready(),
           "ctx_n": _FO_AI_CTX_N, "dup_days": _FO_AI_DUP_DAYS, "sys": _FO_AI_SYS,
           "skip": _FO_AI_SKIP.pattern, "noise": [r.pattern for r in _FO_NOISE_RX],
           "meet_sys": globals().get("_FO_MT_SYS") or "", "meet_sys2": globals().get("_FO_MT_SYS2") or ""}
    async with pool().acquire() as c:
        try:
            st = await _fo_ai_settings(c, p.org_id)
            out["rules"] = [str(r) for r in (st.get("rules") or [])]
        except Exception:
            out["rules"] = []
        try:
            stat = {}
            for r in await c.fetch("SELECT coalesce(ai_state,'—') AS s, count(*) AS n FROM fo_chat_msg WHERE org_id=$1 AND msg_at >= $2 "
                                   "AND tg_chat_id<>'test' GROUP BY 1", p.org_id, since):
                stat[str(r["s"])] = int(r["n"])
            out["week"] = stat
            out["skip_notes"] = [{"note": r["ai_note"], "n": int(r["n"])} for r in await c.fetch(
                "SELECT ai_note, count(*) AS n FROM fo_chat_msg WHERE org_id=$1 AND msg_at >= $2 AND ai_state='skip' "
                "AND tg_chat_id<>'test' GROUP BY 1 ORDER BY 2 DESC LIMIT 8", p.org_id, since)]
        except Exception:
            out["week"], out["skip_notes"] = {}, []
    return out


@router.get("/bots/chats")
async def fo_bots_chats(bot: str = "main", p: Principal = Depends(max_level(1))):
    """281: по кабинетам и по команде. У каждого клиента два чата: «Чат с клиентом» (команда + клиент, kind=client) и
    «Чат МПВ» (зеркало чата с клиентом — только команда, kind=mpv). Внесён ли номером (иначе бот его не видит), сидит ли
    бот, последнее сообщение, сообщений и задач от ИИ за 7 дней. По команде — привязан ли Telegram, план и факт на сегодня."""
    bk = bot if bot in ("main", "meet", "report") else "main"
    tok = _fo_bot_toks().get(bk)
    me = await _fo_bot_me(tok) if tok else {}
    since = _fo_dt.datetime.now(_fo_dt.timezone.utc) - _fo_dt.timedelta(days=7)
    kinds = ("client",) if bk == "meet" else ("client", "mpv")
    team, team_on = [], False
    async with pool().acquire() as c:
        cls = await c.fetch("SELECT id, name FROM client WHERE org_id=$1 ORDER BY name", p.org_id)
        chs = await c.fetch("SELECT cc.client_id, cc.kind, ch.id AS pk, ch.chat_id, ch.title FROM client_chat cc "
                            "JOIN chat ch ON ch.id = cc.chat_pk WHERE ch.org_id=$1 ORDER BY ch.id", p.org_id)
        last = {}
        try:
            for r in await c.fetch("SELECT chat_pk, max(msg_at) AS at, count(*) FILTER (WHERE msg_at >= $2) AS n7 "
                                   "FROM fo_chat_msg WHERE org_id=$1 AND tg_chat_id<>'test' GROUP BY chat_pk", p.org_id, since):
                last[r["chat_pk"]] = (r["at"], int(r["n7"] or 0))
        except Exception:
            last = {}
        ai = {}
        try:
            for r in await c.fetch("SELECT client_id, count(*) AS n, count(*) FILTER (WHERE status='pending') AS wait "
                                   "FROM fo_ai_task WHERE org_id=$1 AND created_at >= $2 GROUP BY client_id", p.org_id, since):
                ai[str(r["client_id"])] = {"n": int(r["n"] or 0), "wait": int(r["wait"] or 0)}
        except Exception:
            ai = {}
        try:
            day = _fo_mt_now().date()
            cfg = await _fo_plan_cfg(c, p.org_id)
            team_on = bool(cfg.get("team_on"))
            names, tgm = await _fo_plan_people(c, p.org_id), await _fo_plan_team_tg(c, p.org_id)
            tk, ar = await _fo_plan_tasks(c, p.org_id, day), await _fo_plan_arts(c, p.org_id, day)
            for e, n in sorted(names.items(), key=lambda kv: kv[1] or "я"):
                tl, al = tk.get(e) or [], (ar.get(e) or {})
                cabs = set([t["client"] for t in tl if t.get("client")] + [x["client"] for x in al.values() if x.get("client")])
                team.append({"employee_id": e, "name": n, "tg": bool(tgm.get(e)), "tasks": len(tl),
                             "done": sum(1 for t in tl if t.get("done")), "cabs": len(cabs),
                             "arts": sum(len(x["skus"]) for x in al.values())})
        except Exception:
            pass
    sem = _fo_aio.Semaphore(6)

    async def member(chat_id):
        if not me.get("id"):
            return None, "бот не на связи"
        async with sem:
            cm = await _fo_aio.to_thread(_fo_tg_api_sync, "getChatMember", {"chat_id": chat_id, "user_id": me["id"]}, tok, 10)
        st = ((cm.get("result") or {}).get("status") or "") if cm and cm.get("ok") else ""
        return st in ("member", "administrator", "creator"), (st or str((cm or {}).get("description") or "")[:60])
    items = [r for r in chs if r["kind"] in kinds]
    num = [r for r in items if re.match(r"^-?\d+$", str(r["chat_id"] or ""))]
    res = await _fo_aio.gather(*[member(str(r["chat_id"])) for r in num])
    mem = {r["pk"]: x for r, x in zip(num, res)}
    by = {}
    for r in items:
        la = last.get(r["pk"]) or (None, 0)
        inn, st = mem.get(r["pk"], (None, ""))
        by.setdefault(str(r["client_id"]), {}).setdefault(r["kind"], []).append({
            "title": r["title"] or "", "num": r["pk"] in mem, "in": inn, "status": st,
            "last": la[0].isoformat() if la[0] else None, "n7": la[1]})
    rows = [{"client_id": str(cl["id"]), "client": cl["name"] or "", "chats": by.get(str(cl["id"]), {}),
             "ai": ai.get(str(cl["id"]), {"n": 0, "wait": 0})} for cl in cls]
    flat = [{"client": r["client"], "chat": x.get("title") or "", "in": bool(x.get("in")), "status": x.get("status") or ""}
            for r in rows for x in r["chats"].get("client", []) if x.get("num")]
    return {"bot": bk, "online": bool(me.get("id")), "username": me.get("username"), "kinds": list(kinds),
            "rows": rows, "team": team, "team_on": team_on, "chats": flat}


@router.post("/bots/request")
async def fo_bots_request(p: Principal = Depends(max_level(1))):
    async with pool().acquire() as c:
        await _fo_bots_set(c, p.org_id, {"requested_at": _fo_mt_now().strftime("%d.%m.%Y %H:%M")})
        org = await c.fetchrow("SELECT name FROM org WHERE id=$1", p.org_id)
        me = await c.fetchrow("SELECT email, display_name FROM app_user WHERE id=$1", _fo_uid(p))
        admins = [r["email"] for r in await c.fetch("SELECT u.email FROM app_user u JOIN role r ON r.code=u.role_code "
                                                     "WHERE r.level=0 AND u.is_active AND u.email IS NOT NULL")]
    sent = 0
    for em in admins:
        try:
            if await _fo_send(em, "Заявка: модуль «Чат-боты»",
                              "Агентство: %s\nСобственник: %s (%s)\nПросит подключить модуль «Чат-боты»." %
                              ((org or {}).get("name") if org else "", (me or {}).get("display_name") if me else "", (me or {}).get("email") if me else "")):
                sent += 1
        except Exception:
            pass
    return {"ok": True, "notified": sent}


class FoBotsAdmIn(_FoBM):
    org_id: str
    enabled: bool


@router.get("/admin/bots")
async def fo_admin_bots(p: Principal = Depends(max_level(0))):
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT o.id, o.name, cd.data FROM org o LEFT JOIN fo_card cd ON cd.kind='org' AND cd.ref_id='bots:'||o.id::text "
                             "ORDER BY o.created_at")
    out = []
    for r in rows:
        d = _fo_st_load(r["data"]) or {}
        out.append({"org_id": str(r["id"]), "name": r["name"], "enabled": bool(d.get("enabled")), "requested_at": d.get("requested_at")})
    return out


@router.post("/admin/bots")
async def fo_admin_bots_set(body: FoBotsAdmIn, p: Principal = Depends(max_level(0))):
    import uuid as _fo_uu
    oid = _fo_uu.UUID(str(body.org_id))
    async with pool().acquire() as c:
        await _fo_bots_set(c, oid, {"enabled": bool(body.enabled)})
    return {"ok": True}


# ── 273: команды собственника в группе плана ──
_FO_PLAN_CMD_RX = re.compile(r"^(факт\s+плана?\s+работы|план\s+работы)\s+(.+?)(?:\s+за\s+(\S+))?$", re.I)


def _fo_plan_norm(x):
    x = str(x or "").lower().replace("ё", "е")
    x = re.sub(r"[«»\"'`.,;:!?()]", " ", x)
    x = re.sub(r"(^|\s)(ип|ооо|ао|зао|пао)(?=\s|$)", " ", x)
    return " ".join(x.split())


def _fo_plan_cmd_date(word, today):
    w = str(word or "").strip().lower().rstrip(".")
    if w in ("", "сегодня"):
        return today
    if w == "вчера":
        return today - _fo_dt.timedelta(days=1)
    if w == "завтра":
        return today + _fo_dt.timedelta(days=1)
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", w)
    if not m:
        return None
    y = int(m.group(3)) if m.group(3) else today.year
    if y < 100:
        y += 2000
    try:
        return _fo_dt.date(y, int(m.group(2)), int(m.group(1)))
    except Exception:
        return None


async def _fo_plan_owner_tg(c, org):
    """Telegram собственника агентства (привязан через бота: почта входа → код)."""
    try:
        rows = await c.fetch("SELECT ref_id, data->>'tg_id' AS tg FROM fo_card WHERE kind='employee' AND org_id=$1 "
                             "AND coalesce(data->>'tg_id','') ~ '^[0-9]+$'", org)
    except Exception:
        return []
    out = []
    for r in rows:
        ref = str(r["ref_id"])
        uid = None
        try:
            uid = await c.fetchval("SELECT user_id FROM employee WHERE id::text=$1", ref)
        except Exception:
            uid = None
        try:
            lvl = await c.fetchval("SELECT r.level FROM app_user u JOIN role r ON r.code=u.role_code WHERE u.id::text=$1",
                                   str(uid or ref))
        except Exception:
            lvl = None
        if lvl is not None and int(lvl) == 1:
            out.append(str(r["tg"]))
    return out


async def _fo_plan_reply(chat_id, lines, reply_to=None):
    tok = _fo_env("TG_BOT_TOKEN")
    if not tok:
        return
    for i, ch in enumerate(_fo_plan_chunks(lines)):
        prm = {"chat_id": str(chat_id), "text": ch, "disable_web_page_preview": True}
        if i == 0 and reply_to:
            prm["reply_to_message_id"] = int(reply_to)
            prm["allow_sending_without_reply"] = True
        await _fo_aio.to_thread(_fo_tg_api_sync, "sendMessage", prm, tok, 20)
        await _fo_aio.sleep(0.3)


async def _fo_plan_cmd(msg, bot=""):
    """True — сообщение из группы плана (обработано или пропущено); False — это не группа плана."""
    chat = msg.get("chat") or {}
    tg = str(chat.get("id") or "")
    if not tg:
        return False
    async with pool().acquire() as c:
        row = await c.fetchrow("SELECT org_id, data FROM fo_card WHERE kind='org' AND ref_id LIKE 'plan:%' "
                               "AND data->>'chat_id'=$1 LIMIT 1", tg)
        if not row:
            return False
        if bot == "meet":
            return True
        frm = msg.get("from") or {}
        if frm.get("is_bot"):
            return True
        raw = str(msg.get("text") or "").strip()
        t = " ".join(raw.replace("ё", "е").replace("Ё", "Е").split()).rstrip(".!?")
        m = _FO_PLAN_CMD_RX.match(t)
        if not m:
            return True                               # не команда — бот молчит
        org = row["org_id"]
        cfg = _fo_st_load(row["data"]) or {}
        if isinstance(cfg, dict) and cfg.get("cmds_off"):
            return True
        if not await _fo_bots_enabled(c, org):                 # 275
            return True
        mid = msg.get("message_id")
        owners = await _fo_plan_owner_tg(c, org)
        if str(frm.get("id") or "") not in owners:
            await _fo_plan_reply(tg, ["Команды плана выполняются только для собственника агентства.",
                                      "Если вы собственник, а бот вас не узнал: напишите боту в личку почту, под которой входите "
                                      "в сервис, — он пришлёт код на почту, перешлите код ему."], mid)
            return True
        fact = m.group(1).lower().startswith("факт")
        today = _fo_mt_now().date()
        day = _fo_plan_cmd_date(m.group(3), today)
        if day is None:
            await _fo_plan_reply(tg, ["Не понял дату «%s». Пишите так: «План работы ИП Петров за 01.10»." % (m.group(3) or "")], mid)
            return True
        q = _fo_plan_norm(m.group(2))
        clients = await _fo_plan_clients(c, org)
        norm = {cid: _fo_plan_norm(nm) for cid, nm in clients.items()}
        cids = [cid for cid, nn in norm.items() if nn and nn == q]
        if not cids:
            import difflib as _fo_dl
            names = {}
            for cid, nn in norm.items():
                names.setdefault(nn, clients[cid])
            sim = _fo_dl.get_close_matches(q, list(names), n=6, cutoff=0.45)
            sub = [nn for nn in names if q and (q in nn or nn in q) and nn not in sim]
            pick = [names[x] for x in (sim + sub)][:6]
            lines = ["Не нашёл клиента «%s»." % m.group(2).strip()]
            if pick:
                lines.append("Похожие: " + ", ".join(pick))
            else:
                lines.append("Клиенты агентства: " + ", ".join(sorted(clients.values())[:40]))
            lines.append("Напишите команду ещё раз с точным названием.")
            await _fo_plan_reply(tg, lines, mid)
            return True
        cname = clients[cids[0]]
        people = await _fo_plan_people(c, org)
        tasks = await _fo_plan_tasks(c, org, day)
        arts = await _fo_plan_arts(c, org, day)
        rk = {}
        if fact:
            try:
                rk = _fo_st_load(await c.fetchval("SELECT data FROM fo_state WHERE org_id=$1::uuid AND scope='org' AND key='rkDone'",
                                                  str(org))) or {}
            except Exception:
                rk = {}
    cset = set(cids)
    if fact and day > today:
        await _fo_plan_reply(tg, ["%s — день ещё не наступил, факта нет." % _fo_plan_date(day),
                                  "План: «План работы %s за %02d.%02d»" % (cname, day.day, day.month)], mid)
        return True
    head = _fo_plan_date(day)
    if fact:
        head += " — 📊 факт" + ((" на %s" % _fo_mt_now().strftime("%H:%M")) if day == today else " за день")
    lines = [head, "🏪 " + cname + (" — факт плана работы" if fact else " — план работы")]
    emps = set()
    for e, tl in tasks.items():
        if any(t["client"] in cset for t in tl):
            emps.add(e)
    for e, cabs in arts.items():
        if any(x["client"] in cset for x in cabs.values()):
            emps.add(e)
    total = ok = 0
    for e in sorted(emps, key=lambda x: people.get(x, "я")):
        if not people.get(e):
            continue
        lines.append("")
        lines.append("👤 " + people[e])
        for t in [t for t in (tasks.get(e) or []) if t["client"] in cset]:
            total += 1
            if fact:
                ok += 1 if t["done"] else 0
                lines.append(("✅ " if t["done"] else "❌ ") + (t["title"] or "задача") + _fo_plan_dl(t["dl"]))
            else:
                lines.append("— " + (t["title"] or "задача") + _fo_plan_dl(t["dl"]))
        for cab, x in (arts.get(e) or {}).items():
            if x["client"] not in cset:
                continue
            sk = x["skus"]
            if fact:
                k1, k2 = "%s|%s|%s" % (e, cab, day.isoformat()), "%s|%s|%s" % (e, x["client"], day.isoformat())
                done = bool(rk.get(k1) or rk.get(k2)) if isinstance(rk, dict) else False
                lines.append(("✅ " if done else "❌ ") + "📦 работа с РК · %d арт." % len(sk))
            else:
                lines.append("📦 Артикулы в работу (%d): " % len(sk) + ", ".join(sk[:80]) + (" … и ещё %d" % (len(sk) - 80) if len(sk) > 80 else ""))
    if not emps:
        lines.append("")
        lines.append("🤷 На этот день задач по клиенту нет.")
    else:
        lines.append("")
        lines.append(("📊 Выполнено %d из %d" % (ok, total)) if fact else ("Всего задач: %d" % total))
    await _fo_plan_reply(tg, lines, mid)
    try:
        async with pool().acquire() as c2:
            await _fo_plan_log(c2, org, {"what": "cmd", "text": raw[:80], "sent": 1, "of": 1, "err": ""})
    except Exception:
        pass
    return True


async def _fo_plan_route(msg, bot=""):
    try:
        if await _fo_plan_cmd(msg, bot):
            return
    except Exception as e:
        try:
            print("fo_plan_cmd:", str(e)[:200])
        except Exception:
            pass
    await _fo_ai_on_msg(msg, bot)


class FoPlanSendIn(_FoBM):
    what: str = "morning"          # morning | evening | week
    day: str | None = None


class FoPlanSetIn(_FoBM):
    morning: str | None = None
    eve_cut: str | None = None
    eve_send: str | None = None
    off: bool | None = None
    chat_id: str | None = None
    title: str | None = None
    send_morning: bool | None = None
    send_arts: bool | None = None
    send_evening: bool | None = None
    send_week: bool | None = None
    cmds_off: bool | None = None
    team_on: bool | None = None
    team_mode: str | None = None
    team_morning: str | None = None
    team_eve: str | None = None
    team_wkend: bool | None = None
    team_send_m: bool | None = None
    team_send_e: bool | None = None
    team_once_day: str | None = None
    team_once_at: str | None = None
    team_once_what: str | None = None
    team_once_clear: bool | None = None


# ══ 282: ЭКОНОМИКА КЛИЕНТОВ И ПРОДЖЕКТОВ (Виталий 05.10) ══════════════
# Источники — только то, что уже есть в сервисе: платёж и «работаем с» — карточка клиента; проджект — карточка
# клиента (pm), иначе проджект, который ведёт больше функций кабинета, иначе единственный проджект агентства;
# часы — задачи сервиса (функции и разовые) за последние 4 недели и 2 недели вперёд, пересчёт на месяц (21 р. д.);
# цена часа — оклад сотрудника / (рабочий день × 21); оклада нет — середина вилки грейда (помечаем).
_FO_ECON_BUCKETS = [(0, 40000, "до 40 тыс"), (40000, 70000, "40–70 тыс"), (70000, 100000, "70–100 тыс"), (100000, None, "100 тыс и выше")]
_FO_GRADE_MID = {"assist": 27500, "jun": 27500, "mid": 50000, "head": 95000, "pm": 110000}
_FO_ECON_ART_MIN = {"A": 5, "B": 4, "C": 3}          # 284: минут на артикул за касание — как на экране АОД


def _fo_econ_num(v):
    try:
        x = float(str(v).replace(" ", "").replace(",", ".")) if v not in (None, "") else 0.0
        return x if x == x else 0.0
    except Exception:
        return 0.0


def _fo_econ_since(v):
    m = re.match(r"^(\d{4})-(\d{1,2})", str(v or "").strip())
    if not m:
        m2 = re.match(r"^(\d{1,2})[./](\d{4})$", str(v or "").strip())
        if not m2:
            return None
        return int(m2.group(2)), int(m2.group(1))
    return int(m.group(1)), int(m.group(2))


async def _fo_econ_cfg(c, org_id):
    d = _fo_st_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1 AND org_id=$2",
                                     "econ:" + str(org_id), org_id)) or {}
    return d if isinstance(d, dict) else {}


async def _fo_econ_people(c, org_id):
    """Сотрудники: имя, оклад, рабочий день, проджект ли (уровень роли 4 или грейд «Проджект»)."""
    out = {}
    rows = await c.fetch("SELECT e.*, r.level AS lvl FROM employee e LEFT JOIN app_user u ON u.id = e.user_id "
                         "LEFT JOIN role r ON r.code = u.role_code WHERE e.org_id = $1::uuid ORDER BY e.name", str(org_id))
    cards = {}
    for r in await c.fetch("SELECT ref_id, data FROM fo_card WHERE kind='employee' AND org_id=$1", org_id):
        cards[str(r["ref_id"])] = _fo_st_load(r["data"]) or {}
    for r in rows:
        d = dict(r)
        if d.get("is_active") is False:
            continue
        cd = cards.get(str(d["id"])) or {}
        grade = str(cd.get("grade") or "")
        pay = _fo_econ_num(cd.get("pay"))
        wd = int(d.get("workday_min") or 480) or 480
        is_pm = (d.get("lvl") == 4) or grade == "pm"
        if d.get("lvl") is not None and d.get("lvl") <= 1 and not pay:
            out[str(d["id"])] = {"id": str(d["id"]), "name": d.get("name") or "", "pay": 0.0, "pay_set": True, "wd": wd,
                                 "pm": False, "lvl": d.get("lvl"), "owner": True}
            continue
        out[str(d["id"])] = {"id": str(d["id"]), "name": d.get("name") or "", "pay": pay or _FO_GRADE_MID.get(grade) or (110000 if is_pm else 50000),
                             "pay_set": bool(pay), "wd": wd, "pm": is_pm, "lvl": d.get("lvl")}
    return out


async def _fo_econ_pm_auto(c, org_id, people):
    """Проджект кабинета без закрепления: кто из проджектов ведёт больше функций кабинета."""
    pms = {k for k, v in people.items() if v["pm"]}
    out = {}
    if not pms:
        return out
    cnt = {}
    try:
        for r in await c.fetch("SELECT cb.client_id, g.employee_id FROM fo_cabinet_fn_cfg g JOIN cabinet cb ON cb.id = g.cabinet_id "
                               "JOIN client cl ON cl.id = cb.client_id WHERE cl.org_id = $1 AND g.employee_id IS NOT NULL", org_id):
            e = str(r["employee_id"])
            if e in pms:
                k = str(r["client_id"])
                cnt.setdefault(k, {}); cnt[k][e] = cnt[k].get(e, 0) + 1
    except Exception:
        cnt = {}
    for k, m in cnt.items():
        out[k] = sorted(m.items(), key=lambda kv: -kv[1])[0][0]
    return out


async def _fo_econ_assign(c, org_id, people, clients=None, cards=None):
    """client_id → (pm_employee_id | None, источник: card | auto | one)."""
    pms = [k for k, v in people.items() if v["pm"]]
    if cards is None:
        cards = {}
        for r in await c.fetch("SELECT ref_id, data FROM fo_card WHERE kind='client' AND org_id=$1", org_id):
            cards[str(r["ref_id"])] = _fo_st_load(r["data"]) or {}
    if clients is None:
        clients = [str(r["id"]) for r in await c.fetch("SELECT id FROM client WHERE org_id=$1", org_id)]
    auto = await _fo_econ_pm_auto(c, org_id, people)
    out = {}
    for cid in clients:
        pm = str((cards.get(cid) or {}).get("pm") or "")
        if pm and pm in people:
            out[cid] = (pm, "card")
        elif auto.get(cid):
            out[cid] = (auto[cid], "auto")
        elif len(pms) == 1:
            out[cid] = (pms[0], "one")
        else:
            out[cid] = (None, "")
    return out


async def _fo_econ(c, org_id):
    today = _fo_mt_now().date()
    w_from, w_to = today - _fo_dt.timedelta(days=28), today + _fo_dt.timedelta(days=13)
    cfg = await _fo_econ_cfg(c, org_id)
    people = await _fo_econ_people(c, org_id)
    cl_rows = [dict(r) for r in await c.fetch("SELECT * FROM client WHERE org_id=$1 ORDER BY name", org_id)]
    cards = {}
    for r in await c.fetch("SELECT ref_id, data FROM fo_card WHERE kind='client' AND org_id=$1", org_id):
        cards[str(r["ref_id"])] = _fo_st_load(r["data"]) or {}
    ids = [str(r["id"]) for r in cl_rows]
    assign = await _fo_econ_assign(c, org_id, people, ids, cards)
    fn_names = {str(r["id"]): (r["name"] or "") for r in await c.fetch("SELECT id, name FROM fn WHERE org_id=$1", org_id)}
    # часы: задачи-функции и разовые в окне
    mins, days = {}, set()
    def add(cid, emp, fid, m, day):
        if not cid:
            return
        x = mins.setdefault(cid, {"t": 0.0, "e": {}, "f": {}})
        x["t"] += m
        x["e"][emp or ""] = x["e"].get(emp or "", 0.0) + m
        if fid:
            x["f"][fid] = x["f"].get(fid, 0.0) + m
        if day:
            days.add(day)
    for r in await c.fetch("SELECT client_id, assignee_id, fn_id, plan_date, plan_minutes FROM task WHERE org_id=$1 "
                           "AND plan_date BETWEEN $2 AND $3 AND status <> 'removed'", org_id, w_from, w_to):
        add(str(r["client_id"] or ""), str(r["assignee_id"] or ""), str(r["fn_id"] or ""), float(r["plan_minutes"] or 30), r["plan_date"])
    try:
        for r in await c.fetch("SELECT client_id, employee_id, fn_id, day, minutes FROM fo_task_once WHERE org_id=$1 "
                               "AND removed_at IS NULL AND day BETWEEN $2 AND $3", org_id, w_from, w_to):
            add(str(r["client_id"] or ""), str(r["employee_id"] or ""), str(r["fn_id"] or ""), float(r["minutes"] or 30), r["day"])
    except Exception:
        pass
    wdays = len([d for d in days if d.weekday() < 5]) or len(days)
    k_month = (21.0 / wdays) if wdays else 0.0
    # 284: работа с артикулами по графику АОД — сразу в месяц, потом делим на k_month (общая формула ниже умножит)
    art_m = {}
    try:
        for r in await c.fetch("SELECT cb.client_id, ao.employee_id, coalesce(ac.code, 'C') AS cat, count(*) AS n "
                               "FROM article_owner ao JOIN article a ON a.id = ao.article_id JOIN cabinet cb ON cb.id = a.cabinet_id "
                               "JOIN client cl ON cl.id = cb.client_id LEFT JOIN article_category ac ON ac.id = a.category_id "
                               "WHERE cl.org_id = $1 AND a.is_active GROUP BY 1, 2, 3", org_id):
            mm = float(r["n"] or 0) * _FO_ECON_ART_MIN.get(str(r["cat"] or "C").upper(), 3) * 52.0 / 12.0
            art_m[(str(r["client_id"]), str(r["employee_id"] or ""))] = art_m.get((str(r["client_id"]), str(r["employee_id"] or "")), 0.0) + mm
    except Exception:
        art_m = {}
    if not k_month and art_m:
        k_month = 1.0
    for (cid, emp), mm in art_m.items():
        add(cid, emp, "__arts__", mm / k_month, None)
    fn_names["__arts__"] = "Артикулы (АОД)"
    # функции кабинетов и артикулы в управлении
    fns = {}
    for r in await c.fetch("SELECT cb.client_id, cf.fn_id FROM cabinet_fn cf JOIN cabinet cb ON cb.id = cf.cabinet_id "
                           "JOIN client cl ON cl.id = cb.client_id WHERE cl.org_id = $1", org_id):
        fns.setdefault(str(r["client_id"]), set()).add(str(r["fn_id"]))
    arts = {}
    try:
        for r in await c.fetch("SELECT cb.client_id, count(*) AS n FROM article a JOIN cabinet cb ON cb.id = a.cabinet_id "
                               "JOIN client cl ON cl.id = cb.client_id WHERE cl.org_id = $1 AND a.is_active GROUP BY 1", org_id):
            arts[str(r["client_id"])] = int(r["n"] or 0)
    except Exception:
        arts = {}
    # срок жизни клиента: из настройки, иначе по уходу (как в блоке LTV), иначе 12 мес.
    n_all = len(ids)
    gone = sum(1 for k in ids if str((cards.get(k) or {}).get("confirm") or "") == "no")
    life_auto = round(1 + 0.5 / (gone / n_all), 1) if (n_all and gone) else 12.0
    life = _fo_econ_num(cfg.get("life")) or life_auto
    # оклад проджекта раскладываем по его клиентам пропорционально часам команды (больше работы — больше его
    # времени на координацию); часов ни у кого нет — поровну
    pm_n, pm_h, pm_r = {}, {}, {}
    for cid in ids:
        pm, _src = assign.get(cid, (None, ""))
        if pm:
            pm_n[pm] = pm_n.get(pm, 0) + 1
            pm_h[pm] = pm_h.get(pm, 0.0) + (mins.get(cid) or {"t": 0.0})["t"]
            pm_r[pm] = pm_r.get(pm, 0.0) + _fo_econ_num((cards.get(cid) or {}).get("amount"))
    split = str(cfg.get("pm_split") or "equal")
    if split not in ("equal", "hours", "revenue"):
        split = "equal"
    rows = []
    for cl in cl_rows:
        cid = str(cl["id"]); cd = cards.get(cid) or {}
        amount = _fo_econ_num(cd.get("amount"))
        sv, since_src = _fo_econ_since(cd.get("since")), "card"
        if not sv:
            ca = cl.get("created_at")
            sv, since_src = ((ca.year, ca.month) if ca else (today.year, today.month)), "service"
        months = max(1, (today.year - sv[0]) * 12 + (today.month - sv[1]) + 1)
        pm, pm_src = assign.get(cid, (None, ""))
        x = mins.get(cid) or {"t": 0.0, "e": {}, "f": {}}
        hours = x["t"] * k_month / 60.0
        # 285: у клиента — только трудозатраты; оклад проджекта целиком — в экономике его группы кабинетов
        team_cost, pm_hours, pm_cost = 0.0, 0.0, 0.0
        for e, m in x["e"].items():
            mm = m * k_month
            pe = people.get(e)
            c1 = (mm * pe["pay"] / (pe["wd"] * 21.0)) if pe else 0.0
            if pm and e == pm:
                pm_hours += mm / 60.0; pm_cost += c1
            else:
                team_cost += c1
        # 286: доля ЗП проджекта на клиента — видна у клиента; его собственные задачи — внутри оклада
        pm_share = 0.0
        if pm and pm in people and pm_n.get(pm):
            pay_pm = people[pm]["pay"]
            if split == "hours" and pm_h.get(pm):
                pm_share = pay_pm * x["t"] / pm_h[pm]
            elif split == "revenue" and pm_r.get(pm):
                pm_share = pay_pm * amount / pm_r[pm]
            else:
                pm_share = pay_pm / pm_n[pm]
        labor = team_cost + pm_cost
        cost = team_cost + pm_share
        margin = amount - cost
        fl = sorted(fns.get(cid) or [], key=lambda f: fn_names.get(f, ""))
        fh = sorted([(f, m * k_month / 60.0) for f, m in x["f"].items()], key=lambda kv: -kv[1])
        art_h = x["f"].get("__arts__", 0.0) * k_month / 60.0
        rows.append({"client_id": cid, "client": cl.get("name") or "", "amount": round(amount), "confirm": cd.get("confirm") or "",
                     "since": "%04d-%02d" % sv, "since_src": since_src, "months": months,
                     "pm": pm, "pm_name": (people.get(pm) or {}).get("name") if pm else None, "pm_src": pm_src,
                     "hours": round(hours, 1), "pm_hours": round(pm_hours, 1), "team_cost": round(team_cost), "pm_share": round(pm_share), "pm_cost": round(pm_cost), "labor": round(labor),
                     "labor_margin": round(amount - labor), "labor_pct": round((amount - labor) / amount * 100, 1) if amount else None,
                     "cost": round(cost), "margin": round(margin), "margin_pct": round(margin / amount * 100, 1) if amount else None,
                     "rph": round(amount / hours) if hours > 0.05 else None,
                     "fns": [fn_names.get(f, "функция") for f in fl], "fn_ids": fl, "fn_hours": [{"fn": fn_names.get(f, "разовые"), "h": round(h, 1)} for f, h in fh[:8]],
                     "arts": arts.get(cid, 0), "arts_card": int(_fo_econ_num(cd.get("articles"))), "arts_hours": round(art_h, 1),
                     "ltv_fact": round(amount * months), "ltv_full": round(amount * (months + life)),
                     "life_value": round(margin * (months + life))})
    rows.sort(key=lambda r: (0 if r["amount"] > 0 else 1, -r["life_value"]))   # без платежа в карточке — в конец
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    def agg(lst):
        n = len(lst); paid = [r for r in lst if r["amount"] > 0]
        rev = sum(r["amount"] for r in lst); hrs = sum(r["hours"] for r in lst); mar = sum(r["margin"] for r in lst)
        return {"n": n, "paying": len(paid), "rev": rev, "check": round(rev / len(paid)) if paid else 0,
                "hours": round(hrs, 1), "hours_per": round(hrs / n, 1) if n else 0, "team_cost": sum(r["team_cost"] for r in lst),
                "cost": sum(r["cost"] for r in lst), "margin": mar, "margin_pct": round(mar / rev * 100, 1) if rev else None,
                "rph": round(rev / hrs) if hrs > 0.05 else None, "arts": sum(r["arts"] for r in lst),
                "arts_per": round(sum(r["arts"] for r in lst) / n) if n else 0,
                "fns_per": round(sum(len(r["fns"]) for r in lst) / n, 1) if n else 0,
                "months_avg": round(sum(r["months"] for r in lst) / n, 1) if n else 0,
                "ltv_fact": sum(r["ltv_fact"] for r in lst), "cap": sum(r["ltv_full"] for r in lst),
                "ltv_avg": round(sum(r["ltv_full"] for r in paid) / len(paid)) if paid else 0,
                "life_value": sum(r["life_value"] for r in lst),
                "life_value_per": round(sum(r["life_value"] for r in lst) / n) if n else 0}
    pms = []
    for e, pe in sorted(people.items(), key=lambda kv: kv[1]["name"]):
        if not pe["pm"]:
            continue
        lst = [r for r in rows if r["pm"] == e]
        a = agg(lst)
        team = sum(r["team_cost"] for r in lst)          # 285: часы команды без собственных часов проджекта
        a["labor_margin"] = sum(r["labor_margin"] for r in lst)   # по трудозатратам, как у клиентов
        a["margin"] = round(a["rev"] - team - pe["pay"])
        a["margin_pct"] = round(a["margin"] / a["rev"] * 100, 1) if a["rev"] else None
        a["team_cost"] = round(team); a["cost"] = round(team + pe["pay"])
        a["pm_hours"] = round(sum(r["pm_hours"] for r in lst), 1)
        a.update({"employee_id": e, "name": pe["name"], "pay": round(pe["pay"]), "pay_set": pe["pay_set"],
                  "pay_share": round(pe["pay"] / a["rev"] * 100, 1) if a["rev"] else None,
                  "clients": [r["client"] for r in lst]})
        pms.append(a)
    noone = [r for r in rows if not r["pm"]]
    buckets = []
    for lo, hi, name in _FO_ECON_BUCKETS:
        lst = [r for r in rows if r["amount"] > 0 and r["amount"] >= lo and (hi is None or r["amount"] < hi)]
        b = agg(lst); b.update({"name": name, "lo": lo, "hi": hi}); buckets.append(b)
    # функции: сколько стоят в месяц на кабинет и как живут кабинеты с ними
    fstat = {}
    for r in rows:
        x = mins.get(r["client_id"]) or {"f": {}}
        for f in r["fn_ids"] + (["__arts__"] if x["f"].get("__arts__") else []):
            s0 = fstat.setdefault(f, {"fn": fn_names.get(f, "функция"), "n": 0, "h": 0.0, "rev": 0.0, "mar": 0.0})
            s0["n"] += 1; s0["h"] += x["f"].get(f, 0.0) * k_month / 60.0; s0["rev"] += r["amount"]; s0["mar"] += r["margin"]
    funcs = sorted([{"fn": v["fn"], "n": v["n"], "h_per": round(v["h"] / v["n"], 1) if v["n"] else 0,
                     "margin_pct": round(v["mar"] / v["rev"] * 100, 1) if v["rev"] else None}
                    for v in fstat.values()], key=lambda z: -z["n"])
    sets = {}
    for r in rows:
        if not r["fns"] or r["amount"] <= 0:
            continue
        key = " + ".join(r["fns"])
        sets.setdefault(key, []).append(r)
    combos = sorted([dict(agg(v), set=k, size=len(v[0]["fns"]), names=[r["client"] for r in v]) for k, v in sets.items()],
                    key=lambda z: -(z["margin_pct"] if z["margin_pct"] is not None else -999))
    tot = agg(rows)
    # 285: итог агентства — выручка − часы команды − оклады всех проджектов (их задачи — внутри оклада)
    pm_pay_all = sum(v["pay"] for v in people.values() if v["pm"])
    tot["labor_margin"] = sum(r["labor_margin"] for r in rows)
    _th = sum(r["hours"] - r["pm_hours"] for r in rows)
    tot["cph"] = round(sum(r["team_cost"] for r in rows) / _th) if _th > 0.05 else None   # час исполнителей
    tot["pm_pay"] = round(pm_pay_all)
    tot["pm_cabs"] = sum(1 for r in rows if r["pm"])
    tot["margin"] = round(sum(r["amount"] - r["team_cost"] for r in rows) - pm_pay_all)
    tot["margin_pct"] = round(tot["margin"] / tot["rev"] * 100, 1) if tot["rev"] else None
    return {"today": today.isoformat(), "window": {"from": w_from.isoformat(), "to": w_to.isoformat(), "workdays": wdays},
            "life": life, "life_auto": life_auto, "life_set": bool(_fo_econ_num(cfg.get("life"))), "pm_split": split,
            "target": _fo_econ_num(cfg.get("target")) or 30.0,
            "art_touch": {"A": [3, _FO_ECON_ART_MIN["A"]], "B": [2, _FO_ECON_ART_MIN["B"]], "C": [1, _FO_ECON_ART_MIN["C"]]},
            "total": tot, "clients": rows, "pms": pms, "noone": agg(noone), "noone_names": [r["client"] for r in noone],
            "buckets": buckets, "funcs": funcs, "combos": combos[:12],
            "missing": {"since": sum(1 for r in rows if r["since_src"] != "card"), "amount": sum(1 for r in rows if r["amount"] <= 0),
                        "pay": [v["name"] for v in people.values() if not v["pay_set"]],
                        "pm": sum(1 for r in rows if r["pm_src"] != "card"), "no_hours": sum(1 for r in rows if r["hours"] <= 0)}}


class FoEconSetIn(_FoBM):
    life: float | None = None
    pm_split: str | None = None
    target: float | None = None


class FoEconPmIn(_FoBM):
    client_id: str
    employee_id: str | None = None


@router.get("/econ")
async def fo_econ_get(p: Principal = Depends(max_level(1))):
    """282: экономика клиентов и проджектов — только собственник."""
    async with pool().acquire() as c:
        return await _fo_econ(c, p.org_id)


@router.post("/econ/settings")
async def fo_econ_settings(body: FoEconSetIn, p: Principal = Depends(max_level(1))):
    v = body.life
    try:
        fs = body.model_fields_set
    except Exception:
        fs = getattr(body, "__fields_set__", set())
    d = {}
    if "life" in fs:
        d["life"] = (max(1.0, min(60.0, float(v))) if v else None)
    if body.pm_split in ("equal", "hours", "revenue"):
        d["pm_split"] = body.pm_split
    if body.target is not None:
        d["target"] = max(0.0, min(90.0, float(body.target)))      # 287: целевая маржа — для «скидка / поднять цену»
    async with pool().acquire() as c:
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now() "
            "WHERE fo_card.org_id = EXCLUDED.org_id", "econ:" + str(p.org_id), p.org_id, _fo_json.dumps(d))
        return {"ok": True, "settings": await _fo_econ_cfg(c, p.org_id)}


@router.get("/econ/team")
async def fo_econ_team(p: Principal = Depends(max_level(4))):
    """282: «Распределение в команде» — проджекты и закреплённые за ними клиенты; без проджекта — отдельно."""
    async with pool().acquire() as c:
        people = await _fo_econ_people(c, p.org_id)
        cards = {}
        for r in await c.fetch("SELECT ref_id, data FROM fo_card WHERE kind='client' AND org_id=$1", p.org_id):
            cards[str(r["ref_id"])] = _fo_st_load(r["data"]) or {}
        cls = await c.fetch("SELECT id, name FROM client WHERE org_id=$1 ORDER BY name", p.org_id)
        auto = await _fo_econ_assign(c, p.org_id, people, [str(r["id"]) for r in cls], cards)
    out = []
    for r in cls:
        cid = str(r["id"]); pm = str((cards.get(cid) or {}).get("pm") or "")
        a = auto.get(cid) or (None, "")
        out.append({"client_id": cid, "name": r["name"] or "", "pm": pm if pm in people else None,
                    "auto": (a[0] if a[1] in ("auto", "one") else None),
                    "auto_name": (people.get(a[0]) or {}).get("name") if a[1] in ("auto", "one") else None})
    return {"pms": [{"employee_id": k, "name": v["name"]} for k, v in sorted(people.items(), key=lambda kv: kv[1]["name"]) if v["pm"]],
            "clients": out, "can_edit": _fo_lvl(p) <= 2}


@router.post("/econ/pm")
async def fo_econ_pm(body: FoEconPmIn, p: Principal = Depends(max_level(2))):
    """282: закрепить клиента за проджектом (или снять). Пишет в карточку клиента — видно везде, где карточка."""
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM client WHERE id=$1::uuid AND org_id=$2", body.client_id, p.org_id)
        if not ok:
            raise HTTPException(404, "клиент не найден")
        emp = str(body.employee_id or "")
        if emp:
            people = await _fo_econ_people(c, p.org_id)
            if emp not in people or not people[emp]["pm"]:
                raise HTTPException(400, "закрепить можно только за сотрудником с ролью «Проджект»")
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('client', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now() "
            "WHERE fo_card.org_id = EXCLUDED.org_id", str(body.client_id), p.org_id, _fo_json.dumps({"pm": emp}))
    return {"ok": True, "client_id": body.client_id, "pm": emp or None}


# ══ 289: КАРТИНКИ ФУНКЦИЙ — сервис рисует сам (Виталий 06.10) ══
# Отчёт «✅ Выполнено: функция» уходит в чат картинкой — один в один шаблон «Планёрки» (banner/tpl4.html): тот же
# фон с логотипом, Inter 800, градиент #8A2DB3 → #B622C9 → #F419BB, мягкая тень. На картинке только название
# функции, без плашек, номеров и расшифровок; длинное — в две строки. Новая функция сразу получает картинку.
# Заголовок — название без номеров и скобок или свой (fo_card kind='org', ref_id='fnimg:<org>', {fn_id: заголовок}).
# Нужен только Pillow; фон и шрифт Inter (SIL OFL) кладёт шаг в /opt/fo/fnimg.
_FO_FI_DIR = "/opt/fo/fnimg"
_FO_FI_W, _FO_FI_H = 1280, 400
_FO_FI_STOPS = ((0.0, (138, 45, 179)), (0.48, (182, 34, 201)), (1.0, (244, 25, 187)))
_FO_FI_RANGES = ((32, 126), (160, 172), (174, 255), (1024, 1119), (8208, 8231), (8240, 8250), (8381, 8381),
                 (8470, 8470), (8592, 8601), (10003, 10003))
_FO_FI_SHORT = ("для", "без", "при", "через", "над", "под", "про")
_FO_FI_MEM = {}          # заголовок → JPEG (в памяти процесса)
_FO_FI_TG = {}           # (бот, заголовок) → file_id Telegram
_FO_FI_BG = {}


def _fo_fi_ok(ch):
    o = ord(ch)
    return any(a <= o <= b for a, b in _FO_FI_RANGES)


def _fo_fi_clean(name):
    """Название функции → заголовок картинки: без расшифровок в скобках, номеров и хвостов «…/…»; пробелы и регистр."""
    t = " ".join(str(name or "").replace(" ", " ").split())
    t = re.sub(r"\s*\([^)]*\)?", " ", t)                        # (расшифровка)
    t = re.sub(r"^\s*\d+[.)]\s*", "", t)                        # «1. …»
    t = re.sub(r"\s+\d+\s*:.*$", "", t)                          # «Регламент 1: …» → «Регламент»
    t = re.sub(r"\s+\d+\s*$", "", t)                             # «Регламент 0» → «Регламент»
    t = re.sub(r"\s+([,.:;!?])", r"\1", t)
    t = " ".join(t.split()).strip(" .,:;-–—/")
    words, out = t.split(" "), []
    for i, w in enumerate(words):
        core = re.sub(r"[^A-Za-zА-Яа-яЁё-]", "", w)
        cyr = bool(re.search(r"[А-Яа-яЁё]", core))
        if cyr and re.fullmatch(r"[А-ЯЁ]{2}[а-яё]+", core):                     # «ЗАполнение», «РЕшаем»
            n = core[0] + core[1:].lower()
            w, core = w.replace(core, n, 1), n
        if cyr and len(core) >= 4 and core.upper() == core and core.lower() != core:   # «ОТЗЫВЫ», «ЗАПУСК»
            n = core.lower()
            w, core = w.replace(core, n, 1), n
        if i > 0 and cyr and re.fullmatch(r"[А-ЯЁ][а-яё-]{2,}", core):          # «Рекламных» посреди фразы
            prev = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", words[i - 1]).upper()
            sur = core.lower().endswith(("ов", "ев", "ин", "ян", "ова", "ева", "ина", "ский", "ская"))
            if prev not in ("ИП", "ООО", "АО", "ПАО", "ЗАО", "ОАО", "ТОО") and not sur:
                n = core.lower()
                w, core = w.replace(core, n, 1), n
        out.append(w)
    t = "".join(ch for ch in " ".join(out) if _fo_fi_ok(ch)).strip()
    if t[:1].islower():
        t = t[0].upper() + t[1:]
    return t[:120] or "Функция"


def _fo_fi_pil():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        import importlib as _il
        _il.invalidate_caches()
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    return Image, ImageDraw, ImageFont, ImageFilter


def _fo_fi_render(title, q=92):
    """Картинка 1280×400 по шаблону «Планёрки»: фон с логотипом + название функции по центру."""
    title = " ".join(str(title or "").split()) or "Функция"
    if title in _FO_FI_MEM:
        return _FO_FI_MEM[title]
    Image, ImageDraw, ImageFont, ImageFilter = _fo_fi_pil()
    W, H, MAXW = _FO_FI_W, _FO_FI_H, 1150
    if "bg" not in _FO_FI_BG:
        bg = Image.open(_FO_FI_DIR + "/bg.jpg").convert("RGB")
        bg.load()
        _FO_FI_BG["bg"] = bg
    img = _FO_FI_BG["bg"].copy()
    fpath = _FO_FI_DIR + "/title.ttf"
    fonts = {}

    def font(s):
        if s not in fonts:
            fonts[s] = ImageFont.truetype(fpath, s)
        return fonts[s]

    def width(t, s):                                   # как в браузере: letter-spacing −0.025em после каждой буквы
        return font(s).getlength(t) - 0.025 * s * len(t)

    # короткие слова («и», «с», «по», «для») не висят в конце строки
    words = []
    for w in title.split(" "):
        last = words[-1].split(" ")[-1] if words else ""
        if last and (len(last) <= 2 or last.lower() in _FO_FI_SHORT):
            words[-1] += " " + w
        else:
            words.append(w)

    def split2(s):                                     # две строки, самая ровная разбивка
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            m = max(width(a, s), width(b, s))
            if best is None or m < best[0]:
                best = (m, [a, b])
        return best

    one = width(" ".join(words), 156)
    s1 = 156 if one <= MAXW else int(156 * MAXW / one)
    s2, lines2 = 104, None
    if len(words) > 1:
        while s2 > 56:
            b = split2(s2)
            if b and b[0] <= MAXW:
                lines2 = b[1]
                break
            s2 -= 2
    if lines2 is None or s1 >= s2 * 0.95:
        size, lines, lh = s1, [" ".join(words)], s1
    else:
        size, lines, lh = s2, lines2, s2 * 1.04
    f = font(size)
    asc, desc = 0.96875 * size, 0.2412 * size            # метрики Inter (hhea), как считает браузер
    pad = 0.04 * size
    box_w = min(MAXW, max(width(x, size) for x in lines)) + 2 * pad
    box_h = lh * len(lines) + 0.08 * size
    bx, by = (W - box_w) / 2, (H - box_h) / 2
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    for i, ln in enumerate(lines):
        base = by + i * lh + (lh - (asc + desc)) / 2 + asc
        x = bx + pad + (box_w - 2 * pad - width(ln, size)) / 2
        for k, ch in enumerate(ln):                      # буква за буквой, с кернингом из префикса
            cx = x + f.getlength(ln[:k]) - 0.025 * size * k
            md.text((cx, base), ch, font=f, fill=255, anchor="ls")
    # градиент по ширине блока заголовка (как background-clip:text)
    row = Image.new("RGB", (W, 1))
    px = row.load()
    for xx in range(W):
        k = min(1.0, max(0.0, (xx - bx) / max(1.0, box_w)))
        for j in range(len(_FO_FI_STOPS) - 1):
            k0, c0 = _FO_FI_STOPS[j]
            k1, c1 = _FO_FI_STOPS[j + 1]
            if k <= k1:
                u = (k - k0) / (k1 - k0)
                px[xx, 0] = tuple(int(round(c0[n] + (c1[n] - c0[n]) * u)) for n in range(3))
                break
    grad = row.resize((W, H))
    # тень: drop-shadow(0 10px 36px rgba(182,34,201,.35))
    sh = Image.new("L", (W, H), 0)
    sh.paste(mask, (0, 10))
    sh = sh.filter(ImageFilter.GaussianBlur(33)).point(lambda v: int(v * 0.35))
    img.paste(Image.new("RGB", (W, H), (182, 34, 201)), (0, 0), sh)
    img.paste(grad, (0, 0), mask)
    import io as _io
    out = _io.BytesIO()
    img.save(out, "JPEG", quality=q, optimize=True)
    data = out.getvalue()
    if len(_FO_FI_MEM) > 300:
        _FO_FI_MEM.clear()
    _FO_FI_MEM[title] = data
    return data

async def _fo_fi_titles(c, org_id):
    r = await c.fetchval("SELECT data FROM fo_card WHERE kind='org' AND ref_id=$1 AND org_id=$2", "fnimg:" + str(org_id), org_id)
    d = _fo_st_load(r) if r is not None else {}
    return d if isinstance(d, dict) else {}


async def _fo_fi_title(c, org_id, fn_id, name, custom=None):
    if custom is None:
        custom = await _fo_fi_titles(c, org_id)
    t = str(custom.get(str(fn_id)) or "").strip()
    return t or _fo_fi_clean(name)


import contextvars as _fo_cv_fi
_FO_FI_CTX = _fo_cv_fi.ContextVar("fo_fi_ctx", default=None)   # 290: галочка знает свою функцию — без угадывания по тексту
_FO_FI_WHY = []                                                 # 290: последние решения «с картинкой / текстом и почему»


def _fo_fi_why(chat_id, name, how, ok):
    try:
        _FO_FI_WHY.insert(0, {"когда": _fo_dt.datetime.now().strftime("%d.%m %H:%M:%S"), "чат": str(chat_id)[-6:],
                              "функция": str(name)[:80], "как": how, "картинка": bool(ok)})
        del _FO_FI_WHY[30:]
        print("290 картинка:", "да" if ok else "НЕТ", "·", how, "·", str(name)[:60])
    except Exception:
        pass


async def _fo_fi_for_text(chat_id, text):
    """Отчёт «✅ Выполнено: <функция>» → (заголовок, JPEG); не функция — None (уйдёт текстом, причина — в журнал)."""
    m = re.match(r"\s*✅ Выполнено: ([^\n]+)", str(text or ""))
    if not m:
        return None
    name = m.group(1).strip()
    ctx = _FO_FI_CTX.get()
    async with pool().acquire() as c:
        if ctx and ctx.get("fn") and str(ctx.get("name") or "").strip() == name:
            org, fid, how = ctx["org"], ctx["fn"], "функция из галочки"
        else:
            r = await c.fetchrow("SELECT f.id, f.org_id FROM fn f JOIN chat ch ON ch.org_id = f.org_id "
                                 "WHERE ch.chat_id=$1 AND lower(btrim(f.name))=lower(btrim($2)) LIMIT 1", str(chat_id), name)
            if not r:
                _fo_fi_why(chat_id, name, "не нашёл функцию по названию в организации чата", False)
                return None
            org, fid, how = r["org_id"], r["id"], "функция по названию"
        title = await _fo_fi_title(c, org, fid, name)
    data = await _fo_aio.to_thread(_fo_fi_render, title)
    _fo_fi_why(chat_id, name, how, True)
    return (title, data)


@router.get("/fnimg/why")
async def fo_fnimg_why(p: Principal = Depends(max_level(2))):
    """290: почему отчёт ушёл без картинки — решения этого процесса и разбор последнего отчёта бота старым способом."""
    import sys as _s
    inst = []
    for nm, mod in list(_s.modules.items()):
        if mod is not None and (nm.endswith(".routing") or nm.endswith(".notify")) and hasattr(mod, "send_telegram"):
            f = getattr(mod, "send_telegram")
            inst.append({"модуль": nm, "наша": f is _fo_rp_send_telegram,
                         "с картинкой": "_noimg" in getattr(getattr(f, "__code__", None), "co_varnames", ())})
    old = {}
    async with pool().acquire() as c:
        r = await c.fetchrow("SELECT tg_chat_id, text, msg_at FROM fo_chat_msg WHERE org_id=$1 AND author='Бот отчётов' "
                             "AND kind='client' AND text LIKE '✅ Выполнено:%' ORDER BY msg_at DESC LIMIT 1", p.org_id)
        if r:
            m = re.match(r"\s*✅ Выполнено: ([^\n]+)", r["text"])
            name = m.group(1).strip() if m else None
            orgs = [str(x["org_id"]) for x in await c.fetch("SELECT org_id FROM chat WHERE chat_id=$1", r["tg_chat_id"])]
            first = await c.fetchval("SELECT org_id FROM chat WHERE chat_id=$1 LIMIT 1", r["tg_chat_id"])
            fn_first = await c.fetchval("SELECT id FROM fn WHERE org_id=$1 AND lower(btrim(name))=lower(btrim($2)) LIMIT 1",
                                        first, name) if first and name else None
            fn_mine = await c.fetchval("SELECT id FROM fn WHERE org_id=$1 AND lower(btrim(name))=lower(btrim($2)) LIMIT 1",
                                       p.org_id, name) if name else None
            old = {"отчёт": str(r["msg_at"])[:16], "функция": name, "текст начинается верно": bool(m),
                   "организаций у чата": len(orgs), "моя организация среди них": str(p.org_id) in orgs,
                   "старый способ: первая организация = моя": str(first) == str(p.org_id),
                   "старый способ нашёл функцию": bool(fn_first), "функция есть в моей организации": bool(fn_mine)}
    return {"установлено": inst, "старый способ на последнем отчёте": old, "решения этого процесса": list(_FO_FI_WHY)}


def _fo_fi_pub_url(title):
    """Публичная ссылка на картинку (Telegram её не забирает: сервер для него недоступен — оставлена на будущее)."""
    import base64 as _b64, hmac as _hm
    key = (_fo_env("TG_REPORT_BOT_TOKEN") or _fo_env("TG_BOT_TOKEN") or "fo").encode()
    t = _b64.urlsafe_b64encode(str(title).encode("utf-8")).decode().rstrip("=")
    sig = _hm.new(key, t.encode(), "sha256").hexdigest()[:20]
    return "https://fo.flater.pro/refs/fnimg/pub/%s/%s.jpg" % (sig, t)


_FO_FI_LAST = {}


def _fo_fi_photo_sync(tok, chat_id, fi, text, fid=None):
    """Картинка функции + подпись. fid — уже загруженная картинка (мгновенно); без него — загрузка файла
    (с сервера в Telegram идёт медленно, поэтому только в фоне). Длинная подпись: остаток следом."""
    import uuid as _uu
    title, data = fi
    text = str(text or "")
    cap, rest = text, ""
    if len(text) > 1024:
        cut = text.rfind("\n", 0, 1000)
        cut = cut if cut > 0 else 1000
        cap, rest = text[:cut], text[cut:].strip()
    prm = {"chat_id": str(chat_id), "caption": cap}
    if fid:
        res = _fo_tg_api_sync("sendPhoto", dict(prm, photo=fid), tok, 20)
    else:
        b = "----fo" + _uu.uuid4().hex
        body = b"".join([("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8")
                         for k, v in prm.items()])
        body += ("--%s\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"function.jpg\"\r\n"
                 "Content-Type: image/jpeg\r\n\r\n" % b).encode() + data + ("\r\n--%s--\r\n" % b).encode()
        rq = _fo_ur.Request("https://api.telegram.org/bot%s/sendPhoto" % tok, data=body,
                            headers={"Content-Type": "multipart/form-data; boundary=" + b})
        try:
            with _fo_ur.urlopen(rq, timeout=150) as r:
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
    if res.get("ok") and rest:
        _fo_tg_api_sync("sendMessage", {"chat_id": str(chat_id), "text": rest[:4000], "disable_web_page_preview": True}, tok, 15)
    return res


def _fo_fi_ref(tok):
    return "fnimg_tg:" + _fo_hl.sha1(str(tok).encode()).hexdigest()[:12]


async def _fo_fi_fid(tok, title):
    """file_id уже загруженной картинки этого бота: память процесса, потом база (переживает перезапуск)."""
    k = (tok[:14], title)
    if _FO_FI_TG.get(k):
        return _FO_FI_TG[k]
    try:
        async with pool().acquire() as c:
            v = await c.fetchval("SELECT data->>$2 FROM fo_card WHERE kind='sys' AND ref_id=$1", _fo_fi_ref(tok), title)
        if v:
            _FO_FI_TG[k] = v
        return v
    except Exception:
        return None


async def _fo_fi_fid_save(tok, chat_id, title, fid):
    _FO_FI_TG[(tok[:14], title)] = fid
    try:
        async with pool().acquire() as c:
            org = await c.fetchval("SELECT org_id FROM chat WHERE chat_id=$1 LIMIT 1", str(chat_id))
            if org:
                await c.execute(
                    "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('sys', $1, $2, $3::jsonb) "
                    "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
                    _fo_fi_ref(tok), org, _fo_json.dumps({title: fid}))
    except Exception:
        pass


async def _fo_fi_log(chat_id, mid, text):
    """Отправленное ложится в историю чата (как у текстового отчёта)."""
    try:
        async with pool().acquire() as c:
            ch = await c.fetchrow("SELECT ch.id, ch.org_id, cc.client_id, cc.kind FROM chat ch "
                                  "JOIN client_chat cc ON cc.chat_pk = ch.id WHERE ch.chat_id=$1 "
                                  "ORDER BY (cc.kind='client') DESC LIMIT 1", str(chat_id))
            if ch and mid:
                await c.execute(
                    "INSERT INTO fo_chat_msg (org_id, client_id, chat_pk, kind, tg_chat_id, msg_id, author, author_tg, text, msg_at, ai_state, ai_note) "
                    "VALUES ($1,$2::uuid,$3,$4,$5,$6,'Бот отчётов','',$7,now(),'skip','сообщение бота отчётов (с картинкой)') "
                    "ON CONFLICT (tg_chat_id, msg_id) DO NOTHING",
                    ch["org_id"], str(ch["client_id"]), ch["id"], ch["kind"], str(chat_id), -(1000000 + int(mid)), str(text)[:4000])
    except Exception:
        pass


async def _fo_fi_bg(tok, chat_id, fi, text, fallback=True):
    """Первая отправка картинки функции — в фоне (галочка не ждёт). Не вышло — отчёт уходит текстом."""
    t0 = _fo_time.time()
    try:
        res = await _fo_aio.to_thread(_fo_fi_photo_sync, tok, chat_id, fi, text, None)
    except Exception as e:
        res = {"ok": False, "description": str(e)[:200]}
    _FO_FI_LAST.clear()
    _FO_FI_LAST.update({"когда": _fo_dt.datetime.now().strftime("%d.%m %H:%M:%S"), "секунд": round(_fo_time.time() - t0, 1),
                        "ok": bool(res.get("ok")), "заголовок": fi[0],
                        "ошибка": None if res.get("ok") else str(res.get("description") or res)[:200]})
    if res.get("ok"):
        r = res.get("result") or {}
        ph = (r.get("photo") or [{}])[-1]
        if ph.get("file_id"):
            await _fo_fi_fid_save(tok, chat_id, fi[0], ph["file_id"])
        await _fo_fi_log(chat_id, r.get("message_id"), text)
    elif fallback:
        print("бот отчётов, картинка не ушла:", _FO_FI_LAST.get("ошибка"))
        await _fo_rp_send_telegram(chat_id, text, _noimg=True)
    return res


@router.get("/fnimg/last")
async def fo_fnimg_last(p: Principal = Depends(max_level(2))):
    """Последняя фоновая отправка картинки: сколько шла, ушла ли."""
    return dict(_FO_FI_LAST) or {"нет": "ещё не отправлялось"}


@router.get("/fnimg/pub/{sig}/{name}")
async def fo_fnimg_pub(sig: str, name: str):
    """Картинка по подписанной ссылке (без входа)."""
    import base64 as _b64, hmac as _hm
    from fastapi.responses import Response as _FoResp
    t = name[:-4] if name.endswith(".jpg") else name
    key = (_fo_env("TG_REPORT_BOT_TOKEN") or _fo_env("TG_BOT_TOKEN") or "fo").encode()
    if not _hm.compare_digest(_hm.new(key, t.encode(), "sha256").hexdigest()[:20], sig):
        raise HTTPException(404, "нет такой картинки")
    try:
        title = _b64.urlsafe_b64decode(t + "=" * (-len(t) % 4)).decode("utf-8")[:140]
        data = await _fo_aio.to_thread(_fo_fi_render, title)
    except Exception:
        raise HTTPException(404, "нет такой картинки")
    return _FoResp(content=data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


class FoFiTitlesIn(_FoBM):
    items: list[dict]


class FoFiTestIn(_FoBM):
    client_id: str
    fn_id: str
    text: str | None = None


@router.get("/fnimg")
async def fo_fnimg_list(p: Principal = Depends(current)):
    """289: функции и заголовки их картинок (свой или авто из названия)."""
    async with pool().acquire() as c:
        custom = await _fo_fi_titles(c, p.org_id)
        rows = await c.fetch("SELECT id, name FROM fn WHERE org_id=$1 ORDER BY name", p.org_id)
    try:
        _fo_fi_pil()
        pil = True
    except Exception:
        pil = False
    return {"ready": pil, "items": [{"fn_id": str(r["id"]), "name": r["name"], "auto": _fo_fi_clean(r["name"]),
                                     "title": str(custom.get(str(r["id"])) or "").strip() or _fo_fi_clean(r["name"]),
                                     "custom": bool(str(custom.get(str(r["id"])) or "").strip())} for r in rows]}


@router.get("/fnimg/{fn_id}/img")
async def fo_fnimg_img(fn_id: str, title: str = "", p: Principal = Depends(current)):
    """Картинка функции (JPEG). title — превью своего заголовка до сохранения."""
    from fastapi.responses import Response as _FoResp
    async with pool().acquire() as c:
        name = await c.fetchval("SELECT name FROM fn WHERE id=$1::uuid AND org_id=$2", fn_id, p.org_id)
        if name is None:
            raise HTTPException(404, "функция не найдена")
        t = (title or "").strip()[:140] or await _fo_fi_title(c, p.org_id, fn_id, name)
    try:
        data = await _fo_aio.to_thread(_fo_fi_render, t)
    except Exception as e:
        raise HTTPException(503, "картинка не рисуется: " + str(e)[:150])
    return _FoResp(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.post("/fnimg/titles")
async def fo_fnimg_titles(body: FoFiTitlesIn, p: Principal = Depends(max_level(2))):
    """Свой заголовок картинки для функций: [{fn_id, title}]; пустой title — вернуть авто из названия."""
    async with pool().acquire() as c:
        ids = {str(r["id"]) for r in await c.fetch("SELECT id FROM fn WHERE org_id=$1", p.org_id)}
        cur = await _fo_fi_titles(c, p.org_id)
        n = 0
        for it in (body.items or [])[:500]:
            fid = str((it or {}).get("fn_id") or "")
            if fid not in ids:
                continue
            t = " ".join(str((it or {}).get("title") or "").split())[:140]
            if t:
                cur[fid] = t
            else:
                cur.pop(fid, None)
            n += 1
        await c.execute(
            "INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', $1, $2, $3::jsonb) "
            "ON CONFLICT (kind, ref_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now() "
            "WHERE fo_card.org_id = EXCLUDED.org_id", "fnimg:" + str(p.org_id), p.org_id, _fo_json.dumps(cur))
    return {"ok": True, "saved": n}


@router.post("/fnimg/test")
async def fo_fnimg_test(body: FoFiTestIn, p: Principal = Depends(max_level(2))):
    """Проверка: картинка функции с подписью «Проверка» — в чат клиента от бота отчётов."""
    tok = _fo_rp_tok() or _fo_env("TG_BOT_TOKEN")
    if not tok:
        raise HTTPException(400, "бот отчётов не подключён")
    async with pool().acquire() as c:
        name = await c.fetchval("SELECT name FROM fn WHERE id=$1::uuid AND org_id=$2", body.fn_id, p.org_id)
        ch = await c.fetchval("SELECT ch.chat_id FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id "
                              "WHERE cc.client_id=$1::uuid AND ch.org_id=$2 AND cc.kind='client' AND ch.chat_id ~ '^-?[0-9]+$' "
                              "LIMIT 1", body.client_id, p.org_id)
        if not name or not ch:
            raise HTTPException(404, "нет функции или чата клиента")
        title = await _fo_fi_title(c, p.org_id, body.fn_id, name)
    data = await _fo_aio.to_thread(_fo_fi_render, title)
    txt = (body.text or "").strip()[:1500] or ("Проверка картинки: ✅ Выполнено: %s" % name)
    fid = await _fo_fi_fid(tok, title)
    if fid:
        res = await _fo_aio.to_thread(_fo_fi_photo_sync, tok, ch, (title, data), txt, fid)
        return {"ok": bool(res.get("ok")), "title": title, "как": "по file_id",
                "error": None if res.get("ok") else str(res.get("description"))[:200]}
    _fo_aio.get_running_loop().create_task(_fo_fi_bg(tok, ch, (title, data), txt, fallback=False))
    return {"ok": True, "title": title, "как": "загружается в фоне — результат: GET /refs/fnimg/last"}


@router.get("/plan")
async def fo_plan_get(p: Principal = Depends(max_level(1))):
    async with pool().acquire() as c:
        chat, title = await _fo_plan_chat(c, p.org_id)
        cfg = await _fo_plan_cfg(c, p.org_id)
        day = _fo_mt_now().date()
        prev = {}
        try:
            prev = {"morning": await _fo_plan_morning_msgs(c, p.org_id, day),
                    "evening": await _fo_plan_evening_msgs(c, p.org_id, day, cfg.get("eve_cut") or _FO_PLAN_DEF["eve_cut"]),
                    "week": await _fo_plan_week_msgs(c, p.org_id, _fo_mt_mon(day))}
        except Exception as e:
            prev = {"error": str(e)[:200]}
        groups = []
        try:
            groups = [{"chat_id": str(r["chat_id"]), "title": r["title"]} for r in await c.fetch(
                "SELECT chat_id, title FROM chat WHERE org_id=$1 AND channel='telegram' AND is_active AND chat_id ~ '^-?[0-9]+$' "
                "AND NOT EXISTS (SELECT 1 FROM client_chat cc WHERE cc.chat_pk = chat.id) ORDER BY added_at DESC", p.org_id)]
        except Exception:
            pass
        people = []
        try:
            for r in await c.fetch("SELECT e.id, e.name, cd.data->>'tg_id' AS tg_id FROM employee e JOIN fo_card cd ON cd.kind='employee' "
                                   "AND cd.ref_id=e.id::text AND cd.org_id::text=e.org_id::text WHERE e.org_id=$1::uuid "
                                   "AND coalesce(cd.data->>'tg_id','') ~ '^[0-9]+$' ORDER BY e.name", str(p.org_id)):
                people.append({"employee_id": str(r["id"]), "name": r["name"], "tg_id": str(r["tg_id"])})
        except Exception:
            pass
        owner_tg = bool(await _fo_plan_owner_tg(c, p.org_id))
        team = {"on": bool(cfg.get("team_on")), "mode": cfg.get("team_mode") or "daily",
                "morning": cfg.get("team_morning") or cfg.get("morning") or _FO_PLAN_DEF["morning"],
                "eve": cfg.get("team_eve") or cfg.get("eve_send") or _FO_PLAN_DEF["eve_send"],
                "wkend": bool(cfg.get("team_wkend")), "send_m": cfg.get("team_send_m", True), "send_e": cfg.get("team_send_e", True),
                "once": cfg.get("team_once") or {}, "once_done": cfg.get("team_once_done") or {},
                "last_m": cfg.get("last_team_morning"), "last_e": cfg.get("last_team_evening"), "people": []}
        try:
            tgm, names = await _fo_plan_team_tg(c, p.org_id), await _fo_plan_people(c, p.org_id)
            tk = await _fo_plan_tasks(c, p.org_id, day)
            for e, n in sorted(names.items(), key=lambda kv: kv[1] or "я"):
                tl = tk.get(e) or []
                team["people"].append({"employee_id": e, "name": n, "tg": bool(tgm.get(e)), "tasks": len(tl),
                                       "done": sum(1 for t in tl if t.get("done"))})
        except Exception:
            pass
    return {"cmds": {"on": not cfg.get("cmds_off"), "owner_tg": owner_tg}, "team": team,
            "chat": chat, "title": title, "settings": {k: cfg.get(k) or _FO_PLAN_DEF[k] for k in _FO_PLAN_DEF}, "off": bool(cfg.get("off")),
            "send": {k: cfg.get(k, True) for k in ("send_morning", "send_arts", "send_evening", "send_week")},
            "last": {k: cfg.get(k) for k in ("last_morning", "last_evening", "last_week")}, "preview": prev, "groups": groups,
            "people": people, "bot": bool(_fo_env("TG_BOT_TOKEN"))}


@router.post("/plan/send")
async def fo_plan_send_now(body: FoPlanSendIn, p: Principal = Depends(max_level(1))):
    day = None
    if body.day:
        try: day = _fo_dt.date.fromisoformat(body.day)
        except Exception: day = None
    async with pool().acquire() as c:
        if body.what in ("team_morning", "team_evening"):          # 280
            return await _fo_plan_team_run(c, p.org_id, body.what[5:], day)
        return await _fo_plan_run(c, p.org_id, body.what if body.what in ("morning", "evening", "week") else "morning", day, force=True)


@router.post("/plan/settings")
async def fo_plan_settings(body: FoPlanSetIn, p: Principal = Depends(max_level(1))):
    patch = {}
    for k in ("morning", "eve_cut", "eve_send"):
        v = getattr(body, k)
        if v and re.match(r"^\d{2}:\d{2}$", v):
            patch[k] = v
    if body.off is not None:
        patch["off"] = bool(body.off)
    for k in ("send_morning", "send_arts", "send_evening", "send_week", "cmds_off"):
        v = getattr(body, k)
        if v is not None:
            patch[k] = bool(v)
    if body.chat_id:
        patch["chat_id"] = str(body.chat_id); patch["title"] = body.title or ""
    # 280: «Разослать команде»
    for k in ("team_on", "team_wkend", "team_send_m", "team_send_e"):
        v = getattr(body, k)
        if v is not None:
            patch[k] = bool(v)
    if body.team_mode in ("daily", "once"):
        patch["team_mode"] = body.team_mode
    for k in ("team_morning", "team_eve"):
        v = getattr(body, k)
        if v and re.match(r"^\d{2}:\d{2}$", v):
            patch[k] = v
    if body.team_once_clear:
        patch["team_once"] = {}
    elif body.team_once_day or body.team_once_at or body.team_once_what:
        d0 = body.team_once_day if body.team_once_day and re.match(r"^\d{4}-\d{2}-\d{2}$", body.team_once_day) else None
        a0 = body.team_once_at if body.team_once_at and re.match(r"^\d{2}:\d{2}$", body.team_once_at) else None
        w0 = body.team_once_what if body.team_once_what in ("morning", "evening", "both") else None
        if not (d0 and a0 and w0):
            return {"ok": False, "why": "для разовой рассылки нужны дата, время и что слать"}
        patch["team_once"] = {"day": d0, "at": a0, "what": w0}
    async with pool().acquire() as c:
        if any(k in patch for k in ("team_on", "team_morning", "team_eve", "team_mode", "team_send_m", "team_send_e")):
            # время сегодня уже прошло — сегодня не досылаем задним числом, начнём со следующего раза
            cur = await _fo_plan_cfg(c, p.org_id)
            cur.update(patch)
            now = _fo_mt_now(); hm, td = now.strftime("%H:%M"), now.date().isoformat()
            if hm >= (cur.get("team_morning") or cur.get("morning") or _FO_PLAN_DEF["morning"]):
                patch["last_team_morning"] = td
            if hm >= (cur.get("team_eve") or cur.get("eve_send") or _FO_PLAN_DEF["eve_send"]):
                patch["last_team_evening"] = td
        if patch:
            await _fo_plan_cfg_set(c, p.org_id, patch)
        return {"ok": True, "settings": await _fo_plan_cfg(c, p.org_id)}


# ══ 264: МАТРИЦА ПРАВ — один источник правды ══════════════════════
# Право = ключ. Базовое правило: уровень роли ≤ порога. Модификаторы (действуют на уровни 3 и ниже):
# галочки роли «Доступы → Роли» (fo_state.roleCfg[<роль>].lim / .ext), выключатель settings.pmMoney (только РМ),
# флаги карточки сотрудника (money=no, canFns=1). Новая роль = строка в таблице role с уровнем — права
# получаются из матрицы сами; новое агентство — та же матрица, свои галочки.
_FO_ROLE_FRONT = {0: "admin", 1: "owner", 2: "dir", 3: "head", 4: "pm", 5: "mgr", 6: "jun", 7: "asst", 8: "client", 9: "client"}
_FO_PERM_RULES = [
    ("admin_panel",          0, "Панель администратора сервиса"),
    ("shadow",               2, "Режим тени"),
    ("access_grant",         1, "Выдавать доступы и приглашения"),
    ("access_block",         1, "Блокировать аккаунты"),
    ("roles_cfg",            2, "Галочки ролей и настройки агентства"),
    ("money_write",          2, "Менять суммы и даты платежей клиентов, оклады, премии, штрафы"),
    ("money_staff_read",     2, "Видеть чужие оклады"),
    ("money_client_read",    4, "Видеть суммы и даты платежей клиентов"),
    ("fin_screen",           4, "Экран «Деньги»"),
    ("client_contacts_read", 4, "Контакты клиентов: собственник, telegram, телефон, таблица"),
    ("client_cards_read",    4, "Открывать карточки клиентов"),
    ("client_cards_write",   4, "Править карточки клиентов, заводить кабинеты"),
    ("staff_cards_read",     4, "Открывать карточки коллег"),
    ("staff_cards_write",    4, "Править карточки коллег"),
    ("cab_fns_write",        4, "Заполнять функции кабинета"),
    ("fns_dir_write",        4, "Править справочник функций"),
    ("tasks_others_read",    4, "Видеть чужие задачи и загрузку"),
    ("tasks_set_others",     4, "Ставить задачи другим"),
    ("tasks_remove",         4, "Снимать и отменять задачи"),
    ("tasks_reassign",       4, "Перераспределять задачи"),
    ("tasks_approve",        2, "Согласовывать задачи (кроме назначенных согласующим)"),
    ("rating_all",           4, "Рейтинг всей команды (ниже — только свой)"),
    ("growth",               2, "«Рост» и модель найма"),
    ("sales",                4, "Отдел продаж"),
    ("aod_all",              4, "АОД целиком (ниже — только свои артикулы)"),
    ("aod",                  6, "АОД"),
    ("meet_manage",          4, "Планёрки: график, отправка"),
    ("meet_rules",           2, "Правила планёрок"),
    ("ai_settings",          2, "Настройки ИИ и согласующие"),
    ("office",               5, "Онлайн-офис"),
    ("export",               4, "Выгрузка данных"),
    ("reg",                  7, "Регламенты и справочник"),
]
_FO_LIM_MAP = {"money": ["money_client_read", "fin_screen"], "pay": ["money_sum_read"], "others": ["tasks_others_read"],
               "cards": ["client_cards_read"], "staff": ["staff_cards_read"], "growth": ["growth"], "rate": ["rating_all"],
               "del": ["tasks_remove"], "export": ["export"]}
_FO_EXT_MAP = {"grant": ["access_grant"], "block": ["access_block"], "setTask": ["tasks_set_others"], "approve": ["tasks_approve"],
               "editFns": ["fns_dir_write"], "aodAll": ["aod_all"], "fin": ["fin_screen", "money_client_read"], "cab": ["client_cards_write"]}
_FO_NO = ("no", "false", "0", "нет")
_FO_YES = ("1", "yes", "true", "да")


def _fo_perm_views(lvl, rf, can):
    cl = rf == "client"
    v = {"work": True, "people": True, "projects": True, "acct": True, "help": True, "orgcard": True,
         "cards": bool(can["client_cards_read"]), "aod": bool(can["aod"]) and not cl, "acc": bool(can["access_grant"]),
         "sales": bool(can["sales"]), "reg": bool(can["reg"]) and not cl, "guide": bool(can["reg"]) and not cl,
         "fns": not cl, "rate": not cl, "adm": bool(can["admin_panel"]), "meet": bool(can["meet_manage"]),
         "office": bool(can["office"]) or cl, "growth": bool(can["growth"]), "fin": bool(can["fin_screen"]),
         "setup": bool(can["client_cards_write"]), "newcab": bool(can["client_cards_write"]), "newman": bool(can["staff_cards_write"]),
         "unload": bool(can["tasks_reassign"]), "tariff": lvl <= 4}
    return v


async def _fo_perms(c, p, with_emp=True):
    """Права аккаунта — один расчёт для сервера и экрана."""
    lvl = _fo_lvl(p)
    rf = _FO_ROLE_FRONT.get(lvl, "client")
    uid = _fo_uid(p)
    rc = None
    try:
        rc = await c.fetchval("SELECT role_code FROM app_user WHERE id=$1", uid)
    except Exception:
        rc = None
    me, how = (None, None)
    if with_emp:
        try:
            me, how = await _fo_resolve_emp(c, p)
        except Exception:
            me, how = None, None
    lims, exts, pm_money = {}, {}, None
    try:
        for r in await c.fetch("SELECT key, data FROM fo_state WHERE org_id=$1::uuid AND scope='org' AND key IN ('roleCfg','settings')", str(p.org_id)):
            d = _fo_st_load(r["data"]) or {}
            if not isinstance(d, dict):
                continue
            if r["key"] == "roleCfg":
                rcfg = d.get(rf) if isinstance(d.get(rf), dict) else {}
                lims = {k: bool(v) for k, v in (rcfg.get("lim") or {}).items() if v}
                exts = {k: bool(v) for k, v in (rcfg.get("ext") or {}).items() if v}
            elif r["key"] == "settings":
                pm_money = d.get("pmMoney")
    except Exception:
        pass
    flags = {}
    if me:
        try:
            cd = _fo_st_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='employee' AND ref_id=$1 AND org_id=$2",
                                              str(me), p.org_id)) or {}
            if isinstance(cd, dict):
                for k in ("money", "canFns", "canGrant", "grade"):
                    if cd.get(k) not in (None, ""):
                        flags[k] = cd.get(k)
        except Exception:
            pass
    can = {k: lvl <= thr for k, thr, _ in _FO_PERM_RULES}
    can["money_sum_read"] = can["money_client_read"]
    if lvl > 2:
        for lk, keys in _FO_LIM_MAP.items():
            if lims.get(lk):
                for k in keys: can[k] = False
        for ek, keys in _FO_EXT_MAP.items():
            if exts.get(ek):
                for k in keys: can[k] = True
        if lvl == 4 and pm_money is False:
            can["money_client_read"] = False; can["fin_screen"] = False
        if str(flags.get("money") or "").strip().lower() in _FO_NO:
            can["money_client_read"] = False; can["fin_screen"] = False
        if str(flags.get("canFns") or "").strip().lower() in _FO_YES:
            can["cab_fns_write"] = True
        if str(flags.get("canGrant") or "").strip().lower() in _FO_YES:
            can["access_grant"] = True
    if not can["money_client_read"]:
        can["money_sum_read"] = False
    if lvl >= 5:
        can["client_contacts_read"] = False; can["money_client_read"] = False; can["money_sum_read"] = False
        can["money_staff_read"] = False; can["fin_screen"] = False
    if lvl > 2:
        can["money_write"] = False
    views = _fo_perm_views(lvl, rf, can)
    return {"level": lvl, "role_code": rc, "role": rf, "employee_id": me, "linked": bool(me), "link_how": how,
            "flags": flags, "lims": lims, "exts": exts, "can": can, "views": views}


async def _fo_can(c, p, key):
    return bool((await _fo_perms(c, p, with_emp=(key == "cab_fns_write")))["can"].get(key))


async def _fo_need(c, p, key, msg=None):
    if not await _fo_can(c, p, key):
        raise HTTPException(403, msg or ("Нет права: " + dict((k, d) for k, _t, d in _FO_PERM_RULES).get(key, key)))


@router.get("/me/perms")
async def fo_me_perms(p: Principal = Depends(current)):
    async with pool().acquire() as c:
        return await _fo_perms(c, p)


class _FoFakeP:
    def __init__(self, user_id, org_id, level):
        self.user_id, self.org_id, self.level = user_id, org_id, level


@router.get("/perms/audit")
async def fo_perms_audit(p: Principal = Depends(max_level(2))):
    """264: все аккаунты агентства — роль, уровень, привязка к сотруднику (и как), флаги, права; расхождения
    внутри одной роли с объяснением; карточки сотрудников без аккаунта."""
    out, issues = [], []
    async with pool().acquire() as c:
        try:
            users = await c.fetch("SELECT u.id, u.email, u.role_code, u.display_name, u." + _FO_NAME_COL + " AS base_name, "
                                  "u.is_active, r.level, r.__ROLE_TITLE__ AS role_title FROM app_user u JOIN role r ON r.code=u.role_code "
                                  "WHERE u.org_id=$1 ORDER BY r.level, u.email", p.org_id)
        except Exception:
            users = await c.fetch("SELECT u.id, u.email, u.role_code, u.display_name, u." + _FO_NAME_COL + " AS base_name, "
                                  "true AS is_active, r.level, r.__ROLE_TITLE__ AS role_title FROM app_user u JOIN role r ON r.code=u.role_code "
                                  "WHERE u.org_id=$1 ORDER BY r.level, u.email", p.org_id)
        emps = {str(e["id"]): e for e in await c.fetch("SELECT id, name, user_id FROM employee WHERE org_id=$1::uuid", str(p.org_id))}
        for u in users:
            fp = _FoFakeP(u["id"], p.org_id, int(u["level"]))
            pr = await _fo_perms(c, fp)
            e = emps.get(str(pr["employee_id"] or ""))
            row = {"id": str(u["id"]), "email": u["email"], "name": u["display_name"] or u["base_name"] or "",
                   "role_code": u["role_code"], "role_title": u["role_title"] or u["role_code"], "level": int(u["level"]),
                   "role": pr["role"], "active": bool(u["is_active"]), "employee": ({"id": str(e["id"]), "name": e["name"]} if e else None),
                   "link_how": pr["link_how"], "flags": pr["flags"], "lims": pr["lims"], "exts": pr["exts"], "can": pr["can"], "views": pr["views"]}
            out.append(row)
            if not pr["linked"] and int(u["level"]) >= 3:
                issues.append({"kind": "unlinked", "email": u["email"], "role_code": u["role_code"],
                               "text": "Аккаунт %s (%s) не привязан к карточке сотрудника: не совпали ни e-mail, ни имя. Впишите e-mail аккаунта в карточку сотрудника (поле «Рабочая почта») — привяжется само." % (u["email"], u["role_code"])})
        by_role = {}
        for r in out:
            by_role.setdefault(r["role_code"], []).append(r)
        for rcode, rows in by_role.items():
            if len(rows) < 2:
                continue
            base = rows[0]
            for r in rows[1:]:
                diff = [k for k in base["can"] if base["can"][k] != r["can"].get(k)]
                if diff:
                    why = []
                    for k in ("money", "canFns", "canGrant"):
                        if (base["flags"].get(k) or "") != (r["flags"].get(k) or ""):
                            why.append("флаг карточки «%s»: %s / %s" % (k, base["flags"].get(k) or "—", r["flags"].get(k) or "—"))
                    if bool(base["employee"]) != bool(r["employee"]):
                        why.append("привязка к карточке: %s / %s" % ("есть" if base["employee"] else "нет", "есть" if r["employee"] else "нет"))
                    issues.append({"kind": "diverge", "role_code": rcode, "emails": [base["email"], r["email"]], "diff": diff,
                                   "text": "Роль %s: у %s и %s разные права (%s) — причина: %s" % (rcode, base["email"], r["email"], ", ".join(diff), "; ".join(why) or "не найдена (сообщите разработчику)")})
        owners = [r for r in out if int(r["level"]) == 1]
        if len(owners) != 1:
            issues.insert(0, {"kind": "owners", "count": len(owners), "emails": [r["email"] for r in owners],
                              "text": ("Собственников в агентстве %d — должен быть ровно один: " % len(owners)) + (", ".join(r["email"] for r in owners) or "никого")})
        linked_ids = set(str(r["employee"]["id"]) for r in out if r["employee"])
        no_acc = [{"id": k, "name": e["name"]} for k, e in emps.items() if k not in linked_ids]
        names = {}
        for e in emps.values():
            names.setdefault(str(e["name"] or "").strip().lower(), []).append(str(e["id"]))
        for nm, ids in names.items():
            if nm and len(ids) > 1:
                issues.append({"kind": "dup_employee", "name": nm, "ids": ids, "text": "Две карточки сотрудника с именем «%s» — привязка по имени может попасть не в ту" % nm})
    matrix = [{"key": k, "max_level": thr, "title": d} for k, thr, d in _FO_PERM_RULES]
    return {"accounts": out, "employees_without_account": no_acc, "issues": issues, "matrix": matrix,
            "owner": (owners[0]["email"] if len(owners) == 1 else None), "owners_count": len(owners),
            "lim_map": _FO_LIM_MAP, "ext_map": _FO_EXT_MAP, "role_front": {str(k): v for k, v in _FO_ROLE_FRONT.items()}}


@router.get("/perms/selftest")
async def fo_perms_selftest(p: Principal = Depends(max_level(2))):
    """264: автопроверка на живых данных агентства — по каждому уровню: что отдают фильтры карточек и задач,
    и не уходит ли лишнее. Запускать после каждого шага сервера."""
    res = []
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT kind, ref_id, data FROM fo_card WHERE org_id=$1", p.org_id)
    cards = []
    for r in rows:
        d = r["data"]
        if isinstance(d, str):
            try: d = _fo_json.loads(d)
            except Exception: d = {}
        cards.append({"kind": r["kind"], "ref_id": r["ref_id"], "data": d or {}})
    for lvl in (0, 1, 2, 3, 4, 5, 6, 7, 8):
        fp = _FoFakeP("00000000-0000-0000-0000-000000000000", p.org_id, lvl)
        async with pool().acquire() as c:
            pr = await _fo_perms(c, fp, with_emp=False)
        out = await _fo_cards_scope(fp, cards)
        leak_money, leak_contact, leak_pay = [], [], []
        for cd in out:
            d = cd.get("data") or {}
            if cd["kind"] in ("client", "cab"):
                if not pr["can"]["money_client_read"]:
                    leak_money += [k for k in d if k in _FO_PRIV_MONEY or str(k).lower().startswith("pay")]
                if not pr["can"]["client_contacts_read"]:
                    leak_contact += [k for k in d if k in _FO_PRIV_CLIENT and k not in _FO_PRIV_MONEY]
            elif cd["kind"] == "employee" and not pr["can"]["money_staff_read"]:
                leak_pay += [k for k in d if _FO_PRIV_PAY.search(str(k))]
        async with pool().acquire() as c:
            ids = await _fo_scope_ids(c, fp)
        res.append({"level": lvl, "role": pr["role"], "cards_in": len(cards), "cards_out": len(out),
                    "money_leak": sorted(set(leak_money))[:10], "contact_leak": sorted(set(leak_contact))[:10], "pay_leak": sorted(set(leak_pay))[:10],
                    "tasks_scope": "все" if ids is None else ("свои" if ids else "ничего (нет карточки)"),
                    "ok": not (leak_money or leak_contact or leak_pay)})
    return {"ok": all(r["ok"] for r in res), "levels": res}


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
            # 270: агентство того, кто добавил бота (tg_id в карточке сотрудника); иначе — с наибольшей командой
            frm = ev.get("from") or {}
            try:
                if frm.get("id"):
                    org = await c.fetchval("SELECT org_id FROM fo_card WHERE kind='employee' AND data->>'tg_id'=$1 LIMIT 1", str(frm["id"]))
            except Exception:
                org = None
            if not org:
                try:
                    org = await c.fetchval("SELECT org_id FROM employee GROUP BY org_id ORDER BY count(*) DESC LIMIT 1")
                except Exception:
                    org = None
        if not org:
            org = await c.fetchval("SELECT id FROM org ORDER BY created_at LIMIT 1")
        await c.execute(
            "INSERT INTO chat (org_id, channel, chat_id, title) VALUES ($1, 'telegram', $2, $3) "
            "ON CONFLICT (org_id, channel, chat_id) DO UPDATE SET title=EXCLUDED.title, is_active=true",
            org, str(chat["id"]), title)


async def _fo_ai_on_msg(msg, src=""):
    try:
        chat = msg.get("chat") or {}
        tg = str(chat.get("id") or "")
        if not tg or chat.get("type") == "private":
            return
        frm = msg.get("from") or {}
        if frm.get("is_bot"):
            return
        text = str(msg.get("text") or msg.get("caption") or "").strip()
        if src == "meet":
            await _fo_mt_on_copy(msg, text)   # копия бота планёрок: только планёрки, историю пишет бот задач (225)
            return
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
                    _neg = await _fo_meet_match(c, link["org_id"], str(link["client_id"]), tg, msg, text,
                                                ids_ok=_fo_mt_ids_ok(msg, src))
                except Exception:
                    _neg = None
            if _neg:
                why = "ответ по времени планёрки — разбирает бот планёрок"
                _fo_aio.get_running_loop().create_task(
                    _fo_mt_claim_run(link["org_id"], _neg, msg, text, pk, src or "main"))
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
    em = upd.get("edited_message")
    if em and (em.get("chat") or {}).get("type") != "private" and request.headers.get("x-fo-bot", "") != "meet":
        _fo_aio.get_running_loop().create_task(_fo_ai_on_edit(em))   # сообщение исправили (228)
    msg = upd.get("message")
    if msg:
        if (msg.get("chat") or {}).get("type") == "private":
            _fo_aio.get_running_loop().create_task(_fo_mt_private(msg, request.headers.get("x-fo-bot", "")))
        else:
            _fo_aio.get_running_loop().create_task(_fo_plan_route(msg, request.headers.get("x-fo-bot", "")))   # 273
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
    lvl = _fo_lvl(p)
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
    lvl = _fo_lvl(p)
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
async def fo_ai_settings_get(p: Principal = Depends(max_level(4))):
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
_FO_MT_DOWACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
_FO_MT_DOWGEN = ["понедельника", "вторника", "среды", "четверга", "пятницы", "субботы", "воскресенья"]
_FO_MT_LVL = {1: (60, 80, 60), 2: (40, 50, 45), 3: (35, 40, 40)}      # мин, макс, по умолчанию
# рабочие дни пн–пт; планёрка заканчивается не позже 18:00: часовая — не позже 17:00, получасовая — 17:30 (Виталий 29.09)
_FO_MT_DEF = {"brk": 15, "gap": 180, "from": 10 * 60, "to": 18 * 60, "auto": True, "auto_at": 10 * 60}
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
        f = st["from"] if f is None else f
        t = st["to"] if t is None else t
        if t - f >= 120:
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
            org_id, str(client_id), chat_pk, tg, mid if test else -mid, text[:4000])
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


async def _fo_mt_link_mail(c, uid, un, text, bot):
    """234 (Виталий 30.09: «бот не понимает, что я собственник»): собственник, директор или руководитель без карточки
    сотрудника привязывается по почте входа — бот шлёт код на почту, человек присылает код сюда."""
    t = str(text or "").strip()
    row = await c.fetchrow("SELECT user_id, code, bot, created_at FROM fo_tg_link WHERE tg_id=$1", int(uid))
    if re.fullmatch(r"\d{4}", t):
        if not row:
            return "Сначала отправьте почту, под которой входите в сервис."
        if (_fo_dt.datetime.now(_fo_dt.timezone.utc) - row["created_at"]).total_seconds() > 900:
            await c.execute("DELETE FROM fo_tg_link WHERE tg_id=$1", int(uid))
            return "Код устарел. Отправьте почту ещё раз — пришлём новый."
        if t != row["code"]:
            return "Код не подошёл. Проверьте письмо и пришлите код ещё раз."
        u = await c.fetchrow("SELECT u.id, u.org_id, u.display_name, u.role_code, r.level FROM app_user u "
                             "JOIN role r ON r.code=u.role_code WHERE u.id=$1", row["user_id"])
        emp = await c.fetchval("SELECT id FROM employee WHERE user_id=$1 AND is_active ORDER BY created_at LIMIT 1", u["id"]) \
            if u else None
        ref = str(emp or u["id"])
        old = _fo_mt_load(await c.fetchval("SELECT data FROM fo_card WHERE kind='employee' AND ref_id=$1", ref), {}) or {}
        bots = sorted(set((old.get("tg_bots") or []) + [bot or "main"]))
        d = {"tg_id": int(uid), "tg_bots": bots}
        if un and not old.get("tg"):
            d["tg"] = un
        await c.execute("INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('employee', $1, $2, $3::jsonb) "
                        "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data, updated_at = now()",
                        ref, u["org_id"], _fo_json.dumps(d))
        await c.execute("DELETE FROM fo_tg_link WHERE tg_id=$1", int(uid))
        name = (u["display_name"] or "").split(" ")[0]
        who = {"owner": "собственник", "director": "директор", "head": "руководитель"}.get(u["role_code"], "руководитель")
        if bot == "meet":
            return ("Готово, %s! Вы %s агентства. Сюда будет приходить график планёрок: каждый будний день в 18:00 — "
                    "на завтра и до конца недели, в пятницу — на всю следующую; изменения времени на ближайшие дни — сразу."
                    % (name, who)).replace(", !", "!") + ("" if emp else "\n(В команде вы не заведены как сотрудник — "
                                                                       "списки ведущим вам не приходят, только общий график.)")
        return ("Готово, %s! Вы %s агентства. Это бот задач: он ставит задачи из чатов с клиентами." % (name, who)).replace(", !", "!")
    if "@" in t and "." in t.split("@")[-1] and " " not in t:
        mail = t.lower()
        u = await c.fetchrow("SELECT u.id, u.email, r.level FROM app_user u JOIN role r ON r.code=u.role_code "
                             "WHERE lower(u.email)=$1 AND u.is_active ORDER BY r.level LIMIT 1", mail)
        if not u:
            return "Такой почты в сервисе нет. Проверьте, под какой почтой вы входите."
        if int(u["level"]) > 3:
            return ("Привязка по почте — для собственника, директора и руководителя. Сотруднику нужно, чтобы его ник "
                    "вписали в карточку сотрудника в сервисе.")
        import random as _rnd
        code = "%04d" % _rnd.randint(0, 9999)
        await c.execute("INSERT INTO fo_tg_link (tg_id, user_id, code, bot, created_at) VALUES ($1, $2, $3, $4, now()) "
                        "ON CONFLICT (tg_id) DO UPDATE SET user_id=EXCLUDED.user_id, code=EXCLUDED.code, bot=EXCLUDED.bot, "
                        "created_at=now()", int(uid), u["id"], code, bot or "main")
        ok = await _fo_send(u["email"], "Flater: код привязки Telegram",
                            "Код: %s\nДействует 15 минут. Пришлите его боту в Telegram.\nЕсли это не вы — просто не отвечайте." % code)
        if not ok:
            return "Не получилось отправить письмо. Напишите Виталию или админу сервиса — привяжут вручную."
        a, b = u["email"].split("@", 1)
        return "Отправили код на %s***@%s. Пришлите его сюда." % (a[:2], b)
    return None


async def _fo_mt_private(msg, bot=""):
    """Личка с ботом: сотрудник пишет /start — привязываем его по нику из карточки сотрудника;
    собственник или директор без карточки — по почте входа и коду (234). Сюда приходят уведомления о планёрках."""
    try:
        frm = msg.get("from") or {}
        uid, un = frm.get("id"), str(frm.get("username") or "").lower()
        if not uid or frm.get("is_bot"):
            return
        ans = ""
        text = str(msg.get("text") or "").strip()
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
                    ans = ("Готово, %s! Сюда будут приходить: список ваших планёрок на два рабочих дня вперёд — каждый будний "
                           "день в 18:00; изменения времени на ближайшие дни; где нужно ваше решение; напоминание за час "
                           "до начала." % name).replace(", !", "!")
                else:
                    mb = await _fo_mt_botname()
                    ans = ("Готово, %s! Это бот задач сервиса Flater: он ставит задачи из чатов с клиентами. "
                           "Уведомления о планёрках присылает другой бот%s — нажмите Start и у него." % (name, (" — @" + mb) if mb else "")).replace(", !", "!")
            else:
                try:
                    ans = await _fo_mt_link_mail(c, uid, un, text, bot)
                except Exception as e:
                    ans = "Не получилось: " + str(e)[:120]
                if not ans:
                    ans = ("Не нашли вас в команде агентства. Попросите руководителя вписать ваш ник @%s в карточку "
                           "сотрудника в сервисе и нажмите /start ещё раз.\n\nЕсли вы собственник, директор или руководитель — "
                           "отправьте сюда почту, под которой входите в сервис: пришлём код на неё." % (frm.get("username") or "…"))
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
# планёрка = совещание = звонок = созвон = кол = «проведём зум» — всё про планёрку (Виталий 29.09)
_FO_MT_SYN = r"план[её]рк|совещ|звон|\bкол(л)?[аеуы]?\b(?!-)|\bcall\b|зум|zoom|телемост|встреч"
# выходные; «на этой неделе не получится»; явный перенос; явная дополнительная (Виталий 29.09)
_FO_MT_WKND_RX = re.compile(r"суббот|воскрес|выходн|\bсб\b", re.I)
_FO_MT_WEEKOFF_RX = re.compile(
    r"не\s+на\s+эт(ой|у)\s+недел|"
    r"эт(ой|у|от)\s+недел\w*[^.?!]{0,50}(не\s+(получится|сможем|можем|выйдет|будет|успеем|до\s+того|до\s+этого)|без\s+(план|созв|совещ|встреч|звон|кол|зум)|пропуст|отмен|не\s+нужн)|"
    r"(не\s+(получится|сможем|можем|выйдет|будет|успеем)|пропуст\w*|отмен\w*|без\s+(план|созв|совещ|встреч|звон|кол|зум)\w*)[^.?!]{0,50}эт(ой|у|от)\s+недел",
    re.I)
_FO_MT_MOVE_RX = re.compile(r"перенес|перенос|сдвин|вместо|поменя|передвин", re.I)
_FO_MT_EXTRA_RX = re.compile(r"дополнительн|ещ[её](\s|$|,)|втор(ую|ой|ая)|добав|отдельн", re.I)
# 244 (Виталий 30.09): пожелание по части дня, просьба предложить слоты, правка «я просила после обеда»
_FO_MT_PART_RX = [("morning", r"до\s+обед|с\s+утра|\bутром\b|\bутро\b|перв(ой|ую)\s+полов|пораньше|в\s+начале\s+дня"),
                  ("afternoon", r"после\s+обед|во\s+втор(ой|ую)\s+полов|\bдн[её]м\b|после\s+полудня|попозже"),
                  ("evening", r"ближе\s+к\s+вечер|\bвечер|под\s+вечер|к\s+концу\s+дня|в\s+конце\s+дня|конц[ае]\s+дня")]
_FO_MT_PART_WORD = {"morning": "в первой половине дня", "afternoon": "после обеда", "evening": "ближе к вечеру"}
_FO_MT_ASK_RX = re.compile(r"слот|вариант|какое\s+время|как(ое|ие)\s+(есть|окн)|когда\s+(вам\s+)?(удобно|можете|сможете|получится|свободн)|"
                           r"предлож|есть\s+(окно|время)|во\s+сколько\s+(можете|удобно|сможете)|что\s+(есть|можете)", re.I)
_FO_MT_FIX_RX = re.compile(r"не\s+то\s+время|просил[аи]?\s+(же\s+)?(после|до|ближе|утр|вечер|дн[её]м)|назначил|поставил[аи]?\s+(не|на)|"
                           r"не\s+так|не\s+то,?\s+что|я\s+(же\s+)?(говорил|писал|сказал)", re.I)


def _fo_mt_part(text, st, mins):
    """Пожелание по части дня → окно начала планёрки: до обеда 10:00–12:30, после обеда с 14:00, ближе к вечеру
    с 16:00, «после 15» — с 15:00, «до 12» — чтобы закончить к 12:00, «с 14 до 16» — в этом окне."""
    t = str(text or "").lower().replace("ё", "е")
    lo, hi, name = None, None, None
    for nm, rx in _FO_MT_PART_RX:
        if re.search(rx, t):
            name = nm
            break
    if name == "morning":
        lo, hi = st["from"], 12 * 60
    elif name == "afternoon":
        lo, hi = 14 * 60, st["to"] - mins
    elif name == "evening":
        lo, hi = 16 * 60, st["to"] - mins
    m = re.search(r"\bс\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s+до\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b", t)
    if m and 8 <= int(m.group(1)) <= 20 and 8 <= int(m.group(3)) <= 20:
        lo = int(m.group(1)) * 60 + int(m.group(2) or 0)
        hi = int(m.group(3)) * 60 + int(m.group(4) or 0) - mins
        name = "span"
    else:
        m = re.search(r"\bпосле\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b(?!\s*(мин|час))", t)
        if m and 8 <= int(m.group(1)) <= 20:
            lo, hi, name = int(m.group(1)) * 60 + int(m.group(2) or 0), st["to"] - mins, "after"
        m = re.search(r"\bдо\s+([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b(?!\s*(мин|час))", t)
        if m and 8 <= int(m.group(1)) <= 20:
            hi = int(m.group(1)) * 60 + int(m.group(2) or 0) - mins
            lo = lo if lo is not None else st["from"]
            name = name or "before"
    if name is None:
        return None
    lo = max(st["from"], lo if lo is not None else st["from"])
    hi = min(st["to"] - mins, hi if hi is not None else st["to"] - mins)
    word = _FO_MT_PART_WORD.get(name) or {"after": "после %s" % _fo_mt_hm(lo), "before": "до %s" % _fo_mt_hm(hi + mins),
                                          "span": "с %s до %s" % (_fo_mt_hm(lo), _fo_mt_hm(hi + mins))}[name]
    return {"name": name, "lo": lo, "hi": hi, "word": word}


def _fo_mt_range_slots(busy, host, d, lo, hi, mins, st, n=3, after=None):
    """Варианты начала в окне [lo, hi]: сначала вплотную к планёркам ведущего (одним блоком), потом сетка по
    30 минут — первый, последний и средний, чтобы клиент выбирал из разного времени."""
    lo, hi = max(lo, st["from"]), min(hi, st["to"] - mins)
    if after is not None:
        lo = max(lo, after)
    if hi < lo:
        return []
    have = sorted(busy.get((host, d), []))
    adj = set()
    for x, y, _ in have:
        adj.add(y + st["brk"])
        adj.add(x - st["brk"] - mins)
    good = sorted(t for t in adj if lo <= t <= hi and _fo_mt_fits(busy, host, d, t, mins, st))
    g0 = ((lo + 29) // 30) * 30
    grid = [t for t in range(g0, hi + 1, 30) if _fo_mt_fits(busy, host, d, t, mins, st) and t not in good]
    if not grid and not good:
        grid = [t for t in range(lo, hi + 1, 5) if _fo_mt_fits(busy, host, d, t, mins, st)]
    out = good[:1]
    for t in ([grid[0], grid[-1], grid[len(grid) // 2]] if grid else []) + good[1:]:
        if len(out) >= n:
            break
        if t not in out:
            out.append(t)
    return sorted(out)


def _fo_mt_pick(text, opts):
    """Выбор из предложенных слотов: время из списка, «первое / второе / третье», «любое», «да» при одном варианте.
    None — клиент назвал другое время или непонятно."""
    t = str(text or "").lower().replace("ё", "е")
    rx = _fo_mt_rx(text)
    if rx["time"]:
        return rx["time"] if rx["time"] in opts else None
    for i, w in enumerate((r"перв|\b1\b|\bодин\b", r"втор|\b2\b|\bдва\b", r"трет|\b3\b|\bтри\b")):
        if i < len(opts) and re.search(w, t):
            return opts[i]
    if re.search(r"любо[ей]|без\s+разниц|на\s+ваш|вс[её]\s+равно|как\s+удобно|как\s+вам", t):
        return opts[0]
    if rx["yes"] and len(opts) == 1:
        return opts[0]
    return None


def _fo_mt_last_change(r, items):
    """Последняя перенесённая или добавленная планёрка (по журналу «стало: YYYY-MM-DD HH:MM») — для правок вроде
    «ты назначил на 11:00, я просила после обеда»."""
    try:
        log = _fo_mt_load(r["log"], []) if r else []
    except Exception:
        log = []
    for x in reversed(log or []):
        if isinstance(x, dict) and x.get("стало"):
            try:
                d, tm = str(x["стало"]).split(" ")[:2]
            except Exception:
                return None
            day = _fo_mt_date(d)
            return next((i for i in items if i["day"] == day and i["time"] == tm), None)
    return None
_FO_MT_ANS_RX = re.compile(
    r"(^|[\s,.!])(да|ок|окей|ok|ага|подходит|удобно|неудобно|не удобно|договорились|согласн\w*|давайте|норм\w*|хорошо|"
    r"отлично|не могу|не можем|не получится|в силе)([\s,.!)]|$)|\b([01]?\d|2[0-3])[:.][0-5]\d\b|\bв\s*([01]?\d|2[0-3])\b|"
    r"понедельн|вторник|\bсред[уаы]\b|четверг|пятниц|\bпн\b|\bвт\b|\bср\b|\bчт\b|\bпт\b|перенес|врем|" + _FO_MT_SYN,
    re.I)

_FO_MT_SYS = (
    "Агентство договаривается с клиентом о времени еженедельной планёрки (созвона по кабинету на маркетплейсе). "
    "Тебе дают, что предложило агентство, и ответ клиента. Определи смысл ответа.\n"
    "Перед сообщением может быть переписка чата: по ней пойми контекст — клиент отвечает на вопрос бота или сотрудника про время, продолжает разговор. Решаешь по сообщению клиента; сообщения сотрудников агентства — не ответ клиента.\n"
    "Планёрка, совещание, звонок, созвон, кол (call), «проведём зум» (Zoom, Телемост) — это всё одно и то же: планёрка.\n"
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
        if _FO_MT_CTX.get():
            usr = "Переписка в чате перед этим (сверху — раньше):\n%s\n\n%s" % (_FO_MT_CTX.get(), usr)
        try:
            txt, _u = await _fo_aio.to_thread(_fo_ygpt_sync, [{"role": "system", "text": sys_t},
                                                              {"role": "user", "text": usr}], 200)
            js = _fo_ai_json(txt) or {}
            if js.get("answer") in ("yes", "other", "no", "unclear", "not_about"):
                js["by"] = "ИИ"
                js["slots"] = _fo_mt_norm(js.get("slots"), rx) if js["answer"] == "other" else []
                # 288: клиент прямо назвал один день — он важнее номера дня от ИИ (ИИ путает 2/3: «среда» → четверг)
                if js["answer"] == "other" and len(rx["days"]) == 1 and js["slots"] and \
                        any(sl.get("day") != rx["days"][0] for sl in js["slots"]):
                    js["slots"] = [{"day": rx["days"][0], "time": sl.get("time") or rx["time"]} for sl in js["slots"][:1]]
                    js["by"] = "ИИ + день по тексту"
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
    # проджекту отдельно не пишем: планёрка придёт в вечернем списке (Виталий 29.09: «не о каждом чихе»)
    return {"state": "agreed", "pin": pin, "send": err or "отправлено", "задачи": applied}


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
    soft = _FO_MT_SOFT.get()
    async with pool().acquire() as c:
        try:
            _FO_MT_CTX.set(await _fo_mt_history(c, org_id, client_id, text))
        except Exception:
            _FO_MT_CTX.set("")
        r = await _fo_mt_row(c, org_id, client_id)
        if not r or r["status"] == "off":
            return {"state": "нет графика"}
        pend = _fo_mt_load(r["pend"], None)
        if pend:
            return await _fo_mt_pend_answer(c, org_id, client_id, r, pend, text, msg_id, pk, test)
        if _fo_mt_weekoff(text):
            return await _fo_mt_week_off(c, org_id, client_id, r, text, msg_id, test)
        if r["status"] != "proposed":
            return await _fo_mt_request(c, org_id, client_id, r, text, msg_id, pk, test)
        offer = _fo_mt_slots(r["offer"]) or _fo_mt_slots(r["slots"])
    js = await _fo_mt_parse(text, offer, org_id)
    kind = js.get("answer")
    if kind == "not_about" or (soft and kind == "unclear"):
        if not test:
            try:
                await _fo_mt_ai_handoff(pk)
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
        if kind == "other" or (kind in ("no", "unclear") and _FO_MT_WKND_RX.search(str(text or ""))):
            # своё время клиента меняет только эту неделю, график остаётся (Виталий 29.09)
            return await _fo_mt_prop_other(c, org_id, client_id, r, offer, js, text, msg_id, test)
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
    txt = ("🔴 Не согласовано.\n"
           "Спасибо! Передали ваш вопрос проджекту — он свяжется с вами и согласует удобное время.")
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=msg_id, test=test)
    r = await _fo_mt_row(c, org_id, client_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    dm = await _fo_mt_notify(c, _fo_mt_eff(r) if r else {}, "⚠ %s: нужно ваше решение по времени планёрки — %s. "
                             "Договоритесь с клиентом и отметьте время в сервисе («Календарь планёрок»)." % (cab, why), test)
    await c.execute("UPDATE fo_meet SET attn=$3, log=log||$4::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), "нужно решение проджекта: " + why, _fo_mt_item("передано проджекту", why=why, итог=dm))
    return {"state": "handoff", "why": why, "проджекту": dm}


async def _fo_meet_match(c, org_id, client_id, tg, msg, text, ids_ok=True):
    """Сообщение клиента — ответ боту планёрок? Реплай на сообщение бота — да; без реплая — если ждём ответа
    не дольше трёх суток и в тексте есть «да», время, день недели или «планёрка». Ошибиться не страшно:
    сообщение не про планёрку ИИ вернёт в обычный разбор задач."""
    r = await c.fetchrow("SELECT client_id, status, msg_id, sent_at, answered_at, pend FROM fo_meet "
                         "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id))
    if not r or r["status"] == "off":
        return None
    try:
        if await _fo_mt_role(c, org_id, client_id, msg.get("from") or {}) == "staff":
            return None     # пишет сотрудник агентства — это не ответ клиента (Виталий 29.09); в историю идёт как контекст
    except Exception:
        pass
    cid = str(r["client_id"])
    rep = msg.get("reply_to_message") or {}
    frm = rep.get("from") or {}
    if ids_ok and rep.get("message_id") and r["msg_id"] and int(rep["message_id"]) == int(r["msg_id"]):
        return cid
    if frm.get("is_bot") and _FO_MT_ME.get("v") and frm.get("username") == _FO_MT_ME.get("v"):
        return cid
    if rep.get("message_id") and not frm.get("is_bot"):
        return cid if _FO_MT_REQ_RX.search(str(text or "")) else None
    waiting = r["status"] == "proposed" or bool(_fo_mt_load(r["pend"], None))
    fresh = r["sent_at"] and (_fo_dt.datetime.now(_fo_dt.timezone.utc) - r["sent_at"]).total_seconds() <= 3 * 86400
    if waiting and fresh and _FO_MT_ANS_RX.search(str(text or "")):
        return cid
    if _FO_MT_REQ_RX.search(str(text or "")) or _FO_MT_WEEKOFF_RX.search(str(text or "")):
        return cid
    # следующее сообщение клиента после вопроса бота (в течение 30 минут) — тоже ответ, «мягкий»: если оно не про
    # планёрку, бот молчит и отдаёт его в разбор задач (Виталий 29.09: «не на этой неделе» бот пропустил)
    if waiting and r["sent_at"] and (_fo_dt.datetime.now(_fo_dt.timezone.utc) - r["sent_at"]).total_seconds() <= 1800 \
            and (r["answered_at"] is None or r["answered_at"] < r["sent_at"]):
        return _FoMtCid(cid, True)
    return None


# ── одно сообщение клиента — один разбор (225, 29.09) ──
# В чате два бота. В обычной группе Telegram присылает сообщение каждому боту под своим номером, и сервер
# разбирал его дважды (игра 29.09: «время комфортно» — в 14:58 и ещё раз в 15:00). Теперь:
# копия бота задач пишет историю и идёт в разбор задач; планёрку разбирает та копия, что пришла первой
# (ключ — чат, автор, время, текст); «не про планёрку» уходит в разбор задач один раз — по копии бота задач
# (её номер нужен для реакций бота задач).
import hashlib as _fo_hl
import contextvars as _fo_cv

_FO_MT_KEY = _fo_cv.ContextVar("fo_mt_key", default=None)
_FO_MT_SOFT = _fo_cv.ContextVar("fo_mt_soft", default=False)
_FO_MT_CTX = _fo_cv.ContextVar("fo_mt_ctx", default="")
_FO_MT_PPL = {}


async def _fo_mt_people(c, org_id):
    """Кто есть кто в чатах: ники сотрудников (карточки сотрудников) и ники клиентов (карточка клиента, поле Telegram).
    Кэш на 5 минут."""
    k = str(org_id)
    hit = _FO_MT_PPL.get(k)
    if hit and _fo_time.time() - hit["t"] < 300:
        return hit
    staff_tg, staff_id, client_tg = set(), set(), {}
    for r in await c.fetch("SELECT kind, ref_id, data FROM fo_card WHERE kind IN ('employee','client','cab') "
                           "AND (org_id=$1 OR org_id IS NULL)", org_id):
        d = _fo_mt_load(r["data"], {}) or {}
        tgs = {x.lstrip("@").lower() for x in re.split(r"[\s,;]+", str(d.get("tg") or "")) if x.strip("@ ")}
        if r["kind"] == "employee":
            staff_tg |= tgs
            if d.get("tg_id"):
                staff_id.add(str(d["tg_id"]))
        elif tgs:
            client_tg.setdefault(str(r["ref_id"]), set()).update(tgs)
    hit = {"t": _fo_time.time(), "staff_tg": staff_tg, "staff_id": staff_id, "client_tg": client_tg}
    _FO_MT_PPL[k] = hit
    return hit


async def _fo_mt_role(c, org_id, client_id, frm):
    """client — ник из карточки клиента; staff — ник или номер Telegram сотрудника; other — кто-то ещё со стороны клиента."""
    p = await _fo_mt_people(c, org_id)
    un, uid = str((frm or {}).get("username") or "").lower(), str((frm or {}).get("id") or "")
    if un and un in p["client_tg"].get(str(client_id), set()):
        return "client"
    if (un and un in p["staff_tg"]) or (uid and uid in p["staff_id"]):
        return "staff"
    return "other"


async def _fo_mt_history(c, org_id, client_id, text, n=10):
    """Переписка чата перед сообщением — агенту планёрок для контекста: кто что писал (клиент, сотрудник, бот)."""
    p = await _fo_mt_people(c, org_id)
    ctg = p["client_tg"].get(str(client_id), set())
    rows = list(reversed(await c.fetch(
        "SELECT author, author_tg, text FROM fo_chat_msg WHERE client_id=$1::uuid AND kind='client' AND text<>'' "
        "ORDER BY id DESC LIMIT $2", str(client_id), n + 1)))
    if rows and (rows[-1]["text"] or "").strip() == str(text or "").strip():
        rows = rows[:-1]
    out = []
    for r in rows[-n:]:
        a, tg = r["author"] or "", str(r["author_tg"] or "").lower()
        who = ("Бот планёрок" if a == "Бот планёрок" else "Клиент" if (tg and tg in ctg) or a == "Клиент (проверка)"
               else ("Сотрудник агентства %s" % a) if tg and tg in p["staff_tg"] else ("Участник со стороны клиента %s" % a))
        out.append("%s: %s" % (who, re.sub(r"\s+", " ", r["text"] or "")[:220]))
    return "\n".join(out)


class _FoMtCid(str):
    """Клиент и признак «мягкого» совпадения: сообщение сразу после вопроса бота, без слов про планёрку."""
    def __new__(cls, v, soft=False):
        o = str.__new__(cls, v)
        o.soft = soft
        return o


def _fo_mt_split():
    """Есть отдельный бот планёрок — сообщения приходят двумя копиями."""
    m = _fo_env("TG_MEET_BOT_TOKEN")
    return bool(m) and m != _fo_env("TG_BOT_TOKEN")


def _fo_mt_ids_ok(msg, src):
    """Номер сообщения годится боту планёрок (реплай, сверка): копия от него самого, один бот в чате или супергруппа
    (там нумерация общая)."""
    return src == "meet" or not _fo_mt_split() or (msg.get("chat") or {}).get("type") == "supergroup"


def _fo_mt_key(msg, text):
    return (str((msg.get("chat") or {}).get("id") or ""), int((msg.get("from") or {}).get("id") or 0),
            int(msg.get("date") or 0), _fo_hl.md5(str(text or "").encode("utf-8")).hexdigest()[:16])


async def _fo_mt_claim_run(org_id, client_id, msg, text, pk, src):
    """Разбор планёрки достаётся первой пришедшей копии; вторая только связывает запись истории."""
    key = _fo_mt_key(msg, text)
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "INSERT INTO fo_meet_seen (tg_chat_id, from_id, at, h, by, main_pk) VALUES ($1,$2,$3,$4,$5,$6) "
            "ON CONFLICT (tg_chat_id, from_id, at, h) DO UPDATE SET main_pk=coalesce(fo_meet_seen.main_pk, EXCLUDED.main_pk) "
            "RETURNING by, verdict, (xmax = 0) AS fresh", *key, src or "main", pk)
        if _fo_hl.md5(str(key).encode()).digest()[0] < 3:
            await c.execute("DELETE FROM fo_meet_seen WHERE created_at < now() - interval '7 days'")
    if not row["fresh"]:
        if pk and row["verdict"] == "not_about":
            await _fo_mt_ai_handoff(pk)
        return {"state": "уже разобрано копией другого бота", "by": row["by"]}
    _FO_MT_KEY.set(key)
    soft = bool(getattr(client_id, "soft", False))
    _FO_MT_SOFT.set(soft)
    if soft:        # «мягко» — только первое сообщение после вопроса бота
        async with pool().acquire() as c:
            await c.execute("UPDATE fo_meet SET answered_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                            str(org_id), str(client_id))
    reply = int(msg.get("message_id") or 0) if _fo_mt_ids_ok(msg, src) else None
    return await _fo_meet_answer(org_id, str(client_id), text, reply, pk)


async def _fo_mt_ai_handoff(pk=None):
    """Сообщение не про планёрку — в обычный разбор задач, ровно один раз, по копии бота задач."""
    key = _FO_MT_KEY.get()
    async with pool().acquire() as c:
        if key:
            got = await c.fetchval("UPDATE fo_meet_seen SET verdict='not_about' WHERE tg_chat_id=$1 AND from_id=$2 AND at=$3 "
                                   "AND h=$4 RETURNING main_pk", *key)
            pk = pk or got
        if not pk or not _fo_ai_ready():
            return   # копия бота задач придёт позже и сама увидит «не про планёрку»
        await c.execute("UPDATE fo_chat_msg SET ai_state=NULL, ai_note='не про планёрку — в разбор задач' WHERE id=$1", pk)
    await _fo_ai_process(pk)


async def _fo_mt_on_copy(msg, text):
    """Копия от бота планёрок: историю не пишем (её пишет бот задач), разбираем только планёрки."""
    tg = str((msg.get("chat") or {}).get("id") or "")
    async with pool().acquire() as c:
        link = await c.fetchrow("SELECT ch.org_id, cc.client_id FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id "
                                "WHERE ch.chat_id=$1 AND cc.kind='client' LIMIT 1", tg)
        if not link:
            return None
        cid = await _fo_meet_match(c, link["org_id"], str(link["client_id"]), tg, msg, text, ids_ok=True)
    if cid:
        return await _fo_mt_claim_run(link["org_id"], cid, msg, text, None, "meet")
    return None


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
                await _fo_mt_digest(c)
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
    _nomoney = False
    try:
        async with pool().acquire() as c:
            _nomoney = "money" in (await _fo_money_lims(c, p, await _fo_my_emp(c, p)))
    except Exception:
        _nomoney = False
    for cid in sorted(lv, key=lambda k: lv[k]["rank"]):
        o = _fo_mt_out(cid, rows.get(cid), lv, cid in chats)
        if _nomoney:
            o["amount"] = None                 # 264: сумма платежа — кому деньги закрыты, не отдаём
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
_FO_MT_NOPIN = {}
_FO_MT_FILE = {}
# одна картинка на все сообщения: логотип справа сверху и «Планёрка» (Виталий 29.09 — без статуса и времени)
_FO_MT_KIMG = {k: "plan" for k in ("week", "confirm", "offer", "move", "extra", "cancel", "agreed", "remind")}
_FO_MT_REQ_RX = re.compile(
    _FO_MT_SYN + r"|перенес|перенос|сдвин|отмен|дополнительн|ещ[её]\s+одн|втор(ую|ой|ая)\s+(план|созв|встреч|совещ|звон|кол|зум)|"
    r"другое\s+время|давайте\s+(в|на)\s", re.I)
_FO_MT_SYS2 = (
    "Ты — агент планёрок digital-агентства (кабинеты продавцов Wildberries и OZON). Планёрки с клиентом на неделю "
    "уже согласованы. Клиент пишет в чат. Определи, что он хочет по планёркам.\n"
    "Перед сообщением может быть переписка чата: по ней пойми контекст — клиент отвечает на вопрос бота или сотрудника про время, продолжает разговор. Решаешь по сообщению клиента; сообщения сотрудников агентства — не ответ клиента.\n"
    "Планёрка, совещание, звонок, созвон, кол (call), «проведём зум» (Zoom, Телемост) — это всё одно и то же: планёрка.\n"
    "intent: move — перенести планёрку на другой день или время; cancel — отменить планёрку; extra — нужна ещё одна, "
    "дополнительная планёрка или созвон; confirm — подтверждает, что всё в силе; not_about — сообщение не про планёрки "
    "(задача, вопрос по товару, цене, рекламе, поставке); unclear — про планёрку, но непонятно, что сделать.\n"
    "from_date — какую планёрку переносят или отменяют: дата YYYY-MM-DD из списка, иначе null.\n"
    "date — на какой день нужна: YYYY-MM-DD («завтра», «в пятницу» переведи в дату; день недели — ближайший будущий), иначе null.\n"
    "time — время HH:MM по Москве, иначе null. «До обеда», «после обеда», «ближе к вечеру», «после 15», «какие слоты», "
    "«когда можете» — это не время, time: null.\n"
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


def _fo_mt_cap_item(x, names, host=True):
    t = _fo_mt_m(x["time"])
    end = _fo_mt_hm(t + int(x["minutes"])) if t is not None else ""
    return "📅 %s\n🕛 %s (до %s)%s" % (_fo_mt_dd(x["day"]), x["time"], end,
                                     (" · ведёт %s" % _fo_mt_h(names.get(x["host"], "проджект"))) if host else "")


def _fo_mt_parts(kind, cab, items, names, note=""):
    """Две части: карточка — только планёрка (кабинет, кто ведёт, дата, время); всё остальное — пояснение и вопрос
    бота — следующим сообщением (Виталий 29.09: «в сообщении с датой и временем — ничего кроме этого»)."""
    full = _fo_mt_caption(kind, cab, items, names)
    head, _sep, tail = full.rpartition("\n\n")
    return head, (("%s\n\n%s" % (note, tail)) if note else tail)


def _fo_mt_caption(kind, cab, items, names, note=""):
    # статус — кружок и подпись словами (Виталий 29.09: «цвет кружка — статус, известный только тебе; подпиши»)
    title = {"week": "Планёрки на неделю", "confirm": "Планёрки на неделю", "offer": "Планёрка", "move": "Перенос планёрки",
             "extra": "Дополнительная планёрка", "agreed": "Планёрка назначена", "remind": "Планёрка через час",
             "cancel": "Отмена планёрки", "next": "Следующая планёрка"}[kind]
    head = "⭐️ <b>%s</b>\n%s" % (title, "🟢 Согласовано" if kind in ("agreed", "remind", "next") else "🟡 На согласовании")
    tail = {"week": "Удобно? Ответьте на это сообщение «да» — или напишите, что поменять.\n"
                    "В течение недели планёрку можно перенести или попросить дополнительную — просто напишите здесь.",
            "confirm": "Всё в силе по нашему постоянному времени? Ответьте «да» — или напишите, что поменять.",
            "offer": "Удобно? Ответьте «да» — или напишите, какое время подходит.",
            "move": "Подходит? Ответьте «да» — или напишите другое время.",
            "extra": "Подходит? Ответьте «да» — или напишите другое время.",
            "agreed": "Зафиксировали ✅ {pin}До встречи!", "remind": "До встречи через час!",
            "next": "Следующая — по графику. До встречи!",
            "cancel": "Отменяем? Ответьте «да» — или напишите, что оставить."}[kind]
    # кто ведёт — строкой под названием кабинета (Виталий 29.09); если в разные дни ведут разные — у каждого дня
    hosts = {x["host"] for x in items}
    one = len(hosts) == 1
    who = ("\n· ведёт %s" % _fo_mt_h(names.get(next(iter(hosts)), "проджект"))) if one else ""
    body = "\n\n".join(_fo_mt_cap_item(x, names, host=not one) for x in items) or "—"
    return "%s\n<b>%s</b>%s\n\n%s%s\n\n%s" % (head, _fo_mt_h(cab), who, body, ("\n\n" + note) if note else "", tail)


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
                "ON CONFLICT (tg_chat_id, msg_id) DO NOTHING", org_id, str(client_id), ch["chat_pk"], ch["chat_id"], -mid, strip(txt)[:4000])
        except Exception:
            pass
    await _store(card, info)
    if pin and _fo_time.time() - _FO_MT_NOPIN.get(str(ch["chat_id"]), 0) < 6 * 3600:
        pin = False
        out["pin"] = "не закрепляли: у бота нет права «Закреплять сообщения» (проверено недавно)"
    if pin:
        old = await c.fetchval("SELECT pin_msg_id FROM fo_meet WHERE org_id=$1::uuid AND client_id=$2::uuid AND tg_chat_id=$3",
                               str(org_id), str(client_id), ch["chat_id"])
        if old and int(old) != card:
            await _fo_aio.to_thread(_fo_tg_api_sync, "unpinChatMessage", {"chat_id": ch["chat_id"], "message_id": int(old)}, None, 10)
        pr = await _fo_aio.to_thread(_fo_tg_api_sync, "pinChatMessage",
                                     {"chat_id": ch["chat_id"], "message_id": card, "disable_notification": True}, None, 10)
        out["pinned"] = bool(pr.get("ok"))
        if not pr.get("ok") and "rights" in str(pr.get("description") or ""):
            _FO_MT_NOPIN[str(ch["chat_id"])] = _fo_time.time()
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
            "extra" if re.search(r"дополнительн|ещ[её]\s+одн|втор(ую|ой|ая)\s+(план|созв|встреч|совещ|звон|кол|зум)|"
                                 r"ещ[её]\s+(план|созв|встреч|совещ|звон|кол|зум)", t) else
            "move" if re.search(r"перенес|перенос|сдвин|другое\s+время|давайте\s+(в|на)\s|можно\s+(в|на)\s", t) else
            "unclear" if re.search(_FO_MT_SYN, t) else "not_about",
            "from_date": None, "date": None, "time": rx["time"], "by": "правило"}
    base["from_day"], base["day"] = _fo_mt_daywords(text)
    if not _fo_ai_ready():
        return base
    lst = "\n".join("- %s (%s) %s–%s%s" % (x["day"].isoformat(), _FO_MT_DOWN[x["day"].weekday()][:2], x["time"],
                                          _fo_mt_hm((_fo_mt_m(x["time"]) or 0) + int(x["minutes"])),
                                          " — прошла" if x["day"] in held or x["day"] < now.date() else "") for x in items) or "(нет)"
    usr = "Сегодня: %s, %s, %s (Москва).\nПланёрки клиента:\n%s\nСообщение клиента: «%s»" % (
        now.date().isoformat(), _FO_MT_DOWN[now.weekday()], now.strftime("%H:%M"), lst, str(text or "")[:800])
    if _FO_MT_CTX.get():
        usr = "Переписка в чате перед этим (сверху — раньше):\n%s\n\n%s" % (_FO_MT_CTX.get(), usr)
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

    if _fo_mt_weekoff(text):
        return await _fo_mt_week_off(c, org_id, client_id, r, text, msg_id, test)
    js = await _fo_mt_req_parse(text, items, now, held, org_id)
    it = js.get("intent")
    t_fix = str(text or "").lower().replace("ё", "е")
    part0 = _fo_mt_part(text, _FO_MT_DEF, 30)
    if it != "cancel" and _FO_MT_FIX_RX.search(t_fix) and (part0 or _fo_mt_rx(text)["time"] or re.search(_FO_MT_SYN, t_fix)):
        it, js["intent"], js["fix"] = "move", "move", True       # 244: «ты назначил на 11:00, я просила после обеда»
    if part0 and (part0["name"] in ("after", "before", "span") or js.get("fix")):
        js["time"] = None                                          # «после 15» — окно, а не время; в правке названо старое время
    await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), str(text or "")[:500],
                    _fo_mt_item("сообщение клиента в течение недели", text=str(text or "")[:300], понял=it, by=js.get("by"),
                                окно=(part0 or {}).get("word")))
    if it == "not_about":
        if not test:
            _fo_aio.get_running_loop().create_task(_fo_mt_ai_handoff(pk))
        return {"state": "не про планёрку — агенту задач"}
    if it == "confirm":
        return {"state": "подтвердил, ничего не меняем"}
    if it == "unclear" and _FO_MT_SOFT.get():
        if not test:
            _fo_aio.get_running_loop().create_task(_fo_mt_ai_handoff(pk))
        return {"state": "не ответ боту — агенту задач"}
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
    raw_day = want_day
    t_low = str(text or "").lower().replace("ё", "е")
    wkend = bool(_FO_MT_WKND_RX.search(t_low)) or bool(want_day and want_day.weekday() > 4)
    if _FO_MT_EXTRA_RX.search(t_low) and it == "move" and not _FO_MT_MOVE_RX.search(t_low):
        it = "extra"
    elif _FO_MT_MOVE_RX.search(t_low) and it == "extra" and not _FO_MT_EXTRA_RX.search(t_low):
        it = "move"
    if js.get("day") is not None:
        # день недели из слов клиента надёжнее даты от ИИ; «в пятницу» — ближайшая пятница, если не сказано «следующую»
        near = mon + _fo_dt.timedelta(days=int(js["day"]))
        if near < today:
            near += _fo_dt.timedelta(days=7)
        nextw = bool(re.search(r"следующ\w*\s+недел|через\s+неделю", t_low))
        if nextw and near < mon + _fo_dt.timedelta(days=7):
            near += _fo_dt.timedelta(days=7)
        if not want_day or want_day.weekday() != int(js["day"]) or nextw or \
                (want_day > near and not re.search(r"следующ", t_low)):
            want_day = near
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
        if js.get("fix") and not cand:
            lc = _fo_mt_last_change(r, items)                      # 244: правка — к последней назначенной
            if lc and not past(lc):
                tgt = lc
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
    part = _fo_mt_part(text, st, mins)                             # 244: часть дня и просьба слотов
    ask = bool(_FO_MT_ASK_RX.search(t_low))
    if js.get("fix") and it == "move" and tgt and not want_day:
        day = tgt["day"]
    named = _fo_mt_m(js.get("time")) if js.get("time") else None
    # выходные или время вне 10:00–18:00 — вежливо объясняем и предлагаем будни (Виталий 29.09)
    if wkend or (named is not None and (named < st["from"] or named + mins > st["to"])):
        return await _fo_mt_offhours(c, org_id, client_id, tgt if it == "move" else None, host, mins,
                                     (raw_day if raw_day and raw_day.weekday() > 4 else today) if wkend else day,
                                     named, wkend, msg_id, test, st)
    # перенос или ещё одна? Клиент не сказал сам, а на этой неделе есть планёрка — спрашиваем один раз
    if want_day and js.get("from_day") is None and not _FO_MT_MOVE_RX.search(t_low) and not _FO_MT_EXTRA_RX.search(t_low):
        wmon = _fo_mt_mon(day)
        up = [x for x in items if not past(x) and _fo_mt_mon(x["day"]) == wmon]
        if up:
            base = next((x for x in up if x["day"] == day), up[0])
            to = {"day": day, "time": _fo_mt_hm(pref) if pref is not None else base["time"],
                  "minutes": int(base["minutes"]), "host": base["host"] or host, "kind": "moved"}
            return await _fo_mt_choose(c, org_id, client_id, base, to, msg_id, test, part=part, ask=ask)
    if (part or ask) and named is None:
        return await _fo_mt_propose(c, org_id, client_id, it, tgt if it == "move" else None, day, part, mins, host,
                                    msg_id, test, st, names, cab)
    return await _fo_mt_decide(c, org_id, client_id, it, tgt if it == "move" else None, day, pref, mins, host,
                               msg_id, test, st, names, cab)


async def _fo_mt_pend_send(c, org_id, client_id, pend, kind, cap, msg_id, test, names, cab):
    sent, err = await _fo_mt_card(c, org_id, client_id, kind, cap, reply_to=msg_id, test=test)
    if not sent:
        return {"state": "error", "why": err}
    await c.execute("UPDATE fo_meet SET pend=$3::jsonb, msg_id=$4, tg_chat_id=$5, sent_at=now(), log=log||$6::jsonb, updated_at=now() "
                    "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), _fo_json.dumps(pend),
                    sent["msg_id"], sent["tg"], _fo_mt_item({"move": "предложили перенос", "cancel": "спросили про отмену",
                                                            "extra": "предложили дополнительную"}[kind],
                                                           text=re.sub(r"<[^>]+>", "", "\n\n".join(cap))[:400], test=("да" if test else None)))
    return {"state": "ждём ответа", "pend": pend}


async def _fo_mt_pend_apply(c, org_id, client_id, pend, msg_id, test):
    """Перенос, отмена или дополнительная согласованы: меняем только этот день, задачи ведущему — сразу.
    Если это правка к предложению недели — неделя считается согласованной, график остаётся как предлагали."""
    fid = await _fo_mt_fn(c, org_id)
    cab_id = await c.fetchval("SELECT id FROM cabinet WHERE client_id=$1::uuid ORDER BY name LIMIT 1", str(client_id))
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    names = await _fo_mt_names(c, org_id)
    kind = pend.get("type")
    fr = _fo_mt_unjs(pend.get("from")) if pend.get("from") else None
    to = _fo_mt_unjs(pend.get("to")) if pend.get("to") else None
    r0 = await _fo_mt_row(c, org_id, client_id)
    if r0 and r0["status"] == "proposed":
        await _fo_mt_mark_agreed(c, org_id, client_id, r0, "с правкой клиента на эту неделю")
    async with c.transaction():
        if fr and kind in ("move", "cancel"):
            await _fo_mt_cancel_item(c, org_id, client_id, fr, fid, cab_id, kind)
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
    if to and to["day"] >= mon + _fo_dt.timedelta(days=7) and not any(x["day"] == to["day"] for x in plan):
        plan += [x for x in await _fo_mt_week(c, org_id, client_id, _fo_mt_mon(to["day"]), rr) if x["day"] == to["day"]]
    dm = ""
    if kind == "cancel":
        note = "🔴 Отменили: %s в %s" % (_fo_mt_dd(fr["day"]), fr["time"])
        if _fo_mt_soon(fr["day"]):
            dm = await _fo_mt_notify(c, {0: {"host": fr["host"]}}, "✖ %s: планёрка %s %s отменена клиентом, задача снята." % (
                cab, _fo_mt_dd(fr["day"]), fr["time"]), test)
    else:
        note = ("Перенесли: было %s в %s" % (_fo_mt_dd(fr["day"]), fr["time"])) if fr and kind == "move" else \
            ("Добавили дополнительную: %s в %s" % (_fo_mt_dd(to["day"]), to["time"]))
        if _fo_mt_soon(to["day"]) or (fr and _fo_mt_soon(fr["day"])):
            dm = await _fo_mt_notify(c, {0: {"host": to["host"]}}, "✅ %s: %s — %s в %s (%d мин)%s. Задача у вас в ганте." % (
                cab, "перенос" if kind == "move" else "дополнительная планёрка", _fo_mt_dd(to["day"]), to["time"],
                int(to["minutes"]), (", было %s в %s" % (_fo_mt_dd(fr["day"]), fr["time"])) if fr and kind == "move" else ""), test)
    if plan:
        cap = _fo_mt_parts("agreed", cab, plan, names, note)
    else:
        nxt = (await _fo_mt_week(c, org_id, client_id, mon + _fo_dt.timedelta(days=7), rr))[:1]
        cap = _fo_mt_parts("next", cab, nxt, names, note) if nxt else (note, None)
    sent, err = await _fo_mt_card(c, org_id, client_id, "agreed" if plan else "next", cap, reply_to=msg_id, test=test, pin=True)
    return {"state": "applied", "type": kind, "send": err or "отправлено", "проджекту": dm or "не писали (не ближайшие дни)"}


async def _fo_mt_pend_answer(c, org_id, client_id, r, pend, text, msg_id, pk, test):
    if pend.get("type") == "which":                                # 288: какую планёрку перенести
        tl = str(text or "").lower().replace("ё", "е")
        rx0 = _fo_mt_rx(text)
        opts = [_fo_mt_unjs(x) for x in (pend.get("opts") or [])]
        pick = None
        if rx0["days"]:
            pick = next((o for o in opts if o["day"].weekday() in rx0["days"]), None)
        if not pick:
            m0 = re.search(r"\b(перв|втор|послед)", tl)
            if m0 and opts:
                pick = opts[0] if m0.group(1) == "перв" else opts[-1] if m0.group(1) == "послед" else (opts[1] if len(opts) > 1 else opts[0])
        extra = (not pick) and bool(re.search(r"ещ[её]|дополнит|добав|отдельн|обе|оба|и\s+ту\s+и", tl))
        await c.execute("UPDATE fo_meet SET pend=NULL, answered_at=now(), answer=$3, log=log||$4::jsonb "
                        "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), str(text or "")[:500],
                        _fo_mt_item("ответ клиента", text=str(text or "")[:300],
                                    понял=("перенести " + _fo_mt_dw(pick["day"], "acc")) if pick else ("ещё одну" if extra else "непонятно — разбираем заново")))
        if not pick and not extra:
            r2 = await _fo_mt_row(c, org_id, client_id)
            return await _fo_mt_request(c, org_id, client_id, r2, text, msg_id, pk, test)
        to = _fo_mt_unjs(pend.get("to"))
        st = await _fo_mt_settings(c, org_id)
        names = await _fo_mt_names(c, org_id)
        cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
        mins = int(to["minutes"])
        if extra:
            lv = (await _fo_mt_levels(c, org_id)).get(str(client_id), {"level": 3})
            mins = _FO_MT_LVL[lv["level"]][2]
        if not to.get("time"):
            part = _fo_mt_part((pend.get("part") or {}).get("word") or "", st, mins) if pend.get("part") else None
            return await _fo_mt_propose(c, org_id, client_id, "move" if pick else "extra", pick, to["day"], part,
                                        mins, to["host"], msg_id, test, st, names, cab)
        return await _fo_mt_decide(c, org_id, client_id, "move" if pick else "extra", pick, to["day"], _fo_mt_m(to["time"]),
                                   mins, to["host"], msg_id, test, st, names, cab)
    if pend.get("type") == "choose":
        tl = str(text or "").lower().replace("ё", "е")
        typ = "move" if re.search(r"перен|вместо|сдвин|поменя|передвин", tl) else \
            ("extra" if re.search(r"ещ[её]|дополнит|добав|втор|отдельн|обе|оба|и\s+ту\s+и", tl) else None)
        await c.execute("UPDATE fo_meet SET pend=NULL, answered_at=now(), answer=$3, log=log||$4::jsonb "
                        "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), str(text or "")[:500],
                        _fo_mt_item("ответ клиента", text=str(text or "")[:300],
                                    понял={"move": "перенести", "extra": "ещё одну"}.get(typ, "непонятно — разбираем заново")))
        if not typ:
            r2 = await _fo_mt_row(c, org_id, client_id)
            return await _fo_mt_request(c, org_id, client_id, r2, text, msg_id, pk, test)
        fr, to = _fo_mt_unjs(pend.get("from")), _fo_mt_unjs(pend.get("to"))
        st = await _fo_mt_settings(c, org_id)
        names = await _fo_mt_names(c, org_id)
        cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
        if typ == "extra":
            lv = (await _fo_mt_levels(c, org_id)).get(str(client_id), {"level": 3})
            to["minutes"] = _FO_MT_LVL[lv["level"]][2]
        if pend.get("part") or pend.get("ask"):                    # 244: окно дня → предлагаем слоты, не фиксируем
            part = _fo_mt_part((pend.get("part") or {}).get("word") or "", st, int(to["minutes"])) if pend.get("part") else None
            if pend.get("part") and not part:
                part = dict(pend["part"])
            return await _fo_mt_propose(c, org_id, client_id, typ, fr if typ == "move" else None, to["day"], part,
                                        int(to["minutes"]), to["host"], msg_id, test, st, names, cab)
        return await _fo_mt_decide(c, org_id, client_id, typ, fr if typ == "move" else None, to["day"], _fo_mt_m(to["time"]),
                                   int(to["minutes"]), to["host"], msg_id, test, st, names, cab)
    if pend.get("opts"):                                           # 244: клиент выбирает из предложенных слотов
        pick = _fo_mt_pick(text, list(pend["opts"]))
        rx0 = _fo_mt_rx(text)
        if pick:
            p2 = dict(pend)
            p2["to"] = dict(pend.get("to") or {}, time=pick)
            p2.pop("opts", None)
            await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                            str(org_id), str(client_id), str(text or "")[:500],
                            _fo_mt_item("ответ клиента", text=str(text or "")[:300], понял="выбрал " + pick))
            return await _fo_mt_pend_apply(c, org_id, client_id, p2, msg_id, test)
        if rx0["yes"] and not rx0["time"] and len(pend["opts"]) > 1:
            ts = list(pend["opts"])
            await _fo_mt_send(c, org_id, client_id, "Какое время выбираете: %s?" % (
                " или ".join([", ".join(ts[:-1]), ts[-1]])), reply_to=msg_id, test=test)
            return {"state": "уточняем, какой слот"}
        if rx0["time"] and not rx0["days"] and not rx0["neg"]:        # своё время в тот же день
            to0 = _fo_mt_unjs(pend.get("to"))
            fr0 = _fo_mt_unjs(pend.get("from")) if pend.get("from") else None
            st0 = await _fo_mt_settings(c, org_id)
            names0 = await _fo_mt_names(c, org_id)
            cab0 = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
            await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                            str(org_id), str(client_id), str(text or "")[:500],
                            _fo_mt_item("ответ клиента", text=str(text or "")[:300], понял="своё время " + rx0["time"]))
            t0 = _fo_mt_m(rx0["time"])
            if t0 < st0["from"] or t0 + int(to0["minutes"]) > st0["to"]:
                return await _fo_mt_offhours(c, org_id, client_id, fr0, to0["host"], int(to0["minutes"]), to0["day"], t0, False,
                                             msg_id, test, st0)
            return await _fo_mt_decide(c, org_id, client_id, pend.get("type") or "extra", fr0, to0["day"], t0,
                                       int(to0["minutes"]), to0["host"], msg_id, test, st0, names0, cab0)
    to = _fo_mt_unjs(pend.get("to")) if pend.get("to") else _fo_mt_unjs(pend.get("from"))
    offer = {to["day"].weekday(): {"time": to["time"], "minutes": int(to["minutes"]), "host": to["host"]}}
    js = await _fo_mt_parse(text, offer, org_id)
    kind = js.get("answer")
    await c.execute("UPDATE fo_meet SET answered_at=now(), answer=$3, log=log||$4::jsonb WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), str(text or "")[:500],
                    _fo_mt_item("ответ клиента", text=str(text or "")[:300], понял=kind, by=js.get("by")))
    if kind == "yes":
        return await _fo_mt_pend_apply(c, org_id, client_id, pend, msg_id, test)
    if kind == "not_about" or (_FO_MT_SOFT.get() and kind == "unclear"):
        if not test:
            _fo_aio.get_running_loop().create_task(_fo_mt_ai_handoff(pk))
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


# ── помощники 228 (игра 29.09) ──
def _fo_mt_weekoff(text):
    """«На этой неделе не получится» без дня и времени (с днём или временем — это перенос)."""
    rx = _fo_mt_rx(text)
    return bool(_FO_MT_WEEKOFF_RX.search(str(text or ""))) and not rx["days"] and not rx["time"]


def _fo_mt_soon(day):
    """Сегодня и два ближайших рабочих дня: об изменениях на эти дни сотруднику пишем сразу, остальное — вечерним
    списком (Виталий 29.09: «не о каждом чихе»)."""
    today = _fo_mt_now().date()
    days, d = [today], today
    while len(days) < 3:
        d = _fo_mt_workday(d + _fo_dt.timedelta(days=1))
        days.append(d)
    return day in days


def _fo_mt_dw(day, case="loc"):
    """«в четверг 01.10», «четверг 01.10» (на …), «четверга 01.10» (с …)."""
    w = {"loc": _FO_MT_DOWA, "acc": _FO_MT_DOWACC, "gen": _FO_MT_DOWGEN}[case][day.weekday()]
    return "%s %02d.%02d" % (w, day.day, day.month)


async def _fo_mt_mark_agreed(c, org_id, client_id, r, how):
    """Предложение недели принято (с правкой клиента только на эту неделю): график — как предлагали, статус «назначена»."""
    off = _fo_mt_slots(r["offer"]) or _fo_mt_slots(r["slots"])
    wk, _items = await _fo_mt_weekitems(c, org_id, client_id, off, r)
    await c.execute("UPDATE fo_meet SET slots=$3::jsonb, offer=NULL, status='agreed', agreed_at=now(), attn=NULL, rounds=0, "
                    "week_of=coalesce(week_of, $4), log=log||$5::jsonb, updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid",
                    str(org_id), str(client_id), _fo_json.dumps(_fo_mt_dump(off)), wk, _fo_mt_item("назначена: " + how))


async def _fo_mt_cancel_item(c, org_id, client_id, fr, fid, cab_id, why):
    """Снять одну планёрку: день графика — пропуск и задача снята; перенос или дополнительная — отменены с задачей."""
    if (fr.get("kind") or "regular") == "regular":
        if cab_id and fid:
            await c.execute("INSERT INTO fo_task_skip (org_id, cabinet_id, fn_id, day, client_id, reason) "
                            "VALUES ($1::uuid, $2, $3, $4, $5::uuid, $6) ON CONFLICT DO NOTHING",
                            str(org_id), cab_id, fid, fr["day"], str(client_id), why)
            await c.execute("DELETE FROM task WHERE org_id=$1 AND cabinet_id=$2 AND fn_id=$3 AND plan_date=$4 "
                            "AND source='generator' AND status='planned'", org_id, cab_id, fid, fr["day"])
    elif fr.get("id"):
        tid = await c.fetchval("UPDATE fo_meet_occ SET status='cancelled' WHERE id=$1 RETURNING task_id", int(fr["id"]))
        if tid:
            await c.execute("DELETE FROM task WHERE id=$1 AND status='planned'", tid)


async def _fo_mt_week_off(c, org_id, client_id, r, text, msg_id, test):
    """«На этой неделе не получится»: снимаем оставшиеся планёрки этой недели, клиенту — когда следующая по графику."""
    now = _fo_mt_now()
    today, mnow = now.date(), now.hour * 60 + now.minute
    mon = _fo_mt_mon(today)
    if r["status"] == "proposed":
        await _fo_mt_mark_agreed(c, org_id, client_id, r, "клиент: на этой неделе без планёрки")
    rr = await _fo_mt_row(c, org_id, client_id)
    held = await _fo_mt_heldset(c, org_id, client_id, mon, mon + _fo_dt.timedelta(days=6))
    left = [x for x in await _fo_mt_week(c, org_id, client_id, mon, rr)
            if x["day"] not in held and (x["day"] > today or (x["day"] == today and (_fo_mt_m(x["time"]) or 0) > mnow))]
    fid = await _fo_mt_fn(c, org_id)
    cab_id = await c.fetchval("SELECT id FROM cabinet WHERE client_id=$1::uuid ORDER BY name LIMIT 1", str(client_id))
    async with c.transaction():
        for x in left:
            await _fo_mt_cancel_item(c, org_id, client_id, x, fid, cab_id, "неделя без планёрки")
        await c.execute("UPDATE fo_meet SET pend=NULL, answered_at=now(), answer=$3, log=log||$4::jsonb, updated_at=now() "
                        "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id), str(text or "")[:500],
                        _fo_mt_item("на этой неделе без планёрки", text=str(text or "")[:300],
                                    снято=["%s %s" % (x["day"].isoformat(), x["time"]) for x in left] or None))
    names = await _fo_mt_names(c, org_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    nxt = (await _fo_mt_week(c, org_id, client_id, mon + _fo_dt.timedelta(days=7), rr))[:1]
    note = "Хорошо, на этой неделе без планёрки." + (
        ("\n🔴 Отменили: " + "; ".join("%s в %s" % (_fo_mt_dd(x["day"]), x["time"]) for x in left)) if left else "")
    if nxt:
        sent, err = await _fo_mt_card(c, org_id, client_id, "next", _fo_mt_parts("next", cab, nxt, names, note),
                                      reply_to=msg_id, test=test)
    else:
        sent, err = await _fo_mt_send(c, org_id, client_id, note + "\nКогда будет удобно встретиться — напишите здесь.",
                                      reply_to=msg_id, test=test)
    dm = []
    for x in left:
        if _fo_mt_soon(x["day"]):
            dm.append(await _fo_mt_dm(c, x["host"], "✖ %s: планёрка %s %s отменена — клиент: на этой неделе без планёрки. "
                                                     "Задача снята." % (cab, _fo_mt_dd(x["day"]), x["time"]), test))
    return {"state": "на этой неделе без планёрки", "снято": len(left), "send": err or "отправлено",
            "проджекту": "; ".join(sorted(set(dm))) or "не писали"}


async def _fo_mt_offhours(c, org_id, client_id, tgt, host, mins, day, t, wkend, msg_id, test, st, proposed=False):
    """Выходные или время вне рабочего: вежливо объясняем (пн–пт, с 10:00 до 18:00) и предлагаем ближайшее — последний
    рабочий день перед выходными и первый после них, или этот же день в рабочее время (Виталий 29.09)."""
    now = _fo_mt_now()
    today, mnow = now.date(), now.hour * 60 + now.minute
    skip = (str(client_id), tgt["day"], tgt["time"]) if tgt else None
    if wkend:
        sat = day if day.weekday() == 5 else (day - _fo_dt.timedelta(days=1) if day.weekday() == 6 else
                                              day + _fo_dt.timedelta(days=(5 - day.weekday()) % 7))
        cands = [sat - _fo_dt.timedelta(days=1), sat + _fo_dt.timedelta(days=2)]
    else:
        cands = [_fo_mt_workday(day), _fo_mt_workday(_fo_mt_workday(day) + _fo_dt.timedelta(days=1))]
    rr = await _fo_mt_row(c, org_id, client_id)
    opts = []
    for dd in cands:
        if dd < today:
            continue
        own = [x for x in await _fo_mt_week(c, org_id, client_id, _fo_mt_mon(dd), rr) if x["day"] == dd]
        if own:
            opts.append((dd, own[0]["time"], True))
            continue
        busy = await _fo_mt_daybusy(c, org_id, dd, skip)
        pl = [x for x in _fo_mt_place(busy, host, dd.weekday(), t, mins, st, 3) if dd > today or x > mnow + 30]
        if pl:
            opts.append((dd, _fo_mt_hm(pl[0]), False))
    fr_, to_ = _fo_mt_hm(st["from"]), _fo_mt_hm(st["to"])
    head = ("Спасибо! В выходные мы не работаем: планёрки проводим с понедельника по пятницу, с %s до %s." % (fr_, to_)
            if wkend else "Спасибо! На %s поставить не получится: планёрки проводим в будни с %s до %s." % (
                _fo_mt_hm(t) if t is not None else "это время", fr_, to_))
    if opts:
        body = "Можем провести %s. Как вам удобнее? Или напишите любой будний день и время с %s до %s." % (
            " или ".join("%s в %s%s" % (_fo_mt_dw(dd), tm, " — по графику" if own else "") for dd, tm, own in opts), fr_, to_)
    else:
        body = "Напишите, пожалуйста, будний день и время с %s до %s — подберём." % (fr_, to_)
    sent, err = await _fo_mt_send(c, org_id, client_id, head + "\n" + body, reply_to=msg_id, test=test)
    await c.execute("UPDATE fo_meet SET answered_at=now(), msg_id=coalesce($3, msg_id), sent_at=CASE WHEN $3::bigint IS NULL "
                    "THEN sent_at ELSE now() END, rounds=coalesce(rounds,0)+$4, log=log||$5::jsonb, updated_at=now() "
                    "WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id),
                    (sent or {}).get("msg_id"), 1 if proposed else 0,
                    _fo_mt_item("выходные / нерабочее время — предложили будни", text=(head + " " + body)[:400], send=err or None))
    return {"state": "нерабочее время — предложили будни", "варианты": ["%s %s" % (dd.isoformat(), tm) for dd, tm, _o in opts]}


async def _fo_mt_choose(c, org_id, client_id, base, to, msg_id, test, part=None, ask=False):
    """Клиент назвал день и время, но не сказал, перенос это или ещё одна планёрка — спрашиваем один раз."""
    same = base["day"] == to["day"]
    when = ("на время %s" % part["word"]) if part else ("на %s" % to["time"])
    when2 = part["word"] if part else ("в %s" % to["time"])
    txt = ("Уточните, пожалуйста: %s — или нужна ещё одна, дополнительная? Ответьте «перенести» или «ещё одну»." % (
        ("перенести планёрку %s с %s %s" % (_fo_mt_dw(base["day"]), base["time"], when)) if same else
        ("перенести планёрку с %s (%s) на %s %s" % (_fo_mt_dw(base["day"], "gen"), base["time"], _fo_mt_dw(to["day"], "acc"), when2))))
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=msg_id, test=test)
    pend = {"type": "choose", "from": _fo_mt_js(base), "to": _fo_mt_js(to), "rounds": 0, "part": part, "ask": bool(ask)}
    await c.execute("UPDATE fo_meet SET pend=$3::jsonb, msg_id=coalesce($4, msg_id), sent_at=now(), log=log||$5::jsonb, "
                    "updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id),
                    _fo_json.dumps(pend), (sent or {}).get("msg_id"), _fo_mt_item("спросили: перенос или ещё одна", text=txt))
    return {"state": "спросили: перенос или ещё одна", "send": err or "отправлено"}


async def _fo_mt_propose(c, org_id, client_id, it, tgt, day, part, mins, host, msg_id, test, st, names, cab):
    """«После обеда», «до обеда», «ближе к вечеру», «какие слоты?» — предлагаем 2–3 свободных варианта в этом окне
    и ждём выбора; точного времени клиент не называл, сами не фиксируем (Виталий 30.09: «должна быть коммуникация
    предложения слотов»). Если в этот день окна нет — ближайший рабочий день с тем же окном."""
    if not host:
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "нет ведущего в графике")
    now = _fo_mt_now()
    today, mnow = now.date(), now.hour * 60 + now.minute
    skip = (str(client_id), tgt["day"], tgt["time"]) if (it == "move" and tgt) else None
    lo = part["lo"] if part else st["from"]
    hi = part["hi"] if part else st["to"] - mins
    word = part["word"] if part else ""
    opts, dd = [], day
    for k in range(5):
        dd = day if k == 0 else _fo_mt_workday(dd + _fo_dt.timedelta(days=1))
        if dd < today:
            continue
        busy = await _fo_mt_daybusy(c, org_id, dd, skip)
        opts = _fo_mt_range_slots(busy, host, dd.weekday(), lo, hi, mins, st, 3, after=(mnow + 30) if dd == today else None)
        if opts:
            break
    if not opts:
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "нет окна %s у ведущего" % (word or "в этот день"))
    times = [_fo_mt_hm(t) for t in opts]
    lst = (" или ".join([", ".join(times[:-1]), times[-1]]) if len(times) > 1 else times[0])
    head = "%s%s: могу предложить %s — планёрка %d минут." % (_fo_mt_dw(dd).capitalize(), (" " + word) if word else "", lst, mins)
    if dd != day:
        head = "%s%s свободных окон у ведущего нет. %s" % (_fo_mt_dw(day).capitalize(), (" " + word) if word else "", head)
    if it == "move" and tgt:
        head = "Хорошо, перенесём планёрку %s %s. %s" % (_fo_mt_dw(tgt["day"], "gen"), tgt["time"], head)
    txt = head + "\nКакое время удобно? Можно назвать и другое — подберём."
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=msg_id, test=test)
    to = {"day": dd, "time": times[0], "minutes": mins, "host": host, "kind": "moved" if it == "move" else "extra"}
    pend = {"type": it, "from": _fo_mt_js(tgt) if (it == "move" and tgt) else None, "to": _fo_mt_js(to), "opts": times, "rounds": 0}
    await c.execute("UPDATE fo_meet SET pend=$3::jsonb, msg_id=coalesce($4, msg_id), sent_at=now(), log=log||$5::jsonb, "
                    "updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id),
                    _fo_json.dumps(pend), (sent or {}).get("msg_id"), _fo_mt_item("предложили слоты", text=txt[:300], варианты=times))
    return {"state": "предложили слоты", "варианты": times, "send": err or "отправлено"}


async def _fo_mt_decide(c, org_id, client_id, it, tgt, day, pref, mins, host, msg_id, test, st, names, cab):
    """Клиент назвал время: свободно и встаёт в блок ведущего — ставим сразу (Виталий 29.09: «сразу назначает»);
    иначе — ближайшее окно рядом с другими планёрками ведущего и вопрос «Подходит?»."""
    if not host:
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "нет ведущего в графике")
    skip = (str(client_id), tgt["day"], tgt["time"]) if (it == "move" and tgt) else None
    busy = await _fo_mt_daybusy(c, org_id, day, skip)
    d = day.weekday()
    ok = pref is not None and _fo_mt_fits(busy, host, d, pref, mins, st) and \
        (not busy.get((host, d)) or _fo_mt_adjacent(busy, host, d, pref, mins, st))
    t = pref if ok else ((_fo_mt_place(busy, host, d, pref, mins, st, 1) or [None])[0])
    if t is None:
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "у ведущего нет окна %s" % _fo_mt_dd(day))
    to = {"day": day, "time": _fo_mt_hm(t), "minutes": mins, "host": host, "kind": "moved" if it == "move" else "extra"}
    pend = {"type": it, "from": _fo_mt_js(tgt) if tgt else None, "to": _fo_mt_js(to), "rounds": 0}
    if ok:
        return await _fo_mt_pend_apply(c, org_id, client_id, pend, msg_id, test)
    note = ("Было: %s в %s" % (_fo_mt_dd(tgt["day"]), tgt["time"])) if (it == "move" and tgt) else ""
    if pref is not None:
        note = (note + "\n" if note else "") + ("На %s поставить не получится: в этот день планёрки у ведущего идут одним блоком "
                                                 "с перерывами — предлагаем ближайшее время." % _fo_mt_hm(pref))
    cap = _fo_mt_parts("move" if it == "move" else "extra", cab, [to], names, note)
    return await _fo_mt_pend_send(c, org_id, client_id, pend, it, cap, msg_id, test, names, cab)


async def _fo_mt_which(c, org_id, client_id, fut, to, msg_id, test, part=None):
    """288: клиент назвал день без планёрки, а планёрок на неделе несколько — какую перенести или нужна ещё одна."""
    when = ("на %s" % _fo_mt_dw(to["day"], "acc")) + ((" в %s" % to["time"]) if to.get("time") else (" %s" % part["word"] if part else ""))
    opts = ["%s в %s" % (_fo_mt_dw(i["day"], "acc"), i["time"]) for i in fut]
    words = [_FO_MT_DOWACC[i["day"].weekday()] for i in fut]
    txt = ("Уточните, пожалуйста: какую планёрку перенести %s — %s? Или нужна ещё одна, дополнительная? "
           "Ответьте днём («%s») или «ещё одну»." % (when, " или ".join(opts), "» / «".join(words)))
    sent, err = await _fo_mt_send(c, org_id, client_id, txt, reply_to=msg_id, test=test)
    pend = {"type": "which", "opts": [_fo_mt_js(i) for i in fut], "to": {"day": to["day"].isoformat(), "time": to.get("time"),
            "minutes": int(to["minutes"]), "host": to["host"]}, "part": part, "rounds": 0}
    await c.execute("UPDATE fo_meet SET pend=$3::jsonb, msg_id=coalesce($4, msg_id), sent_at=now(), log=log||$5::jsonb, "
                    "updated_at=now() WHERE org_id=$1::uuid AND client_id=$2::uuid", str(org_id), str(client_id),
                    _fo_json.dumps(pend), (sent or {}).get("msg_id"), _fo_mt_item("спросили: какую планёрку перенести", text=txt))
    return {"state": "спросили: какую перенести", "send": err or "отправлено"}


async def _fo_mt_prop_other(c, org_id, client_id, r, offer, js, text, msg_id, test):
    """Ответ на предложение недели своим временем: меняем только эту неделю, график остаётся (Виталий 29.09).
    Свободное время — ставим сразу; занятое — ближайшее окно; выходные или вечер — вежливо объясняем."""
    st = await _fo_mt_settings(c, org_id)
    names = await _fo_mt_names(c, org_id)
    cab = await c.fetchval("SELECT name FROM client WHERE id=$1::uuid", str(client_id)) or ""
    today = _fo_mt_now().date()
    wk, items = await _fo_mt_weekitems(c, org_id, client_id, offer, r)
    sl = _fo_mt_norm(js.get("slots"), _fo_mt_rx(text))
    x = sl[0] if sl else {"day": None, "time": None}
    d = x.get("day")
    t = _fo_mt_m(x["time"]) if x.get("time") else None
    named = next((i for i in items if d is not None and i["day"].weekday() == d), None)
    tgt = named or (items[0] if items else None)
    src = tgt or (dict(offer[sorted(offer)[0]]) if offer else None)
    if not src or not src.get("host"):
        return await _fo_mt_handoff(c, org_id, client_id, msg_id, test, "клиент просит: «%s», а ведущего нет" % str(text)[:100])
    host, mins = src["host"], int(src["minutes"])
    wkend = bool(_FO_MT_WKND_RX.search(str(text or "")))
    if d is not None:
        day = wk + _fo_dt.timedelta(days=int(d))
        if day < today:
            day += _fo_dt.timedelta(days=7)
    else:
        day = tgt["day"] if tgt else _fo_mt_workday(today + _fo_dt.timedelta(days=1))
    part = _fo_mt_part(text, st, mins)                             # 244
    if part and part["name"] in ("after", "before", "span"):
        t = None
    if wkend or (t is not None and (t < st["from"] or t + mins > st["to"])):
        return await _fo_mt_offhours(c, org_id, client_id, tgt, host, mins, day, t, wkend, msg_id, test, st, proposed=True)
    _nw = _fo_mt_now(); _nm = _nw.hour * 60 + _nw.minute
    fut = [i for i in items if i["day"] > today or (i["day"] == today and (_fo_mt_m(i["time"]) or 0) > _nm)]
    if d is not None and named is None and len(fut) >= 2:          # 288: не выбираем сами — переспрашиваем
        return await _fo_mt_which(c, org_id, client_id, fut,
                                  {"day": day, "time": _fo_mt_hm(t) if t is not None else None, "minutes": mins, "host": host},
                                  msg_id, test, part)
    if t is None and (part or _FO_MT_ASK_RX.search(str(text or ""))):
        return await _fo_mt_propose(c, org_id, client_id, "move" if tgt else "extra", tgt, day, part, mins, host,
                                    msg_id, test, st, names, cab)
    if tgt and day == tgt["day"] and (t is None or t == _fo_mt_m(tgt["time"])):
        return await _fo_mt_agree(c, org_id, client_id, offer, reply_to=msg_id, test=test)
    if t is None:
        t = _fo_mt_m(tgt["time"]) if tgt else _fo_mt_m(src.get("time"))
    return await _fo_mt_decide(c, org_id, client_id, "move" if tgt else "extra", tgt, day, t, mins, host,
                               msg_id, test, st, names, cab)


_FO_MT_DWS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _fo_mt_stat(r, x, mon):
    """Статус планёрки словами — для списков сотрудникам и собственнику."""
    if x["kind"] != "regular" or (r["status"] == "agreed" and r["week_of"] == mon):
        return "🟢 согласовано"
    if r["status"] == "proposed" and r["week_of"] == mon:
        return "🟡 на согласовании"
    return "🔴 не согласовано"


async def _fo_mt_digest(c, dry_org=None):
    """По итогам дня (будни, 18:00) — график планёрок с завтра до конца рабочей недели (не меньше двух рабочих дней,
    в пятницу — вся следующая неделя): собственнику — весь, ведущим — только их планёрки (Виталий 29.09)."""
    now = _fo_mt_now()
    m = now.hour * 60 + now.minute
    if dry_org is None and (now.weekday() > 4 or not (18 * 60 <= m < 19 * 60)):
        return 0
    today = now.date()
    if today.weekday() > 4:
        today -= _fo_dt.timedelta(days=today.weekday() - 4)
    dry = {}
    if today.weekday() == 4:
        days = [today + _fo_dt.timedelta(days=3 + i) for i in range(5)]
    else:
        days = [today + _fo_dt.timedelta(days=i) for i in range(1, 5 - today.weekday())]
        if len(days) < 2:
            days.append(_fo_mt_workday(days[-1] + _fo_dt.timedelta(days=1)))
    per_host, per_org, names = {}, {}, {}
    for r in await c.fetch("SELECT * FROM fo_meet WHERE status<>'off'"):
        if dry_org is not None and str(r["org_id"]) != str(dry_org):
            continue
        cab = None
        for mon in sorted({_fo_mt_mon(d) for d in days}):
            for x in await _fo_mt_week(c, r["org_id"], r["client_id"], mon, r):
                if x["day"] not in days or not x["host"]:
                    continue
                if cab is None:
                    cab = await c.fetchval("SELECT name FROM client WHERE id=$1", r["client_id"]) or ""
                rec = (x["day"], _fo_mt_m(x["time"]) or 0, x["time"], int(x["minutes"]), cab, _fo_mt_stat(r, x, mon), x["host"])
                per_host.setdefault((r["org_id"], x["host"]), []).append(rec)
                per_org.setdefault(r["org_id"], []).append(rec)
    span = "%s %02d.%02d — %s %02d.%02d" % (_FO_MT_DWS[days[0].weekday()], days[0].day, days[0].month,
                                          _FO_MT_DWS[days[-1].weekday()], days[-1].day, days[-1].month)
    k = "digest " + today.isoformat()

    def line(y):
        return "%s–%s · %s · %s" % (y[2], _fo_mt_hm(y[1] + y[3]), y[4], y[5])

    def dayhead(day):
        return "%s, %02d.%02d" % (_FO_MT_DOWN[day.weekday()].capitalize(), day.day, day.month)

    async def send(org, emp, text):
        if dry_org is not None:
            dry[str(emp)] = text
            return False
        if await c.fetchval("SELECT 1 FROM fo_meet_rem WHERE org_id=$1 AND client_id=$2::uuid AND k=$3", org, emp, k):
            return False
        ok = True
        for part in [text[i:i + 3800] for i in range(0, len(text), 3800)]:
            ok = (await _fo_mt_dm(c, emp, part)) == "проджект уведомлён" and ok
        if ok:
            await c.execute("INSERT INTO fo_meet_rem (org_id, client_id, k) VALUES ($1, $2::uuid, $3) ON CONFLICT DO NOTHING",
                            org, emp, k)
        return ok

    n = 0
    for (org, host), lst in per_host.items():
        lines = ["🗓 Ваши планёрки: " + span]
        for day in days:
            its = sorted(y for y in lst if y[0] == day)
            if its:
                lines += ["", dayhead(day)] + [line(y) for y in its]
        n += bool(await send(org, host, "\n".join(lines)))
    for org, lst in per_org.items():
        if org not in names:
            names[org] = await _fo_mt_names(c, org)
        owners = await c.fetch("SELECT e.id FROM employee e JOIN app_user u ON u.id=e.user_id "
                               "WHERE e.org_id=$1 AND u.role_code='owner'", org)
        if not owners:
            continue
        lines = ["🗓 График планёрок: " + span]
        for day in days:
            its = [y for y in lst if y[0] == day]
            if not its:
                continue
            lines += ["", dayhead(day)]
            for h in sorted({y[6] for y in its}, key=lambda h: names[org].get(h, "")):
                lines.append("👤 " + names[org].get(h, "ведущий"))
                lines += [line(y) for y in sorted(y for y in its if y[6] == h)]
        for o in owners:
            n += bool(await send(org, str(o["id"]), "\n".join(lines)))
    return dry if dry_org is not None else n


@router.get("/meet/digest")
async def fo_meet_digest(p: Principal = Depends(max_level(2))):
    """Посмотреть, что бот пришлёт вечером: собственнику — весь график, ведущим — их планёрки (ничего не отправляет)."""
    async with pool().acquire() as c:
        dry = await _fo_mt_digest(c, dry_org=p.org_id)
        names = await _fo_mt_names(c, p.org_id)
        owners = {str(r["id"]) for r in await c.fetch("SELECT e.id FROM employee e JOIN app_user u ON u.id=e.user_id "
                                                      "WHERE e.org_id=$1 AND u.role_code='owner'", p.org_id)}
    return {"собственнику": {names.get(k, k): v for k, v in dry.items() if k in owners},
            "ведущим": {names.get(k, k): v for k, v in dry.items() if k not in owners},
            "нет_карточки_собственника": not owners}


async def _fo_ai_on_edit(msg):
    """Сообщение исправили: в истории — новый текст; если ИИ уже нашёл по нему задачу и она ещё ждёт согласования —
    разбираем заново по исправленному тексту (Виталий 29.09: задача записалась с опечаткой «по ,h.rfv»)."""
    try:
        chat = msg.get("chat") or {}
        tg, mid = str(chat.get("id") or ""), int(msg.get("message_id") or 0)
        text = str(msg.get("text") or msg.get("caption") or "").strip()
        if not tg or not mid or (msg.get("from") or {}).get("is_bot"):
            return
        async with pool().acquire() as c:
            row = await c.fetchrow("SELECT id, ai_state, text FROM fo_chat_msg WHERE tg_chat_id=$1 AND msg_id=$2", tg, mid)
            if not row or (row["text"] or "") == text:
                return
            await c.execute("UPDATE fo_chat_msg SET text=$2 WHERE id=$1", row["id"], text[:4000])
            if await c.fetchval("SELECT 1 FROM fo_ai_task WHERE msg_pk=$1 AND status<>'pending' LIMIT 1", row["id"]):
                return          # задачу уже приняли или отклонили — правка сообщения её не меняет
            had = await c.fetchval("UPDATE fo_ai_task SET status='replaced', decided_at=now(), "
                                   "decision_note='сообщение исправлено — разобрано заново' "
                                   "WHERE msg_pk=$1 AND status='pending' RETURNING 1", row["id"])
            if not had and row["ai_state"] not in ("task", "clarify", "no_task"):
                return          # планёрка, сообщение бота, шум — не трогаем
            if not _fo_ai_ready():
                return
            await c.execute("UPDATE fo_chat_msg SET ai_state=NULL, ai_note='исправлено — разбираем заново' WHERE id=$1", row["id"])
        await _fo_ai_process(row["id"])
    except Exception as e:
        try:
            print("fo_ai_on_edit:", e)
        except Exception:
            pass


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
p("== КАРТИНКИ ФУНКЦИЙ ==")
_FI_ASSETS = {"bg.jpg": "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",
              "title.ttf": "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BRUAcwUVAHME9ABIBPQASAT0AEgE9ABIBPQASAT0AEgE9ABIBPQASAUaAHMFGgBzBRoASANcAHMElgBBBJYAQQVlAHQDDgAUBRUAcwUVAHMFKgBzBRUAcwUVAHMFFQBzBOwAFgbnAA8EwQAhBMEAIQTyABYE8gAWBPIAFgTyABYE8gAWBKYAdQV2AHMF/QB0BS0AdAcbAEII5wAxBUEAWAXoAHQGAQBCBdUAdAXFAC8GtQBSBkoAdAWvAHMHMQBCCAMAdAhHAHQGsABCB3cAdAVYAHQI9ABCCQUAdAXzAEwIbwB0BUwAIwXzAFIG7ABCBNkASATxAEgEpwBzA60AcwV6ACMHFwAhBDwAQgUVAHMEzQBzBO0AFAaiAHMFFQBzBP0AcwQ6ABQGnQBIBXAAcwT9AHME4wBzBwAAcwdEAHME0gBzBYoAFAauAHMHnQAiB30AcwTDAEYHBABzBLMAGgTDAEgFSABIBMMASAShAB4FMwBXBhEAZAWJAFIDiABbBRoAWwVBAFgFggBdBTcAdQVLAFIEtABCBVAAUgVLAFIFKgBIBSoAngUqAGYFKgBDBSoAKwUqAF0FKgBBBSoAfQUqAD8FKgBBAiYAJAImAFcCJgBXAiYAVwImACQDIACEAyAAWwMgAAcDIABaAyAAuAMgAFoDIACEAyAAWwMgAAcDIABaAyAAuAMgAFoFKgE9BSoBPQUqAIgFKgCIBSoAkAUqAIgFKgBxBSoAiwUqAIgFKgBnBSoA8wUqAIgFKgCIBSoAkAUqAIgFKgBxBSoAiwUqAIgFKgBnBSoAigImAAACJgAABXcASALeAKwC3gCsBKIATQSiAF4DDwCWAw8ANwMPAKQDDwBdA+QAiwPkAF0ISgBSAw8AlgMPADcDDwCkAw8AXQPkAIsD5ABdCEoAUgU+ABEGNgCNAzMAFAMaAOUC7wDdAzMAFAPFAIsEAAAABSoAPAgAAAAIAAAAA4EAgAOBANQDxQCLBAAAAAUqADwIAAAAA4EAgAOBANQCpgCoAqYAqALWAMcEsQDHBKUAqASOAKgEXgB4AnYAeAKmAFQEjgBUAl0AewS4AHsHFAB7Al0AewS4AHsHFAB7AtIAdALSAKwIdwCsBaQArALSAKwC0gCsAuEAdALSAKwDmgBVA5oASAWIAFUFiABIBXwAowV8AMAFfAC5BXwAsgV8AJsFfAC1BXwAsQV8AJEFfACjBXwAwAV8ALkFfACyBXwAmwV8ALUFfACxBXwAkQV8ANQD4AAABPYAswT2ALMD8gBABKkAswV6ALIFTABgB1AAqAOwAG0D+wCxA/UAkwTHAEIE1wBwAsMAdAO9AFsD3ABdAb/+cAI1AFMC/AA7Ax4AQAM4AEYHKQBTBugAUwd7AEAIPACoC0sAqA5aAKgDDwCqAw8ApQUVAQYDYwCLAzoBDQAAAKoAAAClAAAAiwAAAI4BwAAAAcAAAAjZAHQHogDKCroAyhV0AMoKugDKB6IBAAq6AQAVdAEAB6IBAAq6AQAGSQD6BkkA4QZJAOEGSQD6CroAyg4AAMoKugDKDgAAygd5AMoHeQDKBvAAygeiAMoKugDKFXQAygq6AMoHogEACroBABV0AQAHogEACroBAAq6AMoOAADKCroAyg4AAMoGSQDhBkkA4QZJAPoGSQD6Bw4AvgYpABQErAB0BKwAdAXoAHQF/QB0BTcAdAXzAFIFagBCBcUALwYXADEDrQBzBRUAcwUVAHMEzQBzBLEAgQLSAKwC0gCsBM4A5QPxALkD8QC5A+MAGQAAAQYAAACFAAAANQAAAFsAAAB6AAABDQAAAHoE/QBzBG8AQALeAKwGogBzBDoAFAXVAHQD8wCDA+IAMgUOACACIgAyAmMAgATzAFIAAQAAB8D+EgAAFXT5ivVjFKoAAQAAAAAAAAAAAAAAAAAAAdEABAVkAyAABQAABTMEzQAAAJoFMwTNAAACzQDSAp8AAAIACQMAAAACAASAAAIDAACAKgAAAAAAAAAAUlNNUwDAACAnEwfA/hIAAAfAAe4AAAAFAAAAAAReBdIAAAAgAAgAAAACAAAAAwAAABQAAwABAAAAFAAEAvoAAAAaABAAAwAKAC8AOQB+AKwA/wRfICcgOiC9IRYhmScT//8AAAAgADAAOgCgAK4EACAQIDAgvSEWIZAnE///AAAAngAAAAAAAAAAAAAAAOAQ4GwAANqVAAEAGgAAADYAvgDWAXgCNgJkAAAAAAJ0AAAAAAGAAQoBMgEcAMkBdAEJATEBDgEPAWABTgE/ASIBQAEeAUMBRQFLAU0BTAEMARQAAQAKAAwADgAPABcAGAAZABsAIgAkACUAJgAoAC0ANQA2ADcAOAA6ADsAQABBAEIAQwBFARABIQERAV8BXAF4AEYATwBRAFQAVQBdAF4AXwBiAGsAbQBuAG8AcAByAHoAfAB9AH4AgQCCAIgAiQCKAIwAkQESAR8BEwFSAYEBCwDKAMwBHQDLASABaAF5AWMBZQFJAVsBYgF6AWQBUQFqAWsBdwCEAWcBRgF7AWkBZgFKAXIBcQFzAQ0ABAAFAAYAAwACAAcACQANABAAEQASABMAHQAeAB8AHAGpACkAMQAyADMALwAuAU8AMAA8AD0APgA/AEQAkgCAAEoARwBIAEwASQBLAE4AUgBXAFgAWQBWAGUAZgBnAGQArABxAHYAdwB4AHQAcwFQAHUAhQCGAIcAgwCOAFAAjQAVABYAqwGrAKoAOQAgACEAIwClAKYAnwGsACsBsQCaAAgAlAALAaoAlQAUAJYAlwAqACwAmACZACcAGgA0Aa0BrgGvAbAAmwCcAbIAnQCeAKAAoQCiAKMApACnAKgAqQBNAK0ArgCvALAAWgCxALIAswG0ALQAtQC2ALcAeQC4AHsAUwC5AI8AugCLALsAvQC+AL8AwQDCAMAAxQDGAMcAWwBcAGEBswDIAH8AaQBqAGwAwwDEAGABtgG1AJAAvAG7AbwBJAEjASUBJgG6Ab0BLwEwATYBNwEzATQBNQE4AV0BXgEnASgBuQFCAUEBuAF1AXYBOQE6ATsBPAE9AT4BtwFHAUgBgwGUAYcBlQGQAZYBjAGNAY4BjwAAsAAsILAAVVhFWSAgS7gADlFLsAZTWliwNBuwKFlgZiCKVViwAiVhuQgACABjYyNiGyEhsABZsABDI0SyAAEAQ2BCLbABLLAgYGYtsAIsIyEjIS2wAywgZLMDFBUAQkOwE0MgYGBCsQIUQ0KxJQNDsAJDVHggsAwjsAJDQ2FksARQeLICAgJDYEKwIWUcIbACQ0OyDhUBQhwgsAJDI0KyEwETQ2BCI7AAUFhlWbIWAQJDYEItsAQssAMrsBVDWCMhIyGwFkNDI7AAUFhlWRsgZCCwwFCwBCZasigBDUNFY0WwBkVYIbADJVlSW1ghIyEbilggsFBQWCGwQFkbILA4UFghsDhZWSCxAQ1DRWNFYWSwKFBYIbEBDUNFY0UgsDBQWCGwMFkbILDAUFggZiCKimEgsApQWGAbILAgUFghsApgGyCwNlBYIbA2YBtgWVlZG7ACJbAMQ2OwAFJYsABLsApQWCGwDEMbS7AeUFghsB5LYbgQ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CyADMAMwCo4DCgsgCyALIAsgCyALIAsgCoAKgAqACoAKgAqACoAKgAqcCoAKsAMwAzADMAMwAzADNgNYCu4EjASMA2YLIANwA4ADdgOACxYLIAfgB+AH4AsMA5IFAATyBPIDnATyBPIE8gOyCkYDsgOyA7IDsgOyA8AEyAQuCo4LIAsgBIwEsgTICyALIATICyAKgAqqCwwEzgsWBNQE8gUABQYFBgUGBQYFDAUmBY4LIAU8BVoFdAWOCnIKcgpACnIKcgpABZQGAgqACyAGNApyCkAKQApyCkAGigamCkYKRgaKBqYGmAaYBqYGzAbMBuYHAAcABwYHQAdGB0AHRgdQCnIHygpyCnIKcgpACnIKcgfgB/YKVgpWCkwKTApACkYKgApMClYKVgsgClwKcgpyCnIKcgpyCnIKgAqwCrAKjgsgCpwKqgqwCu4LDAsWCyAAAQC6AAEAAgADAAQABQAGAAcACAAMAA0ADgAXABkAGgAbAB0AHgAgACIAIwAkACUAJgAnACgAKQAqACsALAAtAC4ALwAwADEAMgAzADQANQA2ADoAOwA8AD0APgA/AEAAQQBCAEMARABFAFQAXQBkAGcAagBtAG4AcQBzAHQAfQCAAIEAggCDAIQAhQCGAIcAiACJAIwAjQCOAI8AkACSAJUAlgCYAJkAmgCbAJwAnQCeAKAAoQCjAKcAqACvALAAtAC5ALwAvwDAAMEAwwDEAMsAzQDOAM8A0wDUANUA1wD0AQEBAgEDAQUBBgEJAQsBFAEfASEBIgEnASgBKQEtAS8BMAExATIBMwE0ATUBNgE7AT8BQAFBAUMBRQFGAUcBSAFJAUoBTAFOAU8BUAFSAVYBVwFYAVoBWwFcAV0BXgFfAWABYQFiAWMBZAFlAWYBZwF0AYMBhAGFAZcBmAGZAakBqgGrAawBrQGuAa8BsAGyAbMBtgHHAAEBS/+SAAMBQP+7AUH/UgFc/7sACQEi/5gBN/+jATj/owE7/3UBRv+AAVL/rwFb/vUBYP+vAWT/owABAVz/mAAIAEn/rwB0/6MBCf+YART/uwFG/68BS/9pAVv/gAFc/14AAwEJ/5gBRv+7AUv/aQACAUb/uwFL/4AAAQFc/+MAAgBkAEUAagBFAAQAKgCXAGUARQBnAEUBggCXAAIBL/91ATP/dQAFAS//mAEz/5gBS/+vAVv/uwFc/7sAAwFB/2kBS/+7AVz/XgAbAAH/rwAC/68AA/+vAAT/rwAF/68ABv+vAAf/rwAI/68ACf+vACL/rwAj/68AOv+MAED/mABF/68Am/+YAJ//jACi/4wAq/+MASH/mAEv/4wBM/+MATX/AAE2/wABP/8vAUD/LwFB/y8BsP+MABcAnP+YAJ7/uwC5/4AA9P+EAQH/hAED/4QBBf+EASL/hAEp/4QBRv+EAUf/mAFJ/5gBS/+YAU7/hAFQ/4QBUv+EAVb/hAFY/4QBWv+EAVv/hAGH/4QBiP+EAYn/hAAJAEn/lABM/3oAZv+wAQn/gAFB/zsBRv+YAUv/LwFP/6MBW/+YAAUAlv+YAKL/uwE1/5gBNv+YAVz/rwABAVwAgAABAVwAXQAHATX/aQE2/2kBP/9+AUD/fgFB/34BS/+vAVv/uwADAUv/rwFb/7sBXP+7AAEBS//GAAEAwf9bAAYAYgBFAGUARQBmAEUAZwBFAGkARQDCAEUABQEe/68BP/91AUD/dQFB/3UBXP+YAAcBP//UAUD/1AFB/9QBX//xAWD/8QFi//UBZP/xAAYBNf+jATb/owE//8YBQP/GAUH/xgFc/6MABgDT/+wA1//sAQn/owEc/4wBS/9GAVz+uwABAVz/owAbADr/jABA/4AAQf+vAEP/aQBE/2kAiP+7AIn/uwCM/7sAjf+7AI7/uwCP/7sAkP+7AJv/gACf/4wAov+MAKv/jAEh/4ABL/9GATH/uwEy/7sBM/9GAV3/rwFe/68BYv/SAWX/rwFm/68BsP+MAAwAOv91AED/uwBD/3UARP91AJv/uwCf/3UAov91AKv/dQEh/7sBL/+7ATP/uwGw/3UAFQA6/68AQP+cAEH/igCI/5gAjP+YAI3/mACO/5gAj/+YAJD/mACb/5wAn/+vAKL/rwCr/68BIf+cAS//qQEw/4wBM/+pATT/jAE7/4wBS/+SAbD/rwADAJX/mACw/4wBCf+AAAMAnv+AAKL/mAC5/5gACQCE/6MAlf+vALD/jADH/7sBCf91ARz/AAFL/zsBUv+jAVz/rwAGANP/+QDX/+EBCv/dATf+6QE4/ukBgP+oAAYA0//5ANf/4QEK/90BN/7pATj+jAGA/6gAAQCi/5gADgA6/14AQP+vAEL/owBD/5gARP+YAJb/owCX/+cAm/+vAJ//XgCi/14Aq/9e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AAAAAAAAAAD/gAAAAAAAAAAAAAD/gAAAAAAAAAAAAAD/gAAAAAAAAAAA/zsAAAAAAAAAAP/TAAAAAP9eAAAAAAAAAAAAAP/pAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/0IAAAAAAAD+rwAAAAAAAAAAAAAAAP+jAAAAAAAAAAAAAP+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/bgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9j/MQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7pAAAAAAAA/zsAAAAAAAAAAAAAAAD/uwAAAAAAAAAAAAD/owAAAAAAAAAAAAAAAAAAAAAANAAAAAAAAAAAAAAANP/6ADQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/uwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACYAAAAAAAAAAAAAAAD/uwAAAAAAAAAA/7IAAAAAAAD/vgAAAAAAAAAAAAAAAAAA/8EAAAAA/5gAAAAAAAAAAAAA/6MAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/uwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP+qAAAAAAAAAAAAAAAA/6H/owAAAAD/9QAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/uwAAAAAAAAAAAAAAAP+Y/4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP+7AAAAAAAAAAD/uwAA/vX/RgAAAAAAAAAA/68AAAAAAAD/gP+7AAD/uwAA/7v/jAAAAAAAAAAAAAAAAAAAAAAAAAAA/1IAAP+7/6MAAAAAAAAAAAAAAAAAAAAA/68AAAAAAAD/mAAA/7sAAP+YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/dQAAAAAAAAAAAAAAAAAAAAAAAP7xAAAAAAAAAAAAAP8mAAAAAAAAAAAAAAAAAAAAAP+7AAD/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/xgAA//X/bwAA/+kAAAAAAAD/6QAA/+8AAAAAAAAAAP/yAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/28AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/mwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/6MAAAAA/7sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/owAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/mP+YAAD/IwAA/6MAAAAAAAD/rwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/uwAAAAAAuv8AAAAAAP7e/zsAAAAAAAD/4AAAAAD/H//eAAAAAAAAAAD/if+AAAAAAAAAAAAAAAAAACgAAP/jAAAAAAAAAAAAAAAAAAAAAP/OAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFgAAAAAAAAAAAAAAFgAA/68AAAAAAAD/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAJQABAGIAAABkAGcAYgBpAJEAZgCUAKgAjwCqAKwApACuAK8ApwCxALUAqQC4ALoArgC8AMoAsQDOANIAwADVANcAxQDtAO0AyADvAO8AyQDxAPEAygD0APQAywEAAQYAzAEMARUA0wEXARcA3QEZARkA3gEeAR8A3wEhASIA4QEnASkA4wEtAS0A5gEvATYA5wE7ATsA7wE/AUEA8AFDAUMA8wFFAUoA9AFNAVIA+gFVAVoBAAFdAWcBBgFpAWsBEQGDAYYBFAGXAZoBGAGpAbABHAGyAbYBJAHHAccBKQABAAEBtgAFAAUABQAFAAUABQAFAAUABwARABEAFwAXAAQABwAHAAcABwAHAAcABwAHAC4AGgAAAAAAAAAYAAAAAAAYAAAAGAAIAAgAFQAbAAAAAAAAAAAAAAAAAAAABAAEAAQABAAEAAQABAAEACIABAATABIAEgANAAgACAAIAAgACAAkACMAGQAMAAwAHgACAAIAAgACAAIAAgACAAIAJgABAAEAAQABAAEAAAABAAEAAQABAAEAAQABAAEAHwAcAAIAAgACAAkAAAAlAAkACQAJAAAACQAlAAkACQAWAAAAAgACAAIAAQABAAEAAQABAAEAAQABAAEAAQAcAAoADgAOABEABgADAAMAAwADAAMAAwALACAAIQAhAAsACwALAAsACwAUAAAAAAARADQAGQArABUAAAAAAAwABAA0AAAAAgAAADQAAQAAAAEAAQABAAQAPwAAAEAAAQABAAAADgAKAAAAIQACAAIAFgACAAAAAAACAAoAAQAAAAMAAgACAAYAMAAwAAkAMAAwAAEAAQACAAEAEgABAAAAAAAAADkAAABDACsAOgAAAAAAQQArADkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAALAAAACwAAAAsAAAAAAAPAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA8AHQAPABAADwAdAAAAAAAAAAAAAAA4AD0ANgA3ADYANwA2ADcABAAsAAAALAAAACwAAAAAAAAAAABCAAAAAAAFAA8AAAAAAAAAAAAdAB0ADwAAAAAAAAAdAAAAMgAvADMAMwAyAC8ALQAtAAAAAAAAAAAALwAAAAAAAAApACkAKQAAACcAAAAnAA8AOwA8ADsAPAAAAAAAEAAPAB0ADwAQAA8AAAAAABAADwAdAA8AEAAPAAAAAAAqACoANQA1AB0APgAEADUAKgAqAAAAAAAxAEQAKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwAPAA8AEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8ADwAPABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQADQANABUAAAAiABcADQAAABkACgACAAIAFgABAAEBxwAFAAUABQAFAAUABQAFAAUABQABAAEABAAEAAEAAQABAAEAAQABAAEAAQABAAEABAABAAEAAQATAAEAAQATAAEAEwAiACIAAQABAAEAAQABAAEAAQABAAEABAAEAAQABAAEAAQABAAEAAEABAABABAAEAAMAAkACQAJAAkACQAWABwAEgANAA0AFwAHAAcABwAHAAcABwAHAAcABwABAAEAAgACAAIAAgACAAIAAgACAAIAAgACAAIAJAACAAEAAQABAA4AAAAdAA4ADgAOAAAADgAdABUAFQABAAEAAwADAAMAAgACAAIAAgACAAIAAgACAAMAAwACAAMACwALAAEABgAIAAgACAAIAAgACAAKABsAGQAZAAoACgAKAAoACgAYAAEAAAABACkAEgAqAAEAKQABABYABAABAAAADAABAAEADAABAAEAKQABAAQAAQAAAAQADAACACYAAwADACMAGQACAAMAAwAjAAMAAwADAAYAAgAIAAgABwADAAMAAwAGAA4AIwADAAAAAwALAAIAEAACAAAAAAAAACYAMwA7ACoALwAAACYANwA5AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAIAAAACAAAAAPAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARAA8AFAAPABEADwAUAAAAAAAAAAAAAAAuADUALAAtACwALQAsAC0ABAAAACAAAAAgAAAAIAAAAAAAAAA6AAEAAAAWAA8AAAAAAAAAAAAUABQADwAAAAAAAAAUAAAAJwAlACgAKAAnACUAIQAhAAAAAAAAAAAAJQAAAAAAAAAeAB4AHgAAABoAGgAaAA8AMAAxADAAMQAAAAAAEQAPABQADwARAA8AAAAAABEADwAUAA8AEQAPAA8AAAAfAB8AKwArABQANgAEACsAHwAfADIAAAA0ADwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAPAA8ADwARABEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADgAAQABAAEAAQABAAQADAAAABIAAwADAAMAAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAQAAAAoAKABUAAJERkxUAA5sYXRuAA4ABAAAAAD//wADAAAAAQACAANjYWx0ABRjYXNlACB0bnVtACYAAAAEAAEAAgAFAAYAAAABAAAAAAABAAgACQAUAKgR6hJEEmQSjBQmG6AcNAABAAAAAQAIAAIAWAApAccBFQEWARcBGAEZARoBGwEpASoBKwEsAS0BLgFEAVMBVAFVAVYBVwFYAVkBWgFhAZcBmAGZAZoBmwGcAZ0BngGfAacBpAGlAaYBoAGhAaIBowACAAgBCwELAAABDgEUAAEBIgElAAgBJwEoAAwBQwFDAA4BSwFSAA8BYAFgABcBgwGTABgABAAAAAEACAABESYACAAWAI4AjgF4AdYB1gPMBXwAOADqAhgCIgD0AiwCNgD+AkACSgJUAl4CaAJyAnwChgEIApACmgESAqQCrgEcArgCwgLMAtYC4ALqAvQC/gEmAwgDEgEwAxwDJgE6AzADOgNEA04DWANiA2wDdgFEA4ADiAFMA5ADmAFUA6ADqAByAboBhwACAUwAOAByAaABqgB8AbQBvgCGAcgB0gHcAeYB8AH6AgQCDgCQAhgCIgCaAiwCNgCkAkACSgJUAl4CaAJyAnwChgCuApACmgC4AqQCrgDCArgCwgLMAtYC4ALqAvQC/gDMAwgDEADUAxgDIADcAygDMADkAzgBiQAEASUBJQFMAYkABAElASMBTAGJAAQBJQEiAUwBiQAEASMBJQFMAYkABAEjASMBTAGJAAQBIwEiAUwBiQAEASIBJQFMAYkABAEiASMBTAGJAAQBIgEiAUwBiAADASUBTAGIAAMBIwFMAYgAAwEiAUwBiAACAUwAKwC2AMAAygDUAN4A6ADyAPwBBgEQARoBJAEuATgBQgFMAVYBYAFqAXQBfgGIAZIBnAGmAbABugHEAc4B2AHiAewB9gIAAgoCFAIeAiYCLgI2Aj4CRgBYAZsAAgFUACsAWABiAGwAdgCAAIoAlACeAKgAsgC8AMYA0ADaAOQA7gD4AQIBDAEWASABKgE0AT4BSAFSAVwBZgFwAXoBhAGOAZgBogGsAbYBwAHIAdAB2AHgAegB8AGdAAQBJQElAVQBnQAEASUBLAFUAZ0ABAElASMBVAGdAAQBJQEqAVQBnQAEASUBIgFUAZ0ABAElASkBVAGdAAQBLAElAVQBnQAEASwBLAFUAZ0ABAEsASMBVAGdAAQBLAEqAVQBnQAEASwBIgFUAZ0ABAEsASkBVAGdAAQBIwElAVQBnQAEASMBLAFUAZ0ABAEjASMBVAGdAAQBIwEqAVQBnQAEASMBIgFUAZ0ABAEjASkBVAGdAAQBKgElAVQBnQAEASoBLAFUAZ0ABAEqASMBVAGdAAQBKgEqAVQBnQAEASoBIgFUAZ0ABAEqASkBVAGdAAQBIgElAVQBnQAEASIBLAFUAZ0ABAEiASMBVAGdAAQBIgEqAVQBnQAEASIBIgFUAZ0ABAEiASkBVAGdAAQBKQElAVQBnQAEASkBLAFUAZ0ABAEpASMBVAGdAAQBKQEqAVQBnQAEASkBIgFUAZ0ABAEpASkBVAGcAAMBJQFUAZwAAwEsAVQBnAADASMBVAGcAAMBKgFUAZwAAwEiAVQBnAADASkBVAGcAAIBVAAmAE4AWABiAGwAdgCAAIoAlACeAKgAsgC8AMYA0ADaAOQA7gD4AQIBDAEWASABKgE0AT4BSAFSAVwBZAFsAXQBfAGEAYwBlAGcAaQBqgGFAAQBJQElASUBhQAEASUBJQEjAYUABAElASUBIgGFAAQBJQEjASUBhQAEASUBIwEjAYUABAElASMBIgGFAAQBJQEiASUBhQAEASUBIgEjAYUABAElASIBIgGFAAQBIwElASUBhQAEASMBJQEjAYUABAEjASUBIgGFAAQBIwEjASUBhQAEASMBIwEjAYUABAEjASMBIgGFAAQBIwEiASUBhQAEASMBIgEjAYUABAEjASIBIgGFAAQBIgElASUBhQAEASIBJQEjAYUABAEiASUBIgGFAAQBIgEjASUBhQAEASIBIwEjAYUABAEiASMBIgGFAAQBIgEiASUBhQAEASIBIgEjAYUABAEiASIBIgGEAAMBJQElAYQAAwElASMBhAADASUBIgGEAAMBIwElAYQAAwEjASMBhAADASMBIgGEAAMBIgElAYQAAwEiASMBhAADASIBIgGEAAIBJQGEAAIBIwEAAgICDAIWAiACKgI0Aj4CSAJSAlwCZgJwAnoChAKOApgCogKsArYCwALKAtQC3gLoAvIC/AMGAxADGgMkAy4DOANCA0wDVgNgA2oDdAN+A4gDkgOcA6YDsAO6A8QDzgPYA+ID7AP2BAAECgQUBB4EKAQyBDwERgRQBFoEZARuBHgEggSMBJYEoASqBLQEvgTIBNIE3ATmBPAE+gUEBQ4FGAUiBSwFNgVABUoFVAVeBWgFcgV8BYYFkAWaBaQFrgW4BcIFzAXWBeAF6gX0Bf4GCAYSBhwGJgYwBjoGRAZOBlgGYgZsBnYGgAaKBpQGngaoBrIGvAbGBtAG2gbkBu4G+AcCBwwHFgcgByoHNAc+B0gHUgdcB2YHcAd6B4QHjgeYB6IHrAe2B8AHygfUB94H6AfyB/wIBggQCBoIJAguCDgIQghMCFYIYAhqCHQIfgiICJIInAimCLAIugjECM4I2AjiCOwI9gkACQoJFAkeCSgJMgk8CUYJUAlaCWQJbgl4CYIJjAmWCaAJqgm0Cb4JyAnSCdwJ5gnwCfoKBAoOChgKIgosCjYKQApKClQKXgpoCnIKegqCCooKkgqaCqIKqgqyCroKwgrKCtIK2griCuoK8gr6CwILCgsSCxoLIgsqCzILOgtCC0oLUgtaC2ILagtyC3oLgguKC5ILmAueC6QBmQAEASUBJQElAZkABAElASUBLAGZAAQBJQElASMBmQAEASUBJQEqAZkABAElASUBIgGZAAQBJQElASkBmQAEASUBLAElAZkABAElASwBLAGZAAQBJQEsASMBmQAEASUBLAEqAZkABAElASwBIgGZAAQBJQEsASkBmQAEASUBIwElAZkABAElASMBLAGZAAQBJQEjASMBmQAEASUBIwEqAZkABAElASMBIgGZAAQBJQEjASkBmQAEASUBKgElAZkABAElASoBLAGZAAQBJQEqASMBmQAEASUBKgEqAZkABAElASoBIgGZAAQBJQEqASkBmQAEASUBIgElAZkABAElASIBLAGZAAQBJQEiASMBmQAEASUBIgEqAZkABAElASIBIgGZAAQBJQEiASkBmQAEASUBKQElAZkABAElASkBLAGZAAQBJQEpASMBmQAEASUBKQEqAZkABAElASkBIgGZAAQBJQEpASkBmQAEASwBJQElAZkABAEsASUBLAGZAAQBLAElASMBmQAEASwBJQEqAZkABAEsASUBIgGZAAQBLAElASkBmQAEASwBLAElAZkABAEsASwBLAGZAAQBLAEsASMBmQAEASwBLAEqAZkABAEsASwBIgGZAAQBLAEsASkBmQAEASwBIwElAZkABAEsASMBLAGZAAQBLAEjASMBmQAEASwBIwEqAZkABAEsASMBIgGZAAQBLAEjASkBmQAEASwBKgElAZkABAEsASoBLAGZAAQBLAEqASMBmQAEASwBKgEqAZkABAEsASoBIgGZAAQBLAEqASkBmQAEASwBIgElAZkABAEsASIBLAGZAAQBLAEiASMBmQAEASwBIgEqAZkABAEsASIBIgGZAAQBLAEiASkBmQAEASwBKQElAZkABAEsASkBLAGZAAQBLAEpASMBmQAEASwBKQEqAZkABAEsASkBIgGZAAQBLAEpASkBmQAEASMBJQElAZkABAEjASUBLAGZAAQBIwElASMBmQAEASMBJQEqAZkABAEjASUBIgGZAAQBIwElASkBmQAEASMBLAElAZkABAEjASwBLAGZAAQBIwEsASMBmQAEASMBLAEqAZkABAEjASwBIgGZAAQBIwEsASkBmQAEASMBIwElAZkABAEjASMBLAGZAAQBIwEjASMBmQAEASMBIwEqAZkABAEjASMBIgGZAAQBIwEjASkBmQAEASMBKgElAZkABAEjASoBLAGZAAQBIwEqASMBmQAEASMBKgEqAZkABAEjASoBIgGZAAQBIwEqASkBmQAEASMBIgElAZkABAEjASIBLAGZAAQBIwEiASMBmQAEASMBIgEqAZkABAEjASIBIgGZAAQBIwEiASkBmQAEASMBKQElAZkABAEjASkBLAGZAAQBIwEpASMBmQAEASMBKQEqAZkABAEjASkBIgGZAAQBIwEpASkBmQAEASoBJQElAZkABAEqASUBLAGZAAQBKgElASMBmQAEASoBJQEqAZkABAEqASUBIgGZAAQBKgElASkBmQAEASoBLAElAZkABAEqASwBLAGZAAQBKgEsASMBmQAEASoBLAEqAZkABAEqASwBIgGZAAQBKgEsASkBmQAEASoBIwElAZkABAEqASMBLAGZAAQBKgEjASMBmQAEASoBIwEqAZkABAEqASMBIgGZAAQBKgEjASkBmQAEASoBKgElAZkABAEqASoBLAGZAAQBKgEqASMBmQAEASoBKgEqAZkABAEqASoBIgGZAAQBKgEqASkBmQAEASoBIgElAZkABAEqASIBLAGZAAQBKgEiASMBmQAEASoBIgEqAZkABAEqASIBIgGZAAQBKgEiASkBmQAEASoBKQElAZkABAEqASkBLAGZAAQBKgEpASMBmQAEASoBKQEqAZkABAEqASkBIgGZAAQBKgEpASkBmQAEASIBJQElAZkABAEiASUBLAGZAAQBIgElASMBmQAEASIBJQEqAZkABAEiASUBIgGZAAQBIgElASkBmQAEASIBLAElAZkABAEiASwBLAGZAAQBIgEsASMBmQAEASIBLAEqAZkABAEiASwBIgGZAAQBIgEsASkBmQAEASIBIwElAZkABAEiASMBLAGZAAQBIgEjASMBmQAEASIBIwEqAZkABAEiASMBIgGZAAQBIgEjASkBmQAEASIBKgElAZkABAEiASoBLAGZAAQBIgEqASMBmQAEASIBKgEqAZkABAEiASoBIgGZAAQBIgEqASkBmQAEASIBIgElAZkABAEiASIBLAGZAAQBIgEiASMBmQAEASIBIgEqAZkABAEiASIBIgGZAAQBIgEiASkBmQAEASIBKQElAZkABAEiASkBLAGZAAQBIgEpASMBmQAEASIBKQEqAZkABAEiASkBIgGZAAQBIgEpASkBmQAEASkBJQElAZkABAEpASUBLAGZAAQBKQElASMBmQAEASkBJQEqAZkABAEpASUBIgGZAAQBKQElASkBmQAEASkBLAElAZkABAEpASwBLAGZAAQBKQEsASMBmQAEASkBLAEqAZkABAEpASwBIgGZAAQBKQEsASkBmQAEASkBIwElAZkABAEpASMBLAGZAAQBKQEjASMBmQAEASkBIwEqAZkABAEpASMBIgGZAAQBKQEjASkBmQAEASkBKgElAZkABAEpASoBLAGZAAQBKQEqASMBmQAEASkBKgEqAZkABAEpASoBIgGZAAQBKQEqASkBmQAEASkBIgElAZkABAEpASIBLAGZAAQBKQEiASMBmQAEASkBIgEqAZkABAEpASIBIgGZAAQBKQEiASkBmQAEASkBKQElAZkABAEpASkBLAGZAAQBKQEpASMBmQAEASkBKQEqAZkABAEpASkBIgGZAAQBKQEpASkBmAADASUBJQGYAAMBJQEsAZgAAwElASMBmAADASUBKgGYAAMBJQEiAZgAAwElASkBmAADASwBJQGYAAMBLAEsAZgAAwEsASMBmAADASwBKgGYAAMBLAEiAZgAAwEsASkBmAADASMBJQGYAAMBIwEsAZgAAwEjASMBmAADASMBKgGYAAMBIwEiAZgAAwEjASkBmAADASoBJQGYAAMBKgEsAZgAAwEqASMBmAADASoBKgGYAAMBKgEiAZgAAwEqASkBmAADASIBJQGYAAMBIgEsAZgAAwEiASMBmAADASIBKgGYAAMBIgEiAZgAAwEiASkBmAADASkBJQGYAAMBKQEsAZgAAwEpASMBmAADASkBKgGYAAMBKQEiAZgAAwEpASkBmAACASUBmAACASwBmAACASMBmAACASoAAQAIASIBIwElASkBKgEsAUsBUwAGAAAABAAOAB4ALgBAAAMAAAACAFwC3gABCZ4AAAADAAAAAgBsADQAAQmOAAAAAwAAAAIAPAK+AAAAAQAA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"}
_FI_LIC = 'Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter)\n\nThis Font Software is licensed under the SIL Open Font License, Version 1.1.\nThis license is copied below, and is also available with a FAQ at:\nhttp://scripts.sil.org/OFL\n\n-----------------------------------------------------------\nSIL OPEN FONT LICENSE Version 1.1 - 26 February 2007\n-----------------------------------------------------------\n\nPREAMBLE\nThe goals of the Open Font License (OFL) are to stimulate worldwide\ndevelopment of collaborative font projects, to support the font creation\nefforts of academic and linguistic communities, and to provide a free and\nopen framework in which fonts may be shared and improved in partnership\nwith others.\n\nThe OFL allows the licensed fonts to be used, studied, modified and\nredistributed freely as long as they are not sold by themselves. The\nfonts, including any derivative works, can be bundled, embedded,\nredistributed and/or sold with any software provided that any reserved\nnames are not used by derivative works. The fonts and derivatives,\nhowever, cannot be released under any other type of license. The\nrequirement for fonts to remain under this license does not apply\nto any document created using the fonts or their derivatives.\n\nDEFINITIONS\n"Font Software" refers to the set of files released by the Copyright\nHolder(s) under this license and clearly marked as such. This may\ninclude source files, build scripts and documentation.\n\n"Reserved Font Name" refers to any names specified as such after the\ncopyright statement(s).\n\n"Original Version" refers to the collection of Font Software components as\ndistributed by the Copyright Holder(s).\n\n"Modified Version" refers to any derivative made by adding to, deleting,\nor substituting -- in part or in whole -- any of the components of the\nOriginal Version, by changing formats or by porting the Font Software to a\nnew environment.\n\n"Author" refers to any designer, engineer, programmer, technical\nwriter or other person who contributed to the Font Software.\n\nPERMISSION AND CONDITIONS\nPermission is hereby granted, free of charge, to any person obtaining\na copy of the Font Software, to use, study, copy, merge, embed, modify,\nredistribute, and sell modified and unmodified copies of the Font\nSoftware, subject to the following conditions:\n\n1) Neither the Font Software nor any of its individual components,\nin Original or Modified Versions, may be sold by itself.\n\n2) Original or Modified Versions of the Font Software may be bundled,\nredistributed and/or sold with any software, provided that each copy\ncontains the above copyright notice and this license. These can be\nincluded either as stand-alone text files, human-readable headers or\nin the appropriate machine-readable metadata fields within text or\nbinary files as long as those fields can be easily viewed by the user.\n\n3) No Modified Version of the Font Software may use the Reserved Font\nName(s) unless explicit written permission is granted by the corresponding\nCopyright Holder. This restriction only applies to the primary font name as\npresented to the users.\n\n4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font\nSoftware shall not be used to promote, endorse or advertise any\nModified Version, except to acknowledge the contribution(s) of the\nCopyright Holder(s) and the Author(s) or with their explicit written\npermission.\n\n5) The Font Software, modified or unmodified, in part or in whole,\nmust be distributed entirely under this license, and must not be\ndistributed under any other license. The requirement for fonts to\nremain under this license does not apply to any document created\nusing the Font Software.\n\nTERMINATION\nThis license becomes null and void if any of the above conditions are\nnot met.\n\nDISCLAIMER\nTHE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,\nEXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF\nMERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT\nOF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE\nCOPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,\nINCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL\nDAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING\nFROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM\nOTHER DEALINGS IN THE FONT SOFTWARE.\n'
try:
    import base64 as _b64
    os.makedirs("/opt/fo/fnimg", exist_ok=True)
    os.chmod("/opt/fo/fnimg", 0o755)
    for _k, _v in _FI_ASSETS.items():
        _fp = "/opt/fo/fnimg/" + _k
        open(_fp, "wb").write(_b64.b64decode(_v))
        os.chmod(_fp, 0o644)
    open("/opt/fo/fnimg/Inter-LICENSE.txt", "w", encoding="utf-8").write(_FI_LIC)
    _chk = [PY, "-c", "import PIL; print(PIL.__version__)"]
    _r = subprocess.run(_chk, capture_output=True, text=True, timeout=60)
    if _r.returncode != 0:
        _r2 = subprocess.run([PY, "-m", "pip", "install", "-q", "--disable-pip-version-check", "Pillow"],
                             capture_output=True, text=True, timeout=600)
        p("Pillow ставим:", "ок" if _r2.returncode == 0 else ("ошибка " + ((_r2.stderr or "") + (_r2.stdout or ""))[-400:]))
        _r = subprocess.run(_chk, capture_output=True, text=True, timeout=60)
    p("Pillow:", ((_r.stdout or "") + (_r.stderr or "")).strip()[-200:])
    _r3 = subprocess.run([PY, "-c", "from PIL import Image, ImageFont; f = ImageFont.truetype('/opt/fo/fnimg/title.ttf', 60); "
                          "im = Image.open('/opt/fo/fnimg/bg.jpg'); print(im.size, int(f.getlength('Проверка')))"],
                         capture_output=True, text=True, timeout=60)
    p("картинки функций: фон и шрифт", ((_r3.stdout or "") + (_r3.stderr or "")).strip()[-300:])
    # 289д: скорость загрузки файла в Telegram (сам файл никуда не уходит: POST 45 КБ на getMe)
    try:
        import time as _t289, urllib.request as _u289
        _E289 = {}
        for _ln in open("/opt/fo/.env", encoding="utf-8"):
            _ln = _ln.strip()
            if "=" in _ln and not _ln.startswith("#"):
                _a, _b = _ln.split("=", 1)
                _E289[_a.strip()] = _b.strip().strip('"').strip("'")
        for _nm in ("TG_REPORT_BOT_TOKEN", "TG_MEET_BOT_TOKEN"):
            _tk = _E289.get(_nm, "")
            if not _tk:
                p("загрузка 45 КБ,", _nm, ": нет токена")
                continue
            _bd = "----fo289"
            _body = ("--%s\r\nContent-Disposition: form-data; name=\"x\"; filename=\"x.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n" % _bd).encode() \
                + os.urandom(45000) + ("\r\n--%s--\r\n" % _bd).encode()
            _t0 = _t289.time()
            try:
                _rq = _u289.Request("https://api.telegram.org/bot%s/getMe" % _tk, data=_body,
                                    headers={"Content-Type": "multipart/form-data; boundary=" + _bd})
                _u289.urlopen(_rq, timeout=120).read()
                p("загрузка 45 КБ,", _nm, ": %.1f с" % (_t289.time() - _t0))
            except Exception as _e:
                p("загрузка 45 КБ,", _nm, ": ошибка за %.0f с" % (_t289.time() - _t0), str(_e).replace(_tk, "***")[:120])
    except Exception as _e:
        p("загрузка 45 КБ: ошибка", str(_e)[:150])
except Exception as _e:
    p("картинки функций: ошибка", str(_e)[:200])

p("")
p("== ОТЧЁТЫ С КАРТИНКОЙ: ПОЧЕМУ УШЛИ ТЕКСТОМ (290, только чтение) ==")
try:
    p("службы:", sh("systemctl list-units 'fo*' --no-pager --plain --no-legend | awk '{print $1, $3, $4}'").strip().replace("\n", " | ")[:600])
    p("журнал fo (картинки, бот отчётов, ошибки):")
    p(sh("journalctl -u fo --since '-20h' --no-pager -o cat | grep -E 'бот отчётов|картинк|fnimg|_fo_fi|Traceback|Error|error' | tail -40").strip()[:4000] or "(пусто)")
    p("история чата — сообщения бота отчётов за сутки:")
    p(sh("sudo -u postgres psql -d fo -Atc \"SELECT to_char(msg_at AT TIME ZONE 'Europe/Moscow','DD.MM HH24:MI'), coalesce(ai_note,''), length(text), "
         "encode(convert_to(left(text, 14), 'UTF8'), 'hex') FROM fo_chat_msg WHERE author='Бот отчётов' AND msg_at > now() - interval '30 hours' "
         "ORDER BY msg_at DESC LIMIT 15\"").strip()[:2500])
    p("outbox — последние записи:")
    p(sh("sudo -u postgres psql -d fo -Atc \"SELECT left(row_to_json(o)::text, 400) FROM outbox o ORDER BY 1 DESC LIMIT 6\"").strip()[:3000])
    p("routing.py — как шлёт:")
    p(sh("grep -n 'send_telegram\\|def dispatch\\|async def\\|outbox\\|import' /opt/fo/backend/app/routers/routing.py | head -60").strip()[:3500])
    _rp276 = open("/opt/fo/backend/app/routers/routing.py", encoding="utf-8").read()
    _i276 = _rp276.find("async def dispatch")
    p("routing.dispatch:")
    p(_rp276[_i276:_i276 + 3500] if _i276 >= 0 else "(не найдено)")
    p("кто ещё шлёт отчёты (send_telegram в app):")
    p(sh("grep -rn 'send_telegram' /opt/fo/backend/app --include=*.py | grep -v FO-STEP | head -30").strip()[:3000])
except Exception as _e:
    p("разбор 290: ошибка", str(_e)[:200])

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
            if _k == "TG_REPORT_BOT_TOKEN" and re.match(r"^[0-9]{6,12}:[A-Za-z0-9_\-]{30,}$", _v): _got[_k] = _v   # 235: бот отчётов
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
        res = call("getUpdates", {"offset": off, "timeout": 10,
                                  "allowed_updates": json.dumps(["message", "my_chat_member", "edited_message"])}, timeout=20)
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
        time.sleep(1)
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
    "plan": "/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAGQBQADASIAAhEBAxEB/8QAHQAAAwEAAwEBAQAAAAAAAAAAAAECAwUHCAYECf/EAGYQAAIBAwIEAwMDDAsJDAgFBQABAgMREgQFBiEiYQcxURNBcQiBshYXIzI2VXN0kZOhsQkUJjRCcpKzwdHSFTNDUlNWYpSkGCQlNURUZHWCosLTJyhGZqO04fAZRVdYlmNldoPU/8QAHAEBAQEAAwEBAQAAAAAAAAAAAAECBQYHAwQI/8QARREAAgECAwMIBgYJBAIDAQAAAAERAgMEBRIGITFBUWFxgZGxwQcTNHKh0RQWIiMyUhUkMzVCU4Lh8GKSwtIlc0Oy4vH/2gAMAwEAAhEDEQA/APAaGhGlGn7TL7JCOEXLqdr29y7naUc0gQ0Sho0jSLQ0JGlSn7PD7JCWUVLpd7dn3NooIZKKNo2hotBSp+0y+yQhhFy6na9vcu4kzRShxJRSNI0UNFVKfs8euEsoqXS72v7n3JRtGi0NEo0pU/aZdcI4xcup2vb3LuaKgRSITKTNpm0WikZp2NZw9nj1wllFS6Xe3Z9zSZoRSlYi6GmaTEl5Et3HThnl1xjjFy6na/ZdyRJZAQXE2SSCYiqkMMeuEsoqXS727PuQ2ZbMtiZI2xwhnl1xjjFy6na/ZdzBlmbJG2IyzIiWU2FSGGPXGWUVLpd7dn3MMjMxMYmzLMsliKhDPLrjHGLl1O1+y7ksyzJLJKZJhmWJkM1qQwx64yyipdLvbs+5kZZBMllMIQzy64xxi5dTtfsu5kyQTIohnzZgQmMKkMMeqMsoqXJ+XZ9zJGZsQ2IyZYmQaxhnl1RjinLqdr9l3MjLMiZLKZLPmZYmQzSpDDHrjLKKfJ3t2fczZlmWIUhhGGeXVGOMXLqdr9l3MshmJjEzDMMliGxzhhj1xllFS6Xe3Z9zLIzNkspksyzImQzWMM79UY4q/N2v2RkzDMCJZTIZlkYAVOGGPXGWUU+Tvbs+5JkgABUIZ5dcY4xb5u1+y7gEgAAAAFThhj1xllFPk727PuASAAAAFQhnl1xjjFvm7X7LuSAAAAAAVOGGPXGWUU+Tvbs+5IAABUIZ5dcY4xb5u1+y7gEgAAAAFThhj1xllFPk727PuASAAAAFQhnl1xjjFvm7X7LuSAAAAAAVOGGPXGWUU+Tvbs+5IAABUIZ5dcY4xcup2v2XcAkAAAAAqcMMeuMsoqXS727PuASAAAAFQhnl1xjjFy6na/ZdyQAAAAACpwwx64yyipdLvbs+5IAABUIZ5dcY4xcup2v2XcAkAAAAAqcMMeuMsoqXS727PuASAAAAFU6ftMuuEcYuXU7X7LuSAAAAAAVUp+zx64SyipdLvbs+5IAABVOn7TLrhHGLl1O1+y7gEgAAAAFVKfs8euEsoqXS727PuASAAAAFU6ftMuuEcYuXU7X7LuSAAAAAAVUp+zx+yQllFS6Xe1/c+5IAABVOn7TL7JCOMXLqdr29y7gEgAAAAF1Kfs8PskJZRUul3tf3PuAQAAAAF0qXtc/skIYRcup2vb3LuQAAAAAAXVpeyw+yQnnFS6Xe1/c+5AAABdKl7XP7JCGEXLqdr29y7gEAAAAAF1aXssPskJ5xUul3tf3PuAfSjQkxo55HLItDITLRo0ikUiEUjRopMpEIpM0jSKKTJGjaNItDRCZSNJlRaYyEUmaTNJlJlpmY0zaZTRDTIUhplKmaJjuZpjTNSaTLTHkZ5DyLJZLyDIjIMhIkq4rk5CuSRJTYriuK6JJmQE2Jy7iuSSBcQEtmGyNg2SNiMmQZDG2SZMyAmMlsy2QTYmAmzBgliBiZlkYmyRtiMsyxEtjbJMMyITGS2ZZGIQAzJhkskbEYIJkFNkmDLEyWNkmTDAmRRDMsghMZLMGSWIYjLIxMkbJMMyxMllMkwzAmQymSzLIwAAIQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+mTLM0a0avs8uiEsouPUr2v713OcRyokUmSNOxtM0mWNMlM0qVPaYfY4Qxio9Kte3vfcqZpMEzfT6TVampSp0KE5yrTVOnZfbSfuTMKcZVJxpxV3JpL4nYvCdChT3CpOdv2vs2nTvb/AAkk25fNFS/lH78FhfpVemY/yfBM5LLcCsdeVupwpXzfck2fDa/b9ZtWrnodfRdKtTtlFtPzV07rzMacJ1JqnThKUpOyUVdtn6dfu1fcNy1O5V4wnPUNu01fBe63wSSO/vDjWUK3C9Hda+wabapYvKVKjGnGrBL++JLmk+/6j74LBU469VRRVCW9bp3HObN7PWNo8fcwtF526VLTdOpumeWGknw4wefNRptTpKz0+q09SjVjZuFSDjJXV1yfZpkJn7d/3Wpvm967d6l76qvOok/4MW+lfMrL5j8B+KrSqmqeB1zEK3ReqpsuaE3DfFqdz7jRDP6L/J8/Y8fATxU8BeF/FrjbjHjHatVue3VNVr3pdw0VDSUVCpOLl9k00nFKMLtyk/ec9/8Ah+/IR/8A3Gbt/wDy/Zv/APmPyXMdatXKrVUzS4e7mPwU4y3UpU9x/MtSKTPUPyVfkveGnjx4/wDGnhhv3EO+w2Dh+hra+36vatXp1WrxpaqFKnKU5UpwknCV7xiruzVlyPhPlceDfC/yffHDd/DTg7W7lrtr0ej0lWnV3SpTq18qtGM5XlThCPJvlaPl6n0WKtuuijlqUrqP003FVcrtLjTx+HzR0zcaZCkzvH5HvyedP8pXxchwRu2u1+g2XSaGtuG5avRYKtThG0YKLnGUU5VJQXNPlc/S6tKdT5E33bxcvU2qXXXwOklIakf0E+Ux+xscCeE3gzv3iP4ecWcUbnuWwwhqqul3CennTnplNKq17OlBpxi8vO1ovkeAdKqWq1mmo6jGlSlOFOco9No3s5Nv32958sLireLbVp8NxablNdHrKeHyMkwuf012b9jw+RPvuo0m37V49b/rddq8Y0tNpuKdpqVak2r4xhHTNt9kcnxD+xnfJC4RdBcV+MHF2yvU5ewW4cQbXpva42yx9ppVla6vbyuj4PM7NLhz3H51jrVXCe4/lvcLnprjD5PHg7tvyvOGvAvgbjLcN94P32toNPW3KnuOl1Opi61/aYVaVP2SlG3K8Hb33PV/EP7GZ8kThFUHxX4v8X7KtTl7D+6HEG2ab2uNssfaaVZWur28ro+lePtUUU1uYqmN3MfS5iaLdSofFpPsZ/LW6DI9yfKQ+SB8k3wv8HN9438NvGncN94i2/2H7T0FXiPbdVGtnWhCd6dGjGpK0ZSfJq1r+Rn8ib5DnhN8pHwp13HXHPEPFuh1+l3mtt0Ke06vTUqLpwpUpJtVaFSWV5vnlby5CnHW67dV1TFPHd1fMV4q3RQrlXBuPM8PZCuf1GofsZHyWOLtNqtNwJ4y8S6vX6aDg50N227XQozXK9SnSoRk+fmso/FHhP5S/wAm7jH5MvHceEOJtVR3DR62k9Vte56eLjT1lG9m3FtuE4vlKN3blZtNMzax9m9Wrae98J5TVq9RelU8UdSCvYTkOE8MumMsouPUr27rufqk+kibJATkSTI7ktibHOeePTGOMUuStfu+5kkkgDZLZlsgNklRnhl0xlkrc15d13IbMNmQbJbBsRGyAS2VUnlbpisUlyVr92ZtmDICAFUwv0xd1bmvLv8AEy2ZZLYgEzJBNkg3cc5549MVZJcla/cwzBImxtkNmWZYmJlxnhfpi7q3NeXw7mbZhkYmIBNmWZJbEVOedumKskuS8yTJkTIZTYRnjfpi7q3NeRhkZJDZTIZkyAgHOeVumKsrcl5mTLM2IYmYZlksktSxv0xd1bmvLuQZMiZI2xGGZYAOUsrdMVZW5LzEAAAOMsb9MXdW5ryAEAAAAAOUsrdKVlbkvMAQAAAAOMsb9Kd1bmvIQAAAAAA5Syt0pWVuS8xAAADjLG/SndW5ryAEAAAAAOUsrdMVZW5LzAEAAAADjLG/TF3Vua8hAAAAAADlLK3TFWVuS8xAAADjLG/TF3Vua8u4AgAAAAByllbpirK3JefcAQAAAAOMsb9MXdW5ry7iAAAAAAHOeePTGOKS5K1+77iAAAHCeGXTGWSa5q9u67gCAAAAAKnPPHojHGKXJWv3fcAkAAAAKhPDLojLKLXNXt3XckAAAAAAqc88eiMcYqPSrX7vuSAAAVCeGXRGWUXHqV7d13AJAAAAAKnPPHojHGKj0q1+77gEgAAABVOp7PLojLKLj1K9u67kgAAAAAFVKntMeiEcYqPSrX7vuSAAAVTqezy6ISyi49Svbuu4BIAAAABVSp7THohHGKj0q1+77gEgAAABVOp7PLohLKLj1K9u67kgAAAAAFVKntMfscI4xUelWvb3vuSAAAXTqezz+xwllFx6le1/eu4BAAAAABdWr7XD7HCGEVHpVr2977gH0I07EpjRzRyiZomMzTKTNJlLTsUmQfs2nady3vWw27adHU1OpqJuNOHnZeb58kbTNSuUe2JPcNPf3VIv9J9ptdZw4e4iqp2lKdSF+2CX9LOIqeH/ABrs0P7qa7YK9LT6VqrVnlCWMVzbdm3axyOyxdehvW1r7avD2lPvlFr9aRy+V1b3SuO/40s5nKLv2nTS9+/40s18N+BHxDqY7tutJrbaEuUX/h5L3fxV7383rb6HxP8AEGFKjU4T2Gqly9nq6tPkor/JR/p9PL1txe6+KGmo8PUds4boVNLqJU1SleNlp4pWaj6v0fz+Z1zk27t3b5ts/dicZh8DhlhME5qqX2qvJf5u65OavZxayjAPL8sqmq4vvK1xf+lf5uXS2UmUmZpjTOvpnUJP7S/Jn4S1nH3yAdi4I2/VUdNqt+4W1+3Ua1a/s6c6s68FKVudk5c7HkXcv2Jjxf2zbtVuVTxM4PnDSUJ15RjHVXajFtpfY+x6k8Edz3HZv2NrT7vs+4anQ67R8FbrX02q01WVKrRqR9u4zhOLTjJNJppppn8uavykvlEailOhX8e/EapTqRcJwnxTrnGUWrNNOrzTOJqV6rG4lWKknPLv5aoPxYFXPUUtP7Mvd3SenP2JmLh4+8TU203Hhisv9poHw/7Ja0vla8Rf9X7b/wDLQPtv2JaTl4+cStttvhes3/rNA7y+Vj+x7eI3ygvGrdPE7h3jjhvbNDrtNpKENPrVXdWLpUowbeEGubXLmfXFVq3jbVdbhaX4sti7RaxN91OJj/gfyyuf1R/YqPDSjwt4ScR+Lm60o0qvEmten09WatjotKnlK/o6kql/waPDXyh/kn8bfJ2424c4E3re9s33cOJqKq6P+5satrur7JQanFO7l6H9VOKeLuFPkTfJX2ipumzvc9Nw1odFtS0NGpGm9bqqjSqWbTSvJ1Zvk+SZ9MdiqasJ9051vSu/f8YXaMY3eros0qZ39nJ8+w+b+R/4ubd8pbw38SNl32S1NL6pN20lSjJ83t2tlKdJfDGdSK/in8i/E7gjcfDTxD4j4B3WLWp2Hcq+hk3/AAlCbUZrtKNmuzP6ifJp/ZAvDPxc8Udv8L9m8IvqPr77Cr7LVx1NFwqVacJTjTlGFOLbaUknfz+J5w/ZVvCv6lfGPafE3Q6dx0fGOg9nqZKNo/tzTWhL53TdJ/Mz8th1YXF0qqnSq6UuM76Vufwq7z64Sv7y7aahtupLml718fgdG/Iuf/rT+Gq//vlL6Mj1b+y/O24eGX4HdPpac8ofItafyqPDT/ryl9GR6u/ZgHbcPDL8Dun0tOfrxz/WcN11f/Vi37dV7nnUeSfkgtv5T3hn/wD5FpPpH9W/lYfJD2n5VEeHI7nxvq+HvqdepcPYaKOo9t7b2d75Tja3s+/mfyi+SA0/lPeGa/8AeLS/SP6cfLh+SPxh8qSPCS4U4n2baHw89Y6/90VVftPbeyxx9nGXl7N3v6oxmbiuy5jfVv5ty3nxuVacY3q0/ZW+J/N4njP5W/yCNj+TT4XUfEPbvEjXb7Vq7pQ256Wvt0KEUqkZyyyU5eWHlb3nqL9ik5/Jz3df+9Gq/wDl6B5E8cP2OnxK8C/DPd/FDfuO+Gdx0Oz+x9rp9ItQqs/aVY01jlBLk5p835I9dfsUb/8AVy3h/wDvRqv/AJfTmLtxV4G9NzXEckRvp3efaYxr1WbbmftcefdUfLfJ0/Y9fFjws+UHpfF7ivj3hyltmg1mq1cNLs9fU1a+qVTNKlU9pSpxjC0k3Zy8rW966v8A2WTxE4X4h8QeEuA9m1tHV7lwzpNTU3N0pZftedeVPCjJ/wCNjTya92S9Tsf5A3yteLOKfFvivwY8VOLdZvFbcNVqNVw/qdfWdScJ0ZSVTTKT9zprOK92EvU8u/sgPgFV8EvHLXbltellDhrjCVTdttkk3GnUlL7PQv6xm7pf4s4nxoVbxVlXnuVM09O7h493f+qzq+l3ndf21u6Inj8fi+Y8z3sLIi4HOSfpkbbEFxXMySR3E2S5CuRskjbFcTYnIzJkbdiWxCuZkSNktg2SZMtg2AhNmWzLYNkgIyQCWwbEZbMtgIBNmWzLYmyQYmzDZAbJuDYjJlg2Q2NskyZbATYyXcyzJLYAJmGZYmyRtCIwIllCaMMyyBMpiMmWiLCZTQmZMkWuGJQEgQTiPFDsFgBWQWHYLACsFirBYAmwWKsFgCbBYqwWAJsFirBYAmwWKsFgCbBYqwWAJsFirBYAmwWKsFgCbBZDsFhAgnEMSrBYCCcQxKAQIJsKzLAkEgizCxYrCBBIFWCwgQSBVkLEQIEA8RWZIJAAFmAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB9CmaUoe0y64Rxi5dTte3uXcyuM5g5JMtDRCZSZpM0mWpH79t3Pctg1tLcdp17oamMLxqUndpNWad+XzHHDTaLJeJ9PrvEbjbc9HV0Gt4gr1NPXi4VIYwjlF+abSTsz8+0cQx0Oq0terCV4J0qsl76b/pTSfzHAqRR97N6qxVqoPrYu1YerVb3HJ7s9DqN01NXbqsVQd6kXLpu/el897H4Lmdxpiuv1lTq5xXXrqdXOaJ2GpEJgmSSSfb6bxj8X9s4YjwToPFni+hw7LTS039yKG/aqOiVGd8qToKahi7u8bWd3fzPjbmaY1IKE21xZVCUI+g4R47434A19XdeBOMd84c1tak6FXU7RuNbR1Z0203CU6Uotxuk7N2ul6H18PlLfKOnl/6wXiNHGLfVxXr+fZfZfM6xUhplaVXFSTTTMwfV774qeJvFO9bfxJxN4jcUbvu+0uL2/cNfu+o1Gp0jUsk6VWc3KnaXUsWufM34s8YPFjj7b6e0cdeKHFvEehpVVXp6Xdt71OsowqJNKahVnJKVm1e17Nnx1wuNNMJRwNbpk5DZ963jh3dNLvnD+7azbNx0VRVtNrNHXnRr0Ki8pQnBqUWvVNM+g4x8VfFLj7SabQce+JnFHE2m08/b0KO7bzqdbTo1GrZRjVnJRlbldc7Hx9x3NOKuI3TPKchsu+b1w1uum33h3eNbtW5aKoqum1mi1E6FehNeUoVINSi+6Zy3GHiT4i+IctLPj/j7iPiaWiU1pXvG619a6ClbLD2spY3xje3nZeh8zcMg4bTfIN0ycjsm77xsG6afe+H941W17joJqvptZpNROhXo1I+Uqc4NSjL0aaZ91/ul/lHf/r/4kf8A8r1//mnWmQZBpVfi3hqluWj7niLxx8a+L9or8P8AFnjBxtve16rH2+h3HiDV6nT1cZKUcqdSo4ys0mrrk0mfn4T8YPFrgLbZ7NwN4o8XcO7fUquvPS7Tvep0lGVRpJzcKU4xcmkle1+S9D464XJppSaS3MRS1EHJ7fv2+7HvWn4k2ffdbot2oVf21R1+l1U6eppVr3zjUi1KM787p3OY4v8AFXxP8QtPp9Jx94kcUcS0NJN1NPS3jeNRrIUZtWcoKrOSi2uV0fJ3fqFw1S4lcBO/VylZDis79UVZX5u1+xFxXRZElXFcnITkSSFXCaxt1Rd0nyfkZuQnJszIKuK5LYrkI2aRWV+qKsr8/eQ5EuRNySQrJCyRNxNmWzLLn026k7pPk/IjJEtiMshWS7guq/UlZX5vz7EN2JbuZZGVdeoXIAyZZTYpxxt1J3V+T8iWK5kyNslu4ZIRkjBRyv1JWV+bJYxGWZJYimSzJIHKNrdSd0nyZDGJmSEhGOV+aVlfm/MbJMsy0JkspiZCEjlG1upO6vyEBkhLJLZLMGRJZfwkrK/Nk2GBGiQKwWGAgQNxxtzTur8vcKw7AIECsOMb35pWV+bALCBAgHYLCBAhuONuad1fkFgsWBAgHYLCBARV780rK/MQ7BYQIEA7BYQIBq1uad1fkIYrCC6QGle/NKyvzFYLCBpC6FdDsFhA0iuhtJW5p3V+TCwYkgmkLILBYLP1EDSEYXvzSsr8xWGAgQKwWGAgkClDG3NO6vyYrFASBBNhxhlfmlZX5+8YCBBFgLsKwISOUbW5p3V+THYLEBFgsVYLACUMr80rK/Nk2KsAEE2FZlgSCQTKONuad1fk/IRVgsIEEjjHK/UlZX5vzCwWJBIEAWYAAOUcbdUXdX5PyEAAAAADjHK/VFWV+b8+wgAAAAAByjjbqi7q/J+XYQAAA4Qzy6oxxTfN2v2XcQAAAAABU4YY9cZZJPk727PuSAAAAAFQhnl1xjjFvm7X7LuSAAAAAAVOGGPXGWUVLpd7dn3JAAAKhDPLrjHGLl1O1+y7kgAAAAAFVKeGPXGWUVLpd7dn3JAAAAACqdP2mXXCOMXLqdr9l3JAAAAAAKqU/Z49cJZRUul3t2fckAAAqnT9pl1wjjFy6na/ZdyQAAAAACqlP2eP2SEsoqXS72v7n3JAA55MpMzQ0zlUzkCxp2JTGmakslqQ0zMadjUmkzQabRCkO5ZLJakMgE2akppcaZCkNSRVUWS1IaZmO5qSyXcdzO47iSyaXC5mpDyLJZLyGpEZBcsiS8gyIuFxIkvIMiLoLoSJLyDIi4ZCRJWQXZGQZCRJVwvYjIVySJKyFcnIWQElXE2TdhyJJB5CbYXESSAACIRhyJdh2CyMtkJAdhYkBLEU13E13MsyyQCwiMkAS2PzE0ZJBIDEZZBXC4mJkZlobJYXYGGQQBcXwMkYmJjEyMyITGJmSNEsXwG0JmSCExgRojROIYlASCQTiOwwEFgVuwWGAgQKwWHYLFgQABZhYQWAAdgsIECAdhCBACuMLCBBPNisXYLFLBFgsXYLCCQRYLF2CxYLBFgsWAgQQBYWRIEEAVZBiIJBIDxDEkAQJDsFhBIFYLD5oafqSCQTYCuQWIIIAuwsQSCQKxFYCBAOwEgkCsKwwECBWFYoCQSCbCsXYVgQkCrCsQE2Cw7AATYViwECCLAVYLEgkEgOwrMhAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAOaUjSnVwy6Iyyi49Svbuu5imCZySZ+5M0Q0yFIaZqSmiZc6mePRGOMVHpVr933MUxpmkyljTIUhplksmtOrhfojLJW6le3ddxJoi4FkqZpcZnfuNSLJqTWVRzx6Ixxio8la/d9xZMhSHcsiS1IqFRRv0xd1bmr27mVxlkpdwIuFyyJNCpzzx6YxxSXJefd9zG7HkxqEl3C5GTDJl1Fk1hPC/TF3TXNeRNyMmGTGoSXcLkZMMmNQk0lPK3TFWSXJeZLdiHIWRJIVccZ436U7q3NeRnkwuxqLJVwJvYL3EiSrjlLK3SlZW5LzJASB8g5+5AFySBxeN7pO6tzXkLl6BzC3cAGL5x2FYgCUsrckrJLkSVYVvcSBAuQJ2v0p3VuYmBIISJoppi+YjMslxFLnbklZW5IoRkhmxFtEtEZCU7X5J3VuZLuU00JmTMEiGxGSQDd7ckrK3IljEZZBXfqCk17r3XvBoRCMTE7oYmZZGS2wbv7kDEQkAA7BZkgkAnb3IXzDsOwgsE/MMdgsWBAm725LkFyrBYQIJv2Gnb3DsFhAgV+wfMMBA0i5+gO7GAgsE2CxYFEEpCsWAgQTiFkUkxqPqINQT8yCxaiPEQIM8ew1H4GmIYlgaTPFeoYl4hiIEEYIHG9vLkXiFhAgyxfoGJrYVuxIJBmlb3L0FiaOPzCxZIJBFn6CsXYLCCaSHz9yCxVkGJIEEWBcvcuaKxYWfoSCQTZi5lW7AIEE3Y3Ju3JKytyHYLEghN+wr9irCxECATtfpTurcxDsKwgkAIYEgQDd7ckrK3IV+wwEEgm7BTcb9Kd1bmh2CxCQTfsFx2FYkEgQ5O9uSVlbl7wEIEAAAIJAKTjfpi7q3NE8yhWIQm4FWFYkCAlLK3SlZW5LzEAEgkAOMsb9MXdW5ryEAgQAABCAOUsrdMVZW5LzEAAAAADjLG/TF3Vua8u4gAAAAABznnj0xjikuStfu+4gAACoTwy6Iyyi1zV7d13JAAAAAAKnPPHojHGKj0q1+77kgAAAABUJ4ZdEZZRcepXt3XckAAAAAAqc88eiMcYqPSrX7vuSAAAVTqezy6ISyi49Svbuu5IAAAAABVSp7THohHGKj0q1+77kgAcqmNSIuXThnl1xjjFy6na/Zdz98n65KTBMhMakakslqRSZmmXOOGPXGWUU+Tvbs+5ZNJlJhchMakWSyWmNSFTWd+qMcU5c359l3EmWSlpodzO47mpBdwFJOGPVF5JPk727fESkWSyXcFIm5UEpX64xsr835/ASJHkGRNwuWSyXkGSIuVKONuqLur8n5FkSPJBkiLhcSJLyQZIUY5X6krK/N+ZNxIkvJBkiLg3ZCRJTdxXJksbdSd1fk/Im4ksmlwuQnYqEcr9SVlfmJLI1zKRKGhJSkwuIpxtbmndX5FQEhgh2SKWBDsxrnfmlZX5iEGoC3cLIALAgVkFkVKKVuad1fkTYkCBNEuJQJXvzS95IJBDT9BWLF5mSQZtCNMSZRt6MyzMECaZTRJlohImi7X95Jky0Q12JcTQTRkkGbTFbsaNW+ckhIIEzQVu5CQZMDSwsfgQkGYGmPwDD4EgQZga4hiILBmBpjcMF6FgQZ2CxpgvQePxECDKw7GmPxDH4iCwZ2DE0xDEQIM8QxNMQxECCMQsXih4oQIM7BY0x7DxZYEGaiNQ9S8R2QgsEYhYuwWLA0k4seJVmGLLpLBNgsXiPAaRpM8QxRpgGHwGksGeKDE0wFgxpEGeIWLxYWZNJIM8RWNLBYkEgzxRLia4hiSCQY4ixZtZit77CCQZWYrGtkGKJAgyA0x+AsCQSDOyDFGmPYMbCCQZYhY0xQYokEgysFjXBP3iwQgQZWQYr0NMF6Bh2JBIM8V6BivQ0cLE4iCQRiFi8e4KF/eSBBnYRrgLBCCGdkFl6GmK9AcEreTvz5EgGdl6CsaYoWKJBIM7BY1UE780rK/MnEkEgzAtwFixBIIsKxpKDjbmndX5EkgkEWAqw1DK/UlZX5skEggAsBCAADlHG3UndX5PyI0RoQABCAA4xyv1JWV+b8xAAAAAADlHG3VF3V+T8hAAADjHK/VFWV+b8+wAgAAAABzhhj1Rlkk+Tvbs+4AgAAAAqEM8uuMcYt83a/ZdyQAAAAACpwwx64yyipdLvbs+5IAABUIZ5dcY4xcup2v2XcAkAAAAAqpT9nj1wllFS6Xe3Z9wD9ydilIhMdz9cn6ZLTQ0ZjTZqSyXcabIUhpmpKWpDTIQXLIk0uCZCY1IslkvIakRkCaElk0UkFyLhcslk0uFyLsLv1LJZLuO5nkPIsiS7hkyMgyEiTTJhkzPJBkhINMmGTIyQskJBeTBv1IyFcSUu4XITKTS95ZAy48rERZSZZNSUmNO5KfuGjSNIpFIlFFk0h3t5Ad0cJ8L8O6vhvbtTqdl0lWrU08ZTnKkm5P1ZzC4O4V+8Gi/NI7TZ2Yv3bdNxVrek+XlOet5HduUqtVLfv5ToAdjv76juFvvBofzKBcH8LfeDRfmUfX6qYj+YvifX9AXvzr4nQSiGJ399R/C33g0P5lB9R/C33g0P5lD6qYj+YviX6vXvzr4nQNhWR6AXB3C33g0P5lB9R3C33g0P5lF+qeI/mL4mvq7e/OviefsRYs9BLg7hb7waH8yh/Udwr/m/ofzKJ9U8R/Mp+I+rl786+J56aE0eh1wbwo//Z/Q/mUH1GcKf5vaH8yifVLEfzKfiX6tXn/GviedxX7HZfixsWz7To9vntm26fSyqVKim6UFHJJK1zrVrsdezDBVYC+7FblqOHSpOExuEqwd52anLQrJkNFW9Av6o/BB+N0kOJNjTkJmTMGbQrM0shOKMkgzEXj3E4kaJBArF4v0DFk0kgiw8SsWGI0jSTiGKKxHiNJdJGKHZFYjxXoXSNJFkFkXivQMew0l0kWGVj2DHsNLJpJAvHsGL9BpLpICxdmGL9C6RpIsFi8X6BixpGkiw7F4sMRpLBGIYl4gojSIIxDE0w7DUC6SwZqPYai/Q0UUOxUhpM8GNQ7Fn0PAG00N64x2zbtUk6UqrqTi1ykoRc8X8cbfOfaxh6sRdps08aml3uD9GGw1WKvUWKONTSXa4PoOEPBzdN+0tLct31X9z9LVSlTgoZVakfW3lFP3X59j6jV+A2ySoW0G966lWtylWjCcb/BKL/SdngepWNmMus2vV1Uanytty/ju7D2fC7H5TYs+rrt63ytty+57uw8wcU8I7twhrlot0pRcZ3dGtB3hVXqn6+qfNfkOE5eh6O8Utp0+68F66VWK9po0tTSk1zjKL5/ljdfOedcGdDz3KqcrxXq7bmlqV8jzXaXJKMmxnqrTmipSp4rkjsjuPoeDeAt54zryWhUaGlpO1XU1E8Yv/FS/hS7fltyOyaPgJw/Ggo1963Cda328FCMb/wAVpv8ASfb8H7Tp9k4Z27btPFJQoQlNpfbTkryfzts5g7jl2zODs2KXiKdVbW+eToR6Lk2xmXWMNTVi6NdxqXMwp5Elzc/E888beFO8cJ0Jblpq61+3xfXUjHGdL+NHny7p/kPh3HsevK1GlqaFTT16aqUqsXCcJLlKLVmn8x5U33b47Tvev2uEso6TVVaEX6qMmk/0HWdo8ltZdVTdw+6mrk5n8jpm2OzdjJ66L+E3UVyo4w1zPjD8jjMROBrbsFkdY0s6Q6THEVmbOIsOxmCaTEDXAWBNJNJnYVjRwDAmkmkzxFY0wYsRpJpIsK3Y0xYWZNIgzsLFGln3AaWTSZ4oMS7fAVvgSCQRiKxpYViQIIsBdhCCQRYLFisvQkE0kYhiXiGLEDSZ4hYvFhYzBNJmFi7BYQTSZ2FiaYhiSCaTOzFY0xYmvUkEgzsJxNLITTRIMwZOJJrYTiZJBnYmxbVhEaMtEWAqwrGTIgAfmRojQgBqwEIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAfsTGnYhSLp1MMuiMsouPUr27rufok+0jUvUd0Z3HcslNAuQnYuVXPHojHGKj0q1+77lksjUmNSITC5ZLJopILihPDLpjLJNc1e3ddybmtQk0QXIUmNSLJZKuNSFKplj0xjZJcl59xZIslLUmGRFyoTxv0xd1bmvISJKyDIi4CRJdwuQVKeVulKytyXn3LIkd16juvUzuFxIk0uvULr1JjPG/JO6tz93cSYkSVcLk3BMqZpMpMdyc725JWVuQ0zSZpGi5WKTITKjLH3J3VufuLJpFIqJmmaRNJmkVcZCZd8rckrK3I2j6JHf3Bf3KbV+LQOcRwnBf3KbX+LQObR69g/ZrfurwPQ8N+xo6l4ACA/Nq9y27blGW4a/TaVTuoutVjDK3na7Vz71VKhTU4R+htUqWfqA436puG/wDOHbf9bp/1i+qbhv8Azh23/W6f9Z8/pFn8670Fet/mXecogONXE/Df+cO2f63T/rF9U/DX+cO2f63T/rNfSbP513o2r1v8y7zk0M4xcT8Nf5w7Z/rdP+s5ChqKGqox1Gmr061KavGdOSlGS7NeZui7buOKKk+03RcorcUtM1QAgPofZHW/jP8AvLa/wtT9UTqlo7X8ZlfRbZ+FqfqidVNHme0f7xr7PBHQ89X69X2eCM2uwnFGlibHAwcPBm4i5mtiSMkGfzCZpZegYozBNJmFjTFCw9CaSaSLBYvAMew0jSTbuFu5WL9Ax7DSNJNu4Yl4hi/QukuknEMUXiwxYVI0kYr0HivQrFjx7F0F0EWQYovHsGPYaBoIxQ8SsOw8H6MukaSMQwReAYsaRoIwQYIuzCzGkaCMEPArFhixpLpJxQYovFhgxpGgiyA0wY1BF0oukyxfqNR7Gqj2Go9jWkqpMsX6HK8L7t9T/EGh3jFyjpqqlOMfNwfKSXezZ+DEMT6WqqrVauUcU5XYfazXXYuU3aNzpaa61vPU+g1+j3TSUtfoNRCvQrRyhODumv6+xueaNh4o3/hubls+41KMJO8qbtKnJ+ri+V+/mc9qvFnjTVUHRjq9Pp7qznSopS/K72+Y9As7W4aq3N6hqrmUNdm89Sw23OEdmcRRUq+VKGuxyvifd+LvE+k27h+rsNKvGWt1+MXBPnCldNyfpe1l8X6HRmJ+rUVtRrK89Tq69StWqPKdSpJylJ+rb5syxOn5tmFeaYj11ShLcl0HQs8zWvOsV9IqUJKEuZfM9CeHHFGj4h4d01GNeP7d0VKFHUUm+rpVlO3o0r39bo+rPLGh1ut2zUw1m3aurpq8PtalOTi125e7sfXUvF7jWlQVKWp0tWSVvaT06y/RZfoOz5ftRaosq3iqXqSiVvn+53fKduLFvD02sdS9VKiVvTjtUP4HdW+77t/Dm2Vt03KsoU6S6Y36qkvdGK97Z5e1+pqbjrtRr6/981NWdaf8aTu/0s5Det+3riHULU7xuFXUzjfFSdox/ixXJfMjjXE4HO83ea10qhRRTw59/Kzq+020Lz65TTbp026JieLb5X5IxcBYP0NsewsTgdJ1V0mNhW7G2PYWK9CQTSZWFZehrghYGdJnSZ2XoKyNcBYMmkmkzsvULdy8X6CxfoTSNJFgsXi/QMX6DSTSZ27CxNMGGLJpJoM8QxReLDGXoNLJpM8ULHsaYsTTRNJNJFhYo0aFYmkmgjFCwRp8wrdiaWTSZ4IMexpZisyQTSRj2Fj2NLMH8BpGhmeKFgjS3YVl6EdJNDM8BOBr5fwRciaSaTLETi/Q1shOJl0kgxcRNG0lfziuStyJcSNGYMmhNWLcQTtfkndW5mYMtGTRDRq0S0YaMNGQFSVuYm725JWVuRloy0TYXkUKxkwFiWi4SxT6U7q3P3CsIEEgNoRkyADlLK3SlZW5LzEAAAOMsb9MXdW5ryAEAAAAAOUsrdMVZW5Lz7gCAAAABwnhl0xlkmuavbuu4gAAAAACpzzx6IxxilyVr933JAAAKhPDLojLKLj1K9u67gEgAAAAFTnnj0RjjFR6Va/d9wDVMabM1IakfSTcmikNSM7juaksmiYEXHcslku4JkKQ8kWSyXkNSIuBZLJakO/czuO4kF3GZ3YXLJTQLkZBkWRJd2PJkZBkhIkvJhkTkGQkslZDyIuO4kSUpdxp9yAuWSyXcSZOQJmpKmWmVFmadi4sqZo0T8hpkJ2KTNJm0zSP6i0Zw5FJm0bRSNFyM4miZ9EfVHf/AAX9ym1/i0Dm0cJwX9ym1fi0Dm0ev4P2a37q8D0LDfsaOpeAHXPjF+99r/j1f1ROxjrnxi/e+1/x6v6on4c+/d9zs8UfnzT2Svs8UdZgkNIZ5qdNFYLDApRWZ3vwN9yW2fgf6WdEne/A33JbZ+B/pZ2fZX2qv3fNHPbP/t6urzRzyAEB3w7ejrnxl/eW2fhan6kdWfOdqeMivots/C1P1I6sszzXaL9419ngjo+dr9dq7PBE2PqNg8ON74k22G6aLU6GnSnKUUqs5qXJ290Wv0nzGLO8fDCGPBmibX20qr/+JJf0GMiwFnMMS7V7gqW93WvmZyfBWsbiHbu8In4o+F+s1xN/z/bPztT+wH1meJ/+f7X+dqf2DuQZ276r5fzPvOzfV3A8z7zpr6zPE/8Az7a/ztT+wC8GOJ3/AMv2v87U/sHco0X6rZfzPvNLZzA8z7zpr6zHE/v121/nan9gX1mOJ/8An21/nan9g7nEPqtl/M+80tm8BzPvOmvrMcUf8/2v87U/sB9Zjij/AJ/tf52p/YO5wH1Wy7mfeaWzWA5n3nl+vQnp69ShOzlTm4NrybTsRi/Q/ducV/dLV/h5/SZ+bFHnFdGmppHn9dCpqaRliy4Up1Jxp04uUpOyjFXbfZH0HCnBu48V6t09MvZaam17bUSV4w7L1l2/Udz8O8HbFwzSS2/SKVe1paiolKpL5/cuysjmsryC/mS9Z+GjnfL1Ll8DmMsyG/mK1/ho53y9SOnNs8NuMNzipw2qWng/4Wpkqf8A3X1foOeoeCm+SV9Ru2hg/wDQU5frSO4EUdts7KYC2vtzU+lx4Qdss7LYGhfbmrrceEHUc/BLcErw33Tt96LX9J+LV+DXE9BZabUaHUr0jUlGX/eVv0ndBSPrVsvl1ahUtdTfnJ96tmMurUKlrqb85PN+78J8Q7Fd7ptNejBf4RJSh/KjdfpOKxPUkoqScZJNNWaa8z4birws2ndadTV7LCOh1tslCPKjUfo1/B+K5djg8fslXaTrwlWrofHsfB/A4THbJV26XXhKtXQ+PY+D+B0pj8B4/A/Xrdu1e26qpotdQnRr0njOE1zX/wB+phh3OoVW3S9NSho6jVbdLdNS3o/ZsOzVd+3fTbRRrQpT1MnFTkm0rJv3fA+4+sjuv370n5uR894eRtxntf4WX0JHf6O4bO5PhMww9VzEUy1VHFrkR3HZzJcHmGHquYimWqo4tciOofrI7r9+9J+bkH1kd1+/ek/NyO3wOwfVfLPyPvfzOxLZbLPyP/c/meX9fopbfr9ToZTjKWmrTpOS8m4ytf8AQYYv1OV4ij+6Hc3f/llf6bOPUTzO9bVFyqlcE2eYXraouVUrgmzPHuczwnwvX4r3R7ZptVToTjSlVymm1ZNK3L4nF4H3Pg9G3FlT8TqfSgfqyzDUYnGW7NxfZbhn68qw1vFYy3ZuKaanDP1rwP3V/wD53pPzch/WQ3X796T83I7gQHob2Xyz8j738z0tbJ5V+R/7n8zp2p4KbpSpzqPe9I1CLlZU5e5HXSgz1Fq/3rW/By/UeYsex1baPK8NlztrDqJmd7fCDqe1GUYXLHaWFpjVM72+Ec/WZ4BiaYs0oaWvqa0NPp6UqlWpJRhCCvKTfkkjraobcI6qqJcIwxOQ2vh3et6nhte2ajU87OUIPFfGXkvnZ2hwh4SaTSwhr+J0tRXaTjpU/scP4zX2z7eXxOxaNCjpqUaGnowpU4K0YQioxivRJeR2rAbLXb1KuYp6Vzcv9vid3yvYu9iaVdxlWhPkX4u3kXx6UdJaTwd4u1CvW/aWl7Va93/3FI/VLwT4kUbx3LbXL0c6iX5cTudAc5TsvgEoab7Ts1GxeVpQ1U+35QdE6vwi4y00HOnpdPqbe6jXV/8AvWPmNx2Pd9olhum26nStuydWm4p/B+T+Y9Poz1Om0+soz02roU61KorShUipRku6Z+O/sph6l9zW0+nevI/Jitg8HcpnDXKqX0w15P4nlezFZncPGPhFpa9Kev4Vj7KtG8paSUuif8Rv7V9ny+B1LW01fTVZ0NRSlTq024zhNNSi15pp+R1LH5Zfy+vReXU+RnQM1yXFZRc9XiFufBrg+p+XE/PZG+g0FXctfptu07iquqrQowydllKSSu/S7Ix7HKcJxX1VbN/1hp/5yJ+OzbVdyml8G0fgw9lXb1FFXBtLvZ9H9ZTjD/Kbf+fl/ZF9ZPjH3VNv/Py/sne5SO/PZjAdPf8A2PYVsFlD/N/u/sdDfWT4y/x9v/Py/snxW6bXqNo3HUbZq8HW0tR0p4O8ck+dmerjoLXcMa3izxI3Ta9JeEP25UnWq2uqUFLm/wChL3s4XOMjs4WmhYVN1VOOJ1nafZLDZfbsrL6anXXVphueQ+P2zZtz3rVR0W1aGrqa0ueNON7L1b8ku7Pudv8AA3ijU0lU12s0Wjb/AMHKTnJfHFW/SdxcPcO7Vwzt8Nu2rTRpwSWc2uupL/Gk/e//ALRyZ+7CbL2KKU8S3VVzLcvmzm8r9HeDt21VmFTrr5k4pXm+uV1HTE/ALdFG9PiHSyl6SoyS/LdnzW9+FHGeywlWlt0dbSj5z0kvaW/7NlL9B6OQH6L2zOBuUxQnS+hz4yclifR9k9+iLSqofOm38HPkeQpU5Rk4yi007NNc0LHsekuM/DjZOLqUq/s46TcEnhqacftn6TX8Jd/Puef952XX7DuNba9zoOlqKLs15pr3ST96fqdRzLJ72W1fa30vg/nzM8v2h2WxWz9adz7Vt8Kl4Ncj/wAT4nGY9j9e0bVX3ndNLtOlnThW1dWNGEqjainJ2V7Ju3zGWKOd4Fivqz2X8eo/SRx9i2rl2mirg2l8ThMDYpv4q3ar4VVJPqbSPpfrCcX/AHy2f89V/wDLD6wfGH3y2b89V/8ALO+ho739WsBzPvPdF6Osjf8ADV/uZ0J9YPjD75bN+eq/+WfA7ztOo2PddVtGrlTnW0lV0pyptuLa9G0nb5j1yeX/ABAjfjben/0yp+s4PPcpw2As012U5bjj0HS9uNlcuyHCWr2DTTqqhy53Q2fM49gcUa4H7dj2PW8Qbtptn2+GVbUzUFfyivfJ9krt/A61TbddSpp4s82tWK79ym1bU1NpJLlb4I5bg/w24g42oajVbVLS0aGnkoOpqZyjGcrXajjF3aVr/FH0P+5+4x++Wy/nqv8A5Z3fw9sWi4b2fTbLt8bUtNDHJrnOXnKT7t3ZyJ3ixs1habVKvS6uXee75d6McqpwtCxuqq7H2mqoU8y6Fw6eJ5//ANz7xj98tl/PVf8Ayw/3PnGP3z2X89V/8s9AI+Y8ROM6PBewT1cHGWu1F6WjpvneducmvSPm/mXvF7Icuw9t3bkpLpPrjfR/s1l2HrxWIVSooUt6n/kvgudnm/ifhrUcK7tU2bWa7R6mvSinUemlKUYN/wAFuUVztZ/OcRgj9OorVtVXqarU1JVK1abnUnJ3cpN3bb9bn69k2Lc+ItypbVtOllX1FZ8kvKK98pP3Jep0eqn1lyLVPF7lxZ4PctLFYl0YOhxU4pp4ve9y6X5nF4H0Ox+HfGPEUY1dr2DUyoz5xrVUqVNr1Up2T+a53lwV4QcP8MQp6vcqVPctySTdSpG9Om/SEX6f4z5/DyPvkdlwezDqp14qqOhce89YyL0T13qFeza46J/gpie2pyp6En1nn7R/J64srRUtZue2ae/nFTnOS+No2/Sfu/3OO5uP3T6XL0/a8rflud6gvM5WnZ7AJQ6W+1nd7Xox2coUVWqquuuryaPPur+TtxVSg5aPd9srtfwZSnBv/utHyu9+FXHmw03X1ewVq1GPnU0zVZLu1G7S7tI9XCPhe2awda+w3S+ufE/HjPRNkeIpfqHXbfQ5Xamm33o8SuLi2mmmuTTJauer+MfC/hXjOM62s0n7V1zXLWadKM2/9JeU/n5+jR5x4z4J3rgjc3t+60cqc23p9RBfY60fVP3P1XmvyM6vmOTX8v8AtPfTzrz5jyHarYPMdmPvq/vLLca1yc2pfw/FdMnzjRLRq1clr3M4Zo6K1Bi1Ylr3mjRLRhow0ZtENWNWrESRhmIMwHYRmDDQAAEMiE0UIgJAbQjJkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAClIuEc8uuMcYt83a/ZdzILlksl3HchNjUiyJLyLksMeqMrxT6X5dn3MVIdyyU0uFzO47lksmsI5X6oqyb5vz7ISZCkCkWRJpkxqRmpDuJLJrJY49UXdX5PyJyRF0FyyJNLjisr9SVlfm/MzuFxJZLuFyLsLsslku5Uljbqi7q/J+RnkwTEiS7hcm/cdyplkuHVfqSsr82CkiEwTLJSr8/MFLuRfmNM1JZNWsbc07q/J+RUWZJlp+4qZuTQuPP3pWV+ZkmUmbTNJmsfJFJkRZSfobTPpSaRNLWS59zKL5cy0z6I+tJ6B4L+5TavxaBziOD4K+5PavxaBziPYcH7Nb91eB6Hh/wBjR1LwA658Yv7xtX8er+qB2Mdc+Mbtp9r/AI9X9UD8Gffu+52eKPz5p7JX2eKOtLgSnzHc81R01FATcLlk0Ud7cDfcltn4H+lnRCO9+BvuS2z8D/SztGyvtVfu+aOeyD9vV1eaOfQAgO+HbkddeMa/3ltv4Wp+pHV9u52l4w/vLbfwtT9SOr7Hm+0K/wDIV9ngjpOdL9dq7PBE2O9PDuGHBu2x/wBGo/y1JM6NxZ3xwLDDhLbI2/wN/wArbP27KU/rdb/0+aP17OU/rNT/ANPmjnRiGd9O6IBo668U973Xa9XoKW27jX0ynTnKapTccuate3znw/1XcUf5wa789I4DGbRWcFfqsVUNtdXNJw2Kzy1hL1Vmqlto7+EdR8A8Rb9r+KtHpdbu+qr0ZqrlCpUbi7U5NXXxR24clluYUZlad2hNJON/Z8zksvx1OPtO7Qohxv7PmUAAcgcgjzbuUf8AhHVcv8PP6TK2ra9Ru+46fbNKvsuoqKCb8l6t9krv5i9yj/wjquX+Gn9JnM8D73tnDu8vc9zoV6ijSlCn7KKbjJ2582vddfOeSWbVu5iVTdcUt730TvPLbNqi5iFTdcUzvfQd07LtGi2LbaO2aCnjSpRtf3zl75Puz9p8npvE/hGtb2mrrUL/AOUoS/8ADc5PT8ZcK6q3st+0av8A5Sph9Kx6hYxuCdKotXKYXBJo9KsYzBulUWq6YXJKOZRGp1el0cPa6vU0qMP8apNRX5WcFxNxfodl2WpuGj1NDU1pNU6EYVFJOb97s/JJN/MdJ7huGu3XUy1m46upXqzd3Kcr/MvRdkcdmue28vat0LVU9/Hcj8eZ55by9qihaqn07kd/Ut/2KvP2dDetBUm3bGGpg3f4JnILmjzTbsdheFfEusjuP1PaqtOrp60JSoKTv7OUVey9E0ny9V8T8mXbS/Sr9Ni9RGrcmnyn5su2kWKv02btEatyafKdqDQho7YdsR8L4q8NU9x2r+7unh/vnQpZ2X29Jvn+Ru/wudPYs9L6rT09Xpa2kqpShWpypyT8mmrM83zpzhOUJKzi2n8ToO1WDptYim/Svxrf1qN/czoW1WEptYim/Qvxrf1qN/xXcc34fRa4x2z8JL6EjvtHRHACf1YbZ+El9CR3ujltklGEr97yRzGyO7CV+95IYAB2s7ajzlxDH90G5/jlb6bOPxOU4gj/AMPbly/5ZW+mz8GJ41fX3tXW/E8XxC++q634mWJ9v4QK3FVT8TqfSgfG4n23hHG3FNT8UqfSgfuyZfr9r3kfvyRf+Qs+8juZACA9XZ7EjLV/vWt+Dl+o8zpeiPTGq/etb8HL9R5rxR0na9TVZ/q8jom2ymqx/V/xM8Wdz+GnBdPZtFDetwpJ6/VQUoKS/vNN+S7Sfv8Ayep8F4fbDHfeI6EK1NS0+l/3xWT8mk1aPzu3zXO9kY2Yy2mtvGXFw3U9fK/l2l2PymmtvH3VMOKevlfku0AAy1WqoaLTVdXqqip0aMHOcn5KKV2d0qapUs9FlUpt8DZAdI8UeIm977XqUtDqKui0PlGnTlaUl6ykufP08vj5nyzr6h1PautUz/xsnf8AKdWv7UWbdbptUOpc8x5M6bittsPZuaLFt1pcsx3bn5HplAdF8MeIe+bBXp09TqKmt0N7To1ZZNL1jJ8016eX613dotZp9w0lHXaSop0a8FUhJe9M5TLs0s5jS3Rua4pnYcmzzD5zQ3a3VLin49KN0df+KXBVLdNDPiHb6KWt0scqyiv79SXm/jFfoVvQ7AQNJpppNPk0foxmEt42y7Nzg/g+c5DMcvs5nhqsNeW5/B8jXUeWbI5ThWK+qjZ/+sNP/ORP2ca7EuH+JNZt9ONqLl7Wj+DlzS+bmvmPzcKxtxRs7/6fp/5yJ5jTZqsYlW6+Kqj4nh1vDV4XH02bn4qa0n2M9IlIkpHqbP6GQHE7Jw9pdl1W5a2nP2lfc9VLUVJuNml/Bh8Fz/KzljjOId/2/hrbKm6bjO0IdMIL7apN+UV35f0nxuq3T97c/hlzzHyxCsW4xN+EqJcvk3Q33HKAdB714pcWbtWctPrXt9HyjS0/Jpd5ebf5Pgfi0HiDxjt9WNSnv2prKLu46iXtYy7PK5wFe02FVcKltc+75nT6/SDl1F3RTRW6eeF4N/I9FoD5PgLjzTcYaWdGtThQ3GgsqtKL6ZR/x4393qvd86PrDnLF+3ibau2nKZ3fA42xmFinEYerVTV/neM+F8V+DqfEOyS3TSUb7ht8HOLS51KS5yh3t5rvde8+6DzVmfPFYejF2qrNzgxmGX2c0wteEvr7NSjqfI10p7zyTh2Oc4Gi1xlsr/6bS+kjTjXZI7DxRuG20oY0oVc6S9yhJKUV8ydvmDgiNuMNm/HaX0kea2rNVnFU26uKqS7mfzvhcNXhM0osXPxU3En1qqD0wNCGj04/p1AeYuP0/q03rl/yyp+s9Onmbj5fuz3n8bqfrOs7TqbFHX5Hm3pOU5fY9/8A4s+bt2O+PBzgpbLtf1Q6+jbW7hBeyUlzp0PNfPLk/hbude+GPBn1Vb4q2rpN7doWqle65VJfwafz259k/VHohJKySsl5H5Nnsul/S7i4fh+fkcb6ONnNdf6XxC3KVQung6uzgumeZFAAHbWezIx1er0236WtrtZWjSoUIOpUnJ8oxSu2eYuOuLNVxlv1Xc6mUNPD7HpaTf2lNPl87838eyPu/GnjZ6qs+ENsrfYqMlLWzi/tprmqfwXm+9vQ6nxOk5/mHr6/o1t/Zp49L/t4nhnpF2l/SF/9F4ar7u2/tP8ANVzdVPj1IzxZ6S8KuCqPCnD9PU6iiv7pa+Eauok1zhF840+1l597+iPPmz1tFpd20eq3GjOrpaNeFStCCTlOCkm0r2XO1jvnS+N3A+ot7Weu01/8rp72/kOR8sg+jWblV6/Uk1uU/Fny9G9WU4LE3MbmF2mmtbqFU448Xv3cyXWz78aPl9L4mcCay3suJdLG/wDlcqX00jkp8V8Nw0dbcIb3oa1GhTlVm6OohN4xV3ZJ82dwWJs1qaa0+1HulnNsBfp1Wr9FSXNUn4M5WpUp0YOpVqRhCPOUpOyXznFvi3hWNT2UuJtpU/8AFetp3/Jkeb+M+Nt54y3GpqNbXnDSKX2DSxk/Z04+7l75er/osj5txZ1q/tJpras0SudvieWZh6WlbvujA4fVQuWpxPTCW7tfceyKNajqKca2nqwq05c1KEk0/nRZ5a4B4y3HhDfdPXpaip+0atSMdVQyeE4N2creWS80+1vK56lOXy7MacxtupKGuKO/bIbV2dqsNVcpo0V0NKqmZ48Gnu3OHycg0cDxxwnpOM+HdTsupSjUkvaaeq1zpVV9rL4e59mznkM/bct03qHbrUpnacVhbOOsV4bEU6qK001zpnifUaerpa9TT16bhUpTcJxfnGSdmvymajf3r15n2ni9t8NB4h7vTpwUY1akK6svNzhGUn/KbPi2jyrE2fUXarXM2u5n8XZrgXl2NvYOpy7dVVPXpbU/AzkiGjVoiSPytHGNGTQpRtbmndX5FtENGGj5tGbViWXIlowYYoq9+pKyvzEA0RmWhAAGTISjjbmndX5e4looQDJHGOV+pKyvzfmJgZMgAAAA5Rxt1Rd1fk/IQAAAAAOMcr9UVZX5vz7CAAAAAAHOGGPVGWST5O9uz7iAAAKhDPLrjHGLfN2v2XckAAAAAAqcMMeuMsoqXS727PuSAAAAAAAAAAXAAB3YZCASJKyDJEgWSyXcLkBcSJNLhfuRkwyLIkvIeRnkPISWS8gyIyDJepZEmikNMzTQ0xILTGmQm/UE+5ZLJopdxqRmmNMslkd+YJk5Amak2maJmiZim7ouL7mkzSNU7FJmUWWnaxtM+iZsmUn7jOL9w7n0TN0s2TsWmZRd0XFn0TPrSz0LwT9ye1fi0DnEcHwT9yW1fi0DnEexYL2a37q8D0TDfsaOpeAHXHjJ/eNq/j1v1QOxzrfxl/e+1fx636oH4c+/d1zs8UfDNfY6+zxR1kNCTGmeZo6YikAJgaRpFI734G+5LbPwP9LOh0d8cDfcltn4H+lnadlfaq/d80c/kH7erq80c8gBAd8O3I698X1fR7b+FqfqR1koo7N8Xv3ptv4Sp+pHWbdjzjaD94V9ngjpec+2VdnghYr0O+uD44cMbWv+i03+VXOhuZ39w1D2fD21wa5rR0b/ABwRyOyi+/uPo8z92zq+9rfR5nJDEM7wdvR1V4vSUt40UP8AF01/yzf9R8Jj2PtfFmeXElCN/tdHBf8AfmfF3PMs5erH3X0nQM034y4+k+l8N1+7HQ/Cr/NyO6zpbw4f7sND8Kv83I7pO17Lex1e8/BHZtnPZavefgigADsp2JHnXcf+MNV+Gn9Jn5z9e4/8Yar8NP6TPz2R5BcX231nlda+0yLMdmc5w9wnu/ElS2h06jRi7Tr1OUI/1vsjsPavCvYdGlPcqlXXVPem/Zw/Iuf6TksFk2Kxy1W6Yp53uXzfYcjg8oxWNWqimKed7kdQ4s0paatWdqVGc3/oxbPQGk2HZdDFR0m06Slb3xoxv+XzP3pJJJKyXoc5b2Tq/ju9y/uc3b2Vb/Hd7l/c6B0nC3EOtaWm2XWST8pOk4x/K7I7A4D4A1+y6+O87vOnCrTjKNKjB5NNqzcmuXlfyv5n3xSOUwOzmGwlxXW3U1w5F/nacrgtnsPhbiutuprhzf52iGhDR2I7EhnnTcIr9v6n8NP6TPRZ533Bf8Ian8NP6TOo7WKaLXW/I6ltWpotdb8jleAkvqv238JL6DO9EdG8Br9122/hJfQZ3kj9GyqjC1+95I/VsoowtfveSGAAdpO1o+B13hLp9drtRrXvdSD1FWdVxVBO2Tbt9t3MPrN6X7/Vf9XX9o7GQziKsiy+pup2976X8zinkGXVPU7W99L+Z1z9ZrS/f6r/AKuv7RzPCvh9R4X3OW5U90nqHKlKlg6Sj5tO97v0PrgPpZyXA2Liu27cVLhvfzPtZyPAYe4rtu3FS4b38xoAQHJs5hGWq/e1b8HL9R5vsj0hqv3tV/By/UeccTpm1imq1/V5HR9s1NVn+r/idqeD+gjT2vXbi49VeuqSfaEb/rl+g7CR8p4ZU1T4Q0skv75Uqyffra/oPq0c/lNtWsDapXMn37/M7XkdpWcus0r8qffv8wPkPE6O6ajYIbfteh1Oplqa0VVVClKbUI8+aS9cfyH14H6cXY+k2arMxqUSfvxmG+mYeuxqjUolHnr6l+Jf83dz/wBUqf1B9S/Ev+bu5/6pU/qPQyA639VrP8x9yOqrYjD/AM19yPPP1LcTf5u7n/qdT+o7W8Lobrpthq7dumg1Omenrv2Sr0pQvCST5XXrf8p9kgP14DJKMBe9dRW3uiDlcp2Zt5TiPpFu43uaiFvkaGJDOcO1o6r8adAlqNs3KK5zhOhJ/Bpr6Uj4bhZW4n2j8f0/85E7O8ZKSlsGjqtc46xRv8YS/qOs+F1+6baPx7T/AM5E6Bm1tUZpK5XS/A8k2isq1n8rldD8D0YUiSkd6Z7EgOmPGHeams3+ns8Z/YdBTTcV76k1dt/9nH9J3OeduNarr8W7tUbbtq6kP5Lx/oOvbR3XRhVQv4n8Fv8AkdM28xNVrLqbNP8AHUk+pS/GDgcV6hj6Mu3xFbudFg8fg5XhDeavD/EWi3KE7QjUUKy9zpy5SX5OfxSPSZ5Wt3PTex1pajZdv1Enk6ulpTb9W4Jnbdmbri5afDc/n5HqXo5xNTpv4VvcoqXbKfgj94AB2lnqKOmPG3RRp7/otbFJftjS4N+rhJ8/ySR8nwSv3X7Pz/5bS+kj7/x0heGzVLeT1Ef5v+o+C4JS+q/Z/wAcpfSR0LMaFRmjj81L74Z4bn9lWtqGly10PvVL8WekxoQ0d5PeUB0HxdwZxTuXF+5VtHsWsqUtRq5ezqKk8Gm+Ty8rdzvwF5nH5hgKMwoporbUOdxwmf7P2dobNFm/W6VS53R1cpxHCXDWl4U2OhtOntKcVnWqJf3yo/tpf0LskcyAH67dum1QqKFCRzuFw9vCWqbFlRTSkkuhDPlPEbjKnwhscp0Jxe4au9PSxfufvm16Rv8AlsfR6/XabbNFX3DWVVToaeDqVJP3JI80cYcS6vizfK266nKNN9FCk3/e6a8o/H3vu2cRnOYfQ7Omh/bq4dHT8jqe2u0n6DwXqrD++uSqehctXkunqZwlSdStUlVq1HOc25SlJ3cm/NtkWLaFY6C0fzs5blk2F8SrH79m2LdeIdbHb9n0NTU15c2o8lFesn5Jd2Wmh1tU0qWzdqzcv1q1apdVT3JJS2+hHHWQsUd1cPeBGhpRhX4l3KpXqWu9PpuiCfo5vm/mSPvNs4G4Q2hJaHh7RRa5Z1KftJ/yp3f6TmrGz+JurVcap+L/AM7T0LLfRhm2MpVeJqptJ8j31dy3d7k8tQo1KssaVOU36RV2chpOGOJNwljotg3Cv3hpptflsesKVKlQh7OjShTiv4MYpL8iLXmftp2ap/iufD+52Wz6IrU/fYpvqojxqfgdBcJeCnEmv11DVcQUYbfoqc4znCc1KrUSf2qir2v5c7fBnfwxHM4LAWcBS6bXLxbPRtnNmMDszZqtYOW6odTqctxw4Qt0vguUaGJDP2HZkeavHVf+kDUP/o1H6J11JHY3jov/AEgaj8Wo/ROu2eZZmv1y77zP492x/f8AjP8A2V+JkRJGjViZI41o6vUjJohlvyJZ8mfJmcvIllsgwzJA15g/MF5kZhgxFEmDAAAAEsRRLIyMAACEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAKhPDLojLKLj1K9u67kgAAAAAFTnnj0RjjFLkrX7vuSAAAAADhPDLpjLJNc1e3ddxAAAAAADlLK3TFWVuS8+4gAABxljfpi7q3NeQgAAAAAaLcsrdKVlbkiEUaRpAAAgCoSxvyTurc/cCEikAT7wQPzBGzZbd7ckrK3ItGZpE0jaKRpF29yd1bmZotG0bpNIlERL9x9EfSk0iWne3JeRnBlo+iPqj0NwT9yW1fi0DnEcFwT9yW1fi0DnUeyYL2a37q8D0XDfsaOpeAHW/jL+99q/j1v1QOyDrbxm/e+1fx636oH4c//AHdc7PFHwzX2Ovs8UdYplJkIaZ5mjpfE0TGQmUn6lNIpHfHA33JbZ+B/pZ0Md8cDfcltn4H+lnatlPaa/d80dg2f/b1dXmjn0AIDvh25HX3i9+89t/CVP1I6xfqdm+L3LR7b+FqfqR1n5nnG0H7wr7PBHTM49sq7PBDPQ+3UXp9BptO1zpUYQfzRSOiOHduluu+aLQRjkqtaOa/0Fzl+hM7/AEc1spbem7dfDcvGfI5XZ224uXOpf58AGIZ287OjpzxQqZ8V1I/5OhTj+i/9J8mkc5xvqlrOK9yqqV1Gr7L+QlH+g4RHluYVq5i7tS/M/E88xtWvE3KlzvxPpvDj7sND8Kv83I7pOlvDj7sND8Kv83I7pO47L+x1e8/BHa9nPZavefgigADsh2FHnjcf+MNV+Gn9JnL8GcNS4l3eOnqXjpaK9pXkuTx90V3b/pOI3HluGqf/APWn9JnaXhRoqdHYa2tS+yamu03/AKMVZL8rl+U83yrB043HK3X+FS32f3OgZZhacXjFRXwUt9h9lo9JptBpqek0dCFGjSWMIRVkkaggPSUlSoXA9DpSpSSBCqVadGDqVakYRXnKTskfLcecW1eG9JSoaHH9uaq+EpK6pxVryt737l8/odTazcNfuNV1tfrK2om/4VSblb8vkcFmWfWsBc9TTTqqXHkSOHzDPLeBueqpp1VLjyJHdmq4w4Y0eXtt70rx81Tn7R/kjc/DovEDZtz3fTbRttOtXlqJNOq44RilFv3835eiOmT6Lw+pyqcX6DFfaupJ9kqcjirG0WKxN+i0qUk6kud73/nIcZZ2hxOIv0WqaUk2lzvj/nId1jQho7sd2QzzzuH7/wBT+Gn9JnoY89a9f7/1P4af0mdS2q/Da7fI6ptV+C11vyOW4EX7rdt/CS+gzvBHSHAn3W7d+El9Bnd6P07L+y1e95I/Vsr7LX73khgAHZztKGhnn7fv+Pdx/G6302fhOo17U6KnT6rh/q//ACdRr2s0Vuj1PD/V/wDk9IAebz7Lwq+6af4pP6UT74PaT6Vfps+qjU4nV/Y/Tg9p/pd+ix6qNTidX9jt9ACA7OztyMtV+9qv8SX6jzrY9Far97Vf4kv1HnY6btX+K1/V5HSdsfxWf6vI7o8NZ5cH6ON/tJ1Y/wDxG/6T6lHwnhLrI1dk1Whcrz0+oyt6RlFW/TGR92jsGVVq5grTXMl3bjteS3Fdy+zUvypd27yA/FuW9bXs8actz1tPTqq2oOf8K3n+s/afE+K+gnqeH6Otgv3pXTl/FkrX/LifTH3q8Ph6rttS0p+fwP05jiLmEwly/aUulTD+PwOb+rfhP7+6b8r/AKg+rjhP7+6b8r/qOiAOpfWfEfkp+PzOkfXTF/y6fj8zvj6ueEl577pvyv8AqD6ueEvv7pvyv+o6GaEZe02I/JT8fmX67Yz+XT8fmd9/Vzwj9/tN+V/1B9XXCP3+035X/UdBgPrNiPyU/H5l+vGNX/x0/H5nZvifxJsW8bBQ0u2bnR1FWOshUcYN3UVCav8AlaPguF/um2j8e0/85E445Lhhfum2n8e0/wDOROLvYuvHYum9WocrgcFicyuZtmFGJupJzSt3Qz0UUiSkeiM9zQHnfjOj7HizdoNWvq6k/wCU7/0nog6c8XtkqaTe6e9Qh9h10FGTXuqRVrP4xt+RnX9orNVeFVdP8L+D3HTdusLVey+m7SvwVJvqe7xg+AaFYoTOjnkMEnprZaD02z6DTSjZ0tNSg16Wikef+Edlqb9xFotuhC8JVFOq/cqcXeV/m5fFo9GnbNmrLSuXXwcL5+R6j6OsLVTTfxLW5xSuyW/FDAAOzs9PR1X451OjZqSfm9RJ/wDwz4Pgn7rtn/HKX0kfVeNWtjV3/R6KLv8AtfS5S7OUny/JFHyvBX3X7P8AjtL6SOiZhUq8zbX5qfhB4fn11Xtp3UuSuhdypXij0kNCGju57ugBeYHUnEvi7xHs2/a/a9NottnS0teVKDqU6jk0n77TS/QfkxmMtYKlV3eDOMzfO8Jkdqm7i20qnChTv4nboHzfAnF9LjDZVrJxp09ZRl7PU0oXtGXuavzxa8vnXuPpD62rtF+hXKHKZyWCxdnH2KMTYc0VKU/8+JFehR1NGpptRTjUpVYuE4SV1KLVmmec+PuEKvCO9z0sYyloq96mlqP3w98W/WPk/mfvPSBwXGnC2m4t2OrttXGFeP2TTVX/AAKiXL5n5Pt8Djc2wCx1n7P4lw+Xadd2w2cpz/Av1a++o30vn56e3xjpPMrSFij9Ot0ep2/V1dDrKMqVehN06kJecZLzR+c6A004Z/OdVNVFTpqUNH6dq2vVbzuWm2rQwyr6qoqcE3yTfvfZeb+B6Y4U4T2rhHbIbft1JZtJ16zXXWn6t/qXkjqPwP22nquKNRr6kbvRaVun2nNqN/5OX5TvU7bs/hKabTxFS3vcuhHt/oxyWzbwdWaXKZrqbVL5qVucczbmehIBoRxHFfEVDhXYdTvVeHtHRSVOne2c27Rj+Xz7XOfuV026HXVwR6jiMRawlmrEXnFNKbb5kt7OZbSV27JeZw+u4x4U2ybhruIdvpTXnD28XJf9lO55y3/jDiPiavOru251akJO6oRk40odlBcvn8/VnBs6ve2j3xZo7W/L+55Fj/SzpqdOAw8rnrfH+lcP9x6D3fxt4M0FKf8Ac+rqNyrLlGFKlKEW+8ppWXdJn3tGftaUKtrZxUrel0ePoxlOahBXlJpJerPYFCDp0adOXnGKi/mR+zKMwvY+q47sQoiO07JsDtRj9prmJqxipSo0QqVCU6p4tt8FymiGJDOaPS0ebPHT7vq/4tR+ideXs3yXNW5nYnjp931f8Wo/ROu5eZ5nmftlzrfifx/th+/sZ/7K/EyfmSypEs41nV6jJ+ZMne3JKytyLl5kM+TPkyGQaMzaMHzJvi3yTurcxLzG1zBKzMmGgEUKyMwZgUpZW5JWVuQirIViCCRqWN+lO6tzXkFhYhkaJArFCxRmCQIcpZW6YqytyXmGKDFCBAgHiGIgkBGWN+mLurc15dxDxYrMCAALP0AAc5549MY4pLkrX7vuIAAAqE8MuiMsotc1e3ddyQAAAAACpzzx6Ixxio9Ktfu+5IAAAFQhnl1xjjFy6na/ZdwCQAAAACpwwx64yyinyd7dn3AJAAAACoQzy6oxxTfN2v2XckAAAAAAc4YY9UZZJPk727PuIAAAcY5X6oqyvzfn2AECAEAUhiRUo426ou6T5PyNGkIEAIApDQQjlfmlZX5ggCX5ggatzBGzZRa9xLjjbqTur8vcOPkaRs0KRKLgsvelZX5m0bpKgzRehlF2ZombRtMqLsaIz7ovytzTur8j6Jn1Tk9D8EfcltP4rA51HBcEfcjtP4tA51HsuC9mt+6vA9Gw37GjqXgB1t4z/vfav49b9UDsk618aP3vtP8AHrfqgfg2g/d13s/+yPz5t7HX2eKOsExpmal6lJo8xk6SmWmUR5e/zGmaTNKotM764F+5LbPwP9LOhDvvgX7kds/A/wBLO1bKe1V+75o7Ds85v1dXmjn0AIDvx3BHXnjB+89t/C1P1I+Q2LgvfOIdI9dt0KPsVUdNudTHmkn5fOj67xh/eW2/han6kcl4T/cvP8bn9GJ02/g7WPzmuzdmIT3dSOt3cNRi80qtXOEeSN+CuB4cM56zWVoV9bUjheC6acfelfm2/U+tQho7bhsNawltWrKhI7Lh7FvDW1btqEgMdw1tHbdDqNfXdqenpyqS72V7Gx194qcSwo6aPDmlqXq1bVNTb+DBc4x+LfP4Jep8sfi6cDh6r1XJw6+QzjMTThLFV18nDr5DratXnqK1TUVXedSTnJ+rbuyLojILnlbcuWedzO9n1Phw19WGh5+6r/NyO6TpTw3+7HQ/Cr/NyO6zv+y3sdXvPwR3XZz2V+8/BFAAHZDsSPPO4/8AGGp/DT+kzt7w1cXwjpVFc1Uqp/HN/wD0On9wl/whquf+Gn9JnY/hJusKmj1ezTms6U/b0173FpKVvg0v5R0DZ67TbzFp/wASa8/I6TkV1UY9p8qa8/I7DQAgPQTvaOt/FnbNRKpo92hCUqMYOhUaX2jvdN/G7/Idd8z0VVo0tRTlRr0oVKc1aUJxTUl3T8z5zUeHHCdeo6i0E6V3dxp1ZJfkvy+Y6rmuQXcVfd+xUt/FP/GdazPIruKvu9ZqW/imdMpNtRSbb9x2p4b8JajaoT3rc6Tp6ivDClSkuqEPe36N2XL3L4n0G2cI8ObRUjW0W10lVi7qpNuck/VOTdvmOVr6ihpKLr6mrGnTi0nKTsrt2X6WkfbKshWCr+kYipNrhHBdO8++V5EsHc9fiKk2uEcF07zQaENHZztCGeedwf8Av/U/hp/SZ6GPPG4fv/U/hp/SZ1LatxRa635HU9qvwWut+RzHAjvxbtt3/hJfQZ3gjo7gP7rdt/CS+gzvFH6NlvZave8kfr2V9lr97yQwADtB2lHQG/P/AId3H8brfTZ+G5+zfn/w7uP43W+mz8OXxPIr7+9q62eQX/2tXW/Eo+y8Kvumn+KT+lE+MufZeFL/AHTT/FJ/Siftyh/r1rrR+7Jvb7XWjuBACA9QZ60jLVfvar/El+o87HonVfvar+Dl+o86Zdzpu1f4rX9XkdJ2x/FZ/q8j67w13mO18Qx01aVqWvj7Btvkp3vH9PL/ALR3KjzYqkoyUoycZJ3TXmmd28C8WUeJNtjSrzS1+milXi/4a8lNfH3+j+Y1s3j6dLwlb38V5rz7z7bJZnTpeBuPfxp815959MY6zR6fX6SrotXTVSjWg4Ti/embAdrqSqUM726VUnTUtzOkOJ+CN34e1E5Ro1NToubhXpxbSXpO32r/AEHzdz0oj8tTatrqyzq7bpZy9ZUYt/qOq4jZmiut1Wa4XM1PxOl4rYu3cuOrDXNKfI1MdsnQO2bRum9ahabbNFUrzbs8Y9Me7fkl8TufhDg/TcO7Q9HqoUtRqK8lU1EnFON7coq/uXP8rPoaVKlRgqdGnGEF5RirJfMUfty7JbWAq9ZU9VXwXYcxk2zVjK6nerq118JiEupb+84bV8GcK627r7FpLvzdOHs3+WNjhdX4TcLai708tXpn7sKuS/7yb/SfaI/HvO76PYttrbnrqmNKjG9vfKXuiu7P2X8Fg6qXXdophcXC8TlcVlmXV0O5iLVMLe3CW7rOkuNOG9HwvudPbtNr56lypKpJSgouF27Lk+fl2Pw8MfdNtH49p/5yJ+fed11O97nqN01b+yaieVr3UV5KK7JWXzG/C/3TbR+P6f8AnInn7rt14qbSinUo6pPIHcs3MxVWGp00a1C6J6T0UUiSkeks96QHHb9seh4i22rte4QvTnzjJfbU5ryku6/rORPxbfu2k3HUazTUJP2uhrexqxfmnZNP4NP9DPlcVFa9XX/FujnM3lZuL1F6Gq5UPl3b13HTG7+GPFe2VpR0+j/b1Ffa1aDTbXeL5p//AHc/FoeAOL9fNQp7HqKSbs5V17JLv1WPQQHA1bOYZ1yqmlzbvkdPr2By+u5qprqVPNK8Y+Z8vwLwNp+EdLOrWnCvuFdWq1Y/axj/AIkb+71fvfwR9UCA5qzYt4e2rdtQkd0wWDsZfZpw+Hpilf53jC9ldgfE+KPFsNh2WW2aWtbX6+LhFJ86dJ8pT7ei7/AxicRRhbVV2vgi5hj7WWYWvFXn9mld/MutvcdS8ZbxDfuJtfudOV6VSrjSf+hFKMX86SfzhwTb6rtn/HaX0kcJc5rgn7rtn/HKX0kedW7lV3Eq5VxdSfxP58w2IqxWZ0X7n4qrib63VJ6TGhDR6Qf0ugPNnHf3Y7x+N1P1npM82cd/djvH43U/Wdc2l/YUdfkec+kv2Cz7/ky+BeKqvCW/Utc3J6Wr9i1UF76bfnb1Xmvye89H0a1LUUoaihUjOnUipwnF3UotXTR5OudxeDPGK1NB8J6+r9loJ1NHKT+2h5yh83mu1/Q/BkGYerr+jXHufDr5u3x6zhvR3tD9GvforEP7Ne+joq5v6uTp6ztMAA7cz2pHV3jFwV+29O+LNto/Z9PFLWRivt6a8p/GPk+3wOmcketpQhUjKnUgpRkrSi1dNeh518SuC58I703poP8AudrG6mml54etN/C/LtbudQz7L9FX0q2tz49fP2+PWeM+kbZr1Ff6Xwy+zV+NLkfJV1Pg+nrPqvAKUP25vMWup06DXwvO/wDQdyHnnwe3untHGNLT16ijS3GnLStt8lNtOH5Wrf8AaPQxyWQ3Ka8GqVyNrz8zuXo3xVF/IqbVPGiqpPterwYHx3ixs2s3rg3U0tDTlUq6apDU+ziruajdNJe/k2/mPsRo5TEWlftVWquDUHc8xwNGZ4O5g7jhV0umeaVx7DyBfuJs9L7z4Y8F73qJarVbPGlXm7ynp5ypZP1ai7X72uZbb4UcCbdVVaGyR1E15PUVJVF/Jbx/QdRez2I1QqlHPv8AkeIv0U5t67TTdt6Oeapjq08eie06v8J/D7W75uun4g3HTuntmjmqsHNfviafJR9Yp82/Llb1t6AFCnTo040qUIwhBKMYxVlFLySXuM9Jq9Nr9PDV6OvCtRqq8KkHdSXqmdhwOCt4C36uly3vb5z1/ZjZ7C7M4VYS1Vqrq31N8anuXDkS3QuSedmyGJDP2naEebfHP7vq/wCLUfonXbXvOxPHL7v9R+LUfonX2N780rK/M80zP2u51s/kDbBf+exn/sr8WYSRLRpYlo42o6xUjFqz8ibGjXMUo2tzTur8vcfNnzaMrWM7GzViLGGjEGdgSsXGF79SVlfmxJc0Zgy6SbBYuwWsZM6TO3cLGkoY49Sd0nyfkTYQNJFhWZp5BGGV+qKsr82SDMGWIWLsGKIIIsGLLxHKnjbqi7q/J+QJBlYLM0xFYggizA1hTzv1RWKb5vz7LuRbsCQQBdhWAgmyFijWdPDHqi7pPk727fEizEE0k4isy7MqFPPLrjHGLl1O1+y7kgmkyAoLIQSCQHiOpTdPHqjLKKl0u9uz7kJBIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAANFEoaNI0hggAAaKRKGgAl5CQ35CRtGkUiokIpcjSNo0j5FRIiUjSNIs0izNDTszaPoap+4fkSncpM2mbpZ6J4H+5DafxWBzyOg9t8S+Kdq0FDbtHV06oaeCpwUqKbsvVn6l4ucY/wCX0v5hHomG2owNqzRbqVUpJcFyLrO42c8w1FumlzKS5P7neR1p41O2n2n+PW/VA+Z+u3xj/l9K/wD/AEI4jiHjHeeJ40IbtOlJadycMKePna9/yI/Nmu0OExuDrsWk5ccV0p858sfnGHxOHqtUTLjk6V0nFJgQmNN+p0uTraqNE7DUiExlTNSaJnfvAn3IbX+B/pZ5/TPqNs8RuJdp0FHbdHW06o0I4wUqKbt8TnshzGzl16q5emGo3daOWyjG28FdqruzDUbus74QHSS8V+Lv8vpvzCKXivxa/wDD6b8wjtS2pwPNV3L5nYltBhOZ939z6bxjbWi2z8LU/UjkfCR34Wqfjc/owOtN/wCLt44lp0aW6VKUo0G5QwpqPN2v+oNo4w4j2LSvRbVuPsKDm6jj7GEup2u7yi37kcJRnWHozSrGQ3S1HBTwXT5nGU5rZpzB4qHpajp4LpPQAXUU5SaSSu2zouXiNxpNWlvcvmoUl+qJxW4cQ75uqw3HdtVXg/4Eqjx/k+Ry1zazDJfd0VN9MLzZyde0lhL7FDb6YXzO1+KfEna9ppz0u0VYazWtNJxd6dN+rfvfZfPY6j1Wr1Gt1FTV6utKrWqyc5zk+cmz8t2O51fMM1v5lWnc3JcEuC/udfxuY3sfVNzclwXIa5MeRll3DLucdJ+GT6zw1afGWh+FX+bkd2nnHbN11uz62nuG3VvZailfGeKla6s+TTXk2c59crjT78/7PS/snaclzzD5dh3aupttzujmXO1zHZMozixgLDt3U25ndHMulcx3oB0YvErjT79f7PS/sj+uTxp9+v8AZ6X9k5j614P8tXcv+xyy2mwn5au5fM4fcf8AjDVfhp/SZrs+7azZNwo7lop2q0nez8pL3xfZo/BUrTq1JVajylOTlJ282xKb950VXXTc9ZQ4cyjpquOmv1lDhzJ3/wAN8U7ZxLpFW0lWMa6S9rp5Prg/6V3OYPNun1lfSVoajS1p0asHeM4ScZJ9mj6vb/FLifRR9nXq0NZFeTr0+pfPFr9NzumC2ptulU4qlp864Ps5Dt+D2mtulU4qlp864dx3Oijq6h4x6qK/3xsVGb/0K7h+tMz1XjDuVSFtHs+mpSf8KpUlUt8yxOTe0WXJTr+D+Ryf1hy9KdfwfyO0a1ejpqU6+oqwp04LKU5ysor1bOreK+NY7/u+j23bZP8AaNHUwbn5e2lkudvRe78vw+V3ninfd/dtz185007qlHpgn/FX63zOOoV50K1OvTtnTkpxuvenc69mW0Txa9VYUUcvO/kjgcx2geK+6sqKOXnfyR6RGjpj66XFn+W035lAvFPiv/Lab8yjm/rTgearuXzOcW1GB5qu5fM7oPO24N/t/U/hp/SZ9F9dPiz/AC+m/MI+Uq15Vqs60/tpycnb1bOBz3NrGY00KzO6eK546Tgs8zaxmNNCszuniueD6HgNt8Xbb+El9CR3kjzfpNdqdBqYavR1pUq1N3hOPmn5HK/VxxX9/NV/KX9RrJs7s5bZqt3KW23O6OZG8lzyzltmq3cpbbc7o5kd+AdCfVzxZ9/dV/KQfVxxZ9/tV/KX9RzP1swv5Kvh8zmVtdhfyVfD5n59/b/u7uPP/ldb6bPwZMVbUVdRWnXrTc6lSTnOT83Ju7ZGZ0a5c11upcrOi3K1XW6lys1yPs/Cd34nn+KVPpRPh8z9W3btr9prvVbdq6mnquLg5wfPF25foR+jA4mnC4mi9UpVLk/TgMVThMTRfqUqlyekEB0F9XXFn3+1X8pB9XXFv3+1X8pHcfrZhfyVfD5nd1tjhP5dXw+Z3xqv3tW/By/UecMl6nLS444rnFxlvmpaas1deRwuZwGdZtbzN0O2mtM8emPkdez/ADm1mztu1S1pnjHLHyNL92fp2/ctbtWrp67QaidGtTd4yj+p+q7H4suwZdjhabjoaqpcNHAUXKqKlVS4aO6uFvEnad6hDS7lOGh1tkmpu1Oo/wDRk/L4P9J9indJryPMmXY5jaOMuItkUae37pVjSj5Up9cF8FK9vmsdpwW1FVCVGKpnpXHtX/8ADu+W7Z1W6VbxtOr/AFLj2rh4dR6EQHUek8Zt5ppLWbXo63eDlTf62fsXjXUxd+HI39Vq+X0DmadocvqUuuOx+SOyUbW5TUpdxrrpq8kztJAdS1/Gjc5J/tbZdLTf+nUlP9VjgNz8R+LdzThLc3p6b/g6aPs/+8ur9J8Lu0mCoX2Jq6l84Plf2zy20vu5rfQo8YO4uIOLNk4boOe46uPtbXhQg71J/Be74uyOmOK+Mdx4r1aqan7DpqT+w6eLvGPd+r7/AKjgJ1ZVJupUlKUpO7k3dtiudZzHO72PWj8NHNz9bOlZztNic3Xql9i3zLl63y+Bdzk+F3+6baF/07T/AM5E4m5ynCz/AHT7R+P6f+cicbh397T1rxOEwb/WbfvLxPRpSJKR6mz+iEB0tuXFGq4V8R9y19BOpRlWwr0b2VSFl+leaf8A9Tuk89eID/dluv4f/wAKOvbQ3a7Nm3cocNVeTOm7b4i5hMNZv2XFVNaafYzvfZN92ziDRQ1+16mNWnJLKN+qD9JL3M/eeYtu3Xcdo1K1m2ayrpq0eWVOVrr0fquzPr9B4ycU6WChq6Wj1lvOVSm4zf8AJaX6D4YbaSzXTGITT6N6+Z+fLdv8JXQqcdS6audb0/NdW/rO8EB07V8cN3cLUNk0cJes5ykr/BWOA3fxP4v3em6MtwjpKcvOOlj7Nv8A7V3L9J97u0WDoU0TU+r5nIYjb3KbNM23VW+ZKPGDtjjDxC2bhWlKiqkdXr2rR09OX2r9Zv8Agr9J0Tu+87hvu4Vdz3Ku6tes7t+SivdFL3JH4pTcm5Sbbbu2ycjqmY5rdzCr7W6lcF8+c81z/abFZ9Wlc+zbXCleLfK/8S4lXZzXBL/dfs347S+kjgnLua6HX6nbdZR1+iq+zr6eaqU54p4yTunZ8mfgs3FbuU1vkaOEwl+nD4i3eq4U1J9zk9WjR52+uxx99/8A/ZaH9gPrs8f/AH//ANlof2DuP1lwn5au5fM9jXpKyn+Xc7qf+56JPNPHj/dlvHP/AJXU/Wfs+uzx/wDf/wD2Wh/YPmdw3HVbpra24a6r7XUaibqVJ4qOUn5uySS+Y4jOM3s5hapotJppzvjybOpbYbW4LaDDW7OFpqTpql6klyNclTMrm+g3DV7ZraG4aKq6dfTzVSnJe5o/I5oWZ19VOlyjz+m5VRUq6HDW9M9S8KcR6XirY9Pu+ltF1FjWp3506i+2j/V2aZzB5a2DjLiThiNaGx7nLTRrtOpH2cJpteTtJOz+By313PEP/OD/AGSh/YO3WdpLKt0q9S9XLER4ntGX+k/A0YainG263dS+06VTDfOpqXHjw3Ho9HE8WcNaPivZK+0atKLmsqNS13SqL7WS/p9U2joX67viEv8A2h/2Sh/YD673iH/nD/slD+wW5tDgrtDoroqafQvmfoxHpKyLFWqrF6zcdNShrTTvT/rPntx0Ov2Pc6236yEqGq0lTGVnZqS8mn+Rp/A708OPE/RcR6WltW9ainQ3WmlBOTxjqf8ASj/pesfnXbo7feIt34k1i1+9amOo1CgqeapQptxXlfBK/n7zjsmua9x13CZhVgLzqsb6XyPlXzPM8l2lubN4+u9l81Wan+Grc3TyTDaVS51Pc4PYQ0eatk8VuNdjjGlT3NaujBJKlq4e0Vv43KX6T6fS/KA3eFv25w9o6vr7KrKn+vI7Pb2gwla+3NL6vkewYL0m5JiKU77qtvppb+NM+C6ju8F5nS1f5QmslFrTcMUacvc6mqc0vilFHyPEHinxlxFTnp6+4LSaeaalR0kfZqSfubu5Ndr2Jez/AAltTQ3U+qPE+mN9JuR4ah1Yd1XauRKlrvdUeD6jsPxV8UdHo9HX4a4e1Ua2rrxdPU6inK8aMfJxTXnJ81y8vj5fYeG33C7L+Kx/Wzy6fZbT4tcYbJtun2rQV9LHT6WCp01Kgm7d2cPhs7X0mq/iJhqElybzpGS+kRLOLuY5rOl0aaaaVKp+0nytc298r6IS9LIZ5yfjhx4vLU6P/VkL6+PHv/OdH/qyOT+sWD5qu7+53ZelbIV/Dc/2r/sR45fd/qPxej9E68kcxxLxHufFO5y3fd505aiUIwbhDFWirLkcO+Z03GXab+Iru08G2zwLP8bazLNMRjLM6a66qlPGG53kWJkaNEM/CzhWjOxLVvIuwrGGYgzaItY1aIsZMwQCXNFW7AkZgzpFbuKxdhEMwTYVixW7EgQRYVjSyFYySCLMVmaYixYJpIswsy7MLAaSLMOZdhW7AmkkRduwWEDSRZBZFYhiSCQRigxKs0FmIJpIsKxoKxIJBFhWNLCx9ASDOzAu3YViGYMgAqE8MuiMsouPUr27ruZPmSAAAAAVOeePRGOMVHpVr933AJAAAACoTwy6Iyyi1zV7d13JAAAAAAHOeePTGOKS5K1+77iAAAHCeGXTGWSa5q9u67gCAAABFIkuU8semKsrcl59yoqAAApQRSFCeN+lO6tz9wIAb5oQ0J+ZpGkCKE5ZW6UrK3JeY0aRpFplp3Mk7GkJ435J3VuaNGikykQikzSZtMuLt5lpmaKybtySsrcjSZtGiY/MzUik/Rm0yplhcUZW9yd1YE0WTaqKTGpNepI7mlUaktTGpkOSdvJWBdjWo0maqSKTMblRk185UzSZqmxpmSmUpI2mVM0UmUpGV/RlZP0XIsmpNFMeZlkGSKmXUa5jyM1KwZdy6i6jVTQ8l2McmO7LJdRtdBkZZBkWS6jXJDv3MlIakXUaVRqpP1Gn3MskNS7l1GlUa3GmZXY8i6i6ma37hkZZDUjWouo1yHcyyHmXUXUaXC5nkwyY1DUaX7juzLJgpDUXUa37hfuZZMMhqGo1v3FdepnkGQ1DUa3XqF16meQZDUNRpdeqDLuZ5IMkNQ1GuXdBd+plkgyLqGo1yYXZlkvUd+41F1Gl2GTM8gyfqNQ1GmTDIzy7hmxqGo0yDIzzHmXUNReQZfEjL4BkhqGo0zDJepncLiS6jXL4HKcKv90+z/j+n/nInDXOV4Ul+6jZ/wAf0/8AORPvh399R1rxP04J/rNv3l4o9KlIkpHq7P6NQHnjxBf7s915/wCH/wDCj0OedPEOTXGm7JP/AA//AIUdZ2ocYaj3vJnRfSF7Ba9//izgROSM8mLJHRmzyGS3MnInIlt+plsy6i3L1YsiLr1ByRnUTUU5MV36EuZLmTUZdRd36Cuyc/gTl3JqM6iwM8u4ZMmomo0FdEObfnYV7mZJqNLr1DLuZDTt7r8hJJNPnAzTHcSWS/ILkJ9xuTdv6BJZKuFyU36v8oXfq/yiSlXD5yVK1/LmrcxXJIKuS2K4NkkgmJuw5S8uSVlbkR5mWyQJu5NixXtfkuatzMNmGQ/Iza8i2SYZlomwmi7Cm726UrK3IwzDRk+bJsXYVuZlkgiw0veXFuN+mLurcxJGSQTbsKxdgsSCaSLBiXJ5Y9KVlblyuTZkgmknEVi7P0HGWN+mLurc15fAEgzsFigJBIIAsqUs8emKsrcl5/8A1ECDIC7ILL0ECCLBY0g8L9EZZJx5ry7ruTiIJBFgxKxYWZIJBFgsaznnj0RjjFR6Va/d9yBBIIsLE0sioSwy6Iyyi49Svbuu5CQYWCxdgsCaTMLF2Q6ks8eiMcYqPSrX7vuSDMH4wAD5n5gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAUhkpjTNJmkxggAApCYJj8yoqJGmIDRospMhMo0jSLTKTM0ykymkzRMafoQmNM0maTLT9UVdEXQFTNJml36jUjNMd+5qSmimUpGQyyU1uvUDK79RqRqTUmtykZKTGpFTLqNB/OZqZWRZNai7sd2RcdzSqNKorLuPLuRcd+xdRdRV+41J+pGXYd0XUXUXkwyfcm4XGsai8u4ZdyLoLl1F1Gilz8xqRmNWLqRdRqp9xqRkBpVFVRrkvUan3Mrhky6jWo2y7/pHkY5BkVVF1G2Q8u5ipdgyfoNRdRtkvUMjLJhk/UuoajXLuGXcyyfqGTEl1I1y+IZMyyY7v1GoakaZMWRFwuNQ1o0yDJmeQXGomtGmT9QyfczuFxqLrRpkwUmZ3C41DWjTNjzM8gyLqGtGimGZnkGQ1DWjTMeZlkGQ1F1I1yHkY5IMi6i6jbJBkjLPuGY1CTXLuPJmWQKSGoajbI5XhN/up2b/rDT/zkThcjXSayvodXQ12lqYVtPUjVpysnjOLTTs+T5r3n0s3FbuU1vkaPvh7ytXqLlXBNPuZ6tKR53+uvx79/v8AZaP9gPrsce/f/wD2Wj/YO9PavBflq7l/2PW16QsrX8Fzup/7Hog84+Ikrcbbtz/w/wD4UbfXY49+/wD/ALLR/sHze5bnrN211bctwre11FeWVSeKjd/BJJeRw2dZ1YzGzTbtJppzvjmfM2dZ2q2pweeYWixh6ak1VP2klyNcjfOY5ITkQ5Ccu51l1HQnUW5dyXIhysS5mdRl1GjkLIzcu5OXckmdRrl3Fl3MrsDOozqNHInNEATUiakXn2FmRYZNSJqKyDInkPkJRZKyDImw7dxKKmVkgyRIK3cSiyVf4juTyQcvUSaUFXXqO/ckBI3DuFxB84ksodxNgHMmoSIQ33FfsZbIJ8iXzKJMmSWKxVvQDJIJIfMt/AmxGIJtyFYqwWMmYIsUl5DSHYjRIJsKxVgsQkE2FYsViCCLBZFWCwgmkmyCyKsGJIGknFegsUXiGIgaSMQxLxFixBNJGLCzLsKwgmkgCwsiQTSRYLIrEWL9wJpJxFZl2ECQQFi7CxJBlomyFYrFgSCQfgKp0/aZdcI4xcup2v2XckD4n4QAAAAqpT9nj1wllFS6Xe3Z9yQAAAAAqEM8uuMcYuXU7X7LuSAAAAAAVOGGPXGWUVLpd7dn3JAAAKhDPLrjHGLfN2v2XckAAAAAAc4YY9UZZJPk727PuIAAGmIAgaQjlfqirK/N2v2ESmNM0aQxpiAAqccbdSd0nyfkSCYGkzSYyoLK/VFWV+b8yAKUspS9SEx3NJmpNEy2sbdUXdX5e4xGpNFKaIabM1IpSRZKmaR6r80rK/MCMkNS7lk1LLC7JUmGRZLJo+VupO6vyfkFyLjLJdRdyo8780rK/NmeTDIsmpNE+4zNSHcssqZd7FPlbmndX5PyM0xqRZLJWQ8uxGS9Qui6iyaJp35pWVwUiLgWSyXfuPLuZjuNTEmjbVuafK/IMmZ3HcuosmikUpX96MrhdF1Fk1yY1MyBNl1Ism2Y8l6oxyYZepZLJtkh5L1McgUiyNRsmvUMl6mWSDLuJLqNckGSMs+48n6lkajRytYMzPJ+oZMahqNc2Ck/X9JnkLJiS6jTIMmZ5P1C79RqGo0zYZGeT9R5dxqGovIMiMgy+I1DUXkPIzy7sL9xqGo0y7hn3M79wv3LqLJpl3DMzyDIahqNcx5GOQZISNRrkn7h3RlkvULoSNRrcG7e8yUu41IupiTS4ZEZIL9xqNajRSv7wzIAuoai816hmvUzDmNQ1Gjkl7xZmfMLv1JqJqLcmLK9+ZAXJqI6h5Cu/UTlYlz9DLqZl1FA+XvRnk/cJy7mWzOo0yQs0Z3C5JRJLUm780rK/MMmQBJBeQ8iLgmJKjRu1uafv5MWRN2F2XUaLyZUW3fmlZGfMdxJUVkNSITGn3ElRdxvlbmndX5e4zHcSVFXHdEXsO5ZNFrnfmlZX5iv2JuP5iSUd2LmAhIKlHG3Nc0ny9xPv8g+YLEAmOMMr80rK/P3jt2E2QQLyJfYYrEEEjlHHHqi7q/Jhb0CxBBNkOw7Al6kEBCnlfqirK/N2uIoLEMwSIqwWAgJQxx6ou6T5Py7fEiyLx7hiSCaSMUVCmp36oqyvzdrjxDEQNJGKDFFYhYQNJOI50sMeuLySfJ3t2fcdgsxA0kYhZ+hdmIkE0hCnnl1Rjim+p2v2+JFiwEE0kWFiXZBiBAqlLDHrjLKKl0u9uz7kWLsxWIZgixUKftMuqMcYuXU7X7LuOwsRBIIxFYuwiQR0kF1KeGPXGWUVLpd7dn3CwsSGXScYAAfnOMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABpiAApMZCZSZpM0mMAAAAADSZpMBpiApSkx3JBMslksaZNwElTLuMgLsslkvmNNojIeXYslTKyY1Ii47lksmimPLsZXGmUsmmSHkjNMZZLJpl3HkZAWSya5BkZ37hd+oksmt0PLuY3fqO5ZLJrl3DIzuO5ZKaZBczu/ULv1EiTW4zG79RqTLIk1C79TPJ+o8mUsmlwuZ5P1HkxJZNLjujLJhkyyXUa3C5nkGQkSa3C7MsgyfoJLJrdhf1MsmGTLIk1yDIzyfqK4kSa5dwz7mdwuWRJpn3DPuZ3QXQkSaZ9wz7mdwuvUSWTTMeRldAJEmuQZGYXEiTTIMjO4X7iRJpkh5GWXcMhIk0uF+5GaC4kSXcFIm6C/cSJLy7jyZncL9y6hJopDzMrsLsaiya5hl8TK4X7iRJpmGZlfuFySSS8xOTIuK7JqJJd+4rk3YrpEkklXFdk5IL9ySZkoLk5BkCoq47kXY7g0iwuQO4NItMZmik36g0XcCLv1Hd+pTSL5eofOQmxpiSl8wJux37FLBVhpdyb9h37Ao7dwsK79AuwWCrATdhzBYK5CuhJDskCwK4WHyXuDmQsEgOw7EEEgOw0gIJSHZFWFYggVgsVYQgQKwsSrMdmSBBGI8SrMLMQIJxQYlWYWYgQTiLEuzCzECCMQsXZiECCbdhW7FgIJpM7IMTSyFZEgmkzxCzLxCz9ATSZgXYWJIM6SLIWJdmIQR0kWCxYrIhmCLCsXawiGWjiCqdT2eXRCWUXHqV7d13JA/KcQAAAAFVKntMeiEcYqPSrX7vuSAAAAAFU6ns8uiEsouPUr27ruSAAAAAAVUqe0x6Ixxio9Ktfu+5IAABUJ4ZdEZZRcepXt3XckAAAAAAqc88eiMcYqPSrX7vuSAAAAAFQnhl0RllFrmr27ruSAAAFwAAuVTPHpjHFJcla/diuSCZZLJZUJ4X6Yu6tzXl3ITGUoXGIClHzHKeVumMbJLkvP49xXHcslkVxphy9AshIkqE8b9Kd1bmvIQrIdimkxgIZZLJUp5W6UrJLkvPuK4gsWRJSZUZ436U7q3NeRFmHNAslAJX9BlKO79RublbklZW5EgWRJSY0yB8yyWS4ytfkndW5ryAjn6DTYLJQCuFylkpybtySsrchXfqACSyO7HGdr8k7q3P3EgWRJVx3IAslku5Tne3JKytyMrjuJLJeQ8kZ5DuWRJoppX6U7q3NCyRFx3ElKyDIkBIktyvbklZW5ILkAJEl3Q1K1+Sd1bmZ3HdlkSVcCbsLsSCht3tySsrciLsfMSJKAnn6Bz9BIkpO3uTurcwJ5+gc/QSWSguybv0C79BIktybtySsrchXZNxXEkku7BStfkndW5kXC4ksl3C5FwuxIku7G53tySsrcjPL1HkhIk0Uu4XuZ3DIsiTWMmr8k7q3MVzPMeZJEl3C5nkgyQkSayle3JKytyJuiMkLISJNMkCnjfpTurc/cZ5CyJJJLcu5ORNwuSSSVdlOV7ckrJLkQmAKVcZKGWSoqM8b8k7q3NeQJiQ0JNIfMA8gKjSKcm7ckrK3ILsS8xoGkMcZY36U7q3NeQgKbQ0NPsJIaBpDG5ZW6UrK3JCsCElHfsP5hIYKioyxv0xd1bmvIkYWKaD5g5jsMFgJSyt0xVklyQrDCz9BBYEVGWN+lO6tzXl3FZjSBYECTKSHYhYJS9CpSzx6YqyS5Lz7sLBYCBJegWHYeIEChLC/TGWUbc1e3f4it2KsOyBdJFuw7FWCwgukJSzx6YxxilyVr933JsVYLCBpJsVCWF+mMsotc1e3ddwsFiwNJNgsVYLEgaSLFTlnj0RjjFR6Va/d9x2CyEE0kWFZF2QWA0ihLDK0Iyyi49Svbuu5FmXiFgSDOwF27CsQkBUmqmPRGOMVHpVr933IsXj6CsxBmCLDhPDLojLKLj1K9u67jCxII6TPEVmXiJohlogqpP2mPRGOMVHpVr933BxFYkGGjhAAunT9pn9khHGLl1O17e5dz8ZwhAAAAABVSn7PH7JCWUVLpd7X9z7gEgAAABVOn7TLrhHGLl1O1+y7kgAAAAAFVKfs8euEsoqXS727PuSAAAVTp+0y64Rxi5dTtfsu4BIAAAABVSn7PHrhLKKl0u9uz7gEgAAABUIZ5dcY4xcup2v2XckAAAAAAqcMMeuMsoqXS727PuSAA0xFQhnl1xjjFy6na/ZdwATAkLlkslgJMqccMeqLySfJ3t2+JShcaZIAF3AUI55dcY4rLm7X7LuJMsgoBXHcslkB3HKONuqLuk+T8uz7klNSVcdyCoRyy6oxxTfN2v2AHcZFx3BZKAVypRxt1Rd0nyfkWSyK47iAslGmO4oRyv1RVlfm/PsIoLuBFx3AKAJLG3UndX5PyFcSWRjuTcqMcr9SVlfmyyJC47okBJZK5BZElSjjbqi7q/J+RZEjsgsibhcslkqy9Asgj1X6krK/N+YsgWRjFcLiRqGASWNupO6vy9whIkYXEVGOV+pKyvzfmJEiuFxDLJZHcLiHJY26k7q/J+QkSFwuIBIkdwuEY5X6krK/N+YhIkdwuIBIkdxX7DlHG3UndX5PyEJEhyABxWV+pKyvzfmJEiFcYuT8xJdQXDIVglHG3NO6vyfkJEjyFkIBIkrJBkhRjlfqSsr835iEiSroMiRCRqKyC4SWNupO6vyfkTckk1DuFxXHFZ36krK/NiSSA0SNCSopDQkjRxxt1J3SfJ+RZNJkoaAaEmkNJDHCOV+qKsr8359hFNIaGJDQNDGglHC3OLuk+T8uwIGkMLL0AqEMr9UVir835lNoSQ0l6CRRUaQWXoFuwFShhbqjK6T5O9uxTSEkNJAhg0KyHYqEM8uqKxV+btft8RIFSCw7AANQAFyhhj1Rd0nyfl8e4kgWBJDSGVCGeXXGOMW+p2v2QNQRYaAaTLBYEA1EudNQx6oyyinyd7dn3EFgzsOzKApdIsQUTSnT9pl1xjjFy6na/ZdycWDWkmy9B2KxDEDSSBpOmoY9UZZRUul3t2fcmy9AWCQKsvQuFNTy6oxxi5dTtfsu5RBkBVl6BZEEE2FZF4lVKXs8euMsoqXS727PuCaTLEWPoXixWBNJNmI2p0/aZdcY4xcup2v2XciwgkEWFYuyFYkE0kWFY2qU/Z49cJZRUul3t2fcixIMwZ2FY0sOnS9pl1wjjFy6na/ZdwZgxCyKtcTRIMtEOImiyqtL2eP2SEsoqXS72v7n3JBlo+dAAPwnXwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAC4AANMdyQuWSyWBKY7lksjuO5NxgFJhckLgFgTcd+5ZLIwFcdyyWRhdiAokq4JkgCl3Am4XBZLAm4XLIkoBXC6Elkd2O4gLJR3HckACrhckCgu4EXHcAoCbhkBJQCuFxJZKuFybhcsiSrhcV0FxIkdx5E3C4kSVkGRICRJWQZEgJLJWQZEgJElZBkSAkSVkGRICRJWQZEgJElZCuILiRI7hcVwuhJJHcQrhcSJHdiuFwyEiQyFcLhcSJC4XC4riRI+Y0rCRRJCYKxSJKRZNoZSJGimkUCENA2ikAICybQ0UiUUvUppDGiUUimkNDQhoGkNDEhlRtANCRSKjaAYhlKkCKQkNA0A0gQ0DQIYDSKkaSENIaQymkhJDBK5SiDSRI1EqwWLBqBKI7DSGolgsEhYuwJCC6SUmGJdn6BiUukjEeJeIYgukjEMS8V6BigXSRiLE0xDEE0meIWZeIWYJpM7AXYViQTSRZBiViFhBIIsIsVkQzBNhNFYiIRoiwWLE0IMNENE2LFYzBlohoTVi7CsDDR84AF0qvss/scJ5xcepXtf3rucedcIAAAAALq1fa4fY4Qwio9Kte3vfcAgAAAALp1PZ5/Y4Syi49Sva/vXcgAAAAAAupU9ph9jhHGKj0q17e99yAAACqdT2eX2OEsouPUr2v713AJAAAAAKqVPaY9EI4xUelWv3fcAkAAAAKp1PZ5dEJZRcepXt3XckAAAAAAqpU9pj0QjjFR6Va/d9yQAACqdT2eXRCWUXHqV7d13AJAAAAAKqVPaY9EI4xUelWv3fcAkAAAAKhPDLojLKLj1K9u67kgBcdxAAVcLhOeePRGOMVHpVr933JuWSyWBFy6dXDLojLKLXUvLuu5ZLIXC4rjuAO47klTnnj0xjjFR6Va/d9wAuMi4XLILAIVMMumMso26l5d13FkJLIwFcdyyWRhcc5549MY4pLkrX7vuSJEjuO5JUJ4ZdMZZJx5q9u67lLIXHcgAJLuFyblTqZ49MY4pLkrX7vuCyAyLhcsiSwCFTC/TF5K3NeXddychIkoCbjuJLIwuxyqZY9MVZW5Lz7k3EiR8wuxXKhPC/TGV1bmvLuiyJFcLi5ByEgq4XJKnPPHpjGyS5K1+77iShcLiASB3C4QnhfpjLJW5ry7ruISB3C4gEgdwuEp549MVZJcla/f4iEgdwuIcJ4X6Yu6tzXl3+IkCuFxByEkkdwuxXKlPLHpirJLkvPuJEi5gK4XJIkYBCphfpi7q3NeXcm4kSUBNwuJJJQCnUyx6IxxSXJWv3+IkxIkpcikQaU54X6Yu8bc15d13LJtCKX5CRplNIoa5CTKnPPHpjHFKPJWv3fcSbQJlIlDLJtFJjCnUwy6Iu8bc15d/iCKbQ0UQuRSKaQxoc5549EY4xS5K1+77iRUaRQIRdOeGXTGWUcepXt3XcptAhkoYNopDEi5zzx6Yxxio9Ktfu+5UaRI0JcykrFNDAunPDLojLKLj1K9u67iSKaSBIYFJFSPokJIoqc88eiMcYqPSrX7vuJIppIRSiNKxVOeGXRGWUXHqV7d13LBtIkEhpFJFg0kJIaQ0rlzlnj0RjjFR6Va/d9ymkiEhqIwsWDSpElYZdOWGXRGWUXHqV7d13FZFg1pJCxaQWYgsE2foGJrOXtMeiMcYqPSrX7vuTiCwRiGJeJdOXs8uiEsouPUr2v713ECDHELP0Lx7hZiBBnYC7diqk/aY9EY4xUelWvb3vuIJBkKxeIrMkE0kYisbU6ns8vscJZRcepXt3XcgkGYM7CsaYk2BlogVjarP2uH2OEcYqPSrXt733M2iQYaIasIsqnP2eX2OEsouPUr2v713IZaMWrisUBDLRBLRbRVWp7TH7HCGMVHpVr2977kaMNHywABxx1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAuAADuGQgEiSrhckCyWSwIuO4kSUFych3LJZKuGRNx3AHkO5IAFXHcgLlkF3Ai47iSyUBOQZCRJQCuGRZLIwFcdxIkB3FcLiRI7hcVwEiR3YXYgLIkd2FxABI7hcQAsjuFxABI7hcQASO4XEAJI7hcQASO7C7EAkSO4XFcLkkSO4guFxIkAC4riRIwFkFxJJGNEp3GJKmWmNMhMpMptFJjJTGmVM+iLTGSn6D+csmikyiEykym0MpEjTLJtFFIhDRUbRQ0JDSKaKABoqNoaKQkUkU2hpWABpGkfRIaQ0BSRTSQJDApIqR9EgSGA0im0gSuUlYASKkaSBIpIEikjRtISRSVgSsMG0gBIaRSXoag2kJRGkNRGU0kJRGkhjSLBpUisBSQWEF0k27BZ+haQWZS6SLP0Cz9C7MLMF0kWfoBdgsIJpIFYuyFiSCaScUKzKsBIMwZ2E4mlhNAy0ZhYqwmrEgy0Q0KxYmjJlozsIsTQPm0Q0SWJoy1BkklqxQMhho//2Q==",
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
p("== СКОРОСТЬ TELEGRAM (228) ==")
try:
    import time as _t228, urllib.request as _u228
    _E228 = {}
    for _ln in open("/opt/fo/.env", encoding="utf-8"):
        _ln = _ln.strip()
        if "=" in _ln and not _ln.startswith("#"):
            _a, _b = _ln.split("=", 1)
            _E228[_a.strip()] = _b.strip().strip('"').strip("'")
    for _nm in ("TG_BOT_TOKEN", "TG_MEET_BOT_TOKEN"):
        _tk = _E228.get(_nm, "")
        if not _tk:
            p(_nm, "нет")
            continue
        _ts = []
        for _i in range(3):
            _t0 = _t228.time()
            try:
                _u228.urlopen("https://api.telegram.org/bot%s/getMe" % _tk, timeout=20).read()
                _ts.append("%.1f с" % (_t228.time() - _t0))
            except Exception:
                _ts.append("ошибка за %.0f с" % (_t228.time() - _t0))
        p(_nm, "getMe:", ", ".join(_ts))
    _t0 = _t228.time()
    try:
        _u228.urlopen("https://ya.ru", timeout=20).read()
        p("ya.ru: %.1f с" % (_t228.time() - _t0))
    except Exception:
        p("ya.ru: ошибка за %.0f с" % (_t228.time() - _t0))
    for _sv in ("fo-tgpoll", "fo-tgpoll-meet"):
        p(_sv, "за час: принято", sh("journalctl -u %s --since '-60 min' --no-pager -o cat | grep -c 'принято'" % _sv).strip(),
          "· таймаутов", sh("journalctl -u %s --since '-60 min' --no-pager -o cat | grep -c 'timed out'" % _sv).strip())
except Exception as _e:
    p("скорость: ошибка", str(_e)[:200])

p("")
p("== КУДА СООБЩАТЬ: московское время (236) ==")
try:
    _rp = "/opt/fo/backend/app/routers/routing.py"
    _rs = open(_rp, encoding="utf-8").read()
    if "_msk_now()" not in _rs:
        shutil.copy(_rp, _rp + ".bak236")
        _rs = _rs.replace("from typing import List, Optional\n",
                          "from typing import List, Optional\nfrom zoneinfo import ZoneInfo\n\n\n"
                          "def _msk_now():\n    return datetime.now(ZoneInfo(\"Europe/Moscow\")).replace(tzinfo=None)\n", 1)
        _n = _rs.count("now = datetime.now()")
        _rs = _rs.replace("now = datetime.now()", "now = _msk_now()")
        open(_rp, "w", encoding="utf-8").write(_rs)
        p("routing.py: datetime.now() → московское, замен:", _n)
        sh("systemctl restart fo"); sh("sleep 3")
        p("health после routing.py:", sh("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health").strip())
    else:
        p("routing.py уже по Москве")
except Exception as _e:
    p("routing.py: ошибка", str(_e)[:200])

p("")
p("== ОТПРАВКА КЛИЕНТУ (разведка 234) ==")
try:
    import re as _re234
    _sec234 = []
    for _ln in open("/opt/fo/.env", encoding="utf-8"):
        if "=" in _ln and not _ln.startswith("#"):
            _v = _ln.split("=", 1)[1].strip().strip('"').strip("'")
            if len(_v) >= 8:
                _sec234.append(_v)
    def _hide(x):
        x = str(x)
        for _v in _sec234:
            x = x.replace(_v, "***")
        return _re234.sub(r"\d{6,}:[A-Za-z0-9_-]{25,}", "***", x)
    _nt = open("/opt/fo/backend/app/notify.py", encoding="utf-8").read()
    _i = _nt.find("def send_telegram")
    p("notify.send_telegram:", _hide(_nt[max(0, _i - 200):_i + 1400]) if _i >= 0 else "нет send_telegram; файл: " + _hide(_nt[:800]))
    p("таймер fo-flush:", sh("systemctl is-active fo-flush.timer 2>/dev/null").strip(), "·", sh("systemctl list-timers --no-pager 2>/dev/null | grep -i flush").strip()[:200])
    p(sh("sudo -u postgres psql -d fo -Atc \"SELECT 'outbox всего '||count(*)||', не ушло '||count(*) FILTER (WHERE sent_at IS NULL)||', ошибок '||count(*) FILTER (WHERE error IS NOT NULL) FROM outbox\"").strip())
    p(sh("sudo -u postgres psql -d fo -Atc \"SELECT 'chat_route правил '||count(*)||', клиентов '||count(DISTINCT client_id) FROM chat_route\"").strip())
    p(sh("sudo -u postgres psql -d fo -Atc \"SELECT 'fo_task_report: '||string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='fo_task_report'\"").strip()[:600])
    p("TG_REPORT_BOT_TOKEN в .env:", sh("grep -c '^TG_REPORT_BOT_TOKEN=' /opt/fo/.env").strip())
except Exception as _e:
    p("разведка 234: ошибка", str(_e)[:200])

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

p("")
p("== МОДУЛЬ «ЧАТ-БОТЫ» У FLATER (275) ==")
try:
    if os.path.exists("/opt/fo/bots-275.txt"):
        p("уже включён ранее")
    else:
        _r275 = sh("sudo -u postgres psql -d fo -Atc \"INSERT INTO fo_card (kind, ref_id, org_id, data) SELECT 'org', 'bots:'||u.org_id::text, u.org_id, "
                   "'{\\\"enabled\\\": true}'::jsonb FROM app_user u WHERE lower(u.email)='nekrasivostore@gmail.com' LIMIT 1 "
                   "ON CONFLICT (kind, ref_id) DO UPDATE SET data = fo_card.data || EXCLUDED.data RETURNING ref_id\"").strip()
        p("включено:", _r275[:120] or "аккаунт собственника не найден")
        if _r275 and "bots:" in _r275:
            open("/opt/fo/bots-275.txt", "w").write(stamp)
except Exception as _e:
    p("275: ошибка", str(_e)[:200])
p("")
p("== ГРУППА ПЛАНОВ → АГЕНТСТВО СОБСТВЕННИКА (270) ==")
try:
    if os.path.exists("/opt/fo/plan-270.txt"):
        raise RuntimeError("уже выполнялось — повторно не переносим и не шлём")
    open("/opt/fo/plan-270.txt", "w").write(stamp)
    _sql270 = """
DO $$
DECLARE o uuid; cid text; ttl text;
BEGIN
  SELECT u.org_id INTO o FROM app_user u WHERE lower(u.email)='nekrasivostore@gmail.com' LIMIT 1;
  IF o IS NULL THEN SELECT org_id INTO o FROM employee GROUP BY org_id ORDER BY count(*) DESC LIMIT 1; END IF;
  SELECT chat_id, title INTO cid, ttl FROM chat WHERE channel='telegram' AND is_active AND chat_id ~ '^-?[0-9]+$' AND title ILIKE '%план%' ORDER BY added_at DESC LIMIT 1;
  IF cid IS NULL THEN RAISE NOTICE 'группа план не найдена'; RETURN; END IF;
  DELETE FROM chat WHERE channel='telegram' AND chat_id=cid AND org_id<>o AND NOT EXISTS (SELECT 1 FROM client_chat cc WHERE cc.chat_pk=chat.id);
  INSERT INTO chat (org_id, channel, chat_id, title) VALUES (o, 'telegram', cid, ttl) ON CONFLICT (org_id, channel, chat_id) DO UPDATE SET title=EXCLUDED.title, is_active=true;
  DELETE FROM fo_card WHERE kind='org' AND ref_id LIKE 'plan:%';
  INSERT INTO fo_card (kind, ref_id, org_id, data) VALUES ('org', 'plan:'||o::text, o,
    jsonb_build_object('chat_id', cid, 'title', ttl, 'send_now', jsonb_build_array(
      jsonb_build_object('what','morning','day','2026-09-30'),
      jsonb_build_object('what','evening','day','2026-09-30','at', to_char((now() at time zone 'Europe/Moscow') + interval '3 minutes', 'HH24:MI')))));
  RAISE NOTICE 'ok org=% chat=% title=%', o, cid, ttl;
END $$;
"""
    open("/tmp/fo_270.sql", "w", encoding="utf-8").write(_sql270)
    _r270 = sh("sudo -u postgres psql -d fo -v ON_ERROR_STOP=1 -f /tmp/fo_270.sql 2>&1")
    p(_r270.strip()[-600:])
    p(sh("sudo -u postgres psql -d fo -Atc \"SELECT 'задач 30.09: '||count(*) FILTER (WHERE plan_date='2026-09-30')||', 01.10: '||count(*) FILTER (WHERE plan_date='2026-10-01') FROM task t JOIN app_user u ON u.org_id=t.org_id AND lower(u.email)='nekrasivostore@gmail.com'\"").strip())
except Exception as _e:
    p("270: ошибка", str(_e)[:300])
p("")
p("== ОЧЕРЕДЬ ОТПРАВОК (268) ==")
try:
    import datetime as _qd
    _at = (_qd.datetime.utcnow() + _qd.timedelta(hours=3, minutes=3)).strftime("%H:%M")
    p("очередь поставлена блоком 270 (среда 30.09: план сейчас, итоги через 3 минуты, %s)" % _at)
except Exception as _e:
    p("очередь: ошибка", str(_e)[:200])
p("")
p("== ГРУППА ПЛАНОВ (266) ==")
try:
    import json as _pj, urllib.request as _pu, urllib.parse as _pp
    _ptok = ""
    for _ln in open("/opt/fo/.env", encoding="utf-8"):
        if _ln.startswith("TG_BOT_TOKEN="): _ptok = _ln.split("=", 1)[1].strip().strip('"').strip("'")
    _pg = sh("sudo -u postgres psql -d fo -Atc \"SELECT chat_id||'|'||title FROM chat WHERE channel='telegram' AND is_active AND chat_id ~ '^-?[0-9]+$' AND title ILIKE '%план%' ORDER BY added_at DESC LIMIT 1\"").strip()
    p("группа с «план» в названии:", _pg.split("|", 1)[1] if "|" in _pg else "не найдена (бота ещё не добавили или группа без номера)")
    if not os.path.exists("/opt/fo/plan-hello.txt") and "|" in _pg:
        open("/opt/fo/plan-hello.txt", "w").write("v81")   # 268: приветствие уже ушло на v81/v82 — больше не повторяем
    if _ptok and "|" in _pg and os.path.exists("/opt/fo/plan-hello.txt"):
        p("приветствие уже отправлялось — повторно не шлём")
    elif _ptok and "|" in _pg:
        _pcid = _pg.split("|", 1)[0]
        open("/opt/fo/plan-hello.txt", "w").write(stamp)
        with _pu.urlopen("https://api.telegram.org/bot%s/getMe" % _ptok, timeout=15) as _r:
            _pme = (_pj.loads(_r.read().decode()) or {}).get("result") or {}
        p("бот сервиса: @%s" % _pme.get("username"))
        _ptxt = ("Бот подключён к этой группе. Сюда будут приходить: в 09:00 — план работы на день по каждому сотруднику "
                 "и артикулы в работу; в 17:55 — итоги дня (✅/❌ по функциям и по работе с РК, по галочкам до 17:40); "
                 "по понедельникам в 09:00 — план планёрок на неделю.")
        _pd = _pp.urlencode({"chat_id": _pcid, "text": _ptxt}).encode()
        with _pu.urlopen(_pu.Request("https://api.telegram.org/bot%s/sendMessage" % _ptok, data=_pd), timeout=15) as _r:
            _pr = _pj.loads(_r.read().decode()) or {}
        p("тестовое сообщение:", "отправлено ✓" if _pr.get("ok") else ("не ушло: " + str(_pr.get("description"))[:200]))
    elif not _ptok:
        p("в .env нет TG_BOT_TOKEN")
except Exception as _e:
    p("группа планов: ошибка", str(_e).replace(_ptok, "***")[:300] if _ptok else str(_e)[:300])

print("\n".join(out))
