"""
Запись мелодии с микрофона (2026-11-08, этап 1). Компонент web/mic_recorder/index.html записывает и распознаёт
мелодию в браузере и присылает ноты; здесь из них делается MIDI (src/melody_midi.py).
Возвращает объект как у загрузки (.name, .size, .getvalue(), .ts) или None.
"""
import os
import time

import streamlit as st
import streamlit.components.v1 as components

import melody_midi

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mic_recorder")
_component = components.declare_component("mic_recorder", path=_DIR)


class Sung:
    def __init__(self, name, data, info):
        self.name, self._data, self.size, self.info, self.ts = name, data, len(data), info, time.time()

    def getvalue(self):
        return self._data


def record(key="mic"):
    store = "_sung_" + key
    cur = st.session_state.get(store)
    v = _component(done=cur.nonce if cur else None, key=key, default=None)
    if v and (cur is None or cur.nonce != v.get("nonce")):
        try:
            data, info = melody_midi.notes_to_midi(v.get("notes") or [], v.get("tempo", 80), v.get("grid", "восьмые"),
                                                   v.get("octave", "авто"), poly=bool(v.get("poly")))
        except Exception as e:
            st.error("Мелодию не удалось записать в MIDI: %s" % e)
            return cur
        cur = Sung("Напетая_мелодия_%s.mid" % time.strftime("%H-%M"), data, info)
        cur.nonce = v.get("nonce")
        st.session_state[store] = cur
        st.session_state["sung_midi"] = cur            # для страницы проигрывателя
        st.rerun()                                     # сообщаем браузеру «получено»
    if cur is not None:
        i = cur.info
        if i.get("poly"):
            st.caption("🎤 Записанная музыка: %d нот (в том числе одновременные), ритм — %s, сдвиг %+d окт."
                       % (i["notes"], i["grid"], i["octave_shift"]))
        else:
            st.caption("🎤 Напетая мелодия: %d нот, темп %d, ритм — %s, сдвиг %+d окт. Это одна строчка без аккордов: "
                       "оркестр сыграет её почти в унисон (аккорды и бас — следующий этап)."
                       % (i["notes"], i["tempo"], i["grid"], i["octave_shift"]))
        st.download_button("⬇ Скачать напетую мелодию (MIDI)", cur.getvalue(), file_name=cur.name,
                           mime="audio/midi", key=key + "_dl")
    return cur
