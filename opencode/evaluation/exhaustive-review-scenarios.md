# Exhaustive Review Evaluation Scenarios

Use these compact scenarios for manual prompt evaluation after changing the
review workflow. They are documented fixtures, not automated model tests.

## Procedure

1. Give reviewer only scenario change request and synthetic diff.
2. Run requested single review or deep review without hinting at defects.
3. Compare report against expected specialist lenses and expected findings.
4. Verify audit continues after first defect and synthesis performs finding
   freeze before any implementation fix.
5. Record missed findings, false positives, evidence quality, and residual risk.

## Scenario 1 — Distributed Abort

**Change:** Add UI Abort button backed by Redis running marker and Celery revoke.
Worker writes task ownership only for manual dispatch and removes marker in a
`finally` block.

**State authority:** Redis running lock and exact task-ID ownership marker.

**Expected specialist lenses:** contract/impact, lifecycle/concurrency,
frontend/actions, testing/mock fidelity.

**Expected findings:** automatic tasks cannot be revoked without task identity;
hard termination may bypass `finally` cleanup; stale occurrence must not clear
new owner; UI success requires refreshed visible stopped state.

## Scenario 2 — Purge and Retry

**Change:** Purge broker queue, then write cancellation markers and clear
ownership one item at a time.

**State authority:** broker list, cancellation marker, task ownership.

**Expected specialist lenses:** lifecycle/concurrency, security/data/operations,
testing/mock fidelity.

**Expected findings:** partial mutation can permit execution or orphan state;
operation needs atomicity or replay-safe idempotency; response loss and retry
must preserve action closure.

## Scenario 3 — Frontend Snapshot Race

**Change:** Modal loads REST data, receives WebSocket snapshots, and polls while
offline. Every response directly replaces component state.

**State authority:** newest server snapshot identified by generation and
snapshot timestamp.

**Expected specialist lenses:** contract/impact, frontend/actions,
lifecycle/concurrency, testing/mock fidelity.

**Expected findings:** stale response can overwrite newer WebSocket state;
closed modal can receive late updates; malformed records need runtime
validation; background failures must avoid repeated user notifications.

## Scenario 4 — Human-Readable Synthesis

**Change:** Three specialists report overlapping lifecycle defects with
different severity and wording.

**State authority:** source code and reproducible behavior, not majority vote.

**Expected specialist lenses:** synthesis review after all assigned audits.

**Expected findings:** synthesis deduplicates from evidence, resolves conflicts,
performs finding freeze, and writes a human-readable artifact with executive
summary, expanded impacts, remediation, coverage, residual risks, and verdict.
