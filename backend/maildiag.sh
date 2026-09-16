#!/bin/bash
set -u
echo "════ код отправки ════"
sed -n '32,50p' /opt/fo/backend/app/notify.py
echo
echo "════ что видит приложение ════"
cd /tmp
/opt/fo/venv/bin/python - <<'PY'
import io, os, sys, asyncio
for line in io.open("/opt/fo/.env", encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)
sys.path.insert(0, "/opt/fo/backend")
from app.config import settings
from app import notify
print("host =", repr(settings.smtp_host))
print("port =", settings.smtp_port)
print("user =", repr(settings.smtp_user))
print("pass =", len(settings.smtp_pass or ""), "символов")
print("from =", repr(settings.mail_from))
to = settings.smtp_user or "fo@flater.pro"
print()
print("════ прямая отправка ════")
try:
    notify._send_sync(to, "ФО: проверка отправки", "Если письмо пришло — отправка работает.")
    print("OK — письмо ушло на", to)
except Exception as e:
    print("УПАЛО:", type(e).__name__, str(e)[:300])
PY
