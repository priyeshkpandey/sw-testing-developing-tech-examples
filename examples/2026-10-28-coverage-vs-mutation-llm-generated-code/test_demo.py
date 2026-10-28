import unittest

import demo


class TestHarness(unittest.TestCase):
    def test_compile_fn_accepts_source_and_ast(self):
        import ast
        src = "def f(a):\n    return a + 1\n"
        self.assertEqual(demo.compile_fn(src)(1), 2)
        self.assertEqual(demo.compile_fn(ast.parse(src))(1), 2)

    def test_reference_passes_all_suites(self):
        res = demo.run()
        self.assertTrue(res["_sanity_ref_ok"])

    def test_deterministic(self):
        a = demo.run()
        b = demo.run()
        self.assertEqual(a["summary"], b["summary"])
        self.assertEqual(a["table"], b["table"])

    def test_schema(self):
        res = demo.run()
        self.assertIsInstance(res["verdict"], str)
        self.assertIsInstance(res["summary"], dict)
        self.assertGreaterEqual(len(res["outcomes"]), 3)
        for o in res["outcomes"]:
            self.assertIn(o["verdict"], ("worked", "partial", "failed"))
            self.assertIsInstance(o["case"], str)
            self.assertIsInstance(o["evidence"], str)
        ch = res["chart"]
        for s in ch["series"].values():
            self.assertEqual(len(s), len(ch["labels"]))
        self.assertEqual(len(res["table"]["columns"]), len(res["table"]["rows"][0]))
        self.assertTrue(res["notes"])

    def test_mutants_generated(self):
        muts = demo.generate_mutants("def f(a, b):\n    return a >= b\n")
        self.assertGreaterEqual(len(muts), 1)

    def test_coverage_in_unit_range(self):
        src = "def f(a):\n    if a:\n        return 1\n    return 0\n"
        suite = [((1,), 1), ((0,), 0)]
        self.assertEqual(demo.branch_coverage(src, suite), 1.0)
        self.assertEqual(demo.line_coverage(src, suite), 1.0)
        self.assertLess(demo.branch_coverage(src, [((1,), 1)]), 1.0)


if __name__ == "__main__":
    unittest.main()
