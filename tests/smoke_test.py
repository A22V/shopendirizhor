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
print("\nИТОГ:", "все тесты пройдены" if not failed else "ПРОВАЛЕНО тестов: %d" % failed)
sys.exit(1 if failed else 0)
