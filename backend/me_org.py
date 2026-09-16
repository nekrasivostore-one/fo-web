# Своя карточка агентства: собственник видит и правит реквизиты, сервис —
# пробный период. Живёт в refs.py, потому что туда фронт уже ходит.
import io, shutil, datetime, sys

P = "/opt/fo/backend/app/routers/refs.py"
s = io.open(P, encoding="utf-8").read()
if "/org" in s and "me_org" in s:
    print("refs.py: уже добавлено"); sys.exit(0)

ADD = '''

# ── Карточка своего агентства ────────────────────────────────
# Собственнику и директору — правка реквизитов; всем остальным
# внутри агентства — только чтение. Сюда же фронт ходит за
# пробным периодом, чтобы не выдумывать суммы в шапке.

@router.get("/org")
async def me_org(p: Principal = Depends(current)):
    async with pool().acquire() as c:
        o = await c.fetchrow("""SELECT id, name, inn, plan, invite_code, trial_ends_at,
                                       trial_extra_days, trial_note, seats_paid, created_at
                                FROM org WHERE id = $1""", p.org_id)
        if not o:
            raise HTTPException(404, "агентства нет")
        paid = await c.fetchval(
            "SELECT coalesce(sum(amount),0) FROM payment WHERE org_id=$1 AND status='paid'",
            p.org_id)
        users = await c.fetchval(
            "SELECT count(*) FROM app_user WHERE org_id=$1 AND is_active", p.org_id)
    d = dict(o)
    d["paid"] = float(paid or 0)
    d["users"] = users
    return d


class MeOrgIn(BaseModel):
    name:  str | None = None
    inn:   str | None = None
    addr:  str | None = None
    phone: str | None = None


@router.post("/org")
async def me_org_save(body: MeOrgIn, p: Principal = Depends(max_level(1))):
    """Реквизиты правит собственник или директор — уровни 0 и 1."""
    sets, vals = [], []
    for k in ("name", "inn"):
        v = getattr(body, k)
        if v is not None:
            vals.append(v.strip()); sets.append("%s=$%d" % (k, len(vals) + 1))
    if not sets:
        return {"ok": True, "changed": 0}
    async with pool().acquire() as c:
        await c.execute("UPDATE org SET " + ", ".join(sets) + " WHERE id=$1", p.org_id, *vals)
    return {"ok": True, "changed": len(sets)}
'''

need = []
if "from pydantic import BaseModel" not in s and "BaseModel" not in s:
    need.append("from pydantic import BaseModel")
if "HTTPException" not in s:
    need.append("from fastapi import HTTPException")
head = ("\n".join(need) + "\n") if need else ""

shutil.copy(P, P + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
io.open(P, "w", encoding="utf-8").write(head + s.rstrip("\n") + "\n" + ADD)
print("refs.py: добавлена карточка своего агентства", "(+импорты: " + ", ".join(need) + ")" if need else "")
