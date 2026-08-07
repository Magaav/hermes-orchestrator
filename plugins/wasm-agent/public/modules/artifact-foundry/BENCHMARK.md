# Artifact Foundry Stars/Shells Benchmark

Canonical vector:

- generator: `asolaria.stars-shells.v1`
- seed: 3,796 bytes, SHA-256 `d6e2153402a32eb9c4d2210e4513a906a1506b8f8e7a2d9a501cd83bcb9073ff`
- output: 4,596,880 bytes
- output SHA-256: `ae23392ad473718e2196e525a4355af20cdbd57bbb5dc3e85a8719b62552784d`

Measured 2026-07-27:

| Runtime | Pipeline | Duration | Result |
| --- | --- | ---: | --- |
| Production Chrome 150 | WASM pump and shell core + JS GGUF packager | 55 ms | exact |
| Cloud Node 18 | same browser module through VM-module harness | 216 ms | exact |
| Cloud Python 3 + NumPy | published reference generator in isolated venv | 2.59 s process wall time | exact |

The timings are directional, not a universal language/runtime comparison. The
Python number includes process startup and verbose reporting; the browser and
Node receipt durations cover generation and hashing after module load. All
three independently produced the same byte count and SHA-256.

This proves deterministic procedural generation across implementations. It
does not prove general compression, semantic intelligence, or regeneration of
arbitrary data.
