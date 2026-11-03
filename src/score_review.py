"""
Академическая проверка оркестровой партитуры (модуль «рецензент»).

Вход: MIDI оркестровки (по дорожкам). Дополнительно можно передать MusicXML, тогда в отчёт войдут и проверки
валидатора (параллельные квинты и октавы, дыхание духовых, плотность удвоений).
Выход: отчёт по-русски простыми словами и словарь с теми же данными.

Правила модуля:
  * Ничего не исправляет и ничего не блокирует: только замечания.
  * У каждого правила честный статус: «подтверждено» (книга и страница), «эвристика» (наше число, в книге
    не найдено) или «не подтверждено». Порог, взятый «на глаз», всегда назван эвристикой.
  * Звучание модуль не оценивает: он считает ноты, такты, инструменты. Судья звучания: слушатель.
"""
import os, sys
from collections import defaultdict
import mido

STR = {"violin", "viola", "cello", "double_bass"}
WIND = {"flute", "oboe", "clarinet", "bassoon", "horn"}
RU = {"flute": "Флейта", "oboe": "Гобой", "clarinet": "Кларнет", "bassoon": "Фагот", "horn": "Валторна",
      "violin": "Скрипка", "viola": "Альт", "cello": "Виолончель", "double_bass": "Контрабас"}

# Пороги. Все числа ниже: эвристика автора, если не сказано иное.
FAST_BEATS = 0.5          # нота короче полдоли считается «быстрой»
FAST_SHARE_LIMIT = 0.30   # доля быстрых нот, выше которой у «неповоротливых» инструментов выдаём замечание
SLOW_INSTRUMENTS = {"horn", "bassoon", "double_bass"}   # Черни с. 22 и 28: быстрое отдаётся струнным; валторна держит длинные
MAX_WINDS_PER_BAR = 4     # эвристика (в Черни число не указано; с. 22: духовые не должны звучать постоянно)
WALL_SHARE = 0.5          # «стена звука»: доля тактов, где играют 8 и более инструментов (эвристика)
LOW_LIMIT = 48            # C3: если в такте нет нот ниже этой, низ «пустой» (эвристика)
VIOLIN1_SILENT_BARS = 4   # Черни с. 22: первая скрипка не должна слишком часто молчать; число тактов эвристика


def _key(name):
    n = name.lower()
    if "piano" in n or "фортепиано" in n: return None
    if "double" in n or "contrabass" in n: return "double_bass"
    if "violoncello" in n or "cello" in n: return "cello"
    if "viola" in n: return "viola"
    if "violin" in n: return "violin"
    for k in WIND:
        if k in n: return k
    return None


def read_midi(path):
    """Возвращает (дорожки, доли_в_такте, темп_уд_в_мин). Дорожка: dict(name, key, notes=[(старт_в_долях, длина_в_долях, высота)])."""
    m = mido.MidiFile(path)
    tpb = m.ticks_per_beat
    tempo, beats_per_bar = 500000, 4.0
    for t in m.tracks:
        ticks = 0
        for msg in t:
            ticks += msg.time
            if msg.type == "set_tempo" and ticks == 0: tempo = msg.tempo
            if msg.type == "time_signature" and ticks == 0:
                beats_per_bar = msg.numerator * 4.0 / msg.denominator
    tracks, seen = [], defaultdict(int)
    for t in m.tracks:
        key = _key(t.name or "")
        if key is None: continue
        ticks, on, notes = 0, {}, []
        for msg in t:
            ticks += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                on[msg.note] = ticks
            elif msg.type in ("note_off", "note_on") and msg.note in on:
                st = on.pop(msg.note)
                notes.append((st / tpb, max(ticks - st, 1) / tpb, msg.note))
        seen[key] += 1
        label = RU[key]
        if key == "violin": label += " I" if seen[key] == 1 else " II"
        tracks.append({"name": label, "key": key, "notes": sorted(notes), "first_violin": key == "violin" and seen[key] == 1})
    return tracks, beats_per_bar, 60e6 / tempo


def _bar_sets(tracks, bpb):
    total = max((a + d for t in tracks for a, d, _ in t["notes"]), default=0)
    n = int(total // bpb) + (1 if total % bpb > 1e-6 else 0)
    play = [set() for _ in range(n)]      # кто играет в такте
    low = [None] * n                      # самая низкая нота такта
    for t in tracks:
        for a, d, p in t["notes"]:
            for b in range(int(a // bpb), min(n, int((a + d - 1e-6) // bpb) + 1)):
                play[b].add(t["name"])
                low[b] = p if low[b] is None else min(low[b], p)
    return n, play, low


def _ranges():
    try:
        import validator
        return validator.RANGES_BERLIOZ, validator.RANGES_OLD
    except Exception:
        return {}, {}


def review(midi_path, musicxml_path=None):
    tracks, bpb, bpm = read_midi(midi_path)
    n, play, low = _bar_sets(tracks, bpb)
    findings = []   # (важность, код, статус, текст)

    def add(code, status, text): findings.append(("замечание", code, status, text))

    # K1. Диапазоны
    berlioz, old = _ranges()
    for t in tracks:
        ps = [p for _, _, p in t["notes"]]
        if not ps: continue
        if t["key"] in berlioz:
            lo, hi = berlioz[t["key"]]; st = "подтверждено (Берлиоз, главы об инструментах)"
        elif t["key"] in old:
            lo, hi = old[t["key"]]; st = "не подтверждено (таблица проекта; у Берлиоза для этого инструмента число не названо)"
        else: continue
        out = sum(1 for p in ps if p < lo or p > hi)
        if out:
            add("K1", st, f"{t['name']}: {out} нот из {len(ps)} вне удобного диапазона ({lo}–{hi} по MIDI).")

    # K2. Быстрые ноты у «неповоротливых» инструментов
    for t in tracks:
        if t["key"] in SLOW_INSTRUMENTS and t["notes"]:
            fast = sum(1 for _, d, _ in t["notes"] if d < FAST_BEATS - 1e-6)
            share = fast / len(t["notes"])
            if share > FAST_SHARE_LIMIT:
                add("K2", "подтверждено по смыслу (Черни, т. 3, с. 22 и 28: быстрое отдаётся струнным, валторна держит длинные ноты); порог 30% — эвристика",
                    f"{t['name']}: {fast} из {len(t['notes'])} нот ({share*100:.0f}%) короче полдоли. Это быстрые ноты для инструмента, которому такое не поручают.")

    # K3. Густота
    counts = [len(s) for s in play]
    walls = sum(1 for c in counts if c >= 8)
    if n and walls / n > WALL_SHARE:
        add("K3", "эвристика (Черни, с. 22: духовые не должны звучать постоянно; число тактов наше)",
            f"«Стена звука»: в {walls} тактах из {n} играют 8–10 инструментов сразу. Нет воздуха и нет выделенной мелодии.")
    wind_over = [b + 1 for b in range(n) if sum(1 for t in tracks if t["key"] in WIND and t["name"] in play[b]) > MAX_WINDS_PER_BAR]
    if wind_over:
        add("K3", "эвристика (число 4 наше)", f"Духовых больше {MAX_WINDS_PER_BAR} одновременно в тактах: {_rng(wind_over)}.")
    if counts and max(counts) - min(counts) > 4:
        add("K3", "эвристика (число 4 наше)", f"Состав скачет от {min(counts)} до {max(counts)} инструментов между тактами.")

    # K4. Пустой низ
    hollow = [b + 1 for b in range(n) if play[b] and (low[b] is None or low[b] >= LOW_LIMIT)]
    if hollow:
        add("K4", "эвристика (граница C3 наша)", f"Нет ни одной ноты ниже C3 в тактах: {_rng(hollow)}. Низ пустой: проверьте на слух в наушниках.")

    # K5. Первая скрипка молчит
    v1 = next((t for t in tracks if t["first_violin"]), None)
    if v1:
        silent = [b + 1 for b in range(n) if v1["name"] not in play[b]]
        runs = _runs(silent)
        long_runs = [r for r in runs if r[1] - r[0] + 1 >= VIOLIN1_SILENT_BARS]
        if long_runs:
            add("K5", "подтверждено по смыслу (Черни, с. 22: первая скрипка не должна слишком часто молчать); число тактов — эвристика",
                "Скрипка I молчит долго: такты " + ", ".join(f"{a}–{b}" for a, b in long_runs) + ".")

    # K6. Проверки валидатора (нужен MusicXML)
    vissues = []
    if musicxml_path and os.path.exists(musicxml_path):
        try:
            import validator
            vissues, _ = validator.check_score(musicxml_path)
        except Exception as e:
            add("V0", "служебное", f"Проверки валидатора не выполнены: {e}")
    VR = {"HM32": ("параллельные квинты между голосами", "общее правило голосоведения; в таблице правил проекта, источник не перепроверен"),
          "HM05": ("параллельные октавы между скрипками", "общее правило голосоведения; источник не перепроверен"),
          "QX04": ("у духовых слишком долгая игра без паузы на дыхание", "эвристика (16 долей наши)"),
          "QX05": ("слишком много унисонных удвоений", "эвристика (порог 1,35 наш)"),
          "QX06": ("инструмент не играет ни одной ноты (не ошибка, если так задумано)", "эвристика")}
    for sev, rid, where, msg in vissues:
        if rid in VR:
            ru, st = VR[rid]
            add(rid, st, f"{ru.capitalize()}. Подробно: {msg}")

    stats = {"тактов": n, "темп_уд_мин": round(bpm), "инструментов_в_такте_среднее": round(sum(counts) / n, 1) if n else 0,
             "инструментов_в_такте_мин_макс": [min(counts), max(counts)] if counts else [0, 0]}
    return {"stats": stats, "findings": findings, "counts": counts}


def _runs(bars):
    runs = []
    for b in bars:
        if runs and b == runs[-1][1] + 1: runs[-1][1] = b
        else: runs.append([b, b])
    return runs


def _rng(bars):
    return ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in _runs(bars))


def report_text(res, title):
    s = res["stats"]
    L = [f"# Рецензия на партитуру: {title}", "",
         f"Тактов: {s['тактов']}, темп около {s['темп_уд_мин']} уд/мин. Инструментов в такте: в среднем {s['инструментов_в_такте_среднее']}, "
         f"от {s['инструментов_в_такте_мин_макс'][0]} до {s['инструментов_в_такте_мин_макс'][1]}.", "",
         "Модуль считает, а не слушает. Звучание оценивает слушатель.", ""]
    if not res["findings"]:
        L.append("Замечаний нет.")
    for i, (_, code, st, text) in enumerate(res["findings"], 1):
        L += [f"{i}. [{code}] {text}", f"   Статус правила: {st}.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Использование: python src/score_review.py оркестровка.mid [оркестровка.musicxml]"); sys.exit(1)
    r = review(args[0], args[1] if len(args) > 1 else None)
    print(report_text(r, os.path.basename(args[0])))
