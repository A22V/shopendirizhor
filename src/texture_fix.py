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


def figure_enabled():
    return os.environ.get("ORCH_FIGURE", "") not in ("", "0", "false", "False")


# ---------------------------------------------------------------------------
# Бегущий аккомпанемент, который никто не играет (ORCH_FIGURE=1, по умолчанию выключено). Добавлено 2026-11-06.
# Случай: прелюдия ми минор (шестнадцатые левой руки); после ORCH_MELODY_HELD они перестали быть «мелодией»,
# а план модели дал фигурацию только одной фразе — в остальных бегущие ноты молчали.
# Правило:
#   * фраза без фигурации, в которой у фортепиано есть БЕГУЩЕЕ сопровождение: не меньше FIG_DENSITY нот на долю
#     и средняя длина не больше полдоли (эвристика; вальсовое «умпа-па» четвертями не затрагивается);
#   * фигурацию получает один струнный, не занятый во фразе (порядок как в ORCH_THIN: скрипка II, альт, скрипка I,
#     виолончель). Быстрое — струнным: Черни, Op. 600, т. 3, с. 22 (подтверждено);
#   * если все струнные заняты, на фигурацию переходит струнный второго внутреннего голоса (inner2): бегущие ноты
#     и есть та же гармония, только в движении (эвристика); если inner2 у него один, этот голос во фразе исчезает;
#   * во фразе с 8+ инструментами (порог «стены», как ORCH_THIN) новый инструмент не добавляется (только переход inner2).
# ---------------------------------------------------------------------------
FIG_DENSITY = 2.0        # эвристика: нот сопровождения на долю
FIG_MAX_LEN = 0.5        # эвристика: средняя длина ноты сопровождения, в долях


def _phrase_span(ph, bars):
    a, b = ph["bars"]
    if a < 1 or b > len(bars) or a > b:
        return None
    return bars[a - 1][0], bars[b - 1][0] + bars[b - 1][1]


def fill_figuration(plan, fig, bars):
    """fig: meta["fig"] из orchestrator.analyze; bars: meta["bars"]. Возвращает (новый_план, изменения по-русски)."""
    plan = copy.deepcopy(plan)
    changes = []
    for ph in plan.get("phrases", []):
        if ph.get("figuration"):
            continue
        span = _phrase_span(ph, bars)
        if not span:
            continue
        lo, hi = span
        notes = [f for f in fig if lo - 1e-9 <= f["offset"] < hi - 1e-9]
        if not notes or len(notes) / (hi - lo) < FIG_DENSITY or sum(f["dur"] for f in notes) / len(notes) > FIG_MAX_LEN:
            continue
        core = {s[0] for r in CORE for s in ph.get(r, [])}
        free = [n for n in STRINGS_PREF if n not in core]
        where = "такты %d–%d" % tuple(ph["bars"])
        if free and len(_used(ph)) < THIN_MIN:
            ph["figuration"] = [[free[0], 0, None, None]]
            changes.append("%s: бегущее сопровождение отдано (%s), раньше его никто не играл" % (where, STR_RU[free[0]]))
            continue
        inner2_str = [s for s in ph.get("inner2", []) if s[0] in STRINGS_PREF]
        if inner2_str:
            who = inner2_str[0]
            ph["inner2"] = [s for s in ph["inner2"] if s is not who]
            ph["figuration"] = [[who[0], 0, None, None]]
            changes.append("%s: %s переходит со второго внутреннего голоса на бегущее сопровождение" % (where, STR_RU[who[0]]))
    return plan, changes


STR_RU = {"Violin I": "скрипка I", "Violin II": "скрипка II", "Viola": "альт", "Cello": "виолончель"}


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


# ---------------------------------------------------------------------------
# Солирующий инструмент на выбор (2026-11-07, по просьбе пользователя; выбирается при каждой оркестровке,
# по умолчанию «нет» — тогда план не меняется). Не правило для всех пьес, а режим, как в концерте:
# один инструмент ведёт мелодию от начала до конца, остальные аккомпанируют.
#   * Флейта, кларнет, гобой, скрипка, виолончель: во всех фразах мелодию играет только солист; другие инструменты
#     из мелодии убираются (их другие роли остаются), сам солист из сопровождения убирается.
#     Октава выбирается для всей фразы целиком (а не нота за нотой), чтобы не ломать линию: сначала как можно
#     меньше нот вне диапазона, затем для флейты — самая низкая подходящая октава («нежная и невысокая», пожелание
#     пользователя), для остальных — ближайшая к написанной.
#   * Фортепиано: играет свою пьесу целиком (обе руки, как в оригинале); оркестр не дублирует мелодию и бегущее
#     сопровождение (их играет рояль), остаются выдержанные голоса и бас.
# Статус: эвристика (смысл «солист и аккомпанемент» — концертная практика; правила выбора октавы наши).
# ---------------------------------------------------------------------------
SOLO_CHOICES = {"Flute": "флейта", "Clarinet": "кларнет", "Oboe": "гобой", "Violin I": "скрипка I",
                "Cello": "виолончель", "Piano": "фортепиано"}
FLUTE_SOFT_TOP = 84      # C6; эвристика: выше флейта звучит ярко и резко (ср. ORCH_COMFORT, порог G#5 для дубля)
_SOLO_RANGE_KEY = {"Flute": "flute", "Clarinet": "clarinet", "Oboe": "oboe", "Violin I": "violin", "Cello": "cello"}


def _solo_shift(pitches, name, ranges):
    lo, hi = ranges[_SOLO_RANGE_KEY[name]]
    best = None
    for sh in (-24, -12, 0, 12, 24):
        out = sum(1 for p in pitches if not lo <= p + sh <= hi)
        if name == "Flute":   # «нежная и невысокая»: ноты выше C6 считаются так же плохо, как ноты вне диапазона
            key = (out + sum(1 for p in pitches if p + sh > FLUTE_SOFT_TOP), sh)
        else:
            key = (out, (abs(sh), sh))
        if best is None or key < best[0]:
            best = (key, sh)
    return best[1]


def apply_solo(plan, solo, melody, bars):
    """Возвращает (новый_план, изменения, piano_mode). solo: None/"" — ничего не меняется.
    melody: ноты мелодии из анализа ({"offset","pitch"}); bars: [(начало, длина)] тактов в долях."""
    if not solo:
        return plan, [], "off"
    plan = copy.deepcopy(plan)
    changes = []
    import validator
    ranges = validator.RANGES_UNVERIFIED
    starts = [b[0] for b in bars]
    for ph in plan.get("phrases", []):
        if solo == "Piano":
            ph["_was_melody"] = [sp[0] for sp in ph.get("melody", [])] + [sp[0] for sp in ph.get("figuration", []) or []]
            ph["melody"], ph["figuration"] = [], []
            continue
        a, b = ph["bars"]
        t0 = starts[a - 1] if a - 1 < len(starts) else 0.0
        t1 = starts[b] if b < len(starts) else float("inf")
        pitches = [m["pitch"] for m in melody if t0 - 1e-9 <= m["offset"] < t1 - 1e-9]
        sh = _solo_shift(pitches, solo, ranges) if pitches else 0
        for role in ("inner1", "inner2", "bass", "figuration"):
            if ph.get(role):
                ph[role] = [s for s in ph[role] if s[0] != solo]
        was = [sp[0] for sp in ph.get("melody", []) if sp[0] != solo]
        ph["melody"] = [[solo, sh, None, None]]
        ph["_was_melody"] = was
    # кто играл только мелодию, остался бы без нот: такой струнный удваивает первый внутренний голос там,
    # где раньше играл мелодию (новых нот нет); духовых добавляет ORCH_WINDS, если он включён
    used = {sp[0] for ph in plan["phrases"] for r in ("melody", "inner1", "inner2", "bass", "figuration")
            for sp in ph.get(r, []) or []}
    for ph in plan["phrases"]:
        for who in ph.pop("_was_melody", []):
            if who not in used and who in ("Violin I", "Violin II", "Viola", "Cello") and ph.get("inner1") is not None:
                ph["inner1"] = list(ph.get("inner1") or []) + [[who, 0, None, None]]
                changes.append("такты %d–%d: %s удваивает внутренний голос" % (ph["bars"][0], ph["bars"][1], who))
    if solo == "Piano":
        changes.append("солирует фортепиано: рояль играет пьесу целиком, оркестр без мелодии и бегущего сопровождения")
        return plan, changes, "solo"
    changes.append("солирует %s: мелодия во всех фразах только у солиста; октава выбрана для каждой фразы целиком"
                   % SOLO_CHOICES[solo])
    return plan, changes, "off"
