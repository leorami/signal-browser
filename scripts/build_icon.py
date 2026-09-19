#!/usr/bin/env python3
"""Compose the Dock icon: Signal-blue tile, inset official mark, compass.

ImageMagick often ignores SVG viewBox padding, so the glyph is rasterized
transparent and centered on a 1024 canvas with the same optical margin as
Signal's official app icon (~16% on each side).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

SIGNAL_BLUE = "#3B45FD"
CANVAS = 1024
# Official Signal keeps ~16% blue around the dashed ring.
GLYPH = 696


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    svg = root / "packaging" / "logo-appicon.svg"
    dest = root / "packaging" / "SignalBrowser.icns"
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        raise SystemExit("ImageMagick (magick) is required to build the app icon")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        glyph = work / "glyph.png"
        master = work / "logo.png"
        subprocess.run(
            [
                magick,
                "-density",
                "512",
                "-background",
                "none",
                str(svg),
                "-resize",
                f"{GLYPH}x{GLYPH}",
                f"PNG32:{glyph}",
            ],
            check=True,
        )
        subprocess.run(
            [
                magick,
                "-size",
                f"{CANVAS}x{CANVAS}",
                f"xc:{SIGNAL_BLUE}",
                str(glyph),
                "-gravity",
                "center",
                "-composite",
                "-alpha",
                "off",
                f"PNG24:{master}",
            ],
            check=True,
        )
        iconset = work / "SignalBrowser.iconset"
        iconset.mkdir()
        files = [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_512x512@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png"),
        ]
        for size, name in files:
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(master), "--out", str(iconset / name)],
                check=True,
                capture_output=True,
            )
        subprocess.run(["iconutil", "-c", "icns", "-o", str(dest), str(iconset)], check=True)
    print(dest)


if __name__ == "__main__":
    main()
