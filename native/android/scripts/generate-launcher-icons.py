#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

try:
    import cairosvg
except ImportError as exc:
    raise SystemExit(
        "generate-launcher-icons.py requires cairosvg. "
        "Install it in a virtualenv, then rerun this script."
    ) from exc


ROOT = Path(__file__).resolve().parents[3]
SOURCE_ICON = ROOT / "plugins/wasm-agent/public/icons/icon.svg"
RES = ROOT / "native/android/app/src/main/res"


def render_png(output: Path, size: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        url=str(SOURCE_ICON),
        write_to=str(output),
        output_width=size,
        output_height=size,
    )


def main() -> None:
    densities = {
        "mdpi": 1,
        "hdpi": 1.5,
        "xhdpi": 2,
        "xxhdpi": 3,
        "xxxhdpi": 4,
    }
    for density, scale in densities.items():
        render_png(
            RES / f"drawable-{density}/ic_launcher_foreground.png",
            int(108 * scale),
        )
        render_png(RES / f"mipmap-{density}/ic_launcher.png", int(48 * scale))
        render_png(RES / f"mipmap-{density}/ic_launcher_round.png", int(48 * scale))

    print(f"Generated Android launcher icons from {SOURCE_ICON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
