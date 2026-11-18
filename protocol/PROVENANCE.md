# Provenance: protocol/acyclic-delegation.md

| | |
|---|---|
| Source repository | `acyclic-labs/sdk` (https://github.com/acyclic-labs/sdk), local clone `..\acyclic-sdk` |
| Path in source | `rust/crates/harness-core/src/seed/delegation.md` |
| Source HEAD when copied | `92fd2224148f58bb0b54dd7319f7e78c445db327` (`main`, pulled 2026-11-18) |
| Last commit changing the file | `3d38d4f51c9b340ed6a725445878758360b94893` (2026-11-14T07:00:33Z) |
| Git blob | `d9b9a8fa1d4325572ab1cb933b1e0320392cfef3` (497 bytes) |
| Licence | Apache License 2.0 (`LICENSE` at the source root; `rust/Cargo.toml`: `license = "Apache-2.0"`) |

**How it was copied.** The local clone is a sparse, partial checkout that does not write
`seed/` to disk, so the file was copied from the git object itself:
`git -C ../acyclic-sdk cat-file blob d9b9a8fa1d4325572ab1cb933b1e0320392cfef3 > protocol/acyclic-delegation.md`.
**Verified byte for byte:** `git hash-object --no-filters protocol/acyclic-delegation.md` gives
the same blob id. `.gitattributes` marks `protocol/**` as `-text`, so git never converts its line
endings.

**Licence files.** As Apache 2.0 requires when redistributing, the source's licence and notice are
copied beside it, byte for byte from the same commit:
`LICENSE-acyclic-sdk.txt` (blob `ca56a263be937bf1a1f225454c73746471619c66`) and
`NOTICE-acyclic-sdk.txt` (blob `82b6fb298ff178de317a6cf53536be4724292a1b`). The file is used
unmodified.

**Use here.** Replay R5 appends the file's full text, verbatim, to the frozen planner prompt under
the line `Delegation guidance:` (DECISIONS D37). In Acyclic's harness a child can read the
parent's files; in this harness a worker sees only its brief and its slice. So R5 tests their
guidance sentence inside this harness, not their system.
