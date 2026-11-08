"""
Своя кнопка выбора файла (2026-11-08, версия 2).
Штатная загрузка Streamlit (st.file_uploader) на Streamlit Community Cloud с телефона то срабатывала, то молча
отказывала. Здесь файл читается в браузере и передаётся программе частями по веб-сокету (канал всех нажатий).
Сервер подтверждает каждую часть (аргумент `ack` компонента); браузер пишет «Программа получила» только после
подтверждения и сам повторяет отправку, если подтверждения нет (в том числе после перезапуска сервера).
Возвращает объект как у штатной загрузки (.name, .size, .getvalue()) или None.
"""
import base64
import os
import time

import streamlit as st
import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_picker")
_component = components.declare_component("file_picker", path=_DIR)
SERVER_STARTED = time.time()          # когда запущен процесс сервера (для диагностики перезапусков)


class Picked:
    def __init__(self, name, data):
        self.name, self._data, self.size, self.ts = name, data, len(data), time.time()

    def getvalue(self):
        return self._data


def _log(key, text):
    lg = st.session_state.setdefault("_picker_log", [])
    lg.append("%s  [%s] %s" % (time.strftime("%H:%M:%S"), key, text))
    del lg[:-30]


def pick(label, key, max_mb=5):
    """Файл, выбранный своей кнопкой, или None (пока файл не выбран или ещё передаётся)."""
    done_key, parts_key = "_picked_" + key, "_parts_" + key
    cur = st.session_state.get(done_key)
    parts = st.session_state.get(parts_key) or {}
    got = parts.get("got", {})
    nxt = next((i for i in range(parts.get("total", 0)) if i not in got), None)
    ack = {"done": cur.nonce if cur else None, "nonce": parts.get("nonce"), "next": nxt}
    v = _component(label=label, max_mb=max_mb, current=cur.name if cur else None, ack=ack, key=key, default=None)
    if not v:
        if cur is not None:
            _log(key, "файл убран")
        st.session_state.pop(done_key, None)
        st.session_state.pop(parts_key, None)
        return None
    nonce = v.get("nonce")
    if cur is not None and cur.nonce == nonce:
        return cur
    # новая часть
    idx, total = int(v.get("idx", 0)), int(v.get("total", 1))
    if parts.get("nonce") != nonce:
        parts = {"nonce": nonce, "total": total, "got": {}}
    added = idx not in parts["got"]
    if added:
        parts["got"][idx] = v.get("part") or ""
        _log(key, "получена часть %d из %d файла «%s»" % (idx + 1, total, v.get("name")))
    st.session_state[parts_key] = parts
    if len(parts["got"]) < total:
        if added:
            st.rerun()                 # подтверждаем часть (новый ack) — браузер пришлёт следующую
        return None
    try:
        data = base64.b64decode("".join(parts["got"][i] for i in range(total)))
    except Exception as e:
        _log(key, "ошибка сборки: %s" % e)
        st.session_state.pop(parts_key, None)
        st.error("Файл «%s» пришёл повреждённым при передаче. Выберите его ещё раз." % v.get("name"))
        return None
    if v.get("size") is not None and len(data) != v["size"]:
        _log(key, "длина не совпала: %d из %d" % (len(data), v["size"]))
        st.session_state.pop(parts_key, None)
        st.error("Файл «%s» пришёл не полностью (%d из %d байт). Выберите его ещё раз."
                 % (v.get("name"), len(data), v["size"]))
        return None
    cur = Picked(v.get("name") or "file", data)
    cur.nonce = nonce
    st.session_state[done_key] = cur
    st.session_state.pop(parts_key, None)
    _log(key, "файл «%s» собран: %d байт" % (cur.name, len(data)))
    st.rerun()                         # сообщаем браузеру «получено» и продолжаем с готовым файлом


def diagnostics():
    """Раздел «Диагностика загрузки»: когда запущен сервер, память, что приходило от кнопки."""
    with st.expander("Диагностика загрузки (если файл не принимается — пришлите снимок этого раздела)"):
        up = time.time() - SERVER_STARTED
        st.write("Сервер запущен: %s (%d мин назад)." % (time.strftime("%H:%M:%S", time.localtime(SERVER_STARTED)), up // 60))
        try:
            import resources
            snap = resources.snapshot()
            st.write("Память сервера сейчас: %s МБ; пик программы %s МБ, пик дочерних (синтез звука) %s МБ."
                     % (snap.get("rss_mb"), snap.get("peak_main_mb"), snap.get("peak_child_mb")))
        except Exception as e:
            st.write("Память: не удалось узнать (%s)." % e)
        lg = st.session_state.get("_picker_log") or []
        st.code("\n".join(lg) if lg else "От кнопки выбора файла пока ничего не приходило.")
