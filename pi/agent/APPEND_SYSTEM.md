- Before starting a big task or moving to the next step, announce it in one line.

## No-Legacy Rule
Replacing = deleting in the same change (paths, params, keys, flags, tests) — never deprecate, no shims/aliases/dual-key/dual-write. Update all consumers + tests in the same commit, grep-sweep the removed name. External consumers or forced coexistence → explicit versioning, never silent fallback. Git history is the compatibility layer.
