"""
Compare planners on the same pieces: rule-based, hand-written plan, or any model via llm_planner.

Usage (on your computer or in the cloud, where the key is set in the environment):
  python src/compare_models.py input/piece.mid provider model
  python src/compare_models.py input/piece.mid rules          # the rule-based planner, no model
Each run appends one row to out/comparison.csv with the same measures, so providers can be compared.
Fill the 'listening' column by hand after you listen to the MP3.
"""
import sys, os, csv, json, warnings
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orchestrator as o
import llm_planner as L

FIELDS = ["piece", "planner", "model", "rounds", "errors", "warnings", "octave_shifts",
          "silent_instruments", "unresolved_fifths", "listening"]


def measures(log, issues):
    return {
        "errors": sum(1 for i in issues if i[0] == "error"),
        "warnings": sum(1 for i in issues if i[0] == "warning"),
        "octave_shifts": log.get("octave_shifts", 0),
        "silent_instruments": sum(1 for i in issues if i[1] == "QX06"),
        "unresolved_fifths": len(log.get("fifths_unresolved", [])),
    }


def append_row(csv_path, row):
    new = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new: w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def main(argv):
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    if len(argv) < 3:
        print(__doc__); return
    piece, planner = argv[1], argv[2]
    name = os.path.splitext(os.path.basename(piece))[0]
    out_dir = os.path.join(os.path.dirname(HERE), "out", "compare"); os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(os.path.dirname(HERE), "out", "comparison.csv")
    stem = os.path.join(out_dir, name + "_" + planner.replace("/", "_"))
    if planner == "rules":
        log, issues, names = o.run(piece, stem, "off", None)
        row = dict(piece=name, planner="rules", model="-", rounds=0, **measures(log, issues))
    else:
        provider, model = planner, (argv[3] if len(argv) > 3 else "")
        key = os.environ.get(L.KEY_VARS.get(provider, ""), "")
        if not key:
            print("No key found in the environment for", provider); return
        log, issues, names, attempts, plan_path = L.orchestrate_with_llm(piece, stem, provider, model, key)
        row = dict(piece=name, planner=provider, model=model, rounds=len(attempts), **measures(log, issues))
    append_row(csv_path, row)
    print("written:", row)


if __name__ == "__main__":
    main(sys.argv)
