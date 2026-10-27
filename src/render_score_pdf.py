"""Usage: python src/render_score_pdf.py out/piece.musicxml out/piece_score.pdf   (needs verovio, cairosvg, pypdf)"""
import sys, io
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
import verovio, cairosvg
from pypdf import PdfWriter, PdfReader

def main(src, dst):
    tk = verovio.toolkit()
    tk.setOptions({"pageHeight": 2970, "pageWidth": 2100, "scale": 45, "adjustPageHeight": False})
    if not tk.loadFile(src): raise SystemExit("Не удалось прочитать " + src)
    w = PdfWriter()
    for i in range(1, tk.getPageCount() + 1):
        for page in PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=tk.renderToSVG(i).encode("utf-8")))).pages:
            w.add_page(page)
    with open(dst, "wb") as f: w.write(f)
    print("Готово:", dst, "страниц:", tk.getPageCount())

if __name__ == "__main__":
    if len(sys.argv) < 3: raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
