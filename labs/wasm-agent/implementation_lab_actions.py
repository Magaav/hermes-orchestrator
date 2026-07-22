"""Safe-lab adapter from MF5 semantic actions to existing repository primitives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from master_frontier import repository_actions, repository_checks, repository_diff


class ImplementationLabActions:
    def __init__(self, route: dict[str, Any]) -> None:
        self.route = route
        self.root = Path(str(route["workspace_root"])).resolve()

    def _resolve_write(self, value: str) -> Path:
        raw = Path(str(value or ""))
        candidate = (raw if raw.is_absolute() else self.root / raw).resolve()
        roots = [Path(str(item)).resolve() for item in self.route.get("allowed_write_roots") or []]
        if not value or not any(candidate == root or root in candidate.parents for root in roots):
            raise repository_actions.RepositoryActionError("patch_scope_denied", "Patch target is outside the lab workspace.")
        allowed = {str(item) for item in self.route.get("allowed_write_paths") or []}
        if allowed and candidate.relative_to(self.root).as_posix() not in allowed:
            raise repository_actions.RepositoryActionError("patch_scope_denied", "Patch target is not owned by this challenge.")
        if ".git" in candidate.parts:
            raise repository_actions.RepositoryActionError("patch_scope_denied", "Git metadata is not patchable.")
        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _check(self, check_id: str) -> dict[str, Any]:
        check = next((item for item in self.route.get("checks") or [] if item.get("id") == check_id), None)
        if not isinstance(check, dict):
            return {"ok": False, "code": "check_not_registered", "summary": "Focused check is not route-registered."}
        result = repository_checks.run(check["command"], cwd=self.root, timeout_sec=check["timeout_sec"])
        return {**result, "check_id": check_id, "summary": f"Focused check {check_id} {result['status']}."}

    def invoke(self, primitive: str, payload: dict[str, Any]) -> dict[str, Any]:
        if primitive == "kernel.act":
            action = str(payload.get("local_action") or "")
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            if action == "patch.apply_scoped":
                try:
                    result = repository_actions.apply(
                        args.get("operations") if isinstance(args.get("operations"), list) else [],
                        dry_run=bool(args.get("dry_run")), resolve=self._resolve_write, relative=self._relative,
                        max_operations=24, max_file_bytes=262144, max_payload_bytes=262144,
                    )
                except repository_actions.RepositoryActionError as exc:
                    return {"ok": False, "code": exc.code, "local_action": action, "summary": str(exc)}
                return {"ok": True, "code": "ok", "local_action": action, "result": result, "summary": "Applied scoped lab patch."}
            if action == "test.run_focused":
                result = self._check(str(args.get("check_id") or ""))
                return {**result, "local_action": action}
            if action == "git.diff_summary":
                result = repository_diff.collect(self.route)
                return {**result, "local_action": action, "summary": "Collected route-scoped Git diff."}
        if primitive == "kernel.prove":
            return {
                "ok": True, "code": "ok", "primitive": "kernel.prove",
                "schema": "wasm-agent.safe-lab.kernel.prove.v1",
                "route_id": self.route["route_id"], "summary": "Collected scoped lab proof.",
            }
        return {"ok": False, "code": "tool_adapter_missing", "summary": f"Unsupported lab primitive: {primitive}"}
