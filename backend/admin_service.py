# Панель владельца сервиса: сводка по всем агентствам.
# Видит только роль admin (уровень 0) — внутри агентства такого экрана нет.
import io, shutil, datetime, sys

P = "/opt/fo/backend/app/routers/admin.py"
s = io.open(P, encoding="utf-8").read()
if "/service/orgs" in s:
    print("admin.py: уже добавлено"); sys.exit(0)

SQL = """
ALTER TABLE org ADD COLUMN IF NOT EXISTS trial_extra_days int NOT NULL DEFAULT 0;
ALTER TABLE org ADD COLUMN IF NOT EXISTS trial_note text;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_ip text;
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS last_seen timestamptz;
CREATE TABLE IF NOT EXISTS ip_log (
  id       bigserial PRIMARY KEY,
  user_id  uuid,
  org_id   uuid,
  email    text,
  ip       text,
  ua       text,
  at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ip_log_at_idx  ON ip_log (at DESC);
CREATE INDEX IF NOT EXISTS ip_log_org_idx ON ip_log (org_id, at DESC);
"""

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


@router.get("/service/roles")
async def service_roles(p: Principal = Depends(max_level(0))):
    """Список ролей сервиса — из него админ выбирает уровень доступа."""
    async with pool().acquire() as c:
        rows = await c.fetch("SELECT code, title, level FROM role ORDER BY level")
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


class TrialIn(BaseModel):
    days: int | None = None
    until: str | None = None
    note: str | None = None


@router.post("/service/orgs/{org_id}/trial")
async def service_trial(org_id: str, body: TrialIn,
                        p: Principal = Depends(max_level(0))):
    """Продлить пробный период: на N дней (1..31) или до конкретной даты.

    Каждое продление прибавляется к trial_extra_days — это и есть
    несмываемая пометка «сидит бесплатно дольше обычного»."""
    import datetime as _dt
    async with pool().acquire() as c:
        cur = await c.fetchrow(
            "SELECT trial_ends_at, trial_extra_days FROM org WHERE id=$1", org_id)
        if not cur:
            raise HTTPException(404, "нет такого агентства")
        today = _dt.date.today()
        base = cur["trial_ends_at"]
        if hasattr(base, "date"):
            base = base.date()
        if not base or base < today:
            base = today

        if body.until:
            try:
                new_end = _dt.date.fromisoformat(body.until[:10])
            except ValueError:
                raise HTTPException(400, "дата в формате ГГГГ-ММ-ДД")
            if new_end <= today:
                raise HTTPException(400, "дата должна быть в будущем")
            if (new_end - today).days > 365:
                raise HTTPException(400, "больше года пробного периода — это уже тариф")
            add_days = max(0, (new_end - base).days)
        else:
            d = int(body.days or 0)
            if d < 1 or d > 31:
                raise HTTPException(400, "продлевать можно от 1 дня до 31")
            new_end = base + _dt.timedelta(days=d)
            add_days = d

        note = (body.note or "").strip() or None
        extra = int(cur["trial_extra_days"] or 0) + add_days
        await c.execute(
            """UPDATE org SET trial_ends_at=$2, trial_extra_days=$3,
                              trial_note=coalesce($4, trial_note)
               WHERE id=$1""", org_id, new_end, extra, note)
    return {"ok": True, "trial_ends_at": new_end.isoformat(),
            "trial_extra_days": extra, "trial_note": note}


@router.get("/service/ips")
async def service_ips(org_id: str = "", limit: int = 40,
                      p: Principal = Depends(max_level(0))):
    """С каких адресов заходят в сервис."""
    limit = max(1, min(200, int(limit or 40)))
    async with pool().acquire() as c:
        if org_id:
            rows = await c.fetch(
                """SELECT l.ip, l.email, l.at, o.name AS org_name
                   FROM ip_log l LEFT JOIN org o ON o.id = l.org_id
                   WHERE l.org_id = $1 ORDER BY l.at DESC LIMIT $2""", org_id, limit)
        else:
            rows = await c.fetch(
                """SELECT l.ip, l.email, l.at, o.name AS org_name
                   FROM ip_log l LEFT JOIN org o ON o.id = l.org_id
                   ORDER BY l.at DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


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

print("SQL, который надо выполнить отдельно:")
print(SQL)

shutil.copy(P, P + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
io.open(P, "w", encoding="utf-8").write(s.rstrip("\n") + "\n" + ADD)
print("admin.py: добавлена панель сервиса")
