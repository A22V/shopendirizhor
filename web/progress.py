"""
Прогресс по шагам и обратный отсчёт «осталось примерно …» для Оркестратора.

Как устроено:
  * Перед работой известны шаги (план, запись MP3, рецензия, ноты …) и длительность пьесы по MIDI.
  * Для каждого шага есть оценка «a + b × секунд музыки». Числа для быстрых шагов замерены (2026-11-07,
    среда Claude, 5 пьес 22–156 с: план 0,3–1,3 с, рецензия 0,0–0,2 с, ноты 0,1 с, редукция < 0,1 с;
    в облаке взят запас ×2). Для DeepSeek и записи MP3 замеров нет: начальные числа — ПРИКИДКА (эвристика).
  * После каждого прогона программа запоминает фактическое время шагов и уточняет оценку
    (поправочный множитель на шаг, скользящее среднее). Запись MP3 исходного файла после загрузки
    тоже учитывается, поэтому скорость записи известна ещё до нажатия кнопки.
  * Память о скорости хранится во временной папке сервера: после «Reboot app» начинается заново.
  * Счётчик тикает в браузере (не нагружает сервер); на каждом новом шаге он пересчитывается.
    Если время вышло, а работа идёт, пишется «почти готово». Это оценка, а не обещание.
"""
import json, os, tempfile, time

import streamlit as st

try:
    import streamlit.components.v1 as _components
except Exception:                      # нет компонентов (например, в тестах): показываем без тикания
    _components = None

# (a секунд, b секунд на секунду музыки). Статус каждого числа — см. описание модуля.
BASE = {
    "plan": (2.0, 0.02),       # встроенный план + ноты: замер ×2
    "llm": (45.0, 0.0),        # DeepSeek Flash: прикидка
    "llm_reduce": (30.0, 0.0), # DeepSeek для переложения: прикидка
    "mp3": (5.0, 0.35),        # запись MP3 (fluidsynth + ffmpeg, MS Basic): прикидка
    "review": (1.0, 0.005),    # рецензия: замер ×2 с запасом
    "notes": (1.0, 0.01),      # ноты с пометками: замер ×2 с запасом
    "reduce": (1.0, 0.0),      # редукция: замер с запасом
    "piano_review": (1.0, 0.01),
}
STORE = os.path.join(tempfile.gettempdir(), "orkestrator_timing.json")
ALPHA = 0.5                    # вес нового прогона в скользящем среднем (эвристика)


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    try:
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def raw_estimate(key, dur):
    a, b = BASE.get(key, (2.0, 0.0))
    return a + b * max(dur, 0.0)


def estimate(key, dur):
    return raw_estimate(key, dur) * float(_load().get(key, 1.0))


def learn(key, actual, dur):
    """Запомнить фактическое время шага: поправочный множитель = скользящее среднее (факт / прикидка)."""
    raw = raw_estimate(key, dur)
    if raw <= 0 or actual <= 0:
        return
    d = _load()
    ratio = min(max(actual / raw, 0.1), 20.0)
    d[key] = round((1 - ALPHA) * float(d.get(key, 1.0)) + ALPHA * ratio, 3) if key in d else round(ratio, 3)
    _save(d)


def midi_seconds(path_or_bytes):
    try:
        import io, mido
        if isinstance(path_or_bytes, (bytes, bytearray)):
            return float(mido.MidiFile(file=io.BytesIO(path_or_bytes)).length)
        return float(mido.MidiFile(path_or_bytes).length)
    except Exception:
        return 60.0


def _clock(sec):
    sec = max(int(round(sec)), 0)
    return "%d:%02d" % (sec // 60, sec % 60)


def _countdown_html(remaining):
    return """<div id="c" style="font-family:'PT Serif',Georgia,serif;font-size:16px;color:#2a1c12;background:#fffdf8;
border:1px solid #e2cf9b;border-left:4px solid #c9a13b;border-radius:6px;padding:8px 12px;box-sizing:border-box">
Осталось примерно <b id="t">%s</b></div>
<script>(function(){var s=%d,t=document.getElementById('t'),c=document.getElementById('c');
function f(){if(s<=0){c.innerHTML='Почти готово, ещё немного…';clearInterval(h);return;}
t.textContent=Math.floor(s/60)+':'+('0'+(s%%60)).slice(-2);s--;}
var h=setInterval(f,1000);f();})();</script>""" % (_clock(remaining), max(int(round(remaining)), 0))


class Steps:
    """Шаги работы с полосой прогресса и обратным отсчётом.
    steps: [(ключ, подпись)]; dur: длительность пьесы, с. Использование: p.go("mp3") перед каждым шагом, p.finish() в конце."""

    def __init__(self, steps, dur):
        self.dur = dur
        self.items = [(k, label, estimate(k, dur)) for k, label in steps]
        self.ph = st.empty()
        self.i, self.t_step, self.times = -1, None, {}

    def _close_step(self):
        if self.i >= 0 and self.t_step is not None:
            key = self.items[self.i][0]
            self.times[key] = round(time.time() - self.t_step, 2)

    def go(self, key):
        self._close_step()
        self.i = next(n for n, it in enumerate(self.items) if it[0] == key)
        self.t_step = time.time()
        self._render()

    def _render(self):
        total = sum(e for _, _, e in self.items) or 1.0
        done = sum(e for _, _, e in self.items[:self.i])
        remaining = total - done
        key, label, _ = self.items[self.i]
        try:
            with self.ph.container():
                st.progress(min(done / total, 0.99), text="Шаг %d из %d: %s" % (self.i + 1, len(self.items), label))
                if _components is not None:
                    _components.html(_countdown_html(remaining), height=52)
                else:
                    st.caption("Осталось примерно %s" % _clock(remaining))
        except Exception:
            pass                        # прогресс не должен мешать работе

    def finish(self):
        """Закрыть последний шаг, запомнить фактическое время, убрать полосу. Возвращает {шаг: секунды}."""
        self._close_step()
        for k, sec in self.times.items():
            learn(k, sec, self.dur)
        try:
            self.ph.empty()
        except Exception:
            pass
        return dict(self.times)

    def abort(self):
        """Убрать полосу при ошибке (время неудачного прогона не запоминается)."""
        try:
            self.ph.empty()
        except Exception:
            pass
