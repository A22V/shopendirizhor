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
