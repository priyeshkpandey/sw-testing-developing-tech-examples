# Attempt log

The model's raw reply for each attempt is in `attempt_N_reply.txt`; any code it produced is in this folder.

## Attempt 1
```
demo.py exit 1:
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 1
    ```python
    ^
SyntaxError: invalid syntax

```

## Attempt 2
```
demo.py exit 1:
Traceback (most recent call last):
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 403, in <module>
    main()
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 312, in main
    per[sname][fname] = evaluate(fname, src, ex, pr)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 279, in evaluate
    assert run_suite(original, examples, prop), f"suite fails on original {name}"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: suite fails on original discount

```

## Attempt 3
```
demo.py exit 1:
Traceback (most recent call last):
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 540, in <module>
    main()
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 442, in main
    per[sname][fname] = evaluate(fname, src, ex, pr)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/sw-test-patreon-linkedin-poster/sw-test-patreon-linkedin-poster/work/demo/coverage-vs-mutation-score-llm-generated-code/demo.py", line 406, in evaluate
    raise AssertionError(
AssertionError: suite fails on original discount: mismatches=[((10.0, 9), 72.0, 81.0)] prop_ok=None

```