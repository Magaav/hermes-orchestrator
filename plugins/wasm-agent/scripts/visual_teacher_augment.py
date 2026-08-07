#!/usr/bin/env python3
"""Create and approve deterministic aligned variants from visual-teacher gold pairs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps


SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier.visual_teacher_store import VisualTeacherStore  # noqa: E402


def blob(store: VisualTeacherStore, sha256: str) -> bytes:
    return (store.root / "blobs" / sha256[:2] / sha256).read_bytes()


def encoded(image: Image.Image, media_type: str) -> bytes:
    output = BytesIO()
    if media_type == "image/png":
        image.save(output, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def transform(image: Image.Image, index: int, *, is_mask: bool = False) -> Image.Image:
    width, height = image.size
    scale = (0.92, 0.95, 0.97, 0.985, 1.0)[index % 5]
    crop_width = max(1, round(width * scale))
    crop_height = max(1, round(height * scale))
    horizontal = (index * 37 % 101) / 100
    vertical = (index * 53 % 101) / 100
    left = round((width - crop_width) * horizontal)
    top = round((height - crop_height) * vertical)
    resample = Image.Resampling.NEAREST if is_mask else Image.Resampling.LANCZOS
    result = image.crop((left, top, left + crop_width, top + crop_height)).resize((width, height), resample)
    if index % 2:
        result = ImageOps.mirror(result)
    if is_mask:
        return result
    brightness = (0.9, 0.96, 1.0, 1.04, 1.1)[(index // 5) % 5]
    contrast = (0.94, 0.98, 1.0, 1.03, 1.07)[(index * 3) % 5]
    return ImageEnhance.Contrast(ImageEnhance.Brightness(result).enhance(brightness)).enhance(contrast)


def contact_tile(source: Image.Image, mask: Image.Image, target: Image.Image, label: str) -> Image.Image:
    tile = Image.new("RGB", (360, 156), "white")
    for position, image in enumerate((source, target)):
        preview = ImageOps.contain(image.convert("RGB"), (174, 130))
        x = 4 + position * 180 + (174 - preview.width) // 2
        tile.paste(preview, (x, 20 + (130 - preview.height) // 2))
    overlay = ImageOps.contain(mask.getchannel("A"), (174, 130))
    red = Image.new("RGBA", overlay.size, (255, 30, 30, 0))
    red.putalpha(ImageOps.invert(overlay).point(lambda value: 110 if value > 8 else 0))
    target_x = 184 + (174 - red.width) // 2
    tile.paste(red, (target_x, 20 + (130 - red.height) // 2), red)
    ImageDraw.Draw(tile).text((5, 3), label, fill="black")
    return tile


def generate(arguments: argparse.Namespace) -> dict:
    store = VisualTeacherStore(arguments.root)
    approvals = sorted((store.root / "approved/gold").glob("*.json"))
    if not approvals:
        raise RuntimeError("No approved gold pairs are available.")
    created_at = datetime.now(timezone.utc).isoformat()
    candidates = []
    tiles = []
    for approval_path in approvals:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        manifest = json.loads((store.root / "candidates" / f"{approval['pair_id']}.json").read_text(encoding="utf-8"))
        source = Image.open(BytesIO(blob(store, manifest["blobs"]["source"]["sha256"]))).convert("RGB")
        mask = Image.open(BytesIO(blob(store, manifest["blobs"]["mask"]["sha256"]))).convert("RGBA")
        target = Image.open(BytesIO(blob(store, manifest["blobs"]["teacher_output"]["sha256"]))).convert("RGB")
        if target.size != source.size:
            target = target.resize(source.size, Image.Resampling.LANCZOS)
        if mask.size != source.size:
            mask = mask.resize(source.size, Image.Resampling.NEAREST)
        for index in range(arguments.count_per_gold):
            source_variant = transform(source, index)
            mask_variant = transform(mask, index, is_mask=True)
            target_variant = transform(target, index)
            contract = dict(manifest["contract"])
            contract["objective"] = (
                f"{contract['objective']} Deterministic aligned augmentation {index + 1}/"
                f"{arguments.count_per_gold} derived from approved gold pair {approval['pair_id']}."
            )
            candidate = store.register_candidate(
                source=encoded(source_variant, "image/jpeg"),
                mask=encoded(mask_variant, "image/png"),
                teacher_output=encoded(target_variant, "image/jpeg"),
                contract=contract,
                provenance={
                    "teacher": "approved-gold-deterministic-augmentation",
                    "session_id": arguments.session_id,
                    "operator": arguments.operator,
                    "created_at": created_at,
                },
            )
            candidates.append({
                "pair_id": candidate["pair_id"],
                "manifest_sha256": candidate["manifest_sha256"],
                "parent_gold_pair_id": approval["pair_id"],
                "augmentation_index": index,
            })
            tiles.append(contact_tile(source_variant, mask_variant, target_variant, f"{approval['pair_id'][-6:]} · {index + 1}"))
    columns = 5
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 360, rows * 156), "#dddddd")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % columns) * 360, (index // columns) * 156))
    Path(arguments.contact_sheet).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(arguments.contact_sheet, format="JPEG", quality=88, optimize=True)
    batch = {
        "schema": "hermes.wasm_agent.image.teacher_augmentation_batch.v1",
        "created_at": created_at,
        "count": len(candidates),
        "contact_sheet": str(Path(arguments.contact_sheet).resolve()),
        "candidates": candidates,
    }
    Path(arguments.batch_manifest).write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "count": len(candidates), "batch_manifest": arguments.batch_manifest, "contact_sheet": arguments.contact_sheet}


def approve(arguments: argparse.Namespace) -> dict:
    store = VisualTeacherStore(arguments.root)
    batch = json.loads(Path(arguments.batch_manifest).read_text(encoding="utf-8"))
    approved_at = datetime.now(timezone.utc).isoformat()
    results = [
        store.approve(
            item["pair_id"],
            partition="training",
            approver=arguments.approver,
            approved_at=approved_at,
            expected_manifest_sha256=item["manifest_sha256"],
        )
        for item in batch["candidates"]
    ]
    return {"ok": True, "approved": len(results), "summary": store.summary()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate")
    create.add_argument("--count-per-gold", type=int, default=25)
    create.add_argument("--session-id", required=True)
    create.add_argument("--operator", required=True)
    create.add_argument("--batch-manifest", required=True)
    create.add_argument("--contact-sheet", required=True)
    accept = commands.add_parser("approve")
    accept.add_argument("--batch-manifest", required=True)
    accept.add_argument("--approver", required=True)
    arguments = parser.parse_args()
    if arguments.command == "generate" and not 1 <= arguments.count_per_gold <= 50:
        parser.error("--count-per-gold must be between 1 and 50")
    try:
        result = generate(arguments) if arguments.command == "generate" else approve(arguments)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
