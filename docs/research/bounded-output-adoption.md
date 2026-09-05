# Bounded Native-Output Discipline Adoption

## Change

`AGENTS.md` now makes targeted, bounded native inspection the default when output may be large; it retains already-small output, stages Git/diff and file inspection, summarizes successful validation with command/result evidence, and expands failure diagnostics only until the cause is established. It preserves complete authoritative review/acceptance evidence and material diagnostics.

## Basis

The context analysis recommended native bounded-output discipline first. Experiment 1 established the need to retain small initial output and avoid truncating evidence material to diagnosis; Experiment 2 validated the refined behavior across noisy search and multi-file history, retained required evidence, and concluded `ADOPT_NATIVE_DISCIPLINE`.

## Deliberate non-changes

No RTK, wrapper, helper, script, configuration, Skill change, or workflow contract was introduced. Future tooling or RTK work is not justified by the current evidence; reconsider only if measurements show native discipline is repeatedly insufficient.
