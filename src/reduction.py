"""
Piano reduction of an orchestral MIDI: all instruments are merged into one texture, split into a right hand
(at or above middle C) and a left hand (below), and each moment keeps at most a few notes per hand
(top and bottom voices are kept, inner voices are removed first). Timpani/percussion (channel 10 and 15) are dropped.
No model is used: this is a deterministic procedure, so the result is the same every time.
"""
import mido, collections

SPLIT = 60          # middle C
MAX_RH, MAX_LH = 4, 3
PERCUSSION = {9, 15}  # MIDI channels 10 and 16 (0-based 9 and 15)


def _pick(pitches, keep_top, keep_bottom):
    pitches = sorted(set(pitches))
    if len(pitches) <= keep_top + keep_bottom:
        return pitches
    return sorted(set(pitches[-keep_top:]) | set(pitches[:keep_bottom]))


def reduce_to_piano(in_path, out_path, max_rh=MAX_RH, max_lh=MAX_LH):
    src = mido.MidiFile(in_path)
    tpb = src.ticks_per_beat
    tempo_msgs = [m for m in src.tracks[0] if m.type in ("set_tempo", "time_signature", "key_signature")] if src.tracks else []
    notes = []
    for tr in src.tracks:
        t, on = 0, {}
        for msg in tr:
            t += msg.time
            ch = getattr(msg, "channel", 0)
            if ch in PERCUSSION: continue
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault((ch, msg.note), []).append(t)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                k = (ch, msg.note)
                if on.get(k):
                    s = on[k].pop(0); notes.append((s, t - s, msg.note))
    notes.sort()
    tol = max(1, tpb // 8)
    groups = []
    for s, d, p in notes:
        if groups and s - groups[-1][0] <= tol: groups[-1][1].append((s, d, p))
        else: groups.append([s, [(s, d, p)]])
    rh_ev, lh_ev = [], []
    orig_pc, kept_pc = {}, {}
    for start, items in groups:
        durs = {}
        for _, d, p in items: durs[p] = max(durs.get(p, 0), d)
        pitches = list(durs)
        rh = [p for p in pitches if p >= SPLIT]
        lh = [p for p in pitches if p < SPLIT]
        rh_k = _pick(rh, 3, 1) if len(set(rh)) > max_rh else sorted(set(rh))
        lh_k = _pick(lh, 1, 2) if len(set(lh)) > max_lh else sorted(set(lh))
        rh_ev += [(start, durs[p], p) for p in rh_k]
        lh_ev += [(start, durs[p], p) for p in lh_k]
        orig_pc[start] = len({p % 12 for p in pitches})
        kept_pc[start] = len({p % 12 for p in rh_k + lh_k})
    out = mido.MidiFile(type=1, ticks_per_beat=tpb)
    head = mido.MidiTrack(); out.tracks.append(head)
    for m in tempo_msgs: head.append(m.copy(time=m.time))
    for name, ch, events in (("Piano RH", 0, rh_ev), ("Piano LH", 1, lh_ev)):
        tr = mido.MidiTrack(); out.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        ev = []
        for s, d, p in events:
            ev.append((s, 1, p)); ev.append((s + max(1, d), 0, p))
        ev.sort(key=lambda x: (x[0], x[1]))
        last = 0
        for t, is_on, p in ev:
            tr.append(mido.Message("note_on" if is_on else "note_off", channel=ch, note=p,
                                   velocity=80 if is_on else 0, time=t - last))
            last = t
    out.save(out_path)
    cov = [kept_pc[s] / orig_pc[s] for s in orig_pc if orig_pc[s]]
    return {"notes_in": len(notes), "notes_rh": len(rh_ev), "notes_lh": len(lh_ev),
            "pitch_class_coverage": round(sum(cov) / len(cov), 3) if cov else 0.0,
            "full_coverage_share": round(sum(1 for c in cov if c >= 0.999) / len(cov), 3) if cov else 0.0}


BLOCK_BARS = 8          # the model decides once per block of eight bars (4/4 assumed)
KEEP_CHOICES = ("balanced", "outer", "melody")


def _collect(in_path):
    src = mido.MidiFile(in_path)
    tpb = src.ticks_per_beat
    tempo_msgs = [m for m in src.tracks[0] if m.type in ("set_tempo", "time_signature", "key_signature")] if src.tracks else []
    notes = []
    for tr in src.tracks:
        t, on = 0, {}
        for msg in tr:
            t += msg.time
            ch = getattr(msg, "channel", 0)
            if ch in PERCUSSION: continue
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault((ch, msg.note), []).append(t)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                k = (ch, msg.note)
                if on.get(k):
                    s = on[k].pop(0); notes.append((s, t - s, msg.note))
    notes.sort()
    return tpb, tempo_msgs, notes


def describe_for_reduction(in_path):
    """Short text for the model: per block of bars, how dense the texture is and its range."""
    tpb, _, notes = _collect(in_path)
    bar_ticks = tpb * 4 * BLOCK_BARS
    blocks = {}
    for s, d, p in notes:
        b = int(s // bar_ticks)
        blocks.setdefault(b, []).append(p)
    lines = ["Blocks of %d bars (4/4). Columns: block, bars, notes, lowest, highest, peak simultaneous notes per hand" % BLOCK_BARS]
    for b in sorted(blocks):
        ps = blocks[b]
        lines.append("block %d: bars %d-%d, notes %d, range %d-%d" %
                     (b + 1, b * BLOCK_BARS + 1, (b + 1) * BLOCK_BARS, len(ps), min(ps), max(ps)))
    return "\n".join(lines), len(blocks)


def validate_keep_plan(plan, n_blocks):
    """Clamp the model's choices to safe values. Returns (clean_plan, problems)."""
    problems, clean = [], {}
    blocks = plan.get("blocks", []) if isinstance(plan, dict) else []
    for item in blocks:
        try:
            b = int(item["block"]) - 1
            rh = int(item["rh_max"]); lh = int(item["lh_max"])
            keep = str(item.get("keep", "balanced"))
        except Exception:
            problems.append("bad block entry: %r" % (item,)); continue
        if not (0 <= b < n_blocks):
            problems.append("block %s outside 1..%d" % (item.get("block"), n_blocks)); continue
        if keep not in KEEP_CHOICES:
            problems.append("block %s: keep must be one of %s" % (item.get("block"), KEEP_CHOICES)); keep = "balanced"
        clean[b] = {"rh_max": min(max(rh, 2), 6), "lh_max": min(max(lh, 2), 5), "keep": keep}
    for b in range(n_blocks):
        clean.setdefault(b, {"rh_max": MAX_RH, "lh_max": MAX_LH, "keep": "balanced"})
    return clean, problems


def reduce_with_keep_plan(in_path, out_path, keep_plan):
    """Same procedure as reduce_to_piano, but the per-block limits and voice choice come from keep_plan."""
    tpb, tempo_msgs, notes = _collect(in_path)
    bar_ticks = tpb * 4 * BLOCK_BARS
    tol = max(1, tpb // 8)
    groups = []
    for s, d, p in notes:
        if groups and s - groups[-1][0] <= tol: groups[-1][1].append((s, d, p))
        else: groups.append([s, [(s, d, p)]])
    rh_ev, lh_ev = [], []
    orig_pc, kept_pc = {}, {}
    for start, items in groups:
        blk = keep_plan.get(int(start // bar_ticks), {"rh_max": MAX_RH, "lh_max": MAX_LH, "keep": "balanced"})
        durs = {}
        for _, d, p in items: durs[p] = max(durs.get(p, 0), d)
        pitches = list(durs)
        rh = [p for p in pitches if p >= SPLIT]
        lh = [p for p in pitches if p < SPLIT]
        if blk["keep"] == "outer":
            rh_k = _pick(rh, 1, 1) if len(set(rh)) > blk["rh_max"] else sorted(set(rh))
            lh_k = _pick(lh, 1, 1) if len(set(lh)) > blk["lh_max"] else sorted(set(lh))
        elif blk["keep"] == "melody":
            rh_k = sorted(set(rh))[-blk["rh_max"]:] if len(set(rh)) > blk["rh_max"] else sorted(set(rh))
            lh_k = _pick(lh, 1, 2) if len(set(lh)) > blk["lh_max"] else sorted(set(lh))
        else:
            rh_k = _pick(rh, blk["rh_max"] - 1, 1) if len(set(rh)) > blk["rh_max"] else sorted(set(rh))
            lh_k = _pick(lh, 1, blk["lh_max"] - 1) if len(set(lh)) > blk["lh_max"] else sorted(set(lh))
        rh_ev += [(start, durs[p], p) for p in rh_k]
        lh_ev += [(start, durs[p], p) for p in lh_k]
        orig_pc[start] = len({p % 12 for p in pitches})
        kept_pc[start] = len({p % 12 for p in rh_k + lh_k})
    out = mido.MidiFile(type=1, ticks_per_beat=tpb)
    head = mido.MidiTrack(); out.tracks.append(head)
    for m in tempo_msgs: head.append(m.copy(time=m.time))
    for name, ch, events in (("Piano RH", 0, rh_ev), ("Piano LH", 1, lh_ev)):
        tr = mido.MidiTrack(); out.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        ev = []
        for s, d, p in events:
            ev.append((s, 1, p)); ev.append((s + max(1, d), 0, p))
        ev.sort(key=lambda x: (x[0], x[1]))
        last = 0
        for t, is_on, p in ev:
            tr.append(mido.Message("note_on" if is_on else "note_off", channel=ch, note=p,
                                   velocity=80 if is_on else 0, time=t - last))
            last = t
    out.save(out_path)
    cov = [kept_pc[s] / orig_pc[s] for s in orig_pc if orig_pc[s]]
    return {"notes_in": len(notes), "notes_rh": len(rh_ev), "notes_lh": len(lh_ev),
            "pitch_class_coverage": round(sum(cov) / len(cov), 3) if cov else 0.0,
            "full_coverage_share": round(sum(1 for c in cov if c >= 0.999) / len(cov), 3) if cov else 0.0}
