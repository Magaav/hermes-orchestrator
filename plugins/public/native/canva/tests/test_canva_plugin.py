from __future__ import annotations

import base64
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

PLUGIN_PARENT = Path(__file__).resolve().parents[2]
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))
HERMES_AGENT_ROOT = Path("/local/hermes-agent")
if str(HERMES_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT_ROOT))

import canva
from canva.auth import CanvaAuthManager
from canva.client import CanvaClient
from canva.tools import (
    canva_autofill_design,
    canva_create_comment_reply,
    canva_create_comment_thread,
    canva_create_design,
    canva_list_local_assets,
    canva_make_poster_from_asset,
    canva_make_social_post,
    canva_normalize_design_brief,
    canva_qa_design_brief,
    canva_export_design,
    canva_get_comment_thread,
    canva_upload_asset_from_url,
)
from canva.runtime import resolve_workspace_root
from canva.hooks import inject_canva_turn_context
from hermes_constants import WorkspaceResolutionError


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_auth_refresh_success():
    calls = []

    def opener(request, timeout=0):
        calls.append(request)
        return _FakeResponse(
            json.dumps(
                {
                    "access_token": "token-1",
                    "refresh_token": "refresh-2",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "design:meta:read",
                }
            ).encode("utf-8")
        )

    auth = CanvaAuthManager(refresh_token="refresh-1", client_id="client", client_secret="secret", opener=opener, now_fn=lambda: 1000)
    auth._state_path = Path("/tmp/canva_auth_test_state.json")
    if auth._state_path.exists():
        auth._state_path.unlink()
    assert auth.get_access_token() == "token-1"
    assert auth.get_access_token() == "token-1"
    assert len(calls) == 1
    if auth._state_path.exists():
        auth._state_path.unlink()


def test_auth_persists_and_recovers_rotated_refresh_token(tmp_path):
    def opener(request, timeout=0):
        return _FakeResponse(
            json.dumps(
                {
                    "access_token": "token-1",
                    "refresh_token": "refresh-2",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "design:meta:read",
                }
            ).encode("utf-8")
        )

    auth = CanvaAuthManager(refresh_token="refresh-1", client_id="client", client_secret="secret", opener=opener, now_fn=lambda: 1000)
    auth._state_path = tmp_path / "canva_oauth.json"
    assert auth.get_access_token(force_refresh=True) == "token-1"
    payload = json.loads(auth._state_path.read_text(encoding="utf-8"))
    assert payload["refresh_token"] == "refresh-2"

    recovered = CanvaAuthManager(client_id="client", client_secret="secret", opener=opener, now_fn=lambda: 1001)
    recovered._state_path = auth._state_path
    recovered._load_state()
    assert recovered._refresh_token == "refresh-2"


def test_export_download_writes_workspace_canva(tmp_path):
    client = CanvaClient(auth=object(), opener=lambda request, timeout=0: _FakeResponse(b"image-bytes"))
    payload = {"job": {"status": "success", "result": {"urls": ["https://downloads.canva.test/export.png"]}}}
    downloads = client.download_export_result(payload, download_dir=tmp_path / "canva", filename_prefix="demo")
    assert len(downloads) == 1
    assert downloads[0]["path"].endswith("/canva/demo-1.png")
    assert (tmp_path / "canva" / "demo-1.png").read_bytes() == b"image-bytes"


def test_export_tool_uses_workspace_canva(monkeypatch, tmp_path):
    class FakeClient:
        def export_design(self, **kwargs):
            export_dir = kwargs["download_dir"]
            export_dir.mkdir(parents=True, exist_ok=True)
            path = export_dir / "D123-1.png"
            path.write_bytes(b"x")
            return {"downloads": [{"path": str(path), "filename": path.name, "url": "https://example.test/file"}]}

    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())
    raw = canva_export_design({"design_id": "D123", "format_type": "png"}, cwd=str(tmp_path))
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["export_dir"] == str(tmp_path / "canva" / "files")
    assert payload["downloads"][0]["path"].endswith("/canva/files/D123-1.png")
    assert Path(payload["log_path"]).exists()
    assert (tmp_path / "canva" / "logs" / "latest-export_design.json").exists()


class _FakeAuth:
    def __init__(self):
        self.force_refresh_calls = []

    def get_access_token(self, *, force_refresh=False):
        self.force_refresh_calls.append(force_refresh)
        return "fresh-token" if force_refresh else "stale-token"


def test_request_retries_after_401_with_forced_refresh():
    auth = _FakeAuth()
    calls = []

    def opener(request, timeout=0):
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs=None,
                fp=io.BytesIO(json.dumps({"message": "Access token is invalid"}).encode("utf-8")),
            )
        return _FakeResponse(json.dumps({"capabilities": ["autofill"]}).encode("utf-8"))

    client = CanvaClient(auth=auth, opener=opener)
    payload = client.get_capabilities()
    assert payload["capabilities"] == ["autofill"]
    assert auth.force_refresh_calls == [False, True]
    assert calls[0].headers["Authorization"] == "Bearer stale-token"
    assert calls[1].headers["Authorization"] == "Bearer fresh-token"


def test_upload_asset_sets_metadata_and_polls(tmp_path):
    class FakeAuth:
        def get_access_token(self, *, force_refresh=False):
            return "token"

    observed = []
    asset_file = tmp_path / "hero.png"
    asset_file.write_bytes(b"fake-png")

    def opener(request, timeout=0):
        observed.append(request)
        if request.full_url.endswith("/asset-uploads"):
            return _FakeResponse(json.dumps({"job": {"id": "job-1"}}).encode("utf-8"))
        if request.full_url.endswith("/asset-uploads/job-1"):
            return _FakeResponse(
                json.dumps({"asset": {"id": "asset-1", "import_status": {"state": "success"}}}).encode("utf-8")
            )
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    client = CanvaClient(auth=FakeAuth(), opener=opener)
    payload = client.upload_asset(file_path=asset_file, name="Launch Hero", tags=["promo", "spring"])
    assert payload["asset"]["id"] == "asset-1"
    create_request = observed[0]
    metadata = json.loads(create_request.headers["Asset-upload-metadata"])
    assert base64.b64decode(metadata["name_base64"]).decode("utf-8") == "Launch Hero"
    assert metadata["tags"] == ["promo", "spring"]
    assert create_request.headers["Content-type"] == "application/octet-stream"


def test_upload_asset_normalizes_job_asset_payload(tmp_path):
    class FakeAuth:
        def get_access_token(self, *, force_refresh=False):
            return "token"

    asset_file = tmp_path / "hero.png"
    asset_file.write_bytes(b"fake-png")

    def opener(request, timeout=0):
        if request.full_url.endswith("/asset-uploads"):
            return _FakeResponse(json.dumps({"job": {"id": "job-1"}}).encode("utf-8"))
        if request.full_url.endswith("/asset-uploads/job-1"):
            return _FakeResponse(
                json.dumps({"job": {"status": "success", "asset": {"id": "asset-2", "import_status": {"state": "success"}}}}).encode("utf-8")
            )
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    client = CanvaClient(auth=FakeAuth(), opener=opener)
    payload = client.upload_asset(file_path=asset_file, name="Launch Hero")
    assert payload["asset"]["id"] == "asset-2"


def test_autofill_tool_success(monkeypatch):
    class FakeClient:
        def create_autofill_design(self, **kwargs):
            return {"job": {"status": "success", "result": {"design_id": "D-AUTO"}}}

    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())
    raw = canva_autofill_design(
        {
            "brand_template_id": "tmpl-1",
            "title": "Launch Poster",
            "data": {"headline": {"type": "text", "text": "Ship Faster"}},
        }
    )
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["action"] == "autofill_design"
    assert payload["result"]["job"]["result"]["design_id"] == "D-AUTO"


def test_upload_asset_from_url_tool_success(monkeypatch):
    class FakeClient:
        def upload_asset_from_url(self, **kwargs):
            return {"asset": {"id": "asset-url-1"}}

    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())
    raw = canva_upload_asset_from_url({"url": "https://example.test/hero.png", "name": "Hero"})
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["action"] == "upload_asset_from_url"
    assert payload["result"]["asset"]["id"] == "asset-url-1"


def test_comment_tools_success(monkeypatch):
    class FakeClient:
        def create_comment_thread(self, **kwargs):
            return {"thread": {"id": "T-1"}}

        def get_comment_thread(self, **kwargs):
            return {"thread": {"id": "T-1", "design_id": "D-1"}}

        def create_comment_reply(self, **kwargs):
            return {"reply": {"id": "R-1"}}

    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())

    created = json.loads(canva_create_comment_thread({"design_id": "D-1", "message_plaintext": "Tighten the layout"}))
    fetched = json.loads(canva_get_comment_thread({"design_id": "D-1", "thread_id": "T-1"}))
    replied = json.loads(canva_create_comment_reply({"design_id": "D-1", "thread_id": "T-1", "message_plaintext": "Working on it"}))

    assert created["ok"] is True
    assert created["result"]["thread"]["id"] == "T-1"
    assert fetched["ok"] is True
    assert fetched["result"]["thread"]["design_id"] == "D-1"
    assert replied["ok"] is True
    assert replied["result"]["reply"]["id"] == "R-1"


def test_normalize_brief_and_qa_write_logs(tmp_path):
    normalized = json.loads(
        canva_normalize_design_brief(
            {
                "prompt": "Create a premium poster for retail operators.\nColmeio acelera sua operacao\nMais clareza, mais ritmo\nFale com a equipe",
                "asset_paths": ["/tmp/hero.png"],
            },
            cwd=str(tmp_path),
        )
    )
    assert normalized["ok"] is True
    assert normalized["result"]["brief"]["format"] == "poster"
    assert Path(normalized["log_path"]).exists()

    qa = json.loads(canva_qa_design_brief({"brief": normalized["result"]["brief"]}, cwd=str(tmp_path)))
    assert qa["ok"] is True
    assert qa["result"]["ready"] is True
    assert qa["result"]["score"] > 0
    assert (tmp_path / "canva" / "logs" / "session-manifest.jsonl").exists()


def test_make_poster_from_asset_creates_workspace_logs(monkeypatch, tmp_path):
    class FakeClient:
        def upload_asset(self, **kwargs):
            return {"asset": {"id": "asset-123"}}

    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())
    asset = tmp_path / "hero.png"
    asset.write_bytes(b"x")
    payload = json.loads(
        canva_make_poster_from_asset(
            {
                "headline": "Colmeio acelera sua operacao",
                "support_text": "Mais clareza, mais ritmo",
                "cta": "Fale com a equipe",
                "tone": "premium",
                "asset_path": str(asset),
                "title": "Poster Hero",
            },
            cwd=str(tmp_path),
        )
    )
    assert payload["ok"] is True
    assert payload["result"]["design_request"]["asset_id"] == "asset-123"
    assert payload["files_dir"] == str(tmp_path / "canva" / "files")
    assert payload["logs_dir"] == str(tmp_path / "canva" / "logs")
    assert Path(payload["log_path"]).exists()


def test_social_post_playbook_auto_reuses_recent_inbox_asset(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)

    inbox = tmp_path / "workspace" / "canva" / "files" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    recent = inbox / "hero.png"
    recent.write_bytes(b"img")

    class FakeClient:
        calls = 0

        def upload_asset(self, **kwargs):
            self.calls += 1
            return {"asset": {"id": "asset-777"}}

    fake_client = FakeClient()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr("canva.tools._client", lambda: fake_client)

    payload = json.loads(
        canva_make_social_post(
            {
                "headline": "Gestao que fecha o caixa com confianca",
                "support_text": "Operacao, escala e clareza em um so fluxo",
                "cta": "Fale com a nossa equipe",
                "tone": "premium",
                "audience": "Brazilian retail managers",
                "title": "Colmeio Social",
            }
        )
    )

    assert payload["ok"] is True
    assert payload["result"]["asset_resolution"]["asset_id"] == "asset-777"
    assert payload["result"]["asset_resolution"]["source"] == "uploaded_recent_inbox_asset"
    assert payload["result"]["design_request"]["width"] == 1080
    assert payload["result"]["design_request"]["height"] == 1080

    second = json.loads(
        canva_make_social_post(
            {
                "headline": "Gestao que fecha o caixa com confianca",
                "support_text": "Operacao, escala e clareza em um so fluxo",
                "cta": "Fale com a nossa equipe",
                "tone": "premium",
                "audience": "Brazilian retail managers",
                "title": "Colmeio Social",
            }
        )
    )
    assert second["ok"] is True
    assert second["result"]["asset_resolution"]["source"] == "cached_local_asset"


def test_social_post_playbook_blocks_when_no_assets_or_template(tmp_path):
    payload = json.loads(
        canva_make_social_post(
            {
                "headline": "Gestao que fecha o caixa com confianca",
                "support_text": "Operacao, escala e clareza em um so fluxo",
                "cta": "Fale com a nossa equipe",
                "tone": "premium",
                "audience": "Brazilian retail managers",
                "title": "Colmeio Social",
            },
            cwd=str(tmp_path),
        )
    )
    assert payload["ok"] is False
    assert "No asset" in payload["error"] or "brand template" in payload["error"] or "No asset" in json.dumps(payload)
    assert payload["qa"]["ready"] is False


def test_social_post_playbook_handles_invalid_recent_asset_without_crashing(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    inbox = tmp_path / "workspace" / "canva" / "files" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "broken.png").write_bytes(b"not-a-real-image")

    class FakeClient:
        def upload_asset(self, **kwargs):
            raise RuntimeError("invalid image bytes")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())

    payload = json.loads(
        canva_make_social_post(
            {
                "headline": "Gestao que fecha o caixa com confianca",
                "support_text": "Operacao, escala e clareza em um so fluxo",
                "cta": "Fale com a nossa equipe",
                "tone": "premium",
                "audience": "Brazilian retail managers",
                "title": "Colmeio Social",
            }
        )
    )
    assert payload["ok"] is False
    assert payload["asset_resolution"]["upload_errors"]


def test_list_local_assets_reads_inbox(tmp_path):
    inbox = tmp_path / "canva" / "files" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    asset = inbox / "hero.png"
    asset.write_bytes(b"img")
    payload = json.loads(canva_list_local_assets({"limit": 5}, cwd=str(tmp_path)))
    assert payload["ok"] is True
    assert payload["result"]["assets"][0]["path"].endswith("hero.png")


def test_create_design_blocks_blank_designs_by_default(tmp_path):
    payload = json.loads(canva_create_design({"title": "Blank Social", "width": 1080, "height": 1080}, cwd=str(tmp_path)))
    assert payload["ok"] is False
    assert "Blank design creation is blocked" in payload["error"]


def test_create_design_maps_instagram_alias_to_dimensions(monkeypatch):
    class FakeClient:
        def create_design(self, **kwargs):
            return {"design": {"id": "D-1"}, "kwargs": kwargs}

    monkeypatch.setattr("canva.tools._client", lambda: FakeClient())
    payload = json.loads(
        canva_create_design(
            {
                "title": "Social",
                "preset_name": "instagram-post",
                "asset_id": "asset-1",
            }
        )
    )
    assert payload["ok"] is True
    assert payload["resolved_surface"]["width"] == 1080
    assert payload["resolved_surface"]["height"] == 1080


def test_workspace_root_prefers_hermes_home_workspace(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    assert resolve_workspace_root(cwd="/local") == tmp_path / "workspace"


def test_workspace_root_prefers_node_root_workspace(monkeypatch, tmp_path):
    node_root = tmp_path / "agents" / "nodes" / "designer"
    monkeypatch.setenv("HERMES_NODE_ROOT", str(node_root))
    assert resolve_workspace_root(cwd="/local") == node_root / "workspace"


def test_workspace_root_refuses_generic_repo_root_without_node_context(monkeypatch):
    monkeypatch.delenv("HERMES_NODE_ROOT", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    with pytest.raises(WorkspaceResolutionError):
        resolve_workspace_root(cwd="/local")


def test_pre_llm_hook_stages_attachment_paths(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    source_image = tmp_path / "cache" / "hero.png"
    source_image.parent.mkdir(parents=True)
    source_image.write_bytes(b"img")
    payload = inject_canva_turn_context(
        session_id="sess-1",
        user_message=(
            f"[The user sent an image~ Here's what I can see: hero]\n"
            f"[If you need a closer look, use vision_analyze with image_url: {source_image} ~]\n\n"
            "Create a Canva poster for Colmeio"
        ),
        platform="discord",
    )
    assert isinstance(payload, dict)
    context = payload["context"]
    assert "/workspace/canva/files" in context
    inbox = tmp_path / "workspace" / "canva" / "files" / "inbox"
    staged = list(inbox.glob("hero-*.png"))
    assert staged
    latest_log = tmp_path / "workspace" / "canva" / "logs" / "latest-stage_inbound_assets.json"
    assert latest_log.exists()


def test_pre_llm_hook_reuses_paths_from_history(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    source_image = tmp_path / "cache" / "history-hero.png"
    source_image.parent.mkdir(parents=True)
    source_image.write_bytes(b"img")
    payload = inject_canva_turn_context(
        session_id="sess-2",
        user_message="Use the assets I attached in this thread to make a Canva social post",
        conversation_history=[
            {
                "role": "user",
                "content": f"[If you need a closer look, use vision_analyze with image_url: {source_image} ~]",
            }
        ],
        platform="discord",
    )
    assert isinstance(payload, dict)
    assert "history-hero" in payload["context"]


def test_register_exposes_extended_tools_and_skill():
    class FakeCtx:
        def __init__(self):
            self.tools = []
            self.commands = []
            self.cli = []
            self.skills = []
            self.hooks = []

        def register_tool(self, **kwargs):
            self.tools.append(kwargs["name"])

        def register_hook(self, name, callback):
            self.hooks.append(name)

        def register_command(self, name, **kwargs):
            self.commands.append(name)

        def register_cli_command(self, **kwargs):
            self.cli.append(kwargs["name"])

        def register_skill(self, name, path, **kwargs):
            self.skills.append((name, Path(path)))

    ctx = FakeCtx()
    canva.register(ctx)
    assert "canva_get_capabilities" in ctx.tools
    assert "canva_upload_asset" in ctx.tools
    assert "canva_list_local_assets" in ctx.tools
    assert "canva_get_asset" in ctx.tools
    assert "canva_update_asset" in ctx.tools
    assert "canva_delete_asset" in ctx.tools
    assert "canva_list_brand_templates" in ctx.tools
    assert "canva_autofill_design" in ctx.tools
    assert "canva_normalize_design_brief" in ctx.tools
    assert "canva_qa_design_brief" in ctx.tools
    assert "canva_make_poster_from_asset" in ctx.tools
    assert "canva_create_comment_thread" in ctx.tools
    assert "canva_get_comment_thread" in ctx.tools
    assert "canva_create_comment_reply" in ctx.tools
    assert "pre_llm_call" in ctx.hooks
    assert "canva" in ctx.cli
    assert ("canva-designer", Path("/local/plugins/public/native/canva/skills/canva-designer/SKILL.md")) in ctx.skills
