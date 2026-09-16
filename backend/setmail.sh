#!/bin/bash
# Почтовые настройки для ФО. Пароль вводит человек, на экране он не появляется,
# в историю команд и в список процессов не попадает.
# Порядок важный: сначала ПРОВЕРЯЕМ вход на почтовый сервер и только потом
# пишем в .env — чтобы неверный пароль не ломал рабочую настройку.
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
FO_U="$(printf '%s' "$FO_U" | tr -d '[:space:]')"
[ -n "${FO_U:-}" ] || { echo "почта не введена"; exit 1; }

TRY=0
while :; do
  TRY=$((TRY+1))
  printf 'Пароль ящика (на экране не появится): '
  stty -echo 2>/dev/null; read -r FO_P; stty echo 2>/dev/null; printf '\n'
  # срезаем пробелы и переводы строк, которые часто приезжают вместе со вставкой
  FO_P="$(printf '%s' "$FO_P" | tr -d '\r\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [ -n "${FO_P:-}" ] || { echo "  пароль пустой, попробуйте ещё раз"; continue; }
  echo "  вставилось символов: ${#FO_P}"
  if [ ${#FO_P} -gt 40 ]; then
    echo "  ⚠ это подозрительно длинно для пароля ящика — похоже, скопировалась лишняя строка."
    echo "    Скопируйте в Beget ТОЛЬКО сам пароль и вставьте ещё раз."
  fi

  echo "  проверяю вход на $FO_H ..."
  FO_H="$FO_H" FO_U="$FO_U" FO_P="$FO_P" python3 - <<'PY'
import os, ssl, smtplib, sys
try:
    c = smtplib.SMTP_SSL(os.environ["FO_H"], 465, timeout=25,
                         context=ssl.create_default_context())
    c.login(os.environ["FO_U"], os.environ["FO_P"])
    c.quit()
    print("  ✓ вход принят")
    sys.exit(0)
except smtplib.SMTPAuthenticationError as e:
    print("  ✗ сервер не принял логин или пароль:", str(e.smtp_error)[:100])
    sys.exit(2)
except Exception as e:
    print("  ✗ не смог соединиться:", type(e).__name__, str(e)[:120])
    sys.exit(3)
PY
  RC=$?
  [ $RC -eq 0 ] && break
  if [ $RC -eq 3 ]; then
    echo "  Это не про пароль — сервер почты недоступен. Выхожу, .env не тронут."
    exit 1
  fi
  if [ $TRY -ge 3 ]; then
    echo "  Три попытки подряд не прошли. .env не тронут — старые настройки на месте."
    echo "  Проверьте в панели Beget, что ящик $FO_U создан и пароль от него именно тот."
    exit 1
  fi
  echo "  Попробуем ещё раз."
done

# сюда доходим только с проверенным паролем
export FO_U FO_P FO_H
cp "$ENVF" "$ENVF.$(date +%Y%m%d-%H%M%S).bak"
python3 - <<'PY'
import io, os, re
P = "/opt/fo/.env"
s = io.open(P, encoding="utf-8").read()
vals = {
    "SMTP_HOST": os.environ["FO_H"],
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
PY
unset FO_P
chmod 600 "$ENVF"
systemctl restart fo
sleep 4
printf 'health: '; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
echo
echo "════ готово ════"
echo "  отправитель: $FO_U"
echo "  сервер:      $FO_H:465"
echo "  вход на почтовый сервер проверен до записи — письма пойдут."
echo
echo "Для вашего файла «Ключи ФО.txt» (пароль впишите сами, я его не печатаю):"
echo "  SMTP_HOST=$FO_H"
echo "  SMTP_PORT=465"
echo "  SMTP_USER=$FO_U"
echo "  SMTP_PASS=<пароль ящика из панели Beget>"
echo "  MAIL_FROM=$FO_U"
