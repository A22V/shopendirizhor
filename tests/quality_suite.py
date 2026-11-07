"""
Постоянный набор пьес для проверки оркестровки (2026-11-07).
Каждую правку проверять на всех пьесах набора сразу, а не на одной.

Запуск:  python tests/quality_suite.py [папка_с_пьесами]
  папка по умолчанию: tests/pieces (в репозиторий НЕ кладётся: у части MIDI неясные права).
  В папке: фортепианные MIDI; рядом можно положить сохранённые планы модели <пьеса>_plan*.json —
  тогда пьеса прогоняется и по каждому плану (без платных вызовов модели).
Переключатели берутся из окружения, как в облаке (ORCH_RANGES, ORCH_MELODY_HELD …).
Вывод: таблица «пьеса × план → брак», подробности по каждому браку.
"""
import os, sys, glob, io, contextlib, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import orchestrator, quality_gate  # noqa: E402


def run(folder):
    pieces = sorted(p for p in glob.glob(os.path.join(folder, "*.mid")))
    if not pieces:
        print("В папке %s нет MIDI." % folder)
        return 1
    out = tempfile.mkdtemp(prefix="suite_")
    rows, details = [], []
    for piano in pieces:
        stem = os.path.splitext(os.path.basename(piano))[0]
        plans = [None] + sorted(glob.glob(os.path.join(folder, stem + "_plan*.json")))
        mel = quality_gate.melody_of(piano)
        for plan in plans:
            label = "встроенный" if plan is None else os.path.basename(plan)[len(stem) + 1:-5]
            dst = os.path.join(out, "%s_%s" % (stem, label))
            with contextlib.redirect_stdout(io.StringIO()):
                orchestrator.run(piano, dst, plan_path=plan)
            res = quality_gate.check(piano, dst + ".mid", melody=mel)
            s = res["stats"]
            rows.append((stem[:28], label[:22], "нет" if res["ok"] else ",".join(c for c, _, _ in res["defects"]),
                         s["foreign"]["bad"], round(100 * s["melody_found"]), s["melody_hops"], s["bars"],
                         ",".join(c for c, _, _ in res["warnings"]) or "-"))
            for c, t, _ in res["defects"]:
                details.append("%s / %s: [%s] %s" % (stem, label, c, t))
    print("%-28s %-22s %-14s %6s %8s %9s %6s %s" % ("пьеса", "план", "брак", "фальшь", "мелодия%", "переходы", "такты", "предупр."))
    for r in rows:
        print("%-28s %-22s %-14s %6d %8d %9d %6d %s" % r)
    print("\nБез брака: %d из %d прогонов." % (sum(1 for r in rows if r[2] == "нет"), len(rows)))
    for d in details:
        print(" -", d)
    print("Файлы: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "pieces")))
