"""Immutable supervised image-teacher pairs for visual capability distillation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any


SCHEMA = "hermes.wasm_agent.image.teacher_edit.v1"
APPROVAL_SCHEMA = "hermes.wasm_agent.image.teacher_approval.v1"
PARTITIONS = frozenset({"training", "gold", "holdout"})
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_LABELS = 64
MAX_RULES = 64
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class VisualTeacherError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: Any, field: str, limit: int = 500) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise VisualTeacherError("teacher_contract_invalid", f"{field} is missing or too long.")
    if "data:image/" in text.lower() or "base64," in text.lower():
        raise VisualTeacherError("teacher_metadata_binary_forbidden", f"{field} contains inline image data.")
    return text


def _strings(value: Any, field: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise VisualTeacherError("teacher_contract_invalid", f"{field} must be a bounded list.")
    return [_text(item, field, 160) for item in value]


def _image(value: bytes, field: str) -> tuple[bytes, str]:
    if not isinstance(value, bytes) or not value or len(value) > MAX_IMAGE_BYTES:
        raise VisualTeacherError("teacher_image_invalid", f"{field} is empty or exceeds 32 MB.")
    if value.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif value.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif value.startswith((b"RIFF",)) and value[8:12] == b"WEBP":
        media_type = "image/webp"
    else:
        raise VisualTeacherError("teacher_image_invalid", f"{field} must be PNG, JPEG, or WebP.")
    return value, media_type


def default_root() -> Path:
    state = os.environ.get("HERMES_WASM_AGENT_STATE_DIR")
    if state:
        return Path(state) / "visual-teacher"
    return Path(__file__).resolve().parents[2] / "state" / "visual-teacher"


class VisualTeacherStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def _write_once(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.read_bytes() != content:
                raise VisualTeacherError("teacher_artifact_conflict", f"Immutable artifact conflict: {path.name}")
            return
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)

    def _blob(self, content: bytes) -> str:
        sha256 = digest(content)
        self._write_once(self.root / "blobs" / sha256[:2] / sha256, content)
        return sha256

    def register_candidate(
        self,
        *,
        source: bytes,
        mask: bytes,
        teacher_output: bytes,
        contract: dict[str, Any],
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        source, source_type = _image(source, "source")
        mask, mask_type = _image(mask, "mask")
        teacher_output, output_type = _image(teacher_output, "teacher_output")
        if mask_type != "image/png":
            raise VisualTeacherError("teacher_mask_invalid", "The teacher mask must be an alpha-channel PNG.")
        normalized_contract = {
            "objective": _text(contract.get("objective"), "objective", 1000),
            "remove_labels": _strings(contract.get("remove_labels"), "remove_labels", MAX_LABELS),
            "preserve_rules": _strings(contract.get("preserve_rules"), "preserve_rules", MAX_RULES),
            "reject_rules": _strings(contract.get("reject_rules"), "reject_rules", MAX_RULES),
            "mask_semantics": _text(contract.get("mask_semantics"), "mask_semantics", 160),
        }
        normalized_provenance = {
            "teacher": _text(provenance.get("teacher"), "teacher", 160),
            "session_id": _text(provenance.get("session_id"), "session_id", 160),
            "operator": _text(provenance.get("operator"), "operator", 160),
            "created_at": _text(provenance.get("created_at"), "created_at", 80),
        }
        blobs = {
            "source": {"sha256": self._blob(source), "bytes": len(source), "media_type": source_type},
            "mask": {"sha256": self._blob(mask), "bytes": len(mask), "media_type": mask_type},
            "teacher_output": {
                "sha256": self._blob(teacher_output),
                "bytes": len(teacher_output),
                "media_type": output_type,
            },
        }
        identity = canonical({"contract": normalized_contract, "provenance": normalized_provenance, "blobs": blobs})
        pair_id = f"pair_{digest(identity)[:24]}"
        manifest = {
            "schema": SCHEMA,
            "pair_id": pair_id,
            "status": "pending_approval",
            "contract": normalized_contract,
            "provenance": normalized_provenance,
            "blobs": blobs,
        }
        manifest_bytes = canonical(manifest)
        manifest_sha256 = digest(manifest_bytes)
        self._write_once(self.root / "candidates" / f"{pair_id}.json", manifest_bytes + b"\n")
        return {
            "ok": True,
            "pair_id": pair_id,
            "status": "pending_approval",
            "manifest_sha256": manifest_sha256,
            "blob_sha256": {key: value["sha256"] for key, value in blobs.items()},
        }

    def approve(
        self,
        pair_id: str,
        *,
        partition: str,
        approver: str,
        approved_at: str,
        expected_manifest_sha256: str,
    ) -> dict[str, Any]:
        if partition not in PARTITIONS:
            raise VisualTeacherError("teacher_partition_invalid", "Partition must be training, gold, or holdout.")
        if not re.fullmatch(r"pair_[0-9a-f]{24}", pair_id):
            raise VisualTeacherError("teacher_pair_invalid", "Pair id is invalid.")
        manifest_path = self.root / "candidates" / f"{pair_id}.json"
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise VisualTeacherError("teacher_pair_missing", "Teacher pair does not exist.") from exc
        actual_manifest_sha256 = digest(manifest_bytes.rstrip(b"\n"))
        if not SHA256.fullmatch(str(expected_manifest_sha256)) or expected_manifest_sha256 != actual_manifest_sha256:
            raise VisualTeacherError("teacher_manifest_changed", "Teacher manifest digest does not match approval.")
        approval = {
            "schema": APPROVAL_SCHEMA,
            "pair_id": pair_id,
            "partition": partition,
            "approver": _text(approver, "approver", 160),
            "approved_at": _text(approved_at, "approved_at", 80),
            "manifest_sha256": actual_manifest_sha256,
            "approval_nonce": secrets.token_hex(16),
        }
        target = self.root / ("private/holdout" if partition == "holdout" else f"approved/{partition}") / f"{pair_id}.json"
        existing = list(self.root.glob(f"approved/*/{pair_id}.json")) + list(self.root.glob(f"private/holdout/{pair_id}.json"))
        if existing:
            current = json.loads(existing[0].read_text(encoding="utf-8"))
            if current.get("partition") != partition:
                raise VisualTeacherError("teacher_partition_immutable", "Approved pairs cannot change partition.")
            return {
                "ok": True,
                "pair_id": pair_id,
                "partition": partition,
                "status": "approved",
                "approval_sha256": digest(existing[0].read_bytes().rstrip(b"\n")),
                "already_approved": True,
            }
        approval_bytes = canonical(approval)
        self._write_once(target, approval_bytes + b"\n")
        return {
            "ok": True,
            "pair_id": pair_id,
            "partition": partition,
            "status": "approved",
            "approval_sha256": digest(approval_bytes),
            "already_approved": False,
        }

    def summary(self) -> dict[str, Any]:
        count = lambda pattern: sum(1 for _ in self.root.glob(pattern))
        return {
            "schema": "hermes.wasm_agent.image.teacher_summary.v1",
            "pending": count("candidates/*.json")
            - count("approved/training/*.json")
            - count("approved/gold/*.json")
            - count("private/holdout/*.json"),
            "training": count("approved/training/*.json"),
            "gold": count("approved/gold/*.json"),
            "holdout": count("private/holdout/*.json"),
            "holdout_detail": "withheld",
        }
