"""Coverage vs mutation score on simulated LLM-style generated functions.

Stdlib only, deterministic. Writes results.json in the cwd.
The "LLM-generated" functions are hand-written plausible code with subtle
bugs in spirit; they are NOT produced by a real model.
"""
import ast
import copy
import json
import random
import sys

random.seed(1234)

# ---------------------------------------------------------------------------
# Subject functions (plausible LLM-style code). Each is correct w.r.t. its
# spec; mutation then injects subtle faults.
# ---------------------------------------------------------------------------
SOURCES = {
    "discount": '''
def discount(price, qty):
    if qty >= 10:
        rate = 0.2
    elif qty >= 5:
        rate = 0.1
    else:
        rate = 0.0
    return price * qty * (1 - rate)
''',
    "clamp": '''
def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
''',
    "is_leap": '''
def is_leap(y):
    if y % 400 == 0:
        return True
    if y % 100 == 0:
        return False
    return y % 4 == 0
''',
    "paginate": '''
def paginate(items, page, size):
    start = (page - 1) * size
    end = start + size
    return items[start:end]
''',
    "grade": '''
def grade(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    return "F"
''',
    "count_positive": '''
def count_positive(xs):
    n = 0
    for v in xs:
        if v > 0:
            n += 1
    return n
''',
}

# Independent reference implementations (spec), used to validate suites.
def ref_discount(price, qty):
    rate = 0.2 if qty >= 10 else 0.1 if qty >= 5 else 0.0
    return price * qty * (1 - rate)

def ref_clamp(x, lo, hi):
    return max(lo, min(hi, x))

def ref_is_leap(y):
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0

def ref_paginate(items, page, size):
    return list(items)[(page - 1) * size:(page - 1) * size + size]

def ref_grade(s):
    return "A" if s >= 90 else "B" if s >= 80 else "C" if s >= 70 else "F"

def ref_count_positive(xs):
    return sum(1 for v in xs if v > 0)

REFS = {
    "discount": ref_discount, "clamp": ref_clamp, "is_leap": ref_is_leap,
    "paginate": ref_paginate, "grade": ref_grade,
    "count_positive": ref_count_positive,
}

# ---------------------------------------------------------------------------
# Test suites. "examples" are (args, expected) pairs; expected values are
# hand-written literals (not computed). "props" are callables f(fn) -> bool.
# ---------------------------------------------------------------------------
HAPPY = {  # one comfortable input per branch -> 100% line/branch coverage
    "discount": [((10.0, 12), 96.0), ((10.0, 6), 54.0), ((10.0, 2), 20.0)],
    "clamp": [((-5, 0, 10), 0), ((15, 0, 10), 10), ((5, 0, 10), 5)],
    "is_leap": [((2000,), True), ((1900,), False), ((2024,), True),
                ((2023,), False)],
    "paginate": [(([1, 2, 3, 4, 5, 6], 2, 2), [3, 4])],
    "grade": [((95,), "A"), ((85,), "B"), ((75,), "C"), ((10,), "F")],
    "count_positive": [(([1, -2, 3],), 2)],
}

BOUNDARY = {  # extra boundary-value examples (hand-computed literals)
    "discount": [((10.0, 10), 80.0), ((10.0, 9), 72.0), ((10.0, 5), 45.0),
                 ((10.0, 4), 40.0), ((10.0, 0), 0.0)],
    "clamp": [((0, 0, 10), 0), ((10, 0, 10), 10), ((-1, 0, 10), 0),
              ((11, 0, 10), 10), ((1, 0, 10), 1), ((9, 0, 10), 9)],
    "is_leap": [((1600,), True), ((2100,), False), ((2004,), True),
                ((2001,), False), ((1904,), True)],
    "paginate": [(([1, 2, 3, 4, 5], 1, 2), [1, 2]),
                 (([1, 2, 3, 4, 5], 3, 2), [5]),
                 (([1, 2, 3], 4, 2), []),
                 (([1, 2, 3, 4], 2, 2), [3, 4])],
    "grade": [((90,), "A"), ((89,), "B"), ((80,), "B"), ((79,), "C"),
              ((70,), "C"), ((69,), "F")],
    "count_positive": [(([0, 0],), 0), (([1],), 1), (([],), 0),
                       (([0, 1, -1, 2],), 2)],
}


def _prop_discount(fn):
    # monotone non-decreasing total in qty is NOT true at tier edges, so
    # check: result never exceeds undiscounted, never negative, and equals
    # price*qty*(1-r) with r in {0,.1,.2}.
    for qty in range(0, 25):
        v = fn(10.0, qty)
        full = 10.0 * qty
        if v > full + 1e-9 or v < -1e-9:
            return False
        ok = any(abs(v - full * (1 - r)) < 1e-9 for r in (0.0, 0.1, 0.2))
        if not ok:
            return False
    return True


def _prop_clamp(fn):
    for x in range(-15, 26):
        v = fn(x, 0, 10)
        if not (0 <= v <= 10):
            return False
        if 0 <= x <= 10 and v != x:
            return False
    return True


def _prop_is_leap(fn):
    for y in range(1580, 2420):
        if fn(y) != ref_is_leap(y):
            return False
    return True


def _prop_paginate(fn):
    items = list(range(7))
    for size in (1, 2, 3, 7):
        joined = []
        page = 1
        while True:
            chunk = fn(items, page, size)
            if not chunk:
                break
            if len(chunk) > size:
                return False
            joined.extend(chunk)
            page += 1
            if page > 50:
                return False
        if joined != items:
            return False
    return True


def _prop_grade(fn):
    order = "FCBA"
    last = 0
    for s in range(0, 101):
        i = order.index(fn(s))
        if i < last:
            return False
        last = i
    return True


def _prop_count_positive(fn):
    rng = random.Random(7)
    for _ in range(60):
        xs = [rng.randint(-3, 3) for _ in range(rng.randint(0, 8))]
        if fn(xs) != sum(1 for v in xs if v > 0):
            return False
    return True


PROPS = {
    "discount": _prop_discount, "clamp": _prop_clamp,
    "is_leap": _prop_is_leap, "paginate": _prop_paginate,
    "grade": _prop_grade, "count_positive": _prop_count_positive,
}

# ---------------------------------------------------------------------------
# Mutation operators (ast based)
# ---------------------------------------------------------------------------
CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE,
            ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div,
            ast.Mod: ast.Mult}


class Collector(ast.NodeVisitor):
    def __init__(self):
        self.sites = []  # (kind, index)
        self.i = 0

    def generic_visit(self, node):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 \
                and type(node.ops[0]) in CMP_SWAP:
            self.sites.append(("cmp", self.i))
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
            self.sites.append(("bin", self.i))
        elif isinstance(node, ast.Constant) and isinstance(node.value, int) \
                and not isinstance(node.value, bool):
            self.sites.append(("const", self.i))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            self.sites.append(("bool", self.i))
        self.i += 1
        super().generic_visit(node)


class Mutator(ast.NodeTransformer):
    def __init__(self, target):
        self.target = target
        self.i = 0
        self.done = False

    def visit(self, node):
        idx = self.i
        self.i += 1
        node = self.generic_visit(node)
        if idx != self.target or self.done:
            return node
        if isinstance(node, ast.Compare):
            node.ops = [CMP_SWAP[type(node.ops[0])]()]
            self.done = True
        elif isinstance(node, ast.BinOp):
            node.op = BIN_SWAP[type(node.op)]()
            self.done = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            node.value = not node.value
            self.done = True
        elif isinstance(node, ast.Constant):
            node.value = node.value + 1
            self.done = True
        return node


def make_mutants(src):
    tree = ast.parse(src)
    c = Collector()
    c.visit(tree)
    mutants = []
    for kind, idx in c.sites:
        t = copy.deepcopy(tree)
        m = Mutator(idx)
        t = m.visit(t)
        ast.fix_missing_locations(t)
        mutants.append((f"{kind}@{idx}", ast.unparse(t)))
    return mutants


def load(src, name):
    ns = {}
    exec(compile(src, f"<{name}>", "exec"), ns)
    return ns[name]


# ---------------------------------------------------------------------------
# Suite execution
# ---------------------------------------------------------------------------
def _eq(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(a - b) < 1e-9
        except TypeError:
            return False
    return a == b


def run_suite(fn, examples, prop):
    """True if every example and property passes (exceptions = failure)."""
    try:
        for args, exp in examples:
            if not _eq(fn(*[copy.deepcopy(a) for a in args]), exp):
                return False
        if prop is not None and not prop(fn):
            return False
    except Exception:
        return False
    return True


def run_with_timeout_guard(fn, examples, prop):
    # Mutants cannot loop forever in these subjects (bounded for-loops and
    # slicing only), so no timeout machinery is needed.
    return run_suite(fn, examples, prop)


# ---------------------------------------------------------------------------
# Coverage via sys.settrace (line + branch-outcome approximation)
# ---------------------------------------------------------------------------
def executable_lines(src):
    tree = ast.parse(src)
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(
                node, (ast.FunctionDef,)):
            lines.add(node.lineno)
    return lines


def branch_outcomes(src):
    """Return list of (lineno, 'T'/'F') outcomes for each If node."""
    out = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            body_first = node.body[0].lineno
            out.append((node.lineno, "T", body_first))
            if node.orelse:
                out.append((node.lineno, "F", node.orelse[0].lineno))
            else:
                out.append((node.lineno, "F", None))
        elif isinstance(node, ast.For):
            out.append((node.lineno, "T", node.body[0].lineno))
            out.append((node.lineno, "F", None))
    return out


def measure_coverage(src, name, examples, prop):
    code = compile(src, f"<cov-{name}>", "exec")
    ns = {}
    exec(code, ns)
    fn = ns[name]
    hit = []  # ordered line events inside the function

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != f"<cov-{name}>":
            return None
        if event == "line":
            hit.append(frame.f_lineno)
        return tracer

    sys.settrace(tracer)
    try:
        for args, _ in examples:
            fn(*[copy.deepcopy(a) for a in args])
        if prop is not None:
            prop(fn)
    finally:
        sys.settrace(None)

    hitset = set(hit)
    lines = executable_lines(src)
    line_cov = len(lines & hitset) / len(lines) if lines else 1.0

    outs = branch_outcomes(src)
    covered = 0
    for lineno, which, target in outs:
        if target is not None:
            if target in hitset:
                covered += 1
        else:
            # implicit-else / loop exit: count as covered if the next hit
            # after the condition line is not that branch body.
            body = [t for (l, w, t) in outs if l == lineno and w == "T"][0]
            seen = False
            for a, b in zip(hit, hit[1:]):
                if a == lineno and b != body:
                    seen = True
                    break
            if hit and hit[-1] == lineno:
                seen = True
            covered += 1 if seen else 0
    branch_cov = covered / len(outs) if outs else 1.0
    return line_cov, branch_cov


# ---------------------------------------------------------------------------
def evaluate(name, src, examples, prop):
    original = load(src, name)
    ref = REFS[name]
    # Harness sanity: suite must pass on the original AND on the reference.
    if not run_suite(original, examples, prop):
        bad = []
        for args, exp in examples:
            got = original(*[copy.deepcopy(a) for a in args])
            if not _eq(got, exp):
                bad.append((args, exp, got))
        raise AssertionError(
            f"suite fails on original {name}: mismatches={bad[:3]} "
            f"prop_ok={prop(original) if prop else None}")
    if not run_suite(ref, examples, prop):
        raise AssertionError(f"suite disagrees with reference for {name}")

    mutants = make_mutants(src)
    killed = 0
    survivors = []
    for label, msrc in mutants:
        try:
            mfn = load(msrc, name)
        except Exception:
            killed += 1
            continue
        if not run_with_timeout_guard(mfn, examples, prop):
            killed += 1
        else:
            survivors.append(label)
    line_cov, branch_cov = measure_coverage(src, name, examples, prop)
    return {
        "mutants": len(mutants), "killed": killed, "survivors": survivors,
        "line": line_cov, "branch": branch_cov,
    }


def main():
    suites = {
        "happy_path": lambda f: (HAPPY[f], None),
        "boundary": lambda f: (HAPPY[f] + BOUNDARY[f], None),
        "boundary+property": lambda f: (HAPPY[f] + BOUNDARY[f], PROPS[f]),
    }
    per = {s: {} for s in suites}
    for sname, getter in suites.items():
        for fname, src in SOURCES.items():
            ex, pr = getter(fname)
            per[sname][fname] = evaluate(fname, src, ex, pr)

    def agg(sname):
        r = per[sname].values()
        tm = sum(x["mutants"] for x in r)
        tk = sum(x["killed"] for x in r)
        return {
            "line": sum(x["line"] for x in r) / len(per[sname]),
            "branch": sum(x["branch"] for x in r) / len(per[sname]),
            "mutation": tk / tm if tm else 0.0,
            "mutants": tm, "killed": tk,
        }

    A = {s: agg(s) for s in suites}
    summary = {}
    for s in suites:
        summary[f"{s}_line_cov_pct"] = round(100 * A[s]["line"], 1)
        summary[f"{s}_branch_cov_pct"] = round(100 * A[s]["branch"], 1)
        summary[f"{s}_mutation_score_pct"] = round(100 * A[s]["mutation"], 1)
    summary["total_mutants"] = A["happy_path"]["mutants"]

    outcomes = []
    for fname in SOURCES:
        h = per["happy_path"][fname]
        b = per["boundary+property"][fname]
        hs = h["killed"] / h["mutants"]
        bs = b["killed"] / b["mutants"]
        if bs >= 0.9 and hs < 0.6:
            v = "worked"
        elif bs > hs:
            v = "partial"
        else:
            v = "failed"
        ev = (f"happy: line {h['line']:.0%} branch {h['branch']:.0%} "
              f"mut {hs:.0%}; augmented mut {bs:.0%}; "
              f"surviving after augmentation: {b['survivors'] or 'none'}")
        outcomes.append({"case": fname, "verdict": v, "evidence": ev})

    hm = A["happy_path"]["mutation"]
    am = A["boundary+property"]["mutation"]
    hyp_met = hm < 0.6 and am > 0.9
    verdict = (
        f"Happy-path suites reached {100*A['happy_path']['line']:.0f}% line / "
        f"{100*A['happy_path']['branch']:.0f}% branch coverage but killed only "
        f"{100*hm:.0f}% of mutants; adding boundary and property checks raised "
        f"this to {100*am:.0f}% — "
        + ("the stated thresholds (<60% vs >90%) were met on this small, "
           "hand-picked sample." if hyp_met else
           "the stated thresholds (<60% vs >90%) were NOT both met, so the "
           "hypothesis is only partly supported here."))

    chart = {
        "title": "Coverage vs mutation score by suite (mean over subjects)",
        "ylabel": "percent",
        "labels": list(suites),
        "series": {
            "line coverage": [summary[f"{s}_line_cov_pct"] for s in suites],
            "branch coverage": [summary[f"{s}_branch_cov_pct"]
                                for s in suites],
            "mutation score": [summary[f"{s}_mutation_score_pct"]
                               for s in suites],
        },
    }
    rows = []
    for fname in SOURCES:
        row = [fname, per["happy_path"][fname]["mutants"]]
        for s in suites:
            r = per[s][fname]
            row.append(f"{100*r['killed']/r['mutants']:.0f}%")
        rows.append(row)
    table = {
        "columns": ["function", "mutants", "happy_path mut%",
                    "boundary mut%", "boundary+property mut%"],
        "rows": rows,
    }
    notes = [
        "Subjects are 6 tiny hand-written functions imitating LLM style; "
        "no real LLM was used. Results do not generalise to real code bases.",
        "Mutation operators: comparison swap, arithmetic swap, int constant "
        "+1, bool flip. No statement deletion or return-value mutation.",
        "Equivalent mutants are not filtered, so some survivors may be "
        "semantically identical to the original and the true ceiling is "
        "below 100%.",
        "Branch coverage is an approximation derived from line events, not "
        "full branch tracing (sys.settrace line events only).",
        "Property checks here are exhaustive sweeps / seeded random loops, "
        "written knowing the specs; a real author would not have this "
        "hindsight, and thresholds were not tuned after seeing results.",
    ]
    out = {"verdict": verdict, "summary": summary, "outcomes": outcomes,
           "chart": chart, "table": table, "notes": notes}
    with open("results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(verdict)


if __name__ == "__main__":
    main()
