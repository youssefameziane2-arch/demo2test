"""Génère les visuels du README : animation de l'enregistrement et rendu du test généré.

    QT_QPA_PLATFORM=offscreen python docs/make_visuals.py

Tout est produit à partir d'une vraie exécution : la démonstration ``s01_happy_path``
est rejouée sur l'application pendant que l'enregistreur tourne, chaque étape est
capturée, puis le scénario Gherkin réellement généré est affiché.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

from demo2test.abstraction.matching import Pipeline  # noqa: E402
from demo2test.gherkin import generate  # noqa: E402
from demo2test.player import Player, record  # noqa: E402

OUT = ROOT / "docs"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
INK, MUTED, ACCENT, REC = (31, 35, 40), (101, 109, 118), (9, 105, 218), (207, 34, 46)
KEYWORD_COLORS = {"Feature": (130, 80, 223), "Scenario": (130, 80, 223), "Given": (9, 105, 218),
                  "When": (9, 105, 218), "Then": (26, 127, 55), "And": (9, 105, 218)}

frames: list[tuple[Image.Image, str]] = []


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def grab(window, caption: str) -> None:
    QApplication.processEvents()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    window.grab().save(buf, "PNG")
    from io import BytesIO

    img = Image.open(BytesIO(bytes(buf.data()))).convert("RGB")
    frames.append((img, caption))


def instrumented_play(play):
    """Rejoue la démonstration en capturant l'écran après chaque action."""
    labels = {"type": "saisit", "pick": "choisit", "click": "clique", "enter": "Entrée dans",
              "checkpoint": "checkpoint"}

    depth = [0]

    def wrap(name):
        original = getattr(Player, name)

        def inner(self, *args, **kw):
            depth[0] += 1
            try:
                result = original(self, *args, **kw)
            finally:
                depth[0] -= 1
            if depth[0]:
                return result  # appel interne (ex. type -> click) : une seule image par action
            target = self.w.findChild(object, args[0]) if args else None
            what = target.accessibleName() if target is not None and hasattr(target, "accessibleName") else ""
            value = f" « {args[1]} »" if len(args) > 1 else ""
            grab(self.w, f"{labels[name]} {what}{value}".strip())
            return result
        return inner

    for name in labels:
        setattr(Player, name, wrap(name))
    return record(play, settle_ms=700)


def compose(app_img: Image.Image, caption: str, step: int, total: int) -> Image.Image:
    w, h = app_img.size
    canvas = Image.new("RGB", (w + 40, h + 110), (246, 248, 250))
    canvas.paste(app_img, (20, 70))
    d = ImageDraw.Draw(canvas)
    d.ellipse((22, 24, 40, 42), fill=REC)
    d.text((50, 20), "REC", font=_font(SANS_BOLD, 20), fill=REC)
    d.text((105, 22), "démonstration enregistrée par demo2test", font=_font(SANS, 18), fill=MUTED)
    d.text((20, h + 80), f"{step}/{total}  {caption}", font=_font(SANS, 18), fill=INK)
    return canvas


def render_feature(text: str, width: int, title: str) -> Image.Image:
    lines = [ln for ln in text.splitlines() if not ln.startswith("# language")]
    font, size = _font(MONO, 17), 26
    height = 90 + size * len(lines) + 30
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, width, 60), fill=(246, 248, 250))
    d.text((24, 18), title, font=_font(SANS_BOLD, 20), fill=INK)
    y = 80
    for ln in lines:
        stripped = ln.strip()
        x = 24
        if stripped.startswith("#"):
            d.text((x, y), ln, font=font, fill=MUTED)
        else:
            first = stripped.split(" ", 1)[0].rstrip(":")
            color = KEYWORD_COLORS.get(first)
            if color:
                indent = ln[: len(ln) - len(stripped)]
                kw = stripped.split(" ", 1)[0]
                d.text((x, y), indent + kw, font=font, fill=color)
                x += d.textlength(indent + kw + " ", font=font)
                d.text((x, y), stripped[len(kw) + 1:], font=font, fill=INK)
            else:
                d.text((x, y), ln, font=font, fill=INK)
        y += size
    return img


def main() -> None:
    app = QApplication.instance() or QApplication([])
    scenario = next(s for s in SCENARIOS if s.name == "s01_happy_path")
    events = instrumented_play(scenario.play)
    gen = generate(events, "Configure and generate a NoC", Pipeline(), "key", "demo")
    width = max(img.width for img, _ in frames) + 40
    gif = [compose(img, cap, i + 1, len(frames)) for i, (img, cap) in enumerate(frames)]
    feature = render_feature(gen.feature, max(width, 980),
                             f"Test généré : {len(events)} événements → {len(gen.result.calls)} steps "
                             f"+ {len(gen.assertions)} vérifications")
    feature.save(OUT / "generated_feature.png")
    durations = [900] * (len(gif) - 1) + [3000]
    gif[0].save(OUT / "demo.gif", save_all=True, append_images=gif[1:], duration=durations,
                loop=0, optimize=True)
    print(f"{len(frames)} frames -> docs/demo.gif, docs/generated_feature.png")
    app.quit()


if __name__ == "__main__":
    main()
