"""Запись MIDI в WAV через системную библиотеку libfluidsynth (ctypes), когда программы fluidsynth нет.

2026-11-14: в среде разработки есть только библиотека. Звук тот же синтезатор и тот же банк, что у программы.
Запись идёт до последнего события MIDI плюс TAIL секунд на затухание. Без этого ограничения синтезатор ждал,
пока полностью затухнут все струны рояля (на пьесе пользователя 27 секунд почти тишины после последней ноты),
и запись выходила длиннее самой музыки.
"""
import ctypes, ctypes.util, wave

TAIL = 5.0     # секунд после последнего события (эвристика)
_lib = None


def _load():
    global _lib
    if _lib is None:
        for name in (ctypes.util.find_library("fluidsynth"), "libfluidsynth.so.3", "libfluidsynth.so.2", "libfluidsynth.so"):
            if not name:
                continue
            try:
                _lib = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if _lib is None:
            raise RuntimeError("библиотека libfluidsynth не найдена")
        for f in ("new_fluid_settings", "new_fluid_synth", "new_fluid_player"):
            getattr(_lib, f).restype = ctypes.c_void_p
    return _lib


def available():
    try:
        _load()
        return True
    except Exception:
        return False


def render_wav(mid, wav, sf, sr=44100):
    lib = _load()
    V = ctypes.c_void_p
    st = V(lib.new_fluid_settings())
    lib.fluid_settings_setnum(st, b"synth.sample-rate", ctypes.c_double(float(sr)))
    lib.fluid_settings_setstr(st, b"player.timing-source", b"sample")
    lib.fluid_settings_setint(st, b"synth.dynamic-sample-loading", 1)
    syn = V(lib.new_fluid_synth(st))
    pl = None
    try:
        if lib.fluid_synth_sfload(syn, sf.encode("utf-8"), 1) == -1:
            raise RuntimeError("банк не загрузился: " + sf)
        pl = V(lib.new_fluid_player(syn))
        if lib.fluid_player_add(pl, mid.encode("utf-8")) != 0:
            raise RuntimeError("MIDI не прочитан: " + mid)
        lib.fluid_player_play(pl)
        block = 1024
        buf = (ctypes.c_int16 * (block * 2))()
        with wave.open(wav, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
            limit = sr * 3600 // block          # не больше часа
            n = 0
            while lib.fluid_player_get_status(pl) == 1 and n < limit:      # 1 = играет
                total = lib.fluid_player_get_total_ticks(pl)
                if total > 0 and lib.fluid_player_get_current_tick(pl) >= total:
                    break                        # последнее событие сыграно; дальше только затухание
                lib.fluid_synth_write_s16(syn, block, buf, 0, 2, buf, 1, 2)
                w.writeframes(bytes(buf)); n += 1
            tail = int(TAIL * sr / block)
            for k in range(tail):
                lib.fluid_synth_write_s16(syn, block, buf, 0, 2, buf, 1, 2)
                fade = 1.0 if k < tail // 2 else max(0.0, (tail - k) / (tail - tail // 2))
                if fade < 1.0:
                    for i in range(block * 2):
                        buf[i] = int(buf[i] * fade)
                w.writeframes(bytes(buf))
    finally:
        if pl is not None:
            lib.delete_fluid_player(pl)
        lib.delete_fluid_synth(syn)
        lib.delete_fluid_settings(st)
