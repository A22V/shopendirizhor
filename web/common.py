"""Общее для страниц приложения (главная, анализ, проигрыватель): пути, секреты, приём файла.
Импортировать ПЕРВЫМ: секреты Streamlit становятся переменными окружения до импорта модулей из src
(ORCH_RANGES / ORCH_COMFORT читаются при импорте)."""
import os, sys
import streamlit as st

WEB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(WEB)
for _p in (os.path.join(ROOT, "src"), WEB):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    for _k, _v in st.secrets.items():          # keys from Streamlit "Secrets" become environment variables
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

import midi_repair   # noqa: E402
import picker        # noqa: E402  своя кнопка выбора файла (веб-сокет вместо канала загрузки)
import theme         # noqa: E402


def decorate(title=None, motto=""):
    """Барочное оформление страницы (одна тёмно-синяя стена). title=None — главная страница с лирой."""
    st.markdown(theme.CSS(), unsafe_allow_html=True)
    first = not st.session_state.get("bq_opened")       # занавес раздвигается только при первом входе
    st.session_state["bq_opened"] = True
    st.markdown(theme.DECOR_TOP(curtain_open=first and title is None), unsafe_allow_html=True)
    st.markdown(theme.TITLE() if title is None else theme.PAGE_TITLE(title, motto), unsafe_allow_html=True)


def nav(here):
    """Ссылки между страницами в этой же вкладке. Оркестровка этой сессии (номер задания в session_state)
    открывается и в проигрывателе, и в анализе без лишних действий."""
    links = [("app.py", "Главная", "🏛"), ("pages/1_Проигрыватель.py", "Проигрыватель", "🎼"),
             ("pages/2_Анализ.py", "Анализ и проверки", "🔎"), ("pages/3_Генератор.py", "Генератор", "✒️")]
    links = [x for x in links if x[1] != here]
    cols = st.columns(len(links))
    for c, (path, label, icon) in zip(cols, links):
        with c:
            st.page_link(path, label=label, icon=icon, use_container_width=True)


class _Upload:
    """Проверенный MIDI: имя всегда с .mid, содержимое — чистый MIDI (как у объекта загрузки Streamlit)."""
    def __init__(self, name, data):
        self.name, self._data, self.size = name, data, len(data)

    def getvalue(self):
        return self._data


MIDI_EXTS = (".mid", ".midi", ".kar", ".rmi", ".smf", ".bin", ".dat", ".tmp", ".musicxml", ".xml", ".mxl", ".zip")


def midi_bytes(data: bytes):
    """Содержимое MIDI или None. MIDI узнаём по признаку «MThd» внутри файла, а не по имени: телефон (Telegram,
    WhatsApp, Google Диск, «Загрузки» на Android) часто отдаёт файл без окончания .mid или с другим окончанием.
    RIFF-MIDI (.rmi) и файлы с небольшим служебным заголовком перед MIDI тоже принимаются."""
    if data[:4] == b"MThd":
        return data
    i = data.find(b"MThd", 0, 512)
    if i > 0 and (data[:4] == b"RIFF" or i <= 256):
        return data[i:]
    return None


def checked_midi(f, what="Файл"):
    """Принятый MIDI или None. С 2026-11-08 каждый файл проходит ремонт (src/midi_repair.py): нестандартные и
    повреждённые MIDI с сайтов и из мессенджеров переписываются в чистый стандартный MIDI; ноты не меняются."""
    if f is None:
        return None
    name = f.name or "пьеса"
    try:
        midi, fixes = midi_repair.repair(f.getvalue(), name)
    except midi_repair.MidiRepairError as e:
        st.error("%s «%s» не открылся: %s." % (what, name, e))
        return None
    except Exception as e:                 # неожиданное: показываем причину, а не молчим
        st.error("%s «%s» не открылся из-за ошибки программы: %s: %s. Пришлите файл разработчику."
                 % (what, name, type(e).__name__, e))
        return None
    stem, ext = os.path.splitext(name)
    if ext.lower() not in MIDI_EXTS:
        stem = name                    # «Прелюдия» или «document_1234»: окончания нет, имя оставляем целиком
    if fixes:
        st.caption("✔ " + midi_repair.text(fixes))
    elif not name.lower().endswith((".mid", ".midi")):
        st.caption("Имя «%s» без окончания .mid, но внутри MIDI: файл принят." % name)
    return _Upload(stem + ".mid", midi)


def any_file(label, key, diagnostics=False):
    """Файл из своей кнопки (основной путь) или из штатной загрузки Streamlit (запасной путь).
    Запасная кнопка и диагностика — в одном свёрнутом разделе, чтобы не загромождать страницу."""
    key = "%s_%d" % (key, st.session_state.get("reset_n", 0))      # после «Начать заново» кнопки создаются заново, пустыми
    f = picker.pick(label, key)
    with st.expander("Если файл не загружается"):
        g = st.file_uploader("Запасная кнопка (обычная загрузка Streamlit)", accept_multiple_files=False, key=key + "_native")
        if diagnostics:
            picker.diagnostics(box=True)
    return f or g
