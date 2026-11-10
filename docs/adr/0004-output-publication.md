# 0004 — Staged, validated, no-clobber publication

- Status: accepted
- Date: 2026-11-09

## Context
Originals must never change; an existing valid copy must survive failures; several
instances may target the same output; removable drives often lack hard links (§4.3).

## Decision
1. Per-target lock file `.<copy>.searchify-lock` (`O_CREAT|O_EXCL`, host/pid/time).
   On the same host it is stale only when the owner process is gone (or its PID was
   reused by a later process) — a live owner is never overridden, however long its job
   runs. Locks from another host are stale once older than the maximum job timeout
   (24 h) plus 1 h; stale locks are
   renamed away atomically before re-creation, so two breakers cannot both win.
2. Engine output goes to a hidden staging file in the destination directory.
3. Validation: opens with pikepdf, same page count as the source, generator marker set.
4. Publication: overwrite → `os.replace` (atomic). Never-overwrite → `os.link` (fails if
   the target appeared). Without hard-link support → existence check + `rename` while
   holding the lock (safe against other Searchify instances, not foreign writers).
5. Destinations that are symlinks or alias the source (same inode, case-insensitive
   equality) are rejected. Staging leftovers of killed runs are removed under the lock.

## Consequences
Disk-full/permission errors leave the previous copy intact (tested). Tested filesystems:
ext4/tmpfs (CI) with a simulated no-hard-link fallback.
