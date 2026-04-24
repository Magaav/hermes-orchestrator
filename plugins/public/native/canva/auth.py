"""OAuth refresh-token auth for Canva Connect."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"


class CanvaAuthError(RuntimeError):
    """Raised when Canva auth fails."""


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "Bearer"
    scope: str = ""


class CanvaAuthManager:
    """Refresh and cache Canva access tokens."""

    def __init__(
        self,
        *,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        opener=None,
        now_fn=None,
    ) -> None:
        self._access_token_env = access_token or os.getenv("CANVA_ACCESS_TOKEN", "").strip()
        self._refresh_token = refresh_token or os.getenv("CANVA_REFRESH_TOKEN", "").strip()
        self._client_id = client_id or os.getenv("CANVA_CLIENT_ID", "").strip()
        self._client_secret = client_secret or os.getenv("CANVA_CLIENT_SECRET", "").strip()
        self._opener = opener or urllib.request.urlopen
        self._now_fn = now_fn or time.time
        self._state_path = self._resolve_state_path()
        self._token: Optional[TokenBundle] = None
        self._load_state()

    def validate_env(self) -> Dict[str, object]:
        missing = [
            name
            for name, value in (
                ("CANVA_REFRESH_TOKEN", self._refresh_token),
                ("CANVA_CLIENT_ID", self._client_id),
                ("CANVA_CLIENT_SECRET", self._client_secret),
            )
            if not value
        ]
        return {"ok": not missing, "missing": missing}

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and (self._token.expires_at - self._now_fn()) > 60:
            return self._token.access_token
        if not force_refresh and self._access_token_env:
            self._token = TokenBundle(
                access_token=self._access_token_env,
                refresh_token=self._refresh_token,
                expires_at=self._now_fn() + 300,
                token_type="Bearer",
                scope="",
            )
            return self._token.access_token
        with self._refresh_lock():
            self._load_state()
            if not force_refresh and self._token and (self._token.expires_at - self._now_fn()) > 60:
                return self._token.access_token
            self._token = self._refresh_access_token()
        return self._token.access_token

    def status(self, *, force_refresh: bool = False) -> Dict[str, object]:
        env_status = self.validate_env()
        if not env_status["ok"]:
            return {"ok": False, "missing": env_status["missing"], "has_token": False}
        token = self.get_access_token(force_refresh=force_refresh)
        return {
            "ok": True,
            "has_token": bool(token),
            "expires_at": int(self._token.expires_at) if self._token else None,
            "scope": self._token.scope if self._token else "",
            "token_type": self._token.token_type if self._token else "Bearer",
        }

    def _refresh_access_token(self) -> TokenBundle:
        env_status = self.validate_env()
        if not env_status["ok"]:
            raise CanvaAuthError("Missing Canva credentials: " + ", ".join(env_status["missing"]))

        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": self._refresh_token}).encode("utf-8")
        request = urllib.request.Request(
            TOKEN_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise CanvaAuthError(f"Canva token refresh failed: {exc}") from exc

        access_token = str(payload.get("access_token", "") or "").strip()
        refresh_token = str(payload.get("refresh_token", "") or "").strip() or self._refresh_token
        expires_in = int(payload.get("expires_in", 0) or 0)
        if not access_token or not refresh_token or expires_in <= 0:
            raise CanvaAuthError("Canva token response was missing required fields")
        self._refresh_token = refresh_token
        bundle = TokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=self._now_fn() + expires_in,
            token_type=str(payload.get("token_type", "Bearer") or "Bearer"),
            scope=str(payload.get("scope", "") or ""),
        )
        self._save_state(bundle)
        return bundle

    def _resolve_state_path(self) -> Path:
        hermes_home = str(os.getenv("HERMES_HOME", "") or "").strip()
        if hermes_home:
            root = Path(hermes_home).expanduser()
        else:
            root = Path.home() / ".hermes"
        return root / "auth" / "canva_oauth.json"

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        refresh = str(data.get("refresh_token", "") or "").strip()
        if refresh:
            self._refresh_token = refresh
        access = str(data.get("access_token", "") or "").strip()
        expires_at = float(data.get("expires_at", 0) or 0)
        if access and expires_at > self._now_fn():
            self._token = TokenBundle(
                access_token=access,
                refresh_token=self._refresh_token,
                expires_at=expires_at,
                token_type=str(data.get("token_type", "Bearer") or "Bearer"),
                scope=str(data.get("scope", "") or ""),
            )

    def _save_state(self, bundle: TokenBundle) -> None:
        payload = {
            "refresh_token": bundle.refresh_token,
            "access_token": bundle.access_token,
            "expires_at": bundle.expires_at,
            "token_type": bundle.token_type,
            "scope": bundle.scope,
            "updated_at": self._now_fn(),
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            self._state_path.chmod(0o600)
        except Exception:
            pass

    @contextlib.contextmanager
    def _refresh_lock(self):
        lock_path = self._state_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
