"""
Universal LLM planner for the orchestrator.

The model writes the orchestration PLAN (JSON), the code checks it and asks for fixes if needed.
Providers: deepseek, claude, gpt, gemini. Select with the PLANNER_PROVIDER environment variable,
keys come from environment variables only (never store keys in code or in the repository).

  PLANNER_PROVIDER=deepseek|claude|gpt|gemini
  DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
  PLANNER_MODEL=<model name you choose in the provider's console>   (optional override)

Privacy: the note data of the piece is sent to the chosen provider. Use only your own music or
public-domain material, and read the provider's data policy before sending anything.
"""
import os, json, re, urllib.request, urllib.error

INSTRUMENTS = ["Flute", "Oboe", "Clarinet", "Bassoon", "Horn", "Violin I", "Violin II",
               "Viola", "Cello", "Double Bass"]
ENDPOINTS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "gpt": "https://api.openai.com/v1/chat/completions",
    "claude": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}
KEY_VARS = {"deepseek": "DEEPSEEK_API_KEY", "gpt": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


def build_request(provider, model, api_key, system, user):
    """Return (url, headers, body_bytes) for the provider. No network call here."""
    if provider in ("deepseek", "gpt"):
        url = ENDPOINTS[provider]
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + api_key}
        body = {"model": model, "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": user}],
                "temperature": 0.3}
    elif provider == "claude":
        url = ENDPOINTS[provider]
        headers = {"Content-Type": "application/json", "x-api-key": api_key,
                   "anthropic-version": "2023-06-01"}
        body = {"model": model, "max_tokens": 4000, "system": system,
                "messages": [{"role": "user", "content": user}]}
    elif provider == "gemini":
        url = ENDPOINTS[provider].format(model=model) + "?key=" + api_key
        headers = {"Content-Type": "application/json"}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.3}}
    else:
        raise ValueError("unknown provider: " + provider)
    return url, headers, json.dumps(body).encode("utf-8")


def extract_text(provider, data):
    if provider in ("deepseek", "gpt"):
        return data["choices"][0]["message"]["content"]
    if provider == "claude":
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    if provider == "gemini":
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    raise ValueError(provider)


def call_model(provider, model, api_key, system, user, timeout=120):
    url, headers, body = build_request(provider, model, api_key, system, user)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s returned HTTP %s: %s" % (provider, e.code, e.read()[:300]))
    return extract_text(provider, data)


def parse_plan(text):
    """Accept plain JSON or JSON inside a code fence."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def check_plan(plan, n_bars):
    """Structural checks the model cannot be trusted with. Returns a list of problems (empty = ok)."""
    problems = []
    phrases = plan.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        return ["plan has no phrases list"]
    covered = set()
    for ph in phrases:
        a, b = ph.get("bars", [0, 0])
        if not (1 <= a <= b <= n_bars):
            problems.append("phrase %s bars %s outside 1..%d" % (ph.get("id"), [a, b], n_bars))
        covered.update(range(a, b + 1))
        if ph.get("level") not in ("mp", "mf", "f"):
            problems.append("phrase %s: level must be mp, mf or f" % ph.get("id"))
        for role in ("melody", "bass", "inner1", "inner2", "figuration"):
            for spec in ph.get(role, []) or []:
                if spec[0] not in INSTRUMENTS:
                    problems.append("phrase %s: unknown instrument %r" % (ph.get("id"), spec[0]))
                if len(spec) > 1 and not isinstance(spec[1], int):
                    problems.append("phrase %s: octave shift must be an integer" % ph.get("id"))
                for share in spec[2:4]:
                    if share is not None and not (0.0 <= float(share) <= 1.0):
                        problems.append("phrase %s: share %r outside 0..1" % (ph.get("id"), share))
    missing = sorted(set(range(1, n_bars + 1)) - covered)
    if missing:
        problems.append("bars not covered by any phrase: %s" % missing[:20])
    return problems


SYSTEM = (
    "You are an orchestration planner for a chamber ensemble: flute, oboe, clarinet in Bb, bassoon, horn in F, "
    "violin I, violin II, viola, cello, double bass. You do NOT write notes. You write a JSON plan that "
    "assigns voices to instruments phrase by phrase, following academic orchestration practice "
    "(clear melody, gradual entries, no abrupt colour changes, no sustained winds without breath, "
    "no parallel fifths between outer voices, instruments only in their ranges). "
    "Answer with JSON only."
)


def describe_piece(meta, melody, events, n_bars):
    """Compact, plain description of the piece for the model (no full note dump)."""
    lines = ["Bars: %d, time signatures: %s" % (n_bars, meta["tsigs"])]
    lines.append("Melody (bar: pitches, MIDI numbers):")
    starts = [b[0] for b in meta["bars"]]
    per_bar = {}
    for m in melody:
        bi = max(0, sum(1 for s in starts if s <= m["offset"] + 1e-9) - 1)
        per_bar.setdefault(bi + 1, []).append(m["pitch"])
    for b in sorted(per_bar):
        lines.append("  %d: %s" % (b, per_bar[b][:12]))
    lines.append("Accompaniment (figuration notes): %d" % len(meta.get("fig", [])))
    lines.append("Ranges (sounding, MIDI): " + json.dumps(
        {"Flute": [60, 96], "Oboe": [58, 91], "Clarinet": [50, 94], "Bassoon": [34, 75], "Horn": [41, 77],
         "Violin I": [55, 103], "Violin II": [55, 84], "Viola": [48, 79], "Cello": [36, 76],
         "Double Bass": [31, 67]}))
    lines.append("Answer format: {\"phrases\": [{\"id\":1,\"bars\":[1,4],\"kind\":\"lyric|figuration|run|intro\","
                 "\"climax\":false,\"color\":\"...\",\"level\":\"mp|mf|f\","
                 "\"melody\":[[\"Instrument\",octave_shift,from_share?,until_share?]],"
                 "\"inner1\":[...],\"inner2\":[...],\"bass\":[...],\"figuration\":[...],\"why\":[\"...\"]}]}")
    return "\n".join(lines)


def plan_with_model(provider, model, api_key, description, n_bars, max_rounds=3, call=call_model):
    """Ask the model, check, and feed problems back. Returns (plan, log)."""
    log = []
    user = description
    for round_no in range(1, max_rounds + 1):
        text = call(provider, model, api_key, SYSTEM, user)
        try:
            plan = parse_plan(text)
        except Exception as e:
            problems = ["answer is not valid JSON: %s" % e]
        else:
            problems = check_plan(plan, n_bars)
        log.append({"round": round_no, "problems": problems})
        if not problems:
            return plan, log
        user = description + "\n\nYour previous plan had these problems, fix them and answer with JSON only:\n- " + \
               "\n- ".join(problems)
    raise RuntimeError("planner failed after %d rounds: %s" % (max_rounds, log[-1]["problems"]))


def configured_provider():
    p = os.environ.get("PLANNER_PROVIDER", "").strip().lower()
    if p not in KEY_VARS:
        return None, None, None
    key = os.environ.get(KEY_VARS[p], "")
    model = os.environ.get("PLANNER_MODEL", "").strip()
    return p, key, model



def _bar_of_beat(offset, meta):
    starts = [b[0] for b in meta["bars"]]
    idx = max(0, sum(1 for s in starts if s <= offset + 1e-9) - 1)
    return idx + 1


def validator_feedback(issues, meta):
    """Turn validator output into plain sentences with bar numbers, for the model to fix."""
    lines = []
    for sev, rid, off, msg in issues:
        if sev != "error" and rid not in ("QX06", "QX04"):
            continue
        where = " (bar %d)" % _bar_of_beat(off, meta) if isinstance(off, (int, float)) else ""
        lines.append("%s %s: %s%s" % ("ERROR" if sev == "error" else "problem", rid, msg, where))
    return lines


def orchestrate_with_llm(in_path, out_stem, provider, model, api_key, call=call_model, max_rounds=3):
    """Model writes the plan, the orchestrator builds it, the validator checks it, and the model gets the
    validator's findings to fix. Keeps the best attempt. Returns (run_log, issues, names, attempts, plan_path)."""
    import orchestrator as o
    s, events, melody, meta = o.analyze(in_path)
    n_bars = len(meta["bars"])
    description = describe_piece(meta, melody, events, n_bars)
    attempts, best, user = [], None, description
    for r in range(1, max_rounds + 1):
        text = call(provider, model, api_key, SYSTEM, user)
        try:
            plan = parse_plan(text)
        except Exception as e:
            problems = ["answer is not valid JSON: %s" % e]
        else:
            problems = check_plan(plan, n_bars)
        if problems:
            attempts.append({"round": r, "structure": problems})
            user = description + "\n\nYour plan has these structural problems, fix them and answer with JSON only:\n- " + "\n- ".join(problems)
            continue
        stem = "%s_r%d" % (out_stem, r)
        plan_path = stem + "_llm_plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=1)
        log, issues, names = o.run(in_path, stem, "off", plan_path)
        errors = [i for i in issues if i[0] == "error"]
        silent = [i for i in issues if i[1] == "QX06"]
        score = 10 * len(errors) + 2 * len(silent) + sum(1 for i in issues if i[0] == "warning")
        feedback = validator_feedback(issues, meta)
        attempts.append({"round": r, "errors": len(errors), "score": score, "feedback": feedback})
        if best is None or score < best["score"]:
            best = {"score": score, "plan_path": plan_path, "issues": issues, "log": log}
        if not errors and not silent:
            break
        user = (description + "\n\nThe previous plan was built and checked. Problems found:\n- " +
                "\n- ".join(feedback) +
                "\nFix them: avoid parallel fifths between voices, give every instrument a part, "
                "keep each instrument in its range, answer with JSON only.")
    if best is None:
        raise RuntimeError("planner produced no valid plan: %s" % attempts[-1])
    log, issues, names = o.run(in_path, out_stem, "off", best["plan_path"])
    return log, issues, names, attempts, best["plan_path"]
