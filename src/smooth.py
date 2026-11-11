"""Плавность игры и переходов (2026-11-11; по умолчанию выкл.; на слух не проверено).

Повод: пользователь, Экспромт Шуберта op. 142 №2 (143 такта): «кое-где отрывисто и немного рвано».
Измерено на облачном результате (скрипты замеров лежат в scratchpad сессии, цифры в CLAUDE.md 12.57):
- ноты инструмента не соединены: у кларнета 37%, гобоя 37%, скрипок 44%, альта 44% нот после себя оставляют небольшой
  разрыв (до полдоли) до следующей ноты той же партии. Причина: оркестр копирует длины нот из рояля, а в исходнике
  (запись без педали) ноты длятся 75–83% интервала (медиана «длина / интервал» у рояля 0,75–0,83): пианист
  так «разговаривает», но у смычка и дыхания такой разрыв слышен как отрывистость.
- громкость фразы меняется ступенькой на границе такта: mp 64 → mf 80 → mp 64 каждые 6 тактов.

Две правки, каждая под своим переключателем (чтобы проверять на слух по одной):
- ORCH_LEGATO=1: `legato(lines)` — нота продлевается до начала следующей ноты той же партии, если разрыв не больше
  `GAP_MAX` долей и не больше длины самой ноты. Высоты и начала нот не меняются.
- ORCH_RAMP=1: `ramp_base(dyn, starts)` — в последнем такте перед сменой ступени громкости сила нажатия плавно
  идёт от прежней ступени к новой (крещендо или диминуэндо внутрь нового построения).
Все числа (0,5 доли, один такт) — эвристика. Продление нот до следующей и плавная смена громкости — общая практика
исполнения, но в книгах проекта числа не найдены.
"""
import os

GAP_MAX = 0.5        # доли: разрыв между нотами одной партии, который считаем «лишним» (эвристика)


def _on(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def legato_enabled():
    return _on("ORCH_LEGATO")


def ramp_enabled():
    return _on("ORCH_RAMP")


def legato(lines):
    """lines = {"Violin I": [[старт, длина, высота, роль], ...], ...}. Меняет на месте. Возвращает сведения."""
    stat = {}
    total = 0
    for name, seq in lines.items():
        if not seq:
            continue
        starts = sorted({round(n[0], 6) for n in seq})
        nxt = {a: b for a, b in zip(starts, starts[1:])}
        changed = 0
        for n in seq:
            b = nxt.get(round(n[0], 6))
            if b is None:
                continue
            end = n[0] + n[1]
            gap = b - end
            if gap > 1e-4 and gap <= GAP_MAX + 1e-9 and gap <= n[1] + 1e-9:
                n[1] = b - n[0]
                changed += 1
        if changed:
            stat[name] = changed
            total += changed
    return {"extended_notes": total, "by_instrument": stat}


def ramp_base(dyn, starts, level_vel):
    """Возвращает функцию base(off, bar_index) -> сила нажатия ступени с плавным переходом в последнем такте."""
    def base(off, bi):
        cur = dyn.get(bi, "mf")
        nxt = dyn.get(bi + 1)
        v = level_vel[cur]
        if nxt is None or nxt == cur or bi + 1 >= len(starts):
            return v
        length = starts[bi + 1] - starts[bi]
        if length <= 0:
            return v
        frac = max(0.0, min(1.0, (off - starts[bi]) / length))
        return v + (level_vel[nxt] - v) * frac
    return base
