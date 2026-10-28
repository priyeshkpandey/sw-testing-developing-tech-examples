# Do coverage criteria catch LLM-style bugs? (mutation score vs coverage)

## What it does
A tiny corpus of 11 Python functions, each with a correct reference and a buggy variant
imitating common LLM mistakes: off-by-one, missing edge guard, wrong boundary operator,
swapped arguments, None handling. One entry is a behaviourally equivalent "bug" (`>` vs `>=`
in `abs_diff`) to show what no test can catch.

Each function gets three suites: a happy-path suite, a branch-coverage-driven suite, and a
boundary-value suite plus seeded random (`random.Random(1234)`) property-style inputs.
Expected values come from the reference implementation (oracle).

We measure line coverage (`sys.settrace`), branch coverage (AST instrumentation of decisions),
a hand-rolled AST mutation score (comparison flips, arithmetic swaps, int constant +1) on the
reference, and the direct detection rate of the injected bugs.

## Important honesty notes
- **No LLM is used.** Bugs and "LLM-style" suites are deterministic hand-written stubs.
- The corpus is tiny and the boundary suites were authored knowing the bug classes, so this
  illustrates the mechanism rather than proving anything about real LLM output.
- Results are reported as measured; nothing was tuned toward the hypothesis.

## Run
```
python demo.py        # writes results.json
python -m unittest -v # harness self-checks (not technique success)
```
Python stdlib only, deterministic, runs in well under a second.
