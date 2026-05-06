#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_mug_photo_bytes() -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    image = Image.new("RGB", (900, 1200), (150, 145, 132))
    draw = ImageDraw.Draw(image)
    for y in range(1200):
        shade = int(110 + y * 0.04)
        draw.line([(0, y), (900, y)], fill=(shade, max(90, shade - 10), max(80, shade - 18)))
    body = (150, 240, 750, 900)
    draw.rounded_rectangle(body, radius=80, fill=(180, 176, 160), outline=(25, 25, 24), width=16)
    for i in range(10):
        draw.ellipse((150 + i, 210 + i, 750 - i, 340 - i), outline=(20, 20, 20), width=4)
    draw.ellipse((190, 245, 710, 325), fill=(118, 108, 88), outline=(28, 28, 28), width=6)
    for i in range(18):
        draw.arc((690 + i, 480 + i, 940 - i, 760 - i), start=-70, end=80, fill=(185, 181, 165), width=14)
    try:
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 110)
        mid = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 62)
    except Exception:
        big = None
        mid = None
    for text, y, font in (("WANTED", 390, big), ("DEAD OR ALIVE", 520, mid), ("LUFFY", 610, big)):
        draw.text((210, y), text, fill=(18, 18, 18), font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


def write_sized_file(path: Path, size: int, mtime: float) -> None:
    path.write_bytes((path.name[:1] or "x").encode("ascii") * size)
    os.utime(path, (mtime, mtime))


def with_env(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    return previous


def restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def attachment_retention_test(server) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_server = SimpleNamespace(state_dir=Path(tmpdir))
        root = server.attachment_dir(fake_server)
        now = 1_700_000_000.0
        old_digest = "a" * 64
        mid_digest = "b" * 64
        keep_digest = "c" * 64
        for digest, offset in ((old_digest, 30), (mid_digest, 20), (keep_digest, 10)):
            write_sized_file(root / f"{digest}.png", 80, now - offset)
            write_sized_file(root / f"{digest}.json", 20, now - offset)
        previous = with_env({
            "HERMES_WASM_AGENT_ATTACHMENT_STORE_MAX_BYTES": "220",
            "HERMES_WASM_AGENT_ATTACHMENT_STORE_MAX_FILES": "4",
            "HERMES_WASM_AGENT_ATTACHMENT_MAX_AGE_SEC": "0",
        })
        try:
            result = server.prune_agent_attachments(fake_server, keep_hashes={keep_digest})
        finally:
            restore_env(previous)
        assert result["schema"] == "hermes.wasm_agent.attachment_retention.v1"
        assert result["deleted_records"] == 1, result
        assert result["deleted_files"] == 2, result
        assert not (root / f"{old_digest}.png").exists(), result
        assert not (root / f"{old_digest}.json").exists(), result
        assert (root / f"{mid_digest}.png").exists(), result
        assert (root / f"{keep_digest}.png").exists(), result
        assert result["bytes_after"] <= 220, result
        assert result["files_after"] <= 4, result


def attachment_save_test(server) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_server = SimpleNamespace(state_dir=Path(tmpdir))
        result = server.save_agent_attachment(fake_server, {
            "image": {
                "data_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM=",
                "name": "test.png",
                "size": 11,
                "width": 1,
                "height": 1,
                "image_card": {
                    "schema": "hermes.wasm_agent.image_card.v1",
                    "analyzer_revision": "image-card-text-v2",
                    "visual_notes": ["small test image"],
                },
            }
        })
        assert result["schema"] == "hermes.wasm_agent.attachment_asset.v1", result
        assert result["local_url"].startswith("/agent/attachments/"), result
        assert result["retention"]["schema"] == "hermes.wasm_agent.attachment_retention.v1", result
        root = server.attachment_dir(fake_server)
        assert any(path.suffix == ".png" for path in root.iterdir()), result
        assert any(path.suffix == ".json" for path in root.iterdir()), result


def main() -> int:
    payload = synthetic_mug_photo_bytes()
    if payload is None:
        print("image-card golden skipped: PIL unavailable")
        return 0
    server = load_server_module()
    stale_card = {
        "schema": "hermes.wasm_agent.image_card.v1",
        "name": "synthetic-mug-like-photo.jpg",
        "visual_notes": [],
    }
    card = server.server_enrich_stale_image_card(stale_card, payload)
    assert card["analyzer_revision"] == "image-card-text-v2+server-fallback"
    notes = card["visual_notes"]
    assert any("text-like" in note or "printed" in note for note in notes), notes
    assert any("rounded or cylindrical" in note for note in notes), notes
    analysis = card["analysis"]
    assert analysis["text_like_score"] >= 0.6, analysis
    assert analysis["text_band_estimate"] >= 3, analysis
    composition = card["composition"]
    scene_hints = composition["scene_hints"]
    assert scene_hints["printed_object_or_label_likelihood"] >= 0.65, scene_hints
    assert scene_hints["screenshot_likelihood"] <= 0.2, scene_hints
    shape_hints = composition["shape_hints"]
    assert shape_hints["cylindrical_surface_likelihood"] >= 0.65, shape_hints
    assert shape_hints["rim_like_band"]["score"] >= 0.65, shape_hints
    module_results = card["module_results"]
    assert "server-image-card-core" in module_results
    assert module_results["server-image-card-core"]["values"]["source"] == "server_fallback"
    current_card = {
        "schema": "hermes.wasm_agent.image_card.v1",
        "name": "current-browser-mug-like-photo.jpg",
        "analyzer_revision": "image-card-text-v2",
        "analysis": {"text_like_score": 0.5},
        "composition": {},
        "visual_notes": ["browser-built card"],
    }
    hinted_card = server.server_enrich_stale_image_card(current_card, payload)
    assert hinted_card["analyzer_revision"] == "image-card-text-v2+server-hints"
    assert "scene_hints" in hinted_card["composition"], hinted_card["composition"]
    assert "shape_hints" in hinted_card["composition"], hinted_card["composition"]
    hinted_result = hinted_card["module_results"]["server-image-card-core"]
    assert hinted_result["reason"] == "browser_image_card_missing_scene_shape_hints", hinted_result
    assert hinted_result["values"]["source"] == "server_hints", hinted_result
    assert server.server_enrich_stale_image_card(hinted_card, payload) is hinted_card
    attachment_retention_test(server)
    attachment_save_test(server)
    print("image-card golden ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
