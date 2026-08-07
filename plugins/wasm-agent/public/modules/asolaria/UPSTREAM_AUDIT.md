# ASOLARIA Upstream Sync Audit

Audited upstream commit:
`4a684b7f5f40be6c5b522e6baf1c1303f1a31491` (2026-07-27).

Previously imported commit:
`e2f11b93f3d2d1cd5e1e63661f25965f8e87e5f2`.

## Runtime identity

The current upstream `web/asolaria_tribit.wasm` is byte-identical to the
artifact already shipped by wasm-agent:

```text
b98abbbb10c1474558afcbb4dc3aa16d7bbf9d04e1fc40645c18440ca8c8cfd7
```

The Rust ABI did not change. The current source adds independent
cross-implementation receipt vectors and measurement programs, so replacing
the WASM would add no runtime value. wasm-agent instead validates all six
published vectors against the existing bytes.

## Ported contracts

- deterministic 3,078-byte receipts;
- six cross-implementation receipt vectors;
- chain, declared-count, and withheld-marker integrity roles;
- 81 four-axis receipt states with 27 AC states;
- a distinct 27-cell spatial lattice with 9 solid and 18 translucent cells;
- measurement wins over claim;
- matched controls are required;
- physics language without code and a receipt remains metaphor.

The two uses of thirds are intentionally separate. `27/81` describes AC
receipt states. `9/27` and `18/27` describe solid and translucent spatial
cells. Neither is a question-answer accuracy rule.

## Independent measurement

The upstream NumPy script was not directly runnable because this host has no
NumPy and the script contains an author-machine input path. A bounded
standard-library reproduction ran the identical displacement calculation
against upstream `matrices/FABLE5-SELF-SEED-3078.hbi` and 2,000 deterministic
uniform-random controls:

```text
seed bytes       3078
mean R1 delta    -0.16193321964153923
null mean        +0.0009566172416211365
null sigma       0.019557126475904765
z                -8.328924859377873
```

This independently supports the reported contraction measurement. It does not
establish physical gravity, semantic prediction, compression, or ASI.

## Verification limitation

`cargo test --locked` could not run because `cargo` is not installed on this
host. The shipped WASM was instead checked byte-for-byte and through the six
published receipt vectors. No Rust-build equivalence claim is made.

## Routing decision

The exact receipt and lattice functions remain inspectable candidates. The
actual-WASM QA extractor remains rejected after its sealed holdout failed to
add value. No ASOLARIA capability receives Master Frontier reasoning authority.
