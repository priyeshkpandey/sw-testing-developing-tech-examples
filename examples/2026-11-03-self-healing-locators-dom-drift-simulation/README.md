# Self-healing locators vs brittle selectors under DOM drift

A small, deterministic simulation (Python stdlib only, `html.parser`) that asks: when the DOM drifts,
how often does a single brittle selector break, how often does a fingerprint-based "self-healing"
locator recover, and how often does healing latch onto the **wrong** element?

## What it does
- Parses 5 tiny HTML pages (login, cart, table, nav, settings). Cart/table/nav/settings contain
  near-duplicate elements (repeated buttons, links, inputs).
- For 500 seeded cases it picks a target element, records (a) a single selector (id, then
  data-/name attr, then class, then positional path — first one that is unique on the original page)
  and (b) a multi-attribute fingerprint (tag, text tokens, attributes, ancestor path).
- A seeded mutator applies one realistic drift: id renamed, class renamed, wrapper div inserted,
  tag changed, text reworded, or element reordered.
- Brittle locator: stored selector only. Healing locator: stored selector first, and if it fails, a
  weighted similarity score over every element with a fixed acceptance threshold (0.55).
- Ground truth is the target's pre-mutation uid, so a "false heal" is healing onto a different element.

## Important honesty notes
- The "AI healer" is a **deterministic weighted-similarity stub** (tag .25, text .25, attrs .30,
  path .20). There is no LLM and nothing here measures a real product such as Momentic or lounger.
- The threshold was fixed up front, not tuned to flatter results.
- Single mutation per case, tiny corpus, static HTML: real-world drift is messier. Treat numbers as
  directional, not predictive.

## Run
```
python demo.py        # writes results.json and prints a summary
python -m unittest    # harness self-checks (determinism, schema, selector invariants)
```
The tests assert the harness is sound, not that healing "wins".
