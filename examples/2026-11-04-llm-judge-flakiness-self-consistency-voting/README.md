# Flaky verdicts: self-consistency voting vs single-shot LLM-as-judge

## What
A simulation of the flakiness SDETs see when an LLM-as-judge assertion (promptfoo-style)
gates a CI pipeline. It compares:

- single-shot judge (N=1)
- majority vote with N=3, 5, 9
- an adaptive strategy: 3 calls, re-sample up to 5 total only when they disagree

Metrics: per-case verdict flip rate across 200 reruns (flakiness), accuracy vs
ground-truth labels (overall and per difficulty tier), and judge calls per case (cost).

## Important: the judge is a stub
There is **no real LLM** here. The judge is a seeded, deterministic random stub. Each case has a
probability of a correct verdict set by its tier (easy 0.95, borderline 0.65, hard 0.55, and
"biased" 0.30, where a verbosity/position-style bias makes the judge more likely wrong than right).
Those numbers are assumptions chosen up front and not tuned to flatter voting.

## Run
```
python demo.py          # writes results.json and prints a table
python -m unittest      # harness sanity tests (determinism, cost accounting, schema)
```
Stdlib only, runs in a few seconds.

## What to look for
- Does voting cut the flip rate a lot? (Usually yes, since averaging cancels symmetric noise.)
- Does adaptive match fixed N=5 stability at lower cost?
- Does voting help the "biased" tier? It should not: if p_correct < 0.5, a bigger majority
  is *more* reliably wrong. The residual error after voting is bias, not noise.

## Honest limitations
- Independence between judge samples is assumed. Real LLM samples are correlated, so real
  gains from voting are likely smaller.
- Adaptive never re-checks unanimous-but-wrong verdicts.
- Conclusions depend on the assumed tier mix and probabilities; the tests assert only that the
  harness is sound, not that the technique wins.
