import json
import os
import tempfile
import unittest
import demo


class HarnessTests(unittest.TestCase):
    def test_suites_pass_on_original_and_reference(self):
        for name, src in demo.SOURCES.items():
            fn = demo.load(src, name)
            ex = demo.HAPPY[name] + demo.BOUNDARY[name]
            self.assertTrue(demo.run_suite(fn, ex, demo.PROPS[name]), name)
            self.assertTrue(
                demo.run_suite(demo.REFS[name], ex, demo.PROPS[name]), name)

    def test_mutants_deterministic_and_nonempty(self):
        for name, src in demo.SOURCES.items():
            a = demo.make_mutants(src)
            b = demo.make_mutants(src)
            self.assertEqual(a, b)
            self.assertGreater(len(a), 0)

    def test_mutants_differ_from_original(self):
        src = demo.SOURCES["clamp"]
        orig = demo.ast.unparse(demo.ast.parse(src))
        for _, m in demo.make_mutants(src):
            self.assertNotEqual(m, orig)

    def test_results_schema(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                demo.main()
                with open("results.json") as f:
                    r = json.load(f)
            finally:
                os.chdir(old)
        for k in ("verdict", "summary", "outcomes", "chart", "table",
                  "notes"):
            self.assertIn(k, r)
        self.assertGreaterEqual(len(r["outcomes"]), 3)
        for o in r["outcomes"]:
            self.assertIn(o["verdict"], ("worked", "partial", "failed"))
        for s in r["chart"]["series"].values():
            self.assertEqual(len(s), len(r["chart"]["labels"]))


if __name__ == "__main__":
    unittest.main()
