"""
Страница «Анализ и проверки» (2026-11-21): всё, что программа проверяет и находит, отдельно от главной.
1) Разбор последней оркестровки этой сессии (или по номеру задания ?job=…).
2) Проверка готового оркестра (MIDI). 3) Проверка переложения для фортепиано.
Звук и ноты не меняет; кнопки «Исправить» делают НОВЫЙ файл.
"""
import os, sys
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common                 # noqa: E402  (первым: секреты → окружение)
import jobs, analysis_ui      # noqa: E402
import llm_planner            # noqa: E402

st.set_page_config(page_title="Анализ и проверки", page_icon="🔎", layout="centered")
common.decorate("Анализ", "что нашла программа и как это исправить")
common.nav("Анализ и проверки")


def _job():
    try:
        k = st.query_params.get("job")
    except Exception:
        k = None
    k = k if isinstance(k, str) and k else st.session_state.get("job")
    if not k:
        return None, None
    try:
        return k, jobs.load(k)
    except Exception:
        return k, None


_jk, _res = _job()
MINE, ORCH, PIANO = "Моя последняя оркестровка", "Проверить готовый оркестр (MIDI)", "Проверить переложение для фортепиано"
_opts = ([MINE] if _res else []) + [ORCH, PIANO]
what = st.radio("Что разобрать", _opts, key="an_what", horizontal=False)

if what == MINE:
    analysis_ui.show_orch_details(_res, llm_planner.configured_provider()[0])
else:
    if _jk and not _res:
        st.caption("Последняя оркестровка уже не хранится на сервере (прошло больше 6 часов или сервер перезапускался).")
    up = common.checked_midi(common.any_file("Файл: MIDI или MusicXML, до 5 МБ", "an_" + ("orch" if what == ORCH else "piano")))
    orig = None
    if what == PIANO:
        st.caption("По желанию добавьте оркестровый оригинал: тогда программа посчитает, сколько гармонии сохранилось.")
        orig = common.checked_midi(common.any_file("Оркестровый оригинал (необязательно)", "an_orig"), "Оригинал")
    if st.button("Проверить", disabled=up is None, use_container_width=True, key="an_go"):
        st.session_state["an_res"] = (analysis_ui.run_score_review(up) if what == ORCH else analysis_ui.run_piano_review(up, orig))
    r = st.session_state.get("an_res")
    if r and r.get("mode") == ("review" if what == ORCH else "piano_review"):
        (analysis_ui.show_score_review if what == ORCH else analysis_ui.show_piano_review)(r)
st.markdown(common.theme.FOOTER(), unsafe_allow_html=True)
