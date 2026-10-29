# Hybrid code review: rules + simulated LLM triage vs either alone

Inspired by the hybrid architecture of alibaba/open-code-review (deterministic
pipelines plus an LLM agent). This is a small, seeded, stdlib-only experiment.

**Important:** the "LLM" is a clearly labelled deterministic **stub** with fixed,
seeded error rates. It is not a real model. The experiment shows architecture
trade-offs (precision, recall, cost), not any model's quality.

## What it does
- Generates 200 seeded Python snippets: defects (SQL string concatenation,
  `eval`, `pickle.loads`, missing None check, shared mutable state without a
  lock) plus benign look-alikes (parameterised SQL, constant concatenation,
  `ast.literal_eval`, guarded None, locked state).
- Compares three reviewers:
  - **A. rules-only**: naive AST/regex rules. Deliberately has no rule for
    missing locks, and its None rule ignores guards.
  - **B. LLM-only (stub)**: flags each snippet with fixed rates (high recall,
    ~20% false positives on benign code).
  - **C. hybrid**: rules nominate candidates, the stub only confirms or rejects them.
- Reports precision, recall, F1, false positives and simulated LLM calls.

## Run
```
python demo.py        # writes results.json
python -m unittest    # harness sanity tests (not "does the technique win")
```

## Honest caveats
- Error rates are fixed constants chosen up front, not tuned; other values can flip conclusions.
- Hybrid recall is capped by what the rules nominate, so defect classes without a rule are lost.
- The hybrid's confirm step can also discard true candidates.
- The corpus is small and templated; real code is messier.
- "LLM calls" is a crude cost proxy; real cost scales with tokens.
