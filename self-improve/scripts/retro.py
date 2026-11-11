#!/usr/bin/env python3
"""Read-only evidence extractor for the self-improve retrospection cycle.

Parses Claude Code JSONL transcripts (~/.claude/projects/<project>/*.jsonl, plus
subagents/) and Codex rollouts (~/.codex/sessions/**/rollout-*.jsonl) and prints
redacted markdown evidence. Every item cites file:line so findings can be checked.

Subcommands:
  triggers  where a skill was triggered, then the agent's next actions, outputs
            and the next human/agent messages
  signals   corrections, standing rules and re-asks in human messages
  hooks     hook firings, blocks, errors, timeouts, and risky calls with no hook
  tokens    biggest tool outputs, files read again and again, skill re-reads
  lint      static checks of SKILL.md / rules files against Anthropic guidance
  context   events around one file:line, to read a finding in place

Stdlib only. Never writes anything except the --out file.
"""
import argparse, difflib, glob, json, os, re, sys, time
from collections import Counter, defaultdict

# ---------------------------------------------------------------- redaction
SECRET_PATTERNS = [
    # Match complete sensitive forms before any display shortening.
    (re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=_-]{6,}"), r"\1[REDACTED]"),
    (re.compile(r"(?im)((?:set-)?cookie[\"']?\s*[:=]\s*)[^\r\n]+"), r"\1[REDACTED_COOKIE]"),
    (re.compile(r"(?i)([\"'][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|AUTH)[A-Z0-9_]*[\"']\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*')"), r"\1\"[REDACTED]\""),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), "[REDACTED_GH]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED_GH]"),
    (re.compile(r"xox[abposr]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED_GOOGLE]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|AUTH)[A-Z0-9_]*)\s*[=:]\s*['\"]?[^\s'\"&]{6,}"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)([?&](?:s|k|key|token|secret|sig|signature|code|auth|apikey|access_token)=)[^&\s\"'<>]{6,}"), r"\1[REDACTED]"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"), "[REDACTED_BOT_TOKEN]"),
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "[REDACTED_HEX]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
]


def redact(s):
    s = str(s)
    for rx, rep in SECRET_PATTERNS:
        s = rx.sub(rep, s)
    return s


def clip(s, n):
    s = " ".join(redact(s).split())
    return s if len(s) <= n else s[: n - 3] + "..."


# ---------------------------------------------------------------- loading
def find_files(paths, since_days, subagents):
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            out.append(p)
            continue
        pats = ["*.jsonl", "**/rollout-*.jsonl"] + (["*/subagents/*.jsonl"] if subagents else [])
        for pat in pats:
            out += glob.glob(os.path.join(p, pat), recursive=True)
    cutoff = time.time() - since_days * 86400 if since_days else 0
    out = sorted({f for f in out if os.path.getmtime(f) >= cutoff and "auth" not in os.path.basename(f).lower()})
    return out


HEADER = re.compile(r"^=== ([A-Z ]+?)(?: from ([^\[\n]*?))?\s*(?:\[|===)")


def classify_user(text, is_meta=False):
    """Return (source, body). source: owner | agent | system."""
    t = text.lstrip()
    if is_meta or t.startswith(("[Image", "<system-reminder>", "<local-command", "[CONTEXT]", "[CRON FIRED",
                                "[cortextOS startup", "# AGENTS.md", "<environment_context", "<user_instructions",
                                "Caveat:", "<task-notification", "This session is being continued", "[Request interrupted",
                                "Decision moved to chat", "<command-name>", "<command-message>")) or re.match(r"\[[A-Z][A-Z _-]{3,}\]", t):
        return "system", t
    m = HEADER.match(t)
    if m:
        kind = m.group(1)
        fence = re.search(r"```+\n(.*?)\n```", t, re.S)
        body = fence.group(1) if fence else t
        if kind in ("USER MESSAGE", "UI REPLY") or kind.startswith("TELEGRAM"):
            return "owner", body
        if kind in ("AGENT MESSAGE", "DELEGATED OWNER INSTRUCTION"):
            return "agent", body
        return "system", body
    return "owner", t  # plain typed prompt in a CLI session


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or "" if not isinstance(b.get("content"), list) else _text_of(b["content"]))
            else:
                parts.append(str(b))
        return "\n".join(p for p in parts if isinstance(p, str))
    return "" if content is None else str(content)


def tool_input_str(name, inp):
    if isinstance(inp, str):
        return inp
    if not isinstance(inp, dict):
        return str(inp)
    if name == "Read" and ("offset" in inp or "limit" in inp):
        return f"{inp.get('file_path')} [offset={inp.get('offset')} limit={inp.get('limit')}]"
    for k in ("command", "file_path", "path", "pattern", "skill", "url", "prompt", "query"):
        if k in inp:
            extra = f" {inp.get('args', '')}" if k == "skill" and inp.get("args") else ""
            return f"{inp[k]}{extra}"
    return redact(json.dumps(inp))[:500]


def events_claude(f):
    """Yield normalized events from a Claude Code transcript."""
    cwd = ""  # last `cd` target, so `cd skills/x; edit SKILL.md` maps to skill x
    with open(f, errors="replace") as stream:
        for ln, line in enumerate(stream, 1):
            if len(line) > 5_000_000:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            t = o.get("type")
            base = {"file": f, "line": ln, "ts": o.get("timestamp", ""), "session": o.get("sessionId", "")}
            if t == "user":
                c = o.get("message", {}).get("content")
                if isinstance(c, str):
                    src, body = classify_user(c, o.get("isMeta"))
                    if src == "owner" and o.get("isSidechain"):
                        src = "agent"  # a subagent's prompt comes from its parent agent
                    yield dict(base, kind="user", source=src, text=body)
                    continue
                for b in c or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        txt = _text_of(b.get("content"))
                        yield dict(base, kind="result", id=b.get("tool_use_id"), text=txt, size=len(txt), error=bool(b.get("is_error")))
                        safe_error = redact(txt) if b.get("is_error") else ""
                        m = b.get("is_error") and (re.search(r"(\w+:\w+) hook error: (.{0,300})", safe_error[:2000])
                                                   or re.search(r"(?i)(blocked by (?:a )?hook)(.{0,300})", safe_error[:2000]))
                        if m:  # only error results: a fetched doc that mentions "hook error" is not a block
                            yield dict(base, kind="hook", event=m.group(1), outcome="block", detail=m.group(2), id=b.get("tool_use_id"))
                    elif b.get("type") == "text":
                        src, body = classify_user(b.get("text", ""), o.get("isMeta"))
                        yield dict(base, kind="user", source=src, text=body)
            elif t == "assistant":
                for b in o.get("message", {}).get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        inp = tool_input_str(b.get("name"), b.get("input"))
                        cds = re.findall(r"(?:^|[;&]\s*)cd\s+([^\s;&|]+)", inp) if b.get("name") == "Bash" else []
                        cwd_at_start = cwd
                        if cds:
                            cwd = cds[-1]
                        yield dict(base, kind="tool", name=b.get("name"), id=b.get("id"), input=inp, cwd=(cds[0] if cds else cwd_at_start))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        yield dict(base, kind="text", text=b["text"])
            elif t == "attachment":
                a = o.get("attachment", {})
                at = a.get("type", "")
                if at == "queued_command" and isinstance(a.get("prompt"), str):
                    src, body = classify_user(a["prompt"])
                    yield dict(base, kind="user", source=src, text=body)
                elif at.startswith("hook_"):
                    out = redact((a.get("stdout") or "") + (a.get("content") or "") + (a.get("stderr") or ""))
                    outcome = {"hook_success": "ok", "hook_cancelled": "timeout" if a.get("timedOut") else "cancelled",
                               "hook_permission_decision": a.get("decision", "decision")}.get(at, at.replace("hook_", ""))
                    if at == "hook_success":
                        if a.get("exitCode") not in (0, None):
                            outcome = "nonzero"
                        elif re.search(r'"permissionDecision"\s*:\s*"(deny|ask)"|"decision"\s*:\s*"block"', out):
                            outcome = "block"
                        elif "updatedInput" in out:
                            outcome = "rewrite"
                        elif "additionalContext" in out:
                            outcome = "context"
                        elif not out.strip():
                            outcome = "silent"
                    reason = re.search(r'"(?:permissionDecisionReason|reason)"\s*:\s*"([^"]{0,200})', out)
                    yield dict(base, kind="hook", event=a.get("hookName") or a.get("hookEvent", ""), outcome=outcome,
                               detail=(reason.group(1) if reason else out[:200]) or a.get("command", ""), id=a.get("toolUseID"),
                               command=a.get("command", ""))


def events_codex(f):
    seen_user = set()
    with open(f, errors="replace") as stream:
        for ln, line in enumerate(stream, 1):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            p = o.get("payload") or {}
            if not isinstance(p, dict):
                continue
            pt = p.get("type")
            base = {"file": f, "line": ln, "ts": o.get("timestamp", ""), "session": os.path.basename(f)}
            if o.get("type") == "response_item":
                if pt == "message":
                    txt = _text_of(p.get("content"))
                    if p.get("role") == "user":
                        src, body = classify_user(txt)
                        seen_user.add(txt[:200])
                        yield dict(base, kind="user", source=src, text=body)
                    elif p.get("role") == "assistant" and txt.strip():
                        yield dict(base, kind="text", text=txt)
                elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
                    inp = p.get("arguments") or p.get("input") or p.get("action") or ""
                    if isinstance(inp, str) and inp.startswith("{"):
                        try:
                            inp = json.loads(inp)
                        except ValueError:
                            pass
                    if isinstance(inp, dict) and isinstance(inp.get("command"), list):
                        inp = " ".join(map(str, inp["command"]))
                    yield dict(base, kind="tool", name=p.get("name") or pt, id=p.get("call_id"), input=tool_input_str(p.get("name"), inp))
                elif pt in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                    out = p.get("output")
                    txt = _text_of(out) if not isinstance(out, dict) else _text_of(out.get("content") or out.get("output"))
                    yield dict(base, kind="result", id=p.get("call_id"), text=txt, size=len(txt),
                               error=bool(re.search(r"(?i)exit code: [1-9]|\berror\b", txt[:300])))
            elif o.get("type") == "event_msg" and pt == "user_message":
                txt = p.get("message", "")
                if txt[:200] not in seen_user:
                    src, body = classify_user(txt)
                    yield dict(base, kind="user", source=src, text=body)


def load(files):
    for f in files:
        head = open(f, errors="replace").read(4000)
        gen = events_codex if '"payload"' in head and '"session_meta"' in head or "/rollout-" in f else events_claude
        yield f, list(gen(f))


# ---------------------------------------------------------------- triggers
SKILL_PATH = re.compile(r"([A-Za-z0-9_.\-]+)/SKILL\.md")
CMD_NAME = re.compile(r"<command-name>/?([A-Za-z0-9_:.\-]+)</command-name>")


def skill_mode(e):
    """read | grep | edit | delegate: an edit to a SKILL.md right after a correction is a strong signal."""
    n, s = e["name"], e["input"]
    if n in ("Edit", "Write", "MultiEdit", "apply_patch") or re.search(r"sed -i|perl -pi|open\([^)]*['\"][wa]['\"]|write_text\(|\.write\(|>>?\s*\S*SKILL\.md|tee \S*SKILL\.md|apply_patch", s):
        return "edit"
    if n in ("Agent", "Task"):
        return "delegate"
    if n in ("Grep",) or re.search(r"\b(grep|rg)\b[^|;]*SKILL\.md", s) and not re.search(r"\b(cat|sed -n|head|tail|rtk read)\b[^|;]*SKILL\.md", s):
        return "grep"
    if re.search(r"sed -n|\bhead\b|\btail\b|\[offset=", s):
        return "partial-read"
    return "read"


def skill_hits(e):
    if e["kind"] == "tool":
        if e["name"] == "Skill":
            return [(e["input"].split()[0].split(":")[-1], "Skill tool")]
        names = list(dict.fromkeys(SKILL_PATH.findall(e["input"])))
        if not names and re.search(r"(?<![\w/.-])SKILL\.md", e["input"]) and e.get("cwd"):
            names = [os.path.basename(e["cwd"].rstrip("/"))]  # bare SKILL.md after cd into the skill dir
        return [(m, f"{e['name']} {skill_mode(e)} of SKILL.md") for m in names]
    if e["kind"] == "user" and e["source"] != "system" or e["kind"] == "user" and "<command-name>" in e["text"]:
        return [(m.split(":")[-1], "slash command") for m in CMD_NAME.findall(e["text"])]
    return []


def fmt_event(e, rel):
    loc = f"{rel(e['file'])}:{e['line']}"
    k = e["kind"]
    if k == "tool":
        return f"- `{loc}` TOOL {e['name']}: `{clip(e['input'], 160).replace('`', chr(39))}`"
    if k == "result":
        tag = "ERROR " if e["error"] else ""
        return f"- `{loc}` {tag}RESULT ({e['size']} chars): {clip(e['text'], 160)}"
    if k == "text":
        return f"- `{loc}` SAID: {clip(e['text'], 240)}"
    if k == "user":
        return f"- `{loc}` **{e['source'].upper()}**: {clip(e['text'], 400)}"
    if k == "hook":
        return f"- `{loc}` HOOK {e['event']} -> {e['outcome']}: {clip(e['detail'], 160)}"
    return ""


def cmd_triggers(args, data, rel):
    want = set(args.skill or [])
    out, counts, modes = [], Counter(), defaultdict(Counter)
    for f, evs in data:
        last = {}
        for i, e in enumerate(evs):
            for name, how in skill_hits(e):
                if want and name not in want:
                    continue
                m = next((x for x in ("partial-read", "read", "grep", "edit", "delegate") if f" {x} " in f" {how} "), "other")
                modes[name][m] += 1
                if name in last and i - last[name] <= args.merge:
                    last[name] = i  # chunked re-read of the same skill: same trigger
                    continue
                last[name] = i
                counts[name] += 1
                if args.max and counts[name] > args.max:
                    continue
                prev_user = next((p for p in reversed(evs[:i]) if p["kind"] == "user" and p["source"] != "system"), None)
                win, humans = [], 0
                for n in evs[i + 1:]:
                    if n["kind"] == "hook" and n["outcome"] in ("silent", "ok", "rewrite"):
                        continue
                    if n["kind"] == "result" and not n["error"] and not args.results:
                        continue
                    win.append(n)
                    if n["kind"] == "user" and n["source"] != "system":
                        humans += 1
                    if humans >= args.next_msgs or len(win) >= args.window:
                        break
                out.append(f"\n### {name} #{counts[name]} via {how} ({e['ts'][:16]})")
                out.append(f"Trigger: `{rel(f)}:{e['line']}`")
                if prev_user:
                    out.append(f"Asked before: {fmt_event(prev_user, rel)[2:]}")
                out += [fmt_event(n, rel) for n in win]
    head = ["# Skill triggers", "", "Modes count every touch of the skill (before merging). Many partial reads and no whole read of a long",
            "SKILL.md can indicate missed context. Confirm what was actually read before assigning a verdict.", "",
            "| skill | triggers | read | partial-read | grep | edit | delegate | other |", "|---|---|---|---|---|---|---|---|"]
    head += [f"| {k} | {v} | " + " | ".join(str(modes[k][m]) for m in ("read", "partial-read", "grep", "edit", "delegate", "other")) + " |"
             for k, v in counts.most_common()]
    return head + out


# ---------------------------------------------------------------- signals
CORRECTION = re.compile(
    r"(?i)(^\s*(no|nope|stop|wait|wrong)\b|\bdon'?t\b|\bdo not\b|\bnever\b|\balways\b|\bstop\b|\bagain\b|\bI (?:told|said|asked)\b"
    r"|\bshould(?:n'?t| have| not)\b|\binstead\b|\bwhy (?:did|didn'?t|are|is)\b|\bnot what\b|\bfrom now on\b|\bnext time\b"
    r"|\bremember\b|\bchange (?:the )?skill\b|\bupdate (?:the |your )?skill\b|\bmake sure\b|\bstill\b|\bdidn'?t\b|\bmissing\b|\bbroken\b)")
RULE_WORDS = re.compile(r"(?i)\b(always|never|from now on|every time|next time|rule|remember)\b")


def target_hint(text, active):
    t = text.lower()
    if "skill" in t or active:
        return f"skill:{active}" if active else "skill (which?)"
    if RULE_WORDS.search(t):
        return "rules file (CLAUDE.md / AGENTS.md / GUARDRAILS) or hook"
    return "memory (preference/fact)"


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())[:300]


SKILL_ASK = re.compile(r"(?i)\b(add|put|update|change|include|specify|write|bake|fix)\b.{0,50}\bskills?\b|\bskills?\b.{0,60}\b(for next time|to prevent|so (?:it|you) (?:don'?t|never|always))|\bin (?:your|the) skill\b")
BUILTIN_CMDS = {"exit", "clear", "compact", "model", "resume", "help", "config", "cost", "context", "login", "logout", "status", "init", "memory", "permissions", "hooks", "agents", "mcp", "doctor", "fast", "rewind", "export"}
ACTIVE_DECAY = 120  # events after a trigger before a correction stops being attributed to that skill


def cmd_signals(args, data, rel):
    srcs = {"owner"} | ({"agent"} if args.include_agents else set())
    want = set(args.skill or [])
    out, n, asks = ["# Human signals (corrections, rules, re-asks)", ""], 0, []
    for f, evs in data:
        active, active_i, seen = None, -10**9, []
        for i, e in enumerate(evs):
            hits = [h for h in skill_hits(e) if h[0] not in BUILTIN_CMDS]
            if hits:
                active, active_i = hits[0][0], i
            if e["kind"] != "user" or e["source"] not in srcs:
                continue
            act = active if i - active_i <= ACTIVE_DECAY else None
            body = e["text"]
            short = norm(body)
            rep = None
            if len(short) > 15:
                for prev_line, prev in seen[-40:]:
                    if difflib.SequenceMatcher(None, short, prev).ratio() > 0.8:
                        rep = prev_line
                        break
                seen.append((e["line"], short))
            m = CORRECTION.search(body[:600])
            ask = SKILL_ASK.search(body)
            if not (m or rep or ask) or (want and act not in want and not any(w in body for w in want)):
                continue
            n += 1
            why = "SKILL-CHANGE REQUEST" if ask else f"re-ask of line {rep}" if rep else f"matched '{m.group(0).strip()}'"
            out.append(f"- `{rel(f)}:{e['line']}` [{e['source']}] active skill: {act or '-'}; {why}; "
                       f"target: {target_hint(body, act)}\n  > {clip(body, 360)}")
            if ask:
                edit = next((x for x in evs[i + 1:i + 1 + args.lookahead] if x["kind"] == "tool"
                             and any("edit" in how for _, how in skill_hits(x))), None)
                deleg = None if edit else next((x for x in evs[i + 1:i + 1 + args.lookahead] if x["kind"] == "tool" and re.search(
                    r"(send-message|inject|Agent|Task|SendMessage)", x["name"] + " " + x["input"][:200]) and re.search(r"(?i)skill", x["input"])), None)
                done = (f"edited {skill_hits(edit)[0][0]}/SKILL.md at line {edit['line']}" if edit else
                        f"delegated to another agent at line {deleg['line']} (check it landed)" if deleg else
                        f"NO SKILL.md edit or delegation in next {args.lookahead} events")
                asks.append(f"- `{rel(f)}:{e['line']}` -> {done}\n  > {clip(body, 240)}")
    out.insert(2, f"{n} signals. Target is a heuristic hint; confirm by reading the turn.\n")
    out += ["", f"## Explicit skill-change requests ({len(asks)}) and whether a SKILL.md edit followed",
            "An edit may also land later, in another session, or via a script the parser cannot see. Verify against the current file."] + asks
    return out


# ---------------------------------------------------------------- hooks
RISKY = re.compile(r"(git push|--force\b|-f origin|--no-verify|reset --hard|git clean -f|rm -rf (?!/tmp|/private/tmp)|\.env\b|curl [^|]*-X ?(POST|PUT|DELETE)"
                   r"|DROP TABLE|chmod 777|npm publish|gh repo (create|edit)|--visibility|pm2 (delete|kill))")


def cmd_hooks(args, data, rel):
    agg, inst, missed = Counter(), [], []
    for f, evs in data:
        hooked_ids = {e.get("id") for e in evs if e["kind"] == "hook" and e["outcome"] not in ("silent",)}
        for i, e in enumerate(evs):
            if e["kind"] == "hook":
                agg[(e["event"], clip(e.get("command", ""), 60), e["outcome"])] += 1
                if e["outcome"] in ("silent", "ok", "rewrite"):
                    continue
                after = [n for n in evs[i + 1:i + 30] if n["kind"] in ("tool", "text", "user")][: args.window // 4 or 6]
                trig = next((t for t in evs[max(0, i - 8):i + 1] if t["kind"] == "tool" and t.get("id") == e.get("id")), None)
                inst.append(f"\n- `{rel(f)}:{e['line']}` {e['event']} -> **{e['outcome']}**: {clip(e['detail'], 220)}")
                if trig:
                    inst.append(f"  - on: {trig['name']} `{clip(trig['input'], 220).replace('`', chr(39))}`")
                inst += ["  " + fmt_event(n, rel) for n in after]
            elif e["kind"] == "tool" and RISKY.search(e["input"]) and e["id"] not in hooked_ids:
                missed.append(f"- `{rel(f)}:{e['line']}` [{RISKY.search(e['input']).group(0)}] {e['name']}: `{clip(e['input'], 160).replace('`', chr(39))}`")
    out = ["# Hooks", "", "| event | command | outcome | count |", "|---|---|---|---|"]
    out += [f"| {a} | `{clip(b, 60)}` | {c} | {v} |" for (a, b, c), v in agg.most_common(40)]
    out += ["", "## Non-trivial firings (block, error, timeout, context) and what happened next"] + inst[: args.max * 8 or None]
    out += ["", f"## Risky calls with no hook decision ({len(missed)}): should a hook have fired?"] + missed[: args.max or None]
    return out


# ---------------------------------------------------------------- tokens
READ_PATH = re.compile(r"(?:^|[;&|]\s*|\s)(?:cat|head|tail|sed -n [^ ]+|rtk read|less|bat)\s+(?:-n\s*\d+\s+)?([~/\w.\-]+\.(?:md|json|py|ts|js|txt|yaml|yml|sh|jsonl))")


def cmd_tokens(args, data, rel):
    big, reads, by_tool, skill_reads = [], Counter(), Counter(), Counter()
    first_line = {}
    for f, evs in data:
        names = {e["id"]: e for e in evs if e["kind"] == "tool"}
        for e in evs:
            if e["kind"] == "result":
                t = names.get(e["id"])
                by_tool[t["name"] if t else "?"] += e["size"]
                big.append((e["size"], f, e["line"], clip(t["input"], 120) if t else "?"))
            if e["kind"] == "tool":
                paths = [e["input"]] if e["name"] == "Read" else READ_PATH.findall(e["input"])
                for p in paths:
                    key = (rel(f), "/".join(p.split("/")[-2:]) if p.endswith("SKILL.md") else os.path.basename(p))
                    reads[key] += 1
                    first_line.setdefault(key, e["line"])
                    if p.endswith("SKILL.md"):
                        skill_reads[key] += 1
    big.sort(reverse=True)
    out = ["# Token and context", "", "Chars / 4 is a rough token estimate.", "", "## Output volume by tool", "| tool | chars | ~tokens |", "|---|---|---|"]
    out += [f"| {k} | {v} | {v // 4} |" for k, v in by_tool.most_common(12)]
    out += ["", f"## Largest tool outputs (top {args.max or 15})"]
    out += [f"- `{rel(f)}:{ln}` {s} chars: `{inp.replace('`', chr(39))}`" for s, f, ln, inp in big[: args.max or 15]]
    out += ["", "## Files read 4+ times in one session (consider caching, a summary, or a reference split)"]
    out += [f"- `{k[0]}:{first_line[k]}` {k[1]} x{v}" for k, v in reads.most_common(40) if v >= 4]
    out += ["", "## Skill files re-read in one session"]
    out += [f"- `{k[0]}` {k[1]} x{v}" for k, v in skill_reads.most_common(20) if v >= 2]
    return out


# ---------------------------------------------------------------- lint
DOCS_BP = "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices"
DOCS_SK = "https://code.claude.com/docs/en/skills"
DOCS_MEM = "https://code.claude.com/docs/en/memory"


def lint_skill(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    sk = os.path.join(d, "SKILL.md")
    txt = open(sk, errors="replace").read()
    lines = txt.count("\n") + 1
    out = [f"\n### {sk}", f"- lines: {lines}"]
    fm = re.match(r"---\n(.*?)\n---\n", txt, re.S)
    body_lines = lines - (fm.group(0).count("\n") if fm else 0)
    if body_lines > 500:
        out.append(f"- FAIL body {body_lines} lines > 500. Anthropic recommends a body below 500 lines ({DOCS_BP})")
    if not fm:
        out.append(f"- FAIL no YAML frontmatter ({DOCS_BP})")
    else:
        name = re.search(r"^name:\s*(.+)$", fm.group(1), re.M)
        desc = re.search(r"^description:\s*(.+?)(?=^\w[\w-]*:|\Z)", fm.group(1), re.M | re.S)
        if name and (len(name.group(1).strip()) > 64 or not re.fullmatch(r"[a-z0-9-]+", name.group(1).strip())):
            out.append(f"- FAIL name '{name.group(1).strip()}': max 64 chars, lowercase letters/numbers/hyphens ({DOCS_BP})")
        if desc:
            dv = " ".join(desc.group(1).split()).strip("'\"")
            out.append(f"- description: {len(dv)} chars")
            if len(dv) > 1024:
                out.append(f"- FAIL description > 1,024 chars ({DOCS_BP}); Claude Code truncates description+when_to_use at 1,536 in the listing ({DOCS_SK})")
            if re.match(r"(?i)(i |i'm |you can|we )", dv):
                out.append(f"- WARN description not third person (Anthropic recommends third-person descriptions, {DOCS_BP})")
            if re.match(r"(?i)\W*(draft|wip|deprecated|todo)", dv):
                out.append(f"- WARN description opens with a status word; Lead with the use case ({DOCS_SK})")
            if not re.search(r"(?i)\b(use when|use for|use this|when\b|whenever|trigger)", dv):
                out.append(f"- WARN description lacks a 'when to use' clause ({DOCS_BP})")
    refs = {r for r in re.findall(r"(?<![\w/.~$-])((?:\.\./|[\w-]+/)*[\w.-]+\.md)\b", txt) if not r.endswith("SKILL.md")}

    def resolve(r):  # relative to the skill dir first, then its ancestors (agent-root paths are common)
        base = d
        for _ in range(5):
            rp = os.path.normpath(os.path.join(base, r))
            if os.path.exists(rp):
                return rp
            base = os.path.dirname(base)
        return None
    for r in sorted(refs):
        rp = resolve(r)
        if not rp:
            if "/" in r:
                out.append(f"- WARN referenced file not found: {r}")
            continue
        rt = open(rp, errors="replace").read()
        rl = rt.count("\n") + 1
        if rl > 100 and not re.search(r"(?im)^#+ *(contents|table of contents)", rt[:1500]):
            out.append(f"- WARN {r} is {rl} lines with no table of contents (>100 lines should have one, {DOCS_BP})")
        inside = os.path.commonpath([rp, d]) == d
        nested = [x for x in re.findall(r"\(([\w./\-]+\.md)\)", rt) if not x.startswith("http")]
        if inside and nested:
            out.append(f"- WARN {r} links further .md files {nested[:3]}: keep references one level deep ({DOCS_BP})")
    allrefs = [x for x in glob.glob(os.path.join(d, "**", "*.md"), recursive=True) if os.path.basename(x) != "SKILL.md"]
    orphans = [os.path.relpath(x, d) for x in allrefs if os.path.basename(x) not in txt]
    if orphans:
        out.append(f"- WARN reference files never mentioned in SKILL.md (may be ignored): {orphans}")
    big_blocks = [m for m in re.finditer(r"```.*?```", txt, re.S) if m.group(0).count("\n") > 40]
    if big_blocks:
        out.append(f"- INFO {len(big_blocks)} code block(s) over 40 lines in SKILL.md: candidates for scripts/ or references/")
    return out


def lint_rules(path):
    txt = open(path, errors="replace").read()
    lines, size = txt.count("\n") + 1, len(txt.encode())
    out = [f"\n### {path}", f"- lines: {lines}, bytes: {size}"]
    auto_mem = "/.claude/projects/" in path and "/memory/" in path
    if os.path.basename(path) == "MEMORY.md":
        long_entries = sum(1 for l in txt.splitlines() if len(l) > 300)
        if auto_mem and (lines > 200 or size > 25 * 1024):
            out.append(f"- FAIL auto-memory index: only the first 200 lines or 25KB load at session start; the rest is dropped ({DOCS_MEM})")
        elif lines > 200 or size > 25 * 1024:
            out.append(f"- WARN index over 200 lines / 25KB. Not the Claude Code auto-memory file, so it is not truncated, but it is read in full every session. Same organization guideline: concise entries with detail in topic files ({DOCS_MEM})")
        if long_entries:
            out.append(f"- WARN {long_entries} index lines over 300 chars: entry bodies pasted into the index instead of a pointer")
    elif lines > 200:
        out.append(f"- WARN over 200 lines: Anthropic recommends shorter CLAUDE.md files to limit context cost and instruction drift ({DOCS_MEM}). Move detail to referenced files or path-scoped rules.")
    return out


def cmd_context(args, data, rel):
    """Events around one transcript line: `context <file> --line N`."""
    out = [f"# Context around line {args.line}"]
    for f, evs in data:
        i = next((k for k, e in enumerate(evs) if e["line"] >= args.line), len(evs))
        out += [fmt_event(e, rel) for e in evs[max(0, i - args.before):i + args.window]
                if not (e["kind"] == "result" and not e["error"] and not args.results)
                and not (e["kind"] == "hook" and e["outcome"] in ("silent", "rewrite"))]
    return out


def cmd_lint(args, _data, _rel):
    out = ["# Static lint", f"Sources: {DOCS_BP} ; {DOCS_SK} ; {DOCS_MEM}"]
    for p in args.targets:
        p = os.path.expanduser(p)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "SKILL.md")) or p.endswith("SKILL.md"):
            out += lint_skill(p)
        elif os.path.isfile(p):
            out += lint_rules(p)
        else:
            out.append(f"\n- skipped {p}: not a skill dir or file")
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["triggers", "signals", "hooks", "tokens", "lint", "context"])
    ap.add_argument("targets", nargs="*", help="transcript dirs/files (lint: skill dirs or rules files)")
    ap.add_argument("--skill", action="append", help="skill name to focus on (repeatable)")
    ap.add_argument("--since", type=int, default=0, help="only transcripts modified in the last N days")
    ap.add_argument("--no-subagents", action="store_true")
    ap.add_argument("--window", type=int, default=25, help="max events shown after a trigger")
    ap.add_argument("--next-msgs", type=int, default=2, help="stop window after N human/agent messages")
    ap.add_argument("--merge", type=int, default=6, help="re-reads of a skill within N events count as one trigger")
    ap.add_argument("--results", action="store_true", help="show successful tool results too")
    ap.add_argument("--include-agents", action="store_true", help="signals: include agent-to-agent messages")
    ap.add_argument("--lookahead", type=int, default=80, help="signals: events to scan for a SKILL.md edit after a skill-change request")
    ap.add_argument("--max", type=int, default=0, help="cap items per section (0 = all)")
    ap.add_argument("--line", type=int, default=1, help="context: transcript line to centre on")
    ap.add_argument("--before", type=int, default=5, help="context: events shown before --line")
    ap.add_argument("--out", help="write markdown here instead of stdout")
    a = ap.parse_args()
    home = os.path.expanduser("~")
    roots = sorted((os.path.expanduser(t).rstrip("/") + "/" for t in a.targets if os.path.isdir(os.path.expanduser(t))), key=len, reverse=True)

    def rel(p):
        for r in roots:
            if p.startswith(r):
                return p[len(r):]
        return p.replace(home, "~")
    if a.out:
        protected = []
        if a.cmd == "lint":
            for target in a.targets:
                target = os.path.expanduser(target)
                protected += glob.glob(os.path.join(target, "**", "*.md"), recursive=True) if os.path.isdir(target) else [target]
        else:
            protected = find_files(a.targets, 0, True)
            # Even filtered or specially named explicit inputs must stay read-only.
            protected += [os.path.expanduser(t) for t in a.targets if os.path.isfile(os.path.expanduser(t))]
        for target in protected:
            if os.path.realpath(a.out) == os.path.realpath(target) or (os.path.exists(a.out) and os.path.exists(target) and os.path.samefile(a.out, target)):
                ap.error("--out must not overwrite an input file")
    if a.cmd == "lint":
        lines = cmd_lint(a, None, rel)
    else:
        if not a.targets:
            ap.error("give at least one transcript dir or file")
        files = find_files(a.targets, a.since, not a.no_subagents)
        print(f"[retro] {len(files)} transcript files", file=sys.stderr)
        roots_note = "Paths are relative to: " + ", ".join(r.replace(home, "~") for r in roots) if roots else ""
        data = load(files)
        lines = {"triggers": cmd_triggers, "signals": cmd_signals, "hooks": cmd_hooks, "tokens": cmd_tokens, "context": cmd_context}[a.cmd](a, data, rel)
        lines.insert(1, f"\n{roots_note}\n" if roots_note else "")
    text = redact("\n".join(lines)) + "\n"
    if a.out:
        open(a.out, "w").write(text)
        print(f"[retro] wrote {redact(a.out)}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print("[retro] " + redact(str(exc)), file=sys.stderr)
        sys.exit(1)
