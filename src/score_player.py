"""
Партитурный проигрыватель (2026-11-08): подготовка файла на сервере.
Вход: многодорожечный MIDI или MusicXML (.musicxml, .xml, .mxl). Выход (для страницы проигрывателя):
  * какие инструменты есть (распознаются по названию дорожки, иначе по номеру инструмента General MIDI),
    в порядке партитуры: деревянные, медные, ударные, клавишные и арфа, струнные;
  * ноты (SVG verovio): каждый инструмент на своём стане;
  * карта времени (какая нота звучит на какой доле) для указателя;
  * MIDI для звука и номера каналов каждого инструмента (чтобы выключать инструменты).
Звук считается в браузере (spessasynth, банк звуков MS Basic или свой). Ничего не меняет в оркестровке.
Распознавание по названию и номеру — эвристика (таблица ниже наша, по стандарту General MIDI).
"""
import io, json, os, re, tempfile, zipfile

import mido

# (ключ, русское имя, порядок в партитуре, образец названия, номера GM 0..127)
INSTRUMENTS = [
    ("piccolo", "Флейта-пикколо", 10, r"piccolo|пикколо|picc", [72]),
    ("flute", "Флейта", 11, r"flute|flauto|fl[oö]te|флейт|\bfl\b|^fl\.?\s*\d*$", [73, 75]),
    ("oboe", "Гобой", 12, r"oboe|hautbois|гобо|\bob\b", [68]),
    ("rozhok", "Рожок", 13, r"rozhok|рожок|пастуш", []),
    ("english_horn", "Английский рожок", 13, r"english horn|cor anglais|английск", [69]),
    ("clarinet", "Кларнет", 14, r"clarinet|clarinetto|klarinette|кларнет|\bcl\b", [71]),
    ("bassoon", "Фагот", 15, r"bassoon|fagott|fagotto|basson|фагот|\bbsn\b|\bfg\b", [70]),
    ("saxophone", "Саксофон", 16, r"sax|саксоф", [64, 65, 66, 67]),
    ("horn", "Валторна", 20, r"french horn|\bhorn|corno|cor\b|waldhorn|валторн|\bhn\b", [60]),
    ("trumpet", "Труба", 21, r"trumpet|tromba|trompete|труба|\btpt\b", [56, 59]),
    ("trombone", "Тромбон", 22, r"trombone|posaune|тромбон|\btbn\b", [57]),
    ("tuba", "Туба", 23, r"tuba|туба", [58]),
    ("timpani", "Литавры", 30, r"timpani|pauken|литавр", [47]),
    ("percussion", "Ударные", 31, r"percussion|drum|ударн|барабан|treshchotk|трещотк|rattle|ratchet", []),
    ("harp", "Арфа", 40, r"harp|arpa|harfe|арф", [46]),
    ("piano", "Фортепиано", 41, r"piano|klavier|pianoforte|фортепиан|рояль|right hand|left hand|рука", list(range(0, 8))),
    ("organ", "Орган", 42, r"organ|orgel|орган", list(range(16, 21))),
    ("accordion", "Аккордеон", 43, r"accordion|akkordeon|аккорде|баян|garmon|harmon|гармон", [21, 22, 23]),
    ("balalaika", "Балалайка", 44, r"balalaika|балалайк", []),
    ("guitar", "Гитара", 44, r"guitar|gitarre|гитар", list(range(24, 32))),
    ("violin", "Скрипка", 50, r"violin|violino|violine|geige|скрипк|\bvln?\b|\bvl\.?\s*i", [40]),
    ("viola", "Альт", 52, r"viola|bratsche|альт|\bvla\b", [41]),
    ("cello", "Виолончель", 53, r"cello|violoncell|виолонч|\bvc\b|\bvlc\b", [42]),
    ("bass", "Контрабас", 54, r"contrabass|double bass|kontrabass|contrabbasso|контрабас|\bcb\b|\bdb\b|^bass$", [43]),
    ("strings", "Струнные", 55, r"strings|streicher|струнн", [44, 45, 48, 49, 50, 51]),
    ("choir", "Хор", 45, r"choir|chorus|voice|хор|голос", [52, 53, 54]),
]
BY_KEY = {k: (ru, order) for k, ru, order, _, _ in INSTRUMENTS}
UNKNOWN = ("other", "Инструмент", 60)


def identify(name, program=None, drum=False):
    """(ключ, русское имя, порядок) по названию дорожки, иначе по номеру GM. Эвристика."""
    if drum:
        return ("percussion",) + BY_KEY["percussion"]
    low = (name or "").strip().lower()
    # музыкальные названия бывают «Violin I», «Vln. 2», «Скрипка II»: римская цифра не мешает поиску
    for key, ru, order, pat, _ in INSTRUMENTS:
        if low and re.search(pat, low):
            if key == "viola" and re.search(r"violoncell|viola da gamba", low):
                continue
            return key, ru, order
    if program is not None:
        for key, ru, order, _, progs in INSTRUMENTS:
            if program in progs:
                return key, ru, order
    return UNKNOWN


def _roman(n):
    return ["", "I", "II", "III", "IV", "V", "VI"][n] if n < 7 else str(n)


def readable(name):
    """Название дорожки по-человечески. mido читает текст MIDI как латиницу, а русские названия записаны в UTF-8
    или Windows-1251 — получаются «кракозябры»; переводим обратно (2026-11-08)."""
    if not name or all(ord(c) < 128 for c in name):
        return name or ""
    try:
        raw = name.encode("latin-1")
    except UnicodeEncodeError:
        return name                      # уже нормальный текст
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return name


def _midi_tracks(mid):
    """Дорожки с нотами: [{"index", "name", "channels", "program", "notes", "drum"}]."""
    out = []
    for i, tr in enumerate(mid.tracks):
        name, chans, prog, n = readable((tr.name or "").strip()), set(), None, 0
        for m in tr:
            if m.type == "program_change" and prog is None:
                prog = m.program
            if m.type == "note_on" and m.velocity > 0:
                chans.add(m.channel)
                n += 1
            if m.type == "track_name" and not name:
                name = readable(m.name.strip())
        if n:
            out.append({"index": i, "name": name, "channels": sorted(chans), "program": prog, "notes": n,
                        "drum": chans == {9}})
    return out


def _number(parts):
    """Одинаковые инструменты подряд: «Скрипка I», «Скрипка II» (если номера нет в названии)."""
    count = {}
    for p in parts:
        count[p["key"]] = count.get(p["key"], 0) + 1
    seen = {}
    for p in parts:
        # номер из названия берём, только если в названии сам инструмент («Violin 2»), а не «Track 7»
        own = identify(p["source"])[0] == p["key"]
        if count[p["key"]] > 1 and (not own or not re.search(r"\b(i{1,3}|iv|\d)\b", p["source"].lower())):
            seen[p["key"]] = seen.get(p["key"], 0) + 1
            p["label"] = "%s %s" % (p["label"], _roman(seen[p["key"]]))
        elif count[p["key"]] > 1:
            m = re.search(r"\b(i{1,3}|iv|\d)\b", p["source"].lower())
            num = m.group(1).upper() if m else ""
            p["label"] = "%s %s" % (p["label"], {"1": "I", "2": "II", "3": "III", "4": "IV"}.get(num, num))
    return parts


def tempo_map(mid):
    """[(секунда, доля, секунд_на_долю)] из MIDI: перевод времени звука в доли для указателя."""
    tpb = mid.ticks_per_beat
    ev = []
    for tr in mid.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "set_tempo":
                ev.append((t, m.tempo))
    ev.sort()
    if not ev or ev[0][0] > 0:
        ev.insert(0, (0, 500000))
    out, sec, last_t, last_tempo = [], 0.0, 0, ev[0][1]
    for t, tempo in ev:
        sec += (t - last_t) / tpb * last_tempo / 1e6
        if out and t == last_t:
            out[-1] = (out[-1][0], out[-1][1], tempo / 1e6)
        else:
            out.append((round(sec, 6), t / tpb, tempo / 1e6))
        last_t, last_tempo = t, tempo
    return out


def meter_map(mid):
    """[(доля_от_начала, числитель, знаменатель)] из MIDI: для метронома (сильная доля — первая в такте)."""
    tpb, ev = mid.ticks_per_beat, []
    for tr in mid.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "time_signature":
                ev.append((t / tpb, m.numerator, m.denominator))
    ev.sort()
    out = []
    for q, n, d in ev:
        if out and abs(out[-1][0] - q) < 1e-9:
            out[-1] = (q, n, d)
        elif not out or (out[-1][1], out[-1][2]) != (n, d):
            out.append((q, n, d))
    if not out or out[0][0] > 0:
        out.insert(0, (0.0, 4, 4))
    return out


def _read_musicxml_text(data, name):
    if name.lower().endswith(".mxl") or data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = None
            if "META-INF/container.xml" in z.namelist():
                m = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml"))
                inner = m.group(1).decode() if m else None
            inner = inner or next(n for n in z.namelist() if n.endswith((".xml", ".musicxml")) and "META-INF" not in n)
            data = z.read(inner)
    return decode_xml(data)


def decode_xml(data):
    """Текст MusicXML: убирает метку BOM (её ставят программы Windows, verovio на ней молча отказывает),
    понимает UTF-16 и пишет в заголовке UTF-8."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    elif data[:4] in (b"<\x00?\x00", b"\x00<\x00?"):
        text = data.decode("utf-16-le" if data[:1] == b"<" else "utf-16-be", errors="replace")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1251", errors="replace") if b"1251" in data[:200] else data.decode("latin-1")
    text = text.lstrip("﻿ \t\r\n")
    # строка <!DOCTYPE …> со ссылкой на внешнюю схему: в облаке verovio на ней молча отказывал (2026-11-08)
    text = re.sub(r"<!DOCTYPE[^>\[]*(\[.*?\])?\s*>", "", text, count=1, flags=re.S)
    return re.sub(r'(<\?xml[^>]*encoding=["\'])[^"\']*(["\'])', r"\1UTF-8\2", text, count=1)


def is_musicxml(data, name=""):
    head = data[:2000].lstrip()
    return (name.lower().endswith((".musicxml", ".xml", ".mxl")) or data[:2] == b"PK"
            or b"<score-partwise" in head or b"<score-timewise" in head)



BUNDLED_VEROVIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verovio_data")
_NEED = ("Leipzig.xml", "Bravura.xml", "Leipzig.css", "text")


def make_toolkit():
    """verovio.toolkit() с проверкой шрифтов. В облаке бывало: «font resources are not available» (папка шрифтов
    библиотеки не найдена). Если в папке по умолчанию нет нужных файлов, берётся копия шрифтов из репозитория
    (src/verovio_data, Leipzig и Bravura). Вид нот при исправной папке тот же (проверено: SVG побайтно равны)."""
    import verovio
    tk = verovio.toolkit()
    try:
        cur = tk.getResourcePath()
    except Exception:
        cur = ""
    if not all(os.path.exists(os.path.join(cur, f)) for f in _NEED) and os.path.isdir(BUNDLED_VEROVIO):
        tk.setResourcePath(BUNDLED_VEROVIO)
    return tk


def load_verovio(tk, text):
    """tk.loadData с перехватом сообщений verovio: библиотека пишет причину отказа в системный поток ошибок,
    а не в getLog(). Возвращает (ok, текст сообщений). Звук и ноты не меняет."""
    import sys
    fd_err = sys.__stderr__.fileno() if sys.__stderr__ else 2
    cap = tempfile.TemporaryFile(mode="w+b")
    try:
        saved = os.dup(fd_err)
        os.dup2(cap.fileno(), fd_err)
        try:
            ok = tk.loadData(text)
        finally:
            os.dup2(saved, fd_err)
            os.close(saved)
    except OSError:
        ok = tk.loadData(text)
    cap.seek(0)
    msg = cap.read().decode("utf-8", "replace").strip()
    cap.close()
    return ok, msg[-400:]


def prepare(data, name="score.mid", page_width=1500, scale=34):
    """Готовит всё для страницы проигрывателя. Возвращает dict (см. начало файла). Ошибки не прячет."""
    import music21
    work = tempfile.mkdtemp(prefix="player_")
    notes = []
    if is_musicxml(data, name):
        xml = _read_musicxml_text(data, name)
        sc = music21.converter.parseData(xml, format="musicxml")
        parts = []
        for p in sc.parts:
            src = p.partName or ""
            inst = p.getInstrument(returnDefault=False)
            prog = getattr(inst, "midiProgram", None) if inst else None
            key, ru, order = identify(src or (inst.instrumentName if inst else ""), prog)
            parts.append({"key": key, "label": ru, "order": order, "source": src})
        mid_path = os.path.join(work, "sound.mid")
        import midi_repair
        snd = music21.converter.parseData(xml, format="musicxml")     # отдельная копия для звука
        if midi_repair.drop_grace(snd):
            notes.append("Форшлаги видны в нотах, но не звучат.")
        snd.write("midi", fp=mid_path)
        mid = mido.MidiFile(mid_path)
        # music21 даёт одинаковым инструментам (скрипка I и II) один канал: тогда их нельзя выключить по
        # отдельности. Каждой дорожке с нотами — свой канал (10-й только ударным).
        free = [c for c in range(16) if c != 9]
        k = 0
        for tr in mid.tracks:
            if not any(m.type == "note_on" for m in tr):
                continue
            drum = all(m.channel == 9 for m in tr if m.type == "note_on")
            ch = 9 if drum else free[k % len(free)]
            k += 0 if drum else 1
            for i, m in enumerate(tr):
                if hasattr(m, "channel"):
                    tr[i] = m.copy(channel=ch)
        mid.save(mid_path)
        tracks = _midi_tracks(mid)
        # music21 пишет по дорожке на партию в том же порядке (пустые партии без дорожки)
        k = 0
        for p, part in zip(parts, sc.parts):
            if part.recurse().notes and k < len(tracks):
                p["channels"] = tracks[k]["channels"]
                k += 1
            else:
                p["channels"] = []
        notation_xml = xml
        notes.append("Ноты показаны как в файле MusicXML (порядок станов — как в нём).")
        sound = open(mid_path, "rb").read()
    else:
        mid = mido.MidiFile(file=io.BytesIO(data))
        tracks = _midi_tracks(mid)
        if not tracks:
            raise ValueError("в файле нет нот")
        parts = []
        for t in tracks:
            key, ru, order = identify(t["name"], t["program"], t["drum"])
            parts.append({"key": key, "label": ru, "order": order, "source": t["name"], "channels": t["channels"],
                          "track": t["index"], "drum": t["drum"]})
        parts.sort(key=lambda p: (p["order"], p["track"]))       # порядок партитуры; одинаковые — как в файле
        sound = data
        # MIDI для нот: дорожки в порядке партитуры, ударные без нот (их звук остаётся)
        nm = mido.MidiFile(ticks_per_beat=mid.ticks_per_beat)
        meta = mido.MidiTrack()
        nm.tracks.append(meta)
        abs_meta = []
        for tr in mid.tracks:
            t = 0
            for m in tr:
                t += m.time
                if m.is_meta and m.type in ("set_tempo", "time_signature", "key_signature"):
                    abs_meta.append((t, m))
        last = 0
        for t, m in sorted(abs_meta, key=lambda x: x[0]):
            meta.append(m.copy(time=t - last))
            last = t
        shown = [p for p in parts if not p.get("drum")]
        for k, p in enumerate(shown):
            src = mid.tracks[p["track"]]
            tr = mido.MidiTrack()
            tr.append(mido.MetaMessage("track_name", name="P%02d" % k, time=0))
            carry = 0                                  # время пропущенных служебных событий переносится дальше
            for m in src:
                if m.is_meta and m.type in ("track_name", "set_tempo", "time_signature", "key_signature",
                                            "end_of_track"):
                    carry += m.time
                    continue
                tr.append(m.copy(time=m.time + carry))
                carry = 0
            nm.tracks.append(tr)
        if len(shown) < len(parts):
            notes.append("Ударные звучат, но в нотах не показаны.")
        tmp_mid = os.path.join(work, "notation.mid")
        nm.save(tmp_mid)
        import m21_fix
        sc = m21_fix.parse_midi(tmp_mid, quantizePost=True)
        parts = _number(parts)
        for k, part in enumerate(sc.parts):
            if k < len(shown):
                part.partName = shown[k]["label"]
                part.partAbbreviation = shown[k]["label"]
        xml_path = os.path.join(work, "notation.musicxml")
        import xml_safe
        xml_safe.write_musicxml(sc, xml_path)
        notation_xml = open(xml_path, encoding="utf-8").read()
        notes.append("Ноты сделаны из MIDI: ритм выровнен по долям приблизительно (как в MuseScore при открытии MIDI).")
    if is_musicxml(data, name):
        parts = _number(parts)
    _pr = {}                                    # номер инструмента (GM, с 0) по каналу: для проверки банка в проигрывателе
    for _t in mido.MidiFile(file=io.BytesIO(sound)).tracks:
        for _m in _t:
            if _m.type == "program_change" and _m.channel not in _pr:
                _pr[_m.channel] = _m.program
    for _p in parts:
        _p["program"] = next((_pr[c] for c in (_p.get("channels") or []) if c in _pr), None)
    tk = make_toolkit()
    tk.setOptions({"pageWidth": page_width, "pageHeight": 60000, "scale": scale, "adjustPageHeight": True,
                   "header": "none", "footer": "none", "pageMarginLeft": 30, "pageMarginRight": 30,
                   "pageMarginTop": 20, "pageMarginBottom": 20, "svgViewBox": True, "breaks": "auto",
                   "svgRemoveXlink": True})
    # Несколько попыток (в облаке verovio молча отказывал на MusicXML от music21): без BOM и DOCTYPE;
    # как есть; без комментариев; в конце music21 перезаписывает ноты заново.
    clean = decode_xml(notation_xml.encode("utf-8"))
    tried, seen, ok = [], [], False
    for label, variant in (("без DOCTYPE", clean), ("как есть", notation_xml),
                           ("без комментариев", re.sub(r"<!--.*?-->", "", clean, flags=re.S))):
        if variant in seen:
            continue
        seen.append(variant)
        ok, _msg = load_verovio(tk, variant)
        if ok:
            tried.append((label, None))
            break
        tried.append(("%s (verovio: %s)" % (label, _msg) if _msg else label, None))
    if not ok:
        try:
            alt = os.path.join(work, "again.musicxml")
            music21.converter.parseData(clean, format="musicxml").write("musicxml", fp=alt)
            tried.append(("перезапись music21", None))
            ok, _msg = load_verovio(tk, decode_xml(open(alt, "rb").read()))
            if not ok and _msg:
                tried.append(("перезапись: verovio: " + _msg, None))
            if ok:
                notes.append("Ноты пришлось перезаписать (исходный MusicXML распознаватель не принял).")
        except Exception as e:
            tried.append(("перезапись music21: %s" % e, None))
        if not ok:
            why = ("verovio %s не принял ноты (размер %d байт; пробовал: %s): %s"
                   % (tk.getVersion(), len(notation_xml), ", ".join(l for l, _ in tried),
                      (tk.getLog() or "причина не указана").strip()[-300:]))
            return {"parts": [{k: p.get(k) for k in ("key", "label", "source", "channels", "program")} for p in parts],
                    "pages": [], "timemap": [], "tempo": tempo_map(mido.MidiFile(file=io.BytesIO(sound))),
                    "meter": meter_map(mido.MidiFile(file=io.BytesIO(sound))),
                    "length": mido.MidiFile(file=io.BytesIO(sound)).length, "sound": sound,
                    "notes": notes + ["Ноты на экране показать не удалось, но играть файл можно. " + why], "name": name,
                    "notation_error": why}
    pages = [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]
    tm = tk.renderToTimemap({"includeMeasures": True, "includeRests": False})
    timemap = [{"q": e.get("qstamp", 0.0), "on": e.get("on", []), "off": e.get("off", []),
                "m": e.get("measureOn")} for e in tm]
    smid = mido.MidiFile(file=io.BytesIO(sound))
    return {"parts": [{k: p.get(k) for k in ("key", "label", "source", "channels", "program")} for p in parts],
            "pages": pages, "timemap": timemap, "tempo": tempo_map(smid), "meter": meter_map(smid), "length": smid.length,
            "sound": sound, "notes": notes, "name": name}


REVIEW_NAMES = {"flute": "Flute", "oboe": "Oboe", "clarinet": "Clarinet", "bassoon": "Bassoon", "horn": "Horn",
                "violin": "Violin", "viola": "Viola", "cello": "Violoncello", "bass": "Contrabass"}


def name_tracks(data):
    """Дорожкам с нотами, чьи названия рецензент (src/score_review.py) не понимает («Track 1», «Скрипка», пусто),
    даёт его английские названия по нашему распознаванию (название на любом языке, иначе номер инструмента GM).
    Возвращает (байты MIDI, [«было → стало»]). Ноты не меняются (2026-11-08)."""
    import score_review
    mid = mido.MidiFile(file=io.BytesIO(data))
    info = _midi_tracks(mid)
    keys = [identify(t["name"], t["program"], t["drum"])[0] for t in info]
    violins = sum(1 for k in keys if k == "violin")
    seen_v, changes = 0, []
    for t, k in zip(info, keys):
        if k == "violin":
            seen_v += 1
        if score_review._key(t["name"]) or k not in REVIEW_NAMES:
            continue
        new = REVIEW_NAMES[k]
        if k == "violin":
            new = "Violin II" if (violins > 1 and seen_v > 1) else "Violin I"
        tr = mid.tracks[t["index"]]
        for i, m in enumerate(tr):
            if m.type == "track_name":
                tr[i] = m.copy(name=new)
                break
        else:
            tr.insert(0, mido.MetaMessage("track_name", name=new, time=0))
        changes.append("«%s» → %s" % (t["name"] or "без названия", BY_KEY[k][0]))
    if not changes:
        return data, []
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue(), changes


def summary(prep):
    return "; ".join("%s (канал %s)" % (p["label"], ",".join(str(c + 1) for c in p["channels"]) or "—")
                     for p in prep["parts"])


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    prep = prepare(open(path, "rb").read(), os.path.basename(path))
    print(summary(prep))
    print("страниц:", len(prep["pages"]), "событий:", len(prep["timemap"]), "длина %.1f с" % prep["length"],
          "размер нот %d КБ" % (sum(len(s) for s in prep["pages"]) // 1024))
    print("\n".join(prep["notes"]))
