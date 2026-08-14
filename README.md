# claude-cost-kit

Two hooks, an installer and a rules snippet that stop Claude Code from burning money on
long chains of trivial tool calls. Installed into your user settings
(`~/.claude/settings.json`), so it applies to **every project**, not just one repository.

## The problem

Every tool call an agent makes is a separate request to the model, and the whole
accumulated conversation is re-sent with it. A `grep` may return nine tokens, yet the
request that produced it carried a hundred thousand tokens of context. So the cost of a
task is roughly:

```
cost ≈ (number of calls) × (context size per call)
```

The two factors are coupled: the longer the loop runs, the bigger the context each
subsequent step carries. A twenty-grep exploration is not "twenty cheap calls" — it is
twenty full-context requests.

Two consequences that are easy to get wrong:

1. **Prompt caching does not change the order of magnitude.** Cache reads cost about a
   tenth of normal input, but you are still paying to re-send what was already sent,
   hundreds of times.
2. **Clearing the context between messages does not fix it.** The agent re-accumulates
   context inside its own solving loop, and the baseline — system scaffolding plus the
   project's instruction file — is paid from scratch on every single call.

The lever this kit uses: **a subagent has its own isolated context.** A `quick-lookup`
subagent spending one `Grep` call was measured at ~20k tokens total, while a main-loop
call in a working session routinely carries several hundred thousand. Same grep, an order
of magnitude cheaper — and only the answer comes back into the main dialogue.

## What is in the kit

### 1. `hooks/search_gate.py` — a brake, not a report

A `PreToolUse` hook. It counts search calls within a **single user message**
(`prompt_id` from the hook payload):

- search calls are `Grep`, `Glob`, and `Bash`/`PowerShell` invoking `grep`, `rg`, `find`,
  `fd`, `ls`, `dir`, `cat`, `head`, `tail`, `wc`, `tree`, `jq`, `sed`, `awk`,
  `Select-String`, `Get-Content`;
- the first two pass inline, from the third on the hook returns
  `permissionDecision: deny` explaining "batch the rest into one `quick-lookup`
  subagent task";
- calls made **by a subagent** are never counted and never denied — their payload
  carries `agent_id`, which main-loop calls do not have;
- `Read`/`Edit`/`Write`, `git`, `npm`, builds, tests and diagnostic scripts are
  untouched.

Why the threshold is 2 and not 0: a single lookup inline is cheaper than spawning a
subagent, because spawning costs one more full-context main-loop turn plus the return
message. The money burns on chains, so the gate cuts the chain at its third link, before
it becomes the twentieth. Tune with `CLAUDE_FREE_SEARCH_CALLS`.

### 2. `hooks/call_budget.py` — the backstop

Blocks nothing. After 40 calls in a session, and every 25 after that, it injects a
reminder to stop and report. It covers loops that grow for reasons other than search:
screenshot cycles, repeated builds, heavy diagnostic runs. Tune with
`CLAUDE_CALLS_FIRST_WARNING` and `CLAUDE_CALLS_REPEAT_EVERY`.

### 3. `rules-snippet.md` — the rules the agent reads

Installed automatically, into `~/.claude/CLAUDE.md`. The hook is the mechanism, but the
agent also needs to know *why*, otherwise it keeps bumping into the denial instead of
writing a subagent task straight away. The snippet also carries the second half of the
saving: keeping the instruction file itself short, because that file is loaded into every
request **and** into every subagent.

The block covers the **return contract** as well, and that half is not optional. The hook
can only push search out of the main context; it cannot police what comes back. A subagent
asked to "list every file matching this mask" returns three hundred paths, the orchestrator
pastes them into the dialogue, and the payload you paid to keep out is now in the context
and re-sent with every later call. So the rules require a stated ceiling on every `Agent`
task ("at most 10 paths", "under 20 lines"), and treat the subagent report as working
material to be summarised — never forwarded verbatim to the user.

## Install

```sh
git clone https://github.com/anton2riot/claude-cost-kit
cd claude-cost-kit
python3 install.py
```

One command sets up both halves — there is nothing left to copy by hand:

| Written | What lands there |
|---|---|
| `~/.claude/hooks/` | the two hook scripts |
| `~/.claude/settings.json` | the `PreToolUse` entries invoking them |
| `~/.claude/CLAUDE.md` | the rules from `rules-snippet.md`, inside a `<!-- claude-cost-kit:begin -->` / `<!-- claude-cost-kit:end -->` block |

Both edited files are backed up first (`settings.json.bak`, `CLAUDE.md.bak`), and
everything else in them is left alone: unrelated hooks stay, and your own instructions in
`CLAUDE.md` are kept — the rules are appended in their own marked block. Re-running is
safe and is how you update: the kit's previous entries and the previous rules block are
replaced in place, never doubled.

- `python3 install.py --dry-run` — print the resulting `hooks` section and the resulting
  `CLAUDE.md`, change nothing.
- `python3 install.py --no-rules` — hooks only, leave `CLAUDE.md` untouched. For putting
  the rules in a project file instead, or when you keep instructions under version
  control elsewhere. Expect more retries: the agent then meets the denial without knowing
  the reasoning behind it.
- `python3 install.py --remove` — uninstall, including the rules block. The hook scripts
  in `~/.claude/hooks` are left on disk to delete by hand.

Hooks are read at startup, so restart Claude Code afterwards.

The rules go to user level, like the hooks, so they cover every project. The cost is about
1k tokens of instruction carried by every request — which is why the block stays short,
and why the snippet ends with a rule about keeping instruction files short.

### Verifying it works

Two things to check, one per half:

1. Ask the agent to search for three different things in one message. The third search
   call should come back denied, with the message about handing the work to a subagent.
   From there the agent batches the lookups itself.
2. Open `~/.claude/CLAUDE.md` and confirm the `claude-cost-kit` block is there. Without
   it the hook still fires, but the agent has not read the return contract — and a
   subagent whose answer arrives as a dump has saved you nothing.

### 4. `tools/report.py` — measuring the effect

Claude Code stores every session as JSONL under `~/.claude/projects/`, with the `usage`
block of each turn. That is enough to see whether the loop actually got shorter, without
waiting for a billing dashboard:

```sh
python3 tools/report.py --days 14
python3 tools/report.py --split 2026-07-29     # the day you installed the hooks
python3 tools/report.py --project my-repo
```

Per day, and then as a before/after pair around `--split`:

| column | meaning |
|---|---|
| `msgs` | user messages that day — the unit of work |
| `calls`, `calls/msg` | tool calls in the main loop, total and per message |
| `search`, `search/msg` | search calls in the main loop — the gate's direct target |
| `ctx/call` | average context carried by one main-loop request |
| `ctx total` | all context sent in main-loop requests that day — the money line |
| `sub calls`, `sub ctx` | the same work done inside subagents, where context is cheap |
| `denied` | search calls the gate refused, from its own log |

**Read the per-message rows, not the totals.** Days differ in how much work they contain,
so `calls per message` and `context per message` are the comparable numbers; the totals
only say how busy the day was. Expect `sub calls` to go **up** while `calls/msg` goes down
— that is the mechanism working, search moving out of the expensive context.

The report deliberately prints no money: token prices depend on your plan and proxy. Take
the absolute spend from your billing dashboard and use this report to explain its shape.

`denied` only counts days after installation, because the log starts with the gate.

## What it does not do

- It does not shrink context already accumulated in the current session.
- It cannot cap what a subagent *returns*, nor stop the orchestrator from pasting that
  answer into the dialogue. A `PreToolUse` hook sees the task prompt, not the reply, and no
  hook sees the agent's own text at all. That half is rules-level discipline — the return
  contract in `rules-snippet.md` — which is why installing the snippet is not optional.
- It does not help with long loops unrelated to search — screenshot cycles, repeated
  builds, heavy diagnostics. Only the reminder backstop applies there.
- It does not replace shrinking your project instruction file: the baseline is paid on
  every call, including every subagent call.

## Requirements

Python 3.8+ on PATH — the installer writes the absolute path of the current interpreter
into the hook command. One implementation for Windows, macOS and Linux.

## License

MIT
