"""Exercise action glue in isolated temporary directories, without target code."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SHA = "0123456789abcdef0123456789abcdef01234567"
FAILURE = ("# Ordo — Review Path\n\nOrdo could not analyze this pull request.\n\n"
           "See the workflow logs for details.\n")


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.source = self.directory / "source"
        self.source.mkdir()
        (self.source / "go.mod").write_text("module example.com/test\n\ngo 1.25.0\n")
        self.output = self.directory / "output"
        self.summary = self.directory / "summary"
        self.output.touch()
        self.summary.touch()
        self.env = os.environ.copy()
        self.env.update({
            "ACTION_PATH": str(ROOT), "RUNNER_TEMP": str(self.directory),
            "SOURCE_ROOT": str(self.source), "ORDO_PATH_JSON": json.dumps("."),
            "GITHUB_OUTPUT": str(self.output), "GITHUB_STEP_SUMMARY": str(self.summary),
            "EVENT_NAME": "pull_request", "SERVER_URL": "https://github.com",
            "BASE_REPOSITORY": "base/project", "HEAD_REPOSITORY": "fork/project",
            "BASE_SHA": SHA, "HEAD_SHA": SHA, "PR_NUMBER": "123",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
        })

    def run_script(self, name, **overrides):
        env = dict(self.env, **overrides)
        executable = sys.executable if name.endswith(".py") else "bash"
        return subprocess.run([executable, str(SCRIPTS / name)], env=env,
                              capture_output=True, text=True, check=False)

    def outputs(self):
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def check_path(self, value):
        self.output.write_text("")
        return self.run_script("validate_path.py", ORDO_PATH_JSON=json.dumps(value))

    def test_event_accepts_only_pull_request_and_allocates_unique_state(self):
        first = self.run_script("validate_event.sh")
        self.assertEqual(first.returncode, 0, first.stderr)
        state1 = self.outputs()["state_dir"]
        second = self.run_script("validate_event.sh")
        self.assertEqual(second.returncode, 0, second.stderr)
        state2 = self.outputs()["state_dir"]
        self.assertNotEqual(state1, state2)
        self.assertTrue(Path(state1).is_dir())
        self.assertTrue(Path(state1).is_relative_to(self.directory))
        for event in ("", "push", "pull_request_target", "workflow_run", "merge_group"):
            result = self.run_script("validate_event.sh", EVENT_NAME=event)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires the pull_request event", result.stderr)

    def test_missing_or_invalid_pr_context_fails_before_checkout(self):
        cases = {"BASE_REPOSITORY": ["", "a/b/c"], "HEAD_REPOSITORY": ["", "a/b\n"],
                 "BASE_SHA": ["", "main", "a" * 39], "HEAD_SHA": ["", SHA + "x"],
                 "PR_NUMBER": ["", "0", "01", "true", "1\n"],
                 "SERVER_URL": ["", "https://host/x", "https://user@host"]}
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    result = self.run_script("validate_event.sh", **{field: value})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(field, result.stderr)

    def test_root_module_prefix_is_empty(self):
        result = self.check_path(".")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.outputs(), {"module_root": str(self.source), "source_prefix": ""})

    def test_nested_spaces_unicode_alias_and_workspace(self):
        module = self.source / "services" / "платежи ü"
        module.mkdir(parents=True)
        (module / "go.work").write_text("go 1.25.0\n")
        (self.source / "alias").symlink_to(module, target_is_directory=True)
        for value in ("services/платежи ü", "./services/платежи ü/", "alias"):
            result = self.check_path(value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.outputs()["module_root"], str(module))
            self.assertEqual(self.outputs()["source_prefix"], "services/платежи ü")

    def test_absolute_parent_backslash_and_control_paths_are_rejected(self):
        for value in (str(self.source), "/tmp", "../source", "x/../.", "a\\b", "C:/x",
                      ".\n", ".\r", ".\x00", "a\tb", "a\x1bb", "a\u2028b", "", None):
            with self.subTest(value=value):
                result = self.check_path(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.output.read_text(), "")
                self.assertIn("invalid path", result.stderr)

    def test_missing_path_file_and_missing_module_metadata_fail(self):
        (self.source / "plain").mkdir()
        (self.source / "ordinary-file").touch()
        for value in ("missing", "plain", "ordinary-file"):
            result = self.check_path(value)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid path", result.stderr)
        self.assertIn("go.mod or go.work", self.check_path("plain").stderr)

    def test_symlink_escape_and_canonical_control_path_fail(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "go.mod").touch()
        (self.source / "escape").symlink_to(outside, target_is_directory=True)
        result = self.check_path("escape")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink escape", result.stderr)
        bad = self.source / "bad\nname"
        bad.mkdir()
        (bad / "go.mod").touch()
        (self.source / "looks-safe").symlink_to(bad, target_is_directory=True)
        self.assertNotEqual(self.check_path("looks-safe").returncode, 0)

    def test_input_is_not_evaluated_as_shell_source(self):
        value = "$(touch INJECTION);`touch INJECTION2`"
        module = self.source / value
        module.mkdir()
        (module / "go.mod").touch()
        result = self.check_path(value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.outputs()["source_prefix"], value)
        for marker in ("INJECTION", "INJECTION2"):
            self.assertFalse((ROOT / marker).exists())
            self.assertFalse((self.source / marker).exists())

    def git(self, directory, *args, data=None):
        result = subprocess.run(["git", "-C", str(directory), *args], env=self.env,
                                input=data, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def make_history(self, directory, branch, common="common"):
        directory.mkdir(exist_ok=True)
        self.git(directory, "init", "--quiet")
        # Deterministic synthetic objects in disposable repositories only.
        stream = (
            f"commit refs/heads/{branch}\nmark :1\n"
            "committer Fixture <fixture@example.invalid> 1000000000 +0000\n"
            f"data {len(common)}\n{common}\n"
            f"commit refs/heads/{branch}\n"
            "committer Fixture <fixture@example.invalid> 1000000001 +0000\n"
            f"data {len(branch)}\n{branch}\nfrom :1\n\ndone\n"
        )
        self.git(directory, "fast-import", "--quiet", data=stream)
        sha = self.git(directory, "rev-parse", f"refs/heads/{branch}")
        self.git(directory, "checkout", "--detach", sha)
        return sha

    def test_base_history_import_is_local_exact_and_has_merge_base(self):
        head = self.make_history(self.source, "head")
        base_root = self.directory / "base"
        base = self.make_history(base_root, "base")
        result = self.run_script("prepare.sh", HEAD_SHA=head, BASE_SHA=base, BASE_ROOT=str(base_root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.source, "rev-parse", "refs/remotes/ordo/base"), base)
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), head)
        self.assertTrue(self.git(self.source, "merge-base", "HEAD", "refs/remotes/ordo/base"))
        self.assertEqual(self.git(self.source, "remote"), "")
        self.assertEqual(self.outputs()["source_prefix"], "")
        # Moving a branch name cannot move the imported analysis identity.
        self.git(base_root, "update-ref", "refs/heads/base", "HEAD^")
        result = self.run_script("prepare.sh", HEAD_SHA=head, BASE_SHA=base, BASE_ROOT=str(base_root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.source, "rev-parse", "refs/remotes/ordo/base"), base)

    def test_mismatching_checkout_and_unrelated_histories_fail(self):
        head = self.make_history(self.source, "head")
        base_root = self.directory / "base"
        base = self.make_history(base_root, "base", common="unrelated")
        mismatch = self.run_script("prepare.sh", HEAD_SHA=SHA, BASE_SHA=base, BASE_ROOT=str(base_root))
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("do not match", mismatch.stderr)
        unrelated = self.run_script("prepare.sh", HEAD_SHA=head, BASE_SHA=base, BASE_ROOT=str(base_root))
        self.assertNotEqual(unrelated.returncode, 0)
        self.assertIn("no merge base", unrelated.stderr)

    def fake_ordo(self):
        binary = self.directory / "ordo-stub"
        binary.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['TRACE']).write_text(json.dumps({'argv':sys.argv[1:], 'cwd':os.getcwd()}))\n"
            "print('analysis diagnostic', file=sys.stderr)\n"
            "sys.stdout.write(os.environ.get('REPORT', '{\"steps\":[]}'))\n"
            "sys.exit(int(os.environ.get('STATUS', '0')))\n"
        )
        binary.chmod(0o755)
        self.env.update(ORDO_BIN=str(binary), STATE_DIR=str(self.directory),
                        MODULE_ROOT=str(self.source), TRACE=str(self.directory / "trace"))

    def test_analysis_exact_arguments_working_directory_unique_report_and_stderr(self):
        self.fake_ordo()
        result = self.run_script("analyze.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("analysis diagnostic", result.stderr)
        trace = json.loads((self.directory / "trace").read_text())
        self.assertEqual(trace["argv"], ["--diff", "--diff-base", "refs/remotes/ordo/base", "--format", "json", "./..."])
        self.assertEqual(trace["cwd"], str(self.source))
        first = self.outputs()["report_path"]
        self.assertTrue(Path(first).is_relative_to(self.directory))
        self.assertFalse(Path(first).is_relative_to(self.source))
        self.assertEqual(Path(first).read_text(), '{"steps":[]}')
        self.assertEqual(self.run_script("analyze.sh").returncode, 0)
        self.assertNotEqual(first, self.outputs()["report_path"])

    def test_analysis_exit_status_is_preserved_and_empty_report_fails(self):
        self.fake_ordo()
        failed = self.run_script("analyze.sh", STATUS="37")
        self.assertEqual(failed.returncode, 37)
        self.assertEqual(self.output.read_text(), "")
        empty = self.run_script("analyze.sh", REPORT="")
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("non-empty regular JSON report", empty.stderr)
        self.assertEqual(self.output.read_text(), "")

    def test_success_publishes_complete_summary_and_suppresses_failure(self):
        result = self.run_script("publish_summary.sh", STATE_DIR=str(self.directory),
                                 REPORT_PATH=str(ROOT / "tests/fixtures/linear.json"), SOURCE_PREFIX="nested ü")
        self.assertEqual(result.returncode, 0, result.stderr)
        original = self.summary.read_text()
        self.assertTrue(original.endswith("</details>\n"))
        self.assertTrue((self.directory / "summary-published").is_file())
        self.assertEqual(self.run_script("failure_summary.sh", STATE_DIR=str(self.directory)).returncode, 0)
        self.assertEqual(self.summary.read_text(), original)

    def test_bad_report_never_publishes_partial_summary_and_failure_is_idempotent(self):
        self.summary.write_text("Previous summary\n")
        failed = self.run_script("publish_summary.sh", STATE_DIR=str(self.directory),
                                 REPORT_PATH=str(ROOT / "tests/fixtures/malformed.json"), SOURCE_PREFIX="")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.summary.read_text(), "Previous summary\n")
        self.assertFalse((self.directory / "summary-published").exists())
        for _ in range(2):
            self.assertEqual(self.run_script("failure_summary.sh", STATE_DIR=str(self.directory)).returncode, 0)
        self.assertEqual(self.summary.read_text(), "Previous summary\n" + FAILURE)

    def test_failure_before_state_allocation_still_has_friendly_summary(self):
        self.assertEqual(self.run_script("failure_summary.sh", STATE_DIR="").returncode, 0)
        self.assertEqual(self.summary.read_text(), FAILURE)

    def test_empty_report_publishes_success_marker(self):
        result = self.run_script("publish_summary.sh", STATE_DIR=str(self.directory),
                                 REPORT_PATH=str(ROOT / "tests/fixtures/empty.json"), SOURCE_PREFIX="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No changed Go functions", self.summary.read_text())
        self.assertTrue((self.directory / "summary-published").is_file())


if __name__ == "__main__":
    unittest.main()
