"""Flaky verdicts: single-shot vs majority-vote vs adaptive LLM-as-judge.

The judge is a deterministic, seeded STUB -- not a real LLM.
Each case has a ground-truth label, a difficulty and a bias flag. The stub's
probability of answering "pass" is built so that:
  * noise (difficulty) makes the judge close to a coin flip on hard cases,
  * a systematic bias (verbosity / position) pushes some wrong answers toward a
    confidently wrong verdict. Voting cannot repair a probability that is
    itself wrong (p_correct < 0.5).
Nothing here was tuned to make voting look good; the hypothesis may fail.
"""
import json
import random

N_CASES = 400
N_RERUNS = 200
BASE_SEED = 20240607
PLATEAU_TOL = 0.01


def make_cases(seed=BASE_SEED):
    rng = random.Random(seed)
    cases = []
    for i in range(N_CASES):
        label = rng.random() < 0.5            # True = output should pass
        u = rng.random()
        if u < 0.45:
            tier, p_correct = "easy", 0.95
        elif u < 0.80:
            tier, p_correct = "borderline", 0.65
        elif u < 0.92:
            tier, p_correct = "hard", 0.55
        else:
            # Systematic bias: judge is MORE likely wrong than right (e.g. a
            # verbose wrong answer looks good). Voting amplifies this error.
            tier, p_correct = "biased", 0.30
        cases.append({"id": i, "label": label, "tier": tier, "p_correct": p_correct})
    return cases


def judge_once(case, rng):
    """One stochastic judge call; returns the verdict (True=pass)."""
    correct = rng.random() < case["p_correct"]
    return case["label"] if correct else (not case["label"])


def strategy_single(case, rng):
    return judge_once(case, rng), 1


def strategy_vote(n):
    def run(case, rng):
        yes = sum(judge_once(case, rng) for _ in range(n))
        return yes * 2 > n, n
    return run


def strategy_adaptive(n_max):
    """Start with 3 calls; if unanimous stop, else sample up to n_max total."""
    def run(case, rng):
        votes = [judge_once(case, rng) for _ in range(3)]
        if len(set(votes)) == 1:
            return votes[0], 3
        while len(votes) < n_max:
            votes.append(judge_once(case, rng))
        return sum(votes) * 2 > len(votes), len(votes)
    return run


def evaluate(strategy, cases, seed_offset):
    """Run N_RERUNS full-suite reruns; return flip rate, accuracy, calls, per-tier acc."""
    verdicts = {c["id"]: [] for c in cases}
    total_calls = 0
    for r in range(N_RERUNS):
        rng = random.Random(BASE_SEED * 1000 + seed_offset * 100003 + r)
        for c in cases:
            v, calls = strategy(c, rng)
            verdicts[c["id"]].append(v)
            total_calls += calls
    flips = sum(1 for c in cases if len(set(verdicts[c["id"]])) > 1)
    correct = sum(v == c["label"] for c in cases for v in verdicts[c["id"]])
    tiers = {}
    for t in ("easy", "borderline", "hard", "biased"):
        cs = [c for c in cases if c["tier"] == t]
        ok = sum(v == c["label"] for c in cs for v in verdicts[c["id"]])
        tiers[t] = ok / (len(cs) * N_RERUNS) if cs else 0.0
    return {
        "flip_rate": flips / len(cases),
        "accuracy": correct / (len(cases) * N_RERUNS),
        "calls_per_case": total_calls / (len(cases) * N_RERUNS),
        "tier_acc": tiers,
    }


def run_all():
    cases = make_cases()
    strategies = [
        ("single N=1", strategy_single),
        ("vote N=3", strategy_vote(3)),
        ("vote N=5", strategy_vote(5)),
        ("vote N=9", strategy_vote(9)),
        ("adaptive max5", strategy_adaptive(5)),
    ]
    results = {}
    for i, (name, fn) in enumerate(strategies):
        results[name] = evaluate(fn, cases, i)
    return cases, results


def build_report(cases, results):
    base = results["single N=1"]
    v5 = results["vote N=5"]
    ad = results["adaptive max5"]
    flip_cut_v5 = 1 - v5["flip_rate"] / base["flip_rate"]
    flip_cut_ad = 1 - ad["flip_rate"] / base["flip_rate"]
    stab_ratio = flip_cut_ad / flip_cut_v5 if flip_cut_v5 else 0.0
    cost_ratio = ad["calls_per_case"] / v5["calls_per_case"]
    acc_gain_border = v5["tier_acc"]["borderline"] - base["tier_acc"]["borderline"]
    acc_gain_biased = v5["tier_acc"]["biased"] - base["tier_acc"]["biased"]
    acc_gain_v9 = results["vote N=9"]["accuracy"] - v5["accuracy"]

    h1 = flip_cut_v5 > 0.70
    h2 = stab_ratio >= 0.90 and cost_ratio < 0.60
    h3 = acc_gain_v9 <= PLATEAU_TOL and v5["tier_acc"]["biased"] < 0.5

    def vd(ok, partial=False):
        return "worked" if ok else ("partial" if partial else "failed")

    outcomes = [
        {"case": "N=5 vote cuts flip rate by >70%",
         "verdict": vd(h1, flip_cut_v5 > 0.4),
         "evidence": "flip rate %.3f -> %.3f (cut %.1f%%)" % (
             base["flip_rate"], v5["flip_rate"], 100 * flip_cut_v5)},
        {"case": "N=5 vote raises accuracy on borderline cases",
         "verdict": vd(acc_gain_border > 0.05, acc_gain_border > 0),
         "evidence": "borderline acc %.3f -> %.3f" % (
             base["tier_acc"]["borderline"], v5["tier_acc"]["borderline"])},
        {"case": "Adaptive keeps >=90% of vote-5 stability gain at <60% of its calls",
         "verdict": vd(h2, stab_ratio >= 0.9 or cost_ratio < 0.6),
         "evidence": "stability ratio %.2f, call ratio %.2f (%.2f vs %.2f calls/case)" % (
             stab_ratio, cost_ratio, ad["calls_per_case"], v5["calls_per_case"])},
        {"case": "Voting fixes systematically biased cases",
         "verdict": "failed",
         "evidence": "biased-tier acc %.3f -> %.3f (change %+.3f); voting amplifies a wrong majority" % (
             base["tier_acc"]["biased"], v5["tier_acc"]["biased"], acc_gain_biased)},
        {"case": "Accuracy plateaus beyond N=5",
         "verdict": vd(h3, acc_gain_v9 <= 0.02),
         "evidence": "overall acc N=5 %.3f vs N=9 %.3f (gain %+.3f)" % (
             v5["accuracy"], results["vote N=9"]["accuracy"], acc_gain_v9)},
    ]

    names = list(results.keys())
    verdict = ("Voting sharply reduces flakiness (N=5 flip-rate cut %.0f%%) but cannot fix bias-driven "
               "errors; adaptive re-sampling %s the 90%%-stability-at-<60%%-cost target in this simulation." % (
                   100 * flip_cut_v5, "met" if h2 else "did not meet"))
    return {
        "verdict": verdict,
        "summary": {
            "flip_cut_vote5_pct": round(100 * flip_cut_v5, 2),
            "flip_cut_adaptive_pct": round(100 * flip_cut_ad, 2),
            "adaptive_stability_ratio": round(stab_ratio, 3),
            "adaptive_call_ratio": round(cost_ratio, 3),
            "accuracy_single": round(base["accuracy"], 4),
            "accuracy_vote5": round(v5["accuracy"], 4),
            "biased_tier_acc_vote5": round(v5["tier_acc"]["biased"], 4),
        },
        "outcomes": outcomes,
        "chart": {
            "title": "Flip rate vs judge calls per case",
            "ylabel": "case flip rate across reruns",
            "labels": names,
            "series": {"flip_rate": [round(results[n]["flip_rate"], 4) for n in names],
                       "accuracy": [round(results[n]["accuracy"], 4) for n in names]},
        },
        "table": {
            "columns": ["strategy", "flip_rate", "accuracy", "calls_per_case",
                        "acc_easy", "acc_borderline", "acc_hard", "acc_biased"],
            "rows": [[n, round(results[n]["flip_rate"], 4), round(results[n]["accuracy"], 4),
                      round(results[n]["calls_per_case"], 2),
                      round(results[n]["tier_acc"]["easy"], 3),
                      round(results[n]["tier_acc"]["borderline"], 3),
                      round(results[n]["tier_acc"]["hard"], 3),
                      round(results[n]["tier_acc"]["biased"], 3)] for n in names],
        },
        "notes": [
            "The judge is a seeded deterministic STUB, not a real LLM; probabilities are assumptions.",
            "Judge calls are assumed independent; real samples at temperature>0 share prompt-level bias and correlate, so real gains are likely smaller.",
            "Tier mix and p_correct values are fixed up front and not tuned; conclusions depend on them.",
            "Flip rate counts a case as flaky if any of %d reruns disagrees, so it is sensitive to rerun count." % N_RERUNS,
            "Adaptive escalates only when the first 3 votes disagree; confident-but-wrong verdicts are never re-checked.",
        ],
    }


def main():
    cases, results = run_all()
    report = build_report(cases, results)
    with open("results.json", "w") as f:
        json.dump(report, f, indent=2)
    print(report["verdict"])
    for row in report["table"]["rows"]:
        print(row)


if __name__ == "__main__":
    main()
