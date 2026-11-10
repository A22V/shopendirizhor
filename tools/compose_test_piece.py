"""
Тестовая фортепианная пьеса ~2 минуты для проверки оркестровки (2026-11-10).
Нужна, чтобы проверять программу на ЧИСТОМ материале: ноты точно на сетке, две руки на двух дорожках, педаль по тактам,
несколько темпов и размеров, умеренная трудность (растяжка каждой руки не больше октавы с небольшим).
Пьеса сочинена программой по простым правилам (гармония по тактам, мелодия шагами по звукоряду с опорой на звуки аккорда):
это материал для проверки, а не музыка для концерта. Результат детерминирован (зерно 1).
Запуск: python tools/compose_test_piece.py выход.mid
Части: 1) Andante 72, 4/4, ля минор, мелодия + Альберти; 2) Allegretto 116, 3/4, до мажор, вальс; 3) Adagio 58, 4/4,
ля минор, долгая мелодия в терциях + медленные арпеджио; 4) Vivace 138, 4/4: 8 тактов мелодия над шестнадцатыми,
8 тактов быстрые арпеджио правой руки, финал ля мажор.
"""
import sys, random
import mido

TPB = 480
rnd = random.Random(1)
MAJ, MIN, DOM7 = (0, 4, 7), (0, 3, 7), (0, 4, 7, 10)
PC = {"A": 9, "B": 11, "C": 0, "D": 2, "E": 4, "F": 5, "G": 7}


def chord(name):
    """'Am' -> (корень 0..11, тип). 'E7' — доминантсептаккорд, 'A' — мажор."""
    root = PC[name[0]]
    if name.endswith("7"):
        return root, DOM7
    return root, (MIN if name.endswith("m") else MAJ)


def scale_notes(tonic, minor, lo, hi, leading=False):
    pcs = [(tonic + x) % 12 for x in ((0, 2, 3, 5, 7, 8, 10) if minor else (0, 2, 4, 5, 7, 9, 11))]
    if minor and leading:
        pcs = [(tonic + 11) % 12 if p == (tonic + 10) % 12 else p for p in pcs]
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def near(pc, target, lo, hi):
    c = [m for m in range(lo, hi + 1) if m % 12 == pc % 12]
    return min(c, key=lambda m: abs(m - target))


class Piece:
    def __init__(self):
        self.rh, self.lh, self.pedal, self.tempo, self.meter = [], [], [], [], []
        self.t = 0.0                      # текущее время в долях (четвертях)

    def note(self, hand, start, dur, pitch, vel):
        (self.rh if hand == "R" else self.lh).append((start, dur, pitch, max(20, min(120, int(vel)))))


def melody_bar(scale, idx, rhythm, strong, chord_pcs, vel, direction, last_long=False):
    """Мелодия одного такта шагами по звукоряду; на сильных долях — ближайший звук аккорда."""
    out, pos = [], 0.0
    for k, d in enumerate(rhythm):
        if k == 0 or pos in strong:
            cands = [i for i, m in enumerate(scale) if m % 12 in chord_pcs and abs(i - idx) <= 3]
            if cands:
                idx = min(cands, key=lambda i: (abs(i - idx), i))
        else:
            step = rnd.choice((-2, -1, -1, 1, 1, 2)) if rnd.random() < 0.8 else rnd.choice((-3, 3))
            if rnd.random() < 0.55:
                step = abs(step) * direction
            idx = max(0, min(len(scale) - 1, idx + step))
        out.append((pos, d, scale[idx], vel + (6 if pos == 0 else 0) + rnd.randint(-2, 2)))
        pos += d
    return out, idx


def build():
    P = Piece()
    beat = 0.0

    def tempo(b, bpm):
        P.tempo.append((b, bpm))

    def bar_pedal(b0, b1):
        P.pedal.append((b0, 127)); P.pedal.append((b1 - 0.12, 0))

    # ---------- 1. Andante, 4/4, ля минор ----------
    P.meter.append((0.0, 4, 4)); tempo(0, 72)
    prog = ["Am", "Am", "F", "C", "G", "Em", "Am", "Dm", "E", "Am", "E7", "Am"]
    rhythms = [[2, 1, 1], [1.5, 0.5, 1, 1], [1, 1, 2], [1, 1, 1, 1], [1.5, 0.5, 2], [0.5, 0.5, 1, 2], [2, 2]]
    idx, direction = None, 1
    for n, name in enumerate(prog):
        b0 = beat; root, q = chord(name)
        pcs = {(root + x) % 12 for x in q}
        sc = scale_notes(9, True, 62, 86, leading=name in ("E", "E7"))
        if idx is None:
            idx = min(range(len(sc)), key=lambda i: abs(sc[i] - 72))
        if n % 4 == 3: direction = -1
        elif n % 4 == 0: direction = 1
        last = n == len(prog) - 1
        rhy = [4] if last else (rnd.choice(rhythms) if n % 4 != 3 else rnd.choice([[2, 2], [1, 1, 2], [3, 1]]))
        vel = 56 + 4 * (n % 4) + (6 if n in (8, 9) else 0)
        mel, idx = melody_bar(sc, idx, rhy, {0.0, 2.0}, pcs, vel, direction)
        for s, d, p, v in mel: P.note("R", b0 + s, d, p, v)
        base = near(root, 45, 38, 52)
        third = base + (q[1]); fifth = base + 7
        pat = [base, third, fifth, third] * 2 if not last else [base]
        if last:
            P.note("L", b0, 4, base, 50)
        else:
            for k, p in enumerate(pat):
                P.note("L", b0 + 0.5 * k, 0.5, p, 44 + (8 if k % 4 == 0 else 0) + rnd.randint(-2, 2))
        bar_pedal(b0, b0 + 4); beat += 4
        if n == 10: tempo(b0, 66)
        if n == 11: tempo(b0, 60); tempo(b0 + 2, 54)

    # ---------- 2. Allegretto, 3/4, до мажор (вальс) ----------
    P.meter.append((beat, 3, 4)); tempo(beat, 116)
    prog = ["C", "C", "G", "G", "Am", "Am", "F", "G", "C", "C", "G7", "G7", "Am", "F", "Dm", "G7", "C", "F", "G7", "C"]
    rhythms3 = [[1, 1, 1], [1.5, 0.5, 1], [2, 1], [1, 0.5, 0.5, 1], [0.5, 0.5, 0.5, 0.5, 1], [1, 2]]
    idx, prev_inv = None, None
    for n, name in enumerate(prog):
        b0 = beat; root, q = chord(name)
        pcs = {(root + x) % 12 for x in q}
        sc = scale_notes(0, False, 62, 88)
        if idx is None:
            idx = min(range(len(sc)), key=lambda i: abs(sc[i] - 76))
        direction = 1 if (n // 2) % 2 == 0 else -1
        last = n == len(prog) - 1
        rhy = [3] if last else rnd.choice(rhythms3)
        vel = 66 + 3 * (n % 4) + (8 if 8 <= n < 16 else 0)
        mel, idx = melody_bar(sc, idx, rhy, {0.0}, pcs, vel, direction)
        for s, d, p, v in mel: P.note("R", b0 + s, d, p, v)
        base = near(root, 41, 36, 47)
        P.note("L", b0, 3 if last else 1, base, 60)
        if not last:
            tones = sorted({near((root + x) % 12, 58, 52, 66) for x in q[:3]})
            for k in (1, 2):
                for p in tones: P.note("L", b0 + k, 1, p, 46 + rnd.randint(-2, 2))
        else:
            P.note("L", b0, 3, base - 12 if base - 12 >= 33 else base, 50); P.note("L", b0, 3, base, 50)
        bar_pedal(b0, b0 + 3); beat += 3
        if n == len(prog) - 3: tempo(b0, 108)
        if n == len(prog) - 2: tempo(b0, 100)
        if n == len(prog) - 1: tempo(b0, 92)

    # ---------- 3. Adagio, 4/4, ля минор: долгая мелодия в терциях ----------
    P.meter.append((beat, 4, 4)); tempo(beat, 58)
    prog = ["Am", "Dm", "G", "C", "F", "E"]
    rhy3 = [[2, 1, 1], [3, 1], [2, 2], [1.5, 0.5, 2], [2, 1, 1], [4]]
    idx = None
    for n, name in enumerate(prog):
        b0 = beat; root, q = chord(name)
        pcs = {(root + x) % 12 for x in q}
        sc = scale_notes(9, True, 60, 84, leading=name == "E")
        if idx is None:
            idx = min(range(len(sc)), key=lambda i: abs(sc[i] - 69))
        mel, idx = melody_bar(sc, idx, rhy3[n], {0.0, 2.0}, pcs, 48 + 3 * n, 1 if n < 3 else -1)
        for s, d, p, v in mel:
            P.note("R", b0 + s, d, p, v)
            i = sc.index(p)
            if i >= 2 and d >= 1.0:
                P.note("R", b0 + s, d, sc[i - 2], v - 8)      # терция ниже
        base = near(root, 45, 38, 52)
        for k, p in enumerate([base, base + 7, base + 12, base + 7]):
            P.note("L", b0 + k, 1, p, 40 + (6 if k == 0 else 0))
        bar_pedal(b0, b0 + 4); beat += 4
        if n == 5: tempo(b0 + 2, 50)

    # ---------- 4. Vivace, 4/4, ля минор -> ля мажор ----------
    P.meter.append((beat, 4, 4)); tempo(beat, 138)
    prog = ["Am", "Dm", "E", "Am", "Am", "Dm", "E", "Am", "Am", "F", "G", "Am", "Dm", "E", "E7", "A"]
    idx = None
    for n, name in enumerate(prog):
        b0 = beat; root, q = chord(name)
        pcs = {(root + x) % 12 for x in q}
        last = n == len(prog) - 1
        if n < 8:   # мелодия восьмыми над шестнадцатыми левой руки
            sc = scale_notes(9, True, 64, 88, leading=name == "E")
            if idx is None:
                idx = min(range(len(sc)), key=lambda i: abs(sc[i] - 76))
            mel, idx = melody_bar(sc, idx, rnd.choice([[1] * 4, [1.5, 0.5, 1, 1], [0.5] * 8, [1, 1, 2]]), {0.0, 2.0}, pcs, 84 + (6 if n >= 4 else 0), 1 if n % 2 == 0 else -1)
            for s, d, p, v in mel: P.note("R", b0 + s, d, p, v)
            base = near(root, 45, 38, 52)
            seq = [base, base + 7, base + 12, base + 7] * 4
            for k, p in enumerate(seq): P.note("L", b0 + 0.25 * k, 0.25, p, 56 + (10 if k % 4 == 0 else 0))
        elif last:
            base = near(root, 45, 38, 52)
            for p in (base - 12 if base - 12 >= 33 else base, base): P.note("L", b0, 4, p, 96)
            r0 = near(root, 69, 64, 75)
            for p in (r0, r0 + q[1], r0 + 7, r0 + 12): P.note("R", b0, 4, p, 100)
        else:       # быстрые арпеджио правой руки, аккорды-вздохи слева
            start = near(root, 62, 55, 66)
            up = [start, start + q[1], start + 7, start + 12, start + 12 + q[1], start + 19, start + 12 + q[1], start + 12]
            seq = up + [start + 7, start + q[1], start, start + q[1], start + 7, start + 12, start + 7, start + q[1]]
            for k, p in enumerate(seq): P.note("R", b0 + 0.25 * k, 0.25, p, 88 + (8 if k % 4 == 0 else 0))
            base = near(root, 43, 36, 50)
            P.note("L", b0, 1, base, 84); P.note("L", b0 + 2, 1, base, 80)      # бас и аккорд-вздох по очереди (рука прыгает)
            for p in sorted({near((root + x) % 12, 55, 50, 62) for x in q[:3]}):
                P.note("L", b0 + 1, 0.5, p, 70); P.note("L", b0 + 3, 0.5, p, 70)
        bar_pedal(b0, b0 + 4) if not last else P.pedal.append((b0, 127))
        beat += 4
    P.pedal.append((beat + 3.0, 0))
    tempo(beat - 4, 138); tempo(beat - 2, 120); tempo(beat - 1, 100)
    return P, beat


def write(P, path):
    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    cond = mido.MidiTrack(); mid.tracks.append(cond)
    ev = []
    for b, bpm in P.tempo: ev.append((int(round(b * TPB)), 0, mido.MetaMessage("set_tempo", tempo=int(60e6 / bpm))))
    for b, n, d in P.meter: ev.append((int(round(b * TPB)), 0, mido.MetaMessage("time_signature", numerator=n, denominator=d)))
    ev.sort(key=lambda e: e[0]); t = 0
    for tick, _, m in ev:
        m.time = tick - t; t = tick; cond.append(m)
    for name, notes, pedal in (("Piano", P.rh, P.pedal), ("Piano", P.lh, [])):
        tr = mido.MidiTrack(); mid.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=name)); tr.append(mido.Message("program_change", program=0, time=0))
        ev = []
        for s, d, p, v in notes:
            ev.append((int(round(s * TPB)), 1, mido.Message("note_on", note=p, velocity=v)))
            ev.append((int(round((s + d) * TPB)), 0, mido.Message("note_off", note=p, velocity=0)))
        for b, val in pedal:
            ev.append((int(round(b * TPB)), 0, mido.Message("control_change", control=64, value=val)))
        ev.sort(key=lambda e: (e[0], e[1])); t = 0
        for tick, _, m in ev:
            m.time = tick - t; t = tick; tr.append(m)
    mid.save(path)


def seconds(P, total_beats):
    tm = sorted(P.tempo); s = 0.0
    for i, (b, bpm) in enumerate(tm):
        nb = tm[i + 1][0] if i + 1 < len(tm) else total_beats
        s += max(0.0, nb - b) * 60.0 / bpm
    return s


if __name__ == "__main__":
    P, total = build()
    write(P, sys.argv[1])
    print("нот: правая %d, левая %d; длина %.0f с (%d долей)" % (len(P.rh), len(P.lh), seconds(P, total), total))
