# Rules block for a project's `AGENTS.md` / `CLAUDE.md`

The hooks are a mechanical brake, but the agent also has to understand *why* — otherwise
it keeps bumping into the denial instead of writing a subagent task straight away. Copy
this block near the top of your project instruction file (that file is loaded into every
request).

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
   find and what to return. Its context is isolated and far smaller; only the answer
   comes back. Edits (`Read`/`Edit`/`Write`), builds, tests and git go directly.
3. **Budget ≈ 10 calls per task.** Exhausted with no solution — stop and report what was
   found and what is missing. Do not keep digging silently.
4. **One question instead of twenty greps** when the user already knows the answer (which
   screen, which object, what is on the screenshot).
5. **When the user names the symptom and the location, go to the code and fix it** —
   do not reproduce what they already demonstrated.
6. **Hand verification back to the author when it needs the running app:** show the diff
   and what to look at. A self-driven "screenshot → edit → screenshot" loop only on
   request.

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
