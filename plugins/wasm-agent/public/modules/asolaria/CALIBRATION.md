# ASOLARIA Binary Calibration

The calibration lane extracts usable signal from a binary function only when
independent evidence shows that its errors are stable enough to transform.
It does not infer answers from receipt hashes and does not treat the operator's
one-third-right claim as measured accuracy.

Import a JSON array into **ASOLARIA Drills → Calibrate binary results**:

```json
[
  {
    "id": "train-001",
    "topic": "geometry",
    "split": "train",
    "expected": 1,
    "predicted": 0
  },
  {
    "id": "holdout-001",
    "topic": "geometry",
    "split": "holdout",
    "expected": 0,
    "predicted": 1
  }
]
```

Both values must be binary. IDs must be unique. A useful evaluation needs
balanced train and holdout cases distributed across the intended topics.

The default router permits `invert-binary-output` only when:

- train and holdout splits exist;
- the holdout has at least 30 cases and balanced labels;
- the direct 95% Wilson interval is below chance;
- the inverted 95% Wilson interval is above chance;
- train and holdout agree on the direction; and
- each holdout topic has at least 10 cases and inversion beats chance.

All other outcomes remain `hypothesis-only` with `authority=none`.

## Actual WASM Question Adapter

`qa-adapter.js` turns a question into UTF-8 bytes, runs the pinned ASOLARIA
WASM receipt, and applies the preregistered
`receipt-byte-0-lsb-v1` extractor. The extractor is deliberately fixed before
scoring: first receipt byte, least-significant bit. It is never selected by
searching the labeled holdout.

The deterministic arithmetic benchmark contains 360 balanced cases across
parity, comparison, and divisibility, with disjoint train and holdout values.
The actual pinned WASM result was:

- holdout direct: 99/180 (55%);
- holdout inverted: 81/180 (45%);
- train-derived majority baseline: 90/180 (50%); and
- decision: `no-added-value`, `authority=none`.

This falsifies the one-third-right inversion hypothesis for this extractor and
benchmark. It does not prove that every possible ASOLARIA-derived function is
useless, but it forbids routing this one into Master Frontier.
