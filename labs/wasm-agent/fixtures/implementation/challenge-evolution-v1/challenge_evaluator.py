"""Deterministic mutation evaluator for the challenge curriculum."""

from __future__ import annotations

from challenge_cases import CASES


def simulate(case, mode: str) -> list[bool]:
    limit, window, timestamps, _expected = case
    events: list[float] = []
    answers: list[bool] = []
    for now in timestamps:
        cutoff = now - window
        if mode == "inclusive_boundary": events = [value for value in events if value >= cutoff]
        elif mode == "never_expires": events = list(events)
        elif mode == "drops_latest": events = sorted((value for value in events if value > cutoff))[:-1]
        else: events = [value for value in events if value > cutoff]
        effective_limit = limit + 1 if mode == "off_by_one_capacity" else limit
        allowed = len(events) < effective_limit
        if mode == "records_denials" or allowed: events.append(now)
        answers.append(allowed)
    return answers


def evaluate() -> dict:
    if not isinstance(CASES, list) or not 1 <= len(CASES) <= 6:
        return {"ok": False, "code": "case_budget_invalid"}
    for case in CASES:
        if not isinstance(case, tuple) or len(case) != 4 or simulate(case, "reference") != case[3]:
            return {"ok": False, "code": "reference_rejected"}
    mutants = ("inclusive_boundary", "never_expires", "drops_latest", "off_by_one_capacity", "records_denials")
    killed = [mode for mode in mutants if any(simulate(case, mode) != case[3] for case in CASES)]
    return {"ok": len(killed) == len(mutants), "code": "ok" if len(killed) == len(mutants) else "mutants_survived", "killed": killed, "total": len(mutants), "cases": len(CASES)}


if __name__ == "__main__":
    import json
    result = evaluate()
    print(json.dumps(result, separators=(",", ":")))
    raise SystemExit(0 if result["ok"] else 1)
