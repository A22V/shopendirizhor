"""
Фоновые задания оркестровки (2026-11-07). Причина: на телефоне, когда гаснет экран или пользователь уходит в другое
приложение, браузер обрывает связь, страница открывается заново и работа терялась (а с DeepSeek — оплачивалась снова).

Как устроено:
  * Работа идёт в отдельном потоке на сервере и не зависит от того, открыта ли страница.
  * У задания есть номер (отпечаток файла и настроек). Он пишется в адрес страницы (?job=…), поэтому после
    возвращения страница сама находит задание: показывает прогресс или готовый результат.
  * Тот же файл с теми же настройками не считается второй раз: отдаётся готовый результат.
  * Задания хранятся во временной папке сервера не дольше KEEP_HOURS часов, потом удаляются.
    После «Reboot app» (перезапуска сервера) задания пропадают.
"""
import hashlib, json, os, pickle, shutil, tempfile, threading, time, traceback

JOBS_DIR = os.path.join(tempfile.gettempdir(), "orkestrator_jobs")
KEEP_HOURS = 6
_LOCK = threading.Lock()
_RUNNING = set()


def key(data, params):
    h = hashlib.sha1()
    h.update(data)
    env = {k: v for k, v in os.environ.items() if k.startswith(("ORCH_", "LLM_")) or k in ("PLANNER_MODEL", "PLANNER_PROVIDER")}
    h.update(json.dumps({"p": params, "env": env}, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:16]


def _dir(k):
    return os.path.join(JOBS_DIR, "".join(c for c in k if c.isalnum()))


def status(k):
    try:
        with open(os.path.join(_dir(k), "status.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_status(k, **st):
    d = _dir(k)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "status.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, "status.json"))


def load(k):
    with open(os.path.join(_dir(k), "result.pkl"), "rb") as f:
        return pickle.load(f)


class JobProgress:
    """То же, что progress.Steps (go/finish/abort), но пишет шаг в файл задания, а не на экран."""

    def __init__(self, k, steps, dur):
        self.k, self.steps, self.dur = k, steps, dur
        self.cur, self.t_step, self.times, self.t0 = None, None, {}, time.time()

    def _close(self):
        if self.cur is not None:
            self.times[self.cur] = round(time.time() - self.t_step, 2)

    def go(self, step_key):
        self._close()
        self.cur, self.t_step = step_key, time.time()
        _write_status(self.k, state="running", step=step_key, steps=self.steps, dur=self.dur,
                      started=self.t0, step_started=self.t_step, done_times=self.times)

    def finish(self):
        self._close()
        try:
            import progress
            for s, sec in self.times.items():
                progress.learn(s, sec, self.dur)
        except Exception:
            pass
        return dict(self.times)

    def abort(self):
        pass


def start(k, fn, steps, dur):
    """Запустить задание k, если оно ещё не идёт и не готово. fn(prog, work_dir) -> результат (сохраняется pickle)."""
    cleanup()
    st = status(k)
    with _LOCK:
        if k in _RUNNING or (st and st.get("state") == "done" and os.path.exists(os.path.join(_dir(k), "result.pkl"))):
            return False
        if st and st.get("state") == "running" and k not in _RUNNING:
            pass                       # прежний процесс сервера умер посреди работы: запускаем заново
        _RUNNING.add(k)
    d = _dir(k)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "work"), exist_ok=True)
    prog = JobProgress(k, steps, dur)
    _write_status(k, state="running", step=steps[0][0], steps=steps, dur=dur, started=time.time(),
                  step_started=time.time(), done_times={})

    def body():
        try:
            res = fn(prog, os.path.join(d, "work"))
            with open(os.path.join(d, "result.pkl.tmp"), "wb") as f:
                pickle.dump(res, f)
            os.replace(os.path.join(d, "result.pkl.tmp"), os.path.join(d, "result.pkl"))
            _write_status(k, state="done", finished=time.time(), steps=steps, dur=dur)
        except Exception:
            _write_status(k, state="error", error=traceback.format_exc(), steps=steps, dur=dur)
        finally:
            with _LOCK:
                _RUNNING.discard(k)

    threading.Thread(target=body, name="orkestrator-job-" + k, daemon=True).start()
    return True


def alive(k):
    with _LOCK:
        return k in _RUNNING


def forget(k):
    """Стереть файлы задания k (если оно не идёт прямо сейчас)."""
    with _LOCK:
        if k in _RUNNING:
            return False
    shutil.rmtree(_dir(k), ignore_errors=True)
    return True


def cleanup(max_hours=KEEP_HOURS):
    try:
        now = time.time()
        for name in os.listdir(JOBS_DIR):
            d = os.path.join(JOBS_DIR, name)
            if name in _RUNNING:
                continue
            if now - os.path.getmtime(d) > max_hours * 3600:
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
