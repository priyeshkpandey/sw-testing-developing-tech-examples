import unittest

import demo


class HarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.results = demo.run_all()
        cls.report = demo.build_report(cls.cases, cls.results)

    def test_deterministic(self):
        _, again = demo.run_all()
        self.assertEqual(self.results, again)

    def test_cases_well_formed(self):
        self.assertEqual(len(self.cases), demo.N_CASES)
        tiers = {c["tier"] for c in self.cases}
        self.assertEqual(tiers, {"easy", "borderline", "hard", "biased"})

    def test_single_shot_costs_one_call(self):
        self.assertEqual(self.results["single N=1"]["calls_per_case"], 1.0)

    def test_fixed_vote_costs_n_calls(self):
        self.assertEqual(self.results["vote N=5"]["calls_per_case"], 5.0)
        self.assertEqual(self.results["vote N=9"]["calls_per_case"], 9.0)

    def test_adaptive_cost_bounds(self):
        c = self.results["adaptive max5"]["calls_per_case"]
        self.assertGreaterEqual(c, 3.0)
        self.assertLessEqual(c, 5.0)

    def test_metrics_in_range(self):
        for r in self.results.values():
            self.assertTrue(0.0 <= r["flip_rate"] <= 1.0)
            self.assertTrue(0.0 <= r["accuracy"] <= 1.0)

    def test_schema(self):
        r = self.report
        for k in ("verdict", "summary", "outcomes", "chart", "table", "notes"):
            self.assertIn(k, r)
        self.assertIsInstance(r["verdict"], str)
        self.assertGreaterEqual(len(r["outcomes"]), 3)
        for o in r["outcomes"]:
            self.assertIn(o["verdict"], ("worked", "partial", "failed"))
            self.assertIsInstance(o["case"], str)
            self.assertIsInstance(o["evidence"], str)
        self.assertTrue(any(o["verdict"] == "failed" for o in r["outcomes"]))
        ch = r["chart"]
        for name, vals in ch["series"].items():
            self.assertEqual(len(vals), len(ch["labels"]))
        for row in r["table"]["rows"]:
            self.assertEqual(len(row), len(r["table"]["columns"]))
        for v in r["summary"].values():
            self.assertIsInstance(v, (int, float))


if __name__ == "__main__":
    unittest.main()
