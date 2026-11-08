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
# напетая мелодия → MIDI (src/melody_midi.py, web/mic.py, web/mic_recorder/index.html)
try:
    import melody_midi, mido as _mido, io as _io
    _N = [[0.12, 0.76, 52, 100], [0.88, 0.37, 52, 100], [1.25, 0.37, 50, 100], [1.62, 0.76, 48, 100], [2.38, 1.5, 45, 100]]
    _d, _i = melody_midi.notes_to_midi(_N, 80, "восьмые", "0")
    _m = _mido.MidiFile(file=_io.BytesIO(_d)); _t = 0; _on = []
    for _x in _m.tracks[1]:
        _t += _x.time
        if _x.type == "note_on" and _x.velocity > 0:
            _on.append((_t / 480, _x.note))
    ok = [p for _, p in _on] == [52, 52, 50, 48, 45] and [b - a for (a, _), (b, _) in zip(_on, _on[1:])] == [1.0, 0.5, 0.5, 1.0]
    ok = ok and melody_midi.auto_octave([45, 47, 48, 52]) == 1 and _i["notes"] == 5
    _mh = open(os.path.join(ROOT, "web", "mic_recorder", "index.html"), encoding="utf-8").read()
    ok = ok and all(k in _mh for k in ("getUserMedia", "yinFrames", "streamlit:setComponentValue", "OfflineAudioContext",
                                       "ResizeObserver", "analyseBP", "basic_pitch_model/model.json"))
    _md = os.path.join(ROOT, "web", "mic_recorder")
    ok = ok and all(os.path.getsize(os.path.join(_md, f)) > 100000 for f in
                    ("basic_pitch.min.js", "basic_pitch_model/model.json", "basic_pitch_model/group1-shard1of1.bin"))
    # режим «несколько нот сразу»: аккорд сохраняется, октава не сдвигается
    _P = [[0.0, 1.0, 48, 90], [0.0, 1.0, 52, 90], [0.0, 1.0, 55, 90], [1.0, 0.5, 60, 90]]
    _dp, _ip = melody_midi.notes_to_midi(_P, 80, "нет", "авто", poly=True)
    _mp = _mido.MidiFile(file=_io.BytesIO(_dp)); _tp = 0; _at0 = []
    for _x in _mp.tracks[1]:
        _tp += _x.time
        if _x.type == "note_on" and _x.velocity > 0 and _tp == 0:
            _at0.append(_x.note)
    ok = ok and sorted(_at0) == [48, 52, 55] and _ip["octave_shift"] == 0 and _ip["poly"] and _ip["notes"] == 4
    ok = ok and "bpp" in _mh and "poly:" in _mh
    ok = ok and "decodeAudioData" in _mh and 'id="afile"' in _mh and "MAX_FILE_SEC" in _mh
    print("%-30s %s" % ("напетая мелодия → MIDI", "OK " if ok else "FAIL"))
    failed += 0 if ok else 1
except Exception:
    print("напетая мелодия → MIDI FAIL (исключение)"); traceback.print_exc(); failed += 1
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
print("\nИТОГ:", "все тесты пройдены" if not failed else "ПРОВАЛЕНО тестов: %d" % failed)
sys.exit(1 if failed else 0)
