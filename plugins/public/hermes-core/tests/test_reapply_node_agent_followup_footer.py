import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path('/local/plugins/public/hermes-core/scripts/reapply_node_agent_followup_footer.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('node_agent_patch', SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError('Could not load patch module')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE_CONTENT = """        # Bridge sync step_callback → async hooks.emit for agent:step events
        _loop_for_step = asyncio.get_event_loop()
        _hooks_ref = self.hooks

        def _step_callback_sync(iteration: int, prev_tools: list) -> None:
            try:
                # prev_tools may be list[str] or list[dict] with \"name\"/\"result\"
                # keys.  Normalise to keep \"tool_names\" backward-compatible for
                # user-authored hooks that do ', '.join(tool_names)'.
                _names: list[str] = []
                for _t in (prev_tools or []):
                    if isinstance(_t, dict):
                        _names.append(_t.get(\"name\") or \"\")
                    else:
                        _names.append(str(_t))
                asyncio.run_coroutine_threadsafe(
                    _hooks_ref.emit(\"agent:step\", {
                        \"platform\": source.platform.value if source.platform else \"\",
                        \"user_id\": source.user_id,
                        \"session_id\": session_id,
                        \"iteration\": iteration,
                        \"tool_names\": _names,
                        \"tools\": prev_tools,
                    }),
                    _loop_for_step,
                )
            except Exception as _e:
                logger.debug(\"agent:step hook error: %s\", _e)

            agent.step_callback = _step_callback_sync if _hooks_ref.loaded_hooks else None

        # Periodic \"still working\" notifications for long-running tasks.
        # Fires every 10 minutes so the user knows the agent hasn't died.
        _NOTIFY_INTERVAL = 600  # 10 minutes
        _notify_start = time.time()

        async def _notify_long_running():
            _notify_adapter = self.adapters.get(source.platform)
            if not _notify_adapter:
                return
            while True:
                await asyncio.sleep(_NOTIFY_INTERVAL)
                _elapsed_mins = int((time.time() - _notify_start) // 60)
                # Include agent activity context if available.
                _agent_ref = agent_holder[0]
                _status_detail = \"\"
                if _agent_ref and hasattr(_agent_ref, \"get_activity_summary\"):
                    try:
                        _a = _agent_ref.get_activity_summary()
                        _parts = [f\"iteration {_a['api_call_count']}/{_a['max_iterations']}\"]
                        if _a.get(\"current_tool\"):
                            _parts.append(f\"running: {_a['current_tool']}\")
                        else:
                            _parts.append(_a.get(\"last_activity_desc\", \"\"))
                        _status_detail = \" — \" + \", \".join(_parts)
                    except Exception:
                        pass
                try:
                    await _notify_adapter.send(
                        source.chat_id,
                        f\"⏳ Still working... ({_elapsed_mins} min elapsed{_status_detail})\",
                        metadata=_status_thread_metadata,
                    )
                except Exception as _ne:
                    logger.debug(\"Long-running notification error: %s\", _ne)

            # Sync session_id: the agent may have created a new session during
"""


class ReapplyNodeAgentPatchTests(unittest.TestCase):
    def test_apply_functions_are_idempotent(self):
        mod = _load_module()
        content = BASE_CONTENT

        changed_any = False
        for fn in (
            mod._apply_runtime_block,
            mod._apply_step_summary_block,
            mod._apply_step_callback_assignment,
            mod._apply_notify_block,
            mod._apply_final_footer_block,
            mod._apply_richer_followup_summary,
        ):
            content, changed = fn(content)
            changed_any = changed_any or changed

        self.assertTrue(changed_any)
        self.assertIn('COLMEIO_NODE_AGENT_RUNTIME_BEGIN', content)
        self.assertIn('COLMEIO_NODE_AGENT_STEP_SUMMARY_BEGIN', content)
        self.assertIn('COLMEIO_NODE_AGENT_FOLLOWUP_NOTIFY_BEGIN', content)
        self.assertIn('COLMEIO_NODE_AGENT_FINAL_FOOTER_BEGIN', content)
        self.assertIn('(_hooks_ref.loaded_hooks or _followup_summary_enabled)', content)
        self.assertIn('_NOTIFY_INTERVAL = _followup_elapsed_minutes * 60', content)
        self.assertIn('def _push_recent_line(bucket_key: str, value: str, limit: int)', content)
        self.assertIn('Objective:', content)
        self.assertIn('Decision:', content)
        self.assertIn('"window_tool_names": []', content)
        self.assertIn('def _record_followup_tool_result(tool_name: Any, raw_result: Any) -> None', content)
        self.assertIn('def _record_followup_activity(tool_name: Any, preview: Any, raw_args: Any)', content)
        self.assertIn('created_paths: List[str] = []', content)
        self.assertIn('deleted_paths: List[str] = []', content)
        self.assertIn('_append_paths("Created", created_paths)', content)
        self.assertIn('_append_paths("Deleted", deleted_paths)', content)

        # Reapplying should be a no-op.
        second = content
        changed_any_second = False
        for fn in (
            mod._apply_runtime_block,
            mod._apply_step_summary_block,
            mod._apply_step_callback_assignment,
            mod._apply_notify_block,
            mod._apply_final_footer_block,
            mod._apply_richer_followup_summary,
        ):
            second, changed = fn(second)
            changed_any_second = changed_any_second or changed

        self.assertFalse(changed_any_second)
        self.assertEqual(content, second)


if __name__ == '__main__':
    unittest.main()
