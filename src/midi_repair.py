"""
Ремонт MIDI на входе (2026-11-08). Причина: пользователь по 10 минут перебирал файлы, потому что часть MIDI
с сайтов и из мессенджеров не открывалась («badly formed midi», «data byte must be in range 0..127», EOFError).

repair(data, name) -> (чистый_MIDI_байты, [что исправлено по-русски]) или исключение MidiRepairError с
понятной причиной. Делает:
  * находит MIDI внутри файла: обычный, RIFF (.rmi), с заголовком перед MIDI (MacBinary), внутри zip-архива;
  * читает бережно: неверная длина дорожки, обрезанный конец, испорченные байты, нет «конца дорожки»,
    длинный заголовок, несуществующий тип события — плохое место пропускается, остальное сохраняется;
  * время в кадрах SMPTE переводится в обычные доли;
  * формат 0 (все инструменты в одной дорожке) раскладывается по дорожкам: одна дорожка на канал;
  * незакрытые ноты закрываются в конце дорожки;
  * записывает заново стандартный MIDI (формат 1) — его читают mido, music21, verovio и проигрыватель.
Ноты и их время не меняются (кроме перечисленного ремонта).
"""
import io, struct, zipfile

import mido
from mido.midifiles.meta import build_meta_message


class MidiRepairError(ValueError):
    pass


def _find(data, name=""):
    """Байты, начиная с 'MThd'. Понимает zip, RIFF и служебный заголовок перед MIDI."""
    fixes = []
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = [n for n in z.namelist() if not n.endswith("/")]
                pick = [n for n in names if n.lower().endswith((".mid", ".midi", ".kar", ".rmi", ".smf"))] or names
                for n in pick:
                    inner = z.read(n)
                    if b"MThd" in inner[:4096]:
                        fixes.append("MIDI взят из архива: «%s»" % n.split("/")[-1])
                        data = inner
                        break
                else:
                    raise MidiRepairError("в архиве нет MIDI-файла")
        except zipfile.BadZipFile:
            raise MidiRepairError("файл похож на архив, но архив повреждён")
    i = data.find(b"MThd", 0, 4096)
    if i < 0:
        head = data[:200].lstrip().lower()
        if head.startswith(b"<?xml") or b"<score-partwise" in head:
            raise MidiRepairError("это MusicXML, а не MIDI")
        if data[:3] == b"ID3" or data[:4] in (b"RIFF", b"OggS", b"fLaC") or data[4:8] == b"ftyp":
            raise MidiRepairError("это звукозапись (mp3/wav/ogg/m4a), а не MIDI: в ней нет нот")
        raise MidiRepairError("внутри нет признака MIDI-файла («MThd»)")
    if i > 0:
        fixes.append("перед MIDI было %d служебных байт (%s) — пропущены" % (i, "RIFF" if data[:4] == b"RIFF" else "заголовок"))
    return data[i:], fixes


def _varlen(b, pos, end):
    v = 0
    for _ in range(4):
        if pos >= end:
            raise EOFError
        c = b[pos]
        pos += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, pos
    return v, pos


_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


def _parse_track(b, start, end):
    """[(абсолютный тик, mido-сообщение)], число пропущенных мест, обрезан ли конец, тик конца дорожки."""
    out, pos, t, running, skipped, cut, eot = [], start, 0, None, 0, False, None
    while pos < end:
        try:
            delta, pos = _varlen(b, pos, end)
            t += delta
            if pos >= end:
                cut = True
                break
            st = b[pos]
            if st >= 0x80:
                pos += 1
            elif running is None:
                skipped += 1               # данные без статуса: пропускаем байт
                pos += 1
                continue
            else:
                st = running
            if st == 0xFF:
                if pos >= end:
                    raise EOFError
                typ = b[pos]
                ln, pos = _varlen(b, pos + 1, end)
                if pos + ln > end:
                    raise EOFError
                payload = bytes(b[pos:pos + ln])
                pos += ln
                if typ == 0x2F:
                    eot = t                 # конец дорожки (вместе с тишиной перед ним)
                    break
                try:
                    out.append((t, build_meta_message(typ, payload, 0)))
                except Exception:
                    skipped += 1
                continue
            if st in (0xF0, 0xF7):
                ln, pos = _varlen(b, pos, end)
                if pos + ln > end:
                    raise EOFError
                payload = bytes(b[pos:pos + ln])
                pos += ln
                if st == 0xF0 and payload[-1:] == b"\xF7":
                    payload = payload[:-1]
                if st == 0xF0 and all(x < 0x80 for x in payload):
                    out.append((t, mido.Message("sysex", data=list(payload))))
                continue
            if st >= 0xF0:                  # системные события в файле не нужны
                skipped += 1
                continue
            running = st
            n = _DATA_LEN[st & 0xF0]
            if pos + n > end:
                raise EOFError
            d = list(b[pos:pos + n])
            if any(x >= 0x80 for x in d):   # испорченный байт данных: событие пропускаем
                skipped += 1
                pos += next(k for k, x in enumerate(d) if x >= 0x80)
                continue
            pos += n
            out.append((t, mido.Message.from_bytes([st] + d)))
        except EOFError:
            cut = True
            break
        except Exception:
            skipped += 1
            pos += 1
    return out, skipped, cut, eot


def _chunks(b):
    """[(начало данных, конец данных, тип)] с бережным определением длины."""
    pos, out = 0, []
    starts = []
    k = b.find(b"MTrk")
    while k >= 0:
        starts.append(k)
        k = b.find(b"MTrk", k + 4)
    while pos + 8 <= len(b):
        typ = bytes(b[pos:pos + 4])
        ln = struct.unpack(">I", b[pos + 4:pos + 8])[0]
        end = pos + 8 + ln
        nxt = next((s for s in starts if s > pos), None)
        if typ == b"MTrk":
            # длине верим, если после дорожки начинается следующая, или это последняя дорожка и файл не короче
            ok = end <= len(b) and (b[end:end + 4] == b"MTrk" or nxt is None or nxt >= end)
            if not ok:
                end = nxt if nxt is not None else len(b)
            out.append((pos + 8, min(end, len(b)), typ, ok))
            pos = end
        else:
            if end <= len(b) and (nxt is None or end <= nxt):
                pos = end                    # чужой блок: пропускаем
            elif nxt is not None:
                pos = nxt
            else:
                break
    return out


def repair(data, name=""):
    """Любой вход (MIDI в любом виде или MusicXML) -> чистый MIDI. MusicXML переводится в MIDI (2026-11-08)."""
    pre = []
    if is_musicxml(data, name):
        data, note = from_musicxml(data, name)
        pre.append(note)
    clean, fixes = _repair_midi(data, name)
    return clean, pre + fixes


def _repair_midi(data, name=""):
    raw, fixes = _find(data, name)
    if len(raw) < 14:
        raise MidiRepairError("файл слишком короткий: MIDI обрезан в самом начале")
    hlen = struct.unpack(">I", raw[4:8])[0]
    fmt, ntrk, div = struct.unpack(">HHH", raw[8:14])
    if hlen != 6:
        fixes.append("нестандартная длина заголовка (%d) — исправлена" % hlen)
    body = raw[8 + max(hlen, 6):]
    smpte = div & 0x8000
    if smpte:
        fps = 256 - (div >> 8)
        tpf = div & 0xFF
        tps = fps * tpf                      # тиков в секунду
        tpb, tempo = max(24, tps // 2), 500000
        fixes.append("время было в кадрах SMPTE (%d кадр/с) — переведено в доли" % fps)
    else:
        tpb, tempo = div or 480, None
        if not div:
            fixes.append("в заголовке не было разрешения времени — взято 480")
    tracks, ends, skipped_all, cut_any, badlen = [], [], 0, False, 0
    for start, end, _, ok in _chunks(body):
        ev, skipped, cut, eot = _parse_track(body, start, end)
        ends.append(eot or 0)
        skipped_all += skipped
        cut_any |= cut
        badlen += 0 if ok else 1
        tracks.append(ev)
    if not tracks:
        raise MidiRepairError("в файле нет ни одной дорожки (MTrk)")
    if len(tracks) != ntrk:
        fixes.append("в заголовке %d дорожек, найдено %d" % (ntrk, len(tracks)))
    if badlen:
        fixes.append("неверная длина у %d дорожек — найдены по меткам" % badlen)
    if cut_any:
        fixes.append("файл обрезан (недокачан?) — сохранено всё, что успело записаться")
    if skipped_all:
        fixes.append("пропущено испорченных мест: %d" % skipped_all)
    if smpte:
        tracks = [[(t, m) for t, m in tr if not (m.is_meta and m.type == "set_tempo")] for tr in tracks]
        tracks[0].insert(0, (0, mido.MetaMessage("set_tempo", tempo=tempo)))
    # формат 0 / одна дорожка с несколькими каналами -> дорожка на канал
    note_ch = lambda tr: {m.channel for _, m in tr if not m.is_meta and m.type == "note_on"}
    with_notes = [tr for tr in tracks if note_ch(tr)]
    if len(with_notes) == 1 and len(note_ch(with_notes[0])) > 1:
        src = with_notes[0]
        meta = [(t, m) for t, m in src if m.is_meta or m.type == "sysex"]
        chans = sorted({m.channel for _, m in src if not m.is_meta and m.type != "sysex"})
        new = [meta]
        for ch in chans:
            new.append([(t, m) for t, m in src if not m.is_meta and m.type != "sysex" and m.channel == ch])
        others = [tr for tr in tracks if tr is not src]
        tracks = others + new
        fixes.append("все инструменты были в одной дорожке (формат 0) — разложены по %d дорожкам" % len(chans))
    # нулевые ноты (форшлаги из music21): «отпустить» стоит раньше «нажать» в том же тике -> нота длиной 1/32
    grace = 0
    short = max(1, tpb // 8)
    for k, tr in enumerate(tracks):
        tr = sorted(tr, key=lambda x: x[0])
        active, out = {}, []
        for idx, (t, m) in enumerate(tr):
            if m.type in ("note_off", "note_on") and not (m.type == "note_on" and m.velocity > 0):
                key = (m.channel, m.note)
                if not active.get(key):
                    later = any(t2 == t and m2.type == "note_on" and m2.velocity > 0 and (m2.channel, m2.note) == key
                                for t2, m2 in tr[idx + 1:idx + 64] if t2 == t)
                    if later:
                        nxt = min([t2 for t2, m2 in tr[idx + 1:] if t2 > t and m2.type == "note_on" and m2.velocity > 0
                                   and (m2.channel, m2.note) == key] + [t + short])
                        out.append((max(t + 1, nxt), m))
                        grace += 1
                        continue
                else:
                    active[key] -= 1
            elif m.type == "note_on":
                active[(m.channel, m.note)] = active.get((m.channel, m.note), 0) + 1
            out.append((t, m))
        tracks[k] = sorted(out, key=lambda x: x[0])     # устойчиво: порядок в одном тике сохраняется
    if grace:
        fixes.append("нот нулевой длины (форшлаги) сделано короткими: %d" % grace)
    # незакрытые ноты
    hanging = 0
    for tr in tracks:
        on = {}
        last = max((t for t, _ in tr), default=0)
        for t, m in tr:
            if m.type == "note_on" and m.velocity > 0:
                on[(m.channel, m.note)] = on.get((m.channel, m.note), 0) + 1
            elif m.type in ("note_off", "note_on") and on.get((m.channel, m.note)):
                on[(m.channel, m.note)] -= 1
        for (ch, note), n in on.items():
            for _ in range(n):
                tr.append((last + tpb // 2, mido.Message("note_off", channel=ch, note=note, velocity=0)))
                hanging += 1
    if hanging:
        fixes.append("незакрытых нот закрыто в конце: %d" % hanging)
    if not any(m.type == "note_on" and m.velocity > 0 for tr in tracks for _, m in tr if not m.is_meta):
        raise MidiRepairError("в файле нет нот")
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    tail = max(ends + [0])                                     # тишина в конце пьесы, как в исходном файле
    for tr in tracks:
        mt = mido.MidiTrack()
        last = 0
        for t, m in sorted(tr, key=lambda x: x[0]):          # сортировка устойчивая: порядок в один тик сохраняется
            mt.append(m.copy(time=t - last))
            last = t
        mt.append(mido.MetaMessage("end_of_track", time=max(0, tail - last)))
        mid.tracks.append(mt)
    buf = io.BytesIO()
    mid.save(file=buf)
    clean = buf.getvalue()
    mido.MidiFile(file=io.BytesIO(clean))                    # самопроверка: чистый файл читается
    return clean, fixes


def is_musicxml(data, name=""):
    """MusicXML: .musicxml/.xml (текст) или .mxl (zip с MusicXML внутри)."""
    if data[:2] == b"PK":
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except Exception:
            return False
        if any(n.lower().endswith((".mid", ".midi", ".kar")) for n in names):
            return False
        return any(n.lower().endswith((".musicxml", ".xml")) and not n.startswith("META-INF") for n in names)
    head = data[:20000]
    return b"<score-partwise" in head or b"<score-timewise" in head


def drop_grace(sc):
    """Убирает форшлаги (ноты без длительности) перед записью MIDI: music21 пишет их нулевой длины, и в MIDI они
    путают пары «нажал/отпустил» с соседними нотами той же высоты. Возвращает число убранных."""
    n = 0
    for el in list(sc.recurse().notes):
        try:
            if el.duration.isGrace:
                el.activeSite.remove(el)
                n += 1
        except Exception:
            pass
    return n


def from_musicxml(data, name=""):
    """MusicXML -> MIDI (байты) через music21. Повторы (репризы, вольты) разворачиваются, как при экспорте
    MIDI из MuseScore; если развернуть не удалось — играется как написано."""
    import os, sys, tempfile
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import music21, score_player
    try:
        xml = score_player._read_musicxml_text(data, name)
        sc = music21.converter.parseData(xml, format="musicxml")
    except Exception as e:
        raise MidiRepairError("MusicXML не читается (%s: %s)" % (type(e).__name__, str(e)[:120]))
    note = "MusicXML переведён в MIDI"
    ng = drop_grace(sc)
    try:
        ex = sc.expandRepeats()
        if ex is not None and ex.highestTime > sc.highestTime + 1e-6:
            sc, note = ex, note + " (повторы развёрнуты)"
    except Exception:
        pass
    if ng:
        note += "; форшлаги (короткие украшения) не озвучены: %d" % ng
    path = os.path.join(tempfile.mkdtemp(prefix="xml2mid_"), "score.mid")
    try:
        sc.write("midi", fp=path)
    except Exception as e:
        raise MidiRepairError("MusicXML не удалось превратить в MIDI (%s: %s)" % (type(e).__name__, str(e)[:120]))
    with open(path, "rb") as f:
        return f.read(), note


def text(fixes):
    return "Файл подготовлен: " + "; ".join(fixes) + "." if fixes else ""


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        try:
            clean, fx = repair(open(p, "rb").read(), p)
            print("%-30s OK  %s" % (p.split("/")[-1], "; ".join(fx) or "без ремонта"))
        except MidiRepairError as e:
            print("%-30s ОТКАЗ: %s" % (p.split("/")[-1], e))
