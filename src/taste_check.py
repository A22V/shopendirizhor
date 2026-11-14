"""Проверка по вкусу пользователя (2026-11-14). Звук не меняет, ничего не исправляет.

Идея пользователя (PDF «гайд по ИИ-агентам», п. 3): не писать правила стиля с нуля, а собрать «вкус» из всех прежних
правок и оценок и проверять по нему каждую новую работу. Здесь собраны только те пункты, по которым пользователь
сам вынес решение на слух (дата и слова — в CLAUDE.md, разделы 12.x). Пороги — эвристика: подобраны так, чтобы
одобренные пользователем варианты проходили, а отвергнутые — нет (см. calibrate() и tests/smoke_test.py).

Запуск: python src/taste_check.py фортепиано.mid оркестр.mid
"""
import bisect, collections, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_gate as qg

RU = qg.RU
# верх, выше которого звук «режет слух» (тот же, что ORCH_SOFT_TOP в texture_fix; эвристика)
HARSH = {"Flute": 86, "Oboe": 81, "Clarinet": 82, "Violin I": 88, "Violin": 88}
HARSH_MAX = 0.10          # доля времени звучания инструмента выше границы
HOP_BARS_MIN = 6.0        # мелодия переходит к другому инструменту не чаще раза в 6 тактов
VIOLIN_MAX = 0.60         # скрипка I ведёт не больше 60% нот мелодии
QUIET_SHARE = 0.02        # инструмент «почти молчит», если у него меньше 2% нот оркестра
CHOPPY_MAX = 0.25         # у ведущего не больше 25% нот с маленькой дыркой до следующей ноты
CHOPPY_GAP = 0.5          # «маленькая дырка» — от 0 до полдоли
LOST_MAX = 0.02           # звуков рояля, которых нет в оркестре ни в какой октаве
COVER_MAX = 0.25
LEADS_MAX = 2             # сколько разных инструментов могут вести мелодию (каждый — хотя бы 10% её нот)
LEAD_MIN_SHARE = 0.10
LOUD_OVER = 15            # средняя сила нажатия оркестра не больше рояля + 15

TASTE = [
    ("В1", "Не задирать верх: резкие верхние ноты духовых и скрипки",
     "2026-11-14: «слишком задирает верхние ноты, очень резко, режет слух»; 2026-11-05: вариант с комфортным "
     "регистром «получше, чем со слишком завышенными нотами». Смысл: Римский-Корсаков, т. 1, с. 30–31."),
    ("В2", "Без «переклички»: мелодия не скачет между инструментами",
     "2026-11-12: «та же перекличка инструментов, что была»; 2026-11-07: «пересадки есть, но поменьше»; "
     "«Лунная» с одним кларнетом понравилась. Но 2026-11-14 на своей пьесе смена ведущих «вроде неплохо»."),
    ("В3", "Скрипка не солирует всё время",
     "2026-11-07: «постоянно солирующая скрипка не нравится»; 2026-11-12: «скрипка какая-то навязчивая»."),
    ("В4", "Играет весь состав",
     "2026-11-06: «зная, что мы создаём оркестр из 10 инструментов, конечно ожидаются все инструменты»."),
    ("В5", "Контрабас на месте",
     "2026-11-05: «с контрабасом мелодия звучит побогаче», на вальсе «с контрабасом хорошо получилось»."),
    ("В6", "Связно, не отрывисто",
     "2026-11-11 (Экспромт Шуберта): «кое-где отрывисто и рвано»; 2026-11-11 (ансамбли): «местами нет плавности»."),
    ("В7", "Мелодия выражена, её не заслоняют",
     "2026-11-06: «вариант B с более выраженной мелодией, да, B мне нравится»."),
    ("В8", "Ни одна нота рояля не теряется",
     "2026-11-10: «нота в ноту» (движок 2) и «без потерь» (ORCH_KEEP) одобрены: «да, B лучше»."),
    ("В9", "Оркестр не громче рояля: тихая пьеса остаётся тихой",
     "2026-11-10: громкость от пианиста и громкость за роялем одобрены («C получше», «B нравится больше»); "
     "2026-11-12: из «Лунной» выбран тихий образец C (в проигравшем A оркестр на 30 единиц громче рояля)."),
]


def _lead_notes(O, melody):
    """Для каждой ноты мелодии рояля: (начало, ведущий, слой мелодии, высота ведущего).
    Ведущий — самый высокий инструмент, который в этот момент берёт тот же звук (без октавы); слой мелодии — все,
    кто берёт этот звук не ниже октавы под ведущим (удвоения и тянущиеся голоса того же звука)."""
    o_sorted = sorted(O)
    o_starts = [x[0] for x in o_sorted]
    out = []
    for s, e, p in melody:
        lo, hi = bisect.bisect_left(o_starts, s - qg.TOL), bisect.bisect_right(o_starts, s + qg.TOL)
        m = [(q, n) for (s2, e2, q, n) in o_sorted[lo:hi] if q % 12 == p % 12]
        if not m:
            out.append((s, None, set(), None)); continue
        top, lead = max(m)
        out.append((s, lead, {n for q, n in m if q >= top - 12}, top))
    return out


def check(piano_path, orch_path, solo=False, one_lead=False):
    """Возвращает {"passed": [...], "failed": [(код, что не так)], "stats": {...}}."""
    P, _, _, pedal, bpb = qg._notes(piano_path)
    P = qg._with_pedal(P, pedal)
    O, names, _, _, obpb = qg._notes(orch_path)
    bpb = obpb or bpb
    melody = qg.melody_of(piano_path)
    gate = qg.check(piano_path, orch_path, melody=melody, solo=solo)
    st = gate["stats"]
    by = collections.defaultdict(list)
    for s, e, p, n in O:
        by[n].append((s, e, p))
    total = max(len(O), 1)
    failed, stats = [], {}

    # В1 резкий верх
    harsh = {}
    for n, lim in HARSH.items():
        ns = by.get(n)
        if not ns:
            continue
        dur = sum(e - s for s, e, _ in ns) or 1.0
        share = sum(e - s for s, e, p in ns if p > lim) / dur
        if share > 0.005:
            harsh[n] = round(share, 3)
    stats["harsh_top"] = harsh
    bad = {n: v for n, v in harsh.items() if v > HARSH_MAX}
    if bad:
        failed.append(("В1", "Высоко и резко: " + ", ".join("%s %d%% времени выше %s" % (
            RU.get(n, n), round(100 * v), _name(HARSH[n] + 1)) for n, v in bad.items())))

    # В2 перекличка, В3 скрипка (своё измерение: ведущий = самый высокий, кто берёт звук мелодии)
    carriers = _lead_notes(O, melody)
    bars = max(1, st.get("bars", 1))
    hops, prev = 0, None
    for s, lead_, layer, _ in carriers:
        if not lead_:
            continue
        if prev is not None and not (layer & prev):
            hops += 1
        prev = layer
    stats["melody_hops"] = hops
    stats["bars_per_hop"] = round(bars / hops, 1) if hops else None
    leads = [c[1] for c in carriers if c[1]]
    cnt = collections.Counter(leads)
    many = [n for n, k in cnt.most_common() if k >= LEAD_MIN_SHARE * max(len(leads), 1)]
    stats["leading_instruments"] = {n: round(cnt[n] / len(leads), 2) for n in many}
    if hops and bars / hops < HOP_BARS_MIN:
        failed.append(("В2", "Мелодия переходит к другому инструменту %d раз за %d тактов (раз в %.1f такта)."
                       % (hops, bars, bars / hops)))
    elif len(many) > LEADS_MAX and not solo:
        failed.append(("В2", "Мелодию по очереди ведут %d инструментов: %s." % (len(many), ", ".join(
            "%s %d%%" % (RU.get(n, n), round(100 * cnt[n] / len(leads))) for n in many))))
    vio = sum(1 for n in leads if n in ("Violin I", "Violin")) / max(len(leads), 1)
    stats["violin_lead_share"] = round(vio, 3)
    if not solo and vio > VIOLIN_MAX:
        failed.append(("В3", "Скрипка ведёт %d%% нот мелодии." % round(100 * vio)))

    # В4 весь состав (при одном ведущем или солисте молчащие деревянные — по замыслу, только сведения)
    quiet = [n for n in names if n in RU and n not in ("Piano", "Organ", "Accordion", "Guitar")
             and len(by.get(n, ())) < QUIET_SHARE * total]
    stats["quiet"] = quiet
    if quiet and not (solo or one_lead):
        failed.append(("В4", "Молчат или почти молчат: " + ", ".join(
            "%s (%d нот)" % (RU.get(n, n), len(by.get(n, ()))) for n in quiet)))

    # В5 контрабас
    cb = len(by.get("Double Bass", ()) or by.get("Contrabass", ()))
    stats["double_bass_notes"] = cb
    if "Double Bass" in names or "Contrabass" in names:
        if cb == 0 and not solo:
            failed.append(("В5", "Контрабас не играет."))

    # В6 отрывисто: у главного носителя мелодии
    owners = collections.Counter(leads)
    lead = owners.most_common(1)[0][0] if owners else None
    if lead:
        ns = sorted(by[lead])
        # повтор той же ноты без промежутка не сыграть — такие промежутки не считаются; меньше 1/20 доли — тоже
        gaps = [b[0] - a[1] for a, b in zip(ns, ns[1:]) if b[2] != a[2]]
        choppy = sum(1 for g in gaps if 0.05 < g <= CHOPPY_GAP) / max(len(gaps), 1)
        stats["lead"] = lead
        stats["lead_share"] = round(owners[lead] / max(len(leads), 1), 3)
        stats["lead_choppy"] = round(choppy, 3)
        if choppy > CHOPPY_MAX:
            failed.append(("В6", "Отрывисто: у ведущего (%s) после %d%% нот маленькая дырка до следующей."
                           % (RU.get(lead, lead), round(100 * choppy))))

    # В7 мелодия выражена: над ведущим не звучит чужой инструмент выше него
    o_sorted = sorted(O)
    o_starts = [x[0] for x in o_sorted]
    cov_n, cov_t = 0, 0
    for s, lead_, layer, top in carriers:
        if not lead_:
            continue
        cov_t += 1
        j = bisect.bisect_right(o_starts, s + qg.TOL)
        if any(q > top and n not in layer and e2 > s + qg.TOL for (s2, e2, q, n) in o_sorted[max(0, j - 400):j]):
            cov_n += 1
    cov = cov_n / max(cov_t, 1)
    stats["melody_covered"] = round(cov, 3)
    if cov > COVER_MAX:
        failed.append(("В7", "Над %d%% нот мелодии звучит другой инструмент выше неё." % round(100 * cov)))

    # В8 потерянные звуки рояля
    lost, tot = 0, 0
    for s, e, p, _ in P:
        if e - s <= 0:
            continue
        tot += 1
        lo, hi = bisect.bisect_left(o_starts, s - qg.TOL), bisect.bisect_right(o_starts, s + qg.TOL)
        if not any(q % 12 == p % 12 for (s2, e2, q, n) in o_sorted[lo:hi]):
            # звук мог уже тянуться в оркестре
            j = bisect.bisect_right(o_starts, s + qg.TOL)
            if not any(q % 12 == p % 12 and e2 > s for (s2, e2, q, n) in o_sorted[max(0, j - 400):j]):
                lost += 1
    share = lost / max(tot, 1)
    stats["lost_piano_notes"] = {"lost": lost, "total": tot}
    if share > LOST_MAX:
        failed.append(("В8", "Не звучат в оркестре %d из %d нот рояля." % (lost, tot)))

    # В9 громкость: средняя сила нажатия оркестра против рояля
    def _vel(path):
        import mido
        v = [x.velocity for tr in mido.MidiFile(path).tracks for x in tr
             if x.type == "note_on" and x.velocity > 0 and getattr(x, "channel", 0) != 9]
        return sum(v) / len(v) if v else 0.0
    vp, vo = _vel(piano_path), _vel(orch_path)
    stats["velocity"] = {"piano": round(vp, 1), "orchestra": round(vo, 1)}
    if vo > vp + LOUD_OVER:
        failed.append(("В9", "Оркестр громче рояля: средняя сила нажатия %d против %d." % (round(vo), round(vp))))

    codes = {c for c, _ in failed}
    return {"passed": [c for c, *_ in TASTE if c not in codes], "failed": failed, "stats": stats,
            "score": "%d из %d" % (len(TASTE) - len(codes), len(TASTE))}


_N = ["до", "до-диез", "ре", "ре-диез", "ми", "фа", "фа-диез", "соль", "соль-диез", "ля", "ля-диез", "си"]
_OCT = {3: "малой октавы", 4: "первой октавы", 5: "второй октавы", 6: "третьей октавы"}


def _name(p):
    return "%s %s" % (_N[p % 12], _OCT.get(p // 12 - 1, "октавы %d" % (p // 12 - 1)))


def text(res):
    lines = ["Проверка по вашему вкусу: выполнено %s пунктов." % res["score"]]
    names = {c: t for c, t, _ in TASTE}
    for c, msg in res["failed"]:
        lines.append("  ✗ %s %s — %s" % (c, names[c], msg))
    for c in res["passed"]:
        lines.append("  ✓ %s %s" % (c, names[c]))
    return "\n".join(lines)


if __name__ == "__main__":
    r = check(sys.argv[1], sys.argv[2], one_lead="--one-lead" in sys.argv)
    print(text(r))
    print(r["stats"])
