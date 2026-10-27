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
<b>Что делает эта программа.</b> Вы загружаете сольную фортепианную пьесу в формате MIDI.
Программа разбирает её на фразы и раскладывает по инструментам камерного состава:
флейта, гобой, кларнет, фагот, валторна, скрипки, альт, виолончель, контрабас.
На выходе — MIDI с отдельной дорожкой на каждый инструмент, нотный файл (MusicXML) и запись для прослушивания.
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

st.markdown("### 2. Оркестровать")
go = st.button("Создать оркестровку", disabled=up is None, use_container_width=True)


def process(data: bytes, name: str):
    """Runs the full pipeline in a private temporary folder and returns the list of result files."""
    work = tempfile.mkdtemp(prefix="shopendirizhor_")
    src = os.path.join(work, "input.mid")
    with open(src, "wb") as f:
        f.write(data)
    stem = os.path.join(work, "result")
    log, issues, names = orchestrator.run(src, stem, "off", None)
    plan = json.load(open(stem + "_plan.json", encoding="utf-8"))
    report = json.load(open(stem + "_report.json", encoding="utf-8"))
    mp3 = None
    try:
        out = audio_tools.render_mp3(stem + ".mid", stem + ".mp3")
        mp3 = out if os.path.exists(out) else None
    except Exception:
        mp3 = None
    return {"work": work, "stem": stem, "plan": plan, "report": report, "issues": issues,
            "mp3": mp3, "name": os.path.splitext(name)[0]}


if go and up is not None:
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ. Пожалуйста, загрузите более короткую пьесу.")
    else:
        with st.spinner("Оркестровка выполняется. Обычно это занимает меньше минуты..."):
            try:
                st.session_state.result = process(up.getvalue(), up.name)
            except Exception as e:
                st.session_state.result = None
                st.error("Не удалось обработать файл. Проверьте, что это сольная фортепианная пьеса в MIDI с ровным ритмом.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())

res = st.session_state.result
if res:
    st.markdown("### 3. Результат")
    if res["mp3"]:
        st.audio(res["mp3"], format="audio/mpeg")
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в программе для музыки.")

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
