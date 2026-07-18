# Plan
- Parent only: clarify material ambiguity; subagents execute delegation.
- Read project guidance and affected code. Map callers, dependencies, contracts, risks, and rollback before changing behavior.
- Plan highest uncertainty first. State files, exact changes, risks, edge cases, verification, and deferred work.
- Parent asks approval only when plan approval is needed. Persist plan only on explicit request.
- Do not commit without approval. Review may require multiple rounds.
- Significant decision: compare 2+ options; state choice, tradeoff, change condition.
- Plan output: summary; phases (files, changes, risks, rollback); edges; verification.

# Review
Check, in order: architecture/contracts; data flow; null/error/empty paths; security boundaries; readability.
For branches: test empty, single, typical, boundary, and combined-edge states.
For boundaries: compare caller assumptions with callee guarantees.
Report findings first: `file:line | severity | impact`. No findings: state that, then testing gap.
Run focused available tests when useful. Ask only for costly, destructive, credentialed, or environment-dependent tests.
- Review output: files; pass findings; boundary mismatches; verdict.

# Debug And Verify
Reproduce. Minimize. Trace input to output. Test one hypothesis at a time. Fix root cause. Re-run reproducer and regression checks.
Before presenting: re-read diff, trace changed branches, check errors/types/imports, test relevant edge cases, check messages.

# Engineering
- Small focused changes. Preserve behavior until replacement is ready.
- New APIs/types: state exact contract, nullable/error behavior, and consumers.
- Migrations: state rollback and backfill cleanup.
- Prefer strict comparison, parameterized SQL, no mutable Python defaults, no empty JavaScript catches, stable React keys, and accessible HTML.
- Tests: one behavior per test, clear name, public contract and error paths covered.
