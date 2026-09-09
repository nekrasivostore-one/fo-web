-- Куда и когда дублировать события по чатам кабинета
CREATE TABLE IF NOT EXISTS chat_route (
  id          bigserial PRIMARY KEY,
  org_id      uuid        NOT NULL,
  client_id   uuid        NOT NULL,
  chat_pk     bigint      NOT NULL REFERENCES chat(id) ON DELETE CASCADE,
  event       text        NOT NULL,
  enabled     boolean     NOT NULL DEFAULT true,
  when_mode   text        NOT NULL DEFAULT 'ready',   -- ready | time
  at_time     time        NULL,                        -- если when_mode='time'
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  uuid        NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS chat_route_uq ON chat_route (client_id, chat_pk, event);
CREATE INDEX IF NOT EXISTS chat_route_org ON chat_route (org_id);

-- Шаблоны сообщений: свой текст для клиента и для команды
CREATE TABLE IF NOT EXISTS msg_template (
  id         bigserial PRIMARY KEY,
  org_id     uuid   NOT NULL,
  event      text   NOT NULL,
  kind       text   NOT NULL,          -- client | mpv | internal
  text       text   NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS msg_template_uq ON msg_template (org_id, event, kind);

-- Рабочее окно организации: вне его отправка откладывается
ALTER TABLE org ADD COLUMN IF NOT EXISTS work_from time NOT NULL DEFAULT '08:00';
ALTER TABLE org ADD COLUMN IF NOT EXISTS work_to   time NOT NULL DEFAULT '18:00';

-- Отложенная очередь
CREATE TABLE IF NOT EXISTS outbox (
  id         bigserial PRIMARY KEY,
  org_id     uuid   NOT NULL,
  chat_pk    bigint NOT NULL REFERENCES chat(id) ON DELETE CASCADE,
  event      text   NOT NULL,
  body       text   NOT NULL,
  send_after timestamptz NOT NULL,
  sent_at    timestamptz NULL,
  error      text   NULL
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox (send_after) WHERE sent_at IS NULL;
