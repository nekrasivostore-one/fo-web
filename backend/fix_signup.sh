#!/bin/bash
set -u
cd /opt/fo
RAW=https://raw.githubusercontent.com/nekrasivostore-one/fo-web/main/backend
curl -fsSL "$RAW/fix_signup.py?t=$(date +%s)" -o /tmp/fix_signup.py || { echo "не скачался патч"; exit 1; }
grep -q "workspace" /tmp/fix_signup.py || { echo "патч приехал битым"; exit 1; }
python3 /tmp/fix_signup.py || exit 1
echo "── синтаксис ──"
/opt/fo/venv/bin/python -m py_compile backend/app/routers/auth.py backend/app/routers/signup.py \
  && echo "  оба файла компилируются" || { echo "  СИНТАКСИС СЛОМАН — откатываю"; 
      for f in backend/app/routers/auth.py backend/app/routers/signup.py; do
        b=$(ls -t $f.bak-* 2>/dev/null | head -1); [ -n "$b" ] && cp "$b" "$f"; done; exit 1; }
systemctl restart fo
sleep 5
printf 'health: '; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health
