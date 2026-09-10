"""Куда и когда сообщать: правила по чатам кабинета, шаблоны, отложенная очередь."""
import os
from datetime import datetime, timedelta, time as dtime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import pool
from ..deps import current, max_level, Principal
from ..notify import send_telegram

router = APIRouter(prefix="/routing", tags=["Куда сообщать"])

# Событие = шаг в работе. Порядок тот же, что на экране кабинета.
EVENTS = {
    "plan_day":    "План на день",
    "fact_day":    "Итоги дня",
    "task_new":    "Новая задача",
    "task_form":   "Отчёт по форме",
    "approve_req": "Запрос на согласование",
    "approve_res": "Согласовано или отклонено",
    "overdue":     "Просрочка дедлайна",
    "handover":    "Передача задачи",
    "meet_res":    "Итоги планёрки",
}
# Клиенту по умолчанию — только результат, без внутренней кухни.
CLIENT_DEFAULT = {"fact_day", "task_form", "approve_req", "approve_res"}
DEFAULT_TIME = {"plan_day": "10:00", "fact_day": "19:00"}


def _can_edit(p: Principal) -> bool:
    """Настраивают собственник, РМ и главный менеджер."""
    return p.level <= 5


class RuleIn(BaseModel):
    chat_pk: int
    event: str
    enabled: bool = True
    when_mode: str = Field(default="ready", pattern="^(ready|time)$")
    at_time: Optional[str] = None


class RulesIn(BaseModel):
    rules: List[RuleIn]


@router.get("/events")
async def events(p: Principal = Depends(current)):
    """Список событий и что по умолчанию уходит клиенту."""
    return {"события": EVENTS,
            "клиенту_по_умолчанию": sorted(CLIENT_DEFAULT),
            "время_по_умолчанию": DEFAULT_TIME}


@router.get("/{client_id}")
async def get_rules(client_id: str, p: Principal = Depends(current)):
    """Матрица «событие × чат» по кабинету. Чего нет в базе — отдаём умолчанием."""
    async with pool().acquire() as c:
        chats = await c.fetch(
            """SELECT ch.id, ch.title, cc.kind
                 FROM chat ch
                 JOIN client_chat cc ON cc.chat_pk = ch.id
                WHERE cc.client_id = $1 AND ch.org_id = $2 AND ch.is_active
             ORDER BY ch.title""", client_id, p.org_id)
        rows = await c.fetch(
            "SELECT chat_pk, event, enabled, when_mode, at_time FROM chat_route WHERE client_id=$1",
            client_id)
        org = await c.fetchrow("SELECT work_from, work_to FROM org WHERE id=$1", p.org_id)

    saved = {(r["chat_pk"], r["event"]): r for r in rows}
    out = []
    for ev in EVENTS:
        cells = []
        for ch in chats:
            r = saved.get((ch["id"], ev))
            if r:
                cells.append({"чат": ch["id"], "название": ch["title"], "роль": ch["kind"],
                              "включено": r["enabled"], "когда": r["when_mode"],
                              "время": r["at_time"].strftime("%H:%M") if r["at_time"] else None})
            else:
                on = (ev in CLIENT_DEFAULT) if ch["kind"] == "client" else True
                t = DEFAULT_TIME.get(ev)
                cells.append({"чат": ch["id"], "название": ch["title"], "роль": ch["kind"],
                              "включено": on, "когда": "time" if t else "ready", "время": t})
        out.append({"событие": ev, "название": EVENTS[ev], "чаты": cells})
    return {"кабинет": client_id, "матрица": out,
            "рабочее_окно": {"с": str(org["work_from"])[:5] if org else "08:00",
                             "до": str(org["work_to"])[:5] if org else "18:00"},
            "можно_менять": _can_edit(p)}


@router.put("/{client_id}")
async def put_rules(client_id: str, body: RulesIn, p: Principal = Depends(max_level(5))):
    """Сохранить галочки и время. Меняют собственник, РМ и главный менеджер."""
    if not _can_edit(p):
        raise HTTPException(403, "менять может собственник, РМ или главный менеджер")
    bad = [r.event for r in body.rules if r.event not in EVENTS]
    if bad:
        raise HTTPException(400, "неизвестное событие: " + ", ".join(sorted(set(bad))))
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM client WHERE id=$1 AND org_id=$2", client_id, p.org_id)
        if not ok:
            raise HTTPException(404, "кабинет не найден")
        for r in body.rules:
            at = None
            if r.when_mode == "time" and r.at_time:
                hh, _, mm = r.at_time.partition(":")
                at = dtime(int(hh), int(mm or 0))
            await c.execute(
                """INSERT INTO chat_route (org_id, client_id, chat_pk, event, enabled, when_mode, at_time, updated_by)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT (client_id, chat_pk, event) DO UPDATE
                   SET enabled=EXCLUDED.enabled, when_mode=EXCLUDED.when_mode,
                       at_time=EXCLUDED.at_time, updated_at=now(), updated_by=EXCLUDED.updated_by""",
                p.org_id, client_id, r.chat_pk, r.event, r.enabled, r.when_mode, at, p.user_id)
    return {"сохранено": len(body.rules)}


# ---------- отправка с учётом правил и рабочего окна ----------

def _next_slot(now: datetime, work_from: dtime, work_to: dtime, at: Optional[dtime]) -> datetime:
    """Когда реально отправить: сразу, если внутри окна, иначе ближайшее рабочее утро."""
    target = now if at is None else now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if at is not None and target < now:
        target += timedelta(days=1)
    while True:
        t = target.time()
        if target.weekday() >= 5:                       # суббота, воскресенье
            target = (target + timedelta(days=1)).replace(
                hour=work_from.hour, minute=work_from.minute, second=0, microsecond=0)
            continue
        if t < work_from:
            target = target.replace(hour=work_from.hour, minute=work_from.minute, second=0, microsecond=0)
        elif t > work_to:
            target = (target + timedelta(days=1)).replace(
                hour=work_from.hour, minute=work_from.minute, second=0, microsecond=0)
            continue
        return target


async def dispatch(org_id, client_id, event: str, text_by_kind: dict):
    """Разослать событие по правилам кабинета. text_by_kind: {'client': '...', 'mpv': '...'}"""
    if event not in EVENTS:
        return {"отправлено": 0, "отложено": 0}
    now = datetime.now()
    sent = queued = 0
    async with pool().acquire() as c:
        org = await c.fetchrow("SELECT work_from, work_to FROM org WHERE id=$1", org_id)
        wf = org["work_from"] if org else dtime(8, 0)
        wt = org["work_to"] if org else dtime(18, 0)
        chats = await c.fetch(
            """SELECT ch.id, ch.chat_id, cc.kind FROM chat ch
                 JOIN client_chat cc ON cc.chat_pk = ch.id
                WHERE cc.client_id=$1 AND ch.org_id=$2 AND ch.is_active""", client_id, org_id)
        rules = {r["chat_pk"]: r for r in await c.fetch(
            "SELECT chat_pk, enabled, when_mode, at_time FROM chat_route WHERE client_id=$1 AND event=$2",
            client_id, event)}

        for ch in chats:
            r = rules.get(ch["id"])
            if r is not None:
                if not r["enabled"]:
                    continue
                mode, at = r["when_mode"], r["at_time"]
            else:
                on = (event in CLIENT_DEFAULT) if ch["kind"] == "client" else True
                if not on:
                    continue
                d = DEFAULT_TIME.get(event)
                mode = "time" if d else "ready"
                at = dtime(int(d[:2]), int(d[3:])) if d else None

            body = text_by_kind.get(ch["kind"]) or text_by_kind.get("mpv") or ""
            if not body:
                continue
            slot = _next_slot(now, wf, wt, at if mode == "time" else None)
            if mode == "ready" and slot <= now:
                await send_telegram(ch["chat_id"], body)
                sent += 1
            else:
                await c.execute(
                    "INSERT INTO outbox (org_id, chat_pk, event, body, send_after) VALUES ($1,$2,$3,$4,$5)",
                    org_id, ch["id"], event, body, slot)
                queued += 1
    return {"отправлено": sent, "отложено": queued}


@router.post("/flush")
async def flush(p: Principal = Depends(max_level(3))):
    """Разослать то, что дождалось своего времени. Дёргается по расписанию."""
    now = datetime.now()
    done = 0
    async with pool().acquire() as c:
        rows = await c.fetch(
            """SELECT o.id, o.body, ch.chat_id FROM outbox o
                 JOIN chat ch ON ch.id = o.chat_pk
                WHERE o.sent_at IS NULL AND o.send_after <= $1 AND o.org_id = $2
             ORDER BY o.send_after LIMIT 100""", now, p.org_id)
        for r in rows:
            ok = await send_telegram(r["chat_id"], r["body"])
            await c.execute(
                "UPDATE outbox SET sent_at=$1, error=$2 WHERE id=$3",
                now if ok else None, None if ok else "telegram отказал", r["id"])
            done += 1 if ok else 0
    return {"разослано": done, "в_очереди_было": len(rows)}


# ---------- чаты кабинета: привязка, отправка, шаблоны ----------

class ChatIn(BaseModel):
    title: str
    chat_id: str                      # id группы в Telegram, например -1001234567890
    kind: str = Field(default="mpv", pattern="^(client|mpv|internal)$")


@router.get("/{client_id}/chats")
async def list_chats(client_id: str, p: Principal = Depends(current)):
    """Какие чаты привязаны к кабинету."""
    async with pool().acquire() as c:
        rows = await c.fetch(
            """SELECT ch.id, ch.title, ch.chat_id, cc.kind, ch.is_active
                 FROM chat ch JOIN client_chat cc ON cc.chat_pk = ch.id
                WHERE cc.client_id=$1 AND ch.org_id=$2 ORDER BY ch.title""",
            client_id, p.org_id)
    return {"кабинет": client_id,
            "чаты": [{"id": r["id"], "название": r["title"], "телеграм": r["chat_id"],
                      "роль": r["kind"], "активен": r["is_active"]} for r in rows]}


@router.post("/{client_id}/chats")
async def add_chat(client_id: str, body: ChatIn, p: Principal = Depends(max_level(5))):
    """Привязать чат к кабинету. Если такой chat_id уже есть — переиспользуем."""
    async with pool().acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM client WHERE id=$1 AND org_id=$2", client_id, p.org_id)
        if not ok:
            raise HTTPException(404, "кабинет не найден")
        pk = await c.fetchval("SELECT id FROM chat WHERE org_id=$1 AND chat_id=$2",
                              p.org_id, body.chat_id)
        if pk is None:
            pk = await c.fetchval(
                "INSERT INTO chat (org_id, chat_id, title, is_active) VALUES ($1,$2,$3,true) RETURNING id",
                p.org_id, body.chat_id, body.title)
        else:
            await c.execute("UPDATE chat SET title=$1, is_active=true WHERE id=$2", body.title, pk)
        await c.execute(
            """INSERT INTO client_chat (client_id, chat_pk, kind) VALUES ($1,$2,$3)
               ON CONFLICT (client_id, chat_pk) DO UPDATE SET kind=EXCLUDED.kind""",
            client_id, pk, body.kind)
    return {"привязан": pk, "название": body.title, "роль": body.kind}


@router.delete("/{client_id}/chats/{chat_pk}")
async def del_chat(client_id: str, chat_pk: int, p: Principal = Depends(max_level(5))):
    """Отвязать чат от кабинета. Сам чат и история правил остаются."""
    async with pool().acquire() as c:
        await c.execute("DELETE FROM client_chat WHERE client_id=$1 AND chat_pk=$2", client_id, chat_pk)
    return {"отвязан": chat_pk}


class SendIn(BaseModel):
    chat_pk: int
    text: str


@router.post("/send")
async def send_now(body: SendIn, p: Principal = Depends(max_level(5))):
    """Отправить готовый текст в чат — этим уходят доступы новым участникам кабинета."""
    async with pool().acquire() as c:
        row = await c.fetchrow("SELECT chat_id, title FROM chat WHERE id=$1 AND org_id=$2",
                               body.chat_pk, p.org_id)
    if not row:
        raise HTTPException(404, "чат не найден")
    ok = await send_telegram(row["chat_id"], body.text)
    if not ok:
        raise HTTPException(502, "Telegram не принял сообщение")
    return {"отправлено": True, "чат": row["title"]}


class TplIn(BaseModel):
    event: str
    kind: str = Field(pattern="^(client|mpv|internal)$")
    body: str


@router.get("/templates/all")
async def get_templates(p: Principal = Depends(current)):
    """Тексты сообщений по событиям. Чего нет — берётся стандартный."""
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT event, kind, body FROM msg_template WHERE org_id=$1", p.org_id)
    return {"свои": [{"событие": r["event"], "кому": r["kind"], "текст": r["body"]} for r in rows],
            "события": EVENTS}


@router.put("/templates/all")
async def put_template(body: TplIn, p: Principal = Depends(max_level(5))):
    """Переписать текст одного события. Пустой текст = по этому событию не пишем."""
    if body.event not in EVENTS:
        raise HTTPException(400, "неизвестное событие")
    async with pool().acquire() as c:
        await c.execute(
            """INSERT INTO msg_template (org_id, event, kind, body, updated_by)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (org_id, event, kind) DO UPDATE
               SET body=EXCLUDED.body, updated_at=now(), updated_by=EXCLUDED.updated_by""",
            p.org_id, body.event, body.kind, body.body, p.user_id)
    return {"сохранено": body.event + "/" + body.kind}


# ---------- рассылка по расписанию, без входа в систему ----------

@router.post("/cron/flush")
async def cron_flush(request: Request):
    """Дёргается системным таймером раз в 5 минут. Ключ берётся из .env, FLUSH_KEY."""
    key = os.getenv("FLUSH_KEY", "")
    if not key or request.headers.get("X-Flush-Key") != key:
        raise HTTPException(403, "нет ключа")
    now = datetime.now()
    done = failed = 0
    async with pool().acquire() as c:
        rows = await c.fetch(
            """SELECT o.id, o.body, ch.chat_id FROM outbox o
                 JOIN chat ch ON ch.id = o.chat_pk
                WHERE o.sent_at IS NULL AND o.send_after <= $1
             ORDER BY o.send_after LIMIT 200""", now)
        for r in rows:
            ok = await send_telegram(r["chat_id"], r["body"])
            await c.execute(
                "UPDATE outbox SET sent_at=$1, error=$2 WHERE id=$3",
                now if ok else None, None if ok else "telegram отказал", r["id"])
            done += 1 if ok else 0
            failed += 0 if ok else 1
    return {"разослано": done, "не_ушло": failed}
