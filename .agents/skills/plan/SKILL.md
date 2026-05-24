---
name: plan-mode
description: >
  Full rules and output templates for Plan phase. Read this skill whenever the user issues /plan,
  or when the conversation starts in default Plan phase and a task is being scoped, explored, or
  discussed. Covers file reading, classification, risk analysis, plan writing, and gap checks.
  Trigger on: /plan, "let's plan", "what's the approach", "how do we tackle", task analysis,
  architecture discussion, or any time structured planning output is needed.
---

# Plan Phase Rules

## Read-Once Pattern
Before reading any file this phase, check if it's already been marked `[read]` in the current
conversation (e.g. `AGENTS.md [read]`, `task.md [read]`). If marked → skip re-read, use existing
context. Only re-read if user says the file changed.

## Steps — never skip, never reorder

### 1. Read
- Open `AGENTS.md` first. If missing → state it, ask how to proceed. Never invent contents.
- Open task file + all relevant source files. Not from memory.
- Map files, exports, connections. Cite what you find.
- Mark each file `[read]` in your reply header after opening it.

### 2. Classify
- **Verified** — cite file + function/line
- **Inferred** — label clearly, never present as fact
- **Unknown** — ask before proceeding

### 3. Risks
Surface: contradictions, fragile areas, missing requirements, regression risks, ordering dependencies.

### 4. Ask
Ask if user wants a plan. Do not write one until confirmed.

### 5. Write Plan (after confirmation only)
Every plan must be:
- **Self-explanatory** — readable cold, zero prior context needed
- **Beginner-friendly** — exact file + function/line, exact changes, no "handle appropriately"
- **Exhaustive** — every file, side effect, dependency. Nothing hand-waved.
- **Ordered** — each step builds on the last

Per step format: `What · Where (file+fn/line) · How (exact) · Why · Caveats`

### 6. Gap Check
Re-read plan vs task vs actual files. Fix vague/missing/risky steps. State what changed.

---

## Checklist (apply every plan)
Null/empty/invalid input · boundary/off-by-one · auth/permissions · async/race conditions ·
stale cache · broken imports/exports · config/env/schema mismatch · backward compatibility ·
missing validation/error handling/cleanup · loading/error/empty states · test gaps ·
API contract · dead code/naming/complexity

---

## Output Templates

### Discussion output
```
# Discussion Findings
## Verified
## Inferred
## Unknown / needs clarification
## Edge cases / failure modes
## Issues / pushback
## Questions
```

### Post-plan gap check output
```
# Plan Gap Check
## Gaps / risks found
## Changes made
## Open questions
```
