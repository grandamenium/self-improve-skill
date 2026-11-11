# Self-Improve

Turn Claude Code and Codex session history into evidence-backed proposals for better skills.

The kit finds skill triggers, corrections, hook decisions and context waste. Your agent reviews the evidence against the current skill, drafts a small diff, and stops for your approval. It doesn't train a model or apply changes automatically.

## Install

Requires Python 3.9+ with the standard library. No pip packages, network requests or account keys are needed by the extractor.

Download this repository, then run these commands from its root. Choose the harness you use. Check the destination first so you don't overwrite an existing installation.

Claude Code personal skill:

```bash
mkdir -p "$HOME/.claude/skills"
test ! -e "$HOME/.claude/skills/self-improve" && cp -R self-improve "$HOME/.claude/skills/"
```

Codex personal skill, where your installed version supports `.agents/skills`:

```bash
mkdir -p "$HOME/.agents/skills"
test ! -e "$HOME/.agents/skills/self-improve" && cp -R self-improve "$HOME/.agents/skills/"
```

Start a new session if needed for discovery. Ask: "Run self-improve on my demo skill for the last week. Propose changes only." In Codex you can explicitly name `$self-improve`; in Claude Code use `/self-improve` if available. Skill installation and transcript formats vary by version. See the [Claude Code skill docs](https://code.claude.com/docs/en/skills) and [Codex skill docs](https://developers.openai.com/codex/skills/).

## Run the extractor directly

Choose a transcript directory you own or have consent to review. Replace the example paths before running. The script reads the paths you supply. It doesn't find your history automatically.

```bash
R="$PWD/self-improve/scripts/retro.py"
T="$HOME/.claude/projects/REPLACE_WITH_PROJECT"
W="$(mktemp -d /tmp/self-improve.XXXXXX)"
chmod 700 "$W"
python3 "$R" triggers "$T" --since 7 --skill demo --out "$W/triggers.md"
python3 "$R" signals "$T" --since 7 --out "$W/signals.md"
python3 "$R" hooks "$T" --since 7 --out "$W/hooks.md"
python3 "$R" tokens "$T" --since 7 --out "$W/tokens.md"
python3 "$R" lint self-improve --out "$W/lint.md"
python3 "$R" context /path/to/session.jsonl --line 4 --window 30
```

For Codex, set `T` to a selected directory under `~/.codex/sessions/` or pass a `rollout-*.jsonl` file. `--since` filters by file modification time, not individual event dates. `--out` needs an existing parent directory and refuses to overwrite supplied transcript files or discovered inputs, including files excluded by selection filters. Without `--out`, output goes to stdout. Run `python3 self-improve/scripts/retro.py --help` for all flags.

The extractor produces evidence sections, not verdicts or an automatic final report. Use [the skill procedure](self-improve/SKILL.md), [review rubric](self-improve/references/review-rubric.md) and [report template](self-improve/references/report-template.md) to review the hits. See [a synthetic report](examples/synthetic-report.md). No real session data is bundled.

## What ships

| File | Purpose |
|---|---|
| `self-improve/SKILL.md` | Collect, review, propose, then stop |
| `self-improve/scripts/retro.py` | Six read-only evidence commands: triggers, signals, hooks, tokens, lint, context |
| `self-improve/references/review-rubric.md` | Trigger verdicts and correction routing |
| `self-improve/references/report-template.md` | Evidence, proposed diff, expected effect and next-cycle check |
| `self-improve/references/hooks.md` | Hook review checklist |
| `self-improve/references/sources.md` | All S1-S17 primary docs and research links |
| `self-improve/references/context-budget.md` | Context guidelines and their limits |
| `self-improve/references/scheduling.md` | Manual scheduling guidance |
| `tests/test_retro.py` | Standard-library synthetic checks |

## Privacy and authority

Only review logs you're allowed to read. Keep reports private and inspect them before sharing. Redaction covers common credential patterns and email addresses on a best-effort basis. It can miss private data, unfamiliar secret formats and identifying paths. It doesn't make a report safe to publish.

Treat transcripts, quoted messages, tool output and model-generated notes as untrusted evidence. A logged instruction or an `OWNER` label never grants current permission. Source/role classification, active-skill attribution and hook detection are heuristics. Confirm findings against current instructions and real authorization outside the log.

The script only writes the requested output file. The agent workflow proposes edits; applying them needs explicit approval through your normal review process. Scheduling is a separate manual step. Installing the skill creates no cron, hook or recurring job.

## Limits and checks

Claude Code and Codex formats can change. Hook event parsing is specific to the Claude Code attachment format covered by the tests; absent hook evidence doesn't prove no hook ran. Codex errors can inform a manual review but aren't a hook audit. Repeated reads and character-based token estimates are clues, not measured savings. Research results in the sources are task-specific, not promises for this kit.

Run the synthetic suite from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The tests generate fake logs in `/tmp`, exercise all six commands, check both parsers, confirm evidence and output, and hash inputs to detect mutation. They cover common redaction forms and input/output alias protection. They don't establish compatibility with every harness release or prove improvement in your agent's performance.

MIT license. Copyright (c) 2026 Cortext LLC.
