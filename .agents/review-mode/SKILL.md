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

| Signal                                                                      | Mode                             |
| --------------------------------------------------------------------------- | -------------------------------- |
| Git diff present, "review changes", "check the PR", plan exists             | Code review                      |
| "review the architecture", "check the design", no diff, structural question | Arch review                      |
| Both signals, or no clear signal, or user says nothing specific             | **Both — arch first, then code** |

Arch first always. If the design is wrong, code correctness is irrelevant.

State selected mode at the top of your reply, e.g.:
`Review mode: Code` or `Review mode: Arch` or `Review mode: Both (arch first)`

---

## Mode A: Architecture Review

**Goal:** Is the design sound? Are upstream/downstream relationships correct?

### Steps

1. Read `AGENTS.md` → mark `[read]`
2. Identify the component/system being reviewed
3. **Trace upstream** — who calls this? what triggers it? what depends on its interface?
4. **Trace downstream** — what does it call? what does it depend on? what breaks if it changes?
5. Check contracts: API shape, data types, error handling at boundaries
6. Check for: tight coupling, missing abstractions, wrong ownership, hidden side effects
7. Assess: would a change here ripple? where? how bad?

### Arch checklist

Circular dependencies · wrong layer ownership · interface contract mismatches ·
missing error propagation at boundaries · undocumented side effects · config/env assumptions ·
single points of failure · scalability assumptions baked in · auth/permissions at wrong layer ·
data ownership ambiguity

---

## Mode B: Code Review

**Goal:** Is the implementation correct, complete, and regression-safe?

### Steps

1. Check if git repo: `git diff` or `git diff HEAD~1` to get changes. If no git → ask user which files changed.
2. Read every changed file → mark each `[read]`
3. Read adjacent files (callers, dependents, shared utils) for regressions
4. Verify against task + plan step by step — cite file+fn for every claim
5. Docs can be wrong — compare against actual code behavior, not comments or naming
6. Classify every issue by severity: **Critical / Major / Minor / Nitpick**

### Code checklist

Null/empty/invalid input · boundary/off-by-one · auth/permissions · async/race conditions ·
stale cache · broken imports/exports · config/env/schema mismatch · backward compatibility ·
missing validation/error handling/cleanup · loading/error/empty states · test gaps ·
API contract · dead code/naming/complexity

---

## Output Templates

### Architecture Review output

```
# Architecture Review
## Components traced
## Upstream (callers / dependents)
## Downstream (dependencies)
## Contract issues
## Coupling / ownership concerns
## Ripple risk
## Verdict
```

### Code Review output

```
# Code Review
## Files checked
## Verified correct
## Issues found
(file · fn/line · exact problem · why wrong · severity)
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
## Overall recommendation
```
