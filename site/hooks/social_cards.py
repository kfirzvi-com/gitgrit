"""MkDocs hook: keep share cards small enough for every platform.

The social plugin writes full-colour PNGs. The landing card carries the hero
illustration and comes out around 650 KB, and some apps (WhatsApp in
particular) skip a link preview whose image is that large. Cards over the
limit are re-saved with a 256-colour palette, which at 1200×630 is
indistinguishable and about a third of the size. Smaller cards keep full
colour, so their gradients don't band.
"""

import logging
from pathlib import Path

from PIL import Image

CARDS_DIR = "assets/images/social"
LIMIT_BYTES = 300_000

log = logging.getLogger("mkdocs.hooks.social_cards")


def on_post_build(config):
    for card in (Path(config["site_dir"]) / CARDS_DIR).rglob("*.png"):
        before = card.stat().st_size
        if before <= LIMIT_BYTES:
            continue
        with Image.open(card) as image:
            palette = image.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        palette.save(card, optimize=True)
        log.info("Share card %s: %d KB -> %d KB", card.name, before // 1000, card.stat().st_size // 1000)
