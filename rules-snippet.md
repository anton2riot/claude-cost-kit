# Rules block for the agent's instruction file

The hooks are a mechanical brake, but the agent also has to understand *why* — otherwise
it keeps bumping into the denial instead of writing a subagent task straight away, and it
learns nothing about what it may send back into the main dialogue.

`install.py` installs this automatically: it extracts everything between the two `---`
fences below and writes it into `~/.claude/CLAUDE.md` inside a
`<!-- claude-cost-kit:begin -->` / `<!-- claude-cost-kit:end -->` block, so re-installing
updates it in place and `--remove` takes it back out. Nothing else in that file is touched.

**Both fences must stay**, and the text between them is what the agent actually reads — the
installer takes it verbatim. Prose outside the fences (including the closing section) is
documentation for the human. To put the rules in a project file instead, copy the fenced
block into that project's `AGENTS.md` / `CLAUDE.md` by hand and run
`install.py --no-rules`.

---

## Cost of the work: minimum requests per task

Every tool call is a separate billed request, and the whole conversation is re-sent with
it. Cost of a task ≈ (number of calls) × (context size). How the work is done is part of
the requirement.

1. **Batch independent calls into one message.** Several `Read`/`Grep`/`Bash` calls with
   no data dependency go out together, not one at a time.
2. **Mechanical search goes to a subagent, not into the main dialogue.** More than two
   search calls (`Grep`/`Glob`, or `grep`/`find`/`ls`/`cat` in `Bash`) for one user
   message means ONE `Agent` task with `subagent_type: quick-lookup`, stating what to
   find, what to return and **how much** (see the return contract below). Its context is
   isolated and far smaller; only the answer comes back. Edits
   (`Read`/`Edit`/`Write`), builds, tests and git go directly.
3. **Budget ≈ 10 calls per task.** Exhausted with no solution — stop and report what was
   found and what is missing. Do not keep digging silently.
4. **One question instead of twenty greps** when the user already knows the answer (which
   screen, which object, what is on the screenshot).
5. **When the user names the symptom and the location, go to the code and fix it** —
   do not reproduce what they already demonstrated.
6. **Hand verification back to the author when it needs the running app:** show the diff
   and what to look at. A self-driven "screenshot → edit → screenshot" loop only on
   request.

## What comes back: the subagent return contract

Pushing search into a subagent saves nothing if the answer arrives as a dump. What crosses
the boundary lands in the main context and is then re-sent with **every** later call in the
session. The isolated context pays off only when the thing that comes back is small.

7. **Every `Agent` task states its return budget.** Name the shape and the ceiling in the
   task prompt itself: "return at most 10 paths, one line each on what it is for",
   "answer in under 20 lines", "return `file:line` of the definition and nothing else".
   A task with no stated ceiling comes back as a dump — that is the default, not the
   exception.
8. **Ask for the conclusion, not the material.** "Which file defines X and how is it wired
   in" — not "list every file matching this mask". A full listing is a request for a dump
   whose only ceiling is the size of the repository. When the set itself is the answer,
   ask for the count and the grouping ("42 files in 4 directories, named `Stage_N`"), and
   for concrete paths only where they are actually needed.
9. **The subagent report is working material, not a message to the user.** Read it, take
   what changes the decision, write your own answer — three to five lines. Do not paste
   the report, its file lists or its reasoning into the dialogue: that is exactly the
   payload you just paid a subagent to keep out of it. If the user asked for a list, give
   the list; otherwise give the conclusion and offer the detail.
10. **Nothing from a subagent's internals reaches the user.** Its reasoning calls the
    orchestrating agent "the user" and treats the task prompt as a user message; forwarded
    verbatim it reads as nonsense and misattributes the request. Only your own summary
    goes out.
11. **No speculative parallel tasks.** One subagent per open question. Launching a second
    "meanwhile, collect the file lists" task while the first is still running buys nothing
    — the answer usually makes the listing unnecessary, and its dump arrives anyway.

## Diagnostics: protocol priced by uncertainty

The full protocol (capture a baseline, record actual values across every state, confirm
each one by hand) is mandatory when **the cause is unknown**, or when the fix changes a
shared formula that already-verified cases depend on. When the user has named the symptom
and the location and the offending line is visible in the code, the fix is narrow: diff
plus a regression test, verification handed back to the author.

---

## A rule of the same order: keep the instruction file itself short

The project instruction file is loaded into **every** request — the main dialogue and
every subagent alike. Mechanism walkthroughs, formula derivations and bug history do not
belong there; they are read on demand, when they are actually needed.

A structure that works: `AGENTS.md` holds only actionable rules, one to three lines each,
with a link to the detailed write-up. Next to it live files that are *not* auto-loaded:

- `docs/agents-postmortems.md` — why the rules are what they are: formula derivations,
  regression analyses, bug history;
- `docs/agents-ui-and-process.md` — detailed UI and process rules, with a list of
  triggers: "touching this area — read that file first".

Where the text used to be, `AGENTS.md` keeps a single trigger line. On a real project this
split cut the auto-loaded instruction file by roughly 60% — from ~25k tokens to ~10k
tokens paid on every call.
