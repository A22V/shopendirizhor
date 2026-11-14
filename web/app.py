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
import quality_gate          # noqa: E402
import taste_check           # noqa: E402
import score_notation        # noqa: E402
import piano_review          # noqa: E402
import resources             # noqa: E402
import midi_repair           # noqa: E402
import score_player          # noqa: E402
PROVIDER, PROVIDER_KEY, PROVIDER_MODEL = llm_planner.configured_provider()
LLM_READY = bool(PROVIDER and PROVIDER_KEY and PROVIDER_MODEL)

st.set_page_config(page_title="Оркестратор", page_icon="🎼", layout="centered")

# Барочное оформление (вариант A: голубой дворец, золото, красный бархат): web/theme.py.
# Украшения только в шапке, по краям и в углах листа; текст всегда на сплошном светлом листе.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme                 # noqa: E402
import progress
import jobs              # noqa: E402
import picker            # noqa: E402  своя кнопка выбора файла (веб-сокет вместо канала загрузки)
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
- Загружайте только свои пьесы или пьесы, права на которые у вас есть. Загруженный файл и результат оркестровки хранятся на сервере не дольше 6 часов (чтобы результат не терялся, если на телефоне погас экран), потом удаляются.
- Размер файла: MIDI до 2 МБ (около 2000 нот), MusicXML до 5 МБ. Подпись «5MB per file» под кнопкой загрузки — встроенная надпись Streamlit (по-английски), это общий предел для любого файла.
- Программа не умеет превращать запись живой игры (mp3/wav) в MIDI: нужен MIDI с ровным, квантованным ритмом.
- Пьесы короче 3 тактов и длиннее 100 тактов дают неудовлетворительный результат.
""")

if "result" not in st.session_state:
    st.session_state.result = None

st.markdown("🎼 Есть готовая партитура (MIDI или MusicXML)? [**Партитурный проигрыватель** (новая вкладка)](Проигрыватель): "
            "каждый инструмент на своей нотной строке, звук банком MuseScore, можно выключать инструменты.")
st.page_link("pages/1_Проигрыватель.py", label="Открыть здесь", icon="🎼")

st.markdown(theme.SECTION("I", "Загрузите пьесу"), unsafe_allow_html=True)
# Без фильтра type: на планшетах (iPad, Android) браузер с фильтром ".mid" часто делает MIDI-файлы серыми
# и их нельзя выбрать. Расширение проверяем сами.
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


def any_file(label, key):
    """Файл из своей кнопки (основной путь) или из штатной загрузки Streamlit (запасной путь)."""
    key = "%s_%d" % (key, st.session_state.get("reset_n", 0))      # после «Начать заново» кнопки создаются заново, пустыми
    f = picker.pick(label, key)
    with st.expander("Запасная кнопка загрузки (если основная не сработала)"):
        g = st.file_uploader("Обычная загрузка Streamlit", accept_multiple_files=False, key=key + "_native")
    return f or g


up = checked_midi(any_file("Пьеса: MIDI (.mid) или MusicXML (.musicxml, .xml, .mxl), до 5 МБ", "piece"))
picker.diagnostics()


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


if st.button("🧹 Начать заново (стереть файлы и результат)", help="Забывает загруженные файлы, результат и настройки; "
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
use_llm = False
if LLM_READY:
    use_llm = st.checkbox("Помощь модели (%s): план оркестровки или выбор голосов при переложении" % PROVIDER, value=True,
                          help="Модель пишет план по смыслу фраз, программа проверяет его.")
REVIEW_MODE = "Проверить партитуру (готовый оркестр)"
PIANO_REVIEW_MODE = "Проверить переложение (готовое фортепиано)"
ENSEMBLE_MODE = "Ансамбль: дуэт, трио, квартет (из фортепиано)"
mode = st.radio("Что сделать", ["Оркестровка (из фортепиано)", ENSEMBLE_MODE, "Переложение для фортепиано (из оркестра)", REVIEW_MODE,
                                PIANO_REVIEW_MODE], key="mode_pick")
ens_pick = None
if mode == ENSEMBLE_MODE:
    import ensemble
    _grp = st.radio("Сколько исполнителей", ["Дуэт", "Трио", "Квартет"], horizontal=True, key="ens_group")
    _opts = {e["ru"]: k for k, e in ensemble.ENSEMBLES.items() if e["group"] == _grp}
    ens_pick = _opts[st.selectbox("Состав", list(_opts), key="ens_pick_" + _grp)]
    st.caption("Откуда состав: %s. Каждую партию играет один исполнитель; в составах без фортепиано каждая нота пьесы "
               "отдаётся одному инструменту (так делают мастера: замер по базе IRCAM)." % ensemble.ENSEMBLES[ens_pick]["source"])
    ens_legato = st.checkbox("Связная игра (legato): каждый инструмент тянет ноту до своей следующей ноты", value=False,
                             key="ens_legato",
                             help="У рояля звук продлевает педаль, у смычка педали нет: без связывания между нотами "
                                  "остаются паузы и звучит отрывисто. Высоты и начала нот не меняются. Для танцевальных, "
                                  "отрывистых пьес лучше не включать.")
    ens_mono = st.checkbox("Одноголосная мелодия: перебор аккорда не считать мелодией", value=False, key="ens_mono",
                           help="У рояльных свитков и живых записей аккорд берётся чуть вразнобой, и программа принимала "
                                "нижние звуки такого аккорда за мелодию: скрипка играла по 3–5 нот сразу. С галочкой у "
                                "мелодии остаётся одна нота за раз (верхняя), остальные уходят в сопровождение.")
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
if mode == "Оркестровка (из фортепиано)":
    _lead = st.radio("Кто ведёт мелодию", LEAD_MODES, key="lead_pick",
                     help="Один солист: как в концерте, один инструмент ведёт мелодию от начала до конца, остальные тихо "
                          "аккомпанируют. «Болеро»: солист меняется только между высказываниями темы (примерно через "
                          "8 тактов), внутри высказывания мелодию ведёт один инструмент. Выбирается для каждой пьесы.")
    if _lead == LEAD_MODES[1]:
        solo = SOLO_OPTIONS[st.selectbox("Солирующий инструмент", list(SOLO_OPTIONS), key="solo_pick",
                                         help="Фортепиано и орган играют пьесу целиком, оркестр их поддерживает.")]
    elif _lead == LEAD_MODES[2]:
        solo = "Bolero"
    perc = st.checkbox("Лёгкие ударные для ритма (как в эстрадно-симфоническом оркестре)", value=False, key="perc_pick",
                       help="Тихая бочка, обод малого барабана и хай-хэт по размеру такта; громкость следует фразам. "
                            "Ноты оркестра не меняются. Ударные есть в MIDI и MP3, в нотах их нет.")
    plan_text = ""
    with st.expander("План оркестровки от другой модели (Claude, ChatGPT и др.): скачать задание и вставить ответ"):
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
            except Exception as _e:
                st.error("Это не похоже на план (JSON): %s" % _e)
                plan_text = ""
else:
    perc = False
    plan_text = ""
orig_up = None
if mode == PIANO_REVIEW_MODE:
    st.caption("Вверху загрузите MIDI рояля. По желанию добавьте оркестровый оригинал: тогда программа посчитает, "
               "сколько гармонии оркестра сохранилось в переложении.")
    orig_up = checked_midi(any_file("Оркестровый оригинал (необязательно, MIDI или MusicXML)", "orig_up"), "Оригинал")
go = st.button({"Оркестровка (из фортепиано)": "Создать оркестровку", REVIEW_MODE: "Проверить партитуру",
                PIANO_REVIEW_MODE: "Проверить переложение", ENSEMBLE_MODE: "Создать ансамбль"}.get(mode, "Создать переложение"),
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
            gate["taste"] = taste_check.check(src, stem + ".mid", solo=bool(solo), one_lead=_tf.one_lead_enabled())
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


FIX_NO_AUTO = {   # замечания без автоисправления: почему (простыми словами)
    "K1": "ноты вне удобного диапазона: исправлять надо выбором другого инструмента — это делает план, а не готовый файл",
    "K3": "«стена звука» и скачки состава: прореживание включается до расстановки нот (ORCH_THIN), в готовом файле его нет",
    "K5": "первая скрипка молчит: так бывает задумано (мелодия у других), решает слушатель",
    "HM05": "параллельные октавы: нужна переделка голосов, автоматически пока не умеем",
    "HM32": "параллельные квинты: нужна переделка голосов, автоматически пока не умеем",
    "HM32P": "эти параллельные квинты есть в самих фортепианных нотах; программа их только перенесла, исправлять нечего",
    "QX04": "длинные ноты духовых без передышки: решается в плане",
    "QX05": "много унисонных удвоений: решается в плане",
    "QX06": "инструмент не играет: в оркестровке это исправляют защиты плана (ORCH_BASS, ORCH_WINDS)",
}


def show_fix(res, src_midi, key):
    """Раздел «Исправление»: для каждого замечания, у которого есть автоисправление, — кнопка. Каждая кнопка делает
    НОВЫЙ файл (исходный не меняется) и даёт его послушать и скачать; рецензия пересчитывается."""
    review = res.get("review") or {}
    codes = [f[1] for f in review.get("findings", [])]
    st.markdown(theme.SECTION("IV", "Исправление"), unsafe_allow_html=True)
    if not codes:
        st.caption("Замечаний нет — исправлять нечего.")
        return
    fixable = [c for c in score_fix.FIXES if c in codes]
    st.caption("Каждая кнопка делает НОВЫЙ файл; ваш исходный остаётся как был. Сначала послушайте исправленный вариант, "
               "потом решайте, какой оставить.")
    if not fixable:
        st.info("Для найденных замечаний автоматического исправления пока нет.")
    for code in fixable:
        label, fn, approved = score_fix.FIXES[code]
        st.markdown("**[%s]** %s%s" % (code, label, "" if approved else " — не проверено на слух, это проба"))
        if st.button("Исправить [%s]" % code, key="fix_%s_%s" % (key, code), use_container_width=True):
            try:
                base = os.path.splitext(src_midi)[0]
                _fx = base + "_fix_%s.mid" % code
                _chg = fn(src_midi, _fx)
                _rv2 = score_review.review(_fx)
                _mp3f = None
                try:
                    _mp3f = audio_tools.render_mp3(_fx, base + "_fix_%s.mp3" % code)
                except Exception:
                    _mp3f = None
                res.setdefault("fixes", {})[code] = {
                    "midi": _fx, "changes": _chg, "mp3": _mp3f if _mp3f and os.path.exists(_mp3f) else None,
                    "before": len(review.get("findings", [])), "after": len(_rv2["findings"]),
                    "left": [f[3] for f in _rv2["findings"] if f[1] == code]}
                st.session_state.result = res
            except Exception:
                res.get("fixes", {}).pop(code, None)
                st.error("Не удалось исправить файл. Исходный файл не изменён.")
                with st.expander("Подробности для разработчика"):
                    st.code(traceback.format_exc())
        _fix = (res.get("fixes") or {}).get(code)
        if _fix:
            if _fix["changes"]:
                st.success("Что изменено:")
                for _c in _fix["changes"]:
                    st.write("• " + _c)
            else:
                st.info("Исправлять нечего: подходящих мест не найдено.")
            st.write("Замечаний рецензента: было %d, стало %d." % (_fix["before"], _fix["after"]))
            for _l in _fix["left"]:
                st.caption("Осталось: " + _l)
            if _fix["mp3"]:
                st.audio(_fix["mp3"])
            with open(_fix["midi"], "rb") as _fh:
                st.download_button("Скачать исправленный MIDI [%s]" % code, _fh.read(),
                                   file_name=res["name"] + "_исправлено_%s.mid" % code, mime="audio/midi",
                                   use_container_width=True, key="dl_fix_%s_%s" % (key, code))
            if _fix["mp3"]:
                with open(_fix["mp3"], "rb") as _fh:
                    st.download_button("Скачать исправленный MP3 [%s]" % code, _fh.read(),
                                       file_name=res["name"] + "_исправлено_%s.mp3" % code, mime="audio/mpeg",
                                       use_container_width=True, key="dl_fixmp3_%s_%s" % (key, code))
    other = sorted({c for c in codes if c not in score_fix.FIXES})
    if other:
        with st.expander("Почему остальные замечания не исправляются автоматически"):
            for c in other:
                st.write("**[%s]** %s" % (c, FIX_NO_AUTO.get(c, "автоисправления пока нет")))


def show_gate(gate):
    """Контроль брака (src/quality_gate.py): объективные ошибки по сравнению с оригиналом. Ошибку не прячет."""
    st.markdown("#### Контроль брака")
    if not gate:
        return
    if gate.get("error"):
        st.warning("Контроль брака не выполнился. Причина ниже.")
        with st.expander("Подробности для разработчика"):
            st.code(gate["error"])
        return
    if gate["ok"]:
        st.success("Брака не найдено: нет фальшивых нот, мелодия на месте и не скачет, играют все инструменты.")
    else:
        st.error("Есть брак (%d). Такую оркестровку не стоит показывать как готовую." % len(gate["defects"]))
    for code, text, status in gate["defects"]:
        st.markdown("**[%s]** %s" % (code, text))
        st.caption("Статус: " + status)
    for code, text, status in gate["warnings"]:
        st.markdown("**[%s, предупреждение]** %s" % (code, text))
        st.caption("Статус: " + status)
    st.caption("Контроль считает, а не слушает: «брака нет» не значит «звучит хорошо». Судья звучания — слушатель.")
    tc = gate.get("taste")
    if tc:
        st.markdown("#### Проверка по вашему вкусу")
        if tc.get("error"):
            st.warning("Проверка по вкусу не выполнилась.")
            with st.expander("Подробности для разработчика"):
                st.code(tc["error"])
        else:
            names = {c: n for c, n, _ in taste_check.TASTE}
            why = {c: w for c, _, w in taste_check.TASTE}
            (st.success if not tc["failed"] else st.warning)("Выполнено %s пунктов." % tc["score"])
            for c, msg in tc["failed"]:
                st.markdown("**✗ [%s] %s** — %s" % (c, names[c], msg))
                st.caption("Ваш отзыв: " + why[c])
            st.caption("Выполнены: " + ", ".join("%s %s" % (c, names[c]) for c in tc["passed"]))


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
                # дорожки «Track 1» / без названия / по-русски: рецензент узнаёт инструменты по названию или номеру
                _named, _renamed = score_player.name_tracks(up.getvalue())
                if _renamed:
                    st.caption("Инструменты узнаны по дорожкам: " + "; ".join(_renamed) + ".")
                with open(_src, "wb") as _f:
                    _f.write(_named)
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
                st.error("Не удалось проверить файл: %s. Нужен MIDI оркестра (несколько дорожек с инструментами: "
                         "флейта, гобой, кларнет, фагот, валторна, скрипки, альт, виолончель, контрабас)."
                         % (sys.exc_info()[1] or "причина ниже"))
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
                _rep = ensemble.arrange(_src, _stem, ens_pick, plan=_plan, legato=ens_legato, mono=ens_mono)
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
if res and res.get("mode") == "review":
    st.markdown(theme.SECTION("III", "Рецензия на партитуру"), unsafe_allow_html=True)
    st.caption("Программа ничего не исправляет: она показывает, что нашла, и честно называет, чем подтверждено каждое правило.")
    show_review(res["review"])
    st.download_button("Скачать карту замечаний (HTML, открывается в браузере)",
                       score_review.map_html(res["review"], standalone=True).encode("utf-8"),
                       file_name=res["name"] + "_карта_замечаний.html", mime="text/html", use_container_width=True)
    show_fix(res, res["src"], "review")
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
if res and res.get("mode") == "ensemble":
    import ensemble
    st.markdown(theme.SECTION("III", "Ансамбль"), unsafe_allow_html=True)
    _er = res["report"]
    st.info(ensemble.text(_er))
    _pl = _er.get("planner")
    if _pl and _pl.get("used"):
        st.caption("План написала модель: заказано %s, сервис ответил %s; запросов: %d."
                   % (_pl.get("model_requested") or "по умолчанию", ", ".join(_pl.get("model_served_by_api") or ["?"]), len(_pl["rounds"])))
    elif _pl:
        st.warning("План модели не использован: %s. Ансамбль сделан без плана (мелодию ведёт верхний инструмент)." % _pl.get("error"))
        with st.expander("Что ответила модель (для разработчика)"):
            st.json(_pl)
    _fg = _er.get("foreign")
    if _fg:
        st.caption("Проверка на фальшь: %d из %d нот ансамбля не совпадают с тем, что в эту долю играет фортепиано."
                   % (_fg.get("bad", 0), _fg.get("total", 0)))
    elif _er.get("foreign_error"):
        st.warning("Проверку на фальшь выполнить не удалось.")
        with st.expander("Подробности для разработчика"):
            st.code(_er["foreign_error"])
    if res["mp3"]:
        st.audio(res["mp3"], format="audio/mpeg")
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в MuseScore или в партитурном проигрывателе.")
    st.download_button("Скачать ансамбль (MIDI)", open(res["midi"], "rb").read(),
                       file_name="%s_%s.mid" % (res["name"], _er["ensemble"]), mime="audio/midi", use_container_width=True)
    st.caption("Ноты по строкам и звук в браузере: откройте скачанный MIDI в партитурном проигрывателе (ссылка вверху страницы).")
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
    # Партитурный проигрыватель (web/pages/1_Проигрыватель.py): ноты по станам и звук в браузере
    _pj = st.session_state.get("job")
    if _pj:
        st.markdown("🎼 [**Открыть в партитурном проигрывателе** (новая вкладка)](Проигрыватель?job=%s)" % _pj)
        st.page_link("pages/1_Проигрыватель.py", label="…или открыть здесь", icon="🎼")
    if res["mp3"]:
        st.audio(res["mp3"], format="audio/mpeg")
        _sf = os.path.basename(audio_tools.LAST_SOUNDFONT or "")
        if _sf:
            st.caption("Звук сделан набором инструментов «%s»%s." % (os.path.splitext(_sf)[0],
                       "" if "MS Basic" in _sf else " (маленький набор: звучит проще, чем в MuseScore)"))
    else:
        st.info("Звуковая запись сейчас недоступна на сервере. Скачайте MIDI и откройте его в программе для музыки.")
    _rs = (res.get("report") or {}).get("resources")
    if _rs:
        with st.expander("Ресурсы сервера (время и память)"):
            st.write(resources.text(_rs) + ".")
            _tm = (res.get("report") or {}).get("timings_s") or {}
            for _k, _v in (_rs.get("memory_after_step") or {}).items():
                st.write("• шаг «%s»: %s с, память приложения после шага %s МБ" % (
                    _k, _tm.get(_k, "?"), _v.get("rss_mb", "?")))
            st.caption("Цифры для вопроса «хватает ли облаку памяти». Они же лежат в report.json внутри ZIP.")

    if res.get("llm_log"):
        _pi = (res.get("report") or {}).get("planner") or {}
        st.info("План написала модель %s. Проверок плана: %d. Заказано: %s; сервис ответил: %s." % (
            PROVIDER, len(res["llm_log"]), _pi.get("model_requested") or "(не задано)",
            ", ".join(_pi.get("model_served_by_api") or []) or "—"))
    issues = res["issues"]
    errors = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warning"]
    _solo = (((res.get("report") or {}).get("plan_log") or {}).get("solo") or {})
    if _solo.get("instrument"):
        st.info("Мелодию ведёт: %s." % SOLO_NAMES.get(_solo["instrument"], _solo["instrument"]))
        if _solo.get("changes"):
            with st.expander("Кто где солирует и кто молчит в сопровождении"):
                for _c in _solo["changes"]:
                    st.write("• " + _c)
    show_gate(res.get("gate"))
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

    if res.get("review"):
        show_fix(res, res["stem"] + ".mid", "orch")

    with st.expander("Технические замечания проверки (английские коды)"):
        if not issues:
            st.write("Замечаний нет.")
        for sev, rid, _, msg in issues:
            st.write("**%s** %s: %s" % ("Ошибка" if sev == "error" else "Замечание", rid, msg))

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
