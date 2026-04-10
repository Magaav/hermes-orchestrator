import unittest

from gateway.followup import (
    build_followup_summary_lines,
    coerce_followup_bool,
    coerce_followup_minutes,
    count_followup_tool_errors,
)


class FollowupNotificationTests(unittest.TestCase):
    def test_coerce_followup_minutes_defaults_and_floor(self):
        self.assertEqual(coerce_followup_minutes("", default=10), 10)
        self.assertEqual(coerce_followup_minutes("abc", default=10), 10)
        self.assertEqual(coerce_followup_minutes("0", default=10), 1)
        self.assertEqual(coerce_followup_minutes("5", default=10), 5)

    def test_coerce_followup_bool_parsing(self):
        self.assertIs(coerce_followup_bool("true"), True)
        self.assertIs(coerce_followup_bool("YES"), True)
        self.assertIs(coerce_followup_bool("1"), True)
        self.assertIs(coerce_followup_bool("false"), False)
        self.assertIs(coerce_followup_bool("0"), False)
        self.assertIs(coerce_followup_bool("", default=True), True)

    def test_count_followup_tool_errors_detects_structured_and_text_errors(self):
        prev_tools = [
            {"name": "read_file", "result": '{"success": true}'},
            {"name": "patch", "result": '{"success": false, "error": "failed"}'},
            {"name": "terminal", "result": "Error: command failed"},
        ]
        self.assertEqual(count_followup_tool_errors(prev_tools), 2)

    def test_build_followup_summary_lines_includes_activity_and_state(self):
        activity = {
            "api_call_count": 19,
            "max_iterations": 80,
            "current_tool": "read_file",
            "last_activity_desc": "starting API call #19",
        }
        state = {
            "iteration": 19,
            "tool_names": ["terminal", "read_file"],
            "error_count": 1,
        }

        lines = build_followup_summary_lines(activity, state)

        self.assertEqual(lines[0], "iteration 19/80 in progress")
        self.assertIn("running tool: read_file", lines)
        self.assertTrue(any(line.startswith("last tools:") for line in lines))
        self.assertIn("tool errors detected: 1", lines)


if __name__ == "__main__":
    unittest.main()
