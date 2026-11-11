# Report template

One file per cycle, one section per skill. Keep it private to the owner.

````markdown
# Self-improve report: <agent>, <date>

Window: <from> to <to>. Transcripts: <N files, paths>. Skills: <list with trigger counts>.
Status: PROPOSED. Nothing applied.

## Top findings (ranked)
1. <one line each, with skill and expected effect>

## <skill name> (<N> triggers; SKILL.md <lines> lines, description <chars> chars)

Verdicts: followed <n>, drifted <n>, skill-caused <n>, not reached <n>, missing <n>.

### F1. <short title> (<verdict>; impact high|med|low)
Evidence:
- `<transcript>:<line>` <short quote or action>
- `<skill path>:<line>` <the rule as written now>
What happened: <two or three sentences>
Proposed change (target: <file>):
```diff
- old
+ new
```
Expected effect: <what stops happening, what it costs>
Check next cycle: <the signal that shows it worked, e.g. zero chunked reads, no "you have a skill" correction>

## Rules files and memory
## Hooks (right / wrong / missing)
## Token and context
## Not changed, and why
## Apply plan (needs approval)
- <change> via <branch/PR | reviewed skill update | local file>, owner: <who approves>
````

Use unified diffs with file headers and context that can be checked with `git apply --check`, or for large moves describe the move ("move lines 228-268 to
references/pre-live-gate.md and leave a 3-line pointer") and show the pointer text.
