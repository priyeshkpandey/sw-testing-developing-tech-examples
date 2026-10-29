"""Hybrid code review experiment: deterministic rules vs SIMULATED LLM vs hybrid.

The 'LLM' here is a deterministic, seeded STUB with fixed error rates. It is
NOT a real model. The experiment shows architecture trade-offs, not model quality.
Stdlib only, deterministic, no network.
"""
import ast
import hashlib
import json
import random
import re

SEED = 1234
N_SNIPPETS = 200

# Fixed (not tuned) mock-LLM error rates.
LLM_RECALL_OBVIOUS = 0.90      # P(flag | obvious defect)
LLM_RECALL_CONTEXT = 0.85      # P(flag | context-dependent defect)
LLM_FP_BENIGN = 0.20           # P(flag | benign snippet)
LLM_CONFIRM_TRUE_CAND = 0.88   # P(confirm | rule candidate that is a real defect)
LLM_CONFIRM_FALSE_CAND = 0.30  # P(confirm | rule candidate that is benign)


def build_corpus(rng):
    """Return a list of snippets: {id, code, defect (bool), kind, subtype}.

    subtype 'obvious' = syntactically recognisable; 'context' = semantic,
    rules are not expected to see it. Benign look-alikes can trip naive rules.
    """
    corpus = []

    def add(code, defect, kind, subtype):
        corpus.append({"id": len(corpus), "code": code, "defect": defect,
                       "kind": kind, "subtype": subtype})

    n = 0
    while len(corpus) < N_SNIPPETS:
        v = "v%d" % n
        n += 1
        choice = rng.choice([
            "sql_bad", "sql_ok", "sql_ok_const", "eval_bad", "eval_ok",
            "pickle_bad", "pickle_ok", "none_bad", "none_ok",
            "shared_bad", "shared_ok", "plain",
        ])
        if choice == "sql_bad":
            add("def q_%s(cur, name):\n    cur.execute(\"SELECT * FROM t WHERE n='\" + name + \"'\")\n" % v,
                True, "sql_concat", "obvious")
        elif choice == "sql_ok":
            add("def q_%s(cur, name):\n    cur.execute(\"SELECT * FROM t WHERE n=?\", (name,))\n" % v,
                False, "sql_concat", "benign")
        elif choice == "sql_ok_const":
            # concatenation of constants only: lookalike, not injectable
            add("def q_%s(cur):\n    cur.execute(\"SELECT * \" + \"FROM t\")\n" % v,
                False, "sql_concat", "benign")
        elif choice == "eval_bad":
            add("def e_%s(s):\n    return eval(s)\n" % v, True, "unsafe_eval", "obvious")
        elif choice == "eval_ok":
            add("def e_%s():\n    import ast\n    return ast.literal_eval('[1, 2]')\n" % v,
                False, "unsafe_eval", "benign")
        elif choice == "pickle_bad":
            add("import pickle\ndef p_%s(b):\n    return pickle.loads(b)\n" % v,
                True, "unsafe_pickle", "obvious")
        elif choice == "pickle_ok":
            add("import json\ndef p_%s(b):\n    return json.loads(b)\n" % v,
                False, "unsafe_pickle", "benign")
        elif choice == "none_bad":
            # missing None check: dict.get result dereferenced -> context-dependent
            add("def n_%s(d):\n    u = d.get('user')\n    return u.name\n" % v,
                True, "missing_none_check", "context")
        elif choice == "none_ok":
            add("def n_%s(d):\n    u = d.get('user')\n    if u is None:\n        return ''\n    return u.name\n" % v,
                False, "missing_none_check", "benign")
        elif choice == "shared_bad":
            # shared mutable state mutated from threaded code without lock -> context
            add("import threading\nCOUNT = {'n': 0}\ndef s_%s():\n    COUNT['n'] += 1\n"
                "t = threading.Thread(target=s_%s)\n" % (v, v),
                True, "shared_state_no_lock", "context")
        elif choice == "shared_ok":
            add("import threading\nLOCK = threading.Lock()\nCOUNT = {'n': 0}\ndef s_%s():\n"
                "    with LOCK:\n        COUNT['n'] += 1\n"
                "t = threading.Thread(target=s_%s)\n" % (v, v),
                False, "shared_state_no_lock", "benign")
        else:
            add("def f_%s(a, b):\n    return a + b\n" % v, False, "none", "benign")
    return corpus[:N_SNIPPETS]


# ---------------- (A) deterministic rules ----------------
def _is_const_str_concat(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_const_str_concat(node.left) and _is_const_str_concat(node.right)
    return False


def rule_candidates(code):
    """Return set of rule-kind strings flagged. Intentionally simple/naive."""
    found = set()
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "eval":
                found.add("unsafe_eval")
            if (isinstance(f, ast.Attribute) and f.attr in ("loads", "load")
                    and isinstance(f.value, ast.Name) and f.value.id == "pickle"):
                found.add("unsafe_pickle")
            if isinstance(f, ast.Attribute) and f.attr == "execute" and node.args:
                a = node.args[0]
                # naive: any '+' concatenation in execute() arg, even constants
                if isinstance(a, ast.BinOp) and isinstance(a.op, ast.Add):
                    found.add("sql_concat")
    # naive regex rule for None: attribute access on a var assigned from .get(...)
    # (does NOT understand guards, so it over-flags guarded code).
    m = re.search(r"(\w+)\s*=\s*\w+\.get\(", code)
    if m and re.search(r"\b%s\.\w+" % re.escape(m.group(1)), code):
        found.add("missing_none_check")
    # shared-state-with-lock is semantic; no rule is written for it (known gap).
    return found


def run_rules(corpus):
    preds, calls = {}, 0
    for s in corpus:
        preds[s["id"]] = bool(rule_candidates(s["code"]))
    return preds, calls


# ---------------- (B) mock LLM (stub) ----------------
def _u(snippet_id, salt):
    h = hashlib.sha256(("%d:%s:%d" % (SEED, salt, snippet_id)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def mock_llm_flag(s):
    if s["defect"]:
        p = LLM_RECALL_OBVIOUS if s["subtype"] == "obvious" else LLM_RECALL_CONTEXT
    else:
        p = LLM_FP_BENIGN
    return _u(s["id"], "flag") < p


def run_llm_only(corpus):
    preds = {s["id"]: mock_llm_flag(s) for s in corpus}
    return preds, len(corpus)  # one call per snippet


# ---------------- (C) hybrid ----------------
def mock_llm_confirm(s):
    p = LLM_CONFIRM_TRUE_CAND if s["defect"] else LLM_CONFIRM_FALSE_CAND
    return _u(s["id"], "confirm") < p


def run_hybrid(corpus):
    preds, calls = {}, 0
    for s in corpus:
        if rule_candidates(s["code"]):
            calls += 1
            preds[s["id"]] = mock_llm_confirm(s)
        else:
            preds[s["id"]] = False
    return preds, calls


# ---------------- metrics ----------------
def metrics(corpus, preds):
    tp = sum(1 for s in corpus if s["defect"] and preds[s["id"]])
    fp = sum(1 for s in corpus if not s["defect"] and preds[s["id"]])
    fn = sum(1 for s in corpus if s["defect"] and not preds[s["id"]])
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def per_kind_recall(corpus, preds):
    out = {}
    for s in corpus:
        if not s["defect"]:
            continue
        d = out.setdefault(s["kind"], [0, 0])
        d[1] += 1
        d[0] += 1 if preds[s["id"]] else 0
    return out


def verdict_for(ok):
    return "worked" if ok else "failed"


def run():
    rng = random.Random(SEED)
    corpus = build_corpus(rng)
    n_def = sum(1 for s in corpus if s["defect"])

    a_preds, a_calls = run_rules(corpus)
    b_preds, b_calls = run_llm_only(corpus)
    c_preds, c_calls = run_hybrid(corpus)
    ma, mb, mc = metrics(corpus, a_preds), metrics(corpus, b_preds), metrics(corpus, c_preds)

    ratio = b_calls / c_calls if c_calls else float("inf")
    best_f1 = max(("rules", ma["f1"]), ("llm_only", mb["f1"]), ("hybrid", mc["f1"]),
                  key=lambda x: x[1])[0]

    kr_a = per_kind_recall(corpus, a_preds)
    kr_c = per_kind_recall(corpus, c_preds)
    shared_a = kr_a.get("shared_state_no_lock", [0, 0])
    shared_c = kr_c.get("shared_state_no_lock", [0, 0])

    h1 = mc["precision"] > mb["precision"]
    h2 = mc["recall"] > ma["recall"]
    h3 = best_f1 == "hybrid"
    h4 = ratio >= 5
    # Honest check: hybrid recall can never exceed rule candidate recall.
    cand_recall = ma["recall"]
    hybrid_below_llm_recall = mc["recall"] < mb["recall"]

    outcomes = [
        {"case": "Hybrid precision > LLM-only precision",
         "verdict": verdict_for(h1),
         "evidence": "hybrid %.3f vs llm_only %.3f" % (mc["precision"], mb["precision"])},
        {"case": "Hybrid recall > rules-only recall",
         "verdict": verdict_for(h2),
         "evidence": "hybrid %.3f vs rules %.3f (LLM confirm step can DROP true candidates)"
                     % (mc["recall"], ma["recall"])},
        {"case": "Hybrid has best F1 of three",
         "verdict": verdict_for(h3),
         "evidence": "F1 rules %.3f, llm_only %.3f, hybrid %.3f; best=%s"
                     % (ma["f1"], mb["f1"], mc["f1"], best_f1)},
        {"case": "Hybrid uses >=5x fewer LLM calls than LLM-only",
         "verdict": verdict_for(h4),
         "evidence": "llm_only %d calls vs hybrid %d calls (%.2fx)" % (b_calls, c_calls, ratio)},
        {"case": "Shared-state-without-lock defects (no rule exists)",
         "verdict": "failed",
         "evidence": "rules caught %d/%d, hybrid caught %d/%d: hybrid cannot see what rules "
                     "never nominate" % (shared_a[0], shared_a[1], shared_c[0], shared_c[1])},
        {"case": "Hybrid recall vs LLM-only recall",
         "verdict": "failed" if hybrid_below_llm_recall else "partial",
         "evidence": "hybrid %.3f vs llm_only %.3f; recall is capped by rule candidate recall %.3f"
                     % (mc["recall"], mb["recall"], cand_recall)},
    ]

    if h1 and h2 and h3 and h4:
        verdict = ("Hybrid beat both baselines on F1 and cost in this simulation, but its recall is "
                   "capped by what the rules nominate, so unruled defect classes stay missed.")
    else:
        verdict = ("Hypothesis only partly held in this simulation (see outcomes); the hybrid's "
                   "recall is capped by rule candidates and its gains depend on the stub's fixed error rates.")

    results = {
        "verdict": verdict,
        "summary": {
            "snippets": len(corpus), "defects": n_def,
            "rules_precision": ma["precision"], "rules_recall": ma["recall"], "rules_f1": ma["f1"],
            "rules_fp": ma["fp"], "rules_llm_calls": a_calls,
            "llm_precision": mb["precision"], "llm_recall": mb["recall"], "llm_f1": mb["f1"],
            "llm_fp": mb["fp"], "llm_llm_calls": b_calls,
            "hybrid_precision": mc["precision"], "hybrid_recall": mc["recall"], "hybrid_f1": mc["f1"],
            "hybrid_fp": mc["fp"], "hybrid_llm_calls": c_calls,
            "call_reduction_x": round(ratio, 2),
        },
        "outcomes": outcomes,
        "chart": {
            "title": "Precision / Recall / F1 by reviewer (simulated LLM)",
            "ylabel": "score (0-1)",
            "labels": ["rules-only", "LLM-only (stub)", "hybrid"],
            "series": {
                "precision": [ma["precision"], mb["precision"], mc["precision"]],
                "recall": [ma["recall"], mb["recall"], mc["recall"]],
                "f1": [ma["f1"], mb["f1"], mc["f1"]],
            },
        },
        "table": {
            "columns": ["reviewer", "precision", "recall", "f1", "false_positives", "false_negatives", "llm_calls"],
            "rows": [
                ["rules-only", ma["precision"], ma["recall"], ma["f1"], ma["fp"], ma["fn"], a_calls],
                ["LLM-only (stub)", mb["precision"], mb["recall"], mb["f1"], mb["fp"], mb["fn"], b_calls],
                ["hybrid", mc["precision"], mc["recall"], mc["f1"], mc["fp"], mc["fn"], c_calls],
            ],
        },
        "notes": [
            "The LLM is a deterministic seeded STUB with fixed rates; results show architecture trade-offs, not any real model's quality.",
            "Error rates and corpus mix were fixed up front and not tuned; different rates can flip the conclusions.",
            "The synthetic corpus is tiny and templated; real code is far messier and rule false-positive rates differ.",
            "Mock LLM outcomes are independent per snippet; real LLMs correlate errors with code style and context.",
            "Hybrid recall cannot exceed rule candidate recall: defect classes without a rule (e.g. missing locks) are never triaged.",
            "LLM calls are a crude cost proxy (1 per reviewed snippet); real cost scales with tokens, not calls.",
        ],
    }
    return results


def main():
    results = run()
    with open("results.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print(json.dumps(results["summary"], indent=2))
    print(results["verdict"])


if __name__ == "__main__":
    main()
