"""Checks that everything needed is installed. Run: python setup_check.py"""
import sys, os, shutil, importlib
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

ok = True
def line(flag, text):
    print(("[ОК]   " if flag else "[НЕТ]  ") + text)

print("Проверка окружения проекта «Шопендирижёр»\n")
py_ok = sys.version_info >= (3, 9)
line(py_ok, "Python %d.%d.%d (нужен 3.9 или новее)" % sys.version_info[:3]); ok &= py_ok
need = {"music21": "обязательно", "mido": "обязательно", "numpy": "обязательно",
        "pypdf": "для PDF-партитур (необязательно)", "verovio": "для PDF-партитур (необязательно)",
        "cairosvg": "для PDF-партитур (необязательно)"}
for mod, why in need.items():
    try:
        importlib.import_module(mod); line(True, "библиотека %s (%s)" % (mod, why))
    except Exception:
        line(False, "библиотека %s (%s): установите командой  pip install -r requirements.txt" % (mod, why))
        if why == "обязательно": ok = False
import audio_tools
fs, sf, ff = audio_tools.find_fluidsynth(), audio_tools.find_soundfont(), shutil.which("ffmpeg")
line(bool(fs), "fluidsynth (превращает MIDI в звук; необязательно): " + (fs or "не найден"))
line(bool(sf), "звуковой банк .sf2 (необязательно): " + (sf or "не найден, положите файл в папку soundfonts"))
line(bool(ff), "ffmpeg (делает MP3; необязательно): " + (ff or "не найден, будет создан WAV"))
print()
if not ok:
    print("ИТОГ: не хватает обязательных компонентов (см. строки [НЕТ] выше).")
    sys.exit(1)
print("ИТОГ: обязательные компоненты есть." + ("" if (fs and sf) else " Звук (MP3/WAV) пока недоступен: это нормально для первого шага."))
