#!/bin/bash
# Почему письмо не ушло: смотрим, что видит приложение, и шлём пробное письмо.
set -u
cd /opt/fo
sed -n '30,50p' backend/app/notify.py > /tmp/ne.txt
/opt/fo/venv/bin/python - <<'PY'
import asyncio, os, sys, traceback
sys.path.insert(0, "/opt/fo/backend")
os.chdir("/opt/fo")
from app.config import settings
from app import notify
print("host =", repr(settings.smtp_host))
print("port =", settings.smtp_port)
print("user =", repr(settings.smtp_user))
print("pass =", len(settings.smtp_pass or ""), "символов")
print("from =", repr(settings.mail_from))
to = settings.smtp_user or "fo@flater.pro"
print("--- пробую отправить на", to, "---")
try:
    ok = asyncio.get_event_loop().run_until_complete(
        notify.send_email(to, "ФО: проверка почты", "Если это письмо пришло — отправка работает."))
    print("send_email вернул:", ok)
except Exception as e:
    print("ИСКЛЮЧЕНИЕ:", type(e).__name__, str(e)[:200])
print("--- напрямую, без обёртки ---")
try:
    notify._send_sync(to, "ФО: прямая проверка", "Прямая отправка мимо обёртки.")
    print("прямая отправка: OK")
except Exception as e:
    print("прямая отправка упала:", type(e).__name__, str(e)[:300])
PY
