#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SERVER = PLUGIN / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, route_contracts  # noqa: E402
from master_frontier.v5 import policy, tools  # noqa: E402


_MISSING = object()


class MasterFrontierV5AuthorityTests(unittest.TestCase):
    @staticmethod
    def route(
        root: Path, caps: list[str], *, request_class: str = "implementation",
        task_authority: object = _MISSING, write_roots: object = _MISSING,
    ) -> dict:
        task: dict[str, object] = {"request_class": request_class}
        if task_authority is not _MISSING:
            task["authority"] = task_authority
        result: dict[str, object] = {
            "route_id": "fixture.authority",
            "workspace_root": str(root),
            "allowed_read_roots": [str(root)],
            "caps": caps,
            "task_contract": task,
        }
        if request_class == "runtime_inspection" and "runtime.inspect" in caps:
            result["entities"] = [{"id": "entity-a", "kind": "fixture"}]
        if write_roots is not _MISSING:
            result["allowed_write_roots"] = write_roots
        return result

    @staticmethod
    def names(route: dict) -> list[str]:
        return [item["name"] for item in policy.descriptors_for(route)]

    def test_each_tool_requires_its_individual_route_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def scoped(caps: list[str]) -> dict:
                return self.route(
                    root, caps, request_class="unclassified",
                    task_authority=caps, write_roots=[str(root)],
                )
            self.assertEqual(self.names(scoped(["repo.read"])), ["search", "read"])
            self.assertEqual(self.names(scoped(["repo.edit"])), ["edit"])
            self.assertEqual(self.names(scoped(["test.run"])), ["test"])
            self.assertEqual(self.names(scoped(["proof.report"])), ["diff", "prove"])
            self.assertEqual(
                self.names(scoped(["repo.read", "repo.edit", "test.run", "proof.report"])),
                ["search", "read", "edit", "test", "diff", "prove"],
            )

    def test_one_route_capability_cannot_execute_sibling_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(root, ["repo.edit"], write_roots=[str(root)])
            invoked: list[str] = []
            for name, arguments in (("test", {"check_id": "focused"}), ("diff", {}), ("prove", {})):
                result = tools.execute(
                    name, arguments, route,
                    invoke=lambda tool, _arguments: invoked.append(tool) or {"ok": True},
                )
                self.assertEqual(result["code"], "capability_denied")
            self.assertEqual(invoked, [])

    def test_implementation_planning_is_read_only_even_on_write_capable_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(
                root, ["repo.read", "repo.edit", "test.run", "proof.report"],
                request_class="implementation_planning",
                task_authority=["repo.read", "repo.edit", "test.run", "proof.report"],
                write_roots=[str(root)],
            )
            self.assertEqual(self.names(route), ["search", "read"])
            self.assertEqual(authority.coherence(route)["ok"], True)

    def test_explicit_task_authority_is_intersected_with_route_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(
                root, ["repo.read", "repo.edit", "test.run", "proof.report"],
                request_class="unclassified",
                task_authority=["repo.edit", "runtime.inspect"], write_roots=[str(root)],
            )
            self.assertEqual(authority.effective(route), frozenset({"repo.edit"}))
            self.assertEqual(self.names(route), ["edit"])
            route["task_contract"]["authority"] = []
            self.assertEqual(self.names(route), [])

    def test_source_tasks_remain_read_only_even_with_broad_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(
                root, ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                request_class="source_investigation",
                task_authority=["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                write_roots=[str(root)],
            )
            self.assertEqual(self.names(route), ["search", "read"])
            invoked: list[tuple[str, dict]] = []
            result = tools.execute(
                "edit", {"operations": [{"op": "create", "path": "x.py", "content": "x = 1\n"}]}, route,
                invoke=lambda name, arguments: invoked.append((name, arguments)) or {"ok": True},
            )
            self.assertEqual(result["code"], "capability_denied")
            self.assertEqual(result["required_capability"], "repo.edit")
            self.assertEqual(invoked, [])

    def test_raw_fallback_call_is_denied_at_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(root, ["repo.edit"], request_class="source_investigation", write_roots=[str(root)])
            self.assertTrue(policy.allowed("edit"))
            self.assertFalse(policy.allowed("edit", route))
            invoked: list[str] = []
            result = tools.execute("edit", {"operations": []}, route, invoke=lambda name, _args: invoked.append(name) or {"ok": True})
            self.assertEqual(result["code"], "capability_denied")
            self.assertEqual(invoked, [])

    def test_unknown_task_defaults_to_declared_repo_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unknown = self.route(
                root, ["repo.read", "repo.edit", "test.run", "proof.report"],
                request_class="unclassified", write_roots=[str(root)],
            )
            self.assertEqual(self.names(unknown), ["search", "read"])
            self.assertEqual(self.names(self.route(root, ["repo.edit"], request_class="unclassified", write_roots=[str(root)])), [])
            explicitly_authorized = self.route(
                root, ["repo.edit"], request_class="unclassified",
                task_authority=["repo.edit"], write_roots=[str(root)],
            )
            self.assertEqual(self.names(explicitly_authorized), ["edit"])

    def test_runtime_unavailable_sentinel_authorizes_one_typed_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(root, ["runtime.inspect.unavailable"], request_class="runtime_inspection")
            self.assertEqual(self.names(route), ["inspect"])
            invoked: list[tuple[str, dict]] = []
            result = tools.execute(
                "inspect", {"target": "runtime_entity", "id": "entity-a"}, route,
                invoke=lambda name, arguments: invoked.append((name, arguments)) or {
                    "ok": False, "code": "capability_unavailable", "summary": "Runtime inspection is unavailable.",
                },
            )
            self.assertEqual(result["code"], "capability_unavailable")
            self.assertEqual([item[0] for item in invoked], ["kernel.inspect"])

    def test_runtime_task_cannot_expand_into_source_or_mutation_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = self.route(
                root, ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                request_class="runtime_inspection",
                task_authority=["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                write_roots=[str(root)],
            )
            self.assertEqual(self.names(route), ["inspect"])

    def test_missing_write_roots_normalize_empty_and_disable_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = Path(tmp)
            normalized = route_contracts.normalize_contract({
                "route_id": "fixture.no-write-root",
                "workspace_root": ".",
                "allowed_read_roots": ["."],
                "caps": ["repo.edit"],
            }, plugin_root)
            self.assertEqual(normalized["allowed_write_roots"], [])
            normalized["task_contract"] = {"request_class": "implementation"}
            self.assertNotIn("edit", self.names(normalized))
            invoked: list[str] = []
            result = tools.execute("edit", {"operations": []}, normalized, invoke=lambda name, _args: invoked.append(name) or {"ok": True})
            self.assertEqual(result["code"], "capability_denied")
            self.assertEqual(invoked, [])

    def test_explicit_production_write_roots_are_preserved(self) -> None:
        registry = json.loads((SERVER / "agent_route_contracts.json").read_text(encoding="utf-8"))
        contracts = route_contracts.load_contracts(SERVER / "agent_route_contracts.json", PLUGIN)
        self.assertEqual(len(contracts), len(registry["routes"]))
        by_id = {item["route_id"]: item for item in contracts}
        for raw in registry["routes"]:
            expected = [route_contracts.contract_path(PLUGIN, item) for item in raw.get("allowed_write_roots", [])]
            self.assertEqual(by_id[raw["route_id"]]["allowed_write_roots"], expected)

    def test_v5_edit_requires_an_observed_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scoped = self.route(
                root, ["repo.edit"], request_class="unclassified",
                task_authority=["repo.edit"], write_roots=[str(root)],
            )
            invoked: list[tuple[str, dict]] = []
            missing = tools.execute(
                "edit", {"operations": [{"op": "replace", "path": "x.py", "find": "a", "replace": "b"}]},
                scoped, invoke=lambda name, args: invoked.append((name, args)) or {"ok": True},
            )
            self.assertEqual(missing["code"], "patch_precondition_required")
            self.assertEqual(invoked, [])
            accepted = tools.execute(
                "edit", {"operations": [{
                    "op": "replace", "path": "x.py", "find": "a", "replace": "b",
                    "expected_sha256": "a" * 64,
                }, {
                    "op": "replace", "path": "x.py", "find": "c", "replace": "d",
                }]}, scoped, invoke=lambda name, args: invoked.append((name, args)) or {"ok": True},
            )
            self.assertTrue(accepted["ok"])
            self.assertEqual(invoked[0][0], "kernel.act")

    def test_controller_task_projection_preserves_explicit_authority(self) -> None:
        route = {"caps": ["repo.read", "repo.edit", "runtime.inspect"]}
        projected = authority.project_task_contract({
            "objective_kind": "implementation",
            "task_contract": {"intent": "implementation", "authority": ["repo.read"]},
        }, route)
        self.assertEqual(projected["request_class"], "implementation")
        self.assertEqual(projected["authority"], ["repo.read"])
        diagnosis = authority.project_task_contract({
            "objective": "critisize meta-analysis widget inside realure space",
            "task_contract": {"intent": "diagnosis", "evidence_floor": "route"},
        }, route)
        self.assertEqual(diagnosis["request_class"], "source_investigation")

    def test_capability_presence_never_selects_runtime_modality(self) -> None:
        broad_route = {"caps": ["repo.read", "runtime.inspect"]}
        source = authority.project_task_contract({
            "task_contract": {"intent": "diagnosis", "evidence_floor": "source"},
        }, broad_route)
        route_only = authority.project_task_contract({
            "task_contract": {"intent": "diagnosis", "evidence_floor": "route"},
        }, broad_route)
        runtime = authority.project_task_contract({
            "task_contract": {"intent": "diagnosis", "evidence_floor": "runtime"},
        }, {"caps": ["repo.read"]})
        top_level_runtime = authority.project_task_contract({
            "objective_kind": "diagnosis", "evidence_floor": "runtime",
        }, broad_route)
        self.assertEqual(source["request_class"], "source_investigation")
        self.assertEqual(route_only["request_class"], "source_investigation")
        self.assertEqual(runtime["request_class"], "runtime_inspection")
        self.assertEqual(top_level_runtime["request_class"], "runtime_inspection")

    def test_evidence_class_coherence_fails_closed_before_tool_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mismatch = self.route(
                root, ["repo.read", "runtime.inspect"], request_class="runtime_inspection",
            )
            mismatch["task_contract"]["evidence_floor"] = "source"
            self.assertEqual(self.names(mismatch), [])
            self.assertEqual(authority.coherence(mismatch), {
                "ok": False,
                "code": "evidence_class_mismatch",
                "class": "runtime_inspection",
                "evidence": "source",
                "caps": [],
            })

            missing = self.route(root, ["repo.read"], request_class="runtime_inspection")
            missing["task_contract"]["evidence_floor"] = "runtime"
            status = authority.coherence(missing)
            self.assertFalse(status["ok"])
            self.assertEqual(status["code"], "evidence_capability_missing")
            self.assertEqual(status["required"], "runtime.inspect")

            source = self.route(root, ["repo.read", "runtime.inspect"], request_class="source_investigation")
            source["task_contract"]["evidence_floor"] = "source"
            self.assertEqual(self.names(source), ["search", "read"])
            self.assertTrue(authority.coherence(source)["ok"])

            missing_scope = self.route(root, ["runtime.inspect"], request_class="runtime_inspection")
            missing_scope["task_contract"]["evidence_floor"] = "runtime"
            missing_scope.pop("entities")
            scope_status = authority.coherence(missing_scope)
            self.assertEqual(scope_status["code"], "runtime_entity_scope_missing")
            self.assertEqual(self.names(missing_scope), [])

    def test_blocked_and_impossible_workflows_fail_before_tool_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked = self.route(
                root, ["repo.read", "repo.edit", "test.run", "proof.report"],
                write_roots=[str(root)],
            )
            blocked["task_contract"].update({
                "executor": "blocked",
                "block_codes": ["capability_missing"],
            })
            self.assertEqual(authority.coherence(blocked)["code"], "task_contract_blocked")
            self.assertEqual(self.names(blocked), [])

            implementation = self.route(root, ["repo.read"], write_roots=[str(root)])
            status = authority.coherence(implementation)
            self.assertEqual(status["code"], "task_capability_missing")
            self.assertEqual(status["required"], ["proof.report", "repo.edit", "test.run"])
            self.assertEqual(self.names(implementation), [])

            verification = self.route(root, ["repo.read"], request_class="verification")
            status = authority.coherence(verification)
            self.assertEqual(status["code"], "task_capability_missing")
            self.assertEqual(status["required"], ["proof.report", "test.run"])
            self.assertEqual(self.names(verification), [])

            mismatched = self.route(
                root, ["repo.read", "repo.edit", "test.run", "proof.report"],
                request_class="conversation", write_roots=[str(root)],
            )
            mismatched["task_contract"]["declared_classes"] = ["conversation", "implementation"]
            self.assertEqual(authority.coherence(mismatched)["code"], "declared_class_mismatch")
            self.assertEqual(self.names(mismatched), [])


if __name__ == "__main__":
    unittest.main()
