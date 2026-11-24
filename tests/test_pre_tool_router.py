import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pre_tool_router


class TestPreToolRouter(unittest.TestCase):
    def setUp(self):
        # Clear router bypass env var if present
        if "AGY_ROUTER_BYPASS" in os.environ:
            del os.environ["AGY_ROUTER_BYPASS"]

    def test_bypass_env_var(self):
        os.environ["AGY_ROUTER_BYPASS"] = "1"
        self.assertTrue(pre_tool_router.should_fast_path_bypass("write_to_file", {"Path": "test.py"}))

    def test_bypass_readonly_git_status(self):
        self.assertTrue(
            pre_tool_router.should_fast_path_bypass("run_command", {"CommandLine": "git status"})
        )

    def test_bypass_readonly_git_diff(self):
        self.assertTrue(
            pre_tool_router.should_fast_path_bypass("run_command", {"CommandLine": "git diff HEAD~1"})
        )

    def test_bypass_readonly_git_log(self):
        self.assertTrue(
            pre_tool_router.should_fast_path_bypass("run_command", {"CommandLine": "git log --oneline -n 5"})
        )

    def test_bypass_agy_plugin_validate(self):
        self.assertTrue(
            pre_tool_router.should_fast_path_bypass("run_command", {"CommandLine": "agy plugin validate --strict ."})
        )

    def test_bypass_subagent_targeting_glm_worker(self):
        self.assertTrue(
            pre_tool_router.should_fast_path_bypass("invoke_subagent", {"TypeName": "glm-worker"})
        )
        self.assertTrue(
            pre_tool_router.should_fast_path_bypass("invoke_subagent", {"agent": "glm-worker"})
        )

    def test_no_bypass_for_write_file(self):
        self.assertFalse(
            pre_tool_router.should_fast_path_bypass("write_to_file", {"Path": "app/main.py", "Content": "code"})
        )

    def test_no_bypass_for_destructive_command(self):
        self.assertFalse(
            pre_tool_router.should_fast_path_bypass("run_command", {"CommandLine": "npm test"})
        )

    @patch("pre_tool_router.urllib.request.urlopen")
    def test_offload_glm_flash(self, mock_urlopen):
        # Mock d1:3b response returning glm-flash, high confidence, low risk
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "model": "d1:3b",
            "answers": {
                "destination": {
                    "choice": "glm-flash",
                    "confidence": 0.88,
                },
                "risk_level": {
                    "score": 0.5,
                },
            },
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "Path": "src/utils.py",
                    "Target": "def old():",
                    "Replacement": "def new():",
                },
            },
        }

        with patch("sys.stdin.read", return_value=json.dumps(payload)), \
             patch("sys.stdout.write") as mock_stdout:
            pre_tool_router.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("ROUTER_OFFLOAD", res.get("reason", ""))
            self.assertIn("glm-flash", res.get("reason", ""))

    @patch("pre_tool_router.urllib.request.urlopen")
    def test_offload_glm_heavy(self, mock_urlopen):
        # Mock d1:3b response returning glm-heavy, high confidence, low risk
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "model": "d1:3b",
            "answers": {
                "destination": {
                    "choice": "glm-heavy",
                    "confidence": 0.82,
                },
                "risk_level": {
                    "score": 1.2,
                },
            },
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "Path": "src/feature.py",
                    "Content": "class Feature: pass",
                },
            },
        }

        with patch("sys.stdin.read", return_value=json.dumps(payload)), \
             patch("sys.stdout.write") as mock_stdout:
            pre_tool_router.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("ROUTER_OFFLOAD", res.get("reason", ""))
            self.assertIn("glm-heavy", res.get("reason", ""))

    @patch("pre_tool_router.urllib.request.urlopen")
    def test_allow_gemini_native(self, mock_urlopen):
        # Mock d1:3b response returning gemini-native
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "model": "d1:3b",
            "answers": {
                "destination": {
                    "choice": "gemini-native",
                    "confidence": 0.95,
                },
                "risk_level": {
                    "score": 0.2,
                },
            },
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git commit -m 'feat: update'"},
            },
        }

        with patch("sys.stdin.read", return_value=json.dumps(payload)), \
             patch("sys.stdout.write") as mock_stdout:
            pre_tool_router.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "allow")

    @patch("pre_tool_router.urllib.request.urlopen")
    def test_allow_high_risk(self, mock_urlopen):
        # Mock d1:3b response returning high risk (> 1.5)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "model": "d1:3b",
            "answers": {
                "destination": {
                    "choice": "glm-heavy",
                    "confidence": 0.85,
                },
                "risk_level": {
                    "score": 2.5,
                },
            },
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm -rf /etc/secrets"},
            },
        }

        with patch("sys.stdin.read", return_value=json.dumps(payload)), \
             patch("sys.stdout.write") as mock_stdout:
            pre_tool_router.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "allow")

    @patch("pre_tool_router.urllib.request.urlopen")
    def test_allow_low_confidence(self, mock_urlopen):
        # Mock d1:3b response returning confidence < 0.70
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "model": "d1:3b",
            "answers": {
                "destination": {
                    "choice": "glm-flash",
                    "confidence": 0.55,
                },
                "risk_level": {
                    "score": 0.4,
                },
            },
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {"Path": "some_file.py"},
            },
        }

        with patch("sys.stdin.read", return_value=json.dumps(payload)), \
             patch("sys.stdout.write") as mock_stdout:
            pre_tool_router.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "allow")

    @patch("pre_tool_router.urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_fail_open_on_systemone_offline(self, mock_urlopen):
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {"Path": "new_file.py", "Content": "test"},
            },
        }

        with patch("sys.stdin.read", return_value=json.dumps(payload)), \
             patch("sys.stdout.write") as mock_stdout, \
             patch("sys.stderr.write") as mock_stderr:
            pre_tool_router.main()

            written = "".join(call.args[0] for call in mock_stdout.call_args_list)
            res = json.loads(written.strip())
            self.assertEqual(res.get("decision"), "allow")

            # Check warning on stderr
            err_output = "".join(call.args[0] for call in mock_stderr.call_args_list)
            self.assertIn("Decision model /v1/systemone unavailable", err_output)


if __name__ == "__main__":
    unittest.main()
