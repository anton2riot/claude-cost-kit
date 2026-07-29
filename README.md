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

### 3. `rules-snippet.md` — rules for the project instruction file

The hook is the mechanism, but the agent also needs to know *why*, otherwise it keeps
bumping into the denial instead of writing a subagent task straight away. Copy the block
into your project's `AGENTS.md` / `CLAUDE.md`. It also carries the second half of the
saving: keeping the instruction file itself short, because that file is loaded into every
request **and** into every subagent.

## Install

```sh
git clone https://github.com/anton2riot/claude-cost-kit
cd claude-cost-kit
python3 install.py
```

The installer copies the scripts into `~/.claude/hooks`, registers them in
`~/.claude/settings.json` (backing it up as `settings.json.bak`) and leaves unrelated
hooks alone. Re-running is safe: previous entries from this kit are removed first, so
counters are never doubled.

- `python3 install.py --dry-run` — print the resulting `hooks` section, change nothing.
- `python3 install.py --remove` — uninstall.

Hooks are read at startup, so restart Claude Code afterwards.

### Verifying it works

Ask the agent to search for three different things in one message. The third search call
should come back denied, with the message about handing the work to a subagent. From
there the agent batches the lookups itself.

## What it does not do

- It does not shrink context already accumulated in the current session.
- It does not help with long loops unrelated to search — screenshot cycles, repeated
  builds, heavy diagnostics. Only the reminder backstop applies there.
- It does not replace shrinking your project instruction file: the baseline is paid on
  every call, including every subagent call.

## Requirements

Python 3.8+ on PATH — the installer writes the absolute path of the current interpreter
into the hook command. One implementation for Windows, macOS and Linux.

## License

MIT
