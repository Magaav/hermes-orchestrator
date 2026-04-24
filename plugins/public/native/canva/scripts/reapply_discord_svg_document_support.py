#!/usr/bin/env python3
"""Apply the minimal Discord SVG ingress patch needed by the Canva plugin."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _agent_root() -> Path:
    return Path(os.getenv("HERMES_AGENT_ROOT", "/local/hermes-agent")).expanduser()


def _ensure_contains(content: str, old: str, new: str) -> tuple[str, bool]:
    if new in content:
        return content, False
    if old not in content:
        raise RuntimeError(f"anchor not found: {old[:80]!r}")
    return content.replace(old, new, 1), True


def _strip_if_present(content: str, snippet: str) -> tuple[str, bool]:
    if snippet not in content:
        return content, False
    return content.replace(snippet, "", 1), True


def _patch_discord_py(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    changed = False

    legacy_snippets = (
        """CANVA_INBOX_EXTENSIONS = {\n    \".svg\",\n    \".png\",\n    \".jpg\",\n    \".jpeg\",\n    \".webp\",\n    \".gif\",\n    \".pdf\",\n}\n\n\n""",
        """    def _resolve_canva_inbox_dir(self) -> Path:\n        hermes_home = Path(str(os.getenv(\"HERMES_HOME\", \"\") or \"\")).expanduser()\n        if hermes_home:\n            workspace_root = hermes_home.parent / \"workspace\"\n        else:\n            workspace_root = Path(\"/workspace\")\n        inbox = workspace_root / \"canva\" / \"files\" / \"inbox\"\n        inbox.mkdir(parents=True, exist_ok=True)\n        return inbox\n\n    def _mirror_attachment_to_canva_inbox(self, *, source_path: Optional[str] = None, raw_bytes: Optional[bytes] = None, filename: str = \"\") -> Optional[str]:\n        safe_name = Path(filename or \"attachment\").name\n        if not safe_name:\n            safe_name = \"attachment\"\n        ext = Path(safe_name).suffix.lower()\n        if ext not in CANVA_INBOX_EXTENSIONS:\n            return None\n        inbox = self._resolve_canva_inbox_dir()\n        stem = Path(safe_name).stem or \"attachment\"\n        target = inbox / f\"{stem}-{int(time.time())}{ext}\"\n        if raw_bytes is not None:\n            target.write_bytes(raw_bytes)\n            return str(target)\n        if source_path:\n            src = Path(source_path)\n            if src.exists():\n                shutil.copy2(src, target)\n                return str(target)\n        return None\n\n""",
        "import shutil\n",
        """                    inbox_path = self._mirror_attachment_to_canva_inbox(\n                        source_path=cached_path,\n                        filename=att.filename or f\"image{ext}\",\n                    )\n                    if inbox_path:\n                        note = (\n                            f\"[The user attached a Canva-ready image asset: '{att.filename or Path(inbox_path).name}'. \"\n                            f\"Use this local file path for Canva workflows: {inbox_path}]\"\n                        )\n                        pending_text_injection = f\"{pending_text_injection}\\n\\n{note}\" if pending_text_injection else note\n""",
        """                            inbox_path = self._mirror_attachment_to_canva_inbox(\n                                raw_bytes=raw_bytes,\n                                filename=att.filename or f\"document{ext}\",\n                            )\n                            if inbox_path:\n                                note = (\n                                    f\"[The user attached a Canva-ready file: '{att.filename or Path(inbox_path).name}'. \"\n                                    f\"Local file for Canva workflows: {inbox_path}]\"\n                                )\n                                pending_text_injection = f\"{pending_text_injection}\\n\\n{note}\" if pending_text_injection else note\n""",
    )
    for snippet in legacy_snippets:
        content, removed = _strip_if_present(content, snippet)
        changed = changed or removed

    replacements = (
        (
            """                if att.content_type:\n                    if att.content_type.startswith(\"image/\"):\n                        msg_type = MessageType.PHOTO\n                    elif att.content_type.startswith(\"video/\"):\n""",
            """                if att.content_type:\n                    is_svg = (\n                        att.content_type == \"image/svg+xml\"\n                        or str(getattr(att, \"filename\", \"\") or \"\").lower().endswith(\".svg\")\n                    )\n                    if att.content_type.startswith(\"image/\") and not is_svg:\n                        msg_type = MessageType.PHOTO\n                    elif is_svg:\n                        msg_type = MessageType.DOCUMENT\n                    elif att.content_type.startswith(\"video/\"):\n""",
        ),
        (
            """            content_type = att.content_type or \"unknown\"\n            if content_type.startswith(\"image/\"):\n""",
            """            content_type = att.content_type or \"unknown\"\n            is_svg = (\n                content_type == \"image/svg+xml\"\n                or str(getattr(att, \"filename\", \"\") or \"\").lower().endswith(\".svg\")\n            )\n            if content_type.startswith(\"image/\") and not is_svg:\n""",
        ),
        (
            """                if not ext and content_type:\n                    mime_to_ext = {v: k for k, v in SUPPORTED_DOCUMENT_TYPES.items()}\n                    ext = mime_to_ext.get(content_type, \"\")\n                if ext not in SUPPORTED_DOCUMENT_TYPES:\n""",
            """                if is_svg and not ext:\n                    ext = \".svg\"\n                if not ext and content_type:\n                    mime_to_ext = {v: k for k, v in SUPPORTED_DOCUMENT_TYPES.items()}\n                    ext = mime_to_ext.get(content_type, \"\")\n                effective_supported_docs = dict(SUPPORTED_DOCUMENT_TYPES)\n                effective_supported_docs[\".svg\"] = \"image/svg+xml\"\n                if ext not in effective_supported_docs:\n""",
        ),
        (
            """                            doc_mime = SUPPORTED_DOCUMENT_TYPES[ext]\n""",
            """                            doc_mime = effective_supported_docs[ext]\n""",
        ),
        (
            """        media_urls = []\n        media_types = []\n        pending_text_injection: Optional[str] = None\n""",
            """        media_urls = []\n        media_types = []\n        event_text = message.content\n        text_injections = []\n""",
        ),
        (
            """                                    if pending_text_injection:\n                                        pending_text_injection = f\"{pending_text_injection}\\n\\n{injection}\"\n                                    else:\n                                        pending_text_injection = injection\n""",
            """                                    text_injections.append(f\"[Content of {display_name}]:\\n{text_content}\")\n""",
        ),
        (
            """        event_text = message.content\n        if pending_text_injection:\n            event_text = f\"{pending_text_injection}\\n\\n{event_text}\" if event_text else pending_text_injection\n\n        # Defense-in-depth: prevent empty user messages from entering session\n""",
            """        if text_injections:\n            injection_block = \"\\n\\n\".join(text_injections)\n            event_text = f\"{injection_block}\\n\\n{event_text}\" if event_text else injection_block\n\n        # Defense-in-depth: prevent empty user messages from entering session\n""",
        ),
    )
    for old, new in replacements:
        content, applied = _ensure_contains(content, old, new)
        changed = changed or applied

    if changed:
        path.write_text(content, encoding="utf-8")
    return changed


def _patch_run_py(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    old = """                mtype = event.media_types[i] if i < len(event.media_types) else \"\"\n                if mtype.startswith(\"image/\") or event.message_type == MessageType.PHOTO:\n                    image_paths.append(path)\n"""
    new = """                mtype = event.media_types[i] if i < len(event.media_types) else \"\"\n                ext = Path(str(path)).suffix.lower()\n                is_raster_image = mtype.startswith(\"image/\") and ext not in {\".svg\"}\n                if is_raster_image or (event.message_type == MessageType.PHOTO and ext not in {\".svg\"}):\n                    image_paths.append(path)\n"""
    content, changed = _ensure_contains(content, old, new)
    if changed:
        path.write_text(content, encoding="utf-8")
    return changed


def main() -> int:
    agent_root = _agent_root()
    discord_py = agent_root / "gateway" / "platforms" / "discord.py"
    run_py = agent_root / "gateway" / "run.py"
    changed = False
    changed = _patch_discord_py(discord_py) or changed
    changed = _patch_run_py(run_py) or changed
    print(
        json.dumps(
            {
                "ok": True,
                "changed": changed,
                "discord_py": str(discord_py),
                "run_py": str(run_py),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
