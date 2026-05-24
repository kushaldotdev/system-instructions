---
name: review-mode
description: >
  Full rules and output templates for Review phase. Read this skill whenever the user issues
  /review, or when reviewing code changes, implementation correctness, or system architecture.
  Handles two modes: code review (what changed, is it correct) and architecture review
  (upstream/downstream design analysis). Trigger on: /review, "check this", "review the changes",
  "review the architecture", "does this look right", "verify the implementation", "check the design",
  PR review, or any request to evaluate correctness of code, a plan, or a system design.
---

# Review Phase Rules

## Read-Once Pattern
Before reading any file, check if it's already marked `[read]` in this conversation.
If marked → skip re-read, use existing context.
Exception: fresh-pass required on phase entry — treat all files as unread when switching into Review.

---

## Mode Detection — decide before reading anything

Run both modes unless context is clearly one-sided.

| Signal | Mode |
|---|---|
| "review changes", "check the PR", plan exists, specific files mentioned | Code review |
| "review the architecture", "check the design", structural question | Arch review |
| Both signals, or no clear signal, or user says nothing specific | **Both — arch first, then code** |

Arch first always. If the design is wrong, code correctness is irrelevant.

State selected mode at the top of your reply, e.g.:
`Review mode: Code` or `Review mode: Arch` or `Review mode: Both (arch first)`

---

## Step 0: Anchor Check — do this before anything else

The anchor is a compact project summary built from source files. It keeps the big picture
in context during focused subsystem passes without loading full docs every time.

Anchor location: `.agents/anchors/<project-name>.md`
Where `<project-name>` is the root folder name of the project being reviewed.

### Decision tree

```
Does .agents/anchors/<project>.md exist?
  NO  → run Anchor Build (below), then continue to Step 1
  YES → run Anchor Staleness Check (below)
          STALE   → run Anchor Partial Rebuild, then continue to Step 1
          CURRENT → load anchor, mark [anchor:loaded], continue to Step 1
```

### Anchor Build (first time)
1. Read all architecture docs and key source files the user listed
2. Write `.agents/anchors/<project>.md` using the Anchor Format below
3. Mark `[anchor:built]` in your reply

### Anchor Staleness Check (anchor exists)
1. Read the `built` date and `source-files` list from the anchor header
2. For each file in the list: check its last modified timestamp (`os.path.getmtime` or `stat`)
3. Any file modified after `built` date → anchor is stale for that file
4. All files same → anchor is current

### Anchor Partial Rebuild (stale)
1. Re-read only the files newer than the anchor `built` date
2. Update only the affected sections of the anchor
3. Update the `built` date to now
4. Mark `[anchor:rebuilt — changed files: x, y, z]` in your reply

### Anchor Format
```
---
project: <name>
built: <YYYY-MM-DD HH:MM>
source-files:
  - path: <file>
    mtime: <YYYY-MM-DD HH:MM>
  - path: <file>
    mtime: <YYYY-MM-DD HH:MM>
---

# Architecture Anchor: <project>

## End Goal (2 sentences max)

## Critical Invariants
(what must always be true — data integrity, ordering, consistency rules)

## Key Data Flow
(the main path data takes through the system, one level deep)

## Subsystems
(name · responsibility · key files)

## Known Danger Zones
(areas flagged in past reviews, fragile seams, known tech debt)

## Cross-cutting Concerns
(things to check in every subsystem: e.g. float vs Decimal, auth at wrong layer)
```

---

## Step 1: Subsystem Passes

With the anchor loaded, review each subsystem separately.
Anchor stays in context throughout — it is the big picture reference.

For each subsystem:
1. Read only that subsystem's files → mark each `[read]`
2. Apply the relevant checklist (arch or code below)
3. Check cross-cutting concerns from the anchor on every file
4. Note findings — do not write final output yet

Keep passes focused. Do not re-read files from other subsystems unless a dependency
requires it.

---

## Step 2: Synthesis Pass

After all subsystem passes, do one final pass with NO new file reads.
Input: all findings from subsystem passes only.

Check for:
- Issues that interact across subsystems (seam bugs)
- Findings that contradict each other
- Gaps at subsystem boundaries not caught in individual passes
- Update anchor `Known Danger Zones` with any new findings

---

## Mode A: Architecture Review

**Goal:** Is the design sound? Are upstream/downstream relationships correct?

### Checklist per subsystem
Circular dependencies · wrong layer ownership · interface contract mismatches ·
missing error propagation at boundaries · undocumented side effects · config/env assumptions ·
single points of failure · scalability assumptions baked in · auth/permissions at wrong layer ·
data ownership ambiguity

---

## Mode B: Code Review

**Goal:** Is the implementation correct, complete, and regression-safe?

### Steps per subsystem
1. Read changed files → mark each `[read]`
2. Read adjacent files (callers, dependents, shared utils) for regressions
3. Verify against task + plan — cite file+fn for every claim
4. Docs can be wrong — compare against actual code behavior, not comments or naming
5. Classify every issue: **Critical / Major / Minor / Nitpick**

### Checklist per subsystem
Null/empty/invalid input · boundary/off-by-one · auth/permissions · async/race conditions ·
stale cache · broken imports/exports · config/env/schema mismatch · backward compatibility ·
missing validation/error handling/cleanup · loading/error/empty states · test gaps ·
API contract · dead code/naming/complexity

---

## Output Templates

### Architecture Review output
```
# Architecture Review
## Anchor status (built / loaded / rebuilt)
## Subsystems reviewed
## Issues found per subsystem
(subsystem · file · fn/line · exact problem · severity)
## Seam issues (synthesis pass)
## Cross-cutting violations
## Verdict
```

### Code Review output
```
# Code Review
## Anchor status (built / loaded / rebuilt)
## Files checked
## Verified correct
## Issues found
(file · fn/line · exact problem · why wrong · severity)
## Seam issues (synthesis pass)
## Regression risks
## Nitpicks
## Verdict
```

### Combined output (both modes)
Run arch review block first, then code review block.
Add a final section:

```
# Combined Verdict
## Arch issues that affect code correctness
## Seam issues found in synthesis pass
## Overall recommendation
```
