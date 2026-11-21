"""
Оркестратор (репозиторий shopendirizhor): веб-оболочка (Streamlit).
Запуск локально:  streamlit run web/app.py
Размещение в облаке: см. docs/DEPLOY.md
Главная страница (упрощена 2026-11-21): загрузка, выбор, результат. Все проверки, карта замечаний, ноты с
пометками и исправления — на странице «Анализ и проверки» (web/pages/2_Анализ.py, показ: web/analysis_ui.py).
"""
import os, sys, io, json, tempfile, zipfile, shutil, traceback, time
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common                # noqa: E402  первым: секреты Streamlit → переменные окружения до импорта src
from common import ROOT, checked_midi, any_file   # noqa: E402,F401

import orchestrator          # noqa: E402
import validator             # noqa: E402
import audio_tools           # noqa: E402
import llm_planner           # noqa: E402
import reduction             # noqa: E402
import score_review          # noqa: E402
import quality_gate          # noqa: E402
import taste_check           # noqa: E402
import score_notation        # noqa: E402
import resources             # noqa: E402
import theme                 # noqa: E402
import progress              # noqa: E402
import jobs                  # noqa: E402
import picker                # noqa: E402
import analysis_ui           # noqa: E402
PROVIDER, PROVIDER_KEY, PROVIDER_MODEL = llm_planner.configured_provider()
LLM_READY = bool(PROVIDER and PROVIDER_KEY and PROVIDER_MODEL)

st.set_page_config(page_title="Оркестратор", page_icon="🎼", layout="centered")
common.decorate()
common.nav("Главная")

with st.expander("О программе, ограничения и приватность", expanded=False):
    st.markdown("""
**Оркестровка:** фортепианная пьеса (MIDI или MusicXML) → камерный оркестр из десяти инструментов (флейта, гобой, кларнет,
фагот, валторна, скрипки I и II, альт, виолончель, контрабас). **Ансамбль:** дуэт, трио или квартет. **Переложение:**
оркестр → фортепиано. На выходе MIDI по дорожкам, ноты MusicXML и запись для прослушивания.

**Честно о результате.** Правила взяты из учебников (Римский-Корсаков, Берлиоз, Форсайт, Черни) и дополнены эвристиками.
Результат проверяется автоматически, но это не профессиональная аранжировка, а звук синтезированный. Что именно нашла
проверка — на странице «Анализ и проверки».

- Загружайте только свои пьесы или пьесы, права на которые у вас есть. Файл и результат хранятся на сервере не дольше 6 часов, потом удаляются.
- Размер: MIDI до 2 МБ (около 2000 нот), MusicXML до 5 МБ.
- Запись живой игры (mp3/wav) программа в MIDI не превращает.
- Пьесы короче 3 тактов и длиннее 100 тактов дают неудовлетворительный результат.
""")

if "result" not in st.session_state:
    st.session_state.result = None

st.markdown(theme.SECTION("I", "Загрузите пьесу"), unsafe_allow_html=True)
up = checked_midi(any_file("Пьеса: MIDI (.mid) или MusicXML (.musicxml, .xml, .mxl), до 5 МБ", "piece", diagnostics=True))
_gen = st.session_state.get("gen_piece")             # пьеса, присланная со страницы «Генератор»
if up is None and _gen:
    up = common._Upload(_gen["name"], _gen["data"])
    _g1, _g2 = st.columns([3, 1])
    with _g1:
        st.info("Пьеса из генератора: «%s». Выбранный выше файл заменит её." % os.path.splitext(_gen["name"])[0])
    with _g2:
        if st.button("Убрать", key="gen_drop"):
            st.session_state.pop("gen_piece", None)
            st.rerun()

def reset_all():
    """«Начать заново»: забыть файлы, результат и настройки этой сессии, стереть её задание на сервере."""
    _j = st.session_state.get("job")
    try:
        _q = st.query_params.get("job")
        _j = _j or (_q if isinstance(_q, str) else None)
    except Exception:
        pass
    if _j:
        jobs.forget(_j)
    n = st.session_state.get("reset_n", 0) + 1
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state["reset_n"] = n
    st.session_state["bq_opened"] = True            # занавес второй раз не раздвигаем
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()


if st.button("🧹 Начать заново", help="Забывает загруженные файлы, результат и настройки; "
             "с сервера стирается ваша оркестровка. Исходные файлы на вашем телефоне или компьютере не трогаются."):
    reset_all()


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
    st.caption("Исходный файл, как он звучит до обработки:")
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

@st.cache_data(show_spinner=False, max_entries=4)
def _piece_info(data: bytes):
    """Разбор пьесы для задания и проверки чужого плана: (описание для модели, число тактов)."""
    import tempfile as _tmp
    with _tmp.TemporaryDirectory() as d:
        pth = os.path.join(d, "p.mid")
        open(pth, "wb").write(data)
        s, events, melody, meta = orchestrator.analyze(pth)
        n = len(meta["bars"])
        return llm_planner.describe_piece(meta, melody, events, n), n


def plan_bars(data: bytes):
    return _piece_info(data)[1]


def plan_task_text(data: bytes) -> str:
    desc, n = _piece_info(data)
    return ("ЗАДАНИЕ. Ниже правила и описание пьесы. Напишите план оркестровки и ответьте ТОЛЬКО JSON.\n\n"
            "ПРАВИЛА:\n" + llm_planner.system_text() + "\n\nОПИСАНИЕ ПЬЕСЫ (%d тактов; фразы должны покрыть все такты 1..%d без дыр):\n"
            % (n, n) + desc + "\n")

st.markdown(theme.SECTION("II", "Что сделать"), unsafe_allow_html=True)
ORCH_MODE = "Оркестровка (из фортепиано)"
ENSEMBLE_MODE = "Ансамбль: дуэт, трио, квартет (из фортепиано)"
REDUCE_MODE = "Переложение для фортепиано (из оркестра)"
mode = st.radio("Что сделать", [ORCH_MODE, ENSEMBLE_MODE, REDUCE_MODE], key="mode_pick", label_visibility="collapsed")
use_llm = False
if LLM_READY and mode != ENSEMBLE_MODE:
    use_llm = st.checkbox("Помощь модели (%s): %s" % (PROVIDER, "план оркестровки" if mode == ORCH_MODE else "выбор голосов"),
                          value=True, help="Галочка стоит — модель пишет план (кто и где ведёт мелодию), программа расставляет ноты и проверяет. "
                               "Платный запрос. Галочки нет — всё решает программа сама, бесплатно.")
ens_pick = None
if mode == ENSEMBLE_MODE:
    import ensemble
    _grp = st.radio("Сколько исполнителей", ["Дуэт", "Трио", "Квартет"], horizontal=True, key="ens_group")
    _opts = {e["ru"]: k for k, e in ensemble.ENSEMBLES.items() if e["group"] == _grp}
    ens_pick = _opts[st.selectbox("Состав", list(_opts), key="ens_pick_" + _grp)]
    with st.expander("Дополнительные настройки ансамбля"):
        st.caption("Откуда состав: %s." % ensemble.ENSEMBLES[ens_pick]["source"])
        ens_legato = st.checkbox("Связная игра (legato): каждый инструмент тянет ноту до своей следующей ноты", value=False,
                                 key="ens_legato",
                                 help="У рояля звук продлевает педаль, у смычка педали нет: без связывания между нотами "
                                      "остаются паузы и звучит отрывисто. Высоты и начала нот не меняются. Для танцевальных, "
                                      "отрывистых пьес лучше не включать.")
        ens_mono = st.checkbox("Одноголосная мелодия: перебор аккорда не считать мелодией", value=False, key="ens_mono",
                               help="У рояльных свитков и живых записей аккорд берётся чуть вразнобой, и программа принимала "
                                    "нижние звуки такого аккорда за мелодию: скрипка играла по 3–5 нот сразу. С галочкой у "
                                    "мелодии остаётся одна нота за раз (верхняя), остальные уходят в сопровождение.")
        ens_dyn = st.checkbox("Мелодия громче сопровождения (если у файла плоская громкость)", value=False, key="ens_dyn",
                              help="Если у всех нот файла одна и та же сила нажатия (так бывает у нотных редакторов), все партии "
                                   "играют одинаково громко и «перекрикивают» друг друга. С галочкой мелодия получает больше, "
                                   "сопровождение меньше, нижний голос ещё тише. У файлов с живой динамикой ничего не меняется.")
        ens_llm = False
        if LLM_READY:
            ens_llm = st.checkbox("План от модели (%s): кто ведёт мелодию в каждой фразе и где играть связно" % PROVIDER,
                                  value=False, key="ens_llm",
                                  help="Платный запрос (обычно один). Модель получает указания, как поступают мастера, и "
                                       "пишет план; ноты раздаёт программа и проверяет план. Если план не годится или "
                                       "сервис не ответил, ансамбль делается без плана, причина будет показана.")
        else:
            st.caption("План от модели (DeepSeek) недоступен: в настройках сервера нет ключа.")
SOLO_OPTIONS = {"Фортепиано": "Piano", "Флейта (нежная, невысокая)": "Flute", "Кларнет": "Clarinet", "Гобой": "Oboe",
                "Скрипка": "Violin I", "Виолончель": "Cello", "Аккордеон": "Accordion", "Орган": "Organ", "Гитара": "Guitar"}
LEAD_MODES = ["Оркестр сам распределяет мелодию", "Один солист на всю пьесу", "Меняющиеся солисты, как в «Болеро»"]
SOLO_NAMES = dict({v: k for k, v in SOLO_OPTIONS.items()}, Bolero="меняющиеся солисты, как в «Болеро»")
solo = None
perc = False
plan_text = ""
if mode == ORCH_MODE:
    _lead = st.radio("Кто ведёт мелодию", LEAD_MODES, key="lead_pick",
                     help="Один солист: как в концерте, один инструмент ведёт мелодию от начала до конца, остальные тихо "
                          "аккомпанируют. «Болеро»: солист меняется только между высказываниями темы (примерно через "
                          "8 тактов). Выбирается для каждой пьесы.")
    if _lead == LEAD_MODES[1]:
        solo = SOLO_OPTIONS[st.selectbox("Солирующий инструмент", list(SOLO_OPTIONS), key="solo_pick",
                                         help="Фортепиано и орган играют пьесу целиком, оркестр их поддерживает.")]
    elif _lead == LEAD_MODES[2]:
        solo = "Bolero"
    with st.expander("Дополнительные настройки: ударные, план от другой модели"):
        perc = st.checkbox("Лёгкие ударные для ритма (как в эстрадно-симфоническом оркестре)", value=False, key="perc_pick",
                           help="Тихая бочка, обод малого барабана и хай-хэт по размеру такта; громкость следует фразам. "
                                "Ноты оркестра не меняются. Ударные есть в MIDI и MP3, в нотах их нет.")
        st.markdown("**План оркестровки от другой модели** (Claude, ChatGPT и др.)")
        st.caption("Так можно не платить DeepSeek: скачайте задание, отдайте его любой модели (например, Claude), "
                   "а присланный ею план вставьте сюда. Программа проверит план и расставит по нему ноты. "
                   "Если окно пустое, работает обычный план.")
        if up is not None:
            try:
                st.download_button("Скачать задание для плана (.txt)", plan_task_text(up.getvalue()),
                                   file_name="задание_для_плана.txt", key="plan_task_dl")
            except Exception:
                st.warning("Не удалось подготовить задание: " + traceback.format_exc(limit=2))
        else:
            st.caption("Сначала загрузите пьесу.")
        if st.button("Очистить окно плана", key="plan_clear"):
            st.session_state["plan_text"] = ""
        plan_text = st.text_area("Вставьте сюда план (JSON)", key="plan_text", height=160,
                                 help="Текст, начинающийся с { и кончающийся }. Можно вместе с ```json … ```.").strip()
        if plan_text:
            try:
                _pl = llm_planner.parse_plan(plan_text)
                _bars = None
                if up is not None:
                    _bars = plan_bars(up.getvalue())
                _pr = llm_planner.check_plan(_pl, _bars) if _bars else []
                if _pr:
                    st.error("В плане есть проблемы, оркестровка по нему не начнётся:\n- " + "\n- ".join(_pr))
                    plan_text = ""
                else:
                    st.success("План принят: %d фраз." % len(_pl["phrases"]))
                    if use_llm:
                        st.warning("Пока в окне вставлен план, модель (%s) план НЕ пишет: берётся вставленный. "
                                   "Чтобы план написала модель, нажмите «Очистить окно плана»." % PROVIDER)
            except Exception as _e:
                st.error("Это не похоже на план (JSON): %s" % _e)
                plan_text = ""
go = st.button({ORCH_MODE: "Создать оркестровку", ENSEMBLE_MODE: "Создать ансамбль"}.get(mode, "Создать переложение"),
               disabled=up is None, use_container_width=True)


def process(data: bytes, name: str, use_llm_flag: bool = False, prog=None, solo=None, perc=False, work=None,
            plan_text: str = ""):
    """Runs the full pipeline in a private temporary folder and returns the list of result files.
    prog: progress.Steps (шаги llm/plan, mp3, review, notes) или None."""
    _t0, _mem, _cur = time.time(), {}, [None]

    def step(k):                                      # шаг: экран/файл задания + замер памяти в конце прошлого шага
        if _cur[0]:
            _mem[_cur[0]] = resources.snapshot()
        _cur[0] = k
        if prog:
            prog.go(k)
    work = work or tempfile.mkdtemp(prefix="shopendirizhor_")
    src = os.path.join(work, "input.mid")
    with open(src, "wb") as f:
        f.write(data)
    stem = os.path.join(work, "result")
    llm_log = None
    planner_info = None
    step("llm" if (use_llm_flag and not plan_text) else "plan")
    if plan_text:                                     # готовый план от другой модели: проверен в окне, ноты расставляет программа
        _pf = os.path.join(work, "plan_in.json")
        json.dump(llm_planner.parse_plan(plan_text), open(_pf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log, issues, names = orchestrator.run(src, stem, "off", _pf, solo=solo, percussion=perc)
        plan = json.load(open(stem + "_plan.json", encoding="utf-8"))
        planner_info = {"provider": "вставлен вручную", "model_requested": None, "requests": 0}
    elif use_llm_flag:
        llm_planner.MODELS_SERVED.clear()
        log, issues, names, llm_log, _pp = llm_planner.orchestrate_with_llm(
            src, stem, PROVIDER, PROVIDER_MODEL, PROVIDER_KEY, solo=solo, percussion=perc)
        plan = json.load(open(_pp, encoding="utf-8"))
        planner_info = {"provider": PROVIDER, "model_requested": PROVIDER_MODEL,
                        "model_served_by_api": sorted(set(llm_planner.MODELS_SERVED)),
                        "requests": len(llm_planner.MODELS_SERVED)}
    else:
        log, issues, names = orchestrator.run(src, stem, "off", None, solo=solo, percussion=perc)
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
    try:                                              # контроль брака: сравнение с оригиналом, звук не меняет
        gate = quality_gate.check(src, stem + ".mid", solo=bool(solo))
        report["quality_gate"] = {"ok": gate["ok"], "defects": gate["defects"], "warnings": gate["warnings"],
                                  "stats": gate["stats"]}
        try:                                          # проверка по вкусу пользователя (src/taste_check.py), звук не меняет
            import texture_fix as _tf
            _plan_used = None
            if os.path.exists(stem + "_plan.json"):
                try:
                    _plan_used = json.load(open(stem + "_plan.json", encoding="utf-8"))
                except Exception:
                    _plan_used = None
            gate["taste"] = taste_check.check(src, stem + ".mid", solo=bool(solo), one_lead=_tf.one_lead_enabled(),
                                              plan=_plan_used)
            report["taste_check"] = gate["taste"]
        except Exception:
            gate["taste"] = {"error": traceback.format_exc(limit=3)}
        json.dump(report, open(stem + "_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        gate = {"error": traceback.format_exc(limit=3)}
    step("notes")
    score_notation.build(review, stem + ".musicxml", stem + ".mid")   # ноты с пометками; ошибка пишется в review["notation_error"]
    if _cur[0]:
        _mem[_cur[0]] = resources.snapshot()
    if prog:                                          # фактическое время шагов: в отчёт (и в ZIP), для уточнения счётчика
        report["timings_s"] = prog.finish()
    # замер ресурсов сервера (2026-11-07): время, память по шагам, каким банком сделан звук. Звук не меняет.
    report["resources"] = {"seconds": round(time.time() - _t0, 1), "memory_after_step": _mem,
                           "peak": resources.snapshot(),
                           "soundfont": os.path.splitext(os.path.basename(audio_tools.LAST_SOUNDFONT or ""))[0] or None}
    try:
        json.dump(report, open(stem + "_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {"work": work, "stem": stem, "plan": plan, "report": report, "issues": issues, "llm_log": llm_log,
            "mp3": mp3, "name": os.path.splitext(name)[0], "review": review, "gate": gate}


if go and up is not None and mode == REDUCE_MODE:
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
                st.session_state.result = {"mode": "reduction", "stats": _stats, "midi": _out, "llm": bool(use_llm),
                                           "mp3": _mp3 if _mp3 and os.path.exists(_mp3) else None,
                                           "name": os.path.splitext(up.name)[0]}
            except Exception:
                _prog.abort()
                st.session_state.result = None
                st.error("Не удалось сделать редукцию. Проверьте, что это MIDI-файл оркестровки.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None and mode == ENSEMBLE_MODE:
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ.")
    else:
        _prog = progress.Steps([("reduce", "раздача нот по инструментам"), ("mp3", "запись MP3")], progress.midi_seconds(up.getvalue()))
        with st.spinner("Делаю ансамбль..."):
            try:
                import ensemble
                _prog.go("reduce")
                _work = tempfile.mkdtemp(prefix="ensemble_")
                _src = os.path.join(_work, "piano.mid")
                with open(_src, "wb") as _f:
                    _f.write(up.getvalue())
                _stem = os.path.join(_work, "ensemble")
                _plan, _plog = None, None
                if ens_llm and LLM_READY:
                    _plan, _plog = ensemble.plan_with_model(_src, ens_pick, PROVIDER, PROVIDER_MODEL, PROVIDER_KEY)
                _rep = ensemble.arrange(_src, _stem, ens_pick, plan=_plan, legato=ens_legato, mono=ens_mono, dyn=ens_dyn)
                if _plog: _rep["planner"] = _plog
                try:
                    _gate = quality_gate.check(_src, _stem + ".mid", melody=ensemble.melody_beats(_src, mono=ens_mono))
                    _rep["foreign"] = (_gate.get("stats") or {}).get("foreign")
                except Exception:
                    _rep["foreign_error"] = traceback.format_exc()
                _prog.go("mp3")
                try:
                    _mp3 = audio_tools.render_mp3(_stem + ".mid", _stem + ".mp3")
                except Exception:
                    _mp3 = None
                _prog.finish()
                st.session_state.result = {"mode": "ensemble", "report": _rep, "midi": _stem + ".mid",
                                           "mp3": _mp3 if _mp3 and os.path.exists(_mp3) else None,
                                           "name": os.path.splitext(up.name)[0]}
            except Exception:
                _prog.abort()
                st.session_state.result = None
                st.error("Не удалось сделать ансамбль. Проверьте, что это фортепианная пьеса в MIDI или MusicXML.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
elif go and up is not None:
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ. Пожалуйста, загрузите более короткую пьесу.")
    else:
        # Работа идёт в фоне на сервере (web/jobs.py): не теряется, если на телефоне погас экран или открыто другое
        # приложение. Номер задания пишется в адрес страницы; тот же файл с теми же настройками второй раз не считается.
        _steps = [("llm", "модель пишет план, программа расставляет ноты") if use_llm else ("plan", "план фраз и ноты"),
                  ("mp3", "запись MP3"), ("review", "рецензия"), ("notes", "ноты с пометками")]
        _data, _name = up.getvalue(), up.name
        _jk = jobs.key(_data, {"name": _name, "llm": bool(use_llm), "solo": solo, "perc": bool(perc), "plan": plan_text})
        jobs.start(_jk, lambda _p, _w: process(_data, _name, use_llm_flag=use_llm, prog=_p, solo=solo, perc=perc, work=_w,
                                               plan_text=plan_text),
                   _steps, progress.midi_seconds(_data))
        st.session_state.job, st.session_state.job_loaded, st.session_state.result = _jk, None, None
        try:
            st.query_params["job"] = _jk
        except Exception:
            pass

@st.fragment(run_every=3)
def _show_progress(_job):
    """Прогресс фонового задания. Обновляется только этот блок (а не вся страница): раньше страница
    перезапускалась через st.rerun() каждые 3 с и оставляла бледную копию прежнего блока («двойник»).
    Когда задание кончилось, перезапускаем всю страницу один раз, чтобы показать результат."""
    _js = jobs.status(_job)
    if _js is None or _js.get("state") in ("done", "error") or not jobs.alive(_job):
        st.rerun()
    _steps = [tuple(x) for x in _js.get("steps", [])]
    _keys = [k for k, _ in _steps]
    _i = _keys.index(_js.get("step")) if _js.get("step") in _keys else 0
    _dur = float(_js.get("dur") or 60.0)
    _est = [progress.estimate(k, _dur) for k in _keys]
    _left = max(0.0, sum(_est[_i:]) - (time.time() - float(_js.get("step_started", time.time()))))
    st.markdown(theme.SECTION("III", "Результат"), unsafe_allow_html=True)
    st.progress(min(sum(_est[:_i]) / (sum(_est) or 1.0), 0.99),
                text="Шаг %d из %d: %s" % (_i + 1, len(_steps), _steps[_i][1] if _steps else ""))
    try:
        import streamlit.components.v1 as _cmp
        _cmp.html(progress._countdown_html(_left), height=52)
    except Exception:
        st.caption("Осталось примерно %s" % progress._clock(_left))
    st.info("Оркестровка идёт на сервере. Можно погасить экран или переключиться в другое приложение: "
            "когда вернётесь, страница сама покажет результат.")


# Фоновое задание оркестровки: показать прогресс или забрать готовый результат (и после возвращения на страницу)
try:
    _qp = st.query_params.get("job")
except Exception:
    _qp = None
_job = st.session_state.get("job") or (_qp if isinstance(_qp, str) else None)
if _job and st.session_state.get("job_loaded") != _job:
    _js = jobs.status(_job)

    def _forget_job():
        st.session_state.job = None
        try:
            del st.query_params["job"]
        except Exception:
            pass
    if _js is None:
        st.info("Прежняя оркестровка уже не хранится на сервере (прошло больше 6 часов или сервер перезапускался). "
                "Загрузите файл и запустите ещё раз.")
        _forget_job()
    elif _js.get("state") == "done":
        try:
            st.session_state.result = jobs.load(_job)
            st.session_state.job_loaded = _job
        except Exception:
            st.error("Готовый результат не удалось прочитать. Запустите оркестровку ещё раз.")
            with st.expander("Подробности для разработчика"):
                st.code(traceback.format_exc())
            _forget_job()
    elif _js.get("state") == "error":
        st.error("Не удалось обработать файл. Проверьте, что это сольная фортепианная пьеса в MIDI с ровным ритмом.")
        with st.expander("Подробности для разработчика"):
            st.code(_js.get("error", ""))
        _forget_job()
    elif not jobs.alive(_job):
        st.warning("Оркестровка прервалась: сервер перезапускался во время работы. Запустите её ещё раз.")
        _forget_job()
    else:
        _show_progress(_job)

res = st.session_state.result
if res and res.get("mode") == "ensemble":
    import ensemble
    st.markdown(theme.SECTION("III", "Ансамбль"), unsafe_allow_html=True)
    _er = res["report"]
    if res["mp3"]:
        st.audio(res["mp3"], format="audio/mpeg")
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в MuseScore или в проигрывателе.")
    _fg = _er.get("foreign")
    if _fg:
        (st.success if not _fg.get("bad") else st.warning)(
            "Проверка на фальшь: %d из %d нот не совпадают с тем, что в эту долю играет фортепиано." % (_fg.get("bad", 0), _fg.get("total", 0)))
    _pl = _er.get("planner")
    if _pl and _pl.get("used"):
        st.info("Кто решал: модель %s написала план (кто и где ведёт мелодию), программа раздала ноты. Запросов к модели: %d."
                % (", ".join(_pl.get("model_served_by_api") or []) or _pl.get("model_requested") or PROVIDER, len(_pl["rounds"])))
    elif _pl:
        st.warning("Кто решал: программа сама — план модели не подошёл (%s)." % _pl.get("error"))
    else:
        st.info("Кто решал: программа сама, по своим правилам (модель не вызывалась, бесплатно).")
    st.download_button("Скачать ансамбль (MIDI)", open(res["midi"], "rb").read(),
                       file_name="%s_%s.mid" % (res["name"], _er["ensemble"]), mime="audio/midi", use_container_width=True)
    with st.expander("Что сделала программа"):
        st.write(ensemble.text(_er))
        if _pl and _pl.get("used"):
            st.caption("План написала модель: заказано %s, сервис ответил %s; запросов: %d."
                       % (_pl.get("model_requested") or "по умолчанию", ", ".join(_pl.get("model_served_by_api") or ["?"]), len(_pl["rounds"])))
        elif _pl:
            st.warning("План модели не использован: %s. Ансамбль сделан без плана." % _pl.get("error"))
            st.json(_pl)
        if _er.get("foreign_error"):
            st.warning("Проверку на фальшь выполнить не удалось.")
            st.code(_er["foreign_error"])
    res = None
if res and res.get("mode") == "reduction":
    st.markdown(theme.SECTION("III", "Результат переложения"), unsafe_allow_html=True)
    s = res["stats"]
    st.info("Оригинал: %d нот. Фортепиано: правая рука %d, левая %d. "
            "Сохранено высот гармонии: %.0f%%; в %.0f%% моментов звучат все высоты аккорда."
            % (s["notes_in"], s["notes_rh"], s["notes_lh"], 100 * s["pitch_class_coverage"], 100 * s["full_coverage_share"]))
    st.info("Кто решал: модель (%s) выбрала, какие голоса оставить, программа сделала переложение." % PROVIDER
            if res.get("llm") else "Кто решал: программа сама, по своим правилам (модель не вызывалась, бесплатно).")
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
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в программе для музыки.")
    _solo = (((res.get("report") or {}).get("plan_log") or {}).get("solo") or {})
    if _solo.get("instrument"):
        st.caption("Мелодию ведёт: %s." % SOLO_NAMES.get(_solo["instrument"], _solo["instrument"]))
    st.info(analysis_ui.who_line(res, PROVIDER))
    _ok, _line = analysis_ui.verdict_line(res)
    (st.success if _ok else st.warning)("Проверка: %s. Подробности, карта замечаний и исправления — на странице "
                                        "«Анализ и проверки»." % _line)
    _c1, _c2 = st.columns(2)
    with _c1:
        st.page_link("pages/2_Анализ.py", label="Анализ и проверки", icon="🔎", use_container_width=True)
    with _c2:
        st.page_link("pages/1_Проигрыватель.py", label="Ноты в проигрывателе", icon="🎼", use_container_width=True)
    st.markdown("#### Скачать")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        _g = res.get("gate") or {}
        z.writestr(res["name"] + "_контроль_брака.txt",
                   (quality_gate.text(_g) if "ok" in _g else "Контроль брака не выполнился:\n" + str(_g.get("error")))
                   + ("\n\n" + taste_check.text(_g["taste"]) if isinstance(_g.get("taste"), dict) and "score" in _g["taste"] else ""))
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
