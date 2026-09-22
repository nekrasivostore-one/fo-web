# Временный модуль: чинит доставку и открывает диагностический адрес.
# Ставится на время разбора, потом возвращается пустой файл.
# Всё в try/except: приложение не должно падать ни при каких обстоятельствах.

_FO_STATUS = {"stage": "start"}


def _selfheal():
    """Подменить устаревший /opt/fo/fo-backend-pull.sh на актуальный. Один раз."""
    import os, stat, urllib.request
    marker = "/opt/fo/.selfheal-pull-v2"
    target = "/opt/fo/fo-backend-pull.sh"
    url = ("https://raw.githubusercontent.com/nekrasivostore-one/"
           "fo-web/main/backend/fo-backend-pull.sh")
    if os.path.exists(marker):
        _FO_STATUS["selfheal"] = "уже сделано"
        return
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = r.read()
    except Exception as e:
        _FO_STATUS["selfheal"] = "не скачалось: %s" % e
        return
    if b"GitHub" not in data or len(data) < 3000:
        _FO_STATUS["selfheal"] = "скачан не тот файл"
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
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
        with open(marker, "w") as f:
            f.write("done")
        _FO_STATUS["selfheal"] = "заменено, байт %d" % len(data)
    except Exception as e:
        _FO_STATUS["selfheal"] = "ошибка записи: %s" % e


def _facts():
    import os, time
    out = {}
    def info(p):
        try:
            st = os.stat(p)
            return {"есть": True, "байт": st.st_size,
                    "изменён": time.strftime("%F %T", time.localtime(st.st_mtime))}
        except Exception:
            return {"есть": False}
    out["fo-backend-pull.sh"] = info("/opt/fo/fo-backend-pull.sh")
    out["маркер починки"] = info("/opt/fo/.selfheal-pull-v2")
    for p, k in (("/opt/fo/.backend-step.state", "метка шага"),
                 ("/opt/fo/.backend-pull.state", "отпечаток бэкенда")):
        try:
            with open(p) as f:
                out[k] = f.read().strip()
        except Exception:
            out[k] = None
    for p, k, n in (("/opt/fo/backend-pull.log", "журнал доставки", 40),
                    ("/opt/fo/web/fo-step.txt", "отчёт шага", 60)):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out[k] = f.read().splitlines()[-n:]
        except Exception:
            out[k] = None
    return out


def _patch_fastapi():
    """Добавить временный адрес /fo-selfcheck в приложение."""
    try:
        import fastapi
    except Exception:
        return
    if getattr(fastapi, "_fo_patched", False):
        return
    base = fastapi.FastAPI

    class _Patched(base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            try:
                @self.get("/fo-selfcheck", include_in_schema=False)
                def _fo_selfcheck():
                    d = dict(_FO_STATUS)
                    d.update(_facts())
                    return d
            except Exception:
                pass

    fastapi.FastAPI = _Patched
    fastapi._fo_patched = True
    _FO_STATUS["patch"] = "адрес добавлен"


try:
    _selfheal()
except Exception as e:
    _FO_STATUS["selfheal"] = "исключение: %s" % e
try:
    _patch_fastapi()
except Exception as e:
    _FO_STATUS["patch"] = "исключение: %s" % e
