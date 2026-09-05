# Controlled Bounded Native-Output Experiment

**Date:** 2026-09-05  
**Fixed revision:** `f6d5daad10f265f4478dc9ba504e321f836d231f` (`docs: analyze bounded Codex output strategy`)  
**Model / reasoning:** `gpt-5.6-terra` / `low`  
**Scope:** Read-only repository operations. The only repository write was this results artifact.

## Method

Each arm was run independently. “Captured command stream” is the command's actual stdout/stderr, retained for measurement. “Exposed” is what the arm would present to the operator: all captured output for A, and the bounded lookup/read or compact summary for B. Durations are wall-clock measurements around the command(s), so they include negligible shell setup and should not be used for fine performance comparisons.

| Operation | Arm | Exact command(s) | Captured stdout (lines / bytes) | Captured stderr (lines / bytes) | Exposed (lines / bytes) | Extra retrieval / inspection turns | Evidence sufficient? | Diagnosis correct? | Elapsed |
|---|---|---|---:|---:|---:|---:|---|---|---:|
| Locate a documented bounded-output concept | A | `rg -n -i 'bounded output' .` | 2 / 201 | 0 / 0 | 2 / 201 | 0 | Yes: both matching locations were visible. | n/a | 10.33 ms |
| Locate a documented bounded-output concept | B | `rg -n -m 1 -i 'bounded output' docs/research/bounded-output-context-analysis.md`<br>`sed -n '1,12p' docs/research/bounded-output-context-analysis.md` | 13 / 1,258 | 0 / 0 | 13 / 1,258 | 1 | Yes: the selected document's recommendation was visible. | n/a | 10.74 ms |
| Inspect latest commit | A | `git show HEAD` | 154 / 13,547 | 0 / 0 | 154 / 13,547 | 0 | Yes: complete commit and diff were visible. | n/a | 7.75 ms |
| Inspect latest commit | B | `git show --stat --oneline HEAD`<br>`git show --format= -U0 HEAD -- docs/research/bounded-output-context-analysis.md \| sed -n '1,24p'` | 27 / 2,088 | 0 / 0 | 27 / 2,088 | 1 | Yes: identity, changed path, size, and opening hunk were visible. | n/a | 9.41 ms |
| Required full validation | A | `.venv/bin/python3 -m unittest discover -s tests -q` | 41 / 997 | 4 / 99 | 45 / 1,096 | 0 | Yes: `Ran 101 tests` and `OK` were visible. | n/a | 7.264 s |
| Required full validation | B | `.venv/bin/python3 -m unittest discover -s tests -q` (complete stdout/stderr captured); exposed summary: command, exit code, duration, test count, `OK` | 41 / 997 | 4 / 99 | 5 / 125 | 0 | Yes: exit `0`, 101 tests, and `OK` were visible. | n/a | 7.942 s |
| Deliberate safe failure | A | `.venv/bin/python3 -m unittest discover -s tests/nonexistent -q` | 0 / 0 | 21 / 1,121 | 21 / 1,121 | 0 | Yes: full traceback was visible. | Yes. | 65.60 ms |
| Deliberate safe failure | B | `.venv/bin/python3 -m unittest discover -s tests/nonexistent -q` (complete stderr retained); initial exposed summary: `exit code 1; ImportError: Start directory is not importable: 'tests/nonexistent'` | 0 / 0 | 21 / 1,121 | 1 / 98 | 0 | Yes: final exception states the root cause; no expansion was needed. | Yes. | 61.52 ms |

## Measured reduction by operation

| Operation | A exposed | B exposed | Change |
|---|---:|---:|---:|
| Locate concept | 2 lines / 201 bytes | 13 lines / 1,258 bytes | **Increase:** 11 lines / 1,057 bytes (525.9%) |
| Inspect latest commit | 154 lines / 13,547 bytes | 27 lines / 2,088 bytes | **Reduction:** 127 lines / 11,459 bytes (84.6%) |
| Required full validation | 45 lines / 1,096 bytes | 5 lines / 125 bytes | **Reduction:** 40 lines / 971 bytes (88.6%) |
| Deliberate failure | 21 lines / 1,121 bytes | 1 line / 98 bytes | **Reduction:** 20 lines / 1,023 bytes (91.3%) |

## Evidence, diagnosis, and limitations

No required evidence was lost in any bounded arm. The bounded research lookup and commit inspection each required one additional retrieval/read; validation and failure diagnosis required none. The failure diagnosis was correct: `unittest` rejected `tests/nonexistent` because it is not an importable discovery start directory. The complete bounded failure stderr was retained until that conclusion was reached.

The small research search is an important counterexample: the native broad search happened to return only two terse hits, whereas the bounded arm intentionally added twelve lines of context and therefore exposed more output. The commit was a single new 142-line file, so a path-scoped diff alone would still be large; the bounded arm needed an explicit hunk/read limit. Validation elapsed time varied between independent runs and is not evidence of a performance change. This experiment does not measure tokens, billing, quota, or weekly limits, and it does not truncate authoritative review or acceptance evidence.

## Recommendation

**REFINE_AND_REPEAT**. Native bounded discipline substantially reduced output for the complete diff, validation success, and a traceback while retaining the needed conclusion. Repeat with a larger and noisier documentation corpus, tune the lookup/context window so sparse searches do not grow, and include a multi-file change before adopting it as a general default.

RTK is **not justified as the next experiment**: the observed behavior can be refined with native commands and explicit output discipline first. Low reasoning was sufficient for this controlled execution; escalation to medium was not needed.
