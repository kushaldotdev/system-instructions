# Plan Framework

## Steps (ordered -- never skip, never reorder)
0. Interview user for intent. Ask clarifying questions about goal, scope, and requirements. Understand the full picture before planning.
1. Read AGENTS.md + relevant source files. Not from memory.
2. Map dependency graph: every file changed -> every file that depends on it.
3. Order by risk: highest-uncertainty changes first (fail fast).
4. Define interface contracts before touching any implementation.
5. For each phase: specify rollback strategy.
6. Present summary in chat. Bullet points: what, where, approach, phases, key risks.
7. Ask for confirmation. Do NOT write plan file until confirmed.
8. On confirmation + /do: write full plan to `.agents/plan/YYYY-MM-DD-<slug>.md`.
   Then gap-check: re-read plan vs task vs files. Fix vague/missing/risky steps before implement begins.
9. If session is large (~50 turns): offer checkpoint before switching to Implement.

## Output Template
```
# Plan
## Summary
## Phases
Phase N: <files> <exact changes> <risks> <rollback>
## Edge Cases
## Verification
```

# Review Heuristics

## Multi-Pass (run in sequence)
Pass 1 -- **Architecture**: Design sound? Layer violations? Contract mismatches?
Pass 2 -- **Data Flow**: Trace input -> transformation -> output. Data integrity preserved?
Pass 3 -- **Error Paths**: Every return that could be null/error/empty. What reaches the user? What leaks resources?
Pass 4 -- **Security**: Untrusted input paths. Auth at every boundary. Injection vectors.
Pass 5 -- **Readability**: First-time reader test. Confusing names? Missing context?

## Perspectives (apply to every pass)
- Security auditor: where could untrusted data reach sensitive operations?
- Adversarial: how would you intentionally break this?
- Performance: what scales poorly? N+1? Unbounded allocations? Sync in async path?
- User: what happens when things go wrong? Clear error messages? Recovery paths?

## State Analysis
For every function with branching logic, mentally test:
- Null/empty input
- Single-element input
- Typical input
- Boundary (max/min/overflow)
- Multiple edge conditions simultaneously true

## Cross-Boundary Audit
For every function/API boundary:
- List caller assumptions (input format, non-null guarantees, state preconditions)
- List callee guarantees (output format, error behavior, postconditions)
- Mark every mismatch. Every mismatch is a potential production bug.

## Language-Specific Gotchas

PHP: `==` vs `===` (always strict) | `unserialize()` on untrusted data = RCE risk | raw SQL interpolation = injection | use `$stmt->execute(['?'])` with `?` placeholders, never `PDO::query()` or string interpolation

Python: mutable default args (`def f(x=[])`) shared across calls | bare `except:` catches KeyboardInterrupt | late-binding closures in loops

JavaScript: `0.1 + 0.2 !== 0.3` | empty `catch {}` swallows all errors | ASI breaks `return \n value` => undefined

React/TypeScript: stale closures in useEffect/useCallback (list all deps) | state reads after setState are stale | array index as `key` breaks list stability

HTML/CSS: missing `alt` = accessibility failure | `z-index` without `position` is ignored | missing viewport meta breaks mobile layout

## Test-Based Review
Ask the user: "Do you want test-based analysis for this review?"
Only proceed if they say yes. Not the default.

## Session Checkpoint
When context is large (~50 turns), after Implement with verified changes, or after finding bugs in Review: offer to write a checkpoint. Read CHECKPOINT.md.template from config dir. Write to `.agents/state/YYYY-MM-DD-<slug>.md`. Ask user before writing.

## Output Template
```
# Review
## Files Checked
## Pass Results
Pass N: <finding> | <file:line> | <severity: critical/major/minor>
## Boundary Mismatches Found
## Language-Specific Issues
## Verdict
```
