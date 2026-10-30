"""
Шопендирижёр: веб-оболочка (Streamlit).
Запуск локально:  streamlit run web/app.py
Размещение в облаке: см. docs/DEPLOY.md
"""
import os, sys, io, json, tempfile, zipfile, shutil, traceback
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import orchestrator          # noqa: E402
import validator             # noqa: E402
import audio_tools           # noqa: E402
import llm_planner           # noqa: E402
import reduction             # noqa: E402

try:
    for _k, _v in st.secrets.items():          # keys from Streamlit "Secrets" become environment variables
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass
PROVIDER, PROVIDER_KEY, PROVIDER_MODEL = llm_planner.configured_provider()
LLM_READY = bool(PROVIDER and PROVIDER_KEY and PROVIDER_MODEL)

st.set_page_config(page_title="Шопендирижёр", page_icon="🎼", layout="centered")

BAROQUE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,700;1,500&family=IM+Fell+English&display=swap');
:root { --gold:#b8860b; --gold-soft:#d4af37; --wine:#5b1a22; --parchment:#f6efe0; --ink:#2b1d14; }
html, body, [class*="css"] { font-family: 'Cormorant Garamond', 'Georgia', serif; color: var(--ink); }
.stApp { background: radial-gradient(circle at top, #fbf6ea 0%, var(--parchment) 60%, #ead9b5 100%); }
h1, h2, h3 { font-family: 'IM Fell English', 'Cormorant Garamond', serif !important; color: var(--wine); letter-spacing: .5px; }
h1 { border-bottom: 2px double var(--gold); padding-bottom: .3rem; text-align: center; }
.frame { border: 3px double var(--gold); border-radius: 6px; padding: 1.1rem 1.4rem; background: rgba(255,250,240,.7);
         box-shadow: inset 0 0 0 4px rgba(184,134,11,.12); margin-bottom: 1rem; }
.motto { text-align:center; font-style: italic; color: #6b4a1e; margin-top: -.6rem; }
.stButton > button, .stDownloadButton > button {
  background: linear-gradient(#7a2631, var(--wine)); color: #fff6df; border: 1px solid var(--gold);
  font-family: 'Cormorant Garamond', serif; font-size: 1.05rem; letter-spacing: .4px; border-radius: 4px; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--gold-soft); color: #fff; }
.warn { border-left: 4px solid var(--gold); padding: .4rem .8rem; background: rgba(184,134,11,.08); }
</style>
"""
st.markdown(BAROQUE_CSS, unsafe_allow_html=True)

st.markdown("<h1>Шопендирижёр</h1>", unsafe_allow_html=True)
st.markdown("<p class='motto'>Фортепианная пьеса — оркестровый наряд</p>", unsafe_allow_html=True)

st.markdown("""<div class='frame'>
<b>Оркестровка.</b> Загрузите сольную фортепианную пьесу в формате MIDI. Программа разберёт её на фразы и распределит по инструментам камерного состава: флейта, гобой, кларнет, фагот, валторна, скрипки, альт, виолончель, контрабас. На выходе: MIDI с дорожкой на каждый инструмент, нотный файл MusicXML и запись для прослушивания.<br><br>
<b>Переложение для фортепиано.</b> Загрузите оркестровую пьесу в формате MIDI. Программа сведёт все голоса к фортепиано: правая и левая руки, ограниченное число нот в аккорде. На выходе: фортепианный MIDI и запись для прослушивания.
</div>""", unsafe_allow_html=True)

st.markdown("""<div class='frame warn'>
<b>Честно о результате.</b> Оркестровка строится по правилам, которые взяты из книги Римского-Корсакова
и дополнены эвристиками. Она проверяется автоматически, но <i>не является профессиональной аранжировкой</i>.
Звук в записи для прослушивания синтезированный и проще живого оркестра. Пожалуйста, оценивайте результат как прототип.
</div>""", unsafe_allow_html=True)

with st.expander("Ограничения и приватность", expanded=False):
    st.markdown("""
- Загружайте только свои пьесы или пьесы, права на которые у вас есть. Загруженные файлы хранятся только на время обработки и удаляются после неё.
- Максимальный размер файла — 2 МБ (около 2000 нот).
- Программа не умеет превращать запись живой игры (mp3/wav) в MIDI: нужен MIDI с ровным, квантованным ритмом.
- Пьесы короче 3 тактов и длиннее 100 тактов дают неудовлетворительный результат.
""")

if "result" not in st.session_state:
    st.session_state.result = None

st.markdown("### 1. Загрузите пьесу")
up = st.file_uploader("MIDI-файл (.mid, .midi)", type=["mid", "midi"], accept_multiple_files=False)

st.markdown("### 2. Что сделать")
use_llm = False
if LLM_READY:
    use_llm = st.checkbox("Помощь модели (%s): план оркестровки или выбор голосов при переложении" % PROVIDER, value=True,
                          help="Модель пишет план по смыслу фраз, программа проверяет его.")
mode = st.radio("Что сделать", ["Оркестровка (из фортепиано)", "Переложение для фортепиано (из оркестра)"], horizontal=True)
go = st.button("Создать оркестровку" if mode == "Оркестровка (из фортепиано)" else "Создать переложение", disabled=up is None, use_container_width=True)


def process(data: bytes, name: str, use_llm_flag: bool = False):
    """Runs the full pipeline in a private temporary folder and returns the list of result files."""
    work = tempfile.mkdtemp(prefix="shopendirizhor_")
    src = os.path.join(work, "input.mid")
    with open(src, "wb") as f:
        f.write(data)
    stem = os.path.join(work, "result")
    llm_log = None
    if use_llm_flag:
        log, issues, names, llm_log, _pp = llm_planner.orchestrate_with_llm(
            src, stem, PROVIDER, PROVIDER_MODEL, PROVIDER_KEY)
        plan = json.load(open(_pp, encoding="utf-8"))
    else:
        log, issues, names = orchestrator.run(src, stem, "off", None)
        plan = json.load(open(stem + "_plan.json", encoding="utf-8"))
    report = json.load(open(stem + "_report.json", encoding="utf-8"))
    mp3 = None
    try:
        out = audio_tools.render_mp3(stem + ".mid", stem + ".mp3")
        mp3 = out if os.path.exists(out) else None
    except Exception:
        mp3 = None
    return {"work": work, "stem": stem, "plan": plan, "report": report, "issues": issues, "llm_log": llm_log,
            "mp3": mp3, "name": os.path.splitext(name)[0]}


if go and up is not None and mode == "Переложение для фортепиано (из оркестра)":
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ.")
    else:
        with st.spinner("Делаю редукцию..."):
            try:
                _work = tempfile.mkdtemp(prefix="reduction_")
                _src = os.path.join(_work, "orchestra.mid")
                with open(_src, "wb") as _f:
                    _f.write(up.getvalue())
                _out = os.path.join(_work, "piano_reduction.mid")
                if use_llm:
                    _stats = llm_planner.reduction_with_model(PROVIDER, PROVIDER_MODEL, PROVIDER_KEY, _src, _out)[0]
                else:
                    _stats = reduction.reduce_to_piano(_src, _out)
                _mp3 = os.path.join(_work, "piano_reduction.mp3")
                try:
                    _mp3 = audio_tools.render_mp3(_out, _mp3)
                except Exception:
                    _mp3 = None
                st.session_state.result = {"mode": "reduction", "stats": _stats, "midi": _out,
                                           "mp3": _mp3 if _mp3 and os.path.exists(_mp3) else None,
                                           "name": os.path.splitext(up.name)[0]}
            except Exception:
                st.session_state.result = None
                st.error("Не удалось сделать редукцию. Проверьте, что это MIDI-файл оркестровки.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None:
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ. Пожалуйста, загрузите более короткую пьесу.")
    else:
        with st.spinner("Оркестровка выполняется. Обычно это занимает меньше минуты..."):
            try:
                st.session_state.result = process(up.getvalue(), up.name, use_llm_flag=use_llm)
            except Exception as e:
                st.session_state.result = None
                st.error("Не удалось обработать файл. Проверьте, что это сольная фортепианная пьеса в MIDI с ровным ритмом.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())

res = st.session_state.result
if res and res.get("mode") == "reduction":
    st.markdown("### 3. Результат переложения")
    s = res["stats"]
    st.info("Оригинал: %d нот. Фортепиано: правая рука %d, левая %d. "
            "Сохранено высот гармонии: %.0f%%; в %.0f%% моментов звучат все высоты аккорда."
            % (s["notes_in"], s["notes_rh"], s["notes_lh"], 100 * s["pitch_class_coverage"], 100 * s["full_coverage_share"]))
    st.caption("Переложение механическое: внутренние голоса в плотных местах удаляются. Это не фортепианная переработка.")
    if res["mp3"]:
        st.audio(res["mp3"], format="audio/mpeg")
    st.download_button("Скачать переложение (MIDI)", open(res["midi"], "rb").read(),
                       file_name=res["name"] + "_piano.mid", mime="audio/midi", use_container_width=True)
    res = None
if res:
    st.markdown("### 3. Результат")
    if res["mp3"]:
        st.audio(res["mp3"], format="audio/mpeg")
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в программе для музыки.")

    if res.get("llm_log"):
        st.info("План написала модель %s. Проверок плана: %d." % (PROVIDER, len(res["llm_log"])))
    issues = res["issues"]
    errors = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warning"]
    if errors:
        st.error("Найдены серьёзные ошибки: %d. Результат не рекомендуется использовать." % len(errors))
    elif warns:
        st.warning("Проверка пройдена с замечаниями (%d). Они описаны ниже." % len(warns))
    else:
        st.success("Проверка пройдена без замечаний.")

    st.markdown("#### Фразы и состав")
    rows = []
    for ph in res["plan"]["phrases"]:
        rows.append({"Такты": "%d–%d" % tuple(ph["bars"]), "Тип": ph["kind"],
                     "Окраска мелодии": ph.get("color") or "—", "Громкость": ph["level"],
                     "Кульминация": "да" if ph["climax"] else ""})
    st.table(rows)

    with st.expander("Замечания проверки"):
        if not issues:
            st.write("Замечаний нет.")
        for sev, rid, _, msg in issues:
            st.write("**%s** %s: %s" % ("Ошибка" if sev == "error" else "Замечание", rid, msg))

    st.markdown("#### Скачать")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ext in (".mid", ".musicxml", "_plan.json", "_report.json"):
            p = res["stem"] + ext
            if os.path.exists(p):
                z.write(p, res["name"] + os.path.basename(p)[len("result"):] if ext.startswith("_") else res["name"] + ext)
    st.download_button("Скачать всё (ZIP)", buf.getvalue(), file_name=res["name"] + "_оркестровка.zip",
                       mime="application/zip", use_container_width=True)
    if res["mp3"]:
        st.download_button("Скачать запись (MP3)", open(res["mp3"], "rb").read(), file_name=res["name"] + ".mp3",
                           mime="audio/mpeg", use_container_width=True)

    st.caption("Нажимая «Создать оркестровку», вы подтверждаете, что имеете право обработать этот файл.")
