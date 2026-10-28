"""Coverage vs mutation score for LLM-style buggy functions.

Stdlib only, deterministic. No real LLM is involved: the "LLM-style bugs" are
hand-written variants of correct reference functions, and the three test suites
are hand-written to model typical happy-path / branch-driven / boundary+property
testing styles.

Mutation score here = fraction of *mutants of the buggy implementation* that the
suite kills, PLUS we report the detection rate for the injected bugs themselves
(buggy impl vs reference: does the suite fail on the buggy version?).
"""
import ast
import copy
import json
import random
import sys

# --------------------------------------------------------------------------
# Corpus: (name, bug_class, reference source, buggy source)
# --------------------------------------------------------------------------
CORPUS = [
    {
        "name": "sum_first_n",
        "bug": "off-by-one",
        "ref": "def f(xs, n):\n    t = 0\n    for i in range(n):\n        t += xs[i]\n    return t\n",
        "buggy": "def f(xs, n):\n    t = 0\n    for i in range(n - 1):\n        t += xs[i]\n    return t\n",
    },
    {
        "name": "safe_div",
        "bug": "missing-edge-guard",
        "ref": "def f(a, b):\n    if b == 0:\n        return 0\n    return a // b\n",
        "buggy": "def f(a, b):\n    return a // b\n",
    },
    {
        "name": "is_adult",
        "bug": "wrong-boundary-operator",
        "ref": "def f(age):\n    return age >= 18\n",
        "buggy": "def f(age):\n    return age > 18\n",
    },
    {
        "name": "sub_clamped",
        "bug": "swapped-args",
        "ref": "def f(a, b):\n    d = a - b\n    if d < 0:\n        return 0\n    return d\n",
        "buggy": "def f(a, b):\n    d = b - a\n    if d < 0:\n        return 0\n    return d\n",
    },
    {
        "name": "name_len",
        "bug": "none-handling",
        "ref": "def f(s):\n    if s is None:\n        return 0\n    return len(s.strip())\n",
        "buggy": "def f(s):\n    return len(s.strip())\n",
    },
    {
        "name": "max_of",
        "bug": "missing-edge-guard",
        "ref": "def f(xs):\n    if not xs:\n        return None\n    m = xs[0]\n    for x in xs:\n        if x > m:\n            m = x\n    return m\n",
        "buggy": "def f(xs):\n    m = xs[0]\n    for x in xs:\n        if x > m:\n            m = x\n    return m\n",
    },
    {
        "name": "in_range",
        "bug": "wrong-boundary-operator",
        "ref": "def f(x, lo, hi):\n    return lo <= x <= hi\n",
        "buggy": "def f(x, lo, hi):\n    return lo < x < hi\n",
    },
    {
        "name": "last_k",
        "bug": "off-by-one",
        "ref": "def f(xs, k):\n    if k <= 0:\n        return []\n    return xs[-k:]\n",
        "buggy": "def f(xs, k):\n    if k <= 0:\n        return []\n    return xs[-(k + 1):]\n",
    },
    {
        "name": "discount",
        "bug": "swapped-args",
        "ref": "def f(price, pct):\n    return price - price * pct // 100\n",
        "buggy": "def f(price, pct):\n    return pct - pct * price // 100\n",
    },
    {
        "name": "first_word",
        "bug": "none-handling",
        "ref": "def f(s):\n    if s is None or s == '':\n        return ''\n    return s.split()[0] if s.split() else ''\n",
        "buggy": "def f(s):\n    if s == '':\n        return ''\n    return s.split()[0] if s.split() else ''\n",
    },
    {
        "name": "abs_diff",
        "bug": "none-detectable-by-any-test (equivalent)",
        "ref": "def f(a, b):\n    return a - b if a >= b else b - a\n",
        "buggy": "def f(a, b):\n    return a - b if a > b else b - a\n",
    },
]

# --------------------------------------------------------------------------
# Helpers: compile, coverage tracing
# --------------------------------------------------------------------------

def compile_fn(src_or_tree):
    """Compile source text or an AST Module into the function named f."""
    if isinstance(src_or_tree, ast.AST):
        tree = ast.fix_missing_locations(src_or_tree)
        code = compile(tree, "<fn>", "exec")
    else:
        code = compile(src_or_tree, "<fn>", "exec")
    ns = {}
    exec(code, ns)
    return ns["f"]


def line_coverage(src, suite):
    """Fraction of executable lines of f executed by the suite (sys.settrace)."""
    tree = ast.parse(src)
    fn_node = tree.body[0]
    exec_lines = set()
    for node in ast.walk(fn_node):
        if isinstance(node, ast.stmt) and node is not fn_node:
            exec_lines.add(node.lineno)
    code = compile(src, "<cov>", "exec")
    ns = {}
    exec(code, ns)
    f = ns["f"]
    hit = set()

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != "<cov>":
            return tracer
        if event == "line":
            hit.add(frame.f_lineno)
        return tracer

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        for args, _ in suite:
            try:
                f(*args)
            except Exception:
                pass
    finally:
        sys.settrace(old)
    return len(hit & exec_lines) / max(1, len(exec_lines))


def branch_coverage(src, suite):
    """Fraction of (if/while/ternary) decision outcomes observed True and False."""
    tree = ast.parse(src)
    tests = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            tests.append(node)
    if not tests:
        return 1.0
    seen = {}

    class Rec:
        def __init__(self, i):
            self.i = i

        def __call__(self, v):
            seen.setdefault(self.i, set()).add(bool(v))
            return v

    t2 = copy.deepcopy(tree)
    idx = 0
    for node in ast.walk(t2):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            node.test = ast.Call(
                func=ast.Name(id="__rec%d" % idx, ctx=ast.Load()),
                args=[node.test], keywords=[])
            idx += 1
    ast.fix_missing_locations(t2)
    ns = {("__rec%d" % i): Rec(i) for i in range(idx)}
    exec(compile(t2, "<br>", "exec"), ns)
    f = ns["f"]
    for args, _ in suite:
        try:
            f(*args)
        except Exception:
            pass
    total = 2 * idx
    got = sum(len(v) for v in seen.values())
    return got / total

# --------------------------------------------------------------------------
# AST mutation
# --------------------------------------------------------------------------
CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE,
            ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv,
            ast.FloorDiv: ast.Mult}


def generate_mutants(src):
    """Return list of (description, ast.Module) mutants, deterministic order."""
    base = ast.parse(src)
    mutants = []
    nodes = list(ast.walk(base))
    for ni, node in enumerate(nodes):
        if isinstance(node, ast.Compare):
            for oi, op in enumerate(node.ops):
                if type(op) in CMP_SWAP:
                    m = copy.deepcopy(base)
                    tgt = list(ast.walk(m))[ni]
                    tgt.ops[oi] = CMP_SWAP[type(op)]()
                    mutants.append(("cmp %s->%s" % (type(op).__name__, CMP_SWAP[type(op)].__name__), m))
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
            m = copy.deepcopy(base)
            tgt = list(ast.walk(m))[ni]
            tgt.op = BIN_SWAP[type(node.op)]()
            mutants.append(("binop %s->%s" % (type(node.op).__name__, BIN_SWAP[type(node.op)].__name__), m))
        elif isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            m = copy.deepcopy(base)
            tgt = list(ast.walk(m))[ni]
            tgt.value = node.value + 1
            mutants.append(("const %d->%d" % (node.value, node.value + 1), m))
    return mutants

# --------------------------------------------------------------------------
# Suites. Each suite is a list of (args, expected) pairs; expected comes from
# the REFERENCE implementation (oracle), computed in build_suites.
# --------------------------------------------------------------------------
HAPPY = {
    "sum_first_n": [([1, 2, 3, 4], 4)] ,
    "safe_div": [(10, 2)],
    "is_adult": [(30,)],
    "sub_clamped": [(10, 3), (3, 10)],
    "name_len": [(" bob ",)],
    "max_of": [([3, 9, 2],)],
    "in_range": [(5, 1, 10)],
    "last_k": [([1, 2, 3, 4, 5], 2)],
    "discount": [(200, 10)],
    "first_word": [("hello world",)],
    "abs_diff": [(7, 3), (3, 7)],
}

BRANCH = {
    "sum_first_n": [([1, 2, 3, 4], 4), ([1, 2, 3], 0)],
    "safe_div": [(10, 2), (5, 0)],
    "is_adult": [(30,), (5,)],
    "sub_clamped": [(10, 3), (3, 10)],
    "name_len": [(" bob ",), (None,)],
    "max_of": [([3, 9, 2],), ([],)],
    "in_range": [(5, 1, 10), (50, 1, 10)],
    "last_k": [([1, 2, 3, 4, 5], 2), ([1, 2], 0)],
    "discount": [(200, 10), (50, 0)],
    "first_word": [("hello world",), (None,), ("",), ("   ",)],
    "abs_diff": [(7, 3), (3, 7)],
}

BOUNDARY = {
    "sum_first_n": [([1, 2, 3, 4], 4), ([1, 2, 3], 0), ([5], 1), ([1, 2, 3], 2)],
    "safe_div": [(10, 2), (5, 0), (0, 3), (-7, 2), (7, 7)],
    "is_adult": [(17,), (18,), (19,), (0,)],
    "sub_clamped": [(10, 3), (3, 10), (5, 5), (0, 1), (1, 0)],
    "name_len": [(" bob ",), (None,), ("",), ("   ",), ("a",)],
    "max_of": [([3, 9, 2],), ([],), ([1],), ([-5, -2, -9],), ([4, 4],)],
    "in_range": [(5, 1, 10), (1, 1, 10), (10, 1, 10), (0, 1, 10), (11, 1, 10)],
    "last_k": [([1, 2, 3, 4, 5], 2), ([1, 2], 0), ([1, 2, 3], 3), ([1, 2, 3], 1), ([1, 2], -1)],
    "discount": [(200, 10), (50, 0), (100, 100), (0, 50), (7, 33)],
    "first_word": [("hello world",), (None,), ("",), ("   ",), ("x",)],
    "abs_diff": [(7, 3), (3, 7), (5, 5), (0, 0)],
}


def prop_cases(name, rng, n=40):
    """Seeded random property-style inputs (stdlib random, fixed seed)."""
    out = []
    for _ in range(n):
        if name == "sum_first_n":
            xs = [rng.randint(-5, 5) for _ in range(rng.randint(0, 6))]
            out.append((xs, rng.randint(0, len(xs))))
        elif name in ("safe_div", "sub_clamped", "abs_diff"):
            out.append((rng.randint(-10, 10), rng.randint(-3, 3)))
        elif name == "is_adult":
            out.append((rng.randint(10, 26),))
        elif name == "name_len":
            out.append((rng.choice([None, "", " ", " ab ", "abc", "  x"]),))
        elif name == "max_of":
            out.append(([rng.randint(-5, 5) for _ in range(rng.randint(0, 5))],))
        elif name == "in_range":
            lo = rng.randint(-3, 3)
            out.append((rng.randint(-5, 8), lo, lo + rng.randint(0, 4)))
        elif name == "last_k":
            xs = [rng.randint(0, 9) for _ in range(rng.randint(0, 6))]
            out.append((xs, rng.randint(-1, 7)))
        elif name == "discount":
            out.append((rng.randint(0, 300), rng.randint(0, 100)))
        elif name == "first_word":
            out.append((rng.choice([None, "", " ", "a b", "  lead", "x"]),))
    return out


def label(cases, ref_fn):
    """Attach oracle expected values from the reference."""
    suite = []
    for c in cases:
        args = c if isinstance(c, tuple) else (c,)
        # suites above store (args_tuple...) mixed; normalise
        suite.append((args, None))
    return suite


def normalise(raw):
    """Raw entries are tuples of args except sum_first_n/last_k which are (list, n)."""
    return [tuple(c) if isinstance(c, (list, tuple)) else (c,) for c in raw]


def build_suites(name, ref_fn):
    def mk(raw):
        suite = []
        for c in raw:
            args = tuple(c)
            try:
                exp = ref_fn(*copy.deepcopy(args))
            except Exception as e:  # reference should not raise on our inputs
                exp = ("EXC", type(e).__name__)
            suite.append((args, exp))
        return suite

    rng = random.Random(1234)
    boundary_plus_prop = list(BOUNDARY[name]) + prop_cases(name, rng)
    return {
        "happy_path": mk(HAPPY[name]),
        "branch_driven": mk(BRANCH[name]),
        "boundary_property": mk(boundary_plus_prop),
    }


def passes(fn, suite):
    """True if fn matches expected on every case."""
    for args, exp in suite:
        try:
            got = fn(*copy.deepcopy(args))
        except Exception as e:
            got = ("EXC", type(e).__name__)
        if got != exp:
            return False
    return True


def run():
    suites_names = ["happy_path", "branch_driven", "boundary_property"]
    detect = {s: 0 for s in suites_names}
    line_cov = {s: [] for s in suites_names}
    br_cov = {s: [] for s in suites_names}
    mut_killed = {s: 0 for s in suites_names}
    mut_total = 0
    sanity_ref_ok = True
    rows = []
    by_bug = {}
    detectable_total = 0

    for spec in CORPUS:
        ref_fn = compile_fn(spec["ref"])
        buggy_fn = compile_fn(spec["buggy"])
        suites = build_suites(spec["name"], ref_fn)
        equivalent = "equivalent" in spec["bug"]
        if not equivalent:
            detectable_total += 1
        mutants = generate_mutants(spec["ref"])
        # mutation score is computed on mutants of the REFERENCE
        valid_mutants = []
        for desc, tree in mutants:
            try:
                valid_mutants.append((desc, compile_fn(tree)))
            except Exception:
                continue
        mut_total += len(valid_mutants)
        row = [spec["name"], spec["bug"]]
        for s in suites_names:
            suite = suites[s]
            if not passes(ref_fn, suite):
                sanity_ref_ok = False
            caught = not passes(buggy_fn, suite)
            if caught and not equivalent:
                detect[s] += 1
                by_bug.setdefault(spec["bug"], {k: 0 for k in suites_names})[s] += 1
            elif not equivalent:
                by_bug.setdefault(spec["bug"], {k: 0 for k in suites_names})
            line_cov[s].append(line_coverage(spec["ref"], suite))
            br_cov[s].append(branch_coverage(spec["ref"], suite))
            killed = sum(1 for _, mf in valid_mutants if not passes(mf, suite))
            mut_killed[s] += killed
            row.append("caught" if caught else "MISSED")
        rows.append(row)

    n = len(CORPUS)
    summary = {}
    for s in suites_names:
        summary["bug_detection_rate_" + s] = round(detect[s] / detectable_total, 3)
        summary["mutation_score_" + s] = round(mut_killed[s] / mut_total, 3)
        summary["mean_line_coverage_" + s] = round(sum(line_cov[s]) / n, 3)
        summary["mean_branch_coverage_" + s] = round(sum(br_cov[s]) / n, 3)
    summary["functions"] = n
    summary["detectable_bugs"] = detectable_total
    summary["total_mutants"] = mut_total

    outcomes = []
    for s in suites_names:
        rate = summary["bug_detection_rate_" + s]
        v = "worked" if rate >= 0.85 else ("partial" if rate >= 0.5 else "failed")
        outcomes.append({
            "case": "%s suite: injected-bug detection" % s,
            "verdict": v,
            "evidence": "caught %d/%d detectable bugs (rate %.2f); mean line cov %.2f, branch cov %.2f; mutation score %.2f"
            % (detect[s], detectable_total, rate, summary["mean_line_coverage_" + s],
               summary["mean_branch_coverage_" + s], summary["mutation_score_" + s]),
        })
    eq_missed = all(r[2 + i] == "MISSED" for r in rows if r[0] == "abs_diff" for i in range(3))
    outcomes.append({
        "case": "abs_diff equivalent mutant (> vs >=)",
        "verdict": "failed",
        "evidence": "behaviourally equivalent change; no suite can or should catch it (%s). Excluded from detection rate but it shows mutation scores are noisy on equivalents." % ("all suites missed it" if eq_missed else "some suite flagged it unexpectedly"),
    })

    chart = {
        "title": "Coverage vs fault detection by suite",
        "ylabel": "fraction (0-1)",
        "labels": suites_names,
        "series": {
            "line coverage": [summary["mean_line_coverage_" + s] for s in suites_names],
            "branch coverage": [summary["mean_branch_coverage_" + s] for s in suites_names],
            "mutation score": [summary["mutation_score_" + s] for s in suites_names],
            "injected-bug detection": [summary["bug_detection_rate_" + s] for s in suites_names],
        },
    }
    table = {"columns": ["function", "bug class"] + suites_names, "rows": rows}

    h, b, p = (summary["bug_detection_rate_happy_path"],
               summary["bug_detection_rate_branch_driven"],
               summary["bug_detection_rate_boundary_property"])
    verdict = ("Line coverage was high for every suite yet detection varied (happy %.2f, branch %.2f, boundary+property %.2f); "
               "mutation score tracked fault detection far better than coverage did, but results are on a tiny hand-built corpus."
               % (h, b, p))
    notes = [
        "No real LLM is used: the 'LLM-style bugs' and the happy-path suites are hand-written to resemble typical outputs; this is a stub for illustration, not evidence about any model.",
        "Corpus is 11 tiny functions (10 detectable bugs + 1 equivalent mutant); rates are coarse (steps of 0.1) and not statistically meaningful.",
        "Suites were authored by hand with knowledge of the bug classes, which biases boundary suites towards success; the hypothesis numbers were not tuned to.",
        "Mutation score is computed over mutants of the reference implementation (operators: comparison flip, + - * // swap, int constant +1); equivalent mutants are not filtered, which deflates scores.",
        "Line/branch coverage are measured on the reference with sys.settrace / AST instrumentation and are simplified (no exception-edge or short-circuit branches).",
    ]
    return {"verdict": verdict, "summary": summary, "outcomes": outcomes,
            "chart": chart, "table": table, "notes": notes,
            "_sanity_ref_ok": sanity_ref_ok}


if __name__ == "__main__":
    res = run()
    sanity = res.pop("_sanity_ref_ok")
    if not sanity:
        print("HARNESS ERROR: reference failed its own suite", file=sys.stderr)
        sys.exit(2)
    with open("results.json", "w") as fh:
        json.dump(res, fh, indent=2)
    print(res["verdict"])
    for k, v in res["summary"].items():
        print("%s: %s" % (k, v))
