"""
Замер памяти сервера (2026-11-07). Нужен, чтобы цифрами ответить на вопросы «хватает ли облаку памяти» и
«какой шаг самый тяжёлый». Звук и ноты не меняет: только пишет числа в отчёт.

Что меряется (Linux; на других системах — пусто, без ошибки):
  * rss_mb — сколько памяти занимает сам процесс приложения сейчас (VmRSS);
  * peak_main_mb — максимум этого процесса за всё время его жизни (VmHWM; включает и прошлые запуски
    в той же сессии сервера, поэтому это верхняя оценка);
  * peak_child_mb — максимум самой «тяжёлой» внешней программы (fluidsynth, ffmpeg), запущенной процессом;
  * peak_total_mb — грубая верхняя оценка одновременного занятия: peak_main + peak_child.
"""
import resource


def _status(field):
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return round(int(line.split()[1]) / 1024.0, 1)     # кБ -> МБ
    except Exception:
        pass
    return None


def snapshot():
    try:
        child = round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0, 1)   # Linux: кБ
    except Exception:
        child = None
    main = _status("VmHWM")
    return {"rss_mb": _status("VmRSS"), "peak_main_mb": main, "peak_child_mb": child,
            "peak_total_mb": round(main + child, 1) if main is not None and child is not None else None}


def text(res):
    """Одна строка по-русски для экрана."""
    if not res:
        return ""
    p = res.get("peak", {})
    parts = []
    if res.get("seconds") is not None:
        parts.append("время всего %.0f с" % res["seconds"])
    if p.get("peak_main_mb") is not None:
        parts.append("память приложения до %.0f МБ" % p["peak_main_mb"])
    if p.get("peak_child_mb"):
        parts.append("синтез звука до %.0f МБ" % p["peak_child_mb"])
    if res.get("soundfont"):
        parts.append("банк звука «%s»" % res["soundfont"])
    return "; ".join(parts)
