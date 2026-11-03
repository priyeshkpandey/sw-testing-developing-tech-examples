import json
import os
import tempfile
import unittest

import demo


class HarnessTests(unittest.TestCase):
    def test_deterministic(self):
        a = demo.build_results(demo.run())
        b = demo.build_results(demo.run())
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_case_count_and_targets(self):
        cases = demo.make_cases()
        self.assertEqual(len(cases), 500)
        for c in cases:
            uids = {n.uid for n in demo.elements(c["root"])}
            self.assertIn(c["target_uid"], uids)

    def test_uids_are_ints(self):
        for name, html in demo.PAGES.items():
            root = demo.parse(html)
            for n in demo.elements(root):
                self.assertIsInstance(n.uid, int)

    def test_unmutated_page_locates_correctly(self):
        # Invariant: a stored selector uniquely resolves to its own target
        # on the unmutated page, for every element of every page.
        for name, html in demo.PAGES.items():
            root = demo.parse(html)
            for t in demo.elements(root):
                sel = demo.build_selector(t, root)
                found = demo._match(root, sel)
                self.assertEqual(len(found), 1, (name, t.tag, sel))
                self.assertIs(found[0], t, (name, t.tag, sel))
                self.assertIs(demo.brittle_locate(root, sel), t, (name, t.tag, sel))

    def test_schema(self):
        res = demo.build_results(demo.run())
        for k in ("verdict", "summary", "outcomes", "chart", "table", "notes"):
            self.assertIn(k, res)
        self.assertIsInstance(res["verdict"], str)
        self.assertGreaterEqual(len(res["outcomes"]), 3)
        for o in res["outcomes"]:
            self.assertIn(o["verdict"], ("worked", "partial", "failed"))
            self.assertIsInstance(o["case"], str)
            self.assertIsInstance(o["evidence"], str)
        ch = res["chart"]
        for s in ch["series"].values():
            self.assertEqual(len(s), len(ch["labels"]))
        self.assertEqual(len(res["table"]["rows"][0]), len(res["table"]["columns"]))
        for v in res["summary"].values():
            self.assertIsInstance(v, (int, float))
        json.dumps(res)

    def test_main_writes_results(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                demo.main()
                with open("results.json") as f:
                    data = json.load(f)
                self.assertIn("verdict", data)
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
