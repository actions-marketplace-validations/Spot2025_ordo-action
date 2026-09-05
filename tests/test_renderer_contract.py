"""Public extraction coverage in addition to the 16 original dogfood tests."""

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_render_summary import FIXTURES, RENDERER_PATH, render_summary as renderer


SHA = "0123456789abcdef0123456789abcdef01234567"
MISSING = object()


def report(file="pkg/file.go", line=42, function_id="example.com/pkg.F"):
    return {"steps": [{"order": 1, "cycle": False, "functions": [
        {"id": function_id, "file": file, "line": line}
    ]}]}


def render(value, **kwargs):
    context = dict(base_repository="base/project", head_repository="fork/project",
                   sha=SHA, pull_request=123, server_url="https://github.com")
    context.update(kwargs)
    return renderer.render_summary(value, **context)


class ContractTests(unittest.TestCase):
    def rejects(self, value):
        with self.assertRaises(renderer.ReportError):
            renderer.render_summary(value)

    def variants(self, target, field, values):
        for value in values:
            with self.subTest(field=field, value=value):
                sample = report()
                item = {"root": sample, "step": sample["steps"][0],
                        "function": sample["steps"][0]["functions"][0]}[target]
                if value is MISSING:
                    del item[field]
                else:
                    item[field] = value
                self.rejects(sample)

    def test_root_must_be_object_with_required_array(self):
        for value in (None, True, [], "text", 1, {}, {"steps": None}, {"steps": {}},
                      {"steps": "bad"}, {"steps": True}):
            with self.subTest(value=value):
                self.rejects(value)

    def test_steps_must_be_objects(self):
        for value in (None, True, [], "bad", 4):
            self.rejects({"steps": [value]})

    def test_order_is_required_positive_integer_not_bool(self):
        self.variants("step", "order", [MISSING, None, "1", 1.5, True, False, 0, -1])

    def test_cycle_is_required_boolean(self):
        self.variants("step", "cycle", [MISSING, None, 0, 1, "false", []])

    def test_functions_is_required_nonempty_array(self):
        self.variants("step", "functions", [MISSING, None, [], {}, True, "bad"])

    def test_noncycle_cannot_contain_multiple_functions(self):
        value = report()
        value["steps"][0]["functions"] *= 2
        self.rejects(value)

    def test_artifact_requires_cycle_and_boolean_type(self):
        for artifact in (True, "true", 1, 0, None, []):
            value = report()
            value["steps"][0]["artifact"] = artifact
            self.rejects(value)
        for artifact in (True, False):
            value = report()
            value["steps"][0].update(cycle=True, artifact=artifact)
            self.assertIn("Cycle · 1 functions", render(value))

    def test_function_must_be_object(self):
        for value in (None, False, [], 1, "bad"):
            self.variants("step", "functions", [[value]])

    def test_id_is_required_nonempty_string(self):
        self.variants("function", "id", [MISSING, "", None, 1, True, {}])

    def test_file_is_required_string_and_can_be_empty(self):
        self.variants("function", "file", [MISSING, None, 1, True, []])
        self.assertIn("Source unavailable", render(report(file="")))

    def test_line_is_required_nonnegative_integer_not_bool(self):
        self.variants("function", "line", [MISSING, None, "1", 1.1, True, False, -1])

    def test_unknown_fields_are_ignored(self):
        value = report()
        original = render(value)
        value["future"] = {"anything": True}
        value["steps"][0]["future"] = 1
        value["steps"][0]["functions"][0]["code"] = "untrusted <html>"
        self.assertEqual(original, render(value))

    def test_duplicate_noncontiguous_order_and_scc_members_are_preserved(self):
        value = report(function_id="pkg.Z")
        step = value["steps"][0]
        step.update(order=8, cycle=True)
        step["functions"].append({"id": "pkg.A", "file": "a.go", "line": 1})
        value["steps"] += [dict(report(function_id="pkg.Last")["steps"][0], order=2),
                           dict(report(function_id="pkg.Final")["steps"][0], order=2)]
        original = copy.deepcopy(value)
        markdown = render(value)
        self.assertEqual(value, original)
        self.assertLess(markdown.index("## 8"), markdown.index("## 2"))
        self.assertLess(markdown.index("Z()"), markdown.index("A()"))
        self.assertLess(markdown.index("Last()"), markdown.index("Final()"))
        self.assertEqual(markdown.count("## 2"), 2)


class LinkAndSafetyTests(unittest.TestCase):
    def test_full_golden_normal_report_is_unchanged_from_dogfood(self):
        value = renderer.load_report(FIXTURES / "linear.json")
        actual = render(value, base_repository="example/project", head_repository="example/project",
                        source_prefix="awesomeProject")
        self.assertEqual(actual, (FIXTURES / "linear.md").read_text(encoding="utf-8"))

    def test_invalid_repositories_fall_back_independently(self):
        for invalid in (True, 123, {}, "", "no-owner", "/project", "a/b/c", "a/b\n", "a b/c", "a/b?x", "a/b#x"):
            with self.subTest(repository=invalid):
                both = render(report(), base_repository=invalid, head_repository=invalid)
                self.assertNotIn("https://", both)
                self.assertIn("/blob/", render(report(), base_repository=invalid))
                self.assertIn("/pull/", render(report(), head_repository=invalid))

    def test_invalid_sha_uses_diff_only(self):
        for sha in (None, True, 123, {}, "", "abc", "g" * 40, "a" * 65, SHA + "#L99", SHA + "\n"):
            with self.subTest(sha=sha):
                markdown = render(report(), sha=sha)
                self.assertIn("/pull/123/files#diff-", markdown)
                self.assertNotIn("/blob/", markdown)
                self.assertNotIn("([source]", markdown)

    def test_invalid_pr_numbers_use_blob_only(self):
        for number in (None, True, False, 0, -2, "0", "01", " 1", "1 ", "1\n", "1x", 1.0):
            with self.subTest(number=number):
                markdown = render(report(), pull_request=number)
                self.assertNotIn("/pull/", markdown)
                self.assertIn(f"/blob/{SHA}/", markdown)
                self.assertNotIn("([source]", markdown)

    def test_unsafe_paths_are_text_even_with_nested_prefix(self):
        for path in ("/tmp/file.go", "../file.go", "p/../f.go", "p/./f.go", "p//f.go",
                     "p/f.go/", "\\f.go", "p\\f.go", "C:/f.go", "p/\x00f.go",
                     "p/\nf.go", "p/\rf.go", "p/\tf.go", "p/\x1bf.go", "p/\x7ff.go",
                     "p/\u202ef.go", "p/\u2028f.go", "p/\ud800f.go"):
            with self.subTest(path=path):
                for prefix in (None, "module"):
                    markdown = render(report(file=path), source_prefix=prefix)
                    self.assertNotIn("https://", markdown)

    def test_unsafe_prefixes_do_not_create_links(self):
        for prefix in ("/tmp", "../out", "a\\b", "a\x00b", "a\nb", "a//b", "a/./b", "C:/x", "a\u202eb"):
            self.assertNotIn("https://", render(report(), source_prefix=prefix))

    def test_server_url_is_derived_and_unsafe_urls_fall_back_to_text(self):
        markdown = render(report(), server_url="https://git.example.test:8443/")
        self.assertIn("https://git.example.test:8443/base/project/pull/", markdown)
        self.assertIn("https://git.example.test:8443/fork/project/blob/", markdown)
        self.assertNotIn("github.com", markdown)
        for server in ("javascript:alert(1)", "https://host/x", "https://user@host", "https://host#x",
                       "https://host\n", "https://host?x", "https://host/)[bad](x"):
            self.assertNotIn("](https://", render(report(), server_url=server))

    def test_fork_links_use_base_pr_and_exact_head_source(self):
        path = "module ü/pkg/résumé file.go"
        markdown = render(report(file="pkg/résumé file.go"), source_prefix="module ü")
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.assertIn(f"https://github.com/base/project/pull/123/files#diff-{digest}R42", markdown)
        self.assertIn(f"https://github.com/fork/project/blob/{SHA}/module%20%C3%BC/pkg/r%C3%A9sum%C3%A9%20file.go#L42", markdown)
        self.assertNotIn("fork/project/pull/", markdown)
        self.assertNotIn("base/project/blob/", markdown)

    def test_each_cycle_member_has_own_links(self):
        markdown = render(renderer.load_report(FIXTURES / "cycle.json"))
        self.assertEqual(markdown.count("/pull/123/files#diff-"), 2)
        self.assertEqual(markdown.count(f"/blob/{SHA}/"), 2)
        self.assertIn("R9)", markdown)
        self.assertIn("R16)", markdown)

    def test_zero_line_uses_blob_without_line_anchor(self):
        markdown = render(report(line=0))
        self.assertIn(f"/blob/{SHA}/pkg/file.go)", markdown)
        self.assertNotIn("#L", markdown)
        self.assertNotIn("#diff-", markdown)

    def test_markdown_heavy_ids_keep_full_ids_and_adaptive_fences(self):
        raw = "`pkg.[x](https://evil)/<details>``Fn$1`"
        markdown = render(report(function_id=raw))
        self.assertIn(f"- Step 1 — ``` {raw} ```", markdown)
        self.assertEqual(markdown.count("\n<details>\n"), 1)
        self.assertTrue(markdown.endswith("\n</details>\n"))
        for value, expected in (("`x", "`` `x ``"), ("x`", "`` x` ``"), ("a``b", "```a``b```")):
            self.assertEqual(renderer._inline_code(value), expected)

    def test_controls_are_neutralized_without_losing_unicode_or_anonymous_suffix(self):
        raw = "pkg.Обновить$2\r\n\t\x00\x1b\x7f\u202e\u2028\ud800"
        markdown = render(report(function_id=raw))
        self.assertIn("Обновить$2", markdown)
        self.assertIn("- Step 1 — `pkg.Обновить$2", markdown)
        for control in ("\r", "\t", "\x00", "\x1b", "\x7f", "\u202e", "\u2028", "\ud800"):
            self.assertNotIn(control, markdown)
        markdown.encode("utf-8")


class CliTests(unittest.TestCase):
    def run_cli(self, path, *args, env=None):
        context = os.environ.copy()
        for key in ("GITHUB_REPOSITORY", "GITHUB_SHA", "HEAD_SHA", "HEAD_REPOSITORY", "PULL_REQUEST_NUMBER", "GITHUB_SERVER_URL"):
            context.pop(key, None)
        context.update(env or {})
        return subprocess.run([sys.executable, str(RENDERER_PATH), str(path), *args],
                              capture_output=True, text=True, env=context, check=False)

    def test_unreadable_missing_and_directory_reports_fail_without_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (Path(directory), Path(directory) / "missing"):
                result = self.run_cli(path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("could not read", result.stderr)

    def test_malformed_contract_and_invalid_utf8_fail_without_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            for data in (b'{"steps":', b'{"steps":[{}]}', b'{"steps":[]}\xff'):
                path.write_bytes(data)
                result = self.run_cli(path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_empty_cli_is_success(self):
        result = self.run_cli(FIXTURES / "empty.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "# Ordo — Review Path\n\nNo changed Go functions were detected in this pull request.\n")

    def test_cli_never_uses_synthetic_github_sha(self):
        result = self.run_cli(FIXTURES / "linear.json", env={
            "GITHUB_SHA": SHA, "GITHUB_REPOSITORY": "base/project", "HEAD_REPOSITORY": "fork/project"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("/blob/", result.stdout)

    def test_cli_explicit_fork_context_and_server_environment(self):
        result = self.run_cli(FIXTURES / "linear.json", "--base-repository", "base/project",
                              "--head-repository", "fork/project", "--sha", SHA,
                              "--pull-request", "9", "--source-prefix=module ü",
                              env={"GITHUB_SERVER_URL": "https://git.example.test"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("https://git.example.test/base/project/pull/9/", result.stdout)
        self.assertIn(f"https://git.example.test/fork/project/blob/{SHA}/module%20%C3%BC/", result.stdout)


class SizeTests(unittest.TestCase):
    def test_giant_artifact_keeps_warnings_complete_bullets_and_exact_counts(self):
        value = report()
        step = value["steps"][0]
        count = 6000
        step.update(cycle=True, artifact=True, functions=[
            {"id": f"example.com/pkg.F{i}", "file": f"pkg/файл {i}.go", "line": i + 1}
            for i in range(count)])
        markdown = render(value)
        self.assertLessEqual(len(markdown.encode("utf-8")), renderer.SUMMARY_LIMIT)
        self.assertIn(f"**Changed functions:** {count}", markdown)
        self.assertIn(f"## 1 · Cycle · {count} functions", markdown)
        self.assertIn("dependency cycle; review them together", markdown)
        self.assertIn("probable call-graph artifact", markdown)
        bullets = [line for line in markdown.splitlines() if line.startswith("- ")]
        included = len(bullets)
        self.assertGreater(included, 0)
        self.assertLess(included, count)
        self.assertIn(f"{count - included} functions omitted from this cycle.", markdown)
        self.assertIn(f"Showing 1 of 1 steps and {included} of {count} functions.", markdown)
        self.assertIn(f"Omitted 0 steps and {count - included} functions", markdown)
        self.assertNotIn("<details>", markdown)
        for index, bullet in enumerate(bullets):
            self.assertTrue(bullet.startswith(f"- `F{index}()` — ["))
            self.assertTrue(bullet.endswith(f"#L{index + 1}))"))

    def test_summary_at_exact_utf8_boundary_and_one_byte_over(self):
        value = report(function_id="prefix.F")
        initial = render(value)
        spare = renderer.SUMMARY_LIMIT - len(initial.encode("utf-8"))
        # Prefix appears only in Full IDs, so byte growth is exactly controlled.
        value["steps"][0]["functions"][0]["id"] = "prefix" + "é" * (spare // 2) + "x" * (spare % 2) + ".F"
        boundary = render(value)
        self.assertEqual(len(boundary.encode("utf-8")), renderer.SUMMARY_LIMIT)
        self.assertIn("</details>", boundary)
        self.assertNotIn("omitted", boundary)
        value["steps"][0]["functions"][0]["id"] = "x" + value["steps"][0]["functions"][0]["id"]
        over = render(value)
        self.assertLessEqual(len(over.encode("utf-8")), renderer.SUMMARY_LIMIT)
        self.assertIn("Full function IDs were omitted", over)
        self.assertIn("Showing 1 of 1 steps and 1 of 1 functions.", over)
        self.assertIn("Omitted 0 steps and 0 functions.", over)
        self.assertIn("## 1", over)
        self.assertNotIn("<details>", over)

    def test_large_ordinary_steps_are_never_split_or_skipped(self):
        value = {"steps": [dict(report(function_id=f"pkg.F{i}" + "ü" * 15000)["steps"][0], order=i + 1)
                           for i in range(40)]}
        markdown = render(value)
        shown = len(re.findall(r"^## ", markdown, re.MULTILINE))
        self.assertGreater(shown, 0)
        self.assertLess(shown, 40)
        self.assertLessEqual(len(markdown.encode("utf-8")), renderer.SUMMARY_LIMIT)
        self.assertIn(f"Showing {shown} of 40 steps and {shown} of 40 functions.", markdown)
        self.assertIn(f"Omitted {40 - shown} steps and {40 - shown} functions", markdown)
        for index in range(shown):
            self.assertIn(f"`F{index}" + "ü" * 15000 + "()`", markdown)
        self.assertNotIn(f"F{shown}", markdown)

    def test_single_huge_ordinary_step_can_show_zero_without_broken_markdown(self):
        markdown = render(report(function_id="pkg." + "x" * renderer.SUMMARY_LIMIT))
        self.assertNotIn("## 1", markdown)
        self.assertIn("Showing 0 of 1 steps and 0 of 1 functions.", markdown)
        self.assertIn("Run Ordo locally", markdown)
        self.assertLessEqual(len(markdown.encode("utf-8")), renderer.SUMMARY_LIMIT)

    def test_single_huge_cycle_bullet_can_show_only_heading_and_warnings(self):
        value = report(function_id="pkg." + "x" * renderer.SUMMARY_LIMIT)
        value["steps"][0].update(cycle=True, artifact=True)
        markdown = render(value)
        self.assertIn("## 1 · Cycle · 1 functions", markdown)
        self.assertIn("probable call-graph artifact", markdown)
        self.assertIn("1 functions omitted from this cycle.", markdown)
        self.assertIn("Showing 1 of 1 steps and 0 of 1 functions.", markdown)
        self.assertLessEqual(len(markdown.encode("utf-8")), renderer.SUMMARY_LIMIT)


if __name__ == "__main__":
    unittest.main()
