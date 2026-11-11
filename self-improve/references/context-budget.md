# Context budget

These are review guidelines, not evidence that a shorter file always performs better. Confirm a missed rule in the transcript before changing the skill. Official pages were checked 2026-11-11; recheck them when updating the kit.

## Skills

[Anthropic's authoring guide](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) recommends a skill body below 500 lines, moving detail into directly linked references, and a contents list for references above 100 lines. It limits skill names to 64 characters and descriptions to 1,024 characters. Names use lowercase letters, digits and hyphens. Descriptions should explain purpose and triggering situations in third person.

The guide also recommends testing real usage, investigating repeated or missed reference reads, and executing scripts to avoid loading their full source into context. These are starting points for review. A partial read alone doesn't prove an instruction was skipped.

## Rules and memory

[Claude Code memory docs](https://code.claude.com/docs/en/memory) recommend CLAUDE.md files below 200 lines. Imports improve organization but still consume context. Auto-memory loads the first 200 lines or 25KB of MEMORY.md at session start, whichever limit comes first. Detail belongs in topic files read when needed.

Those auto-memory loading limits don't automatically apply to a custom MEMORY.md or another harness. Identify the file's actual loader before assigning a truncation finding. Guidance files influence model behavior; enforcement requires an appropriate hook or check.

## What to inspect

- A correction followed by another read of the same instruction.
- A reference needed repeatedly but poorly signaled by the main skill.
- Duplicated or conflicting rules that could share one canonical location.
- Large tool output that could become a targeted query or a summary.
- Polls that consume turns without moving the task forward.

`tokens` estimates tokens from character counts. Its repeated-read thresholds are local heuristics, not Anthropic performance limits. It doesn't measure billing or prove savings. Propose a specific change and test the next cycle.
