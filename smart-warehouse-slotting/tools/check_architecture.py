#!/usr/bin/env python3
"""Mechanical checks for ARCHITECTURE.md.

Convergence is a script, not a paragraph. This exits non-zero on any violated invariant,
so "the document is consistent" is a fact about a run.

Usage:
    python tools/check_architecture.py [path/to/ARCHITECTURE.md]

With no argument the checker looks for ARCHITECTURE.md beside the repo root, then in
../epoch_hackathon/ARCHITECTURE.md, so it works from the repo or from the docs tree.

Checks
  1  every §N reference resolves to a section heading
  2  register contiguous across open + closed tables; every cited ID exists
  3  the status line's open/closed counts match the tables
  4  every markdown table has consistent column counts
  5  every PROJECT.md requirement R1.1–R3.4 appears
  6  banned phrases (stale counts, withdrawn concepts, self-narration, completion claims)
  7  every target-only claim carries a local D-reference (section map)
  8  arithmetic identities between the document and the committed artifacts
  9  no withdrawn objective symbols; §9.0 symbol table present
 10  the stage table declares re-runnability
 11  headline claims stay inside what the artifacts support (overclaim list)
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = [
    HERE.parent / "ARCHITECTURE.md",                              # repo/tools -> repo/ARCHITECTURE.md
    HERE.parent.parent / "epoch_hackathon" / "ARCHITECTURE.md",   # repo/tools -> sibling docs tree
]
if len(sys.argv) > 1:
    DOC = Path(sys.argv[1])
else:
    seen: dict[Path, Path] = {}
    for p in CANDIDATES:
        if p.exists():
            seen.setdefault(p.resolve(), p)
    existing = list(seen.values())
    if len(existing) > 1:
        print("FAIL: two architecture documents found; refusing to guess which is canonical.")
        for p in existing:
            print(f"  - {p} ({len(p.read_text().splitlines())} lines)")
        print("Pass the canonical path explicitly.")
        sys.exit(2)
    DOC = existing[0] if existing else CANDIDATES[0]
REPO = Path("/home/hemanth/hackathon/SlotSense/smart-warehouse-slotting")
DATASET = Path("/home/hemanth/hackathon/epoch_hackathon/dataset/processed")

failures: list[str] = []
notes: list[str] = []


def fail(check: str, msg: str) -> None:
    failures.append(f"[{check}] {msg}")


def ok(check: str, msg: str) -> None:
    notes.append(f"[{check}] {msg}")


if not DOC.exists():
    print(f"FAIL: document not found at {DOC}")
    sys.exit(2)

text = DOC.read_text(encoding="utf-8")
lines = text.splitlines()

# A document without the register is not the reviewed architecture. Say so instead of
# returning a failure verdict that looks like a verdict on the right file.
if "## 16. Implementation backlog" not in text or "## 15. Conformance" not in text:
    print(f"FAIL: {DOC} lacks the conformance matrix (§15) or the implementation backlog (§16).")
    print("This is not the document this checker reviews. Pass the canonical path:")
    print("  python tools/check_architecture.py <path-to-reviewed-ARCHITECTURE.md>")
    sys.exit(2)

# ---------------------------------------------------------------- 1. section refs
sections = {m.group(1) for m in re.finditer(r"^#{2,3} (\d+)\.", text, re.M)}
refs = set(re.findall(r"§(\d+)(?:\.\d+)?", text))
dangling = sorted(refs - sections, key=int)
if dangling:
    fail("1", f"dangling section references: {dangling}")
else:
    ok("1", f"{len(refs)} section references resolve")

# ---------------------------------------------------------------- 2. deviations
def rows_in(start_heading: str, stop_prefixes: tuple[str, ...]) -> list[int]:
    start = next((i for i, l in enumerate(lines) if l.startswith(start_heading)), None)
    if start is None:
        return []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if any(lines[j].startswith(p) for p in stop_prefixes):
            end = j
            break
    found = []
    for line in lines[start:end]:
        m = re.search(r"\|\s*\*{0,2}D(\d+)\*{0,2}\s*\|", line)
        if m:
            found.append(int(m.group(1)))
    return found


open_rows = rows_in("## 16. Implementation backlog", ("### 16.4", "---"))
closed_rows = rows_in("### 16.4 Closed", ("---",))
all_rows = open_rows + closed_rows
refs_d = {int(x) for x in re.findall(r"\bD(\d+)\b", text)}

if not all_rows:
    fail("2", "no deviation rows found")
else:
    missing = sorted(refs_d - set(all_rows))
    if missing:
        fail("2", f"referenced but unregistered: {[f'D{n}' for n in missing]}")
    expected = list(range(1, max(all_rows) + 1))
    if sorted(all_rows) != expected:
        dupes = [n for n, c in Counter(all_rows).items() if c > 1]
        gaps = sorted(set(expected) - set(all_rows))
        fail("2", f"register not contiguous D1..D{max(all_rows)}: dupes={dupes} gaps={gaps}")
    else:
        ok("2", f"register contiguous D1..D{max(all_rows)} "
                f"({len(open_rows)} open, {len(closed_rows)} closed)")

# ---------------------------------------------------------------- 3. status counts
status = next((l for l in lines if l.startswith("**Backlog status:**")), "")
if not status:
    fail("3", "no backlog status line")
else:
    m = re.search(r"\*\*Backlog status:\*\*\s*\*{0,2}(\d+) open \((\d+) P0, (\d+) P1, (\d+) P2\), (\d+) closed", status)
    if not m:
        fail("3", "status line does not state '<n> open (<a> P0, <b> P1, <c> P2), <m> closed'")
    else:
        stated_open, p0, p1, p2, stated_closed = (int(m.group(i)) for i in range(1, 6))
        if stated_open != p0 + p1 + p2:
            fail("3", f"status says {stated_open} open but P0+P1+P2 = {p0 + p1 + p2}")
        if (stated_open, stated_closed) != (len(open_rows), len(closed_rows)):
            fail("3", f"status says {stated_open}/{stated_closed}, tables hold "
                      f"{len(open_rows)}/{len(closed_rows)}")
        else:
            ok("3", f"status counts match tables ({len(open_rows)} open, {len(closed_rows)} closed)")

# ---------------------------------------------------------------- 4. tables
blocks, cur = [], []
for i, line in enumerate(lines, 1):
    if line.strip().startswith("|"):
        cur.append((i, line))
    else:
        if len(cur) > 2:
            blocks.append(cur)
        cur = []
if len(cur) > 2:
    blocks.append(cur)
bad = [(b[0][0], sorted({len(l.strip().strip("|").split("|")) for _, l in b}))
       for b in blocks
       if len({len(l.strip().strip("|").split("|")) for _, l in b}) > 1]
if bad:
    fail("4", f"tables with inconsistent columns at {bad}")
else:
    ok("4", f"{len(blocks)} tables well-formed")

# ---------------------------------------------------------------- 5. requirements
reqs = ["R1.1", "R1.2", "R1.3", "R1.4", "R2.1", "R2.2", "R2.3", "R2.4", "R2.5", "R2.6",
        "R3.1", "R3.2", "R3.3", "R3.4"]
missing_reqs = [r for r in reqs if r not in text]
if missing_reqs:
    fail("5", f"requirements absent: {missing_reqs}")
else:
    ok("5", "all 14 requirements present")

# ---------------------------------------------------------------- 6. banned phrases
BANNED = {
    r"Two severities": "withdrawn severity model",
    r"\bThree verdicts\b": "stale verdict count",
    r"\bthree verdicts\b": "stale verdict count",
    r"all three true": "stale verdict count",
    r"\badvisory\b": "withdrawn severity class",
    r"earlier draft": "self-narration in a normative section",
    r"was wrong": "self-narration in a normative section",
    r"Nothing in §1–§14 is aspirational": "overreaching self-claim",
    r"converged": "prose completion claim",
    r"no issues": "prose completion claim",
    r"/home/hemanth": "machine-specific absolute path in a judge-facing document",
    r"graph radius": "CAT-01 uses 3-D Euclidean distance, not aisle-graph distance",
    r"pick face": "withdrawn CAT-01 construct",
    r"disagree by >2×": "retracted claim",
    r"feasible and structurally sound": "retracted claim (D34, D5)",
    r"defined four ways": "golden band has seven definition sites, two values",
    r"safety / segregation / structural": "stale verdict set (safety / policy / structural / integrity)",
    r"≈21k": "stale pick-line estimate (exactly 20,000)",
    r"reported, not gating": "a non-gating rule contradicts 'every rule blocking' (ADR-9)",
    r"`built`": "retired status word — use verified / implemented / partial / specified",
}
log_start = next((i for i, l in enumerate(lines) if l.startswith("## 19.")), len(lines))
for pattern, why in BANNED.items():
    hits = [i for i, l in enumerate(lines, 1)
            if re.search(pattern, l, re.I) and i - 1 < log_start]
    if hits:
        fail("6", f"banned /{pattern}/ at {hits} — {why}")
if not any(f.startswith("[6]") for f in failures):
    ok("6", "no banned phrases")

# ---------------------------------------------------------------- 7. backlog completeness
backlog_start = next((i for i, l in enumerate(lines) if l.startswith("## 16.")), None)
if backlog_start is None:
    fail("7", "§16 implementation backlog not found")
else:
    backlog_body = "\n".join(lines[backlog_start:])
    in_backlog = {int(m.group(1)) for m in re.finditer(r"\|\s*\*{0,2}D(\d+)\*{0,2}\s*\|", backlog_body)}
    missing_from_backlog = sorted(set(range(1, 49)) - in_backlog - {26})
    if missing_from_backlog:
        fail("7", f"deviations absent from the backlog: {[f'D{n}' for n in missing_from_backlog]}")
    else:
        ok("7", f"all {len(in_backlog) - len(closed_rows)} open deviations appear in §16 "
                f"({len(in_backlog)} rows incl. closed)")

# ---------------------------------------------------------------- 8. arithmetic
try:
    ev = json.loads((REPO / "outputs/evaluation/evaluation_summary.json").read_text())
    b, o = ev["baseline"], ev["optimized"]
    travel_delta = b["total_travel_distance_m"] - o["total_travel_distance_m"]
    cycle_delta = b["total_route_time_sec"] - o["total_route_time_sec"]
    assert abs(travel_delta / 1.3 - cycle_delta) < 0.01, "cycle identity broken"

    def non_depot(path: Path) -> int:
        with path.open() as f:
            return sum(1 for r in csv.DictReader(f)
                       if not r["location_id"].upper().startswith("DEPOT"))

    base_stops = non_depot(REPO / "outputs/evaluation/pick_route_stops_baseline.csv")
    opt_stops = non_depot(REPO / "outputs/evaluation/pick_route_stops_optimized.csv")
    stop_delta = base_stops - opt_stops
    stop_pct = 100 * stop_delta / base_stops

    def records(path: Path) -> tuple[int, int]:
        with path.open() as f:
            data = list(csv.DictReader(f))
        per = Counter(r["sku_id"] for r in data)
        return len(data), sum(1 for v in per.values() if v > 1)

    base_rec, base_multi = records(DATASET / "storage_assignments_baseline.csv")
    opt_rec, opt_multi = records(REPO / "outputs/optimized/optimized_assignments.csv")

    required_numbers = [
        (f"{base_stops:,}", "baseline charged stops"),
        (f"{opt_stops:,}", "optimized charged stops"),
        (f"{stop_delta:,}", "stop delta"),
        (f"{stop_pct:.1f}%", "stop delta %"),
        (f"{base_rec:,}", "baseline records"),
        (f"{opt_rec:,}", "optimized records"),
        (f"{base_multi}", "baseline multi-bin SKUs"),
        (f"{opt_multi}", "optimized multi-bin SKUs"),
    ]
    absent = [(n, why) for n, why in required_numbers if n not in text]
    if absent:
        fail("8", f"artifact figures absent: {absent}")
    else:
        ok("8", "charged stops, record counts and cycle identity match artifacts")
except Exception as exc:  # noqa: BLE001
    fail("8", f"could not verify arithmetic: {exc}")

# ---------------------------------------------------------------- 9. symbols
for token in ["| `A` affinity", "| `E` ergonomics", "With `S` SKUs"]:
    if token in text:
        fail("9", f"withdrawn/ambiguous symbol usage: {token!r}")
if not re.search(r"^### 9\.\d Symbols", text, re.M):
    fail("9", "no Symbols table in §9")
if not any(f.startswith("[9]") for f in failures):
    ok("9", "objective symbols disambiguated")

# ---------------------------------------------------------------- 10. stage table
if not any(l.startswith("| S") for l in lines):
    fail("10", "stage table not found")
elif "Re-runnable alone" not in text:
    fail("10", "stage table does not declare re-runnability")
else:
    ok("10", "stage re-runnability declared")

# ---------------------------------------------------------------- 11. overclaims
OVERCLAIMS = {
    r"mostly consolidation": "fragmentation split is unmeasured (D22); 2x2 design required",
    r"accounts for ≈−17\.2 pp": "the stop ratio is not independent evidence (D22)",
    r"byte-identical artifacts": "determinism is decision-level (I-11, D27)",
    r"term carrying ~99\.8%": "per-term decomposition is unpublished (D25)",
    r"limits never bind": "local slack is unmeasured (D24)",
    r"near-optimal for the term": "no bound exists (D39)",
}
for pattern, why in OVERCLAIMS.items():
    hits = [i for i, l in enumerate(lines, 1)
            if re.search(pattern, l) and not l.startswith("| **D")]
    if hits:
        fail("11", f"overclaim /{pattern}/ at {hits} — {why}")
if "difference-in-differences" not in text:
    fail("11", "the 2x2 fragmentation split must be described as difference-in-differences")
if "### 10.1 Assumptions" not in text:
    fail("11", "§10.1 must be titled 'Assumptions'")
if "**ID namespaces.**" not in text:
    fail("11", "no ID namespace rule (deviation vs data vector vs deliverable)")
if "## 15. Conformance" not in text:
    fail("11", "no conformance matrix (§15)")
if "## 16. Implementation backlog" not in text:
    fail("11", "no implementation backlog (§16)")
flat = " ".join(text.split())
close_match = re.search(r"Closing the P0 set is required before", flat)
if not close_match:
    fail("11", "the backlog must name the P0 set as the gate before publishing figures")
if not any(f.startswith("[11]") for f in failures):
    ok("11", "no overclaims outside the backlog; conformance and backlog sections present")

# ---------------------------------------------------------------- 12. catalogue + split
cat_start = next((i for i, l in enumerate(lines) if l.startswith("### 8.1")), None)
cat_end = next((i for i, l in enumerate(lines) if l.startswith("### 8.2")), len(lines))
if cat_start is None:
    fail("12", "§8.1 rule catalogue not found")
else:
    rows_c = [l for l in lines[cat_start:cat_end] if re.match(r"^\| `[A-Z]", l)]
    id_count = 0
    for line in rows_c:
        cell = line.split("|")[1]
        for m in re.finditer(r"[A-Z]+-(\d+(?:/\d+)*)", cell):
            id_count += len(m.group(1).split("/"))
    claim = re.search(r"\*\*(\d+) rules and (\d+) IDs\*\*", text)
    if not claim:
        fail("12", "no 'N rules and M IDs' statement")
    else:
        if int(claim.group(1)) != len(rows_c):
            fail("12", f"claims {claim.group(1)} families, table has {len(rows_c)}")
        if int(claim.group(2)) != id_count:
            fail("12", f"claims {claim.group(2)} IDs, table has {id_count}")
if "split-dataset" not in text:
    fail("12", "no split-dataset command (split must have one entry point)")
opt_line = next((l for l in lines if "app/main.py optimize" in l), "")
if "--time-split" in opt_line:
    fail("12", "optimize still splits internally (D46 leak)")
if "source_manifest.json" not in text:
    fail("12", "provenance manifest not specified")
if not any(f.startswith("[12]") for f in failures):
    ok("12", "catalogue counts, split entry point and provenance manifest consistent")

# ---------------------------------------------------------------- 13. conformance counts
conf_start = next((i for i, l in enumerate(lines) if l.startswith("## 15. Conformance")), None)
conf_end = next((i for i, l in enumerate(lines) if l.startswith("## 16.")), len(lines))
if conf_start is None:
    fail("13", "§15 conformance section not found")
else:
    conf_rows = [l for l in lines[conf_start:conf_end]
                 if re.match(r"^\|\s*(R\d\.\d|`PROJECT\.md`|provenance|EDA)", l)]
    counts = {"implemented": 0, "partial": 0, "specified": 0, "verified": 0}
    for row in conf_rows:
        cell = row.rstrip().rstrip("|").split("|")[-1].lower()
        for key in ("partial", "specified", "verified", "implemented"):
            if key in cell:
                counts[key] += 1
                break
    headline = re.search(
        r"Headline count: (\d+) implemented · (\d+) partial · (\d+) specified · (\d+) verified",
        " ".join(text.split()))
    if not headline:
        fail("13", "no headline status count in §15")
    else:
        stated = [int(headline.group(i)) for i in range(1, 5)]
        actual = [counts["implemented"], counts["partial"], counts["specified"], counts["verified"]]
        if stated != actual:
            fail("13", f"headline says {stated}, table counts {actual}")
        elif sum(actual) != len(conf_rows):
            fail("13", f"status counts sum to {sum(actual)}, table has {len(conf_rows)} rows")
        else:
            ok("13", f"conformance counts match the table ({sum(actual)} requirements)")


print(f"checking {DOC} ({len(lines)} lines)")
for n in notes:
    print("  ok  " + n)
if failures:
    print(f"\n{len(failures)} FAILURE(S)")
    for f in failures:
        print("  FAIL " + f)
    sys.exit(1)
print("\nall checks passed")
