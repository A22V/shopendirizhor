"""
Страница-проигрыватель партитуры (2026-11-08): один HTML со всем нужным внутри.
Звук считается в браузере (spessasynth, web/player_js). Банк звуков: по умолчанию MS Basic (банк MuseScore 4,
MIT) скачивается один раз из репозитория и хранится в памяти браузера; можно выбрать свой файл .sf2/.sf3/.dls
с телефона — он тоже запоминается. Данные партитуры готовит src/score_player.py.
"""
import base64, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BANK_URL = "https://raw.githubusercontent.com/A22V/shopendirizhor/main/soundfonts/MS%20Basic.sf3"
DEFAULT_BANK_NAME = "MS Basic (банк MuseScore 4)"


def _b64(name):
    with open(os.path.join(HERE, "player_js", name), "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def build(prep, bank_url=DEFAULT_BANK_URL, bank_name=DEFAULT_BANK_NAME):
    data = {"parts": prep["parts"], "timemap": prep["timemap"], "tempo": prep["tempo"], "length": prep["length"],
            "notes": prep["notes"], "name": prep["name"], "bankUrl": bank_url, "bankName": bank_name,
            "midi": base64.b64encode(prep["sound"]).decode("ascii")}
    svg = "".join('<div class="page">%s</div>' % s for s in prep["pages"])
    return (TEMPLATE.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
            .replace("<!--SVG-->", svg).replace("LIB_B64", _b64("spessa_lib.min.js"))
            .replace("PROC_B64", _b64("spessasynth_processor.min.js")))


TEMPLATE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--ink:#2a1c12;--paper:#fffdf7;--gold:#b8892b;--red:#8e1426;--mute:#9a8f80;--line:#e6dcc6}
*{box-sizing:border-box}
body{margin:0;font-family:Georgia,"Times New Roman",serif;color:var(--ink);background:var(--paper)}
#bar{position:sticky;top:0;z-index:5;background:#f5ecd7;border-bottom:2px solid var(--gold);padding:8px 10px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{font:inherit;font-size:16px;border:1px solid var(--gold);background:#fff;border-radius:8px;padding:8px 12px;color:var(--ink)}
button.main{background:var(--red);color:#fff;border-color:var(--red);min-width:110px;font-weight:bold}
button:disabled{opacity:.5}
#time{font-variant-numeric:tabular-nums;min-width:96px}
input[type=range]{flex:1;min-width:120px;accent-color:var(--red)}
#status{font-size:13px;color:#5b4a36;margin-top:6px}
#prog{height:6px;background:var(--line);border-radius:3px;margin-top:4px;display:none}
#prog>div{height:100%;width:0;background:var(--gold);border-radius:3px}
#parts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{display:flex;align-items:center;border:1px solid var(--gold);border-radius:16px;overflow:hidden;font-size:14px;background:#fff}
.chip .nm{padding:5px 10px;cursor:pointer;user-select:none}
.chip .so{padding:5px 8px;border-left:1px solid var(--line);cursor:pointer;font-size:12px;color:#5b4a36}
.chip.off .nm{color:var(--mute);text-decoration:line-through;background:#f3efe7}
.chip.solo .so{background:var(--gold);color:#fff}
details{margin-top:6px;font-size:14px}
#score{padding:6px 4px 60vh}
.page svg{width:100%;height:auto;display:block}
.playing,.playing *{fill:#c0392b!important;stroke:#c0392b!important}
.small{font-size:12px;color:#6b5a46}
</style></head><body>
<div id="bar">
  <div class="row">
    <button id="play" class="main" disabled>▶ Играть</button>
    <button id="stop" disabled>■</button>
    <span id="time">0:00 / 0:00</span>
    <input id="seek" type="range" min="0" max="1000" value="0" disabled>
  </div>
  <div class="row" style="margin-top:6px">
    <label class="small">Темп <select id="rate"><option value="0.5">×0,5</option><option value="0.75">×0,75</option>
      <option value="1" selected>×1</option><option value="1.25">×1,25</option></select></label>
    <label class="small"><input id="follow" type="checkbox" checked> листать за музыкой</label>
  </div>
  <div id="status">Нажмите «Играть»: загрузится банк звуков.</div>
  <div id="prog"><div></div></div>
  <div id="parts"></div>
</div>
<div id="score"><!--SVG--></div>
<script>
const D = /*DATA*/null;
const $ = id => document.getElementById(id);
const st = s => { $("status").textContent = s; };
const fmt = s => { s = Math.max(0, s || 0); return Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0"); };
const b64buf = b => { const s = atob(b), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u.buffer; };
const blobUrl = (b64, type) => URL.createObjectURL(new Blob([b64buf(b64)], {type}));
const P = { ctx: null, synth: null, seq: null, ready: false, loading: false, muted: new Set(), solo: null, bank: "" };
window.__player = P;

// ---------- инструменты ----------
function renderParts() {
  const box = $("parts"); box.innerHTML = "";
  D.parts.forEach((p, i) => {
    const c = document.createElement("div"); c.className = "chip";
    const nm = document.createElement("span"); nm.className = "nm"; nm.textContent = p.label;
    nm.title = "Нажмите, чтобы выключить или включить"; nm.onclick = () => { P.solo = null; toggle(i); };
    const so = document.createElement("span"); so.className = "so"; so.textContent = "соло";
    so.title = "Слушать только этот инструмент"; so.onclick = () => { P.solo = (P.solo === i ? null : i); apply(); };
    c.append(nm, so); box.append(c);
  });
  apply();
}
function toggle(i) { P.muted.has(i) ? P.muted.delete(i) : P.muted.add(i); apply(); }
function apply() {
  const chips = $("parts").children;
  const offCh = new Set(), onCh = new Set();
  D.parts.forEach((p, i) => {
    const off = P.solo !== null ? P.solo !== i : P.muted.has(i);
    chips[i].classList.toggle("off", off); chips[i].classList.toggle("solo", P.solo === i);
    p.channels.forEach(ch => (off ? offCh : onCh).add(ch));
  });
  if (!P.synth) return;
  for (let ch = 0; ch < 16; ch++) {
    const mute = offCh.has(ch) && !onCh.has(ch);     // канал общий у двух дорожек: выключаем, только если выключены обе
    const c = P.synth.midiChannels && P.synth.midiChannels[ch];
    try { if (c) c.setSystemParameter("isMuted", mute); } catch (e) {}
  }
}

// ---------- банк звуков: память браузера ----------
function idb() { return new Promise((ok, bad) => { const r = indexedDB.open("orkestrator_player", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("banks"); r.onsuccess = () => ok(r.result); r.onerror = () => bad(r.error); }); }
async function idbGet(k) { try { const db = await idb(); return await new Promise(ok => { const q = db.transaction("banks").objectStore("banks").get(k); q.onsuccess = () => ok(q.result); q.onerror = () => ok(null); }); } catch (e) { return null; } }
async function idbPut(k, v) { try { const db = await idb(); await new Promise(ok => { const t = db.transaction("banks", "readwrite"); t.objectStore("banks").put(v, k); t.oncomplete = ok; t.onerror = ok; }); } catch (e) {} }
async function idbDel(k) { try { const db = await idb(); await new Promise(ok => { const t = db.transaction("banks", "readwrite"); t.objectStore("banks").delete(k); t.oncomplete = ok; t.onerror = ok; }); } catch (e) {} }

async function download(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error("сервер ответил " + r.status);
  const total = +r.headers.get("content-length") || 0, rd = r.body.getReader(), chunks = []; let got = 0;
  $("prog").style.display = "block";
  for (;;) { const {done, value} = await rd.read(); if (done) break; chunks.push(value); got += value.length;
    st("Загружаю банк звуков: " + (got / 1048576).toFixed(1) + (total ? " из " + (total / 1048576).toFixed(0) : "") + " МБ (один раз, потом он хранится в телефоне)");
    if (total) $("prog").firstChild.style.width = (100 * got / total).toFixed(1) + "%"; }
  $("prog").style.display = "none";
  const out = new Uint8Array(got); let o = 0; for (const c of chunks) { out.set(c, o); o += c.length; } return out.buffer;
}
async function getBank() {
  const own = await idbGet("own");
  if (own && own.data) { P.bank = "свой: " + own.name; return own.data; }
  const def = await idbGet("default:" + D.bankUrl);
  if (def) { P.bank = D.bankName; return def; }
  const buf = await download(D.bankUrl);
  await idbPut("default:" + D.bankUrl, buf);
  P.bank = D.bankName; return buf;
}

// ---------- запуск ----------
async function start() {
  if (P.ready || P.loading) return; P.loading = true; $("play").disabled = true;
  try {
    P.ctx = new (window.AudioContext || window.webkitAudioContext)();
    await P.ctx.resume();
    st("Запускаю синтезатор…");
    await new Promise((ok, bad) => { const s = document.createElement("script"); s.src = blobUrl("LIB_B64", "text/javascript"); s.onload = ok; s.onerror = () => bad(new Error("движок не загрузился")); document.head.append(s); });
    await P.ctx.audioWorklet.addModule(blobUrl("PROC_B64", "text/javascript"));
    const bank = await getBank();
    st("Читаю банк звуков…");
    P.synth = new Spessa.WorkletSynthesizer(P.ctx);
    P.synth.connect(P.ctx.destination);
    await P.synth.soundBankManager.addSoundBank(bank, "main");
    await P.synth.isReady;
    P.seq = new Spessa.Sequencer(P.synth);
    P.seq.loadNewSongList([{ binary: b64buf(D.midi), fileName: D.name }]);
    P.seq.playbackRate = +$("rate").value;
    P.ready = true; apply();
    st("Готово. Банк: " + P.bank + ".");
    ["play", "stop", "seek"].forEach(id => $(id).disabled = false);
    requestAnimationFrame(tick);
  } catch (e) {
    st("Не получилось запустить звук: " + (e && e.message ? e.message : e)); $("play").disabled = false;
  } finally { P.loading = false; }
}

$("play").onclick = async () => {
  if (!P.ready) { await start(); if (!P.ready) return; }
  await P.ctx.resume();
  if (P.seq.paused) { P.seq.play(); } else { P.seq.pause(); }
  setTimeout(() => apply(), 50);
};
$("stop").onclick = () => { if (!P.seq) return; P.seq.pause(); P.seq.currentTime = 0; resetCursor(); };
$("seek").oninput = () => { if (!P.seq) return; P.seq.currentTime = $("seek").value / 1000 * D.length; resetCursor(); };
$("rate").onchange = () => { if (P.seq) P.seq.playbackRate = +$("rate").value; };
// ---------- указатель по нотам ----------
const TM = D.timemap; let idx = -1, active = new Set(), lastScroll = 0;
function secToQ(sec) {
  const t = D.tempo; let k = 0; while (k + 1 < t.length && t[k + 1][0] <= sec) k++;
  return t[k][1] + (sec - t[k][0]) / t[k][2];
}
function mark(id, on) { const el = document.getElementById(id); if (el) el.classList.toggle("playing", on); }
function resetCursor() { active.forEach(id => mark(id, false)); active.clear(); idx = -1; }
function tick() {
  if (P.seq) {
    const sec = P.seq.currentHighResolutionTime || P.seq.currentTime || 0;
    $("time").textContent = fmt(sec) + " / " + fmt(D.length);
    $("play").textContent = P.seq.paused ? "▶ Играть" : "⏸ Пауза";
    if (!P.seq.paused) $("seek").value = Math.round(1000 * sec / Math.max(D.length, 1));
    const q = secToQ(sec) + 1e-6;
    if (idx >= 0 && idx < TM.length && TM[idx].q > q) resetCursor();     // перемотка назад
    let moved = false;
    while (idx + 1 < TM.length && TM[idx + 1].q <= q) {
      idx++; moved = true;
      for (const id of TM[idx].off || []) { active.delete(id); mark(id, false); }
      for (const id of TM[idx].on || []) { active.add(id); mark(id, true); }
    }
    if (moved && $("follow").checked && !P.seq.paused && Date.now() - lastScroll > 700) {
      const first = active.values().next().value, el = first && document.getElementById(first);
      if (el) { const r = el.getBoundingClientRect(), top = $("bar").getBoundingClientRect().bottom;
        if (r.top < top + 10 || r.bottom > innerHeight - 40) { window.scrollBy({ top: r.top - top - innerHeight * 0.25, behavior: "smooth" }); lastScroll = Date.now(); } }
    }
    if (P.seq.isFinished && !P.seq.paused) { P.seq.pause(); }
  }
  requestAnimationFrame(tick);
}

renderParts();
$("time").textContent = "0:00 / " + fmt(D.length);
$("play").disabled = false;
if (D.notes && D.notes.length) $("status").textContent += " " + D.notes.join(" ");
</script></body></html>"""


BANK_PANEL = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;font-family:Georgia,"Times New Roman",serif;color:#2a1c12;background:transparent}
.box{border:1px solid #b8892b;border-radius:10px;background:#fffdf7;padding:10px 12px}
.t{font-weight:bold;font-size:15px}
.s{font-size:14px;margin:6px 0;color:#2a1c12}
.small{font-size:12px;color:#6b5a46}
button{font:inherit;font-size:15px;border:1px solid #b8892b;background:#fff;border-radius:8px;padding:7px 11px;color:#2a1c12;margin-right:6px}
</style></head><body>
<div class="box">
  <div class="t">Банк звуков</div>
  <div class="s" id="cur">проверяю…</div>
  <button type="button" id="pick">Выбрать свой банк (.sf2, .sf3, .dls)</button><button type="button" id="def">Вернуть по умолчанию</button>
  <input id="file" type="file" accept=".sf2,.sf3,.dls,.sf" style="display:none">
  <div class="small" id="msg">Банк запоминается в этом браузере. Выберите его до открытия нот: звук пойдёт этим банком. Если нот уже открыты, обновите страницу.</div>
</div>
<script>
const DEFAULT_NAME = "__BANK_NAME__";
const $ = id => document.getElementById(id);
function idb() { return new Promise((ok, bad) => { const r = indexedDB.open("orkestrator_player", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("banks"); r.onsuccess = () => ok(r.result); r.onerror = () => bad(r.error); }); }
async function idbGet(k) { try { const db = await idb(); return await new Promise(ok => { const q = db.transaction("banks").objectStore("banks").get(k); q.onsuccess = () => ok(q.result); q.onerror = () => ok(null); }); } catch (e) { return null; } }
async function idbPut(k, v) { const db = await idb(); await new Promise((ok, bad) => { const t = db.transaction("banks", "readwrite"); t.objectStore("banks").put(v, k); t.oncomplete = ok; t.onerror = () => bad(t.error); }); }
async function idbDel(k) { try { const db = await idb(); await new Promise(ok => { const t = db.transaction("banks", "readwrite"); t.objectStore("banks").delete(k); t.oncomplete = ok; t.onerror = ok; }); } catch (e) {} }
async function show() {
  let own = null; try { own = await idbGet("own"); } catch (e) {}
  $("cur").textContent = own && own.name ? "Сейчас: свой банк «" + own.name + "»"
                                        : "Сейчас: " + DEFAULT_NAME + " (по умолчанию, около 50 МБ, грузится при первом «Играть»)";
}
$("pick").onclick = () => $("file").click();
$("file").onchange = async ev => {
  const f = ev.target.files[0]; if (!f) return;
  $("msg").textContent = "Сохраняю банк «" + f.name + "» (" + (f.size / 1048576).toFixed(0) + " МБ)…";
  try { await idbPut("own", { name: f.name, data: await f.arrayBuffer() }); await show();
    $("msg").textContent = "Готово. Теперь откройте ноты: звук пойдёт этим банком. Если ноты уже открыты, обновите страницу.";
  } catch (e) { $("msg").textContent = "Не удалось сохранить банк: " + (e && e.message ? e.message : e) + ". Попробуйте банк поменьше."; }
};
$("def").onclick = async () => { await idbDel("own"); await show(); $("msg").textContent = "Вернул банк по умолчанию. Обновите страницу, если ноты уже открыты."; };
show();
</script></body></html>"""


def bank_panel():
    """Панель выбора банка: показывается над загрузкой файла, работает без нот (2026-11-08)."""
    return BANK_PANEL.replace("__BANK_NAME__", DEFAULT_BANK_NAME)
