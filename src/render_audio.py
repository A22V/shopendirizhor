"""Usage: python src/render_audio.py out/piece.mid out/piece.mp3"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_tools

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 3:
        print("Использование: python src/render_audio.py out/piece.mid out/piece.mp3"); sys.exit(1)
    print("Готово:", audio_tools.render_mp3(sys.argv[1], sys.argv[2]))
