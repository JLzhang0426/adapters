"""Regression checks for the adapter guide / structural validator contract.

Run with: python3 -m unittest discover -s scripts/tests
"""

import json
import math
from pathlib import Path
import re
import statistics
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_adapter as validator

ROOT = Path(__file__).resolve().parents[2]


class AdapterRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.adapter = Path(self.temp.name) / "example"
        self.template = self.adapter / "src/example/task-template"
        self.template.mkdir(parents=True)
        (self.template.parent / "adapter.py").touch()
        for name in ("instruction.md", "environment/Dockerfile"):
            path = self.template / name
            path.parent.mkdir(exist_ok=True)
            path.touch()

    def check_template(self, config, extension, reward):
        (self.template / "task.toml").write_text(config)
        for folder, name in (("tests", "test"), ("solution", "solve")):
            path = self.template / folder / f"{name}.{extension}"
            path.parent.mkdir(exist_ok=True)
            path.write_text(reward)
        report = validator.AdapterReport("example")
        validator.check_template_structure(self.adapter, report)
        validator.check_template_content(self.adapter, report)
        return report

    def test_linux_default(self):
        report = self.check_template('[task]\nname = "{task_id}"\n', "sh",
                                     "echo 1 > /logs/verifier/reward.txt")
        self.assertEqual(report.findings, [])

    def test_windows_with_unrendered_template(self):
        report = self.check_template(
            '[task]\nname = "{task_id}"\n[environment] # target\nos = "WINDOWS"\ncpus = {cpus}\n',
            "bat", r"echo 1 > C:\logs\verifier\reward.txt")
        self.assertEqual(report.findings, [])

    def test_windows_requires_bat(self):
        report = self.check_template('[environment]\nos = "windows"\n', "sh", "")
        self.assertEqual(len(report.errors), 2)
        self.assertTrue(all(".bat" in finding.message for finding in report.errors))

    def test_windows_reward_warning(self):
        report = self.check_template('[environment]\nos = "windows"\n', "bat", "echo done")
        self.assertFalse(report.errors)
        self.assertEqual([f.check for f in report.warnings], ["Reward output"])

    def test_other_sections_and_comments_do_not_select_windows(self):
        for config in ('[metadata]\nos = "windows"\n',
                       '[environment]\n# os = "windows"\n',
                       '[environment]\nos = "linux"\n[metadata]\nos = "windows"\n'):
            with self.subTest(config=config):
                report = self.check_template(config, "sh", "echo 1 > /logs/verifier/reward.txt")
                self.assertEqual(report.findings, [])

    def test_cost_compatibility_and_warnings(self):
        for value, warn in (("$150", False), (150, False), (1.5, False),
                            (None, True), (["$150"], True), (True, True), ({}, True)):
            with self.subTest(value=value):
                (self.adapter / "adapter_metadata.json").write_text(json.dumps([{
                    "adapter_name": "example", "adapter_builders": ["Harbor Team"],
                    "original_benchmark": [], "harbor_adapter": [{"parity_costs": value}],
                }]))
                report = validator.AdapterReport("example")
                validator.check_metadata_json(self.adapter, report)
                costs = [f for f in report.findings if f.check == "Metadata: parity_costs"]
                self.assertEqual(bool(costs), warn)
                self.assertTrue(all(f.level == "warning" for f in costs))

    def test_guide_task_examples(self):
        guide = (ROOT / "docs/adapters.mdx").read_text()
        for block in re.findall(r"```toml\n(.*?)```", guide, re.DOTALL):
            config = tomllib.loads(block)
            if "task" not in config:
                continue
            with self.subTest(config=config):
                (self.template / "task.toml").write_text(block)
                report = validator.AdapterReport("example")
                validator.check_task_toml_schema(self.adapter, report)
                self.assertEqual(report.findings, [])
                self.assertTrue(config["task"]["authors"][0]["name"])

    def test_guide_json_examples(self):
        for guide_name in ("adapters.mdx", "adapters-human.mdx"):
            guide = (ROOT / "docs" / guide_name).read_text()
            for block in re.findall(r"```json\n(.*?)```", guide, re.DOTALL):
                entries = json.loads(block)
                if not isinstance(entries, list):
                    continue  # Historical registry.json migration example.
                with self.subTest(guide=guide_name, entries=entries):
                    parity = "metrics" in entries[0]
                    filename = "parity_experiment.json" if parity else "adapter_metadata.json"
                    (self.adapter / filename).write_text(block)
                    report = validator.AdapterReport("example")
                    if parity:
                        validator.check_parity_json(self.adapter, report)
                        validator.check_parity_pr_links(self.adapter, report)
                    else:
                        validator.check_metadata_json(self.adapter, report)
                    self.assertEqual(report.findings, [])
                    for entry in entries:
                        for metric in entry.get("metrics", []):
                            for side in ("original", "harbor"):
                                runs = metric[f"{side}_runs"]
                                mean, sem = map(float, metric[side].split(" ± "))
                                self.assertEqual(len(runs), entry["number_of_runs"])
                                self.assertAlmostEqual(mean, statistics.mean(runs), places=4)
                                self.assertAlmostEqual(sem, statistics.stdev(runs) / math.sqrt(len(runs)), places=4)

    def test_single_published_score_warns(self):
        (self.adapter / "parity_experiment.json").write_text(json.dumps([{
            "adapter_name": "example", "agent": "codex@1", "model": "example",
            "date": "2026-09-30", "number_of_runs": 1,
            "notes": "Published original score",
            "metrics": [{"benchmark_name": "example", "metric": "pass@1",
                         "original": "50", "original_runs": [50],
                         "harbor": "50", "harbor_runs": [50]}],
        }]))
        report = validator.AdapterReport("example")
        validator.check_parity_json(self.adapter, report)
        self.assertFalse(report.errors)
        self.assertEqual([f.check for f in report.warnings],
                         ["ADP-PARITY: insufficient runs"] * 2)

    def test_parity_findings_identify_repeated_entries_and_metrics(self):
        text = r'''[
  {"adapter_name": "example", "agent": "codex@1", "model": "example",
   "date": "2026-10-23", "dataset_pr": null, "parity_pr": null,
   "adapter_pr": ["https://example.com/1"],
   "metrics": [{"benchmark_name": "example", "metric": "baseline",
                "original": "1", "original_runs": [1, 1],
                "harbor": "1", "harbor_runs": [1, 1]}]},
  {"adapter_name": "example", "agent": "codex@1", "model": "example",
   "date": "2026-10-23", "dataset_pr": null, "parity_pr": null,
   "adapter_pr": ["https://example.com/2"],
   "notes": "Not a field: \"original_runs\": [0], {braces}",
   "metrics": [{"benchmark_name": "example", "metric": "chat reward",
                "original": "1", "original_runs": [1],
                "harbor": "1", "harbor_runs": [1]},
               {"benchmark_name": "example", "metric": "chat points",
                "original": "3", "original_runs": [3],
                "harbor": "3", "harbor_runs": [3]}]}
]'''
        (self.adapter / "parity_experiment.json").write_text(text)
        report = validator.AdapterReport("example")
        validator.check_parity_json(self.adapter, report)
        validator.check_parity_pr_links(self.adapter, report)
        runs = [f for f in report.warnings if f.check == "ADP-PARITY: insufficient runs"]
        self.assertEqual([f.line for f in runs], [13, 14, 16, 17])
        self.assertTrue(all("Entry 1, metric 0 (`chat reward`)" in f.message for f in runs[:2]))
        self.assertTrue(all("Entry 1, metric 1 (`chat points`)" in f.message for f in runs[2:]))
        links = [f for f in report.warnings if f.check == "Parity PR link null"]
        self.assertEqual([f.line for f in links], [3, 3, 9, 9])
        self.assertEqual(len(report.warnings), 8)
        self.assertFalse(report.errors)

    def test_contract_references_do_not_float(self):
        guide = (ROOT / "docs/adapters.mdx").read_text()
        self.assertIn(f"Adapter contract v{validator.CONTRACT_VERSION}", guide)
        for requirement in ("CLI", "AUTHORS", "SCRIPTS", "PARITY", "STATS", "COST", "README"):
            self.assertIn(f"ADP-{requirement}", guide)
        files = [".github/workflows/adapter-review.yml", "scripts/validate_adapter.py",
                 "docs/adapters.mdx", "docs/adapters-human.mdx",
                 "skills/create-adapter/SKILL.md", "skills/run-parity/SKILL.md",
                 "skills/upload-parity-experiments/SKILL.md"]
        for filename in files:
            with self.subTest(file=filename):
                content = (ROOT / filename).read_text()
                self.assertNotIn("blob/main/src/harbor/cli/template-adapter", content)
                self.assertNotIn("uv run python -m", content)
        references = re.findall(r"https://github.com/harbor-framework/harbor/(?:blob|tree)/([0-9a-f]{40})", guide)
        self.assertGreaterEqual(len(references), 4)
        self.assertEqual(len(set(references)), 1)

    def test_readme_section_contract(self):
        guide = (ROOT / "docs/adapters.mdx").read_text()
        headings = guide.split("The required README sections, in order, are:", 1)[1].split("```markdown", 1)[1].split("```", 1)[0]
        for name, pattern in validator._README_SECTIONS:
            with self.subTest(section=name):
                self.assertRegex(headings, "(?m)" + pattern)

if __name__ == "__main__":
    unittest.main()
