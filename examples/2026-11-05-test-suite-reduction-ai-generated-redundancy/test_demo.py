import json
import os
import random
import tempfile
import unittest

import demo


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.suite = demo.generate_suite(random.Random(demo.SEED))
        self.prof = demo.profile_tests(self.suite)

    def test_generator_is_deterministic(self):
        again = demo.generate_suite(random.Random(demo.SEED))
        self.assertEqual(self.suite, again)

    def test_suite_passes_on_original_code(self):
        for t in self.suite:
            fn, br = demo.ORIG[t["subject"]]
            self.assertEqual(fn(*t["args"]), t["expected"])
            br.clear()

    def test_every_mutation_applies(self):
        for subj, old, new, label in demo.MUTATIONS:
            self.assertIn(old, demo.SUBJECT_SRC[subj], label)

    def test_full_suite_is_redundant(self):
        distinct = {(t["subject"], t["args"]) for t in self.suite}
        self.assertLess(len(distinct), len(self.suite))

    def test_strategies_deterministic_and_subsets(self):
        all_ids = {t["id"] for t in self.suite}
        for name, fn in demo.STRATEGIES:
            a = fn(self.suite, self.prof)
            b = fn(self.suite, self.prof)
            self.assertEqual(a, b, name)
            self.assertTrue(set(a) <= all_ids, name)
            self.assertEqual(len(a), len(set(a)), name)

    def test_no_reduction_is_identity_and_never_beaten(self):
        full = demo.measure([t["id"] for t in self.suite], self.prof)
        for name, fn in demo.STRATEGIES:
            part = demo.measure(fn(self.suite, self.prof), self.prof)
            self.assertTrue(part[2] <= full[2], name)

    def test_coverage_greedy_preserves_coverage_by_construction(self):
        full = demo.measure([t["id"] for t in self.suite], self.prof)
        red = demo.measure(demo.reduce_coverage(self.suite, self.prof), self.prof)
        self.assertEqual(red[0], full[0])
        self.assertEqual(red[1], full[1])

    def test_mutation_greedy_preserves_kills_by_construction(self):
        full = demo.measure([t["id"] for t in self.suite], self.prof)
        red = demo.measure(demo.reduce_mutation(self.suite, self.prof), self.prof)
        self.assertEqual(red[2], full[2])

    def test_results_json_schema(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                demo.main()
                with open("results.json") as f:
                    r = json.load(f)
            finally:
                os.chdir(cwd)
        self.assertIsInstance(r["verdict"], str)
        self.assertTrue(all(isinstance(v, (int, float)) for v in r["summary"].values()))
        self.assertGreaterEqual(len(r["outcomes"]), 3)
        self.assertIn("failed", {o["verdict"] for o in r["outcomes"]})
        for o in r["outcomes"]:
            self.assertIn(o["verdict"], {"worked", "partial", "failed"})
        n = len(r["chart"]["labels"])
        for series in r["chart"]["series"].values():
            self.assertEqual(len(series), n)
        for row in r["table"]["rows"]:
            self.assertEqual(len(row), len(r["table"]["columns"]))
        self.assertTrue(r["notes"])


if __name__ == "__main__":
    unittest.main()
