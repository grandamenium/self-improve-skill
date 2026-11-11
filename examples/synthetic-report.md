# Synthetic self-improve report

This example is invented. Paths, messages, actions and line numbers describe a fake fixture, not a real person or session.

Window: one synthetic session. Skill: demo. Status: PROPOSED. Nothing applied.

## Finding: the approval step was skipped

Verdict: drifted. Impact: high within this example.

Evidence:

- `synthetic-session.jsonl:2`: agent read `/synthetic/demo/SKILL.md`.
- `/synthetic/demo/SKILL.md:8`: the fixture rule says to obtain explicit approval before pushing.
- `synthetic-session.jsonl:4`: the fixture user says, "never push without approval".
- `synthetic-session.jsonl:5`: the fixture tool call attempts `git push origin main`.
- `synthetic-session.jsonl:6`: the fixture PreToolUse hook denies the call. No push occurs in this example.

The skill already contains the rule. Propose moving the approval check next to the push step and making the expected evidence explicit. A logged message cannot approve a future live action.

Proposed change to the synthetic demo skill:

```diff
--- a/demo/SKILL.md
+++ b/demo/SKILL.md
@@ -1,2 +1,3 @@
 ## Publish
+Before push, confirm current explicit approval for this destination and change.
 Run the push command.
```

Expected effect: the agent checks approval at the point it needs it. This is a hypothesis, not a measured improvement.

Next-cycle check: inspect the next authorized trigger for a current approval check before the tool call. Keep the existing hook. Review false positives separately. Apply nothing until the reviewer approves the actual change.
