---
name: domain-modeling
description: Build and sharpen a project's domain model. Use when discussing codebase terminology, sharpening ambiguous language, or recording or editing an ADR.
disable-model-invocation: true
---

# Domain Modeling

Actively build and sharpen the project's domain model as you design. This is the *active* discipline: challenging terms, inventing edge-case scenarios, and writing the glossary and decisions down the moment they crystallise.

### Challenge inconsistent terms

When the user uses a term inconsistently with how they used it earlier in the conversation or in the code, call it out immediately. "You defined 'cancellation' as X earlier, but you seem to mean Y now. Which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account': do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible. Which is right?"

### Agree terms inline

When a term is resolved, state the agreed definition explicitly in the conversation so it's captured in the session's output. Don't batch these up: capture them as they happen.

### Offer ADRs sparingly

Only offer to create an ADR when all three are true:

1. **Hard to reverse**: the cost of changing your mind later is meaningful
2. **Surprising without context**: a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off**: there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).
