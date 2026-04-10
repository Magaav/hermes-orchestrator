import json
import unittest

from gateway.final_response_footer import (
    build_files_changed_footer,
    coerce_files_footer_bool,
)


class FinalResponseFooterTests(unittest.TestCase):
    def test_coerce_files_footer_bool(self):
        self.assertIs(coerce_files_footer_bool("true"), True)
        self.assertIs(coerce_files_footer_bool("YES"), True)
        self.assertIs(coerce_files_footer_bool("0"), False)
        self.assertIs(coerce_files_footer_bool("", default=True), True)

    def test_build_files_changed_footer_from_patch_diff(self):
        tool_result = {
            "success": True,
            "diff": "--- a/tmp/a.txt\n+++ b/tmp/a.txt\n@@\n-old\n+new\n",
            "files_modified": ["/tmp/a.txt"],
        }
        messages = [
            {"role": "user", "content": "edit file"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "patch",
                            "arguments": json.dumps({"path": "/tmp/a.txt"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": json.dumps(tool_result),
            },
        ]

        footer = build_files_changed_footer(messages, history_offset=1)

        self.assertIn("## 📁 1 Files Changed +1 -1", footer)
        self.assertIn("- /tmp/a.txt +1 -1", footer)

    def test_build_files_changed_footer_write_file_fallback(self):
        messages = [
            {"role": "user", "content": "write file"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_2",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps({"path": "/tmp/b.txt", "content": "a\nb\n"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "content": json.dumps({"success": True, "bytes_written": 4}),
            },
        ]

        footer = build_files_changed_footer(messages, history_offset=1)

        self.assertIn("## 📁 1 Files Changed", footer)
        self.assertIn("- /tmp/b.txt +2", footer)


if __name__ == "__main__":
    unittest.main()
