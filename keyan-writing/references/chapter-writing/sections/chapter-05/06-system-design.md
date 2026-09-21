# System Design Scheme (cross-project override)

This specification has priority over the legacy project example for section 5.6.

## Dynamic structure

- Systems: confirmed current-project systems or domains.
- Order: confirmed source order and project-specific count.
- Depth: evidence-supported module, submodule, or function-point depth.
- Keep 5.6 as the fixed template section.
- Create 5.6.N only from systems or domains explicitly confirmed in the current source document.
- Preserve confirmed source order. The number of systems is not fixed.
- Copy or semantically reattach descendants according to source parent-child meaning and body evidence.
- Do not assume a fixed H3-H9 mapping and do not mechanically copy every visual heading level.
- Continue to module, submodule, or function-point level only when the current evidence supports that level.

## Evidence and reuse

- Provenance: current source keys, hashes, facts, tables, and sidecars.
- Gaps: explicit missing evidence that cannot be filled from another project.
- Prefer direct subtree reuse when the confirmed source node and target system are structurally equivalent.
- Use semantic migration when only part of the source subtree belongs to the target system.
- Treat a budget or function list as authoritative only when the current input actually provides one.
- Preserve source facts, quantities, names, tables, and descriptions. Record provenance in the sidecar.
- If a required item has no evidence, keep an explicit `GAP`; never fill it from another project.

## Completion checks

- Every 5.6.N title, order, and source key matches the current project-tree metadata.
- Draft source hashes and source keys match the current project anchors.
- Descendant depth reflects evidence semantics rather than a global depth target.
- No legacy project name, manual anchor, draft, or cached content is reused.
- Re-selecting systems or replacing the source invalidates old drafts and assembled output.
