"""
Автоматическое прореживание «стены звука» в плане оркестровки (до превращения плана в ноты).

Включается переменной ORCH_THIN=1 (по умолчанию выключено). Работает с любым планом: от модели (DeepSeek и др.)
и от встроенного планировщика. Меняет только фразы, где одновременно заняты 8 и более инструментов.

Что делается во фразе-«стене»:
  1. Мелодия, внутренние голоса (inner1, inner2) и бас не трогаются.
  2. Фигурацию (быстрые ноты сопровождения) играют только струнные, не больше двух.
     Источник: Черни, Op. 600, т. 3, с. 22 — быстрые пассажи «в общем случае» отдаются струнным (подтверждено);
     валторна держит длинные ноты, с. 28 (подтверждено). Число «не больше двух» — эвристика (вариант B на Рыбникове).
  3. Контрабас из фигурации переносится в бас на октаву ниже (как во встроенном плане программы: ("Double Bass", -12)).
     Черни: быстрые пассажи у виолончели в нижней октаве «быстро становятся неясными» (подтверждено для виолончели;
     для контрабаса — по аналогии, эвристика).
  4. Порог «8 и более инструментов» — эвристика.
"""
import copy, os

THIN_MIN = 8            # эвристика: с этого числа инструментов во фразе считаем её «стеной»
FIG_MAX = 2             # эвристика: не больше двух голосов фигурации
STRINGS_PREF = ["Violin II", "Viola", "Violin I", "Cello"]   # порядок предпочтения для фигурации
CORE = ("melody", "inner1", "inner2", "bass")


def enabled():
    return os.environ.get("ORCH_THIN") == "1"


def _names(specs):
    return [s[0] for s in specs]


def thin_plan(plan):
    """Возвращает (новый_план, список_изменений). Исходный план не меняется."""
    new = copy.deepcopy(plan)
    changes = []
    for ph in new.get("phrases", []):
        used = {s[0] for r in CORE + ("figuration",) for s in ph.get(r, [])}
        if len(used) < THIN_MIN:
            continue
        core = {s[0] for r in CORE for s in ph.get(r, [])}
        fig = ph.get("figuration", [])
        keep = [s for s in fig if s[0] in STRINGS_PREF and s[0] not in core]
        # Черни, с. 22: первая скрипка ведёт и не должна надолго молчать -> если иначе она во фразе молчит, оставляем её первой
        pref = (["Violin I"] + [n for n in STRINGS_PREF if n != "Violin I"]) if "Violin I" not in core else STRINGS_PREF
        keep.sort(key=lambda s: pref.index(s[0]))
        keep = keep[:FIG_MAX]
        removed = [s[0] for s in fig if s not in keep]
        moved_db = False
        if "Double Bass" in _names(fig) and "Double Bass" not in core and ph.get("bass"):
            b = ph["bass"][0]
            spec = ["Double Bass", -12] + list(b[2:4]) if len(b) > 2 else ["Double Bass", -12]
            ph["bass"] = list(ph["bass"]) + [spec]
            moved_db = True
            removed = [n for n in removed if n != "Double Bass"]
        if not removed and not moved_db and len(keep) == len(fig):
            continue                      # nothing to thin (e.g. no fast figuration at all): leave the phrase as is
        ph["figuration"] = keep
        after = {s[0] for r in CORE + ("figuration",) for s in ph.get(r, [])}
        changes.append({"bars": ph["bars"], "instruments_before": len(used), "instruments_after": len(after),
                        "figuration_kept": _names(keep), "removed_from_figuration": removed,
                        "double_bass_moved_to_bass": moved_db})
    return new, changes
