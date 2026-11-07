"""
Партитурный проигрыватель (2026-11-08): отдельная страница программы.
Открывает многодорожечный MIDI или MusicXML, раскладывает инструменты по станам в порядке партитуры и играет
в браузере банком звуков MS Basic (или своим банком с телефона). Можно выключать инструменты и слушать один.
Подготовка нот: src/score_player.py; страница со звуком: web/player_html.py.
"""
import os, sys
import streamlit as st
import streamlit.components.v1 as components

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(WEB)
for p in (os.path.join(ROOT, "src"), WEB):
    if p not in sys.path:
        sys.path.insert(0, p)
import score_player, player_html, jobs   # noqa: E402

st.set_page_config(page_title="Проигрыватель партитуры", page_icon="🎼", layout="wide")
st.markdown("""<style>
.stApp{background:#fcf8ef} h1{font-family:Georgia,serif;color:#8e1426;font-size:1.7rem}
.block-container{padding-top:1.2rem;padding-left:.6rem;padding-right:.6rem;max-width:1200px}
</style>""", unsafe_allow_html=True)
st.markdown("# 🎼 Партитурный проигрыватель")
st.caption("Каждый инструмент на своём стане, звук считается прямо в вашем браузере. "
           "Нажмите на название инструмента, чтобы выключить его, «соло» — слушать только его.")
st.page_link("app.py", label="← Вернуться к оркестровке", icon="🏛")

MAX_MB = 5


@st.cache_data(max_entries=4, show_spinner=False)
def _prepare(data, name):
    return score_player.prepare(data, name)


def _from_job():
    """Оркестровка, открытая кнопкой из результата: номер задания в адресе (?job=…) или в этой же сессии."""
    try:
        k = st.query_params.get("job")
    except Exception:
        k = None
    k = k or st.session_state.get("job")
    if not k:
        return None
    try:
        res = jobs.load(k)
        path = os.path.join(res["work"], res["stem"] + ".mid")
        return open(path, "rb").read(), res["name"] + ".mid"
    except Exception:
        return None


# Банк звуков: выбирается до загрузки файла (хранится в браузере, см. web/player_html.py)
components.html(player_html.bank_panel(), height=170)

src = _from_job()
up = st.file_uploader("Открыть файл: многодорожечный MIDI (.mid) или MusicXML (.musicxml, .xml, .mxl)",
                      key="player_file")
if up is not None:
    data = up.getvalue()
    if len(data) > MAX_MB * 1024 * 1024:
        st.error("Файл больше %d МБ." % MAX_MB)
        st.stop()
    if not (data[:4] == b"MThd" or score_player.is_musicxml(data, up.name)):
        st.error("Это не MIDI и не MusicXML. Нужен файл .mid или .musicxml/.xml/.mxl.")
        st.stop()
    src = (data, up.name)
elif src:
    st.info("Открыта оркестровка «%s». Можно открыть и другой файл кнопкой выше." % src[1])

if not src:
    st.write("Загрузите файл, чтобы увидеть ноты и послушать.")
    st.stop()

try:
    with st.spinner("Готовлю ноты…"):
        prep = _prepare(*src)
except Exception as e:
    st.error("Не удалось открыть файл: %s" % e)
    with st.expander("Подробности"):
        import traceback
        st.code(traceback.format_exc())
    st.stop()

with st.expander("Как распознаны инструменты (%d)" % len(prep["parts"])):
    for p in prep["parts"]:
        st.write("• **%s** ← в файле «%s»" % (p["label"], p["source"] or "без названия"))
    st.caption("Инструмент узнаётся по названию дорожки, а если его нет — по номеру инструмента в файле. "
               "Если что-то распознано неверно, напишите, какая дорожка: поправлю таблицу.")
components.html(player_html.build(prep), height=1150, scrolling=True)
st.caption("Банк звуков по умолчанию — MS Basic (банк MuseScore 4, лицензия MIT): около 50 МБ, загружается "
           "один раз и хранится в браузере. Свой банк выбирается в окошке «Банк звуков» вверху страницы.")
