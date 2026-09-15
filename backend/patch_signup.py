# -*- coding: utf-8 -*-
"""Правка регистрации: код агентства, роль собственника, честный запасной путь.

1) Создатель рабочего пространства получает роль «собственник», а не «директор».
2) _issue_code сообщает, ушло письмо или нет.
3) Если почта на сервере не настроена, код первого входа возвращается в ответе
   и показывается человеку на экране — вместо того чтобы молча пропасть.
   Как только SMTP_PASS заполнен, код в ответе больше не появляется.
"""
import io, re, sys, shutil, datetime

P = "/opt/fo/backend/app/routers/signup.py"
src = io.open(P, encoding="utf-8").read()
orig = src

# ── 1. роль создателя пространства ──
if '"director"' in src:
    src = src.replace('"director"', '"owner"', 1)

# ── 2. _issue_code возвращает (code, sent) ──
old_issue = """    await send_login_code(email, code)"""
new_issue = """    sent = await send_login_code(email, code)
    return code, bool(sent)"""
if old_issue in src and "return code, bool(sent)" not in src:
    src = src.replace(old_issue, new_issue, 1)

# ── 3. /register: отдаём код, если письмо не ушло ──
old_reg = """        await _issue_code(conn, uid, body.email, "first_login")
        return {"ok": True, "workspace": row["org_name"],
                "project": row["client_name"], "next": "verify"}"""
new_reg = """        code, sent = await _issue_code(conn, uid, body.email, "first_login")
        out = {"ok": True, "workspace": row["org_name"],
               "project": row["client_name"], "next": "verify", "mail_sent": sent}
        if not sent:
            out["code_shown"] = code
        return out"""
if old_reg in src:
    src = src.replace(old_reg, new_reg, 1)

# ── 4. /workspace: то же самое ──
old_ws = """        await _issue_code(conn, uid, body.email, "first_login")
    return {"ok": True, "workspace": body.org_name,
            "invite_code": code, "next": "verify"}"""
new_ws = """        code2, sent = await _issue_code(conn, uid, body.email, "first_login")
    out = {"ok": True, "workspace": body.org_name,
           "invite_code": code, "next": "verify", "mail_sent": sent}
    if not sent:
        out["code_shown"] = code2
    return out"""
if old_ws in src:
    src = src.replace(old_ws, new_ws, 1)

if src == orig:
    print("НИЧЕГО НЕ ИЗМЕНЕНО — проверьте шаблоны")
    sys.exit(1)

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy(P, P + "." + stamp + ".bak")
io.open(P, "w", encoding="utf-8").write(src)
print("готово. бэкап:", P + "." + stamp + ".bak")
for probe in ('"owner"', "return code, bool(sent)", "code_shown"):
    print(("  есть " if probe in src else "  НЕТ  ") + probe)
