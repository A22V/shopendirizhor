"""
Своя кнопка выбора файла (2026-11-08).
Штатная загрузка Streamlit (st.file_uploader) отправляет файл отдельным HTTP-запросом; на Streamlit Community Cloud
с телефона она то срабатывала, то молча отказывала. Здесь файл читается в браузере и передаётся в программу по
веб-сокету — тому же каналу, по которому идут все нажатия кнопок. Возвращает объект как у штатной загрузки
(.name, .size, .getvalue()) или None.
"""
import base64
import os

import streamlit as st
import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_picker")
_component = components.declare_component("file_picker", path=_DIR)


class Picked:
    def __init__(self, name, data):
        self.name, self._data, self.size = name, data, len(data)

    def getvalue(self):
        return self._data


def pick(label, key, max_mb=5):
    """Файл, выбранный своей кнопкой, или None. Значение кнопки Streamlit хранит сам между нажатиями."""
    store = "_picked_" + key
    cur = st.session_state.get(store)
    v = _component(label=label, max_mb=max_mb, current=cur.name if cur else None, key=key, default=None)
    if not v:
        st.session_state.pop(store, None)
        return None
    if cur is None or getattr(cur, "nonce", None) != v.get("nonce"):
        try:
            data = base64.b64decode(v["b64"])
        except Exception:
            st.error("Файл «%s» пришёл повреждённым при передаче. Выберите его ещё раз." % v.get("name"))
            return None
        if v.get("size") is not None and len(data) != v["size"]:
            st.error("Файл «%s» пришёл не полностью (%d из %d байт). Выберите его ещё раз."
                     % (v.get("name"), len(data), v["size"]))
            return None
        cur = Picked(v.get("name") or "file", data)
        cur.nonce = v.get("nonce")
        st.session_state[store] = cur
    return cur
