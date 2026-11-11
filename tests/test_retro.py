"""Synthetic regressions only. Never opens actual session history."""
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "self-improve/scripts/retro.py"
spec = importlib.util.spec_from_file_location("retro", SCRIPT)
retro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retro)


def rows(path, data):
    path.write_text("".join(json.dumps(x) + "\n" for x in data))


class RetroTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="self-improve-synthetic-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.claude = self.root / "claude.jsonl"
        self.codex = self.root / "rollout-synthetic.jsonl"
        rows(self.claude, [
            {"type": "user", "message": {"content": "Please review the demo skill."}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "id": "r1", "input": {"file_path": "/synthetic/demo/SKILL.md"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "r1", "content": "Rule: confirm before push."}]}},
            {"type": "user", "message": {"content": "No, add this to the skill: never push without approval."}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "b1", "input": {"command": "git push origin main"}}]}},
            {"type": "attachment", "attachment": {"type": "hook_permission_decision", "hookName": "PreToolUse", "decision": "deny", "toolUseID": "b1", "content": "Approval required"}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "b1", "is_error": True, "content": "Blocked by hook. No push occurred."}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "id": "e1", "input": {"file_path": "/synthetic/demo/SKILL.md", "new_string": "Confirm before push."}}]}},
        ])
        rows(self.codex, [
            {"type": "session_meta", "payload": {"id": "synthetic"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Never skip the approval check."}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1", "arguments": json.dumps({"cmd": "cat /synthetic/demo/SKILL.md"})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "Synthetic rule text"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I will propose a diff and stop."}]}},
        ])

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], text=True, capture_output=True, cwd=ROOT)

    def test_both_parsers_preserve_evidence(self):
        ce = list(retro.events_claude(str(self.claude)))
        xe = list(retro.events_codex(str(self.codex)))
        self.assertTrue(any(e["kind"] == "hook" and e["outcome"] == "deny" for e in ce))
        self.assertTrue(any(e["kind"] == "tool" and retro.skill_hits(e)[0][0] == "demo" for e in xe if retro.skill_hits(e)))
        self.assertTrue(any(e["kind"] == "result" and e["id"] == "c1" for e in xe))
        self.assertEqual(ce[0]["line"], 1)

    def test_all_six_commands_and_no_input_mutation(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.claude, self.codex)}
        expectations = {"triggers": "demo", "signals": "SKILL-CHANGE REQUEST", "hooks": "deny", "tokens": "Output volume by tool", "context": "No, add this to the skill"}
        for cmd, expected in expectations.items():
            with self.subTest(cmd=cmd):
                out = self.root / (cmd + ".md")
                result = self.cli(cmd, self.claude, self.codex, "--out", out, "--results")
                self.assertEqual(result.returncode, 0, result.stderr)
                text = out.read_text()
                self.assertIn(expected, text)
                self.assertIn(".jsonl:", text)
        result = self.cli("lint", ROOT / "self-improve")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Static lint", result.stdout)
        self.assertNotIn("FAIL", result.stdout)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_signal_and_trigger_attribution(self):
        result = self.cli("signals", self.claude, "--skill", "demo")
        self.assertIn("active skill: demo", result.stdout)
        self.assertIn("edited demo/SKILL.md at line 8", result.stdout)
        result = self.cli("triggers", self.claude, "--skill", "demo")
        self.assertIn("claude.jsonl:2", result.stdout)
        self.assertIn("No, add this to the skill", result.stdout)

    def test_redaction_common_credentials(self):
        marker = "SYNTHETIC_CREDENTIAL_ABCxyz123456789"
        cases = [
            json.dumps({"api_key": marker}), json.dumps({"password": marker}),
            "api_key = \"" + marker + "\"", "API_KEY=" + marker,
            "Authorization: Basic " + marker, "Authorization: Bearer " + marker,
            "Cookie: session=" + marker + "; theme=light", "Set-Cookie: session=" + marker + "; HttpOnly",
            "-----BEGIN PRIVATE KEY-----\n" + marker + "\n-----END PRIVATE KEY-----",
            "https://example.invalid/?token=" + marker,
            "sk-" + "a" * 48, "ghp_" + "b" * 36, "xoxb-" + "c" * 24,
            "AKIA" + "A" * 16, "synthetic@example.invalid",
        ]
        for value in cases:
            with self.subTest(form=value.split(":")[0][:20]):
                output = retro.redact(value)
                self.assertNotIn(marker, output)
                if marker not in value:
                    self.assertNotEqual(value, output)

    def test_redact_before_clip_and_serialization_truncation(self):
        value = "sk-" + "a" * 80
        self.assertNotIn("sk-aaaa", retro.clip(value, 16))
        text = retro.tool_input_str("unknown", {"padding": "z" * 460, "api_key": "b" * 80})
        self.assertNotIn('"api_key": "bbbb', text)

    def test_output_cannot_overwrite_transcript(self):
        before = self.claude.read_bytes()
        result = self.cli("signals", self.claude, "--out", self.claude)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.claude.read_bytes())

    def test_filtered_inputs_and_aliases_cannot_be_overwritten(self):
        before = self.claude.read_bytes()
        old = time.time() - 30 * 86400
        os.utime(self.claude, (old, old))
        symlink = self.root / "linked.md"
        symlink.symlink_to(self.claude)
        hardlink = self.root / "hardlinked.md"
        os.link(self.claude, hardlink)
        for output in (self.claude, symlink, hardlink):
            with self.subTest(output=output.name):
                result = self.cli("signals", self.claude, "--since", 1, "--out", output)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.claude.read_bytes())
        result = self.cli("signals", self.root, "--since", 1, "--out", self.claude)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.claude.read_bytes())

    def test_hook_prefixes_redact_complete_secret_before_shortening(self):
        marker = "SYNTHETIC_LONG_PRIVATE_" + "x" * 350
        rows(self.claude, [
            {"type": "attachment", "attachment": {"type": "hook_success", "hookName": "PreToolUse", "command": 'run ' + json.dumps({"api_key": marker}), "exitCode": 1}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "is_error": True, "content": "Blocked by hook " + json.dumps({"api_key": marker})}]}},
        ])
        result = self.cli("hooks", self.claude)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SYNTHETIC_LONG_PRIVATE", result.stdout)
        self.assertIn("[REDACTED]", result.stdout)

    def test_non_object_json_rows_are_skipped(self):
        for path in (self.claude, self.codex):
            with path.open("a") as stream:
                for value in (None, [], "synthetic", 42):
                    stream.write(json.dumps(value) + "\n")
            result = self.cli("context", path, "--results")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(".jsonl:", result.stdout)

    def test_output_paths_are_redacted_in_status_and_errors(self):
        marker = "SYNTHETIC_PATH_PRIVATE123456789"
        target = self.root / ("API_KEY=" + marker)
        result = self.cli("signals", self.claude, "--out", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(marker, result.stderr)
        result = self.cli("signals", self.claude, "--out", target / "missing.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_output_redacts_fixture_credentials(self):
        marker = "SYNTHETIC_PRIVATE_ABCxyz123456789"
        with self.claude.open("a") as out:
            out.write(json.dumps({"type": "user", "message": {"content": "Never store " + json.dumps({"api_key": marker})}}) + "\n")
        for cmd in ("triggers", "signals", "hooks", "tokens", "context"):
            result = self.cli(cmd, self.claude, "--results", "--window", 100)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
