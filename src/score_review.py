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
    marks = []      # для каждого замечания: список клеток (инструмент или "*" = весь такт, номер_такта)

    def add(code, status, text, cells=()):
        findings.append(("замечание", code, status, text)); marks.append(sorted(set(cells), key=lambda c: (c[1], c[0])))
    def bar_of(beat): return int(beat // bpb) + 1

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
        bad = [(t["name"], bar_of(a)) for a, _, p in t["notes"] if p < lo or p > hi]
        if bad:
            add("K1", st, f"{t['name']}: {len(bad)} нот из {len(ps)} вне удобного диапазона ({lo}–{hi} по MIDI).", bad)

    # K2. Быстрые ноты у «неповоротливых» инструментов
    for t in tracks:
        if t["key"] in SLOW_INSTRUMENTS and t["notes"]:
            fast_cells = [(t["name"], bar_of(a)) for a, d, _ in t["notes"] if d < FAST_BEATS - 1e-6]
            fast = len(fast_cells)
            share = fast / len(t["notes"])
            if share > FAST_SHARE_LIMIT:
                add("K2", "подтверждено по смыслу (Черни, т. 3, с. 22 и 28: быстрое отдаётся струнным, валторна держит длинные ноты); порог 30% — эвристика",
                    f"{t['name']}: {fast} из {len(t['notes'])} нот ({share*100:.0f}%) короче полдоли. Это быстрые ноты для инструмента, которому такое не поручают.", fast_cells)

    # K3. Густота
    counts = [len(s) for s in play]
    walls = sum(1 for c in counts if c >= 8)
    if n and walls / n > WALL_SHARE:
        add("K3", "эвристика (Черни, с. 22: духовые не должны звучать постоянно; число тактов наше)",
            f"«Стена звука»: в {walls} тактах из {n} играют 8–10 инструментов сразу. Нет воздуха и нет выделенной мелодии.",
            [("*", b + 1) for b in range(n) if counts[b] >= 8])
    wind_over = [b + 1 for b in range(n) if sum(1 for t in tracks if t["key"] in WIND and t["name"] in play[b]) > MAX_WINDS_PER_BAR]
    if wind_over:
        add("K3", "эвристика (число 4 наше)", f"Духовых больше {MAX_WINDS_PER_BAR} одновременно в тактах: {_rng(wind_over)}.",
            [(t["name"], b) for b in wind_over for t in tracks if t["key"] in WIND and t["name"] in play[b - 1]])
    if counts and max(counts) - min(counts) > 4:
        add("K3", "эвристика (число 4 наше)", f"Состав скачет от {min(counts)} до {max(counts)} инструментов между тактами. На карте отмечены такты, где число инструментов меняется на 4 и больше.",
            [("*", b + 1) for b in range(1, n) if abs(counts[b] - counts[b - 1]) >= 4])

    # K4. Пустой низ
    hollow = [b + 1 for b in range(n) if play[b] and (low[b] is None or low[b] >= LOW_LIMIT)]
    if hollow:
        add("K4", "эвристика (граница C3 наша)", f"Нет ни одной ноты ниже C3 в тактах: {_rng(hollow)}. Низ пустой: проверьте на слух в наушниках.", [("*", b) for b in hollow])

    # K5. Первая скрипка молчит
    v1 = next((t for t in tracks if t["first_violin"]), None)
    if v1:
        silent = [b + 1 for b in range(n) if v1["name"] not in play[b]]
        runs = _runs(silent)
        long_runs = [r for r in runs if r[1] - r[0] + 1 >= VIOLIN1_SILENT_BARS]
        if long_runs:
            add("K5", "подтверждено по смыслу (Черни, с. 22: первая скрипка не должна слишком часто молчать); число тактов — эвристика",
                "Скрипка I молчит долго: такты " + ", ".join(f"{a}–{b}" for a, b in long_runs) + ".",
                [(v1["name"], b) for a, z in long_runs for b in range(a, z + 1)])

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
            cells = []
            if rid == "QX06":
                k = _key(msg.replace(" plays no notes", ""))
                cells = [(RU[k], b) for b in range(1, n + 1)] if k and k != "violin" else []
            elif where is not None:
                who = [_label_from_pair(x) for x in msg.split(" ", 2)[-1].split("-")] if rid in ("HM32", "HM05") else []
                cells = [(w, bar_of(float(where))) for w in who if w] or [("*", bar_of(float(where)))]
            add(rid, st, f"{ru.capitalize()}. Подробно: {msg}", cells)

    stats = {"тактов": n, "темп_уд_мин": round(bpm), "инструментов_в_такте_среднее": round(sum(counts) / n, 1) if n else 0,
             "инструментов_в_такте_мин_макс": [min(counts), max(counts)] if counts else [0, 0]}
    order = [t["name"] for t in tracks]
    return {"stats": stats, "findings": findings, "counts": counts, "marks": marks,
            "grid": {"instruments": order, "play": [sorted(s) for s in play]}}


def _label_from_pair(name):
    k = _key(name.strip())
    if not k: return None
    if k == "violin": return "Скрипка II" if "II" in name else "Скрипка I"
    return RU[k]


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


def map_html(res, only=None, standalone=False):
    """Карта партитуры: строки = инструменты, столбцы = такты.
    Светлая клетка: инструмент играет; пустая: молчит; красная: здесь замечание (номер в подсказке).
    only: номер замечания (с 0), чтобы показать только его; None = все."""
    import html as _h
    g = res.get("grid") or {}
    names, play = g.get("instruments", []), g.get("play", [])
    n = len(play)
    cell, col = {}, {}
    for i, cells in enumerate(res.get("marks", [])):
        if only is not None and i != only: continue
        code = res["findings"][i][1]
        for who, b in cells:
            (col.setdefault(b, []) if who == "*" else cell.setdefault((who, b), [])).append(f"{i+1}. {code}")
    css = ("<style>.smap{border-collapse:collapse;font:11px/1.2 sans-serif;color:#3b2a1a}"
           ".smap td,.smap th{border:1px solid #d8ccb4;width:16px;min-width:16px;height:18px;padding:0;text-align:center}"
           ".smap th.nm{position:sticky;left:0;background:#f7f0e1;text-align:right;padding:0 6px;white-space:nowrap;width:auto}"
           ".smap .on{background:#e4d3ad}.smap .bad{background:#c0392b;color:#fff}"
           ".smap .badoff{background:#f3c4bd}.smap .hbad{background:#c0392b;color:#fff}"
           ".smap thead th{font-weight:normal;font-size:9px;background:#f7f0e1}"
           ".smapwrap{overflow-x:auto;max-width:100%;border:1px solid #d8ccb4;border-radius:6px}"
           ".smapleg span{display:inline-block;width:12px;height:12px;vertical-align:middle;margin:0 4px 0 12px;border:1px solid #d8ccb4}</style>")
    rows = ["<tr><th class='nm'>Такт</th>" + "".join(
        f"<th class='{'hbad' if b in col else ''}' title='{_h.escape('; '.join(col.get(b, [])))}'>{b}</th>" for b in range(1, n + 1)) + "</tr>"]
    body = []
    for nm in names:
        tds = []
        for b in range(1, n + 1):
            on = nm in play[b - 1]
            m = cell.get((nm, b), []) + col.get(b, [])
            cls = ("bad" if on else "badoff") if m else ("on" if on else "")
            tip = f"{nm}, такт {b}" + (": " + "; ".join(m) if m else ("" if on else " (молчит)"))
            tds.append(f"<td class='{cls}' title='{_h.escape(tip)}'></td>")
        body.append(f"<tr><th class='nm'>{_h.escape(nm)}</th>{''.join(tds)}</tr>")
    leg = ("<div class='smapleg' style='font:12px sans-serif;margin:6px 0'><span class='on' style='background:#e4d3ad'></span>играет"
           "<span></span>молчит<span style='background:#c0392b'></span>замечание (инструмент играет)"
           "<span style='background:#f3c4bd'></span>замечание (инструмент молчит). Наведите на клетку: номер замечания.</div>")
    out = css + f"<div class='smapwrap'><table class='smap'><thead>{rows[0]}</thead><tbody>{''.join(body)}</tbody></table></div>" + leg
    if standalone:
        # Отдельная страница: карта для каждого замечания, переключение нажатием на замечание (без внешних библиотек).
        maps = [("Все замечания сразу", None)] + [(f"{i+1}. [{f[1]}]", i) for i, f in enumerate(res["findings"])]
        blocks = "".join(f"<div class='mv' id='mv{k}' style='display:{'block' if k == 0 else 'none'}'>"
                         + (out if idx is None else map_html(res, only=idx)) + "</div>" for k, (_, idx) in enumerate(maps))
        items = "".join(f"<li onclick='sh({i+1})' id='li{i+1}' style='cursor:pointer;padding:4px;border-radius:4px'><b>[{c}]</b> {_h.escape(t)}"
                        f"<br><small>Статус правила: {_h.escape(st)}</small></li>"
                        for i, (_, c, st, t) in enumerate(res["findings"])) or "<li>Замечаний нет.</li>"
        js = ("<script>function sh(k){document.querySelectorAll('.mv').forEach(e=>e.style.display='none');"
              "document.getElementById('mv'+k).style.display='block';document.querySelectorAll('li').forEach(e=>e.style.background='');"
              "var l=document.getElementById('li'+k);if(l)l.style.background='#efe2c4';}</script>")
        out = ("<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
               "<title>Карта замечаний</title></head><body style='background:#fbf7ee;margin:16px;font:14px sans-serif;color:#3b2a1a'>"
               "<h2>Карта замечаний по партитуре</h2><p>Модуль считает, а не слушает: звучание оценивает слушатель. "
               "Нажмите на замечание в списке, чтобы увидеть на карте только его. "
               "<a href='#' onclick='sh(0);return false'>Показать все сразу</a>.</p>"
               + blocks + f"<h3>Замечания</h3><ol>{items}</ol>{js}</body></html>")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Использование: python src/score_review.py оркестровка.mid [оркестровка.musicxml] [--map]"); sys.exit(1)
    r = review(args[0], args[1] if len(args) > 1 else None)
    print(report_text(r, os.path.basename(args[0])))
    if "--map" in sys.argv:
        out = os.path.splitext(args[0])[0] + "_карта_замечаний.html"
        open(out, "w", encoding="utf-8").write(map_html(r, standalone=True)); print("Карта:", out)
