---
title: Mobile Sync Research
tags: [research, technical, project/alpha]
created: 2025-09-20
---

# Mobile Sync Research

Notes on offline-first sync strategies for Project Alpha.

## Options Considered

### CRDTs (Conflict-free Replicated Data Types)

Pros:
- No conflicts by design
- Works well for collaborative editing

Cons:
- Complex to implement correctly
- Memory overhead for large datasets

### Last-Write-Wins

Pros:
- Simple to implement
- Predictable behavior

Cons:
- Data loss possible
- Not suitable for collaborative scenarios

### Operational Transform

Pros:
- Well-understood (Google Docs uses it)

Cons:
- Complex, many edge cases
- Requires central server

## Recommendation

For inventory management, LWW with field-level granularity should be sufficient. Most edits are single-user. Add conflict detection UI for edge cases.

## Resources

- Martin Kleppmann's CRDT talk
- Figma engineering blog on multiplayer
