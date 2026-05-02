from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


HELPERS_PATH = Path("/local/plugins/discord-slash-commands/tests/test_discord_slash_runtime.py")


def load_helpers():
    spec = importlib.util.spec_from_file_location("slash_runtime_test_helpers", HELPERS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load runtime test helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScientificRuntimeTests(unittest.TestCase):
    def test_governance_channel_acl_auto_enables_scientific_command(self) -> None:
        helpers = load_helpers()
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_root = helpers._seed_state(tmp_path, enabled_commands=["acl", "slash", "status"])
            governance_root = cache_root / "governance"
            governance_root.mkdir(parents=True, exist_ok=True)
            (governance_root / "channel_acl.yaml").write_text(
                "\n".join(
                    [
                        "channels:",
                        "  '1497340589191204898':",
                        "    mode: condicionado",
                        "    allowed_commands:",
                        "      - scientific-paper-meta-analysis",
                        "    default_action: command:scientific-paper-meta-analysis",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "HERMES_DISCORD_SLASH_CACHE_ROOT": str(cache_root),
                    "HERMES_DISCORD_PRIVATE_DIR": str(governance_root),
                    "NODE_NAME": "paracelsus",
                },
                clear=False,
            ):
                runtime = helpers._load_runtime()
                self.assertTrue(runtime.is_command_enabled("scientific-paper-meta-analysis"))
                app_scope = json.loads((cache_root / "state" / "app_scope.json").read_text(encoding="utf-8"))
                self.assertIn("scientific-paper-meta-analysis", app_scope.get("enabled_commands") or [])

    def test_render_scientific_pipeline_response_prefers_meta_analysis_packet(self) -> None:
        helpers = load_helpers()
        runtime = helpers._load_runtime()

        rendered = runtime._render_scientific_pipeline_response(
            {
                "report_id": "1497799328289394798",
                "total_raw": 12,
                "total_deduplicated": 6,
                "query": "endothelial function and sauna",
                "papers": [{"title": "Example Paper"}],
                "meta_analysis": {
                    "narrative": "The evidence stack is synthesis-led and the strongest signal sits in the cardiovascular outcomes tier.",
                    "bottom_line": "Start with the synthesis papers, then pressure-test the observational signal.",
                    "clinical_takeaways": [
                        "The top paper is a systematic review.",
                        "Human outcome data is stronger than the mechanistic layer.",
                    ],
                    "uncertainties": ["Trials are still sparse."],
                    "rabbit_holes": ["Compare endpoint definitions across the top-ranked papers."],
                    "ranked_papers": [
                        {
                            "rank": 1,
                            "year": "2025",
                            "title": "Systematic review of sauna exposure",
                            "why_it_matters": "systematic review / meta-analysis, high citation gravity",
                        }
                    ],
                    "evidence_profile": {
                        "total_papers": 6,
                        "open_access_count": 3,
                        "study_design_counts": {"synthesis": 2, "trial": 1, "observational": 2},
                    },
                },
                "cache": {"mode": "mixed", "hits": 2, "misses": 1, "asset_downloads": 0},
            }
        )

        self.assertIn("report: 1497799328289394798", rendered)
        self.assertIn("run stats:", rendered)
        self.assertIn("meta-analysis:", rendered)
        self.assertIn("bottom line:", rendered)
        self.assertIn("clinical takeaways:", rendered)
        self.assertIn("rabbit holes to close:", rendered)
        self.assertIn("ranked leads:", rendered)

    def test_handle_scientific_paper_meta_analysis_returns_pipeline_response(self) -> None:
        helpers = load_helpers()
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            helpers._seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "scientific-paper-meta-analysis"])
            with patch.dict(
                os.environ,
                {
                    "HERMES_DISCORD_SLASH_CACHE_ROOT": str(helpers._cache_root(tmp_path)),
                    "NODE_NAME": "paracelsus",
                },
                clear=False,
            ):
                runtime = helpers._load_runtime()
                with patch.object(
                    runtime,
                    "_execute_scientific_pipeline",
                    return_value="doctor-facing meta analysis",
                ):
                    result = asyncio.run(runtime.handle_scientific_paper_meta_analysis('query:"GLP-1 agonists"'))

            self.assertEqual(result, "doctor-facing meta analysis")

    def test_handle_pre_gateway_message_scientific_dispatches_runtime(self) -> None:
        helpers = load_helpers()
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            helpers._seed_state(tmp_path, enabled_commands=["acl", "slash", "status", "scientific-paper-meta-analysis"])
            with patch.dict(
                os.environ,
                {
                    "HERMES_DISCORD_SLASH_CACHE_ROOT": str(helpers._cache_root(tmp_path)),
                    "NODE_NAME": "paracelsus",
                },
                clear=False,
            ):
                runtime = helpers._load_runtime()
                dispatched = []

                async def fake_dispatch(gateway, source, message_text):
                    dispatched.append((gateway, source, message_text))

                gateway = object()
                source = SimpleNamespace(platform="discord", chat_id="c1", thread_id=None)
                with patch.object(runtime, "_dispatch_normalized_command", fake_dispatch):
                    result = asyncio.run(
                        runtime.handle_pre_gateway_message(
                            platform="discord",
                            source=source,
                            message='/scientific-paper-meta-analysis query:"GLP-1 agonists"',
                            gateway=gateway,
                        )
                    )

            self.assertEqual(result, {"decision": "handled", "message": "", "already_replied": True})
            self.assertEqual(
                dispatched,
                [(gateway, source, '/scientific-paper-meta-analysis query:"GLP-1 agonists"')],
            )


if __name__ == "__main__":
    unittest.main()
