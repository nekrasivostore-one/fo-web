# -*- coding: utf-8 -*-
"""/register тоже отдаёт код первого входа, когда письмо не ушло.
Работает по строкам, без регулярок и без зависимости от переносов."""
import io, shutil, datetime, py_compile, sys

P = "/opt/fo/backend/app/routers/signup.py"
L = io.open(P, encoding="utf-8").read().split("\n")

# уже сделано?
head = "\n".join(L)
reg = head.split('@router.post("/register")')[1].split('@router.post("/workspace")')[0]
if "code_shown" in reg:
    print("в /register уже есть — ок"); sys.exit(0)

# 1) строка вызова _issue_code внутри /register
call = None
for n, l in enumerate(L):
    if '_issue_code(conn, uid, body.email, "first_login")' in l and "=" not in l.split("await")[0]:
        call = n; break
if call is None:
    print("не нашёл вызов _issue_code"); sys.exit(1)
ind = L[call][:len(L[call]) - len(L[call].lstrip())]
L[call] = ind + 'code, sent = await _issue_code(conn, uid, body.email, "first_login")'

# 2) return сразу после него
ret = None
for n in range(call + 1, min(call + 6, len(L))):
    if 'return {"ok": True' in L[n]:
        ret = n; break
if ret is None:
    print("не нашёл return после вызова"); sys.exit(1)
# сколько строк занимает return (до строки, закрывающей словарь)
end = ret
while "}" not in L[end]:
    end += 1
rind = L[ret][:len(L[ret]) - len(L[ret].lstrip())]
block = [
    rind + 'out = {"ok": True, "workspace": row["org_name"],',
    rind + '       "project": row["client_name"], "next": "verify",',
    rind + '       "mail_sent": sent}',
    rind + 'if not sent:',
    rind + '    out["code_shown"] = code',
    rind + 'return out',
]
L[ret:end + 1] = block

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy(P, P + "." + stamp + ".bak")
io.open(P, "w", encoding="utf-8").write("\n".join(L))
py_compile.compile(P, doraise=True)
print("готово, синтаксис ок. бэкап:", P + "." + stamp + ".bak")
