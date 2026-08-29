# MF-V7 Procedure Memory Pilot

Status: structured proof only; semantic router pruned. This is not the MF-V7
core, cannot be promoted, and is not loaded by production routing.

The pilot tests one thesis: a proof-complete V6 trajectory can be compiled into
a scoped declarative procedure, retrieved from a compact map in a later
session, executed without provider inference, and pruned when its environment
or fresh proof no longer matches.

The pilot deliberately does not solve natural-language intent classification.
Benchmarks report procedure-kernel provider calls separately from any future
semantic-router cost. A zero-call procedure result is not an end-to-end
zero-token claim until a production router proves the same intent safely.

Promotion requires two proof-complete observations. Matching is account-scoped,
requires an exact structured intent contract and exact environment/capability
digest, fails closed on ambiguity, and always requires a fresh receipt. Stored
procedures contain no prior answer, cookies, page data, or raw evidence.

Run:

```bash
python3 test_procedure_kernel.py
python3 benchmark.py
```

If the benchmark decision is `prune-pilot`, this directory has no production
consumer and can be removed without migrating V6 state.

Live fixture admission is deliberately narrower than full Windows authority.
`live_fixture.py` permits only top-level window listing, desktop capability
description, and the bounded Notepad UIA canary. A Windows screenshot fixture
is blocked until a generic proof-owned screen-capture primitive exists; the
pilot does not substitute unrestricted PowerShell for a missing contract.

The first admitted live Windows-list fixture completed with valid fresh proof
and no file changes, but consumed four provider calls and 75,893 tokens because
production performed redundant discovery and one rejected final-claim pass.
The pilot records that trajectory as a cold baseline and intentionally blocks
live repetition until either the compiled execution lane or the V6 one-call hot
path is active. Repeating a known-wasteful baseline is not learning.
