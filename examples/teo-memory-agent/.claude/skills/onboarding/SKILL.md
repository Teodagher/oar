---
name: onboarding
description: "Run ONCE to turn this template into a specific agent with its owner. Use when identity.md is missing or holds _TODO: placeholders (status says NOT ONBOARDED), or when the user says 'onboard me', 'set up' or 'get started'. Skip if the owner says they are working on the template itself."
---

# Onboarding

Turn a fresh copy into a working agent in one short conversation. Ask, then do all the writing
yourself. Write **only** to `identity.md`, `LOCAL.md` and `memory/`: never to `AGENTS.md`, the
template's skills or `tools/`.

## Step 0: one question first

> "Are we creating a new agent from scratch, or do you have existing material I should learn from
> (documents, notes, an old prompt, a previous assistant's memory)?"

Existing material: ask for it and read it before Step 1, so you can propose answers.

## Step 1: one batch of questions

If `identity.md` already holds answers (the host asked the setup questions), keep them and ask
only for the rest. One message, numbered:

1. **Role and mission**: what am I, what am I for, what's my name?
2. **Owner**: who are you, how do I reach you?
3. **Who I serve**: only you, a team, customers? Who may talk to me?
4. **Hard rules**: what must I never do? What must I always ask you first?
5. **Tools and channels**, timezone, tone and language.
6. **First 3 jobs.**

## Step 2: write the agent

1. If `identity.md` is missing, create it from the structure of the template's
   `seed/identity.md`. Fill every `_TODO:` line; the first line becomes
   `Onboarded on YYYY-MM-DD with <owner>.`
2. The owner's working preferences that are not hard rules go in `LOCAL.md`.
3. Memory: file the answers verbatim
   (`python3 tools/memory.py file --text - --date <today> --kind chat --slug onboarding-answers`),
   create `person` and `decision` pages, put the first jobs in `memory/now.md`.

## Step 3: finish

`python3 tools/memory.py log setup "Onboarded as <name>"`, `index`, then `lint` (no "not onboarded"
line). Recap in a few lines and ask whether to start the first job.
