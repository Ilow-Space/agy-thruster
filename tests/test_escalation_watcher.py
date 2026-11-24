import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import escalation_watcher


class TestEscalationWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.state_dir = Path(self.temp_dir) / "state" / "pi-delegate-mcp"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(self.temp_dir) / "cache" / "agy-d1-glm-router"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.cwd = str(Path(self.temp_dir) / "workspace")
        Path(self.cwd).mkdir(parents=True, exist_ok=True)

        # Patch paths in common / escalation_watcher
        self.state_patcher = patch("common.get_state_dir", return_value=self.state_dir)
        self.cache_patcher = patch("common.get_cache_dir", return_value=self.cache_dir)
        self.state_patcher.start()
        self.cache_patcher.start()

    def tearDown(self):
        self.state_patcher.stop()
        self.cache_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_delegate_state(self, delegate_id, status, question="Need clarification", updated_at="12345"):
        state_file = self.state_dir / f"{delegate_id}.json"
        data = {
            "delegate_id": delegate_id,
            "status": status,
            "cwd": self.cwd,
            "question": question,
            "updated_at": updated_at,
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return state_file

    def test_pre_invocation_surfaces_needs_input(self):
        self._create_delegate_state("del-101", "needs_input", question="Which auth provider to use?")

        input_payload = {
            "hookEventName": "PreInvocation",
            "cwd": self.cwd,
            "invocationNum": 1,
        }

        with patch("sys.stdin.read", return_value=json.dumps(input_payload)), \
             patch("sys.stdout.write") as mock_stdout:
            escalation_watcher.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())

            self.assertIn("injectSteps", res)
            self.assertEqual(len(res["injectSteps"]), 1)
            msg = res["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("del-101", msg)
            self.assertIn("needs_input", msg)
            self.assertIn("Which auth provider to use?", msg)

    def test_deduplication_does_not_resurface_seen_events(self):
        self._create_delegate_state("del-102", "needs_input", question="Missing database URL")

        input_payload = {
            "hookEventName": "PreInvocation",
            "cwd": self.cwd,
            "invocationNum": 1,
        }

        # First run: should surface
        with patch("sys.stdin.read", return_value=json.dumps(input_payload)), \
             patch("sys.stdout.write") as mock_stdout_1:
            escalation_watcher.main()
            written_1 = "".join(call.args[0] for call in mock_stdout_1.call_args_list)
            res_1 = json.loads(written_1.strip())
            self.assertEqual(len(res_1.get("injectSteps", [])), 1)

        # Second run: should be suppressed
        with patch("sys.stdin.read", return_value=json.dumps(input_payload)), \
             patch("sys.stdout.write") as mock_stdout_2:
            escalation_watcher.main()
            written_2 = "".join(call.args[0] for call in mock_stdout_2.call_args_list)
            res_2 = json.loads(written_2.strip())
            self.assertEqual(len(res_2.get("injectSteps", [])), 0)

    def test_stop_hook_forces_continuation_on_needs_input(self):
        self._create_delegate_state("del-103", "needs_input", question="API key invalid")

        input_payload = {
            "hookEventName": "Stop",
            "cwd": self.cwd,
            "terminationReason": "NO_TOOL_CALL",
        }

        with patch("sys.stdin.read", return_value=json.dumps(input_payload)), \
             patch("sys.stdout.write") as mock_stdout:
            escalation_watcher.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "continue")
            self.assertIn("del-103", res.get("reason", ""))
            self.assertIn("API key invalid", res.get("reason", ""))

    def test_stop_hook_allows_when_no_escalation(self):
        input_payload = {
            "hookEventName": "Stop",
            "cwd": self.cwd,
            "terminationReason": "NO_TOOL_CALL",
        }

        with patch("sys.stdin.read", return_value=json.dumps(input_payload)), \
             patch("sys.stdout.write") as mock_stdout:
            escalation_watcher.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "allow")

    def test_stop_hook_respects_continuation_active(self):
        # When continuationActive is true, prevent continuation loops
        self._create_delegate_state("del-104", "needs_input", question="Loop test")

        input_payload = {
            "hookEventName": "Stop",
            "cwd": self.cwd,
            "terminationReason": "NO_TOOL_CALL",
            "continuationActive": True,
        }

        with patch("sys.stdin.read", return_value=json.dumps(input_payload)), \
             patch("sys.stdout.write") as mock_stdout:
            escalation_watcher.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "allow")


if __name__ == "__main__":
    unittest.main()
