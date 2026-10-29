import json
import os
import tempfile
import unittest

import demo


class HarnessTests(unittest.TestCase):
    def test_corpus_deterministic_and_sized(self):
        import random
        c1 = demo.build_corpus(random.Random(demo.SEED))
        c2 = demo.build_corpus(random.Random(demo.SEED))
        self.assertEqual(c1, c2)
        self.assertEqual(len(c1), demo.N_SNIPPETS)
        self.assertTrue(any(s["defect"] for s in c1))
        self.assertTrue(any(not s["defect"] for s in c1))

    def test_all_snippets_parse(self):
        import random
        import ast
        for s in demo.build_corpus(random.Random(demo.SEED)):
            ast.parse(s["code"])

    def test_run_is_deterministic(self):
        self.assertEqual(demo.run(), demo.run())

    def test_rules_flag_known_cases(self):
        self.assertIn("unsafe_eval", demo.rule_candidates("def f(s):\n    return eval(s)\n"))
        self.assertIn("sql_concat", demo.rule_candidates(
            "def q(c, n):\n    c.execute('a' + n)\n"))
        self.assertEqual(demo.rule_candidates("def f(a):\n    return a\n"), set())

    def test_llm_only_calls_equal_corpus(self):
        r = demo.run()
        self.assertEqual(r["summary"]["llm_llm_calls"], demo.N_SNIPPETS)
        self.assertEqual(r["summary"]["rules_llm_calls"], 0)

    def test_hybrid_never_more_calls_than_llm_only(self):
        r = demo.run()
        self.assertLessEqual(r["summary"]["hybrid_llm_calls"], r["summary"]["llm_llm_calls"])

    def test_hybrid_recall_bounded_by_rules_recall(self):
        r = demo.run()
        self.assertLessEqual(r["summary"]["hybrid_recall"], r["summary"]["rules_recall"])

    def test_schema(self):
        r = demo.run()
        for k in ("verdict", "summary", "outcomes", "chart", "table", "notes"):
            self.assertIn(k, r)
        self.assertIsInstance(r["verdict"], str)
        self.assertGreaterEqual(len(r["outcomes"]), 3)
        for o in r["outcomes"]:
            self.assertIn(o["verdict"], ("worked", "partial", "failed"))
            self.assertIn("case", o)
            self.assertIn("evidence", o)
        self.assertTrue(any(o["verdict"] == "failed" for o in r["outcomes"]))
        n = len(r["chart"]["labels"])
        for vals in r["chart"]["series"].values():
            self.assertEqual(len(vals), n)
        for row in r["table"]["rows"]:
            self.assertEqual(len(row), len(r["table"]["columns"]))
        self.assertGreaterEqual(len(r["notes"]), 1)
        json.dumps(r)

    def test_main_writes_results_json(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                demo.main()
                with open("results.json") as fh:
                    data = json.load(fh)
                self.assertIn("verdict", data)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
