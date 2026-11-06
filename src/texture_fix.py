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


# ---------------------------------------------------------------------------
# Контрабас, забытый моделью (ORCH_BASS=1, по умолчанию выключено).
# Статус: эвристика, проверена на слух (ноктюрн ля минор, 2026-11-05: вариант с
# контрабасом пользователь оценил как «мелодия звучит побогаче»). В книгах не найдено.
# Правило: если в плане контрабас не назначен НИ В ОДНОЙ фразе, он добавляется к басовой линии
# каждой фразы (тот же звуковысотный уровень, диапазон подгоняет orchestrator).
# Если контрабас в плане есть хотя бы раз, ничего не меняется.
# ---------------------------------------------------------------------------
def bass_enabled():
    return os.environ.get("ORCH_BASS", "") not in ("", "0", "false", "False")


def fill_bass(plan):
    plan = copy.deepcopy(plan)
    phrases = plan.get("phrases", [])
    for ph in phrases:
        for role in ("melody", "inner1", "inner2", "bass", "figuration"):
            if "Double Bass" in _names(ph.get(role, [])):
                return plan, []
    changes = []
    for ph in phrases:
        b = ph.get("bass")
        if b:
            b.append(["Double Bass", 0, None, None])
            changes.append("такты %d–%d: контрабас добавлен к басу" % tuple(ph["bars"]))
    return plan, changes


# ---------------------------------------------------------------------------
# Духовые, забытые моделью (ORCH_WINDS=1, по умолчанию выключено). Добавлено 2026-11-06.
# Случай: DeepSeek Flash на прелюдии ми минор не назначил кларнет, фагот и валторну ни в одной фразе
# (QX06 ×3), хотя сам написал «fuller, with horn support».
# Правило (всё эвристика, в книгах не найдено; проверяется на слух парой A/B):
#   * трогаем только инструмент, которого в плане нет НИ В ОДНОЙ фразе; если он есть хоть раз, план не меняется;
#   * добавляем его только во фразы с уровнем mf/f/ff или кульминацией (тихие фразы остаются прозрачными);
#     если таких нет, в самую длинную фразу;
#   * новых нот не придумываем: инструмент удваивает уже существующую линию (унисон, диапазон подгоняет оркестратор):
#     фагот — бас (вместе с виолончелью), валторна — второй внутренний голос (держит гармонию; смысл
#     «валторна держит длинные ноты» — Черни, Op. 600, т. 3, с. 28), кларнет — первый внутренний голос,
#     флейта и гобой — первый внутренний голос;
#   * во фразе, где уже 8 и больше инструментов (порог «стены», как в ORCH_THIN) или уже 4 духовых
#     (порог рецензента K3), ничего не добавляем.
# ---------------------------------------------------------------------------
WINDS = ("Flute", "Oboe", "Clarinet", "Bassoon", "Horn")
FILL_ORDER = ("Horn", "Bassoon", "Clarinet", "Oboe", "Flute")   # кто первым получает место (эвристика: валторна и фагот держат гармонию и бас)
WIND_ROLE = {"Bassoon": ("bass",), "Horn": ("inner2", "inner1"), "Clarinet": ("inner1", "inner2"),
             "Flute": ("inner1", "inner2"), "Oboe": ("inner1", "inner2")}
WIND_RU = {"Flute": "флейта", "Oboe": "гобой", "Clarinet": "кларнет", "Bassoon": "фагот", "Horn": "валторна"}
WINDS_MAX = 4          # эвристика (как K3 рецензента)
LOUD = ("mf", "f", "ff")


def winds_enabled():
    return os.environ.get("ORCH_WINDS", "") not in ("", "0", "false", "False")


def _used(ph):
    return {s[0] for r in CORE + ("figuration",) for s in ph.get(r, [])}


def fill_winds(plan):
    """Возвращает (новый_план, список_изменений по-русски). Исходный план не меняется."""
    plan = copy.deepcopy(plan)
    phrases = plan.get("phrases", [])
    named = set().union(*[_used(ph) for ph in phrases]) if phrases else set()
    missing = [w for w in FILL_ORDER if w not in named]
    if not missing:
        return plan, []
    targets = [ph for ph in phrases if ph.get("climax") or ph.get("level") in LOUD]
    if not targets and phrases:
        targets = [max(phrases, key=lambda p: p["bars"][1] - p["bars"][0])]
    changes = []
    for w in missing:
        for ph in targets:
            used = _used(ph)
            if len(used) >= THIN_MIN or sum(1 for n in used if n in WINDS) >= WINDS_MAX:
                continue
            role = next((r for r in WIND_ROLE[w] if ph.get(r)), None)
            if role is None:
                continue                     # нечего удваивать: новых нот не придумываем
            ph[role] = list(ph[role]) + [[w, 0, None, None]]
            changes.append("такты %d–%d: %s добавлен(а) к голосу %s" % (ph["bars"][0], ph["bars"][1], WIND_RU[w], role))
    return plan, changes
