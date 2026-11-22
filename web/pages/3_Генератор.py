"""
Страница «Генератор» (2026-11-21): фортепианная пьеса по описанию словами (src/composer.py).
Модель сочиняет фортепиано; оркестр, ансамбль или солиста делает основная программа — кнопка «Отправить».
Каждое нажатие «Сочинить» / «Ещё вариант» — платный запрос к модели из Secrets (PLANNER_PROVIDER / PLANNER_MODEL).
"""
import os, sys, time, traceback
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common                     # noqa: E402  (первым: секреты → окружение)
import jobs                       # noqa: E402
import composer, audio_tools, llm_planner, style_analyze   # noqa: E402,E401

st.set_page_config(page_title="Генератор пьес", page_icon="✒️", layout="centered")
common.decorate("Генератор", "фортепианная пьеса по вашему описанию")
common.nav("Генератор")

def _reset_gen():
    """«Начать заново» на этой странице: забыть описание, образец, сочинённую пьесу и её задание на сервере.
    Пьесу, уже отправленную на главную (gen_piece), и файлы главной страницы не трогаем."""
    j = st.session_state.get("gen_job")
    try:
        q = st.query_params.get("gen")
        j = j or (q if isinstance(q, str) else None)
    except Exception:
        pass
    if j:
        jobs.forget(j)
    n = st.session_state.get("gen_reset_n", 0) + 1
    for k in list(st.session_state.keys()):
        if (k.startswith("gen_") and k != "gen_piece") or "gen_ref_file" in k:
            del st.session_state[k]
    st.session_state["gen_reset_n"] = n           # новая кнопка выбора образца, пустая
    try:
        del st.query_params["gen"]
    except Exception:
        pass


st.button("🧹 Начать заново", on_click=_reset_gen, key="gen_reset_btn",
          help="Очищает описание, образец и сочинённую пьесу на этой странице; с сервера стирается её задание. "
               "Пьеса, уже отправленная на главную, и файлы на вашем телефоне не трогаются.")

PROVIDER, KEY, MODEL = llm_planner.configured_provider()
READY = bool(PROVIDER and KEY and MODEL)
AUTO = "на выбор модели"

with st.expander("Как это работает"):
    st.markdown(
        "Модель (%s) сочиняет **фортепианную** пьесу: мелодия в правой руке, сопровождение в левой. Программа "
        "переводит её в MIDI и проверяет: число тактов, тональность, удобство для рук пианиста. Если что-то серьёзно "
        "не так, модель один раз переписывает пьесу. Потом вы слушаете и, если нравится, отправляете пьесу на "
        "главную: в оркестр (можно с солистом), в ансамбль или оставляете как есть.\n\n"
        "- Каждое «Сочинить» и «Ещё вариант» — платный запрос (у Haiku обычно меньше цента; второй запрос — только "
        "если первая попытка с ошибками).\n"
        "- Модель сочиняет грамотно, но просто. Лучше всего получаются пьесы на 16–32 такта.\n"
        "- Программа не слышит музыку: хорошо ли звучит, решаете вы." % (MODEL or "не настроена"))

if not READY:
    st.warning("Модель не настроена: в Secrets нужны PLANNER_PROVIDER, PLANNER_MODEL и ключ. Без неё генератор не работает.")

st.markdown(common.theme.SECTION("I", "Опишите пьесу"), unsafe_allow_html=True)
def _put_template():
    st.session_state["gen_req"] = composer.TEMPLATE


def _put_style(data, name, n_bars):
    """Разбор образца -> шаблон в окне запроса; сам образец остаётся в сессии для проверки похожести."""
    import tempfile
    p = os.path.join(tempfile.mkdtemp(prefix="style_"), "ref.mid")
    open(p, "wb").write(data)
    title = os.path.splitext(name)[0].replace("_", " ")
    try:
        res = style_analyze.analyze(p, title)
    except Exception as e:
        st.session_state["gen_style_err"] = "%s: %s" % (type(e).__name__, e)
        return
    st.session_state["gen_req"] = style_analyze.template(res, n_bars)
    st.session_state["gen_ref"] = {"name": name, "title": title, "data": data, "bars": res["bars"],
                                   "key": style_analyze.key_text(res), "calm": res["rhythm_calm"]}
    st.session_state.pop("gen_style_err", None)


def _drop_style():
    st.session_state.pop("gen_ref", None)


with st.expander("🎼 Сочинить в стиле известной пьесы (по образцу)", expanded=bool(st.session_state.get("gen_ref"))):
    st.caption("Загрузите пьесу для фортепиано (MIDI или MusicXML). Программа сама, без модели и бесплатно, разберёт её "
               "«почерк»: тональность, темп, форму, аккорды, ритм мелодии, фактуру — и напишет шаблон. Модель получит "
               "только это описание, а не ноты образца, и сочинит новую пьесу. Потом программа проверит, что мелодия и "
               "аккорды не списаны с образца.")
    ref_f = common.checked_midi(common.any_file("Образец: MIDI или MusicXML", "gen_ref_file_%d" % st.session_state.get("gen_reset_n", 0)), "Образец")
    sb = st.selectbox("Длина новой пьесы (тактов)", [8, 16, 24, 32, 48], index=2, key="gen_style_bars")
    if ref_f is not None:
        st.button("🔍 Разобрать образец и написать шаблон", on_click=_put_style,
                  args=(ref_f.getvalue(), ref_f.name, sb), use_container_width=True, key="gen_style_go")
    if st.session_state.get("gen_style_err"):
        st.error("Образец не удалось разобрать: " + st.session_state["gen_style_err"])
    _ref = st.session_state.get("gen_ref")
    if _ref:
        st.success("Образец «%s» разобран: %d тактов, %s. Шаблон — в окне ниже, его можно поправить." % (
            _ref["title"], _ref["bars"], _ref["key"]))
        st.button("Убрать образец (не проверять похожесть)", on_click=_drop_style, key="gen_style_drop")


st.button("📋 Вставить пример шаблона", on_click=_put_template, key="gen_tpl",
          help="Шаблон с паспортом, разделами по тактам, аккордами и запретами. Замените своё и сочиняйте.")
req = st.text_area("Что сочинить", key="gen_req", height=220,
                   placeholder="Коротко («нежный вальс в духе Шопена, ля минор, для флейты с оркестром») "
                               "или по шаблону: [Паспорт], разделы с тактами и аккордами, [Запреты]")
TPL = composer.template_params(req)
if TPL:
    st.caption("Шаблон узнан: %s. Берётся то, что в [Паспорт]." % ", ".join(
        x for x in ("%d тактов" % TPL["bars"] if TPL.get("bars") else "", TPL.get("key") or "",
                    "размер " + TPL["time"] if TPL.get("time") else "",
                    "темп %d" % TPL["tempo"] if TPL.get("tempo") else "") if x) +
               " Поля длины, размера, тональности и темпа скрыты: при шаблоне они не нужны.")
bars, meter, key, tempo = 16, AUTO, "", AUTO
if not TPL:     # при шаблоне поля скрыты: всё берётся из [Паспорт]
    c1, c2 = st.columns(2)
    with c1:
        bars = st.selectbox("Длина (тактов)", [8, 16, 24, 32], index=1, key="gen_bars")
        meter = st.selectbox("Размер", [AUTO, "4/4", "3/4", "6/8", "2/4"], key="gen_meter")
    with c2:
        key = st.text_input("Тональность", key="gen_key", placeholder=AUTO,
                            help="Например: ре мажор, ля минор, Bb major. Пусто — выберет модель по описанию.")
        tempo = st.selectbox("Темп (четвертей в минуту)", [AUTO, 60, 72, 84, 96, 108, 120, 138], key="gen_tempo")


def _work(req, tpl, bars, key, meter, tempo, variant, ref=None):
    """Сочинение в фоне на сервере (web/jobs.py): не теряется, если на телефоне погас экран.
    ref — образец (данные MIDI): новая пьеса проверяется на похожесть, найденные заимствования уходят модели."""
    def fn(prog, work):
        prog.go("compose")
        n0 = len(llm_planner.USAGE)
        kw = {}
        if ref:
            rp = os.path.join(work, "ref.mid")
            open(rp, "wb").write(ref["data"])
            rres = style_analyze.analyze(rp, ref["title"])
            kw = {"extra_check": lambda m: style_analyze.similarity(rres, m), "skip_rhythm": bool(ref.get("calm"))}
        if tpl:     # шаблон: тактов, тональность, размер и темп — из [Паспорт]
            r = composer.compose(req, bars=tpl.get("bars") or bars, key=tpl.get("key"), time_sig=tpl.get("time"),
                                 tempo=tpl.get("tempo"), variant=variant, out_dir=work, **kw)
        else:
            r = composer.compose(req, bars=bars, key=key or None, time_sig=None if meter == AUTO else meter,
                                 tempo=None if tempo == AUTO else int(tempo), variant=variant, out_dir=work, **kw)
        r["ref_title"] = ref["title"] if ref else None
        r["usage"] = llm_planner.USAGE[n0:]
        prog.go("mp3")
        try:
            r["mp3"] = open(audio_tools.render_mp3(r["midi"], os.path.splitext(r["midi"])[0] + ".mp3"), "rb").read()
        except Exception:
            r["mp3"] = None
        r["data"] = open(r["midi"], "rb").read()
        r["request"], r["variant"] = req, variant
        return r
    return fn


def _compose(variant):
    # каждое нажатие — новый платный запрос, поэтому в номер задания входит время нажатия
    ref = st.session_state.get("gen_ref")
    params = {"gen": True, "tpl": TPL, "bars": bars, "key": key.strip(), "meter": meter, "tempo": tempo,
              "variant": variant, "t": time.time(), "ref": ref["name"] if ref else None}
    jk = jobs.key(req.encode("utf-8"), params)
    jobs.start(jk, _work(req, TPL, bars, key.strip(), meter, tempo, variant, ref),
               [("compose", "модель сочиняет"), ("mp3", "запись MP3")], 60.0)
    st.session_state["gen_job"], st.session_state["gen_res"] = jk, None
    try:
        st.query_params["gen"] = jk
    except Exception:
        pass


@st.fragment(run_every=3)
def _gen_progress(jk):
    js = jobs.status(jk)
    if js is None or js.get("state") in ("done", "error") or not jobs.alive(jk):
        st.rerun()
    sec = int(time.time() - float(js.get("started") or time.time()))
    st.info("%s… прошло %d:%02d. Сочинение идёт на сервере: можно погасить экран или уйти в другое приложение — "
            "когда вернётесь, пьеса будет здесь." % (
                "Модель сочиняет" if js.get("step") == "compose" else "Записываю MP3", sec // 60, sec % 60))


if st.button("✒️ Сочинить (платный запрос)", disabled=not READY or not req.strip(), use_container_width=True, key="gen_go"):
    st.session_state["gen_n"] = st.session_state.get("gen_n", 0) + 1
    _compose(st.session_state["gen_n"])

# фоновое задание: показать ход или забрать готовую пьесу (и после возвращения на страницу)
try:
    _qp = st.query_params.get("gen")
except Exception:
    _qp = None
_gj = st.session_state.get("gen_job") or (_qp if isinstance(_qp, str) else None)
if _gj and st.session_state.get("gen_loaded") != _gj:
    _js = jobs.status(_gj)

    def _drop():
        st.session_state["gen_job"] = None
        try:
            del st.query_params["gen"]
        except Exception:
            pass
    if _js is None:
        st.info("Прежнее сочинение уже не хранится на сервере (прошло больше 6 часов или приложение перезапускалось).")
        _drop()
    elif _js.get("state") == "done":
        try:
            st.session_state["gen_res"] = jobs.load(_gj)
            st.session_state["gen_loaded"] = _gj
        except Exception:
            st.error("Готовую пьесу не удалось прочитать. Сочините ещё раз.")
            _drop()
    elif _js.get("state") == "error":
        _err = _js.get("error", "")
        st.error("Не получилось сочинить пьесу: %s" % (_err.strip().splitlines() or ["?"])[-1])
        with st.expander("Подробности для разработчика"):
            st.code(_err)
        _drop()
    elif not jobs.alive(_gj):
        st.warning("Сочинение прервалось: сервер перезапускался во время работы. Нажмите «Сочинить» ещё раз.")
        _drop()
    else:
        _gen_progress(_gj)

r = st.session_state.get("gen_res")
if r:
    inf = r["info"]
    st.markdown(common.theme.SECTION("II", "«%s»" % inf["title"]), unsafe_allow_html=True)
    st.caption("Вариант %d · %d тактов · размер %s · темп %d · %s · около %d с" % (
        r["variant"], inf["bars"], inf["time"], inf["tempo"], inf.get("key") or "тональность не указана", inf["seconds"]))
    if r.get("mp3"):
        st.audio(r["mp3"], format="audio/mpeg")
    if r["serious"]:
        st.warning("Проверка: есть замечания — " + " ".join(r["serious"]))
    else:
        st.success("Проверка: такты, тональность и руки пианиста в порядке." if not r["minor"] else
                   "Проверка: серьёзных замечаний нет (мелкие ниже).")
    if r.get("extra"):
        (st.warning if r["extra"]["melody_run"] >= style_analyze.MEL_RUN_MAX or
         r["extra"]["chord_run"] >= style_analyze.CHORD_RUN_MAX else st.info)(
            "Образец «%s». %s" % (r.get("ref_title") or "?", style_analyze.similarity_text(r["extra"])))
    if r["minor"] or r["fixes"]:
        with st.expander("Мелкие замечания и что программа поправила"):
            for m in r["minor"]:
                st.write("• " + m)
            for f in r["fixes"]:
                st.write("• исправлено: " + f)
    st.caption("Запросов к модели: %d; ответила модель: %s." % (sum(1 + x.get("continued", 0) for x in r["rounds"]), ", ".join(r.get("served") or ["?"])))
    _u = r.get("usage") or []
    if _u:
        st.caption("Токены: вход %d (из них прочитано из кэша %d, записано в кэш %d), выход %d (вместе с размышлениями "
                   "модели; выход стоит дороже входа)." % (
                       sum(x["input_tokens"] + x["cache_read_input_tokens"] + x["cache_creation_input_tokens"] for x in _u),
                       sum(x["cache_read_input_tokens"] for x in _u), sum(x["cache_creation_input_tokens"] for x in _u),
                       sum(x["output_tokens"] for x in _u)))
    fname = "%s.mid" % (inf["title"] or "Пьеса").replace("/", "_")[:60]
    st.download_button("Скачать пьесу (MIDI)", r["data"], file_name=fname, mime="audio/midi", use_container_width=True)
    if st.button("🎲 Ещё вариант (платный запрос)", disabled=not READY, use_container_width=True, key="gen_more"):
        st.session_state["gen_n"] = st.session_state.get("gen_n", 0) + 1
        _compose(st.session_state["gen_n"])
        st.rerun()

    st.markdown(common.theme.SECTION("III", "Что сделать с пьесой"), unsafe_allow_html=True)
    import ensemble
    mode, what = composer.suggest_target(r["request"])
    SOLO_RU = {"Flute": "Флейта (нежная, невысокая)", "Clarinet": "Кларнет", "Oboe": "Гобой", "Cello": "Виолончель",
               "Violin I": "Скрипка"}
    opts = ["Оркестр", "Оркестр с солистом", "Оркестр, солисты как в «Болеро»", "Ансамбль"]
    default = 3 if mode == "ensemble" else 2 if what == "Bolero" else 1 if what else 0
    target = st.radio("Куда отправить", opts, index=default, key="gen_target")
    solo_ru = ens_key = None
    if target == opts[1]:
        names = list(SOLO_RU.values())
        solo_ru = st.selectbox("Солист", names, index=names.index(SOLO_RU[what]) if what in SOLO_RU else 0, key="gen_solo")
    if target == opts[3]:
        ens_names = {e["ru"]: k for k, e in ensemble.ENSEMBLES.items()}
        keys = list(ens_names)
        idx = keys.index(ensemble.ENSEMBLES[what]["ru"]) if mode == "ensemble" and what in ensemble.ENSEMBLES else 0
        ens_key = ens_names[st.selectbox("Состав", keys, index=idx, key="gen_ens")]
    if mode != "piano":
        st.caption("Подсказано по словам вашего описания; можно выбрать другое.")
    if st.button("Отправить на главную", use_container_width=True, key="gen_send"):
        st.session_state["gen_piece"] = {"name": fname, "data": r["data"]}
        if target == opts[3]:
            st.session_state["mode_pick"] = "Ансамбль: дуэт, трио, квартет (из фортепиано)"
            grp = ensemble.ENSEMBLES[ens_key]["group"]
            st.session_state["ens_group"] = grp
            st.session_state["ens_pick_" + grp] = ensemble.ENSEMBLES[ens_key]["ru"]
        else:
            st.session_state["mode_pick"] = "Оркестровка (из фортепиано)"
            st.session_state["lead_pick"] = ["Оркестр сам распределяет мелодию", "Один солист на всю пьесу",
                                             "Меняющиеся солисты, как в «Болеро»"][opts.index(target) if target != opts[0] else 0]
            if solo_ru:
                st.session_state["solo_pick"] = solo_ru
        st.switch_page("app.py")
st.markdown(common.theme.FOOTER(), unsafe_allow_html=True)
