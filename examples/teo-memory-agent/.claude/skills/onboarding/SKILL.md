---
name: onboarding
description: "Run ONCE to turn this template into a specific agent with its owner. Use when identity.md is missing or still holds _TODO: placeholders (status says NOT ONBOARDED), or when the user says 'onboard me', 'set up', 'set yourself up' or 'get started'. Skip if the owner says they are working on the template itself."
---

# Onboarding

Turn a fresh copy into a working agent in one short conversation. Ask, then do all the writing
yourself. The `_TODO:` lines in `identity.md` are the state: keep any already filled (a host such
as agent8 may have asked some questions at install), ask only for the rest.

**Write only to your own files:** `identity.md`, `LOCAL.md`, `skills/` and `memory/`. Never to
`AGENTS.md`, `CLAUDE.md`, `agent.yaml`, the template's skills, `.claude/rules/`, `templates/` or
`tools/`: they belong to the template and are replaced on every update.

## Step 0: one question first

> "Are we creating a new agent from scratch, or do you have existing material I should learn from
> (documents, notes, an old prompt, a previous assistant's memory)?"

Existing material → ask them to paste it or give file paths. Read it before Step 1 so you can
propose answers ("here's what I gathered, correct me") instead of asking blind.

## Step 1: one batch of questions

One message, numbered; rough answers are fine. Skip what `identity.md` already answers:

1. **Role and mission**: what am I, what am I for, what's my name?
2. **Owner**: who are you, how do I reach you?
3. **Who I serve**: only you, a team, customers? Who may talk to me?
4. **Success**: what does a great month with me look like?
5. **Hard rules**: what must I never do? What must I always ask you first?
6. **Tools and channels**: which tools, accounts, MCP servers, channels? Timezone?
7. **Tone and language**
8. **First 3 jobs**

If this folder is a git repository (`git rev-parse --show-toplevel` prints this folder), add:

9. **Keep my memory in git?** Say yes only if the repository is private: memory and identity are
   personal.

One follow-up at most, only if hard rules or who may instruct are unclear. Otherwise pick sensible
defaults and say so in the recap.

## Step 2: write the agent

1. `identity.md` (run `python3 tools/memory.py status` first if it is missing: it copies it from
   `seed/`): replace every `_TODO:` line. The line under the title becomes
   `Onboarded on YYYY-MM-DD with <owner>.`; the owner's rules go under **Owner's rules** in
   imperative form. The safe defaults stay in `AGENTS.md`: if the owner wants one lifted, write
   the exception as an owner's rule and log a decision.
2. `LOCAL.md`: working preferences that are not hard rules (how to report, when to check in), one
   per line.
3. Git (only if asked in question 9): **no** → keep memory out of git with
   `printf '/identity.md\n/LOCAL.md\n/skills/\n/memory/\n' >> .git/info/exclude` (a local file,
   not part of the template). **Yes** → nothing to do; `memory.py commit` saves them.
4. Memory:
   - File the answers verbatim: `python3 tools/memory.py file --text - --date <today> --kind chat --slug onboarding-answers`
     with the owner's words on stdin (heredoc).
   - `new person "<owner>"`, `new decision "Agent created"` (who decided, role, mission), a `new lesson`
     per working preference already stated, a `new topic` or `new org` per main subject with facts.
     Fill `summary`, and add evidence lines citing `[[raw/<date>_chat_onboarding-answers.md]]`.
   - `memory/now.md`: the first jobs under **Next** (or **Focus** for the one to start with), with `due:`
     if given.

## Step 3: import existing material (only if Step 0 said so)

For each document or paste: run `remember`, oldest first. Rules from an old prompt or memory become
`lesson` pages, owner's rules in `identity.md` or lines in `LOCAL.md` (ask which when unclear);
facts go to the wiki like any source.

## Step 4: finish

1. `python3 tools/memory.py log setup "Onboarded as <name>, <role>"` and `python3 tools/memory.py index`.
2. `python3 tools/memory.py lint`: 0 errors and no "not onboarded" line. Fix and rerun.
3. `python3 tools/memory.py commit "onboarding: <name>, <role>"`. It commits only your own files and
   memory, and does nothing when they are not kept in git. Never `git add -A`.
4. Recap in a few lines: who I am, who I serve, hard rules, first jobs, defaults picked. Then: "Talk to
   me or hand me files; I remember what matters and pick up `now.md` every session." Ask whether to
   start the first job.
