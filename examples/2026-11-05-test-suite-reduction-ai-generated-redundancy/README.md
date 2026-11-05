# Test-suite reduction on redundant AI-generated tests

## What this does
Simulates an "LLM-style" test generator and compares four reduction strategies
on a small redundant suite:

| strategy | idea |
|---|---|
| `no_reduction` | baseline |
| `exact_dedup` | drop tests with identical (subject, args) |
| `coverage_greedy` | greedy set cover preserving line + branch coverage |
| `mutation_greedy` | greedy set cover preserving killed mutants (then topping up coverage) |

Metrics: suite size, line/branch coverage retained, mutants killed.

## Important honesty notes
- **The generator is a deterministic stub, not a real LLM.** Its redundancy
  pattern (many typical-value paraphrases, a few boundary tests, deliberate gaps)
  is my own design and largely determines the outcome.
- 4 tiny functions, 15 hand-written mutants (one deliberately equivalent),
  one seed. Numbers are illustrative, not statistically meaningful.
- Some mutants survive even the full suite (generator gaps such as no `score == 70`
  or `total == 1000` test). Mutation score is killed/all, so those cap it.
- Greedy set cover is a heuristic, not minimal.
- `mutation_greedy` also adds tests to keep full line/branch coverage.
- The hypothesis (60-80% reduction, >=10 pp mutant loss for coverage-greedy,
  100% retention for mutation-greedy) is evaluated, not assumed: see the last
  note in `results.json` for which parts held. No parameters were tuned
  after seeing results.

## Run
```
python demo.py          # writes results.json in cwd
python -m unittest -v   # harness soundness checks (not "technique works")
```
Python stdlib only, no network, runs in a few seconds.

## Reading results
`results.json` holds the verdict, per-strategy table, chart data and
per-case outcomes, including the failures (mutants lost by coverage-only
reduction; mutants no subset can kill).
