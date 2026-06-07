#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
PWA_ICON = ROOT / "plugins/wasm-agent/public/icons/icon.svg"
ELECTRON_ICON = ROOT / "native/windows/src/build/icon.svg"
RES = ROOT / "native/android/app/src/main/res"


def fail(message: str) -> None:
    print(f"launcher icon verification failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_adaptive_icon(name: str) -> None:
    path = RES / "mipmap-anydpi-v26" / f"{name}.xml"
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    root = ElementTree.parse(path).getroot()
    foreground = root.find("foreground")
    if foreground is None:
        fail(f"{path.relative_to(ROOT)} has no foreground")
    drawable = foreground.attrib.get("{http://schemas.android.com/apk/res/android}drawable")
    if drawable != "@drawable/ic_launcher_foreground":
        fail(f"{path.relative_to(ROOT)} foreground is {drawable!r}")


def verify_png(path: Path, expected_size: int) -> None:
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    with Image.open(path) as image:
        if image.size != (expected_size, expected_size):
            fail(
                f"{path.relative_to(ROOT)} is {image.size}, expected "
                f"{expected_size}x{expected_size}"
            )
        if image.mode not in ("RGBA", "LA"):
            fail(f"{path.relative_to(ROOT)} is {image.mode}, expected alpha PNG")


def main() -> None:
    if sha256(PWA_ICON) != sha256(ELECTRON_ICON):
        fail("PWA and Electron icon.svg files differ")
    if (RES / "drawable/ic_launcher_foreground.xml").exists():
        fail("old custom Android vector foreground still exists")

    verify_adaptive_icon("ic_launcher")
    verify_adaptive_icon("ic_launcher_round")

    densities = {
        "mdpi": 1,
        "hdpi": 1.5,
        "xhdpi": 2,
        "xxhdpi": 3,
        "xxxhdpi": 4,
    }
    for density, scale in densities.items():
        verify_png(
            RES / f"drawable-{density}/ic_launcher_foreground.png",
            int(108 * scale),
        )
        verify_png(RES / f"mipmap-{density}/ic_launcher.png", int(48 * scale))
        verify_png(RES / f"mipmap-{density}/ic_launcher_round.png", int(48 * scale))

    print("Android launcher icons use the shared WA icon artwork.")


if __name__ == "__main__":
    main()
