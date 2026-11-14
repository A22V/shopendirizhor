"""
Партитура нотами с красными пометками замечаний рецензента (src/score_review.py).

Как работает:
  1. MusicXML (или MIDI, тогда сначала переводится в MusicXML через music21) читается библиотекой verovio,
     которая рисует ноты в SVG (как страницы партитуры).
  2. Из внутреннего представления verovio (MEI) берём, какая нота в каком такте и у какого инструмента.
  3. Для выбранного замечания ноты в его клетках «инструмент × такт» красятся красным (стилем CSS).
Ничего не исправляет и не меняет звук: только показывает.
"""
import os, re, tempfile
import xml.etree.ElementTree as ET

RED = "#c0392b"
MEI_NS = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MARKABLE = {"note", "rest", "mRest", "chord"}
OPTIONS = {"pageWidth": 2400, "pageHeight": 3000, "scale": 30, "adjustPageHeight": True,
           "header": "none", "footer": "none", "pageMarginLeft": 40, "pageMarginRight": 40,
           "pageMarginTop": 40, "pageMarginBottom": 40, "svgViewBox": True}


IMPORT_ERROR = None


def available():
    global IMPORT_ERROR
    try:
        import verovio  # noqa: F401
        return True
    except Exception as e:
        IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)
        return False


def build(review, musicxml_path=None, midi_path=None):
    """Строит ноты для рецензии и кладёт их в review["notation"]. Ошибку НЕ прячет: пишет её в review["notation_error"],
    чтобы приложение показало, почему нот нет (2026-11-06: в облаке ноты пропали молча, причину не было видно)."""
    import traceback
    if not review:
        return
    if not available():
        review["notation_error"] = "не загружается библиотека verovio (%s)" % IMPORT_ERROR
        return
    errs = []
    for kw in ({"musicxml_path": musicxml_path, "midi_path": midi_path}, {"midi_path": midi_path}):
        if kw.get("musicxml_path") is None and "musicxml_path" in kw: continue
        try:
            review["notation"] = prepare(**kw)
            review.pop("notation_error", None)
            return
        except Exception:
            errs.append(traceback.format_exc(limit=3))
    review["notation_error"] = "\n---\n".join(errs)


def build_hands(res):
    """Ноты рояля с пометками для результата piano_review.review: два стана (правая и левая рука), как в переложении.
    Руки берутся из res["hand_notes"] (те же, что проверяет рецензент), поэтому красные ноты совпадают с картой.
    Ошибку не прячет: пишет её в res["notation_error"]."""
    import traceback
    if not res or not res.get("hand_notes"):
        return
    if not available():
        res["notation_error"] = "не загружается библиотека verovio (%s)" % IMPORT_ERROR
        return
    try:
        path = _hands_midi(res)
        res["notation"] = prepare(midi_path=path, staff_names=[RH, LH])
        res.pop("notation_error", None)
    except Exception:
        res["notation_error"] = traceback.format_exc(limit=3)


def _hands_midi(res):
    """Временный MIDI с двумя дорожками (правая, левая) по hand_notes; такт и темп берутся из проверки."""
    import mido
    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    meta = mido.MidiTrack()
    mid.tracks.append(meta)
    meta.append(mido.MetaMessage("time_signature", numerator=max(1, round(res.get("bpb", 4.0))), denominator=4,
                                 clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(res.get("bpm") or 120), time=0))
    for hand, latin in ((RH, "Right hand"), (LH, "Left hand")):   # имена станов задаются по порядку; в MIDI только латиница
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=latin, time=0))
        ev = []
        for start, dur, pitch, h in res["hand_notes"]:
            if h != hand:
                continue
            on, off = round(start * tpb), round((start + dur) * tpb)
            ev.append((on, 1, pitch))
            ev.append((max(off, on + 1), 0, pitch))
        last = 0
        for tick, kind, pitch in sorted(ev):          # отпускание раньше нажатия на том же тике
            if kind == 1:
                tr.append(mido.Message("note_on", note=pitch, velocity=80, time=tick - last, channel=0))
            else:
                tr.append(mido.Message("note_off", note=pitch, velocity=0, time=tick - last, channel=0))
            last = tick
    out = os.path.join(tempfile.mkdtemp(prefix="hands_"), "piano_hands.mid")
    mid.save(out)
    return out


def _midi_to_musicxml(midi_path):
    import music21, shutil
    # копия под коротким латинским именем: music21 и verovio на сервере могут не справиться с русским путём
    tmp_in = os.path.join(tempfile.mkdtemp(prefix="midi_"), "input.mid")
    shutil.copyfile(midi_path, tmp_in)
    import m21_fix
    sc = m21_fix.parse_midi(tmp_in)
    out = os.path.join(tempfile.mkdtemp(prefix="notation_"), "score.musicxml")
    import xml_safe
    xml_safe.write_musicxml(sc, out)
    return out


RH, LH = "Правая рука", "Левая рука"


def prepare(musicxml_path=None, midi_path=None, staff_names=None):
    """Возвращает {"pages": [svg, ...], "cells": {(инструмент, такт): [id, ...]}, "page_of": {id: номер_страницы}}.
    staff_names: если заданы, имена станов берутся по порядку (для рояля: правая рука, левая рука)."""
    import verovio
    import score_review
    import score_player
    if not (musicxml_path and os.path.exists(musicxml_path)):
        musicxml_path = _midi_to_musicxml(midi_path)
    tk = score_player.make_toolkit()
    tk.setOptions(OPTIONS)
    # Файл читаем сами и отдаём verovio текстом (loadData): так не зависим от того, как библиотека
    # открывает путь на сервере. Если и так не вышло, в ошибке будет причина из самой библиотеки.
    with open(musicxml_path, "rb") as fh:
        raw = fh.read()
    # Несколько попыток: как есть; без метки BOM и строки DOCTYPE (в облаке verovio молча отказывал на файлах
    # music21, где DOCTYPE ссылается на внешнюю схему); потом без комментариев и лишних пробелов.
    import re
    import score_player
    text = raw.decode("utf-8", errors="replace")
    clean = score_player.decode_xml(raw)
    slim = re.sub(r"<!--.*?-->", "", clean, flags=re.S)
    tried, seen, loaded, why = [], [], False, ""
    for label, variant in (("как есть", text), ("без DOCTYPE и BOM", clean), ("без комментариев", slim)):
        if variant in seen:
            continue
        seen.append(variant)
        tk = score_player.make_toolkit()
        tk.setOptions(OPTIONS)
        ok, why = score_player.load_verovio(tk, variant)
        if ok:
            loaded = True
            break
        tried.append((label, None))
    if not loaded:
        log = why or (tk.getLog() or "").strip()[-600:]
        raise ValueError("verovio не смог прочитать MusicXML (размер %d байт; версия verovio %s; пробовал: %s; причина из verovio: %s)"
                         % (len(raw), tk.getVersion(), ", ".join(l for l, _ in tried), log or "не указана"))
    root = ET.fromstring(tk.getMEI())
    # номер нотного стана -> название инструмента, как в рецензии ("Скрипка I" и т. д.)
    staff_name, violins = {}, 0
    if staff_names:
        for k, sd in enumerate(root.iter(MEI_NS + "staffDef")):
            staff_name[sd.get("n")] = staff_names[k] if k < len(staff_names) else None
    for sd in ([] if staff_names else root.iter(MEI_NS + "staffDef")):
        lab = sd.find(MEI_NS + "label")
        name = score_review._label_from_pair(lab.text if lab is not None and lab.text else "")
        if name and name.startswith("Скрипка"):
            violins += 1
            if lab is not None and "II" not in (lab.text or "") and " I" not in (lab.text or ""):
                name = "Скрипка I" if violins == 1 else "Скрипка II"
        staff_name[sd.get("n")] = name
    cells = {}
    for bar_i, m in enumerate(root.iter(MEI_NS + "measure"), 1):
        try:
            bar = int(re.sub(r"\D", "", m.get("n") or "") or bar_i)
        except ValueError:
            bar = bar_i
        for stf in m.iter(MEI_NS + "staff"):
            name = staff_name.get(stf.get("n"))
            if not name: continue
            ids = [el.get(XML_ID) for el in stf.iter() if el.tag[len(MEI_NS):] in MARKABLE and el.get(XML_ID)]
            cells.setdefault((name, bar), []).extend(ids)
    pages = [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]
    page_of = {}
    for i, svg in enumerate(pages, 1):
        for el_id in re.findall(r'<g id="([^"]+)" class="(?:note|rest|mRest|chord)', svg):
            page_of.setdefault(el_id, i)
    return {"pages": pages, "cells": cells, "page_of": page_of}


def ids_for(res, prep, only=None):
    """id нот, которые надо покрасить: для одного замечания (only, с 0) или для всех."""
    out = set()
    instruments = {k[0] for k in prep["cells"]}
    for i, marks in enumerate(res.get("marks", [])):
        if only is not None and i != only: continue
        for who, bar in marks:
            for nm in (instruments if who == "*" else [who]):
                out.update(prep["cells"].get((nm, bar), []))
    return out


def style_for(ids):
    if not ids: return ""
    sel = ",".join("#" + i for i in sorted(ids))
    return f"<style>{sel}{{fill:{RED};stroke:{RED};color:{RED}}}</style>"


def pages_with(prep, ids):
    return sorted({prep["page_of"][i] for i in ids if i in prep["page_of"]})


def colored_pages(prep, ids, max_pages=6):
    """SVG страниц, где есть покрашенные ноты (не больше max_pages), с красным стилем внутри."""
    pg = pages_with(prep, ids) or [1]
    st = style_for(ids)
    out = []
    for p in pg[:max_pages]:
        svg = prep["pages"][p - 1]
        out.append((p, re.sub(r"(<svg[^>]*>)", r"\1" + st.replace("\\", "\\\\"), svg, count=1)))
    return out, len(pg)


def standalone_html(res, prep, title="Партитура с пометками"):
    """Одна страница: все страницы партитуры и список замечаний; нажатие на замечание красит его ноты."""
    import html as _h, json
    styles = [style_for(ids_for(res, prep, i)) for i in range(len(res["findings"]))]
    first_pages = [(pages_with(prep, ids_for(res, prep, i)) or [1])[0] for i in range(len(res["findings"]))]
    items = "".join(
        f"<li id='li{i}' onclick='sh({i})'><b>[{_h.escape(c)}]</b> {_h.escape(t)}<br><small>Статус правила: {_h.escape(st)}</small></li>"
        for i, (_, c, st, t) in enumerate(res["findings"])) or "<li>Замечаний нет.</li>"
    pages = "".join(f"<div class='pg' id='pg{k}'><div class='pn'>Страница {k}</div>{svg}</div>"
                    for k, svg in enumerate(prep["pages"], 1))
    js = ("<script>const S=" + json.dumps(styles) + ",P=" + json.dumps(first_pages) + ";"
          "function sh(i){document.getElementById('hl').innerHTML=S[i].replace(/<\\/?style>/g,'');"
          "document.querySelectorAll('li').forEach(e=>e.classList.remove('on'));document.getElementById('li'+i).classList.add('on');"
          "document.getElementById('pg'+P[i]).scrollIntoView({behavior:'smooth'});}</script>")
    css = ("<style>body{background:#fbf7ee;margin:0;font:14px sans-serif;color:#3b2a1a}"
           ".side{position:sticky;top:0;background:#f7f0e1;border-bottom:1px solid #d8ccb4;padding:8px 16px;max-height:38vh;overflow:auto;z-index:2}"
           ".side li{cursor:pointer;padding:3px 6px;border-radius:4px;margin:2px 0}.side li.on{background:#efe2c4}"
           ".pg{background:#fff;margin:16px;border:1px solid #d8ccb4;border-radius:6px;padding:8px}.pg svg{width:100%;height:auto}"
           ".pn{font-size:12px;color:#8a7a60}</style><style id='hl'></style>")
    return ("<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_h.escape(title)}</title>{css}</head><body><div class='side'><b>{_h.escape(title)}.</b> "
            "Нажмите на замечание: его ноты станут красными, страница прокрутится к первому месту. "
            "Модуль считает, а не слушает: звучание оценивает слушатель.<ol>" + items + "</ol></div>" + pages + js + "</body></html>")
