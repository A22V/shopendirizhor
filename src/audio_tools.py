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


def find_soundfont():
    env = os.environ.get("SOUNDFONT")
    if env and os.path.isfile(env):
        return env
    local = sorted(glob.glob(os.path.join(ROOT, "soundfonts", "*.sf2")), key=lambda f: -os.path.getsize(f))
    others = ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2",
              "/opt/homebrew/share/soundfonts/default.sf2", "/usr/share/sounds/sf2/TimGM6mb.sf2"]
    for c in local + others:
        if os.path.isfile(c):
            return c
    return None


def render_wav(mid, wav, sr=44100):
    fs, sf = find_fluidsynth(), find_soundfont()
    if not fs or not sf:
        raise RuntimeError("Нет fluidsynth или звукового банка (.sf2). Запустите: python setup_check.py")
    subprocess.run([fs, "-ni", "-F", wav, "-r", str(sr), sf, mid], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
