import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = ROOT / "scripts" / "render_summary.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SPEC = importlib.util.spec_from_file_location("render_summary", RENDERER_PATH)
assert SPEC is not None and SPEC.loader is not None
render_summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_summary)


class RenderSummaryTests(unittest.TestCase):
    SHA = "0123456789abcdef0123456789abcdef01234567"

    def fixture(self, name):
        return render_summary.load_report(FIXTURES / name)

    def single_location_report(self, file_name, line):
        return {
            "steps": [
                {
                    "order": 1,
                    "cycle": False,
                    "functions": [
                        {
                            "id": "example.com/project/pkg.F",
                            "file": file_name,
                            "line": line,
                        }
                    ],
                }
            ]
        }

    def test_linear_graph_renders_counts_names_order_and_source_links(self):
        markdown = render_summary.render_summary(
            self.fixture("linear.json"), "example/project", self.SHA
        )

        self.assertIn("**Changed functions:** 4  \n**Review steps:** 4", markdown)
        self.assertLess(markdown.index("## 1"), markdown.index("## 4"))
        self.assertIn("`User.Validate()`", markdown)
        self.assertIn("`StoreUser()`", markdown)
        self.assertIn(
            "https://github.com/example/project/blob/"
            f"{self.SHA}/internal/model/user.go#L42",
            markdown,
        )
        self.assertNotIn("/pull/", markdown)
        self.assertNotIn("([source]", markdown)
        self.assertIn(
            "`github.com/example/project/internal/model.User.Validate`", markdown
        )

    def test_pull_request_diff_link_hashes_full_repository_path_and_keeps_source(self):
        markdown = render_summary.render_summary(
            self.single_location_report("accounts/account_snapshot.go", 5),
            "Spot2025/Go-practice",
            self.SHA,
            "awesomeProject",
            3,
        )
        path_hash = (
            "7adff936d843c2903e7e6d19453ea77f51f15af0c66f3794877602021c0ecc35"
        )

        self.assertIn(
            "[`awesomeProject/accounts/account_snapshot.go:5`]"
            "(https://github.com/Spot2025/Go-practice/pull/3/files"
            f"#diff-{path_hash}R5) "
            "([source](https://github.com/Spot2025/Go-practice/blob/"
            f"{self.SHA}/awesomeProject/accounts/account_snapshot.go#L5))",
            markdown,
        )
        self.assertNotIn("/pull/3/changes", markdown)

    def test_invalid_pull_request_numbers_fall_back_to_blob_link(self):
        report = self.single_location_report("pkg/file.go", 12)
        invalid_numbers = (
            0,
            -1,
            True,
            "",
            "0",
            "-3",
            "03",
            "3.0",
            " 3",
            "3/evil",
        )

        for pull_request in invalid_numbers:
            with self.subTest(pull_request=pull_request):
                markdown = render_summary.render_summary(
                    report,
                    "example/project",
                    self.SHA,
                    None,
                    pull_request,
                )
                self.assertIn(
                    f"https://github.com/example/project/blob/{self.SHA}/pkg/file.go#L12",
                    markdown,
                )
                self.assertNotIn("/pull/", markdown)
                self.assertNotIn("([source]", markdown)

    def test_zero_line_uses_blob_without_diff_anchor(self):
        markdown = render_summary.render_summary(
            self.single_location_report("pkg/file.go", 0),
            "example/project",
            self.SHA,
            None,
            8,
        )

        self.assertIn(
            f"https://github.com/example/project/blob/{self.SHA}/pkg/file.go",
            markdown,
        )
        self.assertNotIn("/pull/8/files", markdown)
        self.assertNotIn("R0", markdown)

    def test_unicode_and_spaces_use_raw_utf8_hash_and_encoded_blob_path(self):
        markdown = render_summary.render_summary(
            self.single_location_report("pkg/résumé file.go", 7),
            "example/project",
            self.SHA,
            "awesome Project",
            "11",
        )
        path_hash = (
            "31fabcefefb5c16a358c2c8dd5c540a20a850a1e8b10e1e5d9f9861453c655f5"
        )

        self.assertIn(
            "https://github.com/example/project/pull/11/files"
            f"#diff-{path_hash}R7",
            markdown,
        )
        self.assertIn(
            "https://github.com/example/project/blob/"
            f"{self.SHA}/awesome%20Project/pkg/r%C3%A9sum%C3%A9%20file.go#L7",
            markdown,
        )
        self.assertIn("`awesome Project/pkg/résumé file.go:7`", markdown)

    def test_branching_graph_keeps_dependency_first_step_sequence(self):
        markdown = render_summary.render_summary(self.fixture("branching.json"))

        names = ["LoadUser()", "CheckAccess()", "RecordAccess()", "HandleUser()"]
        positions = [markdown.index(name) for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("**Changed functions:** 4", markdown)
        self.assertIn("**Review steps:** 4", markdown)

    def test_multiple_functions_in_scc_are_rendered_as_a_cycle_group(self):
        markdown = render_summary.render_summary(self.fixture("cycle.json"))

        self.assertIn("## 1 · Cycle · 2 functions", markdown)
        self.assertIn("dependency cycle; review them together", markdown)
        self.assertIn("- `Even()` — `internal/parity/parity.go:9`", markdown)
        self.assertIn("- `Odd()` — `internal/parity/parity.go:16`", markdown)
        self.assertIn("**Changed functions:** 2", markdown)
        self.assertIn("**Review steps:** 1", markdown)

    def test_artifact_scc_keeps_members_and_shows_warning(self):
        markdown = render_summary.render_summary(self.fixture("artifact.json"))

        self.assertIn(
            "> ⚠️ Ordo classified this cycle as a probable call-graph artifact.",
            markdown,
        )
        for name in ("A.Run()", "B.Run()", "C.Run()"):
            self.assertIn(name, markdown)

    def test_empty_result_is_successful_and_concise(self):
        markdown = render_summary.render_summary(self.fixture("empty.json"))

        self.assertEqual(
            markdown,
            "# Ordo — Review Path\n\n"
            "No changed Go functions were detected in this pull request.\n",
        )

    def test_malformed_json_returns_nonzero_with_a_readable_error(self):
        result = subprocess.run(
            [sys.executable, str(RENDERER_PATH), str(FIXTURES / "malformed.json")],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid JSON", result.stderr)
        self.assertIn("line", result.stderr)

    def test_missing_optional_artifact_is_treated_as_false(self):
        report = self.fixture("linear.json")
        self.assertTrue(all("artifact" not in step for step in report["steps"]))

        markdown = render_summary.render_summary(report)
        self.assertNotIn("probable call-graph artifact", markdown)

    def test_display_name_handles_real_ssa_methods_and_anonymous_functions(self):
        cases = {
            "(*github.com/example/project/internal/service.Service).CreateUser": (
                "(*Service).CreateUser()"
            ),
            "(github.com/example/project/internal/model.User).Validate": (
                "User.Validate()"
            ),
            "github.com/example/project/internal/service.(*Service).CreateUser": (
                "(*Service).CreateUser()"
            ),
            "github.com/example/project/internal/service.buildRequest$1": (
                "buildRequest$1()"
            ),
        }
        for function_id, expected in cases.items():
            with self.subTest(function_id=function_id):
                self.assertEqual(render_summary.display_name(function_id), expected)

    def test_unknown_source_and_missing_link_context_fall_back_to_text(self):
        unknown_report = {
            "steps": [
                {
                    "order": 1,
                    "cycle": False,
                    "functions": [{"id": "example.com/project/pkg.F", "file": "", "line": 0}],
                }
            ]
        }
        self.assertIn(
            "## 1 · Source unavailable",
            render_summary.render_summary(unknown_report, "example/project", self.SHA),
        )

        markdown = render_summary.render_summary(self.fixture("linear.json"))
        self.assertIn("## 1 · `internal/model/user.go:42`", markdown)
        self.assertNotIn("https://github.com/", markdown)

        traversal_report = {
            "steps": [
                {
                    "order": 1,
                    "cycle": False,
                    "functions": [
                        {
                            "id": "example.com/project/pkg.F",
                            "file": "internal/../secret.go",
                            "line": 1,
                        }
                    ],
                }
            ]
        }
        traversal_markdown = render_summary.render_summary(
            traversal_report, "example/project", self.SHA, None, 3
        )
        self.assertIn("`internal/../secret.go:1`", traversal_markdown)
        self.assertNotIn("https://github.com/", traversal_markdown)

    def test_cli_uses_github_environment_for_source_links(self):
        env = os.environ.copy()
        env.pop("PULL_REQUEST_NUMBER", None)
        env.update({"GITHUB_REPOSITORY": "example/project", "HEAD_SHA": self.SHA, "HEAD_REPOSITORY": "example/project"})
        result = subprocess.run(
            [sys.executable, str(RENDERER_PATH), str(FIXTURES / "linear.json")],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"https://github.com/example/project/blob/{self.SHA}/", result.stdout
        )
        self.assertEqual(result.stderr, "")

    def test_cli_uses_pull_request_number_environment_default(self):
        env = os.environ.copy()
        env.update(
            {
                "GITHUB_REPOSITORY": "example/project",
                "HEAD_SHA": self.SHA, "HEAD_REPOSITORY": "example/project",
                "PULL_REQUEST_NUMBER": "17",
            }
        )
        result = subprocess.run(
            [sys.executable, str(RENDERER_PATH), str(FIXTURES / "linear.json")],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "https://github.com/example/project/pull/17/files#diff-",
            result.stdout,
        )
        self.assertIn(
            f"([source](https://github.com/example/project/blob/{self.SHA}/",
            result.stdout,
        )
        self.assertEqual(result.stderr, "")

    def test_nested_module_prefix_keeps_locations_repository_relative(self):
        markdown = render_summary.render_summary(
            self.fixture("linear.json"),
            "example/project",
            self.SHA,
            "./awesomeProject/",
        )

        self.assertIn(
            "`awesomeProject/internal/model/user.go:42`", markdown
        )
        self.assertIn(
            "https://github.com/example/project/blob/"
            f"{self.SHA}/awesomeProject/internal/model/user.go#L42",
            markdown,
        )

        root_markdown = render_summary.render_summary(
            self.fixture("linear.json"), "example/project", self.SHA, "."
        )
        self.assertIn("`internal/model/user.go:42`", root_markdown)
        self.assertNotIn("/./internal/model/user.go", root_markdown)

        unsafe_markdown = render_summary.render_summary(
            self.fixture("linear.json"),
            "example/project",
            self.SHA,
            "../outside",
            3,
        )
        self.assertIn("`internal/model/user.go:42`", unsafe_markdown)
        self.assertNotIn("https://github.com/", unsafe_markdown)


if __name__ == "__main__":
    unittest.main()
