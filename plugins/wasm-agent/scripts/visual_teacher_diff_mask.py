#!/usr/bin/env python3
"""Build a transparent-change teacher mask from an aligned source/target pair."""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def retain_components(image: Image.Image, minimum_area: int) -> Image.Image:
    width, height = image.size
    source = image.load()
    retained = Image.new("L", image.size, 0)
    output = retained.load()
    visited: set[tuple[int, int]] = set()
    for y in range(height):
        for x in range(width):
            if source[x, y] == 0 or (x, y) in visited:
                continue
            queue = deque([(x, y)])
            visited.add((x, y))
            component = []
            while queue:
                point = queue.popleft()
                component.append(point)
                px, py = point
                for neighbor in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    nx, ny = neighbor
                    if 0 <= nx < width and 0 <= ny < height and source[nx, ny] and neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            if len(component) >= minimum_area:
                for px, py in component:
                    output[px, py] = 255
    return retained


def difference_mask(
    source: Image.Image,
    target: Image.Image,
    threshold: int,
    dilation: int,
    minimum_area: int,
    include_boxes: list[tuple[float, float, float, float]],
) -> Image.Image:
    source = source.convert("RGB")
    target = target.convert("RGB")
    if source.size != target.size:
        raise ValueError("Source and target dimensions must match.")
    bands = ImageChops.difference(source, target).split()
    strongest = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2])
    changed = strongest.point(lambda value: 255 if value > threshold else 0)
    if include_boxes:
        allowed = Image.new("L", source.size, 0)
        draw = ImageDraw.Draw(allowed)
        width, height = source.size
        for left, top, right, bottom in include_boxes:
            draw.rectangle(
                (round(left * width), round(top * height), round(right * width), round(bottom * height)),
                fill=255,
            )
        changed = ImageChops.multiply(changed, allowed)
    changed = changed.filter(ImageFilter.MedianFilter(5))
    changed = retain_components(changed, minimum_area)
    if dilation > 1:
        changed = changed.filter(ImageFilter.MaxFilter(dilation))
    alpha = ImageChops.invert(changed)
    return Image.merge("RGBA", (alpha, alpha, alpha, alpha))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview")
    parser.add_argument("--threshold", type=int, default=24)
    parser.add_argument("--dilation", type=int, default=31)
    parser.add_argument("--minimum-area", type=int, default=256)
    parser.add_argument(
        "--include-box",
        action="append",
        default=[],
        metavar="LEFT,TOP,RIGHT,BOTTOM",
        help="Repeatable normalized review ROI; omit to inspect the full image.",
    )
    arguments = parser.parse_args()
    if not 0 <= arguments.threshold <= 255:
        parser.error("--threshold must be between 0 and 255")
    if arguments.dilation < 1 or arguments.dilation % 2 == 0:
        parser.error("--dilation must be a positive odd integer")
    if arguments.minimum_area < 1:
        parser.error("--minimum-area must be positive")
    include_boxes = []
    for raw_box in arguments.include_box:
        try:
            box = tuple(float(value) for value in raw_box.split(","))
        except ValueError:
            parser.error("--include-box values must be decimal numbers")
        if len(box) != 4 or not all(0 <= value <= 1 for value in box) or box[0] >= box[2] or box[1] >= box[3]:
            parser.error("--include-box must be LEFT,TOP,RIGHT,BOTTOM within 0..1")
        include_boxes.append(box)
    source = Image.open(arguments.source)
    target = Image.open(arguments.target)
    mask = difference_mask(
        source,
        target,
        arguments.threshold,
        arguments.dilation,
        arguments.minimum_area,
        include_boxes,
    )
    destination = Path(arguments.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mask.save(destination, format="PNG", optimize=True)
    if arguments.preview:
        preview = source.convert("RGBA")
        red = Image.new("RGBA", source.size, (255, 24, 24, 0))
        red.putalpha(ImageChops.invert(mask.getchannel("A")).point(lambda value: 120 if value else 0))
        preview.alpha_composite(red)
        preview_destination = Path(arguments.preview)
        preview_destination.parent.mkdir(parents=True, exist_ok=True)
        preview.convert("RGB").save(preview_destination, format="JPEG", quality=90, optimize=True)
    transparent = sum(1 for value in mask.getchannel("A").getdata() if value == 0)
    total = mask.width * mask.height
    print(json.dumps({
        "ok": True,
        "output": str(destination.resolve()),
        "transparent_fraction": round(transparent / total, 6),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
