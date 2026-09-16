# Фиксация адресов входа. Пишем не на каждый запрос, а раз в десять минут
# на человека — иначе журнал превращается в поток и мешает сам себе.
import io, shutil, datetime, re, sys

P = "/opt/fo/backend/app/deps.py"
s = io.open(P, encoding="utf-8").read()
if "ip_log" in s:
    print("deps.py: уже добавлено"); sys.exit(0)

OLD = "async def current(authorization: str = Header(default=\"\")) -> Principal:"
if OLD not in s:
    print("не нашёл current() в ожидаемом виде — покажите файл, поправлю точечно")
    print([l for l in s.split("\n") if "def current" in l])
    sys.exit(3)

NEW = "async def current(request: Request, authorization: str = Header(default=\"\")) -> Principal:"
s = s.replace(OLD, NEW, 1)

# Импорт Request. Проверяем ИМЕННО строку импорта — в прошлый раз проверка
# смотрела на первые 25 строк файла, а там уже стояло "request: Request"
# из замены выше: импорт не добавился и сервис не поднялся.
imp = re.search(r"^from fastapi import .*$", s, re.M)
if not imp:
    print("нет строки 'from fastapi import' — покажите файл"); sys.exit(5)
if "Request" not in imp.group(0):
    s = s[:imp.start()] + imp.group(0).rstrip() + ", Request" + s[imp.end():]
    print("  импорт Request добавлен")
else:
    print("  импорт Request уже был")

# запись адреса — в самом конце current(), перед возвратом Principal
m = re.search(r"(\n    p = Principal\(data\)\n)", s)
if not m:
    m = re.search(r"(\n    return Principal\([^\n]*\)\n)", s)
if not m:
    print("не нашёл, где current возвращает Principal:")
    print("\n".join([l for l in s.split("\n") if "Principal(" in l]))
    sys.exit(4)

TAIL = '''
    try:
        await _note_ip(request, p)
    except Exception:
        pass
'''
ins = m.group(1)
if "p = Principal(data)" in ins:
    s = s.replace(ins, ins + TAIL, 1)
else:
    s = s.replace(ins, "\n    p = Principal(" + ins.split("Principal(", 1)[1].rstrip("\n)") + ")\n"
                  + TAIL + "    return p\n", 1)

HELPER = '''

# ── адрес, с которого зашли ──────────────────────────────────
_ip_seen = {}          # user_id → когда последний раз записали

def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip") or ""
    if real:
        return real.strip()
    return getattr(getattr(request, "client", None), "host", "") or ""


async def _note_ip(request, p) -> None:
    """Раз в десять минут на человека: обновляем последний адрес и пишем в журнал."""
    import time
    ip = _client_ip(request)
    if not ip or not getattr(p, "user_id", None):
        return
    now = time.time()
    was = _ip_seen.get(p.user_id)
    if was and now - was < 600:
        return
    _ip_seen[p.user_id] = now
    ua = (request.headers.get("user-agent") or "")[:300]
    try:
        from .db import pool as _pool
    except Exception:
        from db import pool as _pool
    async with _pool().acquire() as c:
        prev = await c.fetchval("SELECT last_ip FROM app_user WHERE id=$1", p.user_id)
        await c.execute("UPDATE app_user SET last_ip=$2, last_seen=now() WHERE id=$1",
                        p.user_id, ip)
        if prev != ip:
            em = await c.fetchval("SELECT email FROM app_user WHERE id=$1", p.user_id)
            await c.execute(
                """INSERT INTO ip_log (user_id, org_id, email, ip, ua)
                   VALUES ($1, $2, $3, $4, $5)""",
                p.user_id, getattr(p, "org_id", None), em, ip, ua)
'''

shutil.copy(P, P + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
io.open(P, "w", encoding="utf-8").write(s.rstrip("\n") + "\n" + HELPER)
print("deps.py: запись адресов входа добавлена")
