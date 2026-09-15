# -*- coding: utf-8 -*-
"""Добор: /register тоже отдаёт код, когда письмо не ушло. Через регулярку,
чтобы не зависеть от точных отступов."""
import io, re, sys, shutil, datetime

P = "/opt/fo/backend/app/routers/signup.py"
src = io.open(P, encoding="utf-8").read()
orig = src

if "code_shown" in src.split("@router.post(\"/register\")")[1].split("@router.post(\"/workspace\")")[0]:
    print("в /register уже есть code_shown — ничего не делаю")
    sys.exit(0)

# await _issue_code(...)  ->  code, sent = await _issue_code(...)
src = re.sub(
    r'(\n(\s+))await _issue_code\(conn, uid, body\.email, "first_login"\)',
    r'\1code, sent = await _issue_code(conn, uid, body.email, "first_login")',
    src, count=1)

# return {...} в /register  ->  сборка словаря с code_shown
m = re.search(
    r'\n(\s+)return \{"ok": True, "workspace": row\["org_name"\],\s*\n\s*"project": row\["client_name"\], "next": "verify"\}',
    src)
if not m:
    print("не нашёл return в /register"); sys.exit(1)
ind = m.group(1)
new = (
    "\n" + ind + 'out = {"ok": True, "workspace": row["org_name"],\n'
    + ind + '       "project": row["client_name"], "next": "verify",\n'
    + ind + '       "mail_sent": sent}\n'
    + ind + 'if not sent:\n'
    + ind + '    out["code_shown"] = code\n'
    + ind + 'return out'
)
src = src[:m.start()] + new + src[m.end():]

if src == orig:
    print("ничего не изменено"); sys.exit(1)

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy(P, P + "." + stamp + ".bak")
io.open(P, "w", encoding="utf-8").write(src)
import py_compile
py_compile.compile(P, doraise=True)
print("готово, синтаксис проверен. бэкап:", P + "." + stamp + ".bak")
