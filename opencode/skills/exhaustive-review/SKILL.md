---
name: exhaustive-review
description: Use for code review, diff review, final review, correctness audits, lifecycle and concurrency analysis, user-action closure, and review synthesis. Supports single-review and multi-review workflows.
---

# Exhaustive Review

Review implementation as an independent correctness investigation. Delegation,
plans, changed-file lists, and tests are evidence—not complete scope or proof.
Finding one defect never ends an assigned audit. Continue through every
applicable dimension before reporting.

## Impact Radius

Trace beyond edited files:

- Inbound callers and outbound dependencies.
- Public contracts and all consumers.
- Shared-state readers and writers.
- Persistence, queues, workers, schedules, caches, events, and WebSockets.
- Frontend projections, invalidation, and visible postconditions.
- Operational cleanup, retries, recovery, and rollback.

## Required Matrices

Build the applicable rows before reaching a verdict.

### Authority Matrix

```text
state | authority | writers | readers | identity | TTL | cleanup owner
```

### Lifecycle Matrix

```text
resource | create | success | failure | retry | cancel | abort |
timeout | crash | hard kill | stale replacement | cleanup
```

### Action-Closure Matrix

```text
action | capability source | frontend request | backend validation |
state mutation | worker/broker effect | persistence effect |
projection refresh | visible postcondition
```

### Concurrency Matrix

```text
operation | duplicate | stale client | old/new occurrence |
partial mutation | retry | response loss | atomicity | idempotency
```

## Twelve Review Dimensions

1. Requirements, compatibility, and prohibited changes.
2. Architecture and source-of-truth ownership.
3. API, schema, caller, and consumer contracts.
4. Lifecycle completion and cleanup.
5. Concurrency, atomicity, ordering, and idempotency.
6. Cancellation, timeout, SIGTERM, crash, retry, and redelivery.
7. Authentication, authorization, secrets, and trust boundaries.
8. Data integrity, money, migrations, datetime, and scheduling.
9. Frontend asynchronous state, races, and stale responses.
10. User actions, capabilities, feedback, and visible postconditions.
11. Observability, partial failure, recovery, and operations.
12. Test fidelity, rollback, verification gaps, and residual risks.

Mark a dimension `not applicable` only with a concrete reason.

## Review Modes

### Single Review

One reviewer completes every applicable dimension and all four matrices.

### Specialist Review

Complete the delegated lens exhaustively. Follow boundaries into adjacent code
when needed to verify the lens. Never fix implementation. Continue after each
finding until the lens is complete.

Recommended lenses:

- Contract and impact.
- Lifecycle and concurrency.
- Frontend and user actions.
- Security, data, and operations.
- Tests and mock fidelity.

### Synthesis Review

Read the complete diff and every specialist report. Recheck high-risk
boundaries independently. Deduplicate findings, resolve contradictions from
code evidence, and freeze one canonical finding set before any fix begins.
Specialist reports do not replace direct inspection.

## Evidence Standard

- Cite exact file and line.
- State violated invariant, concrete impact, and reproducer or missing test.
- Distinguish verified defects from residual risks.
- Do not claim a pass when an applicable dimension or specialist audit failed,
  timed out, or remained unverified.

## Report

Project review artifacts are for humans first and automation second. Use clear
Markdown headings, short paragraphs, and tables. Explain impact and remediation
in plain language; do not leave readers to decode pipe-delimited lines. Keep the
canonical finding line under each finding for searchability and tooling.

```md
# Review: <descriptive title>

Timestamp: YYYY-MM-DD-HH-MM-SS (environment-local 24-hour time)
Mode: single | specialist:<lens> | synthesis
Scope: <human-readable scope>

## Executive Summary
<What changed, whether it is safe, and the most important consequence in 2-5
sentences.>

## Findings

### F1 — <plain-language title> (<severity>)

`file:line | severity | invariant violated | impact | reproducer/test`

**Impact:** <concrete user/system consequence>
**Evidence:** <code path, state transition, or reproducible scenario>
**Recommended remediation:** <specific fix direction>
**Regression coverage:** <test to add or update>

## Audit Coverage
dimension | evidence | result

## State and Action Coverage
resource/action | authorities | lifecycle paths | gaps

## Verification
command | result

## Residual Risks
risk | reason | recommended validation

## Verdict
**Pass** | **Fail**
```

Omit the Findings section only when there are no findings. Never omit the
executive summary, coverage, verification, residual risks, or verdict from a
written report.
