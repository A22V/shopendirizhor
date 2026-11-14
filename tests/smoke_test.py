"""Smoke test: python tests/smoke_test.py   (takes about a minute)"""
import sys, os, json, traceback
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import orchestrator

CASES = [("test_piano_input.mid", 1), ("k545_piano_excerpt.mid", 2), ("nocturneincsharpminor.mid", 3)]
outdir = os.path.join(ROOT, "out", "smoke"); os.makedirs(outdir, exist_ok=True)
failed = 0
for name, min_phrases in CASES:
    src = os.path.join(ROOT, "input", name)
    stem = os.path.join(outdir, os.path.splitext(name)[0])
    try:
        log, issues, names = orchestrator.run(src, stem, "off", None)
        errors = [i for i in issues if i[0] == "error"]
        plan = json.load(open(stem + "_plan.json", encoding="utf-8"))
        files = all(os.path.exists(stem + ext) for ext in (".mid", ".musicxml", "_plan.json", "_report.json"))
        warns = sorted({i[1] for i in issues if i[0] == "warning"})
        good = (not errors) and files and len(plan["phrases"]) >= min_phrases
        print("%-30s %s  фраз=%d  ошибок=%d  предупреждения=%s" % (name, "OK " if good else "FAIL", len(plan["phrases"]), len(errors), warns or "нет"))
        failed += 0 if good else 1
    except Exception:
        print(name, "FAIL (исключение)"); traceback.print_exc(); failed += 1
# редукция: обычный путь и путь с выбором голосов моделью (раньше второй не проверялся)
try:
    import reduction
    src = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    a = reduction.reduce_to_piano(src, os.path.join(outdir, "red_plain.mid"))
    text, n = reduction.describe_for_reduction(src)
    plan, _ = reduction.validate_keep_plan({"blocks": [{"block": 1, "rh_max": 3, "lh_max": 2, "keep": "outer"}]}, n)
    b = reduction.reduce_with_keep_plan(src, os.path.join(outdir, "red_plan.mid"), plan)
    ok = a["notes_in"] > 0 and b["notes_in"] > 0
    print("%-30s %s  нот: %d -> %d / %d" % ("редукция", "OK " if ok else "FAIL", a["notes_in"], a["notes_rh"] + a["notes_lh"], b["notes_rh"] + b["notes_lh"]))
    failed += 0 if ok else 1
except Exception:
    print("редукция FAIL (исключение)"); traceback.print_exc(); failed += 1
# проверка переложения (piano_review): наше переложение с оригиналом + искусственный аккорд с растяжкой и 6 нотами в руке
try:
    import piano_review, mido
    pr = piano_review.review(os.path.join(outdir, "red_plain.mid"), src)
    m = mido.MidiFile(ticks_per_beat=480)
    for chord in ([72, 76, 79, 88], [40, 43, 47, 50, 53, 55]):          # правая: растяжка 16; левая: 6 нот
        t = mido.MidiTrack(); m.tracks.append(t)
        for p in chord: t.append(mido.Message("note_on", note=p, velocity=80, time=0))
        for i, p in enumerate(chord): t.append(mido.Message("note_off", note=p, velocity=0, time=480 if i == 0 else 0))
    m.save(os.path.join(outdir, "piano_bad.mid"))
    bad = piano_review.review(os.path.join(outdir, "piano_bad.mid"))
    codes = {f[1] for f in bad["findings"]}
    ok = pr["stats"]["нот"] > 0 and pr["stats"]["гармония"] and codes >= {"P1", "P2"} and len(pr["marks"]) == len(pr["findings"])
    print("%-30s %s  замечаний=%d  гармония=%.2f" % ("проверка переложения", "OK " if ok else "FAIL", len(pr["findings"]),
                                                     (pr["stats"]["гармония"] or {}).get("среднее", 0)))
    failed += 0 if ok else 1
except Exception:
    print("проверка переложения FAIL (исключение)"); traceback.print_exc(); failed += 1
# ноты с пометками для переложения рояля (score_notation.build_hands): две руки, красные ноты совпадают с картой
try:
    import score_notation
    if score_notation.available():
        pr2 = piano_review.review(os.path.join(outdir, "red_plain.mid"), src)
        score_notation.build_hands(pr2)
        prep2 = pr2.get("notation")
        if prep2 is None:
            print("ноты переложения FAIL:", pr2.get("notation_error", "")[-500:]); failed += 1
        else:
            names = {k[0] for k in prep2["cells"]}
            marked = score_notation.ids_for(pr2, prep2)
            ok = len(prep2["pages"]) > 0 and names >= {"Правая рука", "Левая рука"} and all(i in prep2["page_of"] for i in marked)
            print("%-30s %s  страниц=%d  красных нот=%d" % ("ноты переложения", "OK " if ok else "FAIL", len(prep2["pages"]), len(marked)))
            failed += 0 if ok else 1
    else:
        print("%-30s пропущено (verovio не установлен)" % "ноты переложения")
except Exception:
    print("ноты переложения FAIL (исключение)"); traceback.print_exc(); failed += 1
# рецензент партитуры: отчёт строится на результате оркестровки K.545 из этого же теста
try:
    import score_review
    stem = os.path.join(outdir, "k545_piano_excerpt")
    res = score_review.review(stem + ".mid", stem + ".musicxml")
    text = score_review.report_text(res, "k545")
    page = score_review.map_html(res, standalone=True)
    ok = (res["stats"]["тактов"] > 0 and "Рецензия" in text and all(f[2] for f in res["findings"])
          and len(res["marks"]) == len(res["findings"]) and "<table" in page and page.count("class='mv'") == len(res["findings"]) + 1)
    print("%-30s %s  тактов=%d  замечаний=%d" % ("рецензент партитуры", "OK " if ok else "FAIL", res["stats"]["тактов"], len(res["findings"])))
    failed += 0 if ok else 1
except Exception:
    print("рецензент партитуры FAIL (исключение)"); traceback.print_exc(); failed += 1
# автоисправление быстрых нот (score_fix): готовый MIDI исправляется, после исправления K2 нет
try:
    import score_fix
    fixed = os.path.join(outdir, "k545_fixed.mid")
    ch = score_fix.fix_midi(stem + ".mid", fixed)
    r2 = score_review.review(fixed)
    unit, _ = score_fix.simplify_fast([[0, 0.25, 40], [0.25, 0.25, 43], [0.5, 0.5, 45], [1, 1, 40], [2, 0.25, 38], [2.25, 0.25, 41]])
    ok = unit == [[0, 0.5, 40], [0.5, 0.5, 45], [1, 1, 40], [2, 1.0, 38]]
    if not ok: print("   simplify_fast:", unit)
    ok = ok and os.path.exists(fixed) and not any(f[1] == "K2" for f in r2["findings"]) and r2["stats"]["тактов"] == res["stats"]["тактов"]
    print("%-30s %s  изменений=%d" % ("автоисправление F2", "OK " if ok else "FAIL", len(ch)))
    failed += 0 if ok else 1
except Exception:
    print("автоисправление F2 FAIL (исключение)"); traceback.print_exc(); failed += 1
# забытые духовые (texture_fix.fill_winds, ORCH_WINDS): добавляются только отсутствующие, только в громкие фразы,
# новых нот не придумывается; план, где все духовые есть, не меняется
try:
    import texture_fix
    ph = lambda bars, lvl, **r: dict({"bars": bars, "level": lvl, "climax": False, "melody": [["Violin I", 0]],
                                      "inner1": [["Violin II", 0]], "inner2": [["Viola", 0]], "bass": [["Cello", 0]], "figuration": []}, **r)
    p = {"phrases": [ph([1, 4], "mp"), ph([5, 8], "f", melody=[["Flute", 0]], inner1=[["Oboe", 0]])]}
    newp, ch = texture_fix.fill_winds(p)
    quiet, loud = newp["phrases"]
    ok = (quiet == p["phrases"][0] and ["Horn", 0, None, None] in loud["inner2"] and ["Bassoon", 0, None, None] in loud["bass"]
          and ["Clarinet", 0, None, None] not in loud["inner1"] and len(ch) == 2)   # кларнет — пятый духовой: предел 4
    full = {"phrases": [ph([1, 4], "f", inner1=[["Oboe", 0], ["Clarinet", 0]], inner2=[["Horn", 0]], bass=[["Bassoon", 0]], melody=[["Flute", 0]])]}
    ok = ok and texture_fix.fill_winds(full) == (full, [])
    print("%-30s %s  изменений=%d" % ("забытые духовые", "OK " if ok else "FAIL", len(ch)))
    failed += 0 if ok else 1
except Exception:
    print("забытые духовые FAIL (исключение)"); traceback.print_exc(); failed += 1
# бегущее сопровождение, которое никто не играет (texture_fix.fill_figuration, ORCH_FIGURE):
# быстрое — свободному струнному; медленное («умпа-па» четвертями) и фразы с фигурацией не трогаются
try:
    import texture_fix
    bars4 = [(0.0, 4.0), (4.0, 4.0)]
    fast = [{"offset": i * 0.25, "dur": 0.25, "pitch": 52} for i in range(32)]
    slow = [{"offset": float(i), "dur": 1.0, "pitch": 52} for i in range(8)]
    base = {"phrases": [{"bars": [1, 2], "level": "mp", "melody": [["Violin I", 0]], "inner1": [["Violin II", 0]],
                         "inner2": [], "bass": [["Cello", 0]], "figuration": []}]}
    p1, c1 = texture_fix.fill_figuration(base, fast, bars4)
    p2, c2 = texture_fix.fill_figuration(base, slow, bars4)
    with_fig = {"phrases": [dict(base["phrases"][0], figuration=[["Viola", 0]])]}
    p3, c3 = texture_fix.fill_figuration(with_fig, fast, bars4)
    ok = (p1["phrases"][0]["figuration"] == [["Viola", 0, None, None]] and len(c1) == 1
          and (p2, c2) == (base, []) and (p3, c3) == (with_fig, []))
    print("%-30s %s  изменений=%d" % ("бегущее сопровождение", "OK " if ok else "FAIL", len(c1)))
    failed += 0 if ok else 1
except Exception:
    print("бегущее сопровождение FAIL (исключение)"); traceback.print_exc(); failed += 1
# контроль брака (quality_gate): своя оркестровка без фальши; та же партия на полтона выше -> брак Б1;
# сдвиг из плана модели (1 = октава) никогда не даёт полутон (ошибка 2026-11-07)
try:
    import quality_gate, mido as _mido
    _src = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    g1 = quality_gate.check(_src, stem + ".mid")
    _m = _mido.MidiFile(stem + ".mid")
    _tr = next(t for t in _m.tracks if any(x.type == "note_on" for x in t))
    for x in _tr:
        if x.type in ("note_on", "note_off"):
            x.note = min(127, x.note + 1)
    _bad = os.path.join(outdir, "k545_semitone.mid"); _m.save(_bad)
    g2 = quality_gate.check(_src, _bad)
    ok = (g1["stats"]["foreign"]["bad"] == 0 and any(c == "Б1" for c, _, _ in g2["defects"])
          and [orchestrator.semitones(x) for x in (0, 1, 2, -1, 12, -12, 24, 7)] == [0, 12, 24, -12, 12, -12, 24, 12])
    print("%-30s %s  чужих нот: своя %d, испорченная %d" % ("контроль брака", "OK " if ok else "FAIL",
          g1["stats"]["foreign"]["bad"], g2["stats"]["foreign"]["bad"]))
    failed += 0 if ok else 1
except Exception:
    print("контроль брака FAIL (исключение)"); traceback.print_exc(); failed += 1
# солист и «Болеро» (texture_fix.apply_solo / solo_accompaniment): без фальши, у одного солиста мелодия не скачет,
# у рояля переносится педаль оригинала
try:
    import quality_gate, mido as _mido
    _src = os.path.join(ROOT, "input", "nocturneincsharpminor.mid")
    _res = {}
    for _solo in ("Flute", "Bolero", "Piano"):
        _st = os.path.join(outdir, "solo_" + _solo)
        orchestrator.run(_src, _st, solo=_solo)
        _g = quality_gate.check(_src, _st + ".mid", solo=True)
        _res[_solo] = (_g["stats"]["foreign"]["bad"], _g["stats"]["melody_hops"],
                       sum(1 for t in _mido.MidiFile(_st + ".mid").tracks for x in t if x.type == "control_change" and x.control == 64))
    _ped_src = sum(1 for t in _mido.MidiFile(_src).tracks for x in t if x.type == "control_change" and x.control == 64)
    ok = (all(v[0] == 0 for v in _res.values()) and _res["Flute"][1] == 0 and _res["Piano"][2] == _ped_src)
    print("%-30s %s  %s" % ("солист и «Болеро»", "OK " if ok else "FAIL", _res))
    failed += 0 if ok else 1
except Exception:
    print("солист и «Болеро» FAIL (исключение)"); traceback.print_exc(); failed += 1
# лёгкие ударные (percussion.py): отдельная дорожка на 10-м канале, ноты оркестра те же, контроль брака их не считает
try:
    import quality_gate, mido as _mido
    _src = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    _a, _b = os.path.join(outdir, "perc_off"), os.path.join(outdir, "perc_on")
    orchestrator.run(_src, _a); _lg, _, _ = orchestrator.run(_src, _b, percussion=True)
    _na = [(t.name, [(x.note, x.time) for x in t if x.type == "note_on"]) for t in _mido.MidiFile(_a + ".mid").tracks]
    _mb = _mido.MidiFile(_b + ".mid")
    _nb = [(t.name, [(x.note, x.time) for x in t if x.type == "note_on"]) for t in _mb.tracks if t.name != "Percussion"]
    _pt = [t for t in _mb.tracks if t.name == "Percussion"]
    ok = (_na == _nb and len(_pt) == 1 and _lg.get("percussion", 0) > 0
          and all(x.channel == 9 for x in _pt[0] if x.type == "note_on")
          and quality_gate.check(_src, _b + ".mid")["stats"]["foreign"]["bad"] == 0)
    print("%-30s %s  ударов=%s" % ("лёгкие ударные", "OK " if ok else "FAIL", _lg.get("percussion")))
    failed += 0 if ok else 1
except Exception:
    print("лёгкие ударные FAIL (исключение)"); traceback.print_exc(); failed += 1
# своя кнопка выбора файла (web/picker.py + web/file_picker/index.html): файл по веб-сокету, а не каналом загрузки
try:
    _ph = open(os.path.join(ROOT, "web", "file_picker", "index.html"), encoding="utf-8").read()
    ok = all(k in _ph for k in ("streamlit:componentReady", "streamlit:setComponentValue", "streamlit:setFrameHeight",
                                 'type="file"', "btoa"))
    ok = ok and 'accept=' not in _ph                       # без фильтра: на Android фильтр делает файлы серыми
    _pp = open(os.path.join(ROOT, "web", "picker.py"), encoding="utf-8").read()
    ok = ok and "declare_component" in _pp and "b64decode" in _pp
    _app = open(os.path.join(ROOT, "web", "app.py"), encoding="utf-8").read()
    _pl = open(os.path.join(ROOT, "web", "pages", "1_Проигрыватель.py"), encoding="utf-8").read()
    ok = ok and "picker.pick" in _app and "picker.pick" in _pl
    ok = ok and "ack" in _ph and "CHUNK" in _ph and "WAIT_MS" in _ph         # части, подтверждение, повтор
    ok = ok and "picker.diagnostics()" in _app and "picker.diagnostics()" in _pl
    print("%-30s %s" % ("своя кнопка выбора файла", "OK " if ok else "FAIL"))
    failed += 0 if ok else 1
except Exception:
    print("своя кнопка выбора файла FAIL (исключение)"); traceback.print_exc(); failed += 1
# фоновые задания (web/jobs.py): работа идёт без страницы, повторный запуск того же задания не считается заново
try:
    sys.path.insert(0, os.path.join(ROOT, "web"))
    import jobs, time as _time
    _k = jobs.key(b"smoke", {"t": _time.time()})
    _calls = []
    def _fn(p, w):
        p.go("plan"); _calls.append(w); return {"ok": 42}
    jobs.start(_k, _fn, [("plan", "план")], 10.0)
    for _ in range(50):
        if (jobs.status(_k) or {}).get("state") == "done": break
        _time.sleep(0.1)
    _again = jobs.start(_k, _fn, [("plan", "план")], 10.0)
    ok = jobs.load(_k) == {"ok": 42} and not _again and len(_calls) == 1
    print("%-30s %s" % ("фоновые задания", "OK " if ok else "FAIL"))
    failed += 0 if ok else 1
except Exception:
    print("фоновые задания FAIL (исключение)"); traceback.print_exc(); failed += 1
# исправление «пустого низа» (score_fix.fix_low, K4): тактов без нот ниже C3 становится меньше, чужих нот нет
try:
    import score_fix, quality_gate
    _src = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    _o = os.path.join(outdir, "low_src"); orchestrator.run(_src, _o)
    _cnt = lambda f: sum(len(x[3].split(",")) for x in score_review.review(f)["findings"] if x[1] == "K4")
    _ch = score_fix.fix_low(_o + ".mid", _o + "_fixlow.mid")
    ok = (quality_gate.check(_src, _o + "_fixlow.mid")["stats"]["foreign"]["bad"] == 0
          and (not _ch or _cnt(_o + "_fixlow.mid") <= _cnt(_o + ".mid")))
    print("%-30s %s  %s" % ("исправление низа (K4)", "OK " if ok else "FAIL", _ch[:1]))
    failed += 0 if ok else 1
except Exception:
    print("исправление низа (K4) FAIL (исключение)"); traceback.print_exc(); failed += 1
# ноты с пометками (нужен verovio; без него проверка пропускается)
try:
    import score_notation
    if score_notation.available():
        prep = score_notation.prepare(stem + ".musicxml", stem + ".mid")
        marked = score_notation.ids_for(res, prep)
        ok = len(prep["pages"]) > 0 and all(i in prep["page_of"] for i in marked) and "<svg" in score_notation.standalone_html(res, prep)
        print("%-30s %s  страниц=%d  красных нот=%d" % ("ноты с пометками", "OK " if ok else "FAIL", len(prep["pages"]), len(marked)))
        failed += 0 if ok else 1
    else:
        print("%-30s пропущено (verovio не установлен)" % "ноты с пометками")
except Exception:
    print("ноты с пометками FAIL (исключение)"); traceback.print_exc(); failed += 1
# ремонт MIDI на входе: трудные файлы с сайтов и из мессенджеров открываются, ноты не меняются
try:
    import io as _io, struct as _struct, zipfile as _zip, mido as _md, midi_repair
    _g = open(os.path.join(ROOT, "input", "test_piano_input.mid"), "rb").read()
    _bz = _io.BytesIO(); _z = _zip.ZipFile(_bz, "w"); _z.writestr("p.mid", _g); _z.close()
    _d = bytearray(_g); _k = _d.find(b"MTrk", 14); _d[_k + 4:_k + 8] = _struct.pack(">I", 10 ** 6)
    _cases = {"обычный": _g, "обрезан": _g[: int(len(_g) * 0.8)], "длина дорожки": bytes(_d), "zip": _bz.getvalue(),
              "RIFF": b"RIFF" + b"\0" * 4 + b"RMIDdata" + b"\0" * 4 + _g, "мусор спереди": b"\0" * 128 + _g}
    for _n, _b in _cases.items():
        _c, _fx = midi_repair.repair(_b, _n)
        _md.MidiFile(file=_io.BytesIO(_c))
    _notes = lambda m: sorted((sum(x.time for x in tr[:i + 1]), x.note) for tr in m.tracks for i, x in enumerate(tr)
                              if x.type == "note_on" and x.velocity)
    _ok = _notes(_md.MidiFile(file=_io.BytesIO(midi_repair.repair(_g)[0]))) == _notes(_md.MidiFile(file=_io.BytesIO(_g)))
    for _bad in (b"ID3" + b"\0" * 100, b"<?xml version='1.0'?><score-partwise/>"):
        try:
            midi_repair.repair(_bad); _ok = False
        except midi_repair.MidiRepairError:
            pass
    # MusicXML на входе: переводится в MIDI (оркестровка, проверки); форшлаги не «зависают»
    import music21 as _m21
    _x = os.path.join(outdir, "smoke_input.musicxml")
    _m21.converter.parse(os.path.join(ROOT, "input", "test_piano_input.mid")).write("musicxml", fp=_x)
    _cx, _fxx = midi_repair.repair(open(_x, "rb").read(), "p.musicxml")
    _ok = _ok and _fxx and _fxx[0].startswith("MusicXML") and not any("незакрыт" in f for f in _fxx)
    print("%-30s %s  случаев=%d + MusicXML" % ("ремонт MIDI", "OK " if _ok else "FAIL", len(_cases)))
    failed += 0 if _ok else 1
except Exception:
    print("ремонт MIDI FAIL (исключение)"); traceback.print_exc(); failed += 1
# партитурный проигрыватель: распознавание инструментов, порядок станов, ноты, карта времени, страница
try:
    import score_player
    sys.path.insert(0, os.path.join(ROOT, "web"))
    import player_html
    names = {n: score_player.identify(n)[1] for n in ("Violin I", "Violoncello", "Contrabass", "Horn in F", "Fl.")}
    ok = names == {"Violin I": "Скрипка", "Violoncello": "Виолончель", "Contrabass": "Контрабас",
                   "Horn in F": "Валторна", "Fl.": "Флейта"} and score_player.identify("", 71)[1] == "Кларнет"
    _src = os.path.join(outdir, "k545_piano_excerpt.mid")      # оркестровка из первого блока теста
    _pp = score_player.prepare(open(_src, "rb").read(), "t.mid")
    labels = [p["label"] for p in _pp["parts"]]
    _ord = [score_player.identify(p["source"])[2] for p in _pp["parts"]]
    ok = ok and _ord == sorted(_ord) and len(labels) >= 3                       # станы в порядке партитуры
    ok = ok and len(set(c for p in _pp["parts"] for c in p["channels"])) == len(_pp["parts"])    # у каждого свой канал
    ok = ok and _pp["pages"] and len(_pp["timemap"]) > 10 and _pp["tempo"][0][0] == 0
    ok = ok and _pp["meter"] and _pp["meter"][0][0] == 0                      # размер такта для метронома
    # MusicXML с меткой BOM (так сохраняют программы Windows) и в UTF-16 должен открываться
    import music21 as _m21
    _xs = _m21.converter.parse(os.path.join(outdir, "k545_piano_excerpt.mid")).write("musicxml")
    _xb = open(_xs, "rb").read()
    for _v in (b"\xef\xbb\xbf" + _xb, _xb.decode("utf-8").encode("utf-16")):
        ok = ok and bool(score_player.prepare(_v, "bom.musicxml")["pages"])
    _h = player_html.build(_pp)
    ok = ok and "WorkletSynthesizer" not in _h[:2000] and "LIB_B64" not in _h and "/*DATA*/" not in _h
    print("%-30s %s  станов=%d событий=%d страница=%d КБ" % ("партитурный проигрыватель", "OK " if ok else "FAIL",
          len(_pp["parts"]), len(_pp["timemap"]), len(_h) // 1024))
    failed += 0 if ok else 1
except Exception:
    print("партитурный проигрыватель FAIL (исключение)"); traceback.print_exc(); failed += 1
# замер ресурсов сервера (только числа в отчёт, звук не меняет)
try:
    import resources
    _s = resources.snapshot()
    _t = resources.text({"seconds": 1.0, "peak": _s, "soundfont": "MS Basic"})
    ok = (_s["peak_main_mb"] or 0) > 0 and "МБ" in _t
    print("%-30s %s  %s" % ("замер памяти", "OK " if ok else "FAIL", _t))
    failed += 0 if ok else 1
except Exception:
    print("замер памяти FAIL (исключение)"); traceback.print_exc(); failed += 1
# запись нот при крошечной паузе (облако 2026-11-09: «2048th duration»): должна выравнивать, а не падать
try:
    import music21 as _m, xml_safe as _xs, tempfile as _tf, os as _os
    _sc = _m.stream.Score(); _pt = _m.stream.Part(); _pt.insert(0, _m.instrument.Flute())
    _pt.insert(0, _m.note.Note("C5", quarterLength=1/3))
    _pt.insert(1/3 + 1/1536, _m.note.Note("D5", quarterLength=1 - 1/3 - 1/1536))
    _sc.insert(0, _pt)
    _fp = _os.path.join(_tf.mkdtemp(), "t.musicxml")
    _fx = _xs.write_musicxml(_sc, _fp)
    _ok = bool(_fx) and len(list(_m.converter.parse(_fp).recurse().notes)) == 2
except Exception as _e:
    _ok = False; print(_e)
print("%-30s %s" % ("запись нот (крошечная пауза)", "OK " if _ok else "FAIL"))
if not _ok: failed += 1

# строгий режим планировщика (LLM_STRICT): температура 0, правила в инструкции, замечания контроля брака в обратной связи
try:
    import importlib, tempfile as _tf, os as _os, json as _js
    _os.environ["LLM_STRICT"] = "1"
    import llm_planner as _L
    importlib.reload(_L)
    _pl = _os.path.join(_os.path.dirname(__file__), "..", "tests", "pieces", "Waltz_Dmajor_piano_plan_5ce53e16.json")
    _mid = _os.path.join(_os.path.dirname(__file__), "..", "tests", "pieces", "Waltz_Dmajor_piano.mid")
    _ok = _L.TEMPERATURE == 0.0 and _js.loads(_L.build_request("deepseek", "m", "k", "s", "u")[2])["temperature"] == 0.0
    if _ok and _os.path.exists(_pl) and _os.path.exists(_mid):
        _txt, _calls = open(_pl, encoding="utf-8").read(), []
        _L.orchestrate_with_llm(_mid, _os.path.join(_tf.mkdtemp(), "w"), "deepseek", "m", "k",
                                call=lambda p_, m_, k_, s_, u_, **kw: (_calls.append((s_, u_)) or _txt))
        _ok = "STRICT RULES" in _calls[0][0]
    _os.environ.pop("LLM_STRICT", None)
    importlib.reload(_L)
    _ok = _ok and _L.TEMPERATURE == 0.3
except Exception as _e:
    _ok = False; print(_e)
print("%-30s %s" % ("строгий режим планировщика", "OK " if _ok else "FAIL"))
if not _ok: failed += 1

# распознавание арпеджио в «мелодии» (ORCH_TEXTURE): зигзаг по аккорду уходит в сопровождение, гамма и долгие ноты остаются
try:
    import orchestrator as _o
    _arp = [{"offset": i * 0.33, "dur": 0.3, "pitch": p_} for i, p_ in enumerate([37, 44, 49, 53, 56, 61, 65, 61, 56, 53])]
    _scale = [{"offset": 10 + i * 0.5, "dur": 0.45, "pitch": 72 + k} for i, k in enumerate([0, 2, 4, 5, 7, 9, 11, 12])]
    _long = [{"offset": 20 + i * 2.0, "dur": 1.9, "pitch": 80 - i} for i in range(3)]
    _mel = _arp + _scale + _long
    _keep, _extra, _rep = _o.split_arpeggio(_mel, [])
    _ok = len(_extra) == len(_arp) and len(_keep) == len(_scale) + len(_long) and _rep["stretches"] == 1
except Exception as _e:
    _ok = False; print(_e)
print("%-30s %s" % ("распознавание арпеджио", "OK " if _ok else "FAIL"))
if not _ok: failed += 1

# движок 2 «нота в ноту» (ORCH_ENGINE=2): все ноты сопровождения розданы, оркестр играет не меньше 90% нот рояля в их момент
try:
    import tempfile as _tf2, os as _os2, bisect as _bs, mido as _md
    import orchestrator as _o2
    _src = _os2.path.join(_os2.path.dirname(__file__), "..", "input", "nocturneincsharpminor.mid")
    _stem = _os2.path.join(_tf2.mkdtemp(), "e2")
    _os2.environ["ORCH_ENGINE"] = "2"
    try:
        _log2, _, _ = _o2.run(_src, _stem)
    finally:
        _os2.environ.pop("ORCH_ENGINE", None)
    def _ns(path):
        m_ = _md.MidiFile(path); out_ = []
        for tr_ in m_.tracks:
            t_ = 0
            for x_ in tr_:
                t_ += x_.time
                if x_.type == "note_on" and x_.velocity > 0: out_.append((t_ / m_.ticks_per_beat, x_.note % 12))
        return sorted(out_)
    _pn, _on = _ns(_src), _ns(_stem + ".mid")
    _os_ = [x_[0] for x_ in _on]
    _hit = sum(1 for t_, pc_ in _pn if any(q_ == pc_ for _, q_ in _on[_bs.bisect_left(_os_, t_ - 0.13):_bs.bisect_right(_os_, t_ + 0.13)]))
    _e2 = _log2["engine2"]
    _ok = _e2["dropped"] == 0 and _hit / len(_pn) >= 0.9
    _msg = "нот рояля сыграно %d%%, пропущено %d, тянущихся нот %d" % (round(100 * _hit / len(_pn)), _e2["dropped"], _e2["holds"])
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("движок 2 «нота в ноту»", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- громкость оркестра следует за роялем (ORCH_FOLLOW) ---
try:
    import tempfile as _tf3, os as _os3, mido as _md3
    import orchestrator as _o3
    _src = _os3.path.join(_os3.path.dirname(__file__), "..", "input", "nocturneincsharpminor.mid")
    _d3 = _tf3.mkdtemp()
    _pf3 = _os3.environ.pop("ORCH_PERFORM", None)      # слой «исполнитель» тоже пишет CC11: в этой проверке он выключен
    _fw3 = _os3.environ.pop("ORCH_FOLLOW", None)       # 2026-11-14: если переключатель включён снаружи, прогон «без него» должен быть без него
    try:
        _o3.run(_src, _os3.path.join(_d3, "off"))
        _os3.environ["ORCH_FOLLOW"] = "1"
        try:
            _l3, _, _ = _o3.run(_src, _os3.path.join(_d3, "on"))
        finally:
            _os3.environ.pop("ORCH_FOLLOW", None)
    finally:
        if _pf3 is not None: _os3.environ["ORCH_PERFORM"] = _pf3
        if _fw3 is not None: _os3.environ["ORCH_FOLLOW"] = _fw3
    def _cnt(path, ctl):
        n_ = 0
        for tr_ in _md3.MidiFile(path).tracks:
            for x_ in tr_:
                if ctl and x_.type == "control_change" and x_.control == 11: n_ += 1
                if not ctl and x_.type == "note_on" and x_.velocity > 0: n_ += 1
        return n_
    _same_notes = _cnt(_os3.path.join(_d3, "off.mid"), False) == _cnt(_os3.path.join(_d3, "on.mid"), False)
    _cc_off, _cc_on = _cnt(_os3.path.join(_d3, "off.mid"), True), _cnt(_os3.path.join(_d3, "on.mid"), True)
    _fl = _l3.get("loudness_follow", {})
    _ok = _same_notes and _cc_off == 0 and _cc_on > 0 and "error" not in _fl
    _msg = "нот поровну, CC11 без переключателя %d, с ним %d, убавление до %s дБ" % (_cc_off, _cc_on, _fl.get("cut_min_db"))
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("громкость за роялем", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- контроль брака: параллельные квинты, которых нет у фортепиано (П3) ---
try:
    import tempfile as _tf4, os as _os4, mido as _md4
    import quality_gate as _qg4
    _d4 = _tf4.mkdtemp()
    def _mk(path, tracks):
        m_ = _md4.MidiFile(type=1, ticks_per_beat=480)
        for name_, notes_ in tracks:
            tr_ = _md4.MidiTrack(); tr_.append(_md4.MetaMessage("track_name", name=name_)); m_.tracks.append(tr_)
            ev_ = []
            for st_, p_ in notes_:
                ev_ += [(st_ * 480, 1, p_), ((st_ + 1) * 480, 0, p_)]
            t_ = 0
            for tt_, on_, p_ in sorted(ev_):
                tr_.append(_md4.Message("note_on" if on_ else "note_off", note=p_, velocity=80 if on_ else 0, time=tt_ - t_)); t_ = tt_
        m_.save(path)
    _pp, _bad, _good = (_os4.path.join(_d4, x) for x in ("p.mid", "bad.mid", "good.mid"))
    _mk(_pp, [("Piano", [(0, 60), (0, 64), (1, 62), (1, 65)])])                      # до-ми, ре-фа
    _mk(_bad, [("Violin I", [(0, 67), (1, 69)]), ("Viola", [(0, 60), (1, 62)])])      # соль-ля над до-ре: квинты
    _mk(_good, [("Violin I", [(0, 64), (1, 65)]), ("Viola", [(0, 60), (1, 62)])])     # ми-фа над до-ре: терции
    _rb = _qg4.check(_pp, _bad, melody=[]); _rg = _qg4.check(_pp, _good, melody=[])
    _ok = _rb["stats"]["parallel_fifths"]["not_in_piano"] == 1 and _rg["stats"]["parallel_fifths"]["not_in_piano"] == 0 \
        and any(w[0] == "П3" for w in _rb["warnings"])
    _msg = "квинты найдены %d / в правильном примере %d" % (_rb["stats"]["parallel_fifths"]["not_in_piano"], _rg["stats"]["parallel_fifths"]["not_in_piano"])
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("параллельные квинты (П3)", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

try:
    import tempfile as _tf, mido as _md, numpy as _np, loudness_follow as _lf
    def _mk5(path, name, notes):
        m = _md.MidiFile(ticks_per_beat=480); t = _md.MidiTrack(); m.tracks.append(t)
        t.append(_md.MetaMessage("set_tempo", tempo=500000)); t.append(_md.MetaMessage("track_name", name=name))
        ev = []
        for a, b, n in notes:
            ev += [(a, "on", n), (b, "off", n)]
        ev.sort(key=lambda x: (x[0], x[1] == "on")); last = 0
        for tk, k, n in ev:
            t.append(_md.Message("note_on" if k == "on" else "note_off", note=n, velocity=80 if k == "on" else 0, time=tk - last, channel=0)); last = tk
        m.save(path)
    _d5 = _tf.mkdtemp(); _b5 = lambda sec: int(sec * 2 * 480)
    _mk5(_d5 + "/p.mid", "Piano", [(_b5(i), _b5(i + 1), 60) for i in range(60)])
    _mk5(_d5 + "/o.mid", "Flute", [(_b5(i), _b5(i + 1), 72) for i in range(60) if not 30 <= i < 32])
    _cut5, _ = _lf.curve(_d5 + "/p.mid", _d5 + "/o.mid")
    _boost5 = float(_cut5.max() - _np.median(_cut5))
    _ok = _boost5 <= 6.0
    _msg = "тихое место выше соседей на %.1f дБ (допустимо до 6)" % _boost5
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("громкость: тихая секунда", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

try:
    import smooth as _sm
    _ln = {"Violin I": [[0.0, 1.0, 60, "melody"], [1.5, 1.0, 62, "melody"], [4.0, 1.0, 64, "melody"]]}
    _st = _sm.legato(_ln)
    _n = _ln["Violin I"]
    _rb = _sm.ramp_base({0: "mp", 1: "mf"}, [0.0, 4.0, 8.0], {"mp": 64, "mf": 80, "f": 96})
    _ok = (abs(_n[0][1] - 1.5) < 1e-9          # разрыв 0,5 дол. закрыт
           and abs(_n[1][1] - 1.0) < 1e-9      # разрыв 1,5 дол. больше предела: не тронут
           and [x[0] for x in _n] == [0.0, 1.5, 4.0]     # начала нот прежние
           and _st["extended_notes"] == 1
           and _rb(0.0, 0) == 64 and _rb(2.0, 0) == 72 and _rb(4.0, 1) == 80)   # плавный переход mp → mf в такте
    _msg = "продлено нот %d; плавный переход 64→72→80" % _st["extended_notes"]
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("плавность (legato, ramp)", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

try:
    import ensemble as _en, quality_gate as _qg5, mido as _md5, tempfile as _tf5
    _src5 = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    _d6 = _tf5.mkdtemp(); _bad5 = []
    for _k in _en.ENSEMBLES:
        _r = _en.arrange(_src5, os.path.join(_d6, _k), _k)
        _g = _qg5.check(_src5, os.path.join(_d6, _k + ".mid"), melody=None)["stats"]["foreign"]
        _m = _md5.MidiFile(os.path.join(_d6, _k + ".mid"))
        _names = [t.name for t in _m.tracks[1:]]
        _want = len(_en.ENSEMBLES[_k]["voices"]) + (1 if _en.ENSEMBLES[_k]["piano"] else 0)
        if _g["bad"] or len(_names) != _want or _r["played_share"] < (0.85 if _k == "duo_violin_cello" else 0.95):
            _bad5.append("%s: чужих %d, дорожек %d из %d, сыграно %.0f%%" % (_k, _g["bad"], len(_names), _want, 100 * _r["played_share"]))
    _ok = not _bad5
    _msg = "составов %d, чужих нот 0, ноты рояля сыграны" % len(_en.ENSEMBLES) if _ok else "; ".join(_bad5)
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("ансамбли (дуэт, трио, квартет)", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- контроль брака на ансамбле: мелодия ансамбля, а не оркестровая (ложный Б3, 2026-11-14) ---
try:
    import tempfile, quality_gate
    import ensemble as _E3
    _src = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    _tmp = tempfile.mkdtemp()
    _E3.arrange(_src, os.path.join(_tmp, "d"), "duo_violin_piano")
    _g = quality_gate.check(_src, os.path.join(_tmp, "d.mid"), melody=_E3.melody_beats(_src))
    _hops = _g["stats"]["melody_hops"]
    _ok = _hops == 0 and not any(d[0] == "Б3" for d in _g["defects"]) and _g["stats"]["foreign"]["bad"] == 0
    _msg = "дуэт скрипка+рояль: пересадок мелодии %d, чужих нот %d" % (_hops, _g["stats"]["foreign"]["bad"])
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("контроль брака на ансамбле", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- ансамбли: связная игра и план модели (кто ведёт мелодию) ---
try:
    import json as _json, tempfile, quality_gate
    import ensemble as _E
    _src = os.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    _tmp = tempfile.mkdtemp()
    _a = _E.arrange(_src, os.path.join(_tmp, "a"), "quartet_string")
    _b = _E.arrange(_src, os.path.join(_tmp, "b"), "quartet_string", legato=True)
    _notes, _meta, _ped, _tpb = _E.read(_src); _mel = _E.melody_ids(_notes, _tpb)
    _bars = _E.bar_table(_meta, max(n["e"] for n in _notes), _tpb)
    _half = max(2, len(_bars) // 2)
    _good = {"phrases": [{"bars": [1, _half], "lead": "Violin", "articulation": "legato", "why": "тема"},
                         {"bars": [_half + 1, len(_bars)], "lead": "Violin II", "articulation": "as_written", "why": "ответ"}]}
    _n = [0]
    def _fake(provider, model, key, system, user):
        _n[0] += 1
        if _n[0] == 1: return '{"phrases":[{"bars":[1,%d],"lead":"Tuba"}]}' % len(_bars)
        return "```json\n" + _json.dumps(_good) + "\n```"
    _plan, _plog = _E.plan_with_model(_src, "quartet_string", "deepseek", "m", "k", call=_fake)
    _c = _E.arrange(_src, os.path.join(_tmp, "c"), "quartet_string", plan=_plan)
    def _boom(*a): raise RuntimeError("HTTP 402")
    _none, _elog = _E.plan_with_model(_src, "quartet_string", "deepseek", "m", "k", call=_boom)
    _t = _E.arrange(_src, os.path.join(_tmp, "t"), "trio_piano", plan={"phrases": [
        {"bars": [1, _half], "lead": "Piano", "articulation": "legato"}, {"bars": [_half + 1, len(_bars)], "lead": "Violin"}]})
    import mido as _mo
    _p = os.path.join(_tmp, "p.mid")                                  # аккорд, взятый вразнобой: 0,05 доли между нотами
    _m = _mo.MidiFile(ticks_per_beat=480); _tr = _mo.MidiTrack(); _m.tracks.append(_tr); _tr.append(_mo.Message("program_change", program=0, time=0))
    _tt = 0
    for _k in range(8):
        for _i, _nt in enumerate((48, 55, 64, 72)):
            _tr.append(_mo.Message("note_on", note=_nt + (_k % 2), velocity=70, time=24 if _i else (0 if _k == 0 and _i == 0 else 360)))
        _tr.append(_mo.Message("note_off", note=48, velocity=0, time=300))
        for _nt in (55, 64, 72): _tr.append(_mo.Message("note_off", note=_nt, velocity=0, time=0))
    _m.save(_p)
    def _overlap(stem):
        _o = _mo.MidiFile(stem + ".mid"); _tk = _o.ticks_per_beat; _best = 0
        for _t0 in _o.tracks:
            if _t0.name != "Violin": continue
            _on = set()
            for _x in _t0:
                if _x.type == "note_on" and _x.velocity > 0: _on.add(_x.note)
                elif _x.type in ("note_on", "note_off"): _on.discard(_x.note)
                _best = max(_best, len(_on))
        return _best
    _E.arrange(_p, os.path.join(_tmp, "m0"), "duo_violin_piano"); _E.arrange(_p, os.path.join(_tmp, "m1"), "duo_violin_piano", mono=True)
    _mono_ok = _overlap(os.path.join(_tmp, "m0")) > 1 and _overlap(os.path.join(_tmp, "m1")) == 1
    _fg = [quality_gate.check(_src, os.path.join(_tmp, x + ".mid"), melody=None)["stats"]["foreign"]["bad"] for x in "bct"]
    _ok = (_plan is not None and _plog["used"] and len(_plog["rounds"]) == 2 and _plog["rounds"][0]["problems"]
           and _none is None and "HTTP 402" in _elog["error"]
           and _b["stat"].get("sing_extended", 0) > 0 and _b["played_share"] == _a["played_share"]
           and "Violin II" in _c["plan"]["lead_share"] and _c["played_share"] >= 0.95
           and _t["plan"]["lead_share"].get("Piano", 0) > 0 and _fg == [0, 0, 0]
           and "План модели" in _E.text(_c) and _mono_ok)
    _msg = "связано %d нот; план принят со 2-й попытки; ведут %s; чужих нот %s; одноголосная мелодия: до %d нот сразу -> 1" % (_b["stat"].get("sing_extended", 0), _c["plan"]["lead_share"], _fg, _overlap(os.path.join(_tmp, "m0")))
except Exception as e:
    _ok, _msg = False, "исключение: %r" % e
print("%-30s %s  %s" % ("ансамбли: legato и план модели", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- слой «исполнитель» (ORCH_PERFORM): ноты те же, меняются сила нажатия и CC11 ---
try:
    import tempfile as _tf9, os as _os9, mido as _md9
    import orchestrator as _o9
    _src = _os9.path.join(ROOT, "input", "k545_piano_excerpt.mid")
    _d9 = _tf9.mkdtemp()
    _keep9 = {k: _os9.environ.pop(k, None) for k in ("ORCH_PERFORM", "ORCH_FOLLOW")}
    try:
        _o9.run(_src, _os9.path.join(_d9, "off"))
        _os9.environ["ORCH_PERFORM"] = "1"
        _l9, _, _ = _o9.run(_src, _os9.path.join(_d9, "on"))
    finally:
        _os9.environ.pop("ORCH_PERFORM", None)
        for k, v in _keep9.items():
            if v is not None: _os9.environ[k] = v
    def _ev9(path):
        nt, vel, cc = [], [], []
        for i_, tr_ in enumerate(_md9.MidiFile(path).tracks):
            t_ = 0
            for x_ in tr_:
                t_ += x_.time
                if x_.type in ("note_on", "note_off"):
                    nt.append((i_, t_, x_.type == "note_on" and x_.velocity > 0, x_.note))
                    if x_.type == "note_on" and x_.velocity > 0: vel.append(x_.velocity)
                elif x_.type == "control_change" and x_.control == 11: cc.append(x_.value)
        return nt, vel, cc
    _n0, _v0, _c0 = _ev9(_os9.path.join(_d9, "off.mid")); _n1, _v1, _c1 = _ev9(_os9.path.join(_d9, "on.mid"))
    _pf = _l9.get("performer", {})
    _ok = (_n0 == _n1 and _v0 != _v1 and not _c0 and len(_c1) > 0 and min(_c1) >= 20 and max(_c1) <= 127
           and "error" not in _pf and _pf.get("phrases", 0) > 0)
    _msg = "ноты и времена те же (%d событий); фраз %s; сила нажатия изменена у %s нот; точек CC11 %d (от %d до %d)" % (
        len(_n0), _pf.get("phrases"), _pf.get("velocity_changed"), len(_c1), min(_c1) if _c1 else 0, max(_c1) if _c1 else 0)
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("слой «исполнитель»", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- «съехавшие такты» (m21_fix, 2026-11-14): music21 ставил такты со сдвигом, ноты оркестра уезжали от рояля ---
# Ритм — тот, на котором ошибка найдена (аккорд через тактовую черту рядом с бегущими нотами); высоты — гамма.
try:
    import mido as _md10, tempfile as _tf10, os as _os10
    import m21_fix as _mf10, orchestrator as _o10
    _R10 = [(0.0, 0.25, 1), (0.0, 0.5, 1), (0.25, 0.25, 1), (0.5, 0.5, 2), (1.0, 0.25, 1), (1.0, 4.25, 1), (1.25, 0.25, 1),
            (1.5, 0.25, 1), (1.75, 0.25, 1), (2.0, 0.25, 1), (2.25, 0.25, 1), (2.5, 0.25, 1), (2.75, 0.25, 1), (3.0, 1.25, 3),
            (4.25, 0.25, 1), (4.5, 0.25, 1), (4.75, 0.25, 1), (5.0, 0.25, 1), (5.25, 0.25, 1), (5.5, 0.25, 1), (5.75, 0.25, 1),
            (6.0, 0.25, 1), (6.25, 0.25, 1), (6.5, 0.25, 1), (6.75, 0.25, 1), (7.0, 1.0, 1), (8.0, 1.0, 1), (9.0, 0.25, 1),
            (9.0, 2.5, 1), (9.25, 0.25, 1), (9.5, 0.25, 1), (9.75, 0.25, 1), (10.0, 0.25, 1), (10.25, 0.25, 1), (10.5, 0.25, 1),
            (10.75, 0.25, 1), (11.0, 1.0, 2), (11.5, 0.5, 1)]
    _ev10 = []
    for _i, (_s, _d, _k) in enumerate(_R10):
        for _j in range(_k):
            _p = 60 + (_i * 2) % 12 + 4 * _j
            _ev10.append((int(round(_s * 480)), 1, _p)); _ev10.append((int(round((_s + _d) * 480)), 0, _p))
    _ev10.sort(key=lambda x: (x[0], x[1]))
    _m10 = _md10.MidiFile(ticks_per_beat=480); _t10 = _md10.MidiTrack(); _m10.tracks.append(_t10); _last = 0
    for _tick, _on, _p in _ev10:
        _t10.append(_md10.Message("note_on" if _on else "note_off", note=_p, velocity=64 if _on else 0, time=_tick - _last)); _last = _tick
    _f10 = _os10.path.join(_tf10.mkdtemp(prefix="drift_"), "drift.mid"); _m10.save(_f10)
    _want = sorted({round(_s, 2) for _s, _d, _k in _R10})
    _s10 = _mf10.parse_midi(_f10)
    _got = sorted({round(float(_n.offset), 2) for _n in _s10.flatten().notes if _n.tie is None or _n.tie.type == "start"})
    _, _, _mel10, _meta10 = _o10.analyze(_f10)
    _ok = _got == _want and max(_x["offset"] for _x in _mel10) <= 11.5 + 1e-6
    _msg = "начала нот совпадают с файлом (%d моментов); переставлено тактов: %d" % (len(_want), getattr(_s10, "regrid_moved", 0))
    if not _ok: _msg = "начала нот НЕ совпадают: ждали до %.2f, получили до %.2f" % (_want[-1], _got[-1] if _got else -1)
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("съехавшие такты", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- тянущийся фон (ORCH_PAD) не создаёт параллельных квинт, которых нет у рояля (2026-11-14) ---
try:
    import os as _os11, tempfile as _tf11
    import orchestrator as _o11, quality_gate as _q11
    _src11 = _os11.path.join(ROOT, "input", "nocturneincsharpminor.mid")
    _set11 = {"ORCH_ENGINE": "2", "ORCH_PAD": "1", "ORCH_ONE_LEAD": "1", "ORCH_MELODY_HELD": "1", "ORCH_FIGURE": "1", "ORCH_BASS": "1"}
    _keep11 = {k: _os11.environ.get(k) for k in _set11}
    try:
        _os11.environ.update(_set11)
        _st11 = _os11.path.join(_tf11.mkdtemp(prefix="pad5_"), "o")
        _l11, _, _ = _o11.run(_src11, _st11)
        _g11 = _q11.check(_src11, _st11 + ".mid")
    finally:
        for k, v in _keep11.items():
            if v is None: _os11.environ.pop(k, None)
            else: _os11.environ[k] = v
    _pf11 = _g11["stats"].get("parallel_fifths", {})
    _ok = _pf11.get("not_in_piano", 1) == 0 and _g11["stats"]["foreign"]["bad"] == 0
    _msg = "квинт всего %s, из них созданных программой %s; чужих нот %s; убрано нот фона %s" % (
        _pf11.get("total"), _pf11.get("not_in_piano"), _g11["stats"]["foreign"]["bad"], (_l11.get("engine2") or {}).get("pad_fifths_removed"))
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("фон без новых квинт", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- «мягкий верх» (ORCH_SOFT_TOP): высокая фраза ведущего играется октавой ниже; без переключателя план прежний ---
try:
    import os as _os12, texture_fix as _tf12
    _bars12 = [(4.0 * _i, 4.0) for _i in range(4)]
    _mel12 = ([{"offset": float(_i), "dur": 1.0, "pitch": 62 + _i} for _i in range(8)] +          # такты 1-2: 62..69, в норме
              [{"offset": 8.0 + _i, "dur": 1.0, "pitch": _p} for _i, _p in enumerate([72, 74, 76, 78, 84, 86, 74, 72])])   # такты 3-4: до 86, высоко
    _plan12 = {"phrases": [{"bars": [1, 2], "level": "mp", "melody": [["Violin I", 0, 0.0]]},
                           {"bars": [3, 4], "level": "mp", "melody": [["Violin I", 0, 0.0]]}]}
    _k12 = _os12.environ.pop("ORCH_SOFT_TOP", None)
    try:
        _p0, _ = _tf12.one_lead(_plan12, _mel12, _bars12)
        _os12.environ["ORCH_SOFT_TOP"] = "1"
        _p1, _n1 = _tf12.one_lead(_plan12, _mel12, _bars12)
    finally:
        _os12.environ.pop("ORCH_SOFT_TOP", None)
        if _k12 is not None: _os12.environ["ORCH_SOFT_TOP"] = _k12
    _s0 = [ph["melody"][0][1] for ph in _p0["phrases"]]; _s1 = [ph["melody"][0][1] for ph in _p1["phrases"]]
    _ok = _s0 == [0, 0] and _s1 == [0, -12] and _p1["phrases"][0]["melody"][0][0] == "Clarinet"
    _msg = "сдвиг фраз без переключателя %s, с ним %s (ведущий %s)" % (_s0, _s1, _p1["phrases"][0]["melody"][0][0])
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("мягкий верх", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- проверка по вкусу пользователя (taste_check, 2026-11-14): своя оркестровка считается; резкий верх ловится ---
try:
    import os as _os13, tempfile as _tf13, mido as _md13
    import orchestrator as _o13, taste_check as _t13
    _src13 = _os13.path.join(ROOT, "input", "nocturneincsharpminor.mid")
    _st13 = _os13.path.join(_tf13.mkdtemp(prefix="taste_"), "o")
    _o13.run(_src13, _st13)
    _r13 = _t13.check(_src13, _st13 + ".mid")
    _m13 = _md13.MidiFile(_st13 + ".mid")          # та же оркестровка, флейта и гобой на две октавы выше
    for _tr in _m13.tracks:
        if any(_x.type == "track_name" and _x.name in ("Flute", "Oboe") for _x in _tr):
            for _i, _x in enumerate(_tr):
                if _x.type in ("note_on", "note_off"):
                    _tr[_i] = _x.copy(note=min(127, _x.note + 24))
    _m13.save(_st13 + "_high.mid")
    _h13 = _t13.check(_src13, _st13 + "_high.mid")
    _ok = "score" in _r13 and any(c == "В1" for c, _ in _h13["failed"]) and "В1" in _t13.text(_h13)
    _msg = "своя оркестровка: %s; флейта и гобой +2 октавы: В1 %s" % (_r13["score"], "пойман" if _ok else "НЕ пойман")
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("проверка по вкусу", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- шрифты verovio: если родная папка не найдена, берётся копия из репозитория ---
try:
    import verovio as _v14, score_player as _sp14
    _orig = _v14.toolkit
    class _Bad:
        def __init__(self):
            self._t = _orig(); self._t.setResourcePath("/nonexistent_verovio")
        def __getattr__(self, k): return getattr(self._t, k)
    _v14.toolkit = _Bad
    try:
        _tk = _sp14.make_toolkit()
        _xml = open(_src13.replace(".mid", ".musicxml"), encoding="utf-8").read() if False else None
        _ok = os.path.exists(os.path.join(_sp14.BUNDLED_VEROVIO, "Leipzig.xml")) and _tk.getResourcePath() == _sp14.BUNDLED_VEROVIO
    finally:
        _v14.toolkit = _orig
    _msg = "запасная папка шрифтов подключена" if _ok else "НЕ подключена"
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("шрифты verovio", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

# --- мелодия правой руки скачком вниз (ORCH_MEL_TRACK): ноты остаются мелодией, «педальная» нота перебора — нет ---
try:
    import engine2 as _e15
    _rh = [(0, 1, 74), (1, 1.5, 74), (1.5, 2, 67), (2, 2.5, 67), (2.5, 3, 71), (3, 4, 72),       # D5 D5 G4 G4 B4 C5
           (4, 4.5, 84), (4.5, 5, 76), (5, 5.5, 83), (5.5, 6, 76), (6, 6.5, 84), (6.5, 7, 76)]   # C6 E5 B5 E5 C6 E5
    _all = [(a, b, p, 0) for a, b, p in _rh] + [(0, 4, 43, 1), (4, 8, 45, 1)]
    _m0 = {(m["offset"], m["pitch"]) for m in _e15.find_melody(_all)}
    _m1 = {(m["offset"], m["pitch"]) for m in _e15.find_melody(_all, top_part=0)}
    _ok = (1.5, 67) not in _m0 and (1.5, 67) in _m1 and (2, 67) in _m1 and (4.5, 76) not in _m1 and (5, 83) in _m1
    _msg = "без переключателя G4 потерян: %s; с ним G4 в мелодии: %s; педальная E5 не в мелодии: %s" % (
        (1.5, 67) not in _m0, (1.5, 67) in _m1, (4.5, 76) not in _m1)
except Exception as _e:
    _ok = False; _msg = repr(_e)
print("%-30s %s  %s" % ("мелодия правой руки", "OK " if _ok else "FAIL", _msg))
if not _ok: failed += 1

print("\nИТОГ:", "все тесты пройдены" if not failed else "ПРОВАЛЕНО тестов: %d" % failed)
sys.exit(1 if failed else 0)
