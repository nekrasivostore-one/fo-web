# Панель владельца сервиса: сводка по всем агентствам.
# Видит только роль admin (уровень 0) — внутри агентства такого экрана нет.
import io, shutil, datetime, sys

P = "/opt/fo/backend/app/routers/admin.py"
s = io.open(P, encoding="utf-8").read()
if "/service/orgs" in s:
    print("admin.py: уже добавлено"); sys.exit(0)

ADD = '''

# ── Панель владельца сервиса ─────────────────────────────────
# Всё, что ниже, видит только admin (уровень 0): это не про одно
# агентство, а про сервис целиком.

@router.get("/service/orgs")
async def service_orgs(p: Principal = Depends(max_level(0))):
    """Все агентства: люди, клиенты, задачи, деньги, вовлечённость."""
    async with pool().acquire() as c:
        rows = await c.fetch("""
            SELECT o.id, o.name, o.inn, o.plan, o.invite_code,
                   o.trial_ends_at, o.seats_paid, o.created_at,
                   (SELECT count(*) FROM app_user u
                      WHERE u.org_id = o.id AND u.is_active) AS users,
                   (SELECT count(*) FROM app_user u
                      WHERE u.org_id = o.id AND u.first_login) AS pending,
                   (SELECT u.email FROM app_user u
                      WHERE u.org_id = o.id AND u.role_code = 'owner'
                      ORDER BY u.created_at LIMIT 1) AS owner_email,
                   (SELECT max(u.created_at) FROM app_user u
                      WHERE u.org_id = o.id) AS last_join,
                   (SELECT count(*) FROM client cl WHERE cl.org_id = o.id) AS clients,
                   (SELECT count(*) FROM employee e WHERE e.org_id = o.id) AS staff,
                   (SELECT count(*) FROM task t WHERE t.org_id = o.id) AS tasks,
                   (SELECT coalesce(sum(pm.amount), 0) FROM payment pm
                      WHERE pm.org_id = o.id AND pm.status = 'paid') AS paid,
                   (SELECT coalesce(sum(pm.amount), 0) FROM payment pm
                      WHERE pm.org_id = o.id AND pm.status <> 'paid') AS due,
                   (SELECT min(pm.due_date) FROM payment pm
                      WHERE pm.org_id = o.id AND pm.status <> 'paid'
                        AND pm.due_date >= current_date) AS next_due,
                   (SELECT max(pm.paid_at) FROM payment pm
                      WHERE pm.org_id = o.id AND pm.paid_at IS NOT NULL) AS last_paid
            FROM org o ORDER BY o.created_at DESC""")
    out = []
    for r in rows:
        d = dict(r)
        users = d.get("users") or 0
        pend = d.get("pending") or 0
        live = max(0, users - pend)
        # вовлечённость: сколько приглашённых реально дошли до работы
        # и есть ли в агентстве хоть какая-то жизнь
        share = round(live / users * 100) if users else 0
        alive = 0
        if d.get("clients"): alive += 25
        if d.get("staff"):   alive += 15
        if d.get("tasks"):   alive += 20
        d["engagement"] = min(100, round(share * 0.4) + alive)
        d["live_users"] = live
        out.append(d)
    return out


@router.get("/service/users")
async def service_users(org_id: str = "", p: Principal = Depends(max_level(0))):
    """Люди по всем агентствам или по одному."""
    sql = """SELECT u.id, u.email, u.role_code, r.title AS role_title, r.level,
                    u.is_active, u.first_login, u.created_at, u.last_ip,
                    o.id AS org_id, o.name AS org_name
             FROM app_user u
             JOIN role r ON r.code = u.role_code
             JOIN org  o ON o.id  = u.org_id"""
    async with pool().acquire() as c:
        if org_id:
            rows = await c.fetch(sql + " WHERE o.id = $1 ORDER BY r.level, u.email", org_id)
        else:
            rows = await c.fetch(sql + " ORDER BY o.created_at DESC, r.level, u.email")
    return [dict(r) for r in rows]


class OrgCardIn(BaseModel):
    name: str | None = None
    inn: str | None = None
    plan: str | None = None
    seats_paid: int | None = None


@router.post("/service/orgs/{org_id}")
async def service_org_edit(org_id: str, body: OrgCardIn,
                           p: Principal = Depends(max_level(0))):
    """Карточка юридического лица: название, ИНН, тариф, оплаченные места."""
    sets, vals = [], []
    for k in ("name", "inn", "plan", "seats_paid"):
        v = getattr(body, k)
        if v is not None:
            vals.append(v); sets.append("%s=$%d" % (k, len(vals) + 1))
    if not sets:
        return {"ok": True, "changed": 0}
    async with pool().acquire() as c:
        await c.execute("UPDATE org SET " + ", ".join(sets) + " WHERE id=$1",
                        org_id, *vals)
    return {"ok": True, "changed": len(sets)}


class SvcLevelIn(BaseModel):
    role_code: str


@router.post("/service/users/{user_id}/role")
async def service_set_role(user_id: str, body: SvcLevelIn,
                           p: Principal = Depends(max_level(0))):
    """Админ выдаёт уровень доступа любому человеку в любом агентстве."""
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM role WHERE code=$1", body.role_code)
        if not ok:
            raise HTTPException(404, "нет такой роли")
        if body.role_code == "owner":
            org = await c.fetchval("SELECT org_id FROM app_user WHERE id=$1", user_id)
            has = await c.fetchval(
                """SELECT count(*) FROM app_user
                   WHERE org_id=$1 AND role_code='owner' AND id<>$2""", org, user_id)
            if has:
                raise HTTPException(409, "у агентства уже есть собственник")
        await c.execute("UPDATE app_user SET role_code=$2 WHERE id=$1",
                        user_id, body.role_code)
    return {"ok": True}
'''

shutil.copy(P, P + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
io.open(P, "w", encoding="utf-8").write(s.rstrip("\n") + "\n" + ADD)
print("admin.py: добавлена панель сервиса")
