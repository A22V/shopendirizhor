"""
Барочная тема «A: голубой дворец, золото, красный бархат» для программы «Оркестратор» (репозиторий shopendirizhor).

Все орнаменты нарисованы здесь же в SVG (свои, без чужих картинок и водяных знаков).
Принцип читаемости: украшения живут в шапке, по краям экрана и в углах рабочего поля;
весь текст, кнопки и таблицы стоят на сплошной светлой «бумаге» и никогда не лежат на рисунке.

CSS() — стили (вставляются один раз), DECOR_TOP() — ламбрекен, занавеси и эмблема (разметка),
FOOTER() — нижняя гирлянда. Логику программы модуль не трогает.
"""
import urllib.parse as _up

GOLD, GOLD_HI, GOLD_LO = "#c9a13b", "#efd27a", "#8f6a17"
CRIMSON, CRIMSON_HI, CRIMSON_LO = "#8e1426", "#b8283d", "#4e0712"
INK, PAPER = "#2a1c12", "#fcf8ef"


def _uri(svg):
    return "url(\"data:image/svg+xml;utf8," + _up.quote(svg, safe="=:/ ,;'()") + "\")"


# --- стена с панелями (фон страницы); на стене нет текста ------------------------------------------
# Два варианта цвета: «светлая» (бледно-голубая) и «глубокая» (насыщенный дворцовый голубой).
WALLS = {
    "light": dict(base="#e3ecf5", stripe="#f1f6fb", panel="#ecf2f9", inner="#ffffff", line="#cdb36a", rose="#d6c07e"),
    "deep":  dict(base="#7d9ec4", stripe="#9ab7d6", panel="#89a9cd", inner="#e8f0f9", line="#e2c46e", rose="#e6cb7c"),
}


def _wall(c):
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='280' height='440' viewBox='0 0 280 440'>"
        f"<rect width='280' height='440' fill='{c['base']}'/>"
        f"<rect x='0' width='16' height='440' fill='{c['stripe']}'/><rect x='16' width='2' height='440' fill='{c['line']}' opacity='.6'/>"
        f"<rect x='44' y='36' width='208' height='262' rx='10' fill='{c['panel']}' stroke='{c['line']}' stroke-width='1.6' opacity='.9'/>"
        f"<rect x='56' y='48' width='184' height='238' rx='6' fill='none' stroke='{c['inner']}' stroke-width='2.2'/>"
        f"<g transform='translate(148 92)' fill='{c['rose']}' opacity='.8'>"
        + "".join("<ellipse cx='0' cy='-10' rx='4.2' ry='9' transform='rotate(%d)'/>" % a for a in range(0, 360, 45))
        + "<circle r='4.5' fill='#c9a13b'/></g>"
        f"<rect x='44' y='330' width='208' height='80' rx='6' fill='{c['panel']}' stroke='{c['line']}' stroke-width='1.4' opacity='.85'/>"
        f"<rect x='56' y='340' width='184' height='60' rx='4' fill='none' stroke='{c['inner']}' stroke-width='1.6'/>"
        f"<rect x='0' y='312' width='280' height='3' fill='{c['line']}' opacity='.55'/>"
        "</svg>")


def WALL_CSS(name):
    """Правило фона страницы для выбранной стены (в приложении вставляется отдельно, чтобы переключать)."""
    c = WALLS[name]
    return ".stApp {{ background: {} center top / 280px 440px repeat, {}; }}".format(_uri(_wall(c)), c["base"])

# --- угол рабочего поля: завиток аканта (4 поворота) --------------------------------------------------
def _corner(rot):
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='72' height='72' viewBox='0 0 72 72'>"
        f"<g transform='rotate({rot} 36 36)' fill='none' stroke='{GOLD}' stroke-width='2.2' stroke-linecap='round'>"
        "<path d='M6 66 V22 C6 10 14 6 24 6 H66'/>"
        "<path d='M14 58 V28 C14 18 20 14 28 14 H58' stroke-width='1.2'/>"
        "<path d='M24 6 C30 18 22 26 14 22 C8 18 12 10 18 12'/>"
        "<path d='M40 6 C40 14 46 18 52 14' stroke-width='1.6'/><path d='M6 40 C14 40 18 46 14 52' stroke-width='1.6'/>"
        f"<circle cx='24' cy='24' r='3.2' fill='{GOLD}' stroke='none'/>"
        "</g></svg>")


# --- ламбрекен: карниз, бархатные фестоны, золотая бахрома, кисти --------------------------------------
def _valance():
    sw, n = 240, 6
    parts = [
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 150' preserveAspectRatio='xMidYMin slice'>",
        "<defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>"
        f"<stop offset='0' stop-color='{GOLD_HI}'/><stop offset='.55' stop-color='{GOLD}'/><stop offset='1' stop-color='{GOLD_LO}'/></linearGradient>"
        "<linearGradient id='v' x1='0' y1='0' x2='0' y2='1'>"
        f"<stop offset='0' stop-color='{CRIMSON_LO}'/><stop offset='.45' stop-color='{CRIMSON_HI}'/><stop offset='1' stop-color='{CRIMSON}'/></linearGradient></defs>",
    ]
    for i in range(n):
        x = i * sw
        parts.append(f"<path d='M{x} 24 Q{x + sw / 2} 150 {x + sw} 24 Z' fill='url(#v)'/>")
        for k, d in ((0.28, 112), (0.5, 98), (0.72, 112)):
            parts.append(f"<path d='M{x + 14} 26 Q{x + sw * k} {d} {x + sw - 14} 26' fill='none' stroke='{CRIMSON_LO}' stroke-width='2' opacity='.45'/>")
        parts.append(f"<path d='M{x} 24 Q{x + sw / 2} 158 {x + sw} 24' fill='none' stroke='{GOLD}' stroke-width='9' stroke-dasharray='1.6 2.6'/>")
        parts.append(f"<path d='M{x} 24 Q{x + sw / 2} 148 {x + sw} 24' fill='none' stroke='{GOLD_HI}' stroke-width='2'/>")
    for i in range(n + 1):
        x = i * sw
        parts.append(f"<circle cx='{x}' cy='30' r='9' fill='url(#g)'/>"
                     f"<path d='M{x - 7} 38 L{x - 10} 74 H{x + 10} L{x + 7} 38 Z' fill='url(#g)'/>"
                     f"<path d='M{x - 10} 74 V80 M{x - 5} 74 V82 M{x} 74 V83 M{x + 5} 74 V82 M{x + 10} 74 V80' stroke='{GOLD_LO}' stroke-width='1.4'/>")
    parts.append("<rect x='0' y='0' width='1440' height='26' fill='url(#g)'/>"
                 f"<rect x='0' y='20' width='1440' height='2' fill='{GOLD_LO}' opacity='.6'/>"
                 f"<path d='M0 11 H1440' stroke='{GOLD_LO}' stroke-width='3' stroke-dasharray='3 9' opacity='.55'/>")
    parts.append("</svg>")
    return "".join(parts)


# --- боковая занавесь, подхваченная золотым шнуром (правая = зеркало левой) ---------------------------
def _curtain():
    folds = "".join(
        f"<path d='M{x} 0 C{x - 6} 260 {x * 0.55 + 10} 470 {x * 0.25 + 26} 560 C{x * 0.4 + 40} 660 {x * 0.6 + 40} 800 {x * 0.75 + 30} 1000' "
        f"fill='none' stroke='{CRIMSON_LO}' stroke-width='{w}' opacity='.5'/>"
        for x, w in ((40, 3), (80, 4), (120, 3), (158, 2)))
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 1000' preserveAspectRatio='xMinYMin slice'>"
        "<defs><linearGradient id='c' x1='0' y1='0' x2='1' y2='0'>"
        f"<stop offset='0' stop-color='{CRIMSON_LO}'/><stop offset='.35' stop-color='{CRIMSON_HI}'/>"
        f"<stop offset='.7' stop-color='{CRIMSON}'/><stop offset='1' stop-color='{CRIMSON_LO}'/></linearGradient>"
        f"<linearGradient id='g2' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='{GOLD_HI}'/><stop offset='1' stop-color='{GOLD_LO}'/></linearGradient></defs>"
        "<clipPath id='cc'><path d='M0 0 H190 C176 250 120 460 36 560 C80 650 128 800 150 1000 H0 Z'/></clipPath>"
        "<path d='M0 0 H190 C176 250 120 460 36 560 C80 650 128 800 150 1000 H0 Z' fill='url(#c)'/>"
        "<g clip-path='url(#cc)'>" + folds + "</g>" +
        f"<path d='M190 0 C176 250 120 460 36 560 C80 650 128 800 150 1000' fill='none' stroke='{GOLD}' stroke-width='5'/>"
        f"<path d='M190 0 C176 250 120 460 36 560 C80 650 128 800 150 1000' fill='none' stroke='{GOLD_HI}' stroke-width='1.5' stroke-dasharray='2 4'/>"
        f"<ellipse cx='30' cy='562' rx='34' ry='11' fill='none' stroke='url(#g2)' stroke-width='7'/>"
        f"<circle cx='58' cy='566' r='9' fill='url(#g2)'/>"
        f"<path d='M58 575 C56 600 54 612 50 640 H72 C68 612 64 600 62 575 Z' fill='url(#g2)'/>"
        f"<path d='M50 640 V656 M55 640 V660 M61 640 V662 M67 640 V660 M72 640 V656' stroke='{GOLD_LO}' stroke-width='2'/>"
        "</svg>")


# --- эмблема над названием: лира в лавровых ветвях -------------------------------------------------------
LYRE = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 220 120' width='190' height='104'>"
    f"<defs><linearGradient id='l' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='{GOLD_HI}'/><stop offset='1' stop-color='{GOLD_LO}'/></linearGradient></defs>"
    f"<g fill='none' stroke='url(#l)' stroke-linecap='round'>"
    "<path d='M86 100 C70 80 66 50 80 30 C86 22 94 22 96 30' stroke-width='5'/>"
    "<path d='M134 100 C150 80 154 50 140 30 C134 22 126 22 124 30' stroke-width='5'/>"
    "<path d='M80 38 H140' stroke-width='4'/><path d='M84 100 H136' stroke-width='5'/>"
    "<path d='M98 40 V98 M106 40 V98 M114 40 V98 M122 40 V98' stroke-width='1.4'/>"
    "</g>"
    f"<g fill='url(#l)'>"
    + "".join(f"<ellipse cx='{60 - i * 9}' cy='{98 - i * 11}' rx='9' ry='4' transform='rotate({-40 - i * 8} {60 - i * 9} {98 - i * 11})'/>"
              f"<ellipse cx='{160 + i * 9}' cy='{98 - i * 11}' rx='9' ry='4' transform='rotate({40 + i * 8} {160 + i * 9} {98 - i * 11})'/>"
              for i in range(5))
    + "<circle cx='110' cy='14' r='5'/></g>"
    f"<path d='M70 104 C50 100 34 80 24 50 M150 104 C170 100 186 80 196 50' fill='none' stroke='{GOLD_LO}' stroke-width='1.6'/>"
    "</svg>")

FLEURON = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 28' width='320' height='28'>"
    f"<g fill='none' stroke='{GOLD}' stroke-width='1.6' stroke-linecap='round'>"
    "<path d='M6 14 H112'/><path d='M208 14 H314'/>"
    "<path d='M112 14 C122 2 136 2 142 12 C136 20 126 18 128 12'/>"
    "<path d='M208 14 C198 2 184 2 178 12 C184 20 194 18 192 12'/>"
    "<path d='M146 14 C150 4 170 4 174 14 C170 24 150 24 146 14Z'/>"
    f"</g><circle cx='160' cy='14' r='4' fill='{CRIMSON}'/></svg>")


def CSS():
    corners = ", ".join(f"{_uri(_corner(r))} {pos} / 64px 64px no-repeat" for r, pos in
                        ((0, "top left"), (90, "top right"), (270, "bottom left"), (180, "bottom right")))
    return f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;0,700;1,600&family=Cormorant+SC:wght@600;700&family=PT+Serif:ital,wght@0,400;0,700;1,400&family=Great+Vibes&family=Marck+Script&display=swap');
:root {{ --gold:{GOLD}; --gold-hi:{GOLD_HI}; --gold-lo:{GOLD_LO}; --crimson:{CRIMSON}; --crimson-hi:{CRIMSON_HI};
        --crimson-lo:{CRIMSON_LO}; --ink:{INK}; --paper:{PAPER}; --muted:#5e4b39; --navy:#23395b; }}
/* страница: бледно-голубая стена с панелями; на ней НЕТ текста */
.stApp {{ color: var(--ink); }}
{WALL_CSS('light')}
[data-testid="stHeader"] {{ background: transparent; }}
html, body, .stApp, [data-testid="stMarkdownContainer"], label, p, li {{
  font-family: 'PT Serif', 'Georgia', 'Times New Roman', serif; font-size: 17.5px; line-height: 1.6; color: var(--ink); }}
/* рабочее поле: сплошная «бумага», двойная золотая рамка, завитки в углах (вне текста) */
[data-testid="stMainBlockContainer"], .block-container {{
  max-width: 800px; margin: 150px auto 60px; padding: 3.4rem 3rem 3rem !important;
  background: {corners}, var(--paper);
  border: 1px solid var(--gold); outline: 3px double var(--gold); outline-offset: 6px;
  box-shadow: 0 0 0 14px rgba(252,248,239,.55), 0 18px 50px rgba(35,57,91,.25); border-radius: 4px; }}
h1, h2, h3, h4 {{ font-family: 'Cormorant Garamond', 'Georgia', serif !important; color: var(--crimson) !important; font-weight: 700 !important; }}
h3 {{ font-size: 1.65rem !important; margin-top: 1.6rem !important; display: flex; align-items: center; gap: .6rem; }}
h3::after {{ content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, var(--gold), transparent); }}
.bq-title {{ text-align: center; margin: -1.2rem 0 .4rem; }}
.bq-title h1 {{ font-family: 'Great Vibes', 'Marck Script', 'Cormorant Garamond', cursive !important; font-weight: 400 !important;
  font-size: 4.6rem !important; line-height: 1.1;
  margin: .1rem 0 0; padding: 0; letter-spacing: 1.5px; border: 0; text-shadow: 0 1px 0 #fff, 0 2px 6px rgba(143,106,23,.25); }}
.bq-motto {{ font-family: 'Cormorant Garamond', 'Georgia', serif; font-style: italic; font-weight: 600; font-size: 1.5rem; color: var(--navy); margin: .1rem 0 0; }}
.bq-title h1 a, .bq-title [data-testid="stHeaderActionElements"] {{ display: none !important; }}
.bq-fleuron {{ text-align: center; margin: .6rem 0 .4rem; }}
.bq-fleuron svg {{ max-width: 100%; height: auto; }}
.bq-num {{ display: inline-flex; width: 2.1rem; height: 2.1rem; border-radius: 50%; align-items: center; justify-content: center;
  border: 2px solid var(--gold); background: radial-gradient(#fff, #f3e7c6); color: var(--crimson); font-size: 1.15rem; flex: none; }}
.frame {{ background: #fffdf8; border: 1px solid #e2cf9b; border-left: 4px solid var(--gold); border-radius: 4px;
  padding: 1rem 1.2rem; margin: 0 0 1rem; }}
.frame.warn {{ border-left-color: var(--crimson); background: #fff9f3; }}
/* кнопки: красный бархат с золотой каймой */
.stButton > button, .stDownloadButton > button {{
  background: linear-gradient(180deg, var(--crimson-hi) 0%, var(--crimson) 55%, var(--crimson-lo) 100%) !important;
  color: #fff6df !important; border: 1.5px solid var(--gold) !important; border-radius: 6px !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.25), inset 0 0 0 3px rgba(239,210,122,.18), 0 3px 8px rgba(78,7,18,.3);
  font-family: 'Cormorant SC', 'Cormorant Garamond', serif !important; font-size: 1.2rem !important; letter-spacing: .8px;
  min-height: 3rem; }}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: var(--gold-hi) !important; filter: brightness(1.08); }}
.stButton > button:focus-visible {{ outline: 3px solid var(--navy); outline-offset: 2px; }}
/* поле загрузки */
[data-testid="stFileUploaderDropzone"] {{ background: #fffdf8 !important; border: 2px dashed var(--gold) !important; border-radius: 8px; }}
/* выбор режима: карточка «меню» */
.st-key-mode_pick [role="radiogroup"], .bq-menu [role="radiogroup"] {{ background: #fffdf8; border: 1px solid #e2cf9b; border-radius: 6px; padding: .5rem 1rem;
  outline: 1px solid #e2cf9b; outline-offset: 4px; gap: 0 !important; }}
.st-key-mode_pick [role="radiogroup"] label, .bq-menu [role="radiogroup"] label {{ padding: .45rem 0; border-bottom: 1px dotted #d8c38a; margin: 0 !important; width: 100%; }}
.st-key-mode_pick [role="radiogroup"] label:last-child, .bq-menu [role="radiogroup"] label:last-child {{ border-bottom: 0; }}
[data-testid="stExpander"] details {{ border: 1px solid #e2cf9b !important; border-radius: 6px; background: #fffdf8; }}
[data-testid="stAlert"] {{ border-radius: 6px; border: 1px solid #e2cf9b; }}
.bq-audio {{ background: #fffdf8; border: 1px solid #e2cf9b; border-radius: 8px; padding: .6rem .8rem; }}
audio {{ width: 100%; }}
input[type=radio], input[type=checkbox] {{ accent-color: var(--crimson); }}
.st-key-wall [data-testid="stRadio"] {{ display: flex; justify-content: center; }}
.st-key-wall [role="radiogroup"] {{ justify-content: center; }}
.st-key-wall label, .st-key-wall p {{ font-size: .95rem !important; color: var(--muted); }}
[data-testid="stDecoration"] {{ display: none; }}
/* декор вокруг: ламбрекен сверху, занавеси по бокам. Только украшение: клики проходят сквозь */
.bq-valance {{ position: fixed; top: 0; left: 0; right: 0; height: 128px; z-index: 5; pointer-events: none; }}
.bq-valance svg {{ width: 100%; height: 100%; filter: drop-shadow(0 6px 8px rgba(35,57,91,.3)); }}
.bq-curtain {{ position: fixed; top: 0; bottom: 0; width: 180px; z-index: 4; pointer-events: none; }}
.bq-curtain svg {{ width: 100%; height: 100%; }}
.bq-curtain.left {{ left: 0; }} .bq-curtain.right {{ right: 0; transform: scaleX(-1); }}
.bq-footer {{ text-align: center; color: var(--muted); font-size: .95rem; margin-top: 2rem; }}
/* занавес при входе: раздвигается один раз, ~1,4 с */
.bq-open {{ position: fixed; inset: 0; z-index: 50; pointer-events: none; display: flex; }}
.bq-open i {{ flex: 1; background: repeating-linear-gradient(90deg, var(--crimson-lo) 0 6px, var(--crimson) 6px 40px, var(--crimson-hi) 40px 52px, var(--crimson) 52px 80px);
  animation: bqL 1.4s .35s cubic-bezier(.6,.05,.3,1) forwards; border-right: 4px solid var(--gold); }}
.bq-open i + i {{ animation-name: bqR; border-right: 0; border-left: 4px solid var(--gold); }}
@keyframes bqL {{ to {{ transform: translateX(-101%); visibility: hidden; }} }}
@keyframes bqR {{ to {{ transform: translateX(101%); visibility: hidden; }} }}
@media (prefers-reduced-motion: reduce) {{ .bq-open {{ display: none; }} }}
/* где мало места, боковые занавеси убираются, чтобы не закрывать поле */
@media (max-width: 1240px) {{ .bq-curtain {{ display: none; }} }}
@media (max-width: 700px) {{
  [data-testid="stMainBlockContainer"], .block-container {{ margin: 92px 10px 30px; padding: 2.6rem 1.1rem 1.6rem !important;
    outline-offset: 3px; background-size: 40px 40px, 40px 40px, 40px 40px, 40px 40px, auto; }}
  .bq-valance {{ height: 80px; }}
  .bq-title h1 {{ font-size: 3.3rem !important; }}
  html, body, .stApp, [data-testid="stMarkdownContainer"], label, p, li {{ font-size: 16.5px; }}
}}
</style>"""


def DECOR_TOP(curtain_open=True):
    c = _curtain()
    return ("<div class='bq-valance' aria-hidden='true'>" + _valance() + "</div>"
            "<div class='bq-curtain left' aria-hidden='true'>" + c + "</div>"
            "<div class='bq-curtain right' aria-hidden='true'>" + c + "</div>"
            + ("<div class='bq-open' aria-hidden='true'><i></i><i></i></div>" if curtain_open else ""))


def TITLE():
    return ("<div class='bq-title'>" + LYRE + "<h1>Оркестратор</h1>"
            "<p class='bq-motto'>Фортепианная пьеса — оркестровый наряд</p></div>"
            "<div class='bq-fleuron'>" + FLEURON + "</div>")


def SECTION(num, text):
    return "<h3><span class='bq-num'>%s</span>%s</h3>" % (num, text)


def FOOTER():
    return "<div class='bq-fleuron'>" + FLEURON + "</div><div class='bq-footer'>Оркестратор · камерный оркестр из десяти инструментов</div>"
