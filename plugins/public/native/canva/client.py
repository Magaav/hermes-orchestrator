"""Small Canva Connect API client."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from .auth import CanvaAuthManager, CanvaAuthError


API_ROOT = "https://api.canva.com/rest/v1"


class CanvaApiError(RuntimeError):
    """Raised for normalized Canva API failures."""

    def __init__(self, message: str, *, status: int = 0, payload: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class CanvaClient:
    def __init__(self, auth: Optional[CanvaAuthManager] = None, opener=None) -> None:
        self.auth = auth or CanvaAuthManager()
        self._opener = opener or urllib.request.urlopen

    def auth_status(self, *, force_refresh: bool = False) -> Dict[str, object]:
        return self.auth.status(force_refresh=force_refresh)

    def get_capabilities(self) -> dict:
        return self._request_json("GET", "/users/me/capabilities")

    def list_designs(self, *, query: str = "", ownership: str = "any", sort_by: str = "relevance", limit: int = 25, continuation: str = "") -> dict:
        params = {"ownership": ownership, "sort_by": sort_by, "limit": str(max(1, min(int(limit or 25), 100)))}
        if query.strip():
            params["query"] = query.strip()
        if continuation.strip():
            params["continuation"] = continuation.strip()
        return self._request_json("GET", "/designs", params=params)

    def list_brand_templates(
        self,
        *,
        query: str = "",
        ownership: str = "any",
        dataset: str = "any",
        sort_by: str = "relevance",
        limit: int = 25,
        continuation: str = "",
    ) -> dict:
        params = {
            "ownership": ownership,
            "dataset": dataset,
            "sort_by": sort_by,
            "limit": str(max(1, min(int(limit or 25), 100))),
        }
        if query.strip():
            params["query"] = query.strip()
        if continuation.strip():
            params["continuation"] = continuation.strip()
        return self._request_json("GET", "/brand-templates", params=params)

    def get_brand_template_dataset(self, brand_template_id: str) -> dict:
        return self._request_json("GET", f"/brand-templates/{urllib.parse.quote(brand_template_id)}/dataset")

    def get_design(self, design_id: str) -> dict:
        return self._request_json("GET", f"/designs/{urllib.parse.quote(design_id)}")

    def get_design_pages(self, design_id: str) -> dict:
        return self._request_json("GET", f"/designs/{urllib.parse.quote(design_id)}/pages")

    def get_export_formats(self, design_id: str) -> dict:
        return self._request_json("GET", f"/designs/{urllib.parse.quote(design_id)}/export-formats")

    def create_comment_thread(self, *, design_id: str, message_plaintext: str, assignee_id: str = "") -> dict:
        body: Dict[str, object] = {"message_plaintext": message_plaintext.strip()}
        if assignee_id.strip():
            body["assignee_id"] = assignee_id.strip()
        return self._request_json("POST", f"/designs/{urllib.parse.quote(design_id)}/comments", body=body)

    def get_comment_thread(self, *, design_id: str, thread_id: str) -> dict:
        return self._request_json("GET", f"/designs/{urllib.parse.quote(design_id)}/comments/{urllib.parse.quote(thread_id)}")

    def create_comment_reply(self, *, design_id: str, thread_id: str, message_plaintext: str) -> dict:
        body = {"message_plaintext": message_plaintext.strip()}
        return self._request_json(
            "POST",
            f"/designs/{urllib.parse.quote(design_id)}/comments/{urllib.parse.quote(thread_id)}/replies",
            body=body,
        )

    def list_comment_replies(self, *, design_id: str, thread_id: str, continuation: str = "") -> dict:
        params = {}
        if continuation.strip():
            params["continuation"] = continuation.strip()
        return self._request_json(
            "GET",
            f"/designs/{urllib.parse.quote(design_id)}/comments/{urllib.parse.quote(thread_id)}/replies",
            params=params or None,
        )

    def create_autofill_design(
        self,
        *,
        brand_template_id: str,
        data: dict,
        title: str = "",
    ) -> dict:
        body: Dict[str, object] = {
            "brand_template_id": brand_template_id.strip(),
            "data": data,
        }
        if title.strip():
            body["title"] = title.strip()
        created = self._request_json("POST", "/autofills", body=body)
        job_id = str(created.get("job", {}).get("id", "") or "").strip()
        if not job_id:
            raise CanvaApiError("Autofill job response did not include a job id", payload=created)
        return self.poll_autofill_job(job_id)

    def poll_autofill_job(self, job_id: str, *, timeout_sec: int = 120, interval_sec: float = 2.0) -> dict:
        deadline = time.time() + max(5, timeout_sec)
        while time.time() < deadline:
            payload = self._request_json("GET", f"/autofills/{urllib.parse.quote(job_id)}")
            status = str(payload.get("job", {}).get("status", "") or "").lower()
            if status in {"success", "failed"}:
                return payload
            time.sleep(interval_sec)
        raise CanvaApiError(f"Autofill job {job_id} timed out")

    def create_design(self, *, title: str = "", preset_name: str = "", width: int = 0, height: int = 0, asset_id: str = "") -> dict:
        body: Dict[str, object] = {}
        if preset_name.strip():
            body["design_type"] = {"type": "preset", "name": preset_name.strip()}
        else:
            body["design_type"] = {"type": "custom", "width": int(width), "height": int(height)}
        if asset_id.strip():
            body["type"] = "type_and_asset"
            body["asset_id"] = asset_id.strip()
        if title.strip():
            body["title"] = title.strip()
        return self._request_json("POST", "/designs", body=body)

    def resize_design(self, *, design_id: str, preset_name: str = "", width: int = 0, height: int = 0) -> dict:
        design_type: Dict[str, object]
        if preset_name.strip():
            design_type = {"type": "preset", "name": preset_name.strip()}
        else:
            design_type = {"type": "custom", "width": int(width), "height": int(height)}
        created = self._request_json("POST", "/resizes", body={"design_id": design_id.strip(), "design_type": design_type})
        job_id = str(created.get("job", {}).get("id", "") or "").strip()
        if not job_id:
            raise CanvaApiError("Resize job response did not include a job id", payload=created)
        return self.poll_resize_job(job_id)

    def poll_resize_job(self, job_id: str, *, timeout_sec: int = 90, interval_sec: float = 2.0) -> dict:
        deadline = time.time() + max(5, timeout_sec)
        while time.time() < deadline:
            payload = self._request_json("GET", f"/resizes/{urllib.parse.quote(job_id)}")
            status = str(payload.get("job", {}).get("status", "") or "").lower()
            if status in {"success", "failed"}:
                return payload
            time.sleep(interval_sec)
        raise CanvaApiError(f"Resize job {job_id} timed out")

    def export_design(self, *, design_id: str, export_spec: dict, download_dir: Path, filename_prefix: str = "") -> dict:
        created = self._request_json("POST", "/exports", body={"design_id": design_id.strip(), "format": export_spec})
        job_id = str(created.get("job", {}).get("id", "") or "").strip()
        if not job_id:
            raise CanvaApiError("Export job response did not include a job id", payload=created)
        result = self.poll_export_job(job_id)
        result["downloads"] = self.download_export_result(result, download_dir=download_dir, filename_prefix=filename_prefix or design_id)
        return result

    def poll_export_job(self, job_id: str, *, timeout_sec: int = 120, interval_sec: float = 2.0) -> dict:
        deadline = time.time() + max(5, timeout_sec)
        while time.time() < deadline:
            payload = self._request_json("GET", f"/exports/{urllib.parse.quote(job_id)}")
            status = str(payload.get("job", {}).get("status", "") or "").lower()
            if status in {"success", "failed"}:
                return payload
            time.sleep(interval_sec)
        raise CanvaApiError(f"Export job {job_id} timed out")

    def download_export_result(self, payload: dict, *, download_dir: Path, filename_prefix: str) -> list[dict]:
        urls = self._extract_export_urls(payload)
        download_dir.mkdir(parents=True, exist_ok=True)
        downloads = []
        for index, url in enumerate(urls, start=1):
            suffix = self._infer_suffix(url)
            name = f"{filename_prefix}-{index}{suffix}"
            path = download_dir / name
            request = urllib.request.Request(url, method="GET")
            try:
                with self._opener(request, timeout=120) as response:
                    path.write_bytes(response.read())
            except Exception as exc:
                raise CanvaApiError(f"Failed to download export artifact: {exc}") from exc
            downloads.append({"url": url, "path": str(path), "filename": name})
        return downloads

    def _extract_export_urls(self, payload: dict) -> list[str]:
        job = payload.get("job", {})
        if str(job.get("status", "") or "").lower() == "failed":
            error = job.get("error") or {}
            raise CanvaApiError(str(error.get("message", "Canva export job failed") or "Canva export job failed"), payload=payload)
        urls = []
        direct_urls = job.get("urls")
        if isinstance(direct_urls, list):
            urls.extend(str(item) for item in direct_urls if str(item).strip())
        result = job.get("result") or {}
        for key in ("urls", "download_urls"):
            value = result.get(key)
            if isinstance(value, list):
                urls.extend(str(item) for item in value if str(item).strip())
        if not urls and str(result.get("url", "") or "").strip():
            urls.append(str(result["url"]))
        if not urls:
            raise CanvaApiError("Canva export job completed without download URLs", payload=payload)
        return urls

    def upload_asset(self, *, file_path: Path, name: str = "", tags: Optional[list[str]] = None) -> dict:
        file_path = Path(file_path).expanduser().resolve()
        if not file_path.exists() or not file_path.is_file():
            raise CanvaApiError(f"Asset file not found: {file_path}")
        metadata = {"name_base64": base64.b64encode((name or file_path.stem).encode("utf-8")).decode("ascii")}
        if tags:
            metadata["tags"] = list(tags)
        with file_path.open("rb") as handle:
            created = self._request_raw(
                "POST",
                "/asset-uploads",
                data=handle.read(),
                headers={
                    "Content-Type": "application/octet-stream",
                    "Asset-Upload-Metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )
        job_id = str(created.get("job", {}).get("id", "") or "").strip()
        if not job_id:
            raise CanvaApiError("Asset upload response did not include a job id", payload=created)
        return self.poll_asset_upload_job(job_id)

    def upload_asset_from_url(self, *, url: str, name: str, tags: Optional[list[str]] = None) -> dict:
        body: Dict[str, object] = {"url": url.strip(), "name": name.strip()}
        if tags:
            body["tags"] = list(tags)
        created = self._request_json("POST", "/url-asset-uploads", body=body)
        job_id = str(created.get("job", {}).get("id", "") or "").strip()
        if not job_id:
            raise CanvaApiError("URL asset upload response did not include a job id", payload=created)
        return self.poll_url_asset_upload_job(job_id)

    def poll_asset_upload_job(self, job_id: str, *, timeout_sec: int = 120, interval_sec: float = 2.0) -> dict:
        deadline = time.time() + max(5, timeout_sec)
        while time.time() < deadline:
            payload = self._request_json("GET", f"/asset-uploads/{urllib.parse.quote(job_id)}")
            asset = self._normalize_asset_payload(payload)
            state = str(asset.get("import_status", {}).get("state", "") or payload.get("job", {}).get("status", "") or "").lower()
            if state in {"success", "failed"} or asset.get("id"):
                return payload
            time.sleep(interval_sec)
        raise CanvaApiError(f"Asset upload job {job_id} timed out")

    def poll_url_asset_upload_job(self, job_id: str, *, timeout_sec: int = 120, interval_sec: float = 2.0) -> dict:
        deadline = time.time() + max(5, timeout_sec)
        while time.time() < deadline:
            payload = self._request_json("GET", f"/url-asset-uploads/{urllib.parse.quote(job_id)}")
            asset = self._normalize_asset_payload(payload)
            state = str(asset.get("import_status", {}).get("state", "") or payload.get("job", {}).get("status", "") or "").lower()
            if state in {"success", "failed"} or asset.get("id"):
                return payload
            time.sleep(interval_sec)
        raise CanvaApiError(f"URL asset upload job {job_id} timed out")

    def get_asset(self, asset_id: str) -> dict:
        return self._request_json("GET", f"/assets/{urllib.parse.quote(asset_id)}")

    def update_asset(self, *, asset_id: str, name: str = "", tags: Optional[list[str]] = None) -> dict:
        body: Dict[str, object] = {}
        if name.strip():
            body["name"] = name.strip()
        if tags is not None:
            body["tags"] = list(tags)
        if not body:
            raise CanvaApiError("Provide name and/or tags to update an asset")
        return self._request_json("PATCH", f"/assets/{urllib.parse.quote(asset_id)}", body=body)

    def delete_asset(self, asset_id: str) -> dict:
        self._request_raw("DELETE", f"/assets/{urllib.parse.quote(asset_id)}")
        return {"deleted": True, "asset_id": asset_id}

    def _request_json(self, method: str, path: str, *, params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
        return self._request_raw(method, path, params=params, body=body)

    def _request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        data: Optional[bytes] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        force_refresh = False
        for attempt in range(2):
            try:
                token = self.auth.get_access_token(force_refresh=force_refresh)
            except CanvaAuthError as exc:
                raise CanvaApiError(str(exc)) from exc
            url = f"{API_ROOT}{path}"
            if params:
                url = f"{url}?{urllib.parse.urlencode(params)}"
            final_headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if headers:
                final_headers.update(headers)
            request_data = data
            if body is not None:
                request_data = json.dumps(body).encode("utf-8")
                final_headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=request_data, method=method, headers=final_headers)
            try:
                with self._opener(request, timeout=60) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(detail) if detail else {}
                except Exception:
                    payload = {"raw": detail}
                if int(exc.code) == 401 and attempt == 0:
                    force_refresh = True
                    continue
                message = payload.get("message") or payload.get("error", {}).get("message") or f"Canva API request failed with status {exc.code}"
                raise CanvaApiError(str(message), status=int(exc.code), payload=payload) from exc
            except Exception as exc:
                raise CanvaApiError(f"Canva API request failed: {exc}") from exc
        raise CanvaApiError("Canva API request failed after retry")

    @staticmethod
    def _infer_suffix(url: str) -> str:
        suffix = Path(urllib.parse.urlparse(url).path).suffix
        return suffix or ".bin"

    @staticmethod
    def _normalize_asset_payload(payload: dict) -> dict:
        asset = payload.get("asset")
        if isinstance(asset, dict) and asset:
            return asset
        job_asset = payload.get("job", {}).get("asset")
        if isinstance(job_asset, dict) and job_asset:
            payload["asset"] = job_asset
            return job_asset
        return {}
