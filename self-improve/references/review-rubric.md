# Review rubric

## Trigger verdicts

| Verdict | Meaning | Typical evidence |
|---|---|---|
| followed | Agent did what the skill says and it worked | Relevant actions and results satisfy the rule; silence alone is insufficient |
| drifted | Agent skipped or bent a step the skill states | Human says "you have a skill for this", "like the skill says"; agent later admits the rule was there |
| skill-caused | Agent followed the skill and the skill was wrong, stale or ambiguous | Human corrects behaviour that matches the skill text |
| not reached | The rule exists but the agent never read that part | Chunked `sed -n a,bp` reads that skip the rule's lines; a grep for the wrong word; a delegation brief that paraphrased the skill |
| missing | No rule covers the situation | Human states a new rule; agent improvises |

"Not reached" is usually a structure problem, not an obedience problem. Fix it by moving the rule up, splitting
the file, or turning the rule into a checked step, not by adding emphasis.

## Drift patterns worth naming

- **Status as proof:** the agent reports done on a proxy (`compiled: true`, HTTP 200, a cron created) instead of
  the outcome the skill defines (a real DM sent, a calendar row visible).
- **Two places, one updated:** the rule lives in two skills or a skill and a memory file, and only one copy changed.
- **Fix by append:** after a correction the agent adds another dated MANDATORY block to the end of a long file.
  Check whether the new block duplicates an existing rule that was simply not reached.
- **Brief drift:** a coordinator paraphrases the skill into a worker brief and drops a gate.
- **No exit condition:** a poll or tick cron with no stop rule keeps firing after the goal is met.

## Where each correction should land

| The correction is about | Put it in | Why |
|---|---|---|
| How to do one job (steps, gates, templates) | That skill's SKILL.md, or a reference file it points to | Loads only when the job runs |
| Behaviour across all work (tone, approvals, safety) | CLAUDE.md / AGENTS.md / GUARDRAILS | Loads every session; keep it short |
| Something that must never happen regardless of judgement | A hook (PreToolUse) or a script check, plus one line in the rules file | Rules files are context, not enforcement (code.claude.com/docs/en/memory) |
| A fact or preference about the person or project | Memory (one index line plus a topic file) | Not an instruction |
| A one-off ("not now", "wait for the next video") | Nothing | Not a standing rule |

Before proposing a new rule, search the current skill, rules files and memory for an existing one. If it
exists, the finding is "not reached" or "drifted", and the diff should move or enforce it, not repeat it.

## Re-asks

The same request twice within a session (the script flags messages over 80% similar) can indicate that the first answer
did not satisfy. Read both turns: was the agent slow, wrong, or did it answer a different question?
