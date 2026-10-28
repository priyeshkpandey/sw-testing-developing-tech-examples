# Coverage vs mutation score on LLM-style generated code

**Question:** if a happy-path test suite gives 100% line coverage on plausible
"LLM-written" functions, how many injected faults does it actually catch?

**Important:** the functions are hand-written imitations of typical generated
code. There is **no real LLM** here, and nothing is a model output.

## What it does
- 6 small subject functions (discount tiers, clamp, leap year, pagination,
  grading, counting).
- Mutants are generated with `ast`: comparison swaps (`>=` to `>`), arithmetic
  swaps, int constant +1, and bool flips.
- Three suites: `happy_path` (one comfortable input per branch),
  `boundary` (adds boundary-value examples) and `boundary+property`
  (adds a property-style check per function).
- Line and approximate branch coverage via `sys.settrace`.
- Mutation score = killed / total mutants (equivalent mutants not filtered).

## Run
```
python demo.py        # writes results.json
python -m unittest    # harness soundness tests only
```

## Harness fix
An earlier version aborted with `suite fails on original discount`. The
harness now checks each suite against both the original and an independent
reference implementation at startup and prints exactly which example
mismatched. The experiment itself (suites, mutants, metrics) is unchanged.

## Honest limitations
- Tiny, hand-picked sample; the hypothesis thresholds were fixed beforehand and
  not tuned.
- Property checks are written with knowledge of the spec, which flatters the
  augmented suite.
- Some surviving mutants may be equivalent, so 100% is unreachable.
- Branch coverage is approximated from line events.
- Tests assert harness soundness, not that the technique wins.
