"""Безопасная запись нот в MusicXML через music21 (2026-11-09)."""


def write_musicxml(score, path):
    """Запись нот в MusicXML. Звук (MIDI) уже записан раньше и от этого не меняется.
    Бывает (2026-11-09, облако, план DeepSeek): между нотами остаётся крошечная пауза (например 1/2048),
    и music21 падает «Cannot convert "2048th" duration to MusicXML (too short)» — вся оркестровка
    пропадала. Тогда выравниваем начала и длины нот в НОТНОЙ записи по сетке 1/12 доли (шестнадцатые
    и триоли, эвристика) и пишем снова. Возвращает None, если правка не понадобилась, иначе описание."""
    try:
        score.write("musicxml", fp=path)
        return None
    except Exception as e:
        first = "%s: %s" % (type(e).__name__, e)
    fixed = score.quantize(quarterLengthDivisors=(4, 3), processOffsets=True, processDurations=True,
                           inPlace=False, recurse=True)
    removed = 0
    for el in list(fixed.recurse().notesAndRests):
        if el.duration.quarterLength < 1e-6 or (el.isRest and el.duration.quarterLength < 1 / 12):
            el.activeSite.remove(el)
            removed += 1
    try:
        fixed = fixed.makeNotation(inPlace=False)
    except Exception:
        pass
    fixed.write("musicxml", fp=path)
    return {"reason": first, "action": "ноты выровнены по сетке 1/12 доли только в нотной записи (звук тот же)",
            "removed_tiny": removed}
