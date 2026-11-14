"""Чтение MIDI через music21 без «съехавших тактов».

Найдено 2026-11-14 на пьесе пользователя (830 нот, 4/4): music21 10.5.2 при чтении MIDI, где в одной дорожке
аккорд тянется через тактовую черту, а другие ноты идут своим ходом, ставит следующий такт позже, чем надо
(такт 12 на доле 44,25 вместо 44), и сдвиг копится: к 135-й доле +5 долей. Ноты ВНУТРИ тактов при этом стоят
верно. Итог до исправления: 613 из 830 нот оркестровки не на своих местах, пьеса на 4 доли длиннее оригинала.

Исправление: такты каждой партии ставятся подряд, каждый длиной в свой размер (barDuration). Если такты и так
стоят ровно (все прежние тестовые пьесы), ничего не меняется. Проверка: после исправления начала нот совпадают
с началами нот в самом MIDI (см. tests/smoke_test.py, блок «съехавшие такты»).
"""
from music21 import converter, stream


def regrid(score):
    """Ставит такты подряд. Возвращает число тактов, которые стояли не на месте (0 = ничего не менялось)."""
    moved = 0
    parts = list(score.parts) if hasattr(score, "parts") else []
    for p in parts:
        run = None
        for m in list(p.getElementsByClass(stream.Measure)):
            off = float(m.offset)
            if run is None:
                run = off
            if abs(off - run) > 1e-6:
                p.setElementOffset(m, run)
                moved += 1
            run += float(m.barDuration.quarterLength)
        if moved:
            p.coreElementsChanged()
    return moved


def parse_midi(path, **kw):
    """converter.parse + regrid. На score остаётся пометка score.regrid_moved (сколько тактов переставлено)."""
    s = converter.parse(path, **kw)
    try:
        s.regrid_moved = regrid(s)
    except Exception:
        s.regrid_moved = 0
    return s
