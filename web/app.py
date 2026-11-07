"""
Оркестратор (репозиторий shopendirizhor): веб-оболочка (Streamlit).
Запуск локально:  streamlit run web/app.py
Размещение в облаке: см. docs/DEPLOY.md
"""
import os, sys, io, json, tempfile, zipfile, shutil, traceback, time
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
import score_fix             # noqa: E402
import score_notation        # noqa: E402
import piano_review          # noqa: E402
PROVIDER, PROVIDER_KEY, PROVIDER_MODEL = llm_planner.configured_provider()
LLM_READY = bool(PROVIDER and PROVIDER_KEY and PROVIDER_MODEL)

st.set_page_config(page_title="Оркестратор", page_icon="🎼", layout="centered")

# Барочное оформление (вариант A: голубой дворец, золото, красный бархат): web/theme.py.
# Украшения только в шапке, по краям и в углах листа; текст всегда на сплошном светлом листе.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme                 # noqa: E402
import progress              # noqa: E402
st.markdown(theme.CSS(), unsafe_allow_html=True)
_first_visit = not st.session_state.get("bq_opened")     # занавес раздвигается только при первом входе
st.session_state["bq_opened"] = True
st.markdown(theme.DECOR_TOP(curtain_open=_first_visit), unsafe_allow_html=True)
st.markdown(theme.TITLE(), unsafe_allow_html=True)
_wall = st.radio("Стена", ["глубокая", "светлая"], horizontal=True, key="wall")
st.markdown("<style>" + theme.WALL_CSS("deep" if _wall == "глубокая" else "light") + "</style>", unsafe_allow_html=True)

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

st.markdown(theme.SECTION("I", "Загрузите пьесу"), unsafe_allow_html=True)
# Без фильтра type: на планшетах (iPad, Android) браузер с фильтром ".mid" часто делает MIDI-файлы серыми
# и их нельзя выбрать. Расширение проверяем сами.
class _Upload:
    """Проверенный MIDI: имя всегда с .mid, содержимое — чистый MIDI (как у объекта загрузки Streamlit)."""
    def __init__(self, name, data):
        self.name, self._data, self.size = name, data, len(data)

    def getvalue(self):
        return self._data


MIDI_EXTS = (".mid", ".midi", ".kar", ".rmi", ".smf", ".bin", ".dat", ".tmp")


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
    if f is None:
        return None
    midi = midi_bytes(f.getvalue())
    name = f.name or "пьеса"
    if midi is None:
        st.error("%s «%s» не похож на MIDI: внутри нет признака MIDI-файла. Если вы уверены, что это MIDI, "
                 "пришлите его разработчику." % (what, name))
        return None
    stem, ext = os.path.splitext(name)
    if ext.lower() not in MIDI_EXTS:
        stem = name                    # «Прелюдия» или «document_1234»: окончания нет, имя оставляем целиком
    if not name.lower().endswith((".mid", ".midi")):
        st.caption("Имя «%s» без окончания .mid, но внутри MIDI: файл принят." % name)
    return _Upload(stem + ".mid", midi)


up = checked_midi(st.file_uploader("MIDI-файл (.mid, .midi)", accept_multiple_files=False))


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
        _t0 = time.time()
        out = audio_tools.render_mp3(mid, mp3)
        progress.learn("mp3", time.time() - _t0, progress.midi_seconds(data))   # для счётчика: скорость записи в облаке
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

st.markdown(theme.SECTION("II", "Что сделать"), unsafe_allow_html=True)
use_llm = False
if LLM_READY:
    use_llm = st.checkbox("Помощь модели (%s): план оркестровки или выбор голосов при переложении" % PROVIDER, value=True,
                          help="Модель пишет план по смыслу фраз, программа проверяет его.")
REVIEW_MODE = "Проверить партитуру (готовый оркестр)"
PIANO_REVIEW_MODE = "Проверить переложение (готовое фортепиано)"
mode = st.radio("Что сделать", ["Оркестровка (из фортепиано)", "Переложение для фортепиано (из оркестра)", REVIEW_MODE,
                                PIANO_REVIEW_MODE], key="mode_pick")
orig_up = None
if mode == PIANO_REVIEW_MODE:
    st.caption("Вверху загрузите MIDI рояля. По желанию добавьте оркестровый оригинал: тогда программа посчитает, "
               "сколько гармонии оркестра сохранилось в переложении.")
    orig_up = checked_midi(st.file_uploader("Оркестровый оригинал (необязательно, .mid)", accept_multiple_files=False,
                                            key="orig_up"), "Оригинал")
go = st.button({"Оркестровка (из фортепиано)": "Создать оркестровку", REVIEW_MODE: "Проверить партитуру",
                PIANO_REVIEW_MODE: "Проверить переложение"}.get(mode, "Создать переложение"),
               disabled=up is None, use_container_width=True)


def process(data: bytes, name: str, use_llm_flag: bool = False, prog=None):
    """Runs the full pipeline in a private temporary folder and returns the list of result files.
    prog: progress.Steps (шаги llm/plan, mp3, review, notes) или None."""
    step = (lambda k: prog.go(k)) if prog else (lambda k: None)
    work = tempfile.mkdtemp(prefix="shopendirizhor_")
    src = os.path.join(work, "input.mid")
    with open(src, "wb") as f:
        f.write(data)
    stem = os.path.join(work, "result")
    llm_log = None
    planner_info = None
    step("llm" if use_llm_flag else "plan")
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
    step("mp3")
    try:
        out = audio_tools.render_mp3(stem + ".mid", stem + ".mp3")
        mp3 = out if os.path.exists(out) else None
    except Exception:
        mp3 = None
    step("review")
    try:
        review = score_review.review(stem + ".mid", stem + ".musicxml")
    except Exception:
        review = None
    step("notes")
    score_notation.build(review, stem + ".musicxml", stem + ".mid")   # ноты с пометками; ошибка пишется в review["notation_error"]
    if prog:                                          # фактическое время шагов: в отчёт (и в ZIP), для уточнения счётчика
        report["timings_s"] = prog.finish()
        try:
            json.dump(report, open(stem + "_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass
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
        _prog = progress.Steps([("review", "рецензия"), ("notes", "ноты с пометками")], progress.midi_seconds(up.getvalue()))
        with st.spinner("Проверяю партитуру..."):
            try:
                _work = tempfile.mkdtemp(prefix="review_")
                _src = os.path.join(_work, "score.mid")
                with open(_src, "wb") as _f:
                    _f.write(up.getvalue())
                _prog.go("review")
                _rv = score_review.review(_src)
                if not _rv["stats"]["тактов"]:
                    raise ValueError("в файле не найдено ни одной дорожки оркестровых инструментов")
                _prog.go("notes")
                score_notation.build(_rv, None, _src)
                _prog.finish()
                st.session_state.result = {"mode": "review", "review": _rv, "name": os.path.splitext(up.name)[0], "src": _src}
            except Exception:
                _prog.abort()
                st.session_state.result = None
                st.error("Не удалось проверить файл. Нужен MIDI оркестровки, где дорожки названы по инструментам "
                         "(Flute, Oboe, Clarinet, Bassoon, Horn, Violin, Viola, Cello, Double Bass).")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None and mode == "Переложение для фортепиано (из оркестра)":
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ.")
    else:
        _prog = progress.Steps([("llm_reduce", "модель выбирает голоса, программа делает переложение") if use_llm else
                                ("reduce", "переложение"), ("mp3", "запись MP3")], progress.midi_seconds(up.getvalue()))
        with st.spinner("Делаю редукцию..."):
            try:
                _prog.go("llm_reduce" if use_llm else "reduce")
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
                _prog.go("mp3")
                try:
                    _mp3 = audio_tools.render_mp3(_out, _mp3)
                except Exception:
                    _mp3 = None
                _prog.finish()
                st.session_state.result = {"mode": "reduction", "stats": _stats, "midi": _out,
                                           "mp3": _mp3 if _mp3 and os.path.exists(_mp3) else None,
                                           "name": os.path.splitext(up.name)[0]}
            except Exception:
                _prog.abort()
                st.session_state.result = None
                st.error("Не удалось сделать редукцию. Проверьте, что это MIDI-файл оркестровки.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None and mode == PIANO_REVIEW_MODE:
    if up.size > 2 * 1024 * 1024 or (orig_up is not None and orig_up.size > 2 * 1024 * 1024):
        st.error("Файл больше 2 МБ.")
    else:
        _prog = progress.Steps([("piano_review", "проверка рук и гармонии"), ("notes", "ноты с пометками")],
                               progress.midi_seconds(up.getvalue()))
        with st.spinner("Проверяю переложение..."):
            try:
                _prog.go("piano_review")
                _work = tempfile.mkdtemp(prefix="preview_")
                _src = os.path.join(_work, "piano.mid")
                with open(_src, "wb") as _f:
                    _f.write(up.getvalue())
                _orig = None
                if orig_up is not None:
                    _orig = os.path.join(_work, "orchestra.mid")
                    with open(_orig, "wb") as _f:
                        _f.write(orig_up.getvalue())
                _rv = piano_review.review(_src, _orig)
                if not _rv["stats"]["нот"]:
                    raise ValueError("в файле нет нот")
                _prog.go("notes")
                score_notation.build_hands(_rv)   # ноты с пометками; ошибка пишется в _rv["notation_error"]
                _prog.finish()
                st.session_state.result = {"mode": "piano_review", "review": _rv, "name": os.path.splitext(up.name)[0]}
            except Exception:
                _prog.abort()
                st.session_state.result = None
                st.error("Не удалось проверить файл. Нужен MIDI фортепиано (одна или две дорожки).")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None:
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ. Пожалуйста, загрузите более короткую пьесу.")
    else:
        _prog = progress.Steps([("llm", "модель пишет план, программа расставляет ноты") if use_llm else
                                ("plan", "план фраз и ноты"), ("mp3", "запись MP3"), ("review", "рецензия"),
                                ("notes", "ноты с пометками")], progress.midi_seconds(up.getvalue()))
        with st.spinner("Оркестровка выполняется..."):
            try:
                st.session_state.result = process(up.getvalue(), up.name, use_llm_flag=use_llm, prog=_prog)
            except Exception as e:
                _prog.abort()
                st.session_state.result = None
                st.error("Не удалось обработать файл. Проверьте, что это сольная фортепианная пьеса в MIDI с ровным ритмом.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())

res = st.session_state.result
if res and res.get("mode") == "review":
    st.markdown(theme.SECTION("III", "Рецензия на партитуру"), unsafe_allow_html=True)
    st.caption("Программа ничего не исправляет: она показывает, что нашла, и честно называет, чем подтверждено каждое правило.")
    show_review(res["review"])
    st.download_button("Скачать карту замечаний (HTML, открывается в браузере)",
                       score_review.map_html(res["review"], standalone=True).encode("utf-8"),
                       file_name=res["name"] + "_карта_замечаний.html", mime="text/html", use_container_width=True)
    # Исправление быстрых нот (K2): одобрено на слух 2026-11-07. Исходный файл не меняется: получается отдельный MIDI.
    st.markdown(theme.SECTION("IV", "Исправление"), unsafe_allow_html=True)
    st.caption("Кнопка делает НОВЫЙ файл: у валторны, фагота и контрабаса в долях с быстрыми нотами остаётся одна опорная нота. "
               "Высоты не меняются. Ваш исходный файл остаётся как был, так что вернуться к нему можно всегда.")
    if st.button("Исправить быстрые ноты (валторна, фагот, контрабас)", key="fix_go", use_container_width=True):
        try:
            _fx = os.path.join(os.path.dirname(res["src"]), "score_fixed.mid")
            _chg = score_fix.fix_midi(res["src"], _fx)
            _rv2 = score_review.review(_fx)
            _mp3f = None
            try:
                _mp3f = audio_tools.render_mp3(_fx, os.path.join(os.path.dirname(res["src"]), "score_fixed.mp3"))
            except Exception:
                _mp3f = None
            res["fix"] = {"midi": _fx, "changes": _chg, "mp3": _mp3f if _mp3f and os.path.exists(_mp3f) else None,
                          "before": len(res["review"]["findings"]), "after": len(_rv2["findings"])}
            st.session_state.result = res
        except Exception:
            res.pop("fix", None)
            st.error("Не удалось исправить файл. Исходный файл не изменён.")
            with st.expander("Подробности для разработчика"):
                st.code(traceback.format_exc())
    _fix = res.get("fix")
    if _fix:
        if _fix["changes"]:
            st.success("Что изменено:")
            for _c in _fix["changes"]:
                st.write("• " + _c)
        else:
            st.info("Исправлять нечего: быстрых нот у валторны, фагота и контрабаса не найдено.")
        st.write("Замечаний рецензента: было %d, стало %d." % (_fix["before"], _fix["after"]))
        if _fix["mp3"]:
            st.audio(_fix["mp3"])
            st.caption("Звук: " + str(getattr(audio_tools, "LAST_SOUNDFONT", "") or "банк по умолчанию"))
        with open(_fix["midi"], "rb") as _fh:
            st.download_button("Скачать исправленный MIDI", _fh.read(), file_name=res["name"] + "_исправлено.mid",
                               mime="audio/midi", use_container_width=True, key="dl_fixed_mid")
        if _fix["mp3"]:
            with open(_fix["mp3"], "rb") as _fh:
                st.download_button("Скачать исправленный MP3", _fh.read(), file_name=res["name"] + "_исправлено.mp3",
                                   mime="audio/mpeg", use_container_width=True, key="dl_fixed_mp3")
    res = None
if res and res.get("mode") == "piano_review":
    st.markdown(theme.SECTION("III", "Проверка переложения"), unsafe_allow_html=True)
    st.caption("Программа ничего не исправляет: она показывает, что нашла, и честно называет, чем подтверждено каждое правило. "
               "Модуль считает, а не слушает: звучание оценивает слушатель.")
    _rv, _s = res["review"], res["review"]["stats"]
    st.caption("Тактов: %d, темп около %d уд/мин, нот: %d. Руки определены %s." % (_s["тактов"], _s["темп_уд_мин"], _s["нот"], _s["руки"]))
    if _s.get("гармония"):
        st.info("Сохранено высот гармонии оригинала: в среднем %.0f%%; все высоты аккорда звучат в %.0f%% моментов."
                % (100 * _s["гармония"]["среднее"], 100 * _s["гармония"]["все_высоты"]))
    if _s.get("между_руками_больше_18"):
        st.caption("Справка: между руками больше 18 полутонов в %d аккордах. Число не подтверждено источником, "
                   "в фортепианной музыке это обычно, поэтому это не замечание." % _s["между_руками_больше_18"])
    if not _rv["findings"]:
        st.success("Замечаний нет.")
    for _, code, status, text in _rv["findings"]:
        st.markdown("**[%s]** %s" % (code, text))
        st.caption("Статус правила: " + status)
    _only = None
    if _rv["findings"]:
        st.markdown("**Карта замечаний.** Строки: руки, столбцы: такты. Красное: место замечания.")
        _opts = ["Все замечания сразу"] + ["%d. [%s] %s" % (i + 1, f[1], f[3][:70]) for i, f in enumerate(_rv["findings"])]
        _pick = st.selectbox("Показать на карте", _opts, index=1 if len(_opts) > 1 else 0, key="pmap_pick")
        _only = None if _pick == _opts[0] else _opts.index(_pick) - 1
        st.markdown(score_review.map_html(_rv, only=_only), unsafe_allow_html=True)
    _prep = _rv.get("notation")
    if not _prep and _rv.get("notation_error"):
        st.warning("Ноты с пометками на этот раз не построились (карта выше работает). "
                   "Пришлите, пожалуйста, текст из раздела ниже разработчику.")
        with st.expander("Почему нет нот (для разработчика)"):
            st.code(_rv["notation_error"][-3000:])
    if _prep:
        import base64
        _pages, _total = score_notation.colored_pages(_prep, score_notation.ids_for(_rv, _prep, _only), max_pages=4)
        st.markdown("**Ноты с пометками.** Две строки: правая и левая рука. Красные ноты: место замечания "
                    "(если выбрано одно). Показаны страницы %s%s." % (
                        ", ".join(str(p) for p, _ in _pages),
                        "" if _total <= len(_pages) else " (первые %d из %d; все страницы в файле ниже)" % (len(_pages), _total)))
        for _p, _svg in _pages:
            st.markdown("<div style='background:#fff;border:1px solid #d8ccb4;border-radius:6px;padding:6px;margin-bottom:8px'>"
                        "<img style='width:100%%' src='data:image/svg+xml;base64,%s'/></div>" % base64.b64encode(_svg.encode("utf-8")).decode(),
                        unsafe_allow_html=True)
        st.download_button("Скачать ноты с пометками (HTML, открывается в браузере)",
                           score_notation.standalone_html(_rv, _prep, title="Переложение с пометками").encode("utf-8"),
                           file_name=res["name"] + "_переложение_с_пометками.html", mime="text/html",
                           use_container_width=True, key="dl_piano_notes")
    st.download_button("Скачать отчёт и карту (HTML, открывается в браузере)",
                       score_review.map_html(_rv, standalone=True).encode("utf-8"),
                       file_name=res["name"] + "_проверка_переложения.html", mime="text/html", use_container_width=True)
    res = None
if res and res.get("mode") == "reduction":
    st.markdown(theme.SECTION("III", "Результат переложения"), unsafe_allow_html=True)
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
    st.markdown(theme.SECTION("III", "Результат"), unsafe_allow_html=True)
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

st.markdown(theme.FOOTER(), unsafe_allow_html=True)
