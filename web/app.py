"""
Шопендирижёр: веб-оболочка (Streamlit).
Запуск локально:  streamlit run web/app.py
Размещение в облаке: см. docs/DEPLOY.md
"""
import os, sys, io, json, tempfile, zipfile, shutil, traceback
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
try:
    for _k, _v in st.secrets.items():          # keys from Streamlit "Secrets" become environment variables
        if isinstance(_v, str):                 # (before the imports below: ORCH_RANGES / ORCH_COMFORT are read at import)
            os.environ.setdefault(_k, _v)
except Exception:
    pass

import orchestrator          # noqa: E402
import validator             # noqa: E402
import audio_tools           # noqa: E402
import llm_planner           # noqa: E402
import reduction             # noqa: E402
import score_review          # noqa: E402
import score_notation        # noqa: E402
PROVIDER, PROVIDER_KEY, PROVIDER_MODEL = llm_planner.configured_provider()
LLM_READY = bool(PROVIDER and PROVIDER_KEY and PROVIDER_MODEL)

st.set_page_config(page_title="Шопендирижёр", page_icon="🎼", layout="centered")

GOLD_SCROLL = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 60'>"
    "<g fill='none' stroke='%23b8860b' stroke-width='2' stroke-linecap='round'>"
    "<path d='M4 56 C 4 20, 30 6, 52 14 S 58 40, 40 42 S 28 30, 38 24'/>"
    "<path d='M116 56 C 116 20, 90 6, 68 14 S 62 40, 80 42 S 92 30, 82 24'/>"
    "<circle cx='60' cy='10' r='3' fill='%23b8860b'/>"
    "<path d='M30 56 H90' stroke-width='1.2'/>"
    "</g></svg>"
)
DIVIDER = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 24' width='300' height='24'>"
    "<g fill='none' stroke='%23b8860b' stroke-width='1.5' stroke-linecap='round'>"
    "<path d='M4 12 H110'/><path d='M190 12 H296'/>"
    "<path d='M110 12 C 120 2, 132 2, 140 12 C 132 22, 120 22, 110 12'/>"
    "<path d='M190 12 C 180 2, 168 2, 160 12 C 168 22, 180 22, 190 12'/>"
    "<circle cx='150' cy='12' r='4' fill='%23b8860b'/>"
    "</g></svg>"
)

import urllib.parse as _up
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
.frame { position: relative; }
.frame::before, .frame::after {
  content: ""; position: absolute; width: 60px; height: 30px; pointer-events: none;
  background-image: url("data:image/svg+xml;utf8,__SCROLL_URI__");
  background-size: contain; background-repeat: no-repeat; opacity: .8;
}
.frame::before { top: -6px; left: -6px; }
.frame::after { bottom: -6px; right: -6px; transform: rotate(180deg); }
.divider { text-align: center; margin: -.4rem 0 .6rem; }

</style>
"""
BAROQUE_CSS = BAROQUE_CSS.replace("__SCROLL_URI__", _up.quote(GOLD_SCROLL.replace('%23', '#'), safe="'=:/ "))
st.markdown(BAROQUE_CSS, unsafe_allow_html=True)

st.markdown("<div class='divider'>" + DIVIDER + "</div>", unsafe_allow_html=True)
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
# Без фильтра type: на планшетах (iPad, Android) браузер с фильтром ".mid" часто делает MIDI-файлы серыми
# и их нельзя выбрать. Расширение проверяем сами.
up = st.file_uploader("MIDI-файл (.mid, .midi)", accept_multiple_files=False)
if up is not None and not up.name.lower().endswith((".mid", ".midi")):
    st.error("Это не MIDI-файл: «%s». Нужен файл с окончанием .mid или .midi." % up.name)
    up = None


def source_mp3(data: bytes):
    """MP3 загруженного файла как есть (до оркестровки или переложения). Считается один раз на файл:
    Streamlit перезапускает страницу при каждом нажатии, поэтому результат хранится по отпечатку содержимого."""
    import hashlib
    key = hashlib.md5(data).hexdigest()
    cached = st.session_state.get("source_mp3")
    if cached and cached.get("key") == key:
        return cached
    work = tempfile.mkdtemp(prefix="source_")
    mid, mp3 = os.path.join(work, "source.mid"), os.path.join(work, "source.mp3")
    with open(mid, "wb") as f:
        f.write(data)
    res = {"key": key, "mp3": None, "soundfont": None, "error": None}
    try:
        out = audio_tools.render_mp3(mid, mp3)
        res["mp3"] = open(out, "rb").read()
        res["soundfont"] = os.path.basename(audio_tools.LAST_SOUNDFONT or "")
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    st.session_state["source_mp3"] = res
    return res


if up is not None and up.size <= 2 * 1024 * 1024:
    st.markdown("**Исходный файл:** так звучит загруженный MIDI до обработки.")
    with st.spinner("Готовлю запись исходного файла..."):
        _src = source_mp3(up.getvalue())
    if _src["mp3"]:
        st.audio(_src["mp3"], format="audio/mpeg")
        if _src["soundfont"]:
            st.caption("Звук сделан набором инструментов «%s»." % os.path.splitext(_src["soundfont"])[0])
    else:
        st.warning("Запись исходного файла сделать не удалось. Обработка файла от этого не зависит.")
        with st.expander("Почему нет записи (для разработчика)"):
            st.code(_src["error"] or "причина неизвестна")

st.markdown("### 2. Что сделать")
use_llm = False
if LLM_READY:
    use_llm = st.checkbox("Помощь модели (%s): план оркестровки или выбор голосов при переложении" % PROVIDER, value=True,
                          help="Модель пишет план по смыслу фраз, программа проверяет его.")
REVIEW_MODE = "Проверить партитуру (готовый оркестр)"
mode = st.radio("Что сделать", ["Оркестровка (из фортепиано)", "Переложение для фортепиано (из оркестра)", REVIEW_MODE], horizontal=True)
go = st.button({"Оркестровка (из фортепиано)": "Создать оркестровку", REVIEW_MODE: "Проверить партитуру"}.get(mode, "Создать переложение"),
               disabled=up is None, use_container_width=True)


def process(data: bytes, name: str, use_llm_flag: bool = False):
    """Runs the full pipeline in a private temporary folder and returns the list of result files."""
    work = tempfile.mkdtemp(prefix="shopendirizhor_")
    src = os.path.join(work, "input.mid")
    with open(src, "wb") as f:
        f.write(data)
    stem = os.path.join(work, "result")
    llm_log = None
    planner_info = None
    if use_llm_flag:
        llm_planner.MODELS_SERVED.clear()
        log, issues, names, llm_log, _pp = llm_planner.orchestrate_with_llm(
            src, stem, PROVIDER, PROVIDER_MODEL, PROVIDER_KEY)
        plan = json.load(open(_pp, encoding="utf-8"))
        planner_info = {"provider": PROVIDER, "model_requested": PROVIDER_MODEL,
                        "model_served_by_api": sorted(set(llm_planner.MODELS_SERVED)),
                        "requests": len(llm_planner.MODELS_SERVED)}
    else:
        log, issues, names = orchestrator.run(src, stem, "off", None)
        plan = json.load(open(stem + "_plan.json", encoding="utf-8"))
    report = json.load(open(stem + "_report.json", encoding="utf-8"))
    if planner_info:                                  # в отчёт: какая модель писала план (видно и в ZIP)
        report["planner"] = planner_info
        try:
            json.dump(report, open(stem + "_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            report.pop("planner", None)
    mp3 = None
    try:
        out = audio_tools.render_mp3(stem + ".mid", stem + ".mp3")
        mp3 = out if os.path.exists(out) else None
    except Exception:
        mp3 = None
    try:
        review = score_review.review(stem + ".mid", stem + ".musicxml")
    except Exception:
        review = None
    score_notation.build(review, stem + ".musicxml", stem + ".mid")   # ноты с пометками; ошибка пишется в review["notation_error"]
    return {"work": work, "stem": stem, "plan": plan, "report": report, "issues": issues, "llm_log": llm_log,
            "mp3": mp3, "name": os.path.splitext(name)[0], "review": review}


def show_review(review, expanded=True):
    """Russian-language review of the score (src/score_review.py): findings with an honest status of every rule."""
    if not review:
        st.info("Рецензия недоступна.")
        return
    s = review["stats"]
    st.caption("Тактов: %d, темп около %d уд/мин. Инструментов в такте: в среднем %s, от %d до %d. "
               "Модуль считает, а не слушает: звучание оценивает слушатель." % (
                   s["тактов"], s["темп_уд_мин"], s["инструментов_в_такте_среднее"], *s["инструментов_в_такте_мин_макс"]))
    if not review["findings"]:
        st.success("Замечаний нет.")
    for _, code, status, text in review["findings"]:
        st.markdown("**[%s]** %s" % (code, text))
        st.caption("Статус правила: " + status)
    if review.get("grid") and review["findings"]:
        st.markdown("**Карта замечаний.** Строки: инструменты, столбцы: такты. Красное: место замечания.")
        opts = ["Все замечания сразу"] + ["%d. [%s] %s" % (i + 1, f[1], f[3][:70]) for i, f in enumerate(review["findings"])]
        pick = st.selectbox("Показать на карте", opts, index=1 if len(opts) > 1 else 0, key="map_pick")
        only = None if pick == opts[0] else opts.index(pick) - 1
        st.markdown(score_review.map_html(review, only=only), unsafe_allow_html=True)
        prep = review.get("notation")
        if not prep and review.get("notation_error"):
            st.warning("Ноты с пометками на этот раз не построились (карта выше работает). "
                       "Пришлите, пожалуйста, текст из раздела ниже разработчику.")
            with st.expander("Почему нет нот (для разработчика)"):
                st.code(review["notation_error"][-3000:])
        if prep:
            import base64
            pages, total = score_notation.colored_pages(prep, score_notation.ids_for(review, prep, only), max_pages=4)
            st.markdown("**Ноты с пометками.** Красные ноты: место выбранного замечания. Показаны страницы %s%s." % (
                ", ".join(str(p) for p, _ in pages), "" if total <= len(pages) else " (первые %d из %d; все страницы в файле ниже)" % (len(pages), total)))
            for p, svg in pages:
                st.markdown("<div style='background:#fff;border:1px solid #d8ccb4;border-radius:6px;padding:6px;margin-bottom:8px'>"
                            "<img style='width:100%%' src='data:image/svg+xml;base64,%s'/></div>" % base64.b64encode(svg.encode("utf-8")).decode(),
                            unsafe_allow_html=True)
            st.download_button("Скачать партитуру с пометками (HTML, открывается в браузере)",
                               score_notation.standalone_html(review, prep).encode("utf-8"),
                               file_name="партитура_с_пометками.html", mime="text/html", use_container_width=True, key="dl_notes")



if go and up is not None and mode == REVIEW_MODE:
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ.")
    else:
        with st.spinner("Проверяю партитуру..."):
            try:
                _work = tempfile.mkdtemp(prefix="review_")
                _src = os.path.join(_work, "score.mid")
                with open(_src, "wb") as _f:
                    _f.write(up.getvalue())
                _rv = score_review.review(_src)
                if not _rv["stats"]["тактов"]:
                    raise ValueError("в файле не найдено ни одной дорожки оркестровых инструментов")
                score_notation.build(_rv, None, _src)
                st.session_state.result = {"mode": "review", "review": _rv, "name": os.path.splitext(up.name)[0]}
            except Exception:
                st.session_state.result = None
                st.error("Не удалось проверить файл. Нужен MIDI оркестровки, где дорожки названы по инструментам "
                         "(Flute, Oboe, Clarinet, Bassoon, Horn, Violin, Viola, Cello, Double Bass).")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None and mode == "Переложение для фортепиано (из оркестра)":
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
if res and res.get("mode") == "review":
    st.markdown("### 3. Рецензия на партитуру")
    st.caption("Программа ничего не исправляет: она показывает, что нашла, и честно называет, чем подтверждено каждое правило.")
    show_review(res["review"])
    st.download_button("Скачать карту замечаний (HTML, открывается в браузере)",
                       score_review.map_html(res["review"], standalone=True).encode("utf-8"),
                       file_name=res["name"] + "_карта_замечаний.html", mime="text/html", use_container_width=True)
    res = None
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
        _sf = os.path.basename(audio_tools.LAST_SOUNDFONT or "")
        if _sf:
            st.caption("Звук сделан набором инструментов «%s»%s." % (os.path.splitext(_sf)[0],
                       "" if "MS Basic" in _sf else " (маленький набор: звучит проще, чем в MuseScore)"))
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в программе для музыки.")

    if res.get("llm_log"):
        _pi = (res.get("report") or {}).get("planner") or {}
        st.info("План написала модель %s. Проверок плана: %d. Заказано: %s; сервис ответил: %s." % (
            PROVIDER, len(res["llm_log"]), _pi.get("model_requested") or "(не задано)",
            ", ".join(_pi.get("model_served_by_api") or []) or "—"))
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

    with st.expander("Рецензия на партитуру (по-русски)", expanded=True):
        show_review(res.get("review"))

    with st.expander("Технические замечания проверки (английские коды)"):
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
        if res.get("review"):
            try:
                z.writestr(res["name"] + "_карта_замечаний.html", score_review.map_html(res["review"], standalone=True))
            except Exception:
                z.writestr(res["name"] + "_ОШИБКА_карты.txt", traceback.format_exc())
            try:
                if res["review"].get("notation"):
                    z.writestr(res["name"] + "_партитура_с_пометками.html",
                               score_notation.standalone_html(res["review"], res["review"]["notation"]))
                elif res["review"].get("notation_error"):
                    z.writestr(res["name"] + "_ОШИБКА_нот.txt", res["review"]["notation_error"])
            except Exception:
                z.writestr(res["name"] + "_ОШИБКА_нот.txt", traceback.format_exc())
    st.download_button("Скачать всё (ZIP)", buf.getvalue(), file_name=res["name"] + "_оркестровка.zip",
                       mime="application/zip", use_container_width=True)
    if res["mp3"]:
        st.download_button("Скачать запись (MP3)", open(res["mp3"], "rb").read(), file_name=res["name"] + ".mp3",
                           mime="audio/mpeg", use_container_width=True)

    st.caption("Нажимая «Создать оркестровку», вы подтверждаете, что имеете право обработать этот файл.")
