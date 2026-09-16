# Две правки на сервере.
#
# 1. auth.py::_user — SELECT без ORDER BY возвращал ПРОИЗВОЛЬНУЮ строку, если
#    у почты оказалось несколько аккаунтов. Код входа выписывался одному
#    аккаунту, а проверялся у другого — отсюда «код неверен или истёк»
#    на свежем коде. Берём самый новый аккаунт.
#
# 2. signup.py::workspace — повторная регистрация с той же почтой заводила
#    ВТОРОЕ агентство и второй аккаунт. Теперь: если первый вход не завершён,
#    переиспользуем аккаунт и просто шлём новый код; если завершён — 409.
import io, re, shutil, datetime, sys

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
changed = []

# ── 1. _user ──────────────────────────────────────────────────
A = "/opt/fo/backend/app/routers/auth.py"
s = io.open(A, encoding="utf-8").read()
old_user = '''"""SELECT u.*, r.level FROM app_user u
           JOIN role r ON r.code = u.role_code
           WHERE u.email = $1 AND u.is_active""", email)'''
new_user = '''"""SELECT u.*, r.level FROM app_user u
           JOIN role r ON r.code = u.role_code
           WHERE u.email = $1 AND u.is_active
           ORDER BY u.created_at DESC LIMIT 1""", email)'''
if "ORDER BY u.created_at DESC LIMIT 1" in s:
    print("auth.py: уже исправлен")
elif old_user in s:
    shutil.copy(A, A + ".bak-" + stamp)
    io.open(A, "w", encoding="utf-8").write(s.replace(old_user, new_user, 1))
    changed.append("auth.py::_user")
else:
    # запасной путь: вставляем ORDER BY перед закрытием запроса в _user
    lines = s.split("\n")
    i0 = None
    for i, l in enumerate(lines):
        if l.startswith("async def _user("):
            i0 = i; break
    if i0 is None:
        print("auth.py: НЕ НАШЁЛ _user"); sys.exit(1)
    for i in range(i0, min(i0 + 12, len(lines))):
        if "u.is_active" in lines[i]:
            lines[i] = lines[i].replace(
                'u.is_active"""',
                'u.is_active\n           ORDER BY u.created_at DESC LIMIT 1"""')
            shutil.copy(A, A + ".bak-" + stamp)
            io.open(A, "w", encoding="utf-8").write("\n".join(lines))
            changed.append("auth.py::_user (запасной путь)")
            break
    else:
        print("auth.py: НЕ НАШЁЛ строку is_active"); sys.exit(1)

# ── 2. workspace ──────────────────────────────────────────────
S = "/opt/fo/backend/app/routers/signup.py"
t = io.open(S, encoding="utf-8").read()
if "reused" in t:
    print("signup.py: уже исправлен")
else:
    i0 = t.index('@router.post("/workspace")')
    i1 = t.index('@router.get("/invite/{code}")')
    NEW = '''@router.post("/workspace")
async def workspace(body: WorkspaceIn):
    """Регистрация собственника: создаём организацию и владельца.

    Если почта уже заведена — второе агентство НЕ создаём.
    Не завершённый первый вход просто получает новый код."""
    async with pool().acquire() as conn:
        prev = await conn.fetchrow(
            """SELECT u.id, u.first_login, u.org_id,
                      o.name AS org_name, o.invite_code
               FROM app_user u JOIN org o ON o.id = u.org_id
               WHERE u.email = $1 AND u.is_active
               ORDER BY u.created_at DESC LIMIT 1""", body.email)

        if prev and not prev["first_login"]:
            raise HTTPException(
                409, "Эта почта уже зарегистрирована — войдите по паролю")

        if prev:
            name = (body.org_name or "").strip() or prev["org_name"]
            async with conn.transaction():
                if name != prev["org_name"]:
                    await conn.execute(
                        "UPDATE org SET name=$2 WHERE id=$1", prev["org_id"], name)
                code2, sent = await _issue_code(
                    conn, prev["id"], body.email, "first_login")
            out = {"ok": True, "workspace": name,
                   "invite_code": prev["invite_code"],
                   "next": "verify", "mail_sent": sent, "reused": True}
            if not sent:
                out["code_shown"] = code2
            return out

        async with conn.transaction():
            org_id = await conn.fetchval(
                """INSERT INTO org (name, plan, invite_code)
                   VALUES ($1,'trial',
                     upper(substr(replace(gen_random_uuid()::text,'-',''),1,6)))
                   RETURNING id""", body.org_name.strip())
            uid = await _make_user(conn, org_id, body.email, "owner",
                                   body.email.split("@")[0])
            code = await conn.fetchval(
                "SELECT invite_code FROM org WHERE id=$1", org_id)
            code2, sent = await _issue_code(
                conn, uid, body.email, "first_login")
    out = {"ok": True, "workspace": body.org_name,
           "invite_code": code, "next": "verify", "mail_sent": sent}
    if not sent:
        out["code_shown"] = code2
    return out


'''
    shutil.copy(S, S + ".bak-" + stamp)
    io.open(S, "w", encoding="utf-8").write(t[:i0] + NEW + t[i1:])
    changed.append("signup.py::workspace")

print("изменено:", ", ".join(changed) if changed else "ничего")
