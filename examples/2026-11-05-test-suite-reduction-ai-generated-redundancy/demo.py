"""Test-suite reduction on a simulated, redundant "LLM-style" generated suite.

The generator is a deterministic STUB (no real LLM). It emits paraphrased and
near-duplicate tests for a few small functions. We then compare reduction
strategies on size, line/branch coverage retained and mutants killed.

Coverage is measured with sys.settrace (lines) and a hand-instrumented branch
recorder (via a global _BR set). Mutants are produced by textual replacement
of the function source, so everything is stdlib and deterministic.
"""
import json
import random
import sys

SEED = 12345

# ---------------------------------------------------------------------------
# Subjects: source text. Branch ids are recorded via _BR.add((fn, id, taken)).
# ---------------------------------------------------------------------------
SUBJECT_SRC = {
    "clamp": '''
def clamp(x, lo, hi):
    if x < lo:
        _BR.add(("clamp", 1, True))
        return lo
    _BR.add(("clamp", 1, False))
    if x > hi:
        _BR.add(("clamp", 2, True))
        return hi
    _BR.add(("clamp", 2, False))
    return x
''',
    "grade": '''
def grade(score):
    if score >= 90:
        _BR.add(("grade", 1, True))
        return "A"
    _BR.add(("grade", 1, False))
    if score >= 80:
        _BR.add(("grade", 2, True))
        return "B"
    _BR.add(("grade", 2, False))
    if score >= 70:
        _BR.add(("grade", 3, True))
        return "C"
    _BR.add(("grade", 3, False))
    return "F"
''',
    "discount": '''
def discount(price, qty):
    total = price * qty
    if qty >= 10:
        _BR.add(("discount", 1, True))
        total = total * 0.9
    else:
        _BR.add(("discount", 1, False))
    if total > 1000:
        _BR.add(("discount", 2, True))
        total = total - 50
    else:
        _BR.add(("discount", 2, False))
    return round(total, 2)
''',
    "is_leap": '''
def is_leap(y):
    if y % 400 == 0:
        _BR.add(("is_leap", 1, True))
        return True
    _BR.add(("is_leap", 1, False))
    if y % 100 == 0:
        _BR.add(("is_leap", 2, True))
        return False
    _BR.add(("is_leap", 2, False))
    return y % 4 == 0
''',
}

# Mutations: (subject, old, new, label). Each old string must occur in the source.
MUTATIONS = [
    ("clamp", "x < lo", "x <= lo", "clamp: < -> <= (lo)"),
    ("clamp", "x > hi", "x >= hi", "clamp: > -> >= (hi)"),
    ("clamp", "return lo", "return hi", "clamp: return lo -> hi"),
    ("grade", "score >= 90", "score > 90", "grade: >=90 -> >90"),
    ("grade", "score >= 80", "score > 80", "grade: >=80 -> >80"),
    ("grade", "score >= 70", "score > 70", "grade: >=70 -> >70"),
    ("grade", 'return "C"', 'return "B"', "grade: C -> B"),
    ("discount", "qty >= 10", "qty > 10", "discount: qty>=10 -> >10"),
    ("discount", "total > 1000", "total >= 1000", "discount: >1000 -> >=1000"),
    ("discount", "total * 0.9", "total * 0.8", "discount: 0.9 -> 0.8"),
    ("discount", "total - 50", "total - 40", "discount: -50 -> -40"),
    ("is_leap", "y % 400 == 0", "y % 400 == 1", "is_leap: 400 rule broken"),
    ("is_leap", "y % 100 == 0", "y % 100 == 1", "is_leap: 100 rule broken"),
    ("is_leap", "y % 4 == 0", "y % 4 == 1", "is_leap: 4 rule broken"),
    # Equivalent mutant (cannot be killed): 3 -> 3 arithmetic no-op on a return.
    ("clamp", "return x", "return x + 0", "clamp: return x -> x+0 (EQUIVALENT)"),
]

# ---------------------------------------------------------------------------
# Deterministic LLM-STUB generator: (subject, args, expected) tuples with
# paraphrase-style redundancy. Expected values are computed from the ORIGINAL
# implementation so every test passes on correct code.
# ---------------------------------------------------------------------------


def compile_fn(name, src):
    ns = {"_BR": set()}
    exec(compile(src, "<%s>" % name, "exec"), ns)
    return ns[name], ns["_BR"]


ORIG = {n: compile_fn(n, s) for n, s in SUBJECT_SRC.items()}


def expected(subject, args):
    fn, br = ORIG[subject]
    out = fn(*args)
    br.clear()
    return out


def generate_suite(rng):
    """LLM-style stub: many 'happy path' paraphrases, few boundary tests."""
    raw = []

    def add(subject, args, tag):
        raw.append({"subject": subject, "args": args, "tag": tag})

    # Heavy redundancy around mid-range / typical values (what LLMs love).
    for v in [5, 6, 7, 5, 8, 5, 9, 6]:
        add("clamp", (v, 0, 10), "clamp-inrange")
    for v in [-5, -9, -5, -20]:
        add("clamp", (v, 0, 10), "clamp-low")
    for v in [15, 50, 15, 99]:
        add("clamp", (v, 0, 10), "clamp-high")
    add("clamp", (0, 0, 10), "clamp-boundary-lo")  # rare boundary tests
    add("clamp", (10, 0, 10), "clamp-boundary-hi")
    for v in [95, 99, 100, 95, 97, 99]:
        add("grade", (v,), "grade-A")
    for v in [85, 88, 85, 86]:
        add("grade", (v,), "grade-B")
    for v in [75, 72, 75, 78]:
        add("grade", (v,), "grade-C")
    for v in [10, 30, 10, 50, 0, 10]:
        add("grade", (v,), "grade-F")
    add("grade", (90,), "grade-boundary-A")
    add("grade", (80,), "grade-boundary-B")
    # No boundary test for 70: a realistic generator gap.
    for q, p in [(1, 10), (2, 10), (1, 10), (3, 5), (2, 10), (1, 20)]:
        add("discount", (p, q), "discount-small")
    for q, p in [(20, 10), (12, 10), (20, 10), (15, 8)]:
        add("discount", (p, q), "discount-bulk")
    for q, p in [(20, 100), (30, 100), (20, 100)]:
        add("discount", (p, q), "discount-huge")
    add("discount", (10, 10), "discount-boundary-qty10")
    # No boundary test for total == 1000, another realistic gap.
    for y in [2024, 2000, 2024, 2020, 2024, 2016, 2000, 2024]:
        add("is_leap", (y,), "leap-yes")
    for y in [2023, 2021, 2023, 2019, 2023]:
        add("is_leap", (y,), "leap-no")
    for y in [1900, 1800, 1900]:
        add("is_leap", (y,), "leap-century-no")

    # Stable shuffle: ordering must not be accidentally favourable/unfavourable.
    rng.shuffle(raw)
    suite = []
    for i, t in enumerate(raw):
        suite.append({
            "id": i,
            "subject": t["subject"],
            "args": t["args"],
            "tag": t["tag"],
            "expected": expected(t["subject"], t["args"]),
        })
    return suite


# ---------------------------------------------------------------------------
# Execution + measurement
# ---------------------------------------------------------------------------


def run_in(subject, src, args):
    """Run one call against (possibly mutated) source; return (result, lines, branches)."""
    fn, br = compile_fn(subject, src)
    code = fn.__code__
    lines = set()

    def tracer(frame, event, arg):
        if frame.f_code is code:
            if event == "line":
                lines.add((subject, frame.f_lineno))
            return tracer
        return None

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        try:
            res = ("ok", fn(*args))
        except Exception as e:  # mutant may crash
            res = ("err", type(e).__name__)
    finally:
        sys.settrace(old)
    return res, lines, set(br)


def profile_tests(suite):
    """Per-test: line set, branch set, set of mutant indexes killed."""
    prof = {}
    for t in suite:
        _, lines, branches = run_in(t["subject"], SUBJECT_SRC[t["subject"]], t["args"])
        killed = set()
        for mi, (subj, old, new, _label) in enumerate(MUTATIONS):
            if subj != t["subject"]:
                continue
            msrc = SUBJECT_SRC[subj].replace(old, new, 1)
            assert msrc != SUBJECT_SRC[subj], "mutation did not apply: " + _label
            res, _, _ = run_in(subj, msrc, t["args"])
            if res != ("ok", t["expected"]):
                killed.add(mi)
        prof[t["id"]] = {"lines": lines, "branches": branches, "killed": killed}
    return prof


def measure(ids, prof):
    lines, branches, killed = set(), set(), set()
    for i in ids:
        lines |= prof[i]["lines"]
        branches |= prof[i]["branches"]
        killed |= prof[i]["killed"]
    return lines, branches, killed


# ---------------------------------------------------------------------------
# Reduction strategies
# ---------------------------------------------------------------------------


def reduce_none(suite, prof):
    return [t["id"] for t in suite]


def reduce_exact_dedup(suite, prof):
    seen, keep = set(), []
    for t in suite:
        key = (t["subject"], t["args"])
        if key not in seen:
            seen.add(key)
            keep.append(t["id"])
    return keep


def greedy_cover(suite, universe_of):
    """Generic greedy set cover; ties broken by lowest test id (deterministic)."""
    universe = set()
    for t in suite:
        universe |= universe_of(t["id"])
    keep, covered = [], set()
    remaining = sorted(t["id"] for t in suite)
    while covered != universe:
        best, best_gain = None, 0
        for i in remaining:
            gain = len(universe_of(i) - covered)
            if gain > best_gain:
                best, best_gain = i, gain
        if best is None:
            break
        keep.append(best)
        covered |= universe_of(best)
        remaining.remove(best)
    return keep


def reduce_coverage(suite, prof):
    return greedy_cover(
        suite, lambda i: prof[i]["lines"] | {("B",) + b for b in prof[i]["branches"]})


def reduce_mutation(suite, prof):
    # Preserve mutants killed; also keep line/branch coverage (mutation-first, then coverage).
    keep = greedy_cover(suite, lambda i: {("M", m) for m in prof[i]["killed"]})
    lines, branches, _ = measure(keep, prof)
    all_ids = [t["id"] for t in suite]
    all_lines, all_branches, _ = measure(all_ids, prof)
    if lines != all_lines or branches != all_branches:
        rest = [t for t in suite if t["id"] not in keep]
        extra = greedy_cover(
            rest,
            lambda i: (prof[i]["lines"] - lines)
            | {("B",) + b for b in (prof[i]["branches"] - branches)})
        keep = keep + extra
    return keep


STRATEGIES = [
    ("no_reduction", reduce_none),
    ("exact_dedup", reduce_exact_dedup),
    ("coverage_greedy", reduce_coverage),
    ("mutation_greedy", reduce_mutation),
]


def pct(a, b):
    return round(100.0 * a / b, 2) if b else 0.0


def main():
    rng = random.Random(SEED)
    suite = generate_suite(rng)
    prof = profile_tests(suite)
    all_ids = [t["id"] for t in suite]
    full_lines, full_br, full_killed = measure(all_ids, prof)
    n_mut = len(MUTATIONS)

    rows, per = [], {}
    for name, fn in STRATEGIES:
        keep = fn(suite, prof)
        l, b, k = measure(keep, prof)
        per[name] = {
            "size": len(keep),
            "reduction_pct": pct(len(suite) - len(keep), len(suite)),
            "line_ret": pct(len(l), len(full_lines)),
            "branch_ret": pct(len(b), len(full_br)),
            "killed": len(k),
            "kill_ret": pct(len(k), len(full_killed)),
            "mutation_score": pct(len(k), n_mut),
        }
        rows.append([name, len(keep), per[name]["reduction_pct"], per[name]["line_ret"],
                     per[name]["branch_ret"], len(k), per[name]["kill_ret"],
                     per[name]["mutation_score"]])

    cov, mut, dd = per["coverage_greedy"], per["mutation_greedy"], per["exact_dedup"]
    cov_loss_pp = round(100.0 - cov["kill_ret"], 2)
    unkilled = [MUTATIONS[i][3] for i in range(n_mut) if i not in full_killed]
    lost_by_cov = sorted(
        MUTATIONS[i][3] for i in full_killed - measure(reduce_coverage(suite, prof), prof)[2])

    cov_ok = (cov["line_ret"] == 100.0 and cov["branch_ret"] == 100.0)
    hyp_size = 60.0 <= cov["reduction_pct"] <= 80.0
    hyp_loss = cov_loss_pp >= 10.0
    mut_ok = mut["kill_ret"] == 100.0

    outcomes = [
        {"case": "coverage_greedy keeps full line+branch coverage",
         "verdict": "worked" if cov_ok else "failed",
         "evidence": "line %.1f%%, branch %.1f%% retained at %d/%d tests (%.1f%% smaller)"
                     % (cov["line_ret"], cov["branch_ret"], cov["size"], len(suite),
                        cov["reduction_pct"])},
        {"case": "coverage_greedy preserves mutants killed",
         "verdict": "failed" if cov_loss_pp >= 10.0 else ("partial" if cov_loss_pp > 0 else "worked"),
         "evidence": "lost %.1f pp of killed mutants (%d of %d); lost: %s"
                     % (cov_loss_pp, len(full_killed) - cov["killed"], len(full_killed),
                        "; ".join(lost_by_cov) or "none")},
        {"case": "mutation_greedy preserves all killed mutants",
         "verdict": "worked" if mut_ok else "failed",
         "evidence": "%d/%d killed mutants retained with %d tests (%.1f%% smaller)"
                     % (mut["killed"], len(full_killed), mut["size"], mut["reduction_pct"])},
        {"case": "exact_dedup reduction power on paraphrased tests",
         "verdict": "partial",
         "evidence": "only %.1f%% smaller (%d tests); kill retention %.1f%%"
                     % (dd["reduction_pct"], dd["size"], dd["kill_ret"])},
        {"case": "mutants no suite subset can kill (generator gaps / equivalent)",
         "verdict": "failed",
         "evidence": "%d of %d mutants survive even the full suite: %s"
                     % (len(unkilled), n_mut, "; ".join(unkilled) or "none")},
    ]

    hyp_text = ("hypothesis size band 60-80%%: %s (coverage_greedy %.1f%%); "
                ">=10pp mutant loss: %s (%.1f pp); mutation_greedy 100%% retention: %s"
                % ("met" if hyp_size else "NOT met", cov["reduction_pct"],
                   "met" if hyp_loss else "NOT met", cov_loss_pp,
                   "met" if mut_ok else "NOT met"))

    verdict = ("Coverage-preserving reduction shrank the generated suite by %.0f%% while keeping "
               "all lines/branches but lost %.1f pp of killed mutants; mutation-preserving "
               "reduction kept every killed mutant at %d vs %d tests, but this is a small "
               "single-seed simulated suite where the full suite itself misses %d mutants."
               % (cov["reduction_pct"], cov_loss_pp, mut["size"], cov["size"], len(unkilled)))

    results = {
        "verdict": verdict,
        "summary": {
            "suite_size": len(suite),
            "mutants_total": n_mut,
            "mutants_killed_full_suite": len(full_killed),
            "coverage_greedy_size": cov["size"],
            "coverage_greedy_reduction_pct": cov["reduction_pct"],
            "coverage_greedy_kill_loss_pp": cov_loss_pp,
            "mutation_greedy_size": mut["size"],
            "mutation_greedy_reduction_pct": mut["reduction_pct"],
            "mutation_greedy_kill_loss_pp": round(100.0 - mut["kill_ret"], 2),
            "exact_dedup_reduction_pct": dd["reduction_pct"],
        },
        "outcomes": outcomes,
        "chart": {
            "title": "Reduction strategies: size vs retained detection",
            "ylabel": "value",
            "labels": [n for n, _ in STRATEGIES],
            "series": {
                "suite size (tests)": [per[n]["size"] for n, _ in STRATEGIES],
                "branch coverage retained (%)": [per[n]["branch_ret"] for n, _ in STRATEGIES],
                "killed mutants retained (%)": [per[n]["kill_ret"] for n, _ in STRATEGIES],
            },
        },
        "table": {
            "columns": ["strategy", "tests", "size reduction %", "line cov retained %",
                        "branch cov retained %", "mutants killed", "kill retained %",
                        "mutation score %"],
            "rows": rows,
        },
        "notes": [
            "Generator is a deterministic STUB imitating LLM redundancy; no real model was used.",
            "Redundancy structure (many typical values, few boundary tests) is my own design "
            "choice and drives the outcome; real suites may differ greatly.",
            "Single seed, 4 tiny functions, %d mutants incl. 1 deliberate equivalent mutant: "
            "percentages are coarse and not statistically meaningful." % n_mut,
            "Mutation score here = killed / all mutants, so equivalent/unkilled mutants cap it.",
            "Greedy set cover is a heuristic; it is not guaranteed to be minimal.",
            "mutation_greedy also adds tests to keep full line/branch coverage, so it is not "
            "a pure mutation-only reduction.",
            hyp_text,
        ],
    }
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results["summary"], indent=2))
    print(hyp_text)


if __name__ == "__main__":
    main()
