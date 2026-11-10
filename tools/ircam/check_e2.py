import sys; sys.path.insert(0, "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/lop2"); sys.path.insert(0, "/home/claude/shopendirizhor/src")
import importlib, statistics as st
from common import load
import cont, pedal
S = "/tmp/claude-0/-home-claude/718a13e4-8715-50b4-a7fc-29c7bb4cad0e/scratchpad/"
src = open(S + "lop2/cover.py").read(); src = src[:src.index("S = ")]
ns = {}; exec(src, ns); cover = ns["cover"]
import quality_gate
m = {"Flute": "Flute", "Oboe": "Oboe", "Clarinet": "Clarinet", "Bassoon": "Bassoon", "Horn": "Horn", "Violin": "Violin", "Violin'": "Violin", "Viola": "Viola", "Violoncello": "Violoncello", "Contrabass": "Contrabass"}
for piece in sys.argv[1:]:
    solo = S + "chopin_orig.mid" if piece == "Chopin" else "/home/claude/shopendirizhor/tests/pieces/%s_piano.mid" % piece
    for lab, d in (("старый", "ours"), ("движок 2", "e2")):
        orch = S + "lop2/%s/%s.mid" % (d, piece)
        c = cover(solo, orch); k = cont.measure(solo, orch)
        O = load(orch)[0]
        res, fc, hc, ni, nf, ntr = pedal.study(solo, orch, inst=m)
        allni = [x for v in ni.values() for x in v]; allfc = [x for v in fc.values() for x in v]; allhc = [x for v in hc.values() for x in v]
        g = quality_gate.check(solo, orch)
        print("%-16s %-9s ноты рояля сыграны %3.0f%% (короткие %s), ритм %3.0f%%, придумано %2.0f%%, поток %.2f | в такте инстр. %.1f: бегут %.1f, держат %.1f | брак: %s | чужих %d/%d, мелодия %d%%, пересадок %d" % (
            piece, lab, 100 * c["all"], "—" if c["short"] is None else "%.0f%%" % (100 * c["short"]), 100 * c["rhythm"], 100 * c["extra"], k["stream_same"], st.mean(allni), st.mean(allfc), st.mean(allhc),
            ",".join(x[0] for x in g["defects"]) or "нет", g["stats"]["foreign"]["bad"], g["stats"]["foreign"]["total"], round(100 * g["stats"]["melody_found"]), g["stats"]["melody_hops"]))
        if lab != "старый": print("   ", {k2: len(v) for k2, v in O.items()})
