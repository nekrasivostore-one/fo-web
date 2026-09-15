#!/bin/bash
# Вписывает почтовые настройки в /opt/fo/.env, не показывая пароль на экране.
# Пароль вводит человек, он не попадает ни в историю команд, ни в список процессов.
set -u
ENVF=/opt/fo/.env
[ -f "$ENVF" ] || { echo "нет файла $ENVF"; exit 1; }

printf 'Почта, с которой шлём письма (например fo@flater.pro): '
read -r FO_U
printf 'Пароль приложения Google (16 символов, на экране не появится): '
stty -echo 2>/dev/null; read -r FO_P; stty echo 2>/dev/null; printf '\n'

[ -n "${FO_U:-}" ] || { echo "почта не введена"; exit 1; }
[ -n "${FO_P:-}" ] || { echo "пароль не введён"; exit 1; }

export FO_U FO_P
cp "$ENVF" "$ENVF.$(date +%Y%m%d-%H%M%S).bak"
python3 - <<'PY'
import io, os, re
P = "/opt/fo/.env"
s = io.open(P, encoding="utf-8").read()
vals = {
    "SMTP_HOST": "smtp.gmail.com",
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
