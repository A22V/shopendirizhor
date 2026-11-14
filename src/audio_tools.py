"""Helpers for turning MIDI into audio (optional part of the project)."""
import os, shutil, subprocess, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def find_fluidsynth():
    p = shutil.which("fluidsynth")
    if p:
        return p
    for c in glob.glob(os.path.join(ROOT, "tools", "**", "fluidsynth*"), recursive=True):
        if os.path.isfile(c) and (c.lower().endswith(".exe") or os.access(c, os.X_OK)):
            return c
    return None


def all_soundfonts():
    """Все найденные звуковые банки: сначала SOUNDFONT из окружения, затем папка soundfonts/ (самый большой первым),
    затем системные. render_wav пробует их по очереди: если большой банк не влез в память облака, берётся следующий."""
    out = []
    env = os.environ.get("SOUNDFONT")
    if env and os.path.isfile(env):
        out.append(env)
    local = sorted(glob.glob(os.path.join(ROOT, "soundfonts", "*.sf2")) + glob.glob(os.path.join(ROOT, "soundfonts", "*.sf3")),
                   key=lambda f: -os.path.getsize(f))
    others = ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2",
              "/opt/homebrew/share/soundfonts/default.sf2", "/usr/share/sounds/sf2/TimGM6mb.sf2", "/usr/share/sounds/sf3/MuseScore_General.sf3"]
    for c in local + others:
        if os.path.isfile(c) and c not in out:
            out.append(c)
    return out


def find_soundfont():
    sfs = all_soundfonts()
    return sfs[0] if sfs else None


LAST_SOUNDFONT = None   # каким банком сделан последний звук (для подписи в приложении)


def _wav_has_sound(wav):
    """Есть ли в WAV хоть один ненулевой отсчёт (без audioop: его нет в Python 3.13)."""
    try:
        with open(wav, "rb") as f:
            f.seek(44)
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    return False
                if chunk.strip(b"\x00"):
                    return True
    except Exception:
        return False


def render_wav(mid, wav, sr=44100):
    global LAST_SOUNDFONT
    fs, sfs = find_fluidsynth(), all_soundfonts()
    last_err = None
    if not fs and sfs:
        # 2026-11-14: программы fluidsynth нет, но есть её библиотека — пишем звук через неё (src/fluid_lib.py)
        import fluid_lib
        if fluid_lib.available():
            for sf in sfs:
                try:
                    if os.path.exists(wav): os.remove(wav)
                    fluid_lib.render_wav(mid, wav, sf, sr)
                    if _wav_has_sound(wav):
                        LAST_SOUNDFONT = sf
                        return
                    last_err = RuntimeError("тишина с банком " + os.path.basename(sf))
                except Exception as e:
                    last_err = e
            raise RuntimeError("Не удалось сделать звук ни с одним банком: %s" % last_err)
    if not fs or not sfs:
        raise RuntimeError("Нет fluidsynth или звукового банка (.sf2). Запустите: python setup_check.py")
    for sf in sfs:
        # 2026-11-07: сначала с «загрузкой только нужных звуков» (synth.dynamic-sample-loading): банк MS Basic
        # занимал ~557 МБ, так ~201 МБ; звук побайтно тот же (проверено на пьесе 53 такта). Если версия
        # fluidsynth настройку не знает или запись не удалась — повтор по-старому, без неё.
        for opts in (["-o", "synth.dynamic-sample-loading=1"], []):
            try:
                if os.path.exists(wav): os.remove(wav)
                subprocess.run([fs, "-ni"] + opts + ["-F", wav, "-r", str(sr), sf, mid], check=True, timeout=300,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if _wav_has_sound(wav):
                    LAST_SOUNDFONT = sf
                    return
                last_err = RuntimeError("тишина с банком " + os.path.basename(sf))
            except Exception as e:   # нехватка памяти, сбой, слишком долго: другой способ, потом следующий банк
                last_err = e
    raise RuntimeError("Не удалось сделать звук ни с одним банком: %s" % last_err)


def render_mp3(mid, mp3, bitrate="128k"):
    """MIDI -> MP3 (needs ffmpeg). Without ffmpeg a WAV file is written instead. Returns the file path."""
    wav = mp3 + ".tmp.wav"
    render_wav(mid, wav)
    ff = shutil.which("ffmpeg")
    if ff:
        # 2026-11-14: программа fluidsynth пишет звук, пока не затухнут все струны (у рояля до ~30 с почти тишины
        # после последней ноты; отсюда «3:05 вместо 2:38» в плеере). Запись обрезается: музыка + 5 с, затухание 2 с.
        cut, af = [], "loudnorm=I=-16"
        try:
            import mido
            _len = float(mido.MidiFile(mid).length)
            if _len > 1.0:
                cut = ["-t", "%.2f" % (_len + 5.0)]
                af = "afade=t=out:st=%.2f:d=2,loudnorm=I=-16" % (_len + 3.0)
        except Exception:
            pass
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", wav] + cut + ["-af", af, "-b:a", bitrate, mp3],
                       check=True)
        os.remove(wav)
        return mp3
    final = os.path.splitext(mp3)[0] + ".wav"
    os.replace(wav, final)
    return final
