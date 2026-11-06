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
print("\nИТОГ:", "все тесты пройдены" if not failed else "ПРОВАЛЕНО тестов: %d" % failed)
sys.exit(1 if failed else 0)
