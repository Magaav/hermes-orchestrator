# Semantic Router Pilot: Pruned

The disposable learned-example semantic router was tested on August 27, 2026
and removed before any production or MF-V7 integration.

The first 12-fixture set passed only after a generic negation fail-closed guard.
In one batched isolated-Codex reference call, the router matched the declared
policy on 12/12 fixtures at zero provider tokens while Codex matched 10/12 at
10,160 tokens. That set overlapped learned examples and did not establish
general semantic quality.

Four held-out paraphrases were then added. The router retained zero unsafe
misroutes but correctly routed only 1/4 held-out paraphrases. It therefore
failed the predeclared minimum 50% held-out coverage gate. No local semantic
embedding/model runtime was installed; the available ONNX artifacts were voice
models and were not repurposed.

A second candidate used one compact brokered GLM-5.2 call over the same frozen
16-fixture suite. It used 1,449 exact tokens, classified 15/16 overall, and
classified all four held-out paraphrases correctly. It nevertheless routed the
contradictory request `open the default cdp in a private disposable session`
to incognito instead of failing closed. That violated the predeclared zero
unsafe-misroute gate, so the executable candidate was removed. The bounded
negative receipt remains in `semantic-glm-result.json`; it is evidence, not a
loadable router.

A third candidate asked GLM to compile typed action, persistence, privacy,
negation, contradiction, and confidence facts before deterministic host
validation. With default thinking it exhausted 4,096 completion tokens without
emitting content. With the provider's documented thinking mode disabled, it
completed in one call using 1,283 exact tokens with zero reasoning tokens and
4/4 held-out accuracy. It still made two unsafe classifications: Calculator
control inspection became Windows application listing, and the contradictory
default/private CDP request again became incognito. The compiler code was
therefore pruned; `semantic-compiler-result.json` retains the bounded evidence.

Decision: prune all three natural-language candidates. Do not bootstrap MF-V7,
lower the safety gate, or add lexical conflict aliases from these experiments. The
isolated structured procedure registry remains only as evidence that exact
trusted intent contracts can reuse fresh-proof procedures after semantic
classification is solved by a future quality-proven mechanism.
