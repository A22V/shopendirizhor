"""
Turns a moment of the recording into a bar number and phrase.
Usage: python src/time_to_bar.py input/piece.mid 80 [out/piece_plan.json]     (80 = seconds from the start)
The user says "around 1:20 it sounds harsh" -> 1:20 = 80 seconds.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orchestrator


def main():
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 3:
        print(__doc__); return
    path, secs = sys.argv[1], float(sys.argv[2])
    s, events, melody, meta = orchestrator.analyze(path)
    segs = list(meta["tempos"]) or [(0.0, 60.0)]
    if segs[0][0] > 0: segs.insert(0, (0.0, segs[0][1]))
    t, off = 0.0, 0.0
    for i, (o, bpm) in enumerate(segs):
        end = segs[i + 1][0] if i + 1 < len(segs) else float("inf")
        spq = 60.0 / bpm
        if t + (end - o) * spq >= secs:
            off = o + (secs - t) / spq
            break
        t += (end - o) * spq
    starts = [b[0] for b in meta["bars"]]
    bi = orchestrator.bar_of(starts, off)
    beat = off - starts[bi] + 1
    msg = "Время %d:%02d = такт %d, доля %.1f" % (secs // 60, secs % 60, bi + 1, beat)
    if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
        plan = json.load(open(sys.argv[3], encoding="utf-8"))
        for ph in plan["phrases"]:
            if ph["bars"][0] <= bi + 1 <= ph["bars"][1]:
                msg += "; фраза %d (такты %d-%d, тип %s, окраска %s, громкость %s)" % (
                    ph["id"], ph["bars"][0], ph["bars"][1], ph["kind"], ph.get("color"), ph["level"])
    print(msg)


if __name__ == "__main__":
    main()
