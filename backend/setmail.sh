#!/bin/bash
# Вписывает почтовые настройки в /opt/fo/.env, не показывая пароль на экране.
# Пароль вводит человек, он не попадает ни в историю команд, ни в список процессов.
set -u
ENVF=/opt/fo/.env
[ -f "$ENVF" ] || { echo "нет файла $ENVF"; exit 1; }

echo "Какой сервис почты:"
echo "  1) Beget — почта на flater.pro (smtp.beget.com)   2) Яндекс   3) Gmail   4) Mail.ru   5) вручную"
printf 'Номер [1]: '
read -r FO_S
case "${FO_S:-1}" in
  1|"") FO_H=smtp.beget.com ;;
  2) FO_H=smtp.yandex.ru ;;
  3) FO_H=smtp.gmail.com ;;
  4) FO_H=smtp.mail.ru ;;
  *) printf 'SMTP-сервер: '; read -r FO_H ;;
esac
printf 'Почта, с которой шлём письма (например fo@flater.pro): '
read -r FO_U
printf 'Пароль ящика (на экране не появится): '
stty -echo 2>/dev/null; read -r FO_P; stty echo 2>/dev/null; printf '\n'

[ -n "${FO_U:-}" ] || { echo "почта не введена"; exit 1; }
[ -n "${FO_P:-}" ] || { echo "пароль не введён"; exit 1; }

export FO_U FO_P FO_H
cp "$ENVF" "$ENVF.$(date +%Y%m%d-%H%M%S).bak"
python3 - <<'PY'
import io, os, re
P = "/opt/fo/.env"
s = io.open(P, encoding="utf-8").read()
vals = {
    "SMTP_HOST": os.environ.get("FO_H") or "smtp.beget.com",
    "SMTP_PORT": "465",
    "SMTP_USER": os.environ["FO_U"],
    "SMTP_PASS": os.environ["FO_P"],
    "MAIL_FROM":  os.environ["FO_U"],
}
for k, v in vals.items():
    if re.search(r"(?m)^%s=" % k, s):
        s = re.sub(r"(?m)^%s=.*$" % k, "%s=%s" % (k, v), s)
    else:
        s = s.rstrip("\n") + "\n%s=%s\n" % (k, v)
io.open(P, "w", encoding="utf-8").write(s)
print("записано: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM")
PY
unset FO_P
chmod 600 "$ENVF"
systemctl restart fo
sleep 4
printf 'health: '; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
echo '— проверка: длина пароля в .env (сам пароль не печатаем)'
awk -F= '/^SMTP_PASS=/{print "  символов в пароле: " length($2)}' "$ENVF"
awk -F= '/^SMTP_USER=/{print "  отправитель: " $2}' "$ENVF"
awk -F= '/^SMTP_HOST=/{print "  сервер: " $2}' "$ENVF"
echo '— пробная отправка'
cd /opt/fo && python3 - <<'PY2'
import os, ssl, smtplib, io
env = {}
for line in io.open("/opt/fo/.env", encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); env[k] = v
try:
    c = smtplib.SMTP_SSL(env["SMTP_HOST"], int(env.get("SMTP_PORT") or 465),
                         timeout=20, context=ssl.create_default_context())
    c.login(env["SMTP_USER"], env["SMTP_PASS"])
    c.quit()
    print("  SMTP: вход принят, письма пойдут")
except Exception as e:
    print("  SMTP: не пускает —", type(e).__name__, str(e)[:160])
PY2
