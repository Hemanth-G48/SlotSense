# Phase Validation Prompts — Overview & How to Use

This folder contains a **validation prompt for every build phase** in `../` (phases 1–8). Each
validation prompt is written to be given to an AI agent (or a human reviewer) AFTER a build phase
completes. The validator inspects the phase's deliverables, runs its acceptance checks, and
produces a **confidence score** and a pass/fail verdict per artifact.

## What every validation prompt does

Given the phase's actual artifacts (code, outputs, configs) in the repo, each validator:

1. **Locates** the deliverables the phase was supposed to produce.
2. **Runs/verifies** each deliverable against the phase's stated acceptance criteria.
3. **Checks internal consistency** (schemas, units, naming, reproducibility).
4. **Scores** every deliverable and the overall phase.
5. **Outputs** a JSON report with per-artifact verdicts, evidence, and confidence.

## Confidence score protocol (used by every validator)

Score each deliverable on a **0–100** scale, where:

| Score | Meaning |
|---|---|
| 100–90 | Fully met; artifact exists, works, and passes every check with evidence. |
| 89–75 | Meets core intent; minor gaps or missing evidence, no functional breakage. |
| 74–50 | Substantially implemented but incomplete; one or more acceptance checks fail. |
| 49–25 | Partial/rough work; most checks fail or critical artifacts missing. |
| 24–0 | Absent or non-functional. |

Confidence is **per-deliverable** and aggregated for the phase as the weighted mean, where each
deliverable's weight is listed in the phase prompt.

### Mapping to a verdict

- **PASS (≥ 80):** phase is ready for the next build phase.
- **PARTIAL (50–79):** phase is usable but must be fixed before proceeding — list every failing
  check and required rework.
- **FAIL (< 50):** phase must be redone; do not proceed.

## Output format (every validator writes this)

Write a JSON file to `outputs/validation/phaseN_validation.json` (or the build phase's `outputs/`
dir) with this shape:

```json
{
  "phase": "01",
  "phase_name": "Project Scaffold & Warehouse Domain Model",
  "validated_at": "<timestamp>",
  "deliverables": [
    {
      "id": "D1.1",
      "name": "Repository scaffold",
      "weight": 0.1,
      "status": "PASS|PARTIAL|FAIL",
      "score": 0,
      "checks": [
        {"name": "structure present", "passed": true, "detail": "..."}
      ],
      "evidence": ["paths or snippet refs"],
      "gap": "what is missing or unverified"
    }
  ],
  "phase_score": 0,
  "phase_verdict": "PASS|PARTIAL|FAIL",
  "blocking_issues": ["..."]
}
```

The agent must cite **actual evidence** (file paths, command output, metric values) for every
claim. A check without evidence is scored as not-passed.

## How to run a phase validation

1. Give the validator prompt for phase N to an agent, pointing it at the repo state after phase N
   completes (or the whole repo if all phases are done — the validator only inspects phase-N
   artifacts).
2. The agent should actually run the phase's pipeline/tests/commands where feasible, and run the
   Phase-4 validator + Phase-6 simulation to cross-check optimizer and metric claims.
3. The agent writes the JSON report and a short prose summary (pass/fail per deliverable, top
   issues, recommended fixes).
4. Only advance past a phase when its validator returns **PASS**, or the listed issues are
   resolved and re-validated.

## Validation order note

Validation for the optimizer (Phase 5), evaluation (Phase 6), and dashboard (Phase 7) should
always re-run the Phase-4 validator and the metric definitions, because correctness in those
phases depends on them.