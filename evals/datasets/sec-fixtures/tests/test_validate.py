"""Offline recovery checks cannot promote historical assertions to verified evidence."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DATASET = Path(__file__).resolve().parents[1]
SCRIPT = DATASET / "validate.py"


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT.is_file():
            raise AssertionError("offline structural validator is not implemented")
        spec = importlib.util.spec_from_file_location("sec_fixture_validate", SCRIPT)
        cls.validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.validator)
        cls.data = (DATASET / "manifest.jsonl").read_bytes()
        cls.cohort = (DATASET.parent / "issuer-cohort.json").read_bytes()
        cls.rows = [json.loads(line) for line in cls.data.splitlines()]

    def mutated(self, field, value):
        rows = copy.deepcopy(self.rows)
        rows[0][field] = value
        return b"\n".join(json.dumps(row).encode() for row in rows) + b"\n"

    def report(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = self.validator.main(args)
        return code, json.loads(output.getvalue())

    def test_exact_recovery_passes_without_rejecting_filing_agent_prefixes(self):
        self.assertEqual(self.validator.validate_manifest(self.data, self.cohort), [])
        self.assertEqual(len(self.rows), 60)
        self.assertEqual(
            sum(row["accession"][:10] != row["issuer"]["cik"] for row in self.rows), 21
        )
        self.assertEqual(
            hashlib.sha256((DATASET / "SOURCE-LICENSE.txt").read_bytes()).hexdigest(),
            "9df2530031b509fd7af008447f39b631abb2058c31cfe2febb49a3de3cea83a9",
        )

    def test_structural_success_does_not_satisfy_full_acceptance(self):
        for args, expected in [(["--structural-only"], 0), ([], 2)]:
            with self.subTest(args=args):
                code, report = self.report(args)
                self.assertEqual(code, expected)
                self.assertEqual(report["scope"], "historical_structure")
                self.assertTrue(report["structural_valid"])
                self.assertFalse(report["acceptance_passed"])
                self.assertEqual(report["verified_feature_count"], 0)
                self.assertEqual(len(report["historical_feature_assertions"]), 7)
                self.assertEqual(report["historical_feature_assertions"]["multi_currency"], 2)
                self.assertIn("fetched_bytes", report["unavailable_evidence"])

    def test_whitespace_drift_and_substituted_cohort_fail_recovery(self):
        self.assertEqual(
            self.validator.validate_manifest(self.data + b" ", self.cohort)[0],
            "manifest.sha256",
        )
        self.assertIn(
            "cohort.sha256", self.validator.validate_manifest(self.data, self.cohort + b" ")
        )

    def test_invalid_jsonl_and_duplicate_keys_fail_closed(self):
        for data in [b"\xff", b"{", b"{}\n\n", b'{"id":1,"id":2}', b"[]"]:
            with self.subTest(data=data):
                errors = self.validator.validate_manifest(data, self.cohort)
                self.assertTrue(any(code in errors for code in ["manifest.jsonl", "row.1.keys"]))
        for cohort in [b"{", b"[]", b'{"issuers":[]}', b'{"issuers":null}']:
            with self.subTest(cohort=cohort):
                self.assertIn("cohort.issuers", self.validator.validate_manifest(self.data, cohort))

    def test_row_shapes_and_nonempty_scalar_types_are_required(self):
        row = self.rows[0]
        for changed in [
            {k: v for k, v in row.items() if k != "form"},
            {**row, "supplemental": True},
        ]:
            data = json.dumps(changed).encode() + b"\n" + b"\n".join(self.data.splitlines()[1:])
            self.assertIn("row.1.keys", self.validator.validate_manifest(data, self.cohort))
        for field, value, code in [
            ("form", True, "scalar"),
            ("why_selected", " ", "scalar"),
            ("issuer", [], "issuer"),
            ("issuer", {"cik": "0001433195"}, "issuer"),
            ("issuer", {"cik": True, "ticker": "APPF"}, "issuer"),
            ("issuer", {"cik": "0001433195", "ticker": "APPF", "other": 1}, "issuer"),
            ("stress_features", [], "stress_features"),
            ("stress_features", True, "stress_features"),
            ("stress_features", [True], "stress_features"),
        ]:
            with self.subTest(field=field, value=value):
                self.assertIn(
                    f"row.1.{code}",
                    self.validator.validate_manifest(self.mutated(field, value), self.cohort),
                )

    def test_bad_identity_date_tag_and_metadata_associations_are_rejected(self):
        cases = [
            ("id", "FX-0061"),
            ("id", "BAD"),
            ("accession", "123"),
            ("filed_at", "2026-02-30"),
            ("filed_at", "20260201"),
            ("sha256", "A" * 64),
            ("form", "8-K"),
            ("issuer", {"cik": "1433195", "ticker": "APPF"}),
            ("issuer", {"cik": "9999999999", "ticker": "APPF"}),
            ("issuer", {"cik": "0001433195", "ticker": "CRM"}),
            ("stress_features", ["invented_eighth_feature"]),
            ("stress_features", ["pre_2018_formatting", "pre_2018_formatting"]),
            ("stress_features", ["amended_filing", "pre_2018_formatting"]),
            ("stress_features", ["legacy_html_no_ixbrl"]),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.assertIn(
                    f"row.1.{field}",
                    self.validator.validate_manifest(self.mutated(field, value), self.cohort),
                )

    def test_duplicate_identities_and_missing_cohort_coverage_fail(self):
        for field in ["id", "accession", "url", "sha256"]:
            with self.subTest(field=field):
                errors = self.validator.validate_manifest(
                    self.mutated(field, self.rows[1][field]), self.cohort
                )
                self.assertIn(f"duplicate.{field}", errors)
        missing = b"\n".join(
            json.dumps(row).encode() for row in self.rows if row["issuer"]["ticker"] != "APPF"
        )
        errors = self.validator.validate_manifest(missing, self.cohort)
        self.assertIn("manifest.rows", errors)
        self.assertIn("manifest.issuers", errors)

    def test_archive_urls_cannot_escape_or_misidentify_recorded_filing(self):
        for basename in ["../x.htm", "x/y.htm", "x\\y.htm", "%78.htm", "x.htm?q", ".", ".."]:
            with self.subTest(basename=basename):
                self.assertIn(
                    "row.1.primary_document",
                    self.validator.validate_manifest(
                        self.mutated("primary_document", basename), self.cohort
                    ),
                )
        for url in [
            self.rows[0]["url"] + "?q=1",
            self.rows[0]["url"] + "#x",
            self.rows[1]["url"],
            "https://example.invalid/filing.htm",
        ]:
            with self.subTest(url=url):
                self.assertIn(
                    "row.1.url",
                    self.validator.validate_manifest(self.mutated("url", url), self.cohort),
                )

    def test_read_failure_and_invalid_data_never_print_input_contents(self):
        for error in [FileNotFoundError("sensitive path"), PermissionError("sensitive path")]:
            with patch.object(Path, "read_bytes", side_effect=error):
                code, report = self.report(["--structural-only"])
            self.assertEqual(code, 1)
            self.assertFalse(report["acceptance_passed"])
            self.assertEqual(report["errors"], ["input.read"])
            self.assertNotIn("sensitive path", json.dumps(report))
        with patch.object(Path, "read_bytes", side_effect=[b"private malformed data", self.cohort]):
            code, report = self.report(["--structural-only"])
        self.assertEqual(code, 1)
        self.assertFalse(report["structural_valid"])
        self.assertNotIn("private malformed data", json.dumps(report))

    def test_cli_uses_adjacent_inputs_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            for args, expected in [(["--structural-only"], 0), ([], 2)]:
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), *args],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertFalse(json.loads(result.stdout)["acceptance_passed"])


if __name__ == "__main__":
    unittest.main()
