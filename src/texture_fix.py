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
# Солирующий инструмент на выбор и режим «как в Болеро» (2026-11-07, по просьбе пользователя; выбирается при каждой
# оркестровке, по умолчанию «нет» — тогда план не меняется). Не правило для всех пьес, а режим.
#   * Фортепиано, орган: играют пьесу целиком (обе руки, с педалью оригинала); оркестр не дублирует мелодию и бегущее
#     сопровождение.
#   * Флейта, кларнет, гобой, скрипка, виолончель, аккордеон, гитара: мелодию во всех фразах играет только солист.
#     Октава выбирается для всей фразы целиком: сначала как можно меньше нот вне диапазона, у флейты ноты выше C6
#     тоже штрафуются и берётся самая низкая подходящая октава («нежная и невысокая» — пожелание пользователя).
#   * «Болеро»: солист меняется только между высказываниями темы; высказывание = подряд идущие фразы, пока не наберётся
#     8 тактов (эвристика: «период» из 8 тактов). Внутри высказывания мелодию ведёт один инструмент. Каждый раз берётся
#     тот, кому мелодия ложится в диапазон, кроме предыдущего солиста; реже звучавшие — раньше.
# Сопровождение солиста (solo_accompaniment, после всех заполнений плана), подтверждено Форсайтом, «Orchestration» 1914:
#   с. 187: флейтовые соло «lightly accompanied», пример — «one Horn and the muted Strings»;
#   с. 197: «the extreme lightness of the accompaniment, twelve stringed-instruments only, all muted»;
#   с. 185: низкие ноты флейты легко заглушить; контрабасы «in the accompaniment of Flute solos … omitted altogether».
#   Поэтому: сопровождают струнные и валторна; остальные духовые молчат (кроме кульминации); при солирующей флейте
#   контрабас молчит, бас у виолончели. Насколько тише сопровождение (orchestrator.SOLO_ACC_VEL) — эвристика.
# ---------------------------------------------------------------------------
SOLO_CHOICES = {"Piano": "фортепиано", "Organ": "орган", "Flute": "флейта", "Clarinet": "кларнет", "Oboe": "гобой",
                "Violin I": "скрипка I", "Cello": "виолончель", "Accordion": "аккордеон", "Guitar": "гитара",
                "Bolero": "меняющиеся солисты, как в «Болеро»"}
KEYBOARD_FULL = {"Piano": "solo", "Organ": "organ"}          # играют пьесу целиком
BOLERO_POOL = ["Flute", "Clarinet", "Oboe", "Violin I", "Horn", "Cello"]
BOLERO_BARS = 8          # эвристика
FLUTE_SOFT_TOP = 84      # C6; эвристика: выше флейта звучит ярко и резко (ср. ORCH_COMFORT, порог G#5 для дубля)
SOLO_RANGE_KEY = {"Flute": "flute", "Clarinet": "clarinet", "Oboe": "oboe", "Violin I": "violin", "Cello": "cello",
                  "Horn": "horn", "Accordion": "accordion", "Guitar": "guitar"}
SOLO_STRINGS = ("Violin I", "Violin II", "Viola", "Cello")


def _solo_cost(pitches, name, ranges):
    """(штраф, сдвиг) для лучшей октавы фразы у инструмента name."""
    lo, hi = ranges[SOLO_RANGE_KEY[name]]
    best = None
    for sh in (-24, -12, 0, 12, 24):
        out = sum(1 for p in pitches if not lo <= p + sh <= hi)
        if name == "Flute":   # «нежная и невысокая»: ноты выше C6 считаются так же плохо, как ноты вне диапазона
            key = (out + sum(1 for p in pitches if p + sh > FLUTE_SOFT_TOP), sh)
        else:
            key = (out, (abs(sh), sh))
        if best is None or key < best[0]:
            best = (key, sh)
    return best[0][0], best[1]


def _solo_shift(pitches, name, ranges):
    return _solo_cost(pitches, name, ranges)[1]


def _switch_beat(melody, t_b, bars):
    """Где передать мелодию следующему солисту рядом с тактовой чертой t_b (в долях). Конец мысли — долгая нота и пауза
    после неё; передаём на первой ноте после такого места, ищем в пределах такта до и после черты.
    Сила места = длина ноты + 3 × пауза − 0,5 × расстояние до черты (числа — эвристика, подобраны 2026-11-07 на пьесе
    пользователя: на 5 стыках из 5 передача ушла с середины мысли)."""
    bar_len = bars[0][1] if bars else 4.0
    mel = sorted(melody, key=lambda m: m["offset"])
    best = (None, t_b)
    for i in range(len(mel) - 1):
        a, b = mel[i], mel[i + 1]
        if not (t_b - bar_len - 1e-9 <= b["offset"] <= t_b + bar_len + 1e-9):
            continue
        gap = max(0.0, b["offset"] - (a["offset"] + a["dur"]))
        score = a["dur"] + 3.0 * gap - 0.5 * abs(b["offset"] - t_b)
        if best[0] is None or score > best[0]:
            best = (score, b["offset"])
    return best[1]


def apply_solo(plan, solo, melody, bars):
    """Назначает солиста. Возвращает (новый_план, изменения, piano_mode). solo: None/"" — ничего не меняется.
    melody: ноты мелодии из анализа ({"offset","pitch"}); bars: [(начало, длина)] тактов в долях."""
    if not solo:
        return plan, [], "off"
    plan = copy.deepcopy(plan)
    changes = []
    import orchestrator
    ranges = orchestrator.all_ranges()
    starts = [b[0] for b in bars]

    def pitches_of(ph):
        a, b = ph["bars"]
        t0 = starts[a - 1] if a - 1 < len(starts) else 0.0
        t1 = starts[b] if b < len(starts) else float("inf")
        return [m["pitch"] for m in melody if t0 - 1e-9 <= m["offset"] < t1 - 1e-9]

    phrases = plan.get("phrases", [])
    who_for = {}
    if solo == "Bolero":
        groups, cur = [], []
        for k, ph in enumerate(phrases):
            cur.append(k)
            if sum(phrases[j]["bars"][1] - phrases[j]["bars"][0] + 1 for j in cur) >= BOLERO_BARS:
                groups.append(cur); cur = []
        if cur:
            if groups and sum(phrases[j]["bars"][1] - phrases[j]["bars"][0] + 1 for j in cur) < BOLERO_BARS // 2:
                groups[-1] += cur      # короткий хвост — к предыдущему высказыванию
            else:
                groups.append(cur)
        prev, used, owners = None, {n: 0 for n in BOLERO_POOL}, []
        for g in groups:
            ps = [p for j in g for p in pitches_of(phrases[j])]
            cands = [n for n in BOLERO_POOL if n != prev] or BOLERO_POOL
            pick = min(cands, key=lambda n: (_solo_cost(ps, n, ranges)[0], used[n], BOLERO_POOL.index(n)))
            used[pick] += 1
            prev = pick
            for j in g:
                who_for[j] = pick
            a = phrases[g[0]]["bars"][0]
            t_b = starts[a - 1] if a - 1 < len(starts) else 0.0
            owners.append([_switch_beat(melody, t_b, bars) if owners else 0.0, pick, _solo_cost(ps, pick, ranges)[1]])
        plan["melody_owner"] = owners      # orchestrator.realize: кто играет мелодию с какой доли (вместо тактов фраз)
        # соседние солисты не играют сопровождение рядом со стыком (иначе у инструмента две ноты сразу)
        for gi, g in enumerate(groups):
            near = {owners[k][1] for k in (gi - 1, gi + 1) if 0 <= k < len(owners)}
            for j in (g[0], g[-1]):
                for role in ("inner1", "inner2", "bass", "figuration"):
                    if phrases[j].get(role):
                        phrases[j][role] = [sp for sp in phrases[j][role] if sp[0] not in near]
            changes.append("такты %d–%d: солирует %s" % (phrases[g[0]]["bars"][0], phrases[g[-1]]["bars"][1],
                                                          SOLO_CHOICES.get(pick, pick.lower() if pick != "Horn" else "валторна")))
    for k, ph in enumerate(phrases):
        if solo in KEYBOARD_FULL:
            ph["_was_melody"] = [sp[0] for sp in ph.get("melody", [])] + [sp[0] for sp in ph.get("figuration", []) or []]
            ph["melody"], ph["figuration"] = [], []
            continue
        name = who_for.get(k, solo)
        ps = pitches_of(ph)
        sh = _solo_shift(ps, name, ranges) if ps else 0
        for role in ("inner1", "inner2", "bass", "figuration"):
            if ph.get(role):
                ph[role] = [sp for sp in ph[role] if sp[0] != name]
        ph["_was_melody"] = [sp[0] for sp in ph.get("melody", []) if sp[0] != name]
        ph["melody"] = [[name, sh, None, None]]
    # кто играл только мелодию, остался бы без нот: такой струнный удваивает первый внутренний голос там,
    # где раньше играл мелодию (новых нот нет)
    used_all = {sp[0] for ph in phrases for r in ("melody", "inner1", "inner2", "bass", "figuration")
                for sp in ph.get(r, []) or []}
    for ph in phrases:
        for who in ph.pop("_was_melody", []):
            if who not in used_all and who in SOLO_STRINGS and ph.get("inner1") is not None:
                ph["inner1"] = list(ph.get("inner1") or []) + [[who, 0, None, None]]
                changes.append("такты %d–%d: %s удваивает внутренний голос" % (ph["bars"][0], ph["bars"][1], who))
    if solo in KEYBOARD_FULL:
        changes.insert(0, "солирует %s: играет пьесу целиком, оркестр без мелодии и бегущего сопровождения" % SOLO_CHOICES[solo])
        return plan, changes, KEYBOARD_FULL[solo]
    if solo != "Bolero":
        changes.insert(0, "солирует %s: мелодия во всех фразах только у солиста; октава выбрана для каждой фразы целиком"
                       % SOLO_CHOICES[solo])
    return plan, changes, "off"


def solo_accompaniment(plan, solo):
    """Сопровождение солиста. Вызывать ПОСЛЕ всех заполнений плана. Возвращает (новый_план, изменения).
    v3 (2026-11-07, отзыв пользователя на v2: «слишком занизил громкость… играют только скрипки»): духовые снова
    подпевают; убираем только то, что подтверждено: быстрое сопровождение (фигурация) — у струнных (Черни, Op. 600,
    т. 3, с. 22), при солирующей флейте контрабас молчит (Форсайт с. 185). Тише сопровождение делает
    orchestrator.SOLO_ACC_VEL."""
    if not solo:
        return plan, []
    plan = copy.deepcopy(plan)
    changes = []
    winds = {"Flute", "Oboe", "Clarinet", "Bassoon", "Horn"}
    for ph in plan.get("phrases", []):
        soloists = {sp[0] for sp in ph.get("melody", []) or []}
        removed = []
        for role in ("inner1", "inner2", "bass", "figuration"):
            keep = []
            for sp in ph.get(role, []) or []:
                n = sp[0]
                if role == "figuration" and n in winds:
                    removed.append(n); continue
                if n == "Double Bass" and "Flute" in soloists:
                    removed.append(n); continue
                keep.append(sp)
            ph[role] = keep
        if not ph.get("bass"):
            for n in ("Cello", "Viola"):
                if n not in soloists:
                    ph["bass"] = [[n, 0, None, None]]; break
        if removed:
            changes.append("такты %d–%d: в сопровождении молчат %s" % (ph["bars"][0], ph["bars"][1],
                           ", ".join(sorted(set(removed)))))
    return plan, changes
