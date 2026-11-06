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
    if not fs or not sfs:
        raise RuntimeError("Нет fluidsynth или звукового банка (.sf2). Запустите: python setup_check.py")
    last_err = None
    for sf in sfs:
        try:
            if os.path.exists(wav): os.remove(wav)
            subprocess.run([fs, "-ni", "-F", wav, "-r", str(sr), sf, mid], check=True, timeout=300,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if _wav_has_sound(wav):
                LAST_SOUNDFONT = sf
                return
            last_err = RuntimeError("тишина с банком " + os.path.basename(sf))
        except Exception as e:   # нехватка памяти, сбой, слишком долго: пробуем следующий банк
            last_err = e
    raise RuntimeError("Не удалось сделать звук ни с одним банком: %s" % last_err)


def render_mp3(mid, mp3, bitrate="128k"):
    """MIDI -> MP3 (needs ffmpeg). Without ffmpeg a WAV file is written instead. Returns the file path."""
    wav = mp3 + ".tmp.wav"
    render_wav(mid, wav)
    ff = shutil.which("ffmpeg")
    if ff:
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", wav, "-af", "loudnorm=I=-16", "-b:a", bitrate, mp3],
                       check=True)
        os.remove(wav)
        return mp3
    final = os.path.splitext(mp3)[0] + ".wav"
    os.replace(wav, final)
    return final
