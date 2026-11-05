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


def available():
    try:
        import verovio  # noqa: F401
        return True
    except Exception:
        return False


def _midi_to_musicxml(midi_path):
    import music21
    sc = music21.converter.parse(midi_path)
    out = os.path.join(tempfile.mkdtemp(prefix="notation_"), "score.musicxml")
    sc.write("musicxml", fp=out)
    return out


def prepare(musicxml_path=None, midi_path=None):
    """Возвращает {"pages": [svg, ...], "cells": {(инструмент, такт): [id, ...]}, "page_of": {id: номер_страницы}}."""
    import verovio
    import score_review
    if not (musicxml_path and os.path.exists(musicxml_path)):
        musicxml_path = _midi_to_musicxml(midi_path)
    tk = verovio.toolkit()
    tk.setOptions(OPTIONS)
    if not tk.loadFile(musicxml_path):
        raise ValueError("verovio не смог прочитать MusicXML")
    root = ET.fromstring(tk.getMEI())
    # номер нотного стана -> название инструмента, как в рецензии ("Скрипка I" и т. д.)
    staff_name, violins = {}, 0
    for sd in root.iter(MEI_NS + "staffDef"):
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
