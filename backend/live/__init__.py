# Одноразовая починка доставки бэкенда.
#
# На сервере лежала устаревшая версия /opt/fo/fo-backend-pull.sh - она умела
# только возить файлы по манифесту и ничего не знала про серверные шаги
# (_step.id / _step.py), а механизма самообновления в ней не было.
# Заменить её снаружи было нечем: консоль недоступна.
#
# Поэтому подмена делается отсюда, при старте приложения, ровно один раз:
# ставится маркер, и дальше этот файл ничего не делает.
# Всё обёрнуто в try/except - приложение не должно падать ни при каких обстоятельствах.

def _selfheal():
    import os, stat, urllib.request

    marker = "/opt/fo/.selfheal-pull-v2"
    target = "/opt/fo/fo-backend-pull.sh"
    url = ("https://raw.githubusercontent.com/nekrasivostore-one/"
           "fo-web/main/backend/fo-backend-pull.sh")

    if os.path.exists(marker):
        return
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = r.read()
    except Exception:
        return
    # берём только заведомо правильный файл
    if b"GitHub" not in data or len(data) < 3000:
        return
    try:
        if os.path.exists(target):
            with open(target, "rb") as f:
                old = f.read()
            with open(target + ".bak-selfheal", "wb") as f:
                f.write(old)
        tmp = target + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.chmod(tmp, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP
                      | stat.S_IROTH | stat.S_IXOTH)   # 755
        os.replace(tmp, target)
        with open(marker, "w") as f:
            f.write("done")
    except Exception:
        return

try:
    _selfheal()
except Exception:
    pass
