"""Страница «Анализ и проверки»: показ контроля брака, проверки по вкусу, рецензии, карты замечаний, нот с
пометками и исправлений. Вынесено из web/app.py 2026-11-21 (просьба пользователя: главная без нагромождений)."""
import os, io, sys, tempfile, traceback, base64
import streamlit as st

import theme, progress                                         # noqa: E401
import audio_tools, score_review, score_fix, quality_gate, taste_check, score_notation, piano_review  # noqa: E401
import resources, score_player                                 # noqa: E401


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



def run_score_review(up):
    """Проверка готового оркестра (MIDI). Возвращает результат для show_score_review или None (ошибка показана)."""
    if up.size > 2 * 1024 * 1024:
        st.error("Файл больше 2 МБ.")
        return None
    _prog = progress.Steps([("review", "рецензия"), ("notes", "ноты с пометками")], progress.midi_seconds(up.getvalue()))
    with st.spinner("Проверяю партитуру..."):
        try:
            _work = tempfile.mkdtemp(prefix="review_")
            _src = os.path.join(_work, "score.mid")
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
            return {"mode": "review", "review": _rv, "name": os.path.splitext(up.name)[0], "src": _src}
        except Exception:
            _prog.abort()
            st.error("Не удалось проверить файл: %s. Нужен MIDI оркестра (несколько дорожек с инструментами: "
                     "флейта, гобой, кларнет, фагот, валторна, скрипки, альт, виолончель, контрабас)."
                     % (sys.exc_info()[1] or "причина ниже"))
            with st.expander("Подробности для разработчика"):
                st.code(traceback.format_exc())
            return None


def run_piano_review(up, orig_up):
    if up.size > 2 * 1024 * 1024 or (orig_up is not None and orig_up.size > 2 * 1024 * 1024):
        st.error("Файл больше 2 МБ.")
        return None
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
            return {"mode": "piano_review", "review": _rv, "name": os.path.splitext(up.name)[0]}
        except Exception:
            _prog.abort()
            st.error("Не удалось проверить файл. Нужен MIDI фортепиано (одна или две дорожки).")
            with st.expander("Подробности для разработчика"):
                st.code(traceback.format_exc())
            return None


def show_score_review(res):
    st.markdown(theme.SECTION("II", "Рецензия на партитуру"), unsafe_allow_html=True)
    st.caption("Программа ничего не исправляет: она показывает, что нашла, и честно называет, чем подтверждено каждое правило.")
    show_review(res["review"])
    st.download_button("Скачать карту замечаний (HTML, открывается в браузере)",
                       score_review.map_html(res["review"], standalone=True).encode("utf-8"),
                       file_name=res["name"] + "_карта_замечаний.html", mime="text/html", use_container_width=True)
    show_fix(res, res["src"], "review")


def show_piano_review(res):
    st.markdown(theme.SECTION("II", "Проверка переложения"), unsafe_allow_html=True)
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


def show_orch_details(res, provider=None):
    """Всё о готовой оркестровке, кроме звука и скачивания (они на главной): кто писал план, контроль брака и вкус,
    проверка валидатора, фразы, рецензия с картой и нотами, исправления, технические коды, ресурсы сервера."""
    rep = res.get("report") or {}
    st.markdown(theme.SECTION("I", "Пьеса «%s»" % res.get("name", "")), unsafe_allow_html=True)
    if res.get("mp3"):
        st.audio(res["mp3"], format="audio/mpeg")
    _pi = rep.get("planner") or {}
    if _pi.get("provider") == "вставлен вручную":
        st.caption("План: вставлен вручную. Модель в этот раз не вызывалась.")
    elif res.get("llm_log"):
        st.caption("План написала модель %s. Проверок плана: %d. Заказано: %s; сервис ответил: %s." % (
            _pi.get("provider") or provider or "?", len(res["llm_log"]), _pi.get("model_requested") or "(не задано)",
            ", ".join(_pi.get("model_served_by_api") or []) or "—"))
    else:
        st.caption("План: встроенный планировщик программы (модель не вызывалась).")
    _solo = ((rep.get("plan_log") or {}).get("solo") or {})
    if _solo.get("changes"):
        with st.expander("Кто где солирует и кто молчит в сопровождении"):
            for _c in _solo["changes"]:
                st.write("• " + _c)
    show_gate(res.get("gate"))
    issues = res.get("issues") or []
    errors = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warning"]
    st.markdown("#### Проверка правил (валидатор)")
    if errors:
        st.error("Найдены серьёзные ошибки: %d. Результат не рекомендуется использовать." % len(errors))
    elif warns:
        st.warning("Проверка пройдена с замечаниями (%d). Коды в разделе внизу." % len(warns))
    else:
        st.success("Проверка пройдена без замечаний.")

    st.markdown(theme.SECTION("II", "Фразы и состав"), unsafe_allow_html=True)
    rows = []
    for ph in (res.get("plan") or {}).get("phrases", []):
        rows.append({"Такты": "%d–%d" % tuple(ph["bars"]), "Тип": ph.get("kind", ""),
                     "Окраска мелодии": ph.get("color") or "—", "Громкость": ph.get("level", ""),
                     "Кульминация": "да" if ph.get("climax") else ""})
    if rows:
        st.table(rows)

    st.markdown(theme.SECTION("III", "Рецензия, карта и ноты с пометками"), unsafe_allow_html=True)
    show_review(res.get("review"))
    if res.get("review"):
        show_fix(res, res["stem"] + ".mid", "orch")

    with st.expander("Технические замечания проверки (английские коды)"):
        if not issues:
            st.write("Замечаний нет.")
        for sev, rid, _, msg in issues:
            st.write("**%s** %s: %s" % ("Ошибка" if sev == "error" else "Замечание", rid, msg))
    _rs = rep.get("resources")
    if _rs:
        with st.expander("Ресурсы сервера (время и память)"):
            st.write(resources.text(_rs) + ".")
            _tm = rep.get("timings_s") or {}
            for _k, _v in (_rs.get("memory_after_step") or {}).items():
                st.write("• шаг «%s»: %s с, память приложения после шага %s МБ" % (_k, _tm.get(_k, "?"), _v.get("rss_mb", "?")))


def verdict_line(res):
    """Итог одной строкой для главной страницы: брак, вкус, валидатор."""
    g = res.get("gate") or {}
    parts = []
    if "ok" in g:
        parts.append("брака нет" if g["ok"] else "есть брак (%d)" % len(g["defects"]))
    t = g.get("taste")
    if isinstance(t, dict) and "score" in t:
        parts.append("по вашему вкусу %s" % t["score"])
    errs = sum(1 for i in (res.get("issues") or []) if i[0] == "error")
    if errs:
        parts.append("ошибок правил: %d" % errs)
    ok = g.get("ok") and not errs
    return ok, "; ".join(parts) or "проверка не выполнилась"
