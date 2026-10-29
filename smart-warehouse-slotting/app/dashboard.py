"""Interactive warehouse slotting & optimization dashboard (Streamlit + Plotly).

Every number, chart, map and table is derived from the generated artifacts in
``../dataset/processed`` and ``outputs/`` through :mod:`app.dashboard_data`. Nothing is
hardcoded: missing backend data produces an explicit "data unavailable" state instead of a
fabricated result.

Run with: ``streamlit run app/dashboard.py``
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from app import dashboard_data as dd
except ModuleNotFoundError:  # streamlit run app/dashboard.py puts app/ on sys.path
    import dashboard_data as dd  # type: ignore[no-redef]

try:
    from app import phase5_views as p5v
except ModuleNotFoundError:  # streamlit run app/dashboard.py puts app/ on sys.path
    import phase5_views as p5v  # type: ignore[no-redef]

try:
    from app import phase6_registry as p6r
except ModuleNotFoundError:  # streamlit run app/dashboard.py puts app/ on sys.path
    import phase6_registry as p6r  # type: ignore[no-redef]

st.set_page_config(page_title="Smart Warehouse Slotting", page_icon="🏭", layout="wide")

PLOT_HEIGHT = 600
NEUTRAL = "#95a5a6"
ACCENT = "#2471a3"
BASELINE_COLOR = "#94a3b8"
OPTIMIZED_COLOR = "#2563eb"
GOOD = "#15803d"
BAD = "#b91c1c"
WARN = "#b45309"
BORDER = "#dbe3ec"
TEXT = "#0f2742"
MUTED = "#52637a"

pio.templates["hermes_ops"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family='-apple-system, "Segoe UI", Inter, Roboto, sans-serif', size=12, color=TEXT),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        colorway=[OPTIMIZED_COLOR, BASELINE_COLOR, GOOD, WARN, BAD, "#7c3aed", "#0891b2"],
        margin=dict(l=16, r=16, t=58, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        xaxis=dict(gridcolor="#edf2f7", zerolinecolor="#cbd5e1"),
        yaxis=dict(gridcolor="#edf2f7", zerolinecolor="#cbd5e1"),
    )
)
pio.templates.default = "plotly_white+hermes_ops"

_APP_CSS = f"""
<style>
:root {{
  --canvas: #f6f8fb;
  --surface: #ffffff;
  --border: {BORDER};
  --text: {TEXT};
  --muted: {MUTED};
  --blue: {OPTIMIZED_COLOR};
  --good: {GOOD};
  --bad: {BAD};
  --warn: {WARN};
}}
html, body, [class*="css"] {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
}}
.stApp {{ background: var(--canvas); }}
.block-container {{ max-width: 1480px; padding-top: 1.2rem; padding-bottom: 3rem; }}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
[data-testid="stAppDeployButton"], #MainMenu, footer {{ display: none !important; }}
h1, h2, h3 {{ color: var(--text); letter-spacing: -0.015em; }}
h2 {{ font-size: 1.28rem !important; margin-top: 1.35rem !important; }}
h3 {{ font-size: 1.02rem !important; }}
p, li {{ color: #26364a; }}
.hero {{ border-bottom: 1px solid var(--border); padding: 0 0 1rem 0; margin-bottom: .25rem; }}
.hero .eyebrow {{
  color: var(--blue); font-size: .74rem; font-weight: 800; letter-spacing: .11em;
  text-transform: uppercase; margin-bottom: .35rem;
}}
.hero h1 {{ font-size: 1.95rem; line-height: 1.15; margin: 0 0 .45rem 0; }}
.hero p {{ color: var(--muted); font-size: .92rem; max-width: 960px; margin: 0; }}
.section-label {{
  color: var(--text); font-size: .80rem; font-weight: 800; letter-spacing: .08em;
  text-transform: uppercase; margin: 1.15rem 0 .55rem 0;
}}
[data-testid="stSidebar"] {{ background: var(--surface); border-right: 1px solid var(--border); }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}
.sidebar-brand {{ font-size: .72rem; font-weight: 800; letter-spacing: .10em; color: var(--blue); text-transform: uppercase; }}
.sidebar-title {{ font-size: 1.05rem; font-weight: 750; color: var(--text); margin: .2rem 0 .7rem 0; }}
[data-testid="stMetric"] {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 13px 15px; min-height: 128px;
}}
[data-testid="stMetricLabel"] p {{
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
  font-size: .80rem !important; line-height: 1.3 !important; font-weight: 650 !important;
  color: var(--muted) !important; min-height: 2.1em;
}}
[data-testid="stMetricValue"] {{ font-size: 1.55rem !important; font-weight: 750 !important; color: var(--text) !important; }}
[data-testid="stMetricDelta"] {{ display: none !important; }}
.kpi-change {{
  display: inline-block; border-radius: 999px; padding: .12rem .48rem; font-size: .74rem;
  font-weight: 700; margin: .15rem 0 .05rem 0; border: 1px solid transparent;
}}
.kpi-change.good {{ color: #166534; background: #ecfdf3; border-color: #bbf7d0; }}
.kpi-change.bad {{ color: #991b1b; background: #fef2f2; border-color: #fecaca; }}
.kpi-change.neutral {{ color: #475569; background: #f1f5f9; border-color: #e2e8f0; }}
.kpi-baseline {{ color: var(--muted); font-size: .72rem; line-height: 1.35; }}
.status-strip {{
  border: 1px solid var(--border); border-radius: 10px; padding: .65rem .8rem; background: #fff;
  font-size: .84rem; color: var(--text);
}}
.stTabs [data-baseweb="tab-list"] {{ gap: .15rem; border-bottom: 1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{
  height: 2.55rem; padding: 0 .9rem; color: var(--muted); font-weight: 650; font-size: .86rem;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: var(--text); background: #f8fafc; }}
.stTabs [aria-selected="true"] {{ color: var(--blue) !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: var(--blue) !important; height: 3px !important; }}
div[data-testid="stExpander"] {{ border: 1px solid var(--border); border-radius: 10px; background: #fff; }}
div[data-testid="stExpander"] summary {{ font-weight: 650; color: var(--text); }}
[data-testid="stDataFrame"] {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}
[data-testid="stAlert"] {{ border-radius: 10px; }}
.stButton > button, .stDownloadButton > button {{
  border-radius: 8px; border: 1px solid #cbd5e1; font-weight: 650; color: #1e3a5f; background: #fff;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: var(--blue); color: var(--blue); }}
[data-testid="stSelectbox"] label p, [data-testid="stMultiSelect"] label p,
[data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p {{
  font-size: .79rem; font-weight: 650; color: var(--muted);
}}
[data-testid="stPlotlyChart"] {{ background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 4px; }}
@media (max-width: 900px) {{
  .block-container {{ padding-left: .8rem; padding-right: .8rem; }}
  .hero h1 {{ font-size: 1.55rem; }}
  [data-testid="stMetric"] {{ min-height: 112px; }}
}}
</style>
"""


def _safe_render(name: str, func, *args, **kwargs) -> None:
    """Keep one failed tab from taking down every later tab."""
    try:
        func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — boundary is deliberate
        logging.getLogger(__name__).exception("dashboard view failed: %s", name)
        st.error(
            f"**{name} could not be rendered.** The rest of the dashboard is still available. "
            "Refresh the page; if the problem persists, check the run logs and generated artifacts."
        )
        st.caption(f"Reference: {type(exc).__name__}. No partial result is shown as valid.")



# --------------------------------------------------------------------------- helpers
@st.cache_data(show_spinner="Loading generated warehouse outputs…")
def _load_cached() -> dict:
    return dd.load_all()


def load_all() -> dict:
    """Uncached loader (also used by tests)."""
    return dd.load_all()


def _num(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def fmt_number(value, digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    number = _num(value)
    if number is None:
        return str(value)
    return f"{number:,.{digits}f}"


_METRIC_UNITS = {
    "total_travel_distance_m": ("0", "m"),
    "avg_travel_distance_m": ("1", "m"),
    "avg_distance_per_order_m": ("1", "m"),
    "total_route_time_sec": ("0", "s"),
    "avg_route_time_sec": ("1", "s"),
    "avg_time_per_order_sec": ("1", "s"),
    "throughput_orders_per_hr": ("2", "orders/h"),
    "cube_utilization_pct": ("2", "%"),
    "golden_zone_demand_share_pct": ("2", "%"),
    "class_a_skus_outside_golden": ("0", "SKUs"),
    "affinity_separation_m": ("1", "m"),
    "constraint_violations": ("0", ""),
    "valid_assignments": ("0", ""),
    "required_assignments": ("0", ""),
    "assignment_feasibility_pct": ("2", "%"),
    "rule_check_pass_pct": ("2", "%"),
    "checks_run": ("0", ""),
}


def metric_text(key: str, value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    digits, unit = _METRIC_UNITS.get(key, ("2", ""))
    text = fmt_number(value, int(digits))
    return f"{text} {unit}".strip()


def change_label(row: dict) -> str:
    if not row.get("available", True):
        return "unavailable"
    kind = row.get("change_kind")
    if kind in ("reduction", "improvement") and row.get("change_pct") is None:
        # Zero (or missing) baseline: no percent change is mathematically defined.
        return "not defined (zero baseline)"
    if row.get("change_pct") is not None:
        value = row["change_pct"]
        if abs(value) < 0.005:
            return "no change"
        if kind == "reduction":
            return f"↓ {value:,.1f}% lower"
        return f"↑ {value:,.1f}% higher"
    if row.get("change_pp") is not None:
        value = row["change_pp"]
        return "no change" if abs(value) < 0.005 else f"{value:+,.2f} pp"
    if row.get("delta") is not None:
        value = row["delta"]
        if abs(value) < 1e-9:
            return "no change"
        unit = row.get("unit") or ""
        return f"{value:+,.0f}{(' ' + unit) if unit else ''}"
    return "not defined"


def change_tone(row: dict) -> str:
    """Semantic tone for a change badge; lower/higher is read from the metric definition."""
    if not row.get("available", True):
        return "neutral"
    kind = row.get("change_kind")
    if kind in ("reduction", "improvement"):
        return "good" if row.get("change_pct") not in (None, 0) else "neutral"
    delta = row.get("delta")
    if delta is None or abs(float(delta)) < 1e-9:
        return "neutral"
    direction = str(row.get("direction") or "").lower()
    if "lower" in direction:
        return "good" if float(delta) < 0 else "bad"
    if "higher" in direction:
        return "good" if float(delta) > 0 else "bad"
    return "neutral"


def _metric_badge_html(row: dict) -> str:
    return f'<span class="kpi-change {change_tone(row)}">{change_label(row)}</span>'


def _metric_note(row: dict) -> str:
    direction = row.get("direction") or ""
    return f"Baseline: {metric_text(row['key'], row['baseline'])} · {direction}".strip()


def _unavailable(reason: str, heading: str = "Data unavailable") -> None:
    st.warning(f"**{heading}.** {reason}")


def _selection_point(event) -> str | None:
    """Location id from a Plotly selection event, tolerating dict/attr shapes."""
    try:
        points = event["selection"]["points"]  # type: ignore[index]
    except (TypeError, KeyError, IndexError):
        try:
            points = event.selection.points  # type: ignore[attr-defined]
        except (AttributeError, TypeError, KeyError):
            return None
    if not points:
        return None
    point = points[0]
    try:
        custom = point["customdata"]
    except (TypeError, KeyError):
        custom = getattr(point, "customdata", None)
    if isinstance(custom, (list, tuple)):
        custom = custom[0] if custom else None
    return str(custom) if custom else None


def _class_legend_html(frame: pd.DataFrame) -> str:
    counts = frame["abc_class"].value_counts().to_dict()
    parts = []
    for cls in dd.CLASS_ORDER:
        color = dd.CLASS_COLORS[cls]
        parts.append(
            f"<span style='display:inline-block;margin-right:16px;font-size:13px'>"
            f"<span style='display:inline-block;width:11px;height:11px;background:{color};"
            f"border-radius:2px;margin-right:6px'></span>{dd.CLASS_DESCRIPTIONS[cls]} "
            f"<strong>({counts.get(cls, 0):,} bins)</strong></span>"
        )
    return "<div style='line-height:1.9'>" + "".join(parts) + "</div>"


# --------------------------------------------------------------------------- overview
_CARD_KEYS = [
    "total_travel_distance_m",
    "avg_travel_distance_m",
    "avg_distance_per_order_m",
    "total_route_time_sec",
    "avg_route_time_sec",
    "throughput_orders_per_hr",
    "cube_utilization_pct",
    "constraint_violations",
    "assignment_feasibility_pct",
    "golden_zone_demand_share_pct",
    "affinity_separation_m",
    "rule_check_pass_pct",
    "valid_assignments",
]

_KPI_GROUPS = (
    (
        "Flow and travel",
        ["total_travel_distance_m", "avg_travel_distance_m", "avg_distance_per_order_m", "throughput_orders_per_hr"],
    ),
    (
        "Time and service",
        ["total_route_time_sec", "avg_route_time_sec"],
    ),
    (
        "Safety and completeness",
        ["constraint_violations", "assignment_feasibility_pct", "rule_check_pass_pct", "valid_assignments"],
    ),
    (
        "Storage and ergonomics",
        ["cube_utilization_pct", "golden_zone_demand_share_pct", "affinity_separation_m"],
    ),
)


def _render_kpi_card(column, key: str, rows: dict) -> None:
    row = rows[key]
    if key == "valid_assignments":
        required = _num(rows.get("required_assignments", {}).get("optimized"))
        value = f"{fmt_number(row['optimized'])} / {fmt_number(required)}"
    else:
        value = metric_text(key, row["optimized"])
    with column:
        st.metric(row["label"], value, help=row.get("definition"))
        st.markdown(_metric_badge_html(row), unsafe_allow_html=True)
        st.markdown(f'<div class="kpi-baseline">{_metric_note(row)}</div>', unsafe_allow_html=True)


def _normalized_figure(rows: dict, keys: list[str]) -> go.Figure:
    labels, values, hovers = [], [], []
    for key in keys:
        entry = rows.get(key)
        if entry is None or not entry.get("available"):
            continue
        b, o = entry["baseline"], entry["optimized"]
        if b in (None, 0) or o is None:
            continue
        labels.append(entry["label"])
        values.append(o / b * 100.0)
        hovers.append(
            f"Baseline {metric_text(key, b)}<br>Optimized {metric_text(key, o)}<br>"
            f"{change_label(entry)}"
        )
    figure = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=[
                OPTIMIZED_COLOR if value <= 100 else "#b03a2e" for value in values
            ],
            text=[f"{value:.1f}" for value in values],
            textposition="outside",
            customdata=hovers,
            hovertemplate="%{y}<br>Index %{x:.1f} (baseline = 100)<br>%{customdata}<extra></extra>",
        )
    )
    figure.add_vline(x=100, line_dash="dash", line_color="#566573")
    figure.update_layout(
        title="Normalized comparison — index, baseline = 100 (lower is better except throughput)",
        height=360,
        margin=dict(l=10, r=20, t=60, b=20),
        xaxis_title="Index (baseline = 100)",
        showlegend=False,
    )
    return figure


def _bar_compare(rows: dict, key: str, title: str, height: int = 320) -> go.Figure | None:
    entry = rows.get(key)
    if entry is None or not entry.get("available"):
        return None
    b, o = entry["baseline"], entry["optimized"]
    if b is None or o is None:
        return None
    _, unit = _METRIC_UNITS.get(key, ("", ""))
    figure = go.Figure(
        go.Bar(
            x=["Baseline", "Optimized"],
            y=[b, o],
            marker_color=[BASELINE_COLOR, OPTIMIZED_COLOR],
            text=[metric_text(key, b), metric_text(key, o)],
            textposition="outside",
        )
    )
    figure.update_layout(
        title=f"{title} ({unit})" if unit else title,
        height=height,
        margin=dict(l=10, r=20, t=70, b=30),
        yaxis_title=unit or None,
        showlegend=False,
    )
    return figure


def _kpi_table(rows: dict) -> pd.DataFrame:
    records = []
    for key, label in dd.KPI_LABELS.items():
        row = rows.get(key)
        if row is None:
            continue
        records.append({
            "Metric": label,
            "Unit": _METRIC_UNITS.get(key, ("", ""))[1],
            "Baseline": metric_text(key, row["baseline"]),
            "Optimized": metric_text(key, row["optimized"]),
            "Absolute difference": metric_text(key, row["delta"]) if row["delta"] is not None else "—",
            "Change vs baseline": change_label(row),
            "Direction": row.get("direction") or "",
            "Definition": row.get("definition") or "",
        })
    return pd.DataFrame(records)


def render_overview(data: dict) -> None:
    metrics = data.get("metrics")
    if metrics is None:
        _unavailable(
            "Baseline/optimized evaluation metrics were not found. "
            "Run `python app/main.py run-all` to generate them.",
            "KPIs not yet calculated",
        )
        return

    rows = {row["key"]: row for row in dd.kpi_rows(metrics)}
    evaluation = data.get("eval_summary") or {}
    if evaluation.get("evaluation_status") == "BLOCKED_INFEASIBLE_LAYOUT":
        blocked = ", ".join(evaluation.get("blocked_layouts") or []) or "a layout"
        feasibility = evaluation.get("feasibility") or {}
        counts = ", ".join(
            f"{name}: {info.get('n_violations')} violations ({info.get('violations_by_rule')})"
            for name, info in sorted(feasibility.items())
        )
        st.error(
            "**Evaluation BLOCKED_INFEASIBLE_LAYOUT** — the independent validator found hard "
            f"violations in the {blocked} layout ({counts}). No baseline-vs-optimized comparison "
            "is published as evidence; the KPI cards below are diagnostic only."
        )
    st.subheader("Baseline vs optimized — operational KPIs")
    st.caption(
        "Same order workload, warehouse geometry, routing method and on-hand inventory in both "
        "layouts. Percent changes are computed from the baseline and optimized values shown. "
        "Utilization is reported in percentage points (pp)."
    )

    cards = [key for key in _CARD_KEYS if key in rows]
    for group_title, group_keys in _KPI_GROUPS:
        available_keys = [key for key in group_keys if key in cards]
        if not available_keys:
            continue
        st.markdown(f'<div class="section-label">{group_title}</div>', unsafe_allow_html=True)
        columns = st.columns(min(4, len(available_keys)))
        for column, key in zip(columns, available_keys):
            _render_kpi_card(column, key, rows)
    # Any metric not assigned to a group is still shown rather than silently dropped.
    grouped = {key for _, keys in _KPI_GROUPS for key in keys}
    leftovers = [key for key in cards if key not in grouped]
    if leftovers:
        st.markdown('<div class="section-label">Additional metrics</div>', unsafe_allow_html=True)
        columns = st.columns(min(4, len(leftovers)))
        for column, key in zip(columns, leftovers):
            _render_kpi_card(column, key, rows)

    # ---- safety verdict, only when validation actually ran -------------------
    verdict = dd.safety_status(data, "optimized")
    checks_run = verdict.get("checks_run", 0)
    if verdict["status"] == "PASS":
        st.success(
            f"**Safety compliance: PASS** — {checks_run:,} hard-constraint checks ran on the "
            f"optimized layout with 0 failures across all configured safety rules."
        )
    elif verdict["status"] == "FAIL":
        st.error(
            f"**Safety compliance: FAIL** — {verdict['failed_checks']:,} of {checks_run:,} checks "
            f"failed ({verdict['hard_violations']:,} high severity). "
            f"Rules: {', '.join(verdict['rules_failed']) or 'n/a'}. See the Constraints & Safety tab."
        )
    else:
        st.warning(f"**Safety compliance: not verified.** {verdict['reason']}")

    st.metric(
        "Safety compliance",
        verdict["status"],
        help="PASS is shown only when the validator ran on this layout and returned zero failed checks.",
    )
    st.caption(
        f"{checks_run:,} checks run" if checks_run else "No validation run recorded for this layout."
    )

    # ---- solver status ------------------------------------------------------
    st.subheader("Optimization run")
    optimization = data.get("opt_summary")
    if optimization:
        if optimization.get("execution_status") == "ERROR":
            st.error(f"Optimization run failed: {optimization.get('error')}")
        cols = st.columns(4)
        cols[0].metric(
            "Solver status",
            optimization.get("feasibility_status")
            or ("FEASIBLE" if optimization.get("feasibility") else "INFEASIBLE"),
        )
        cols[1].metric("Optimization runtime", f"{fmt_number(optimization.get('runtime_sec'), 2)} s")
        cols[2].metric("Moves evaluated", fmt_number(optimization.get("moves_evaluated")))
        cols[3].metric("Globally optimal", "No" if not optimization.get("globally_optimal") else "Yes")
        st.caption(
            f"Algorithm: {optimization.get('algorithm', 'n/a')} · "
            f"stopping reason: {optimization.get('stopping_reason', 'n/a')} · "
            f"objective {fmt_number(optimization.get('final_objective'), 1)} "
            f"(baseline {fmt_number(optimization.get('baseline_objective'), 1)})."
        )
        repair = optimization.get("repair") or {}
        if repair:
            st.caption(
                f"Repair: {repair.get('initial_violations', 'n/a')} → "
                f"{repair.get('final_violations', 'n/a')} violations · "
                f"{repair.get('termination_reason', 'n/a')} · accepted "
                f"{repair.get('moves_accepted', 0)}/{repair.get('moves_attempted', 0)} candidate moves."
            )
        completion = optimization.get("assignment_completeness") or {}
        if completion:
            st.caption(
                f"Assignment completeness: {fmt_number(completion.get('units_placed'))} / "
                f"{fmt_number(completion.get('units_required'))} units "
                f"({completion.get('completeness_pct', 'n/a')}%)."
            )
    else:
        _unavailable("No optimization summary found. Run `python app/main.py optimize` first.")

    # ---- comparison charts --------------------------------------------------
    st.subheader("Comparison charts")
    st.plotly_chart(
        _normalized_figure(
            rows,
            [
                "avg_travel_distance_m",
                "avg_distance_per_order_m",
                "total_route_time_sec",
                "avg_route_time_sec",
                "avg_time_per_order_sec",
                "affinity_separation_m",
            ],
        ),
        width="stretch",
    )
    st.caption(
        "Each bar is a separate metric normalized to its own baseline (100). They are not additive "
        "and no unit-mixing scale is implied; absolute values with units are in the table below."
    )
    chart_cols = st.columns(3)
    with chart_cols[0]:
        figure = _bar_compare(rows, "throughput_orders_per_hr", "Throughput")
        if figure is not None:
            st.plotly_chart(figure, width="stretch")
            entry = rows["throughput_orders_per_hr"]
            st.caption(f"{change_label(entry)} · definition: {entry.get('definition', '')}")
    with chart_cols[1]:
        figure = _bar_compare(rows, "cube_utilization_pct", "Cube utilization")
        if figure is not None:
            st.plotly_chart(figure, width="stretch")
            entry = rows["cube_utilization_pct"]
            st.caption(
                f"Change {change_label(entry)}. Occupied inventory volume / usable storage volume; "
                "both layouts hold the same on-hand inventory, so no change is expected."
            )
    with chart_cols[2]:
        figure = _bar_compare(rows, "golden_zone_demand_share_pct", "Golden-zone demand share")
        if figure is not None:
            st.plotly_chart(figure, width="stretch")
            entry = rows["golden_zone_demand_share_pct"]
            st.caption(f"Change {change_label(entry)}. Demand-weighted units stored on golden shelf levels.")

    # ---- full table ---------------------------------------------------------
    st.subheader("All comparative metrics")
    st.dataframe(_kpi_table(rows), hide_index=True, width="stretch")

    with st.expander("Formulas, definitions and evaluation conditions"):
        st.markdown(
            "- **Travel-distance reduction (%)** = `(baseline distance − optimized distance) / baseline distance × 100`\n"
            "- **Route-time reduction (%)** = `(baseline time − optimized time) / baseline time × 100`\n"
            "- **Cube utilization (%)** = `occupied inventory volume / total usable storage volume × 100`\n"
            "- **Utilization change** = `optimized utilization (%) − baseline utilization (%)`, in percentage points\n"
            "- **Assignment feasibility (%)** = `valid assignments / required assignments × 100`; a required assignment is a "
            "SKU holding on-hand inventory, valid when the entire quantity is placed and no validation check for it failed\n"
            "- **Golden-zone demand share (%)** = `Σ(demand × units) on golden shelf levels / Σ(demand × units) placed × 100`\n"
            "- Zero denominators are reported as “not defined” instead of being divided.\n"
            "- Cube utilization is a volume-based approximation using SKU bounding-box volumes, not an exact 3-D packing result."
        )
        assumptions = (data.get("eval_summary") or {}).get("assumptions") or {}
        if assumptions:
            st.json(assumptions)
        notes = (data.get("eval_summary") or {}).get("notes") or {}
        if notes:
            st.caption(
                f"Validation: baseline {notes.get('baseline_constraint_violations', 'n/a')} violations, "
                f"optimized {notes.get('optimized_constraint_violations', 'n/a')} violations; "
                f"same inventory units: {notes.get('same_inventory_units', 'n/a')}."
            )


# --------------------------------------------------------------------------- layout figures
# --------------------------------------------------------------------------- layout figures
def _rack_side_name(rack_id: str) -> str:
    """Returns human-readable side (South, North, West, East) for 3x3 zone edge racks."""
    r = str(rack_id)
    if "-1-1" in r:
        return "South"
    if "-1-2" in r:
        return "North"
    if "-2-1" in r:
        return "West"
    if "-2-2" in r:
        return "East"
    return "Edge rack"


def overview_figure(locations, dispatch=None):
    """Warehouse boundary + dispatch point overview in the recorded coordinates."""
    figure = go.Figure()
    if locations is None or locations.empty:
        figure.update_layout(title="Warehouse overview (no topology)", height=PLOT_HEIGHT)
        return figure
    x = pd.to_numeric(locations["x_m"], errors="coerce")
    y = pd.to_numeric(locations["y_m"], errors="coerce")
    pad = 2.0
    x0, x1 = float(x.min()) - pad, float(x.max()) + pad
    y0, y1 = float(y.min()) - pad, float(y.max()) + pad
    figure.add_shape(
        type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
        line=dict(color="#1a252f", width=2.5), fillcolor="#f8f9f9", layer="below",
    )
    if dispatch is not None:
        figure.add_trace(go.Scatter(
            x=[dispatch[0]], y=[dispatch[1]], mode="markers+text", name="Dispatch / I-O",
            marker=dict(symbol="star", size=18, color="#f1c40f", line=dict(width=1, color="#7d6608")),
            text=["I-O"], textposition="bottom center",
        ))
    figure.update_layout(
        title="Warehouse overview — recorded coordinate extent", height=PLOT_HEIGHT,
        margin=dict(l=10, r=10, t=60, b=40),
    )
    figure.update_xaxes(title="x (m, stretched display)", range=[x0, x1], showgrid=False)
    figure.update_yaxes(title="y (m)", range=[y0, y1], showgrid=False)
    return figure


def warehouse_plan_figure(
    locations: pd.DataFrame | None,
    selected_zone: str = "Z1",
    selected_rack: str | None = None,
    dispatch: tuple[float, float] | None = None,
    ruler_overlay: dict | None = None,
    racks: pd.DataFrame | None = None,
    title: str = "Warehouse plan — actual zone extents",
) -> go.Figure:
    """Truthful plan view built from recorded coordinates, not an invented 3x3 box.

    The processed dataset stores zones as sequential 17 m bands along Y (total extent
    ~174 m), so a 40.8 x 40.8 m matrix would misplace every bin. Zone boxes below are
    the min/max extents of the recorded bin footprints; the display aspect is stretched.
    """
    figure = go.Figure()
    if locations is None or locations.empty:
        figure.update_layout(title=title or "Warehouse plan (no data)", height=520)
        return figure
    data = locations.copy()
    data["_x0"] = pd.to_numeric(data["x_m"], errors="coerce") - pd.to_numeric(data["width_cm"], errors="coerce").fillna(0) / 200.0
    data["_x1"] = pd.to_numeric(data["x_m"], errors="coerce") + pd.to_numeric(data["width_cm"], errors="coerce").fillna(0) / 200.0
    data["_y0"] = pd.to_numeric(data["y_m"], errors="coerce") - pd.to_numeric(data["depth_cm"], errors="coerce").fillna(0) / 200.0
    data["_y1"] = pd.to_numeric(data["y_m"], errors="coerce") + pd.to_numeric(data["depth_cm"], errors="coerce").fillna(0) / 200.0
    zones = data.groupby("zone_id", as_index=False).agg(
        x0=("_x0", "min"), x1=("_x1", "max"), y0=("_y0", "min"), y1=("_y1", "max"),
        bins=("location_id", "nunique"),
    )
    for row in zones.itertuples(index=False):
        is_selected = str(row.zone_id) == str(selected_zone)
        figure.add_shape(
            type="rect", x0=row.x0, x1=row.x1, y0=row.y0, y1=row.y1,
            line=dict(color="#2563eb" if is_selected else "#94a3b8", width=2.2 if is_selected else 1),
            fillcolor="#e8f1fb" if is_selected else "#f8fafc", layer="below",
        )
        figure.add_annotation(
            x=(row.x0 + row.x1) / 2, y=(row.y0 + row.y1) / 2,
            text=f"<b>{row.zone_id}</b><br>{int(row.bins):,} bins",
            showarrow=False, font=dict(size=11, color="#0f2742"),
        )
    if racks is not None and not racks.empty:
        zone_racks = racks[racks["zone_id"].astype(str) == str(selected_zone)]
        for row in zone_racks.itertuples(index=False):
            is_rack = str(row.rack_id) == str(selected_rack)
            figure.add_shape(
                type="rect", x0=row.x_min, x1=row.x_max, y0=row.y_min, y1=row.y_max,
                line=dict(color="#b45309" if is_rack else "#64748b", width=2 if is_rack else 0.7),
                fillcolor="#f59e0b" if is_rack else "#cbd5e1", layer="above",
            )
    if dispatch is not None:
        figure.add_trace(go.Scatter(
            x=[dispatch[0]], y=[dispatch[1]], mode="markers+text", name="Dispatch / I-O",
            marker=dict(symbol="star", size=16, color="#f59e0b", line=dict(width=1, color="#92400e")),
            text=["Dispatch / I-O"], textposition="bottom center",
            hovertemplate="Dispatch point (%{x:.1f}, %{y:.1f}) m<extra></extra>",
        ))
    if ruler_overlay is not None and ruler_overlay.get("xs") and ruler_overlay.get("ys"):
        xs, ys = ruler_overlay["xs"], ruler_overlay["ys"]
        figure.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers", name=f"Measured corridor path ({ruler_overlay.get('distance', 0)} m)",
            line=dict(color="#0891b2", width=3), marker=dict(size=5, color="#0891b2"),
            hovertemplate="Waypoint (%{x:.1f}, %{y:.1f}) m<extra></extra>",
        ))
        figure.add_trace(go.Scatter(
            x=[xs[0]], y=[ys[0]], mode="markers+text", name="Start",
            marker=dict(size=11, color="#15803d", symbol="circle"), text=["Start"], textposition="top center",
        ))
        figure.add_trace(go.Scatter(
            x=[xs[-1]], y=[ys[-1]], mode="markers+text", name="End",
            marker=dict(size=11, color="#b91c1c", symbol="square"), text=["End"], textposition="top center",
        ))
    x0 = float(zones["x0"].min()) - 0.6
    x1 = float(zones["x1"].max()) + 0.6
    y0 = float(zones["y0"].min()) - 2.0
    y1 = float(zones["y1"].max()) + 2.0
    figure.update_layout(
        title=title, height=520, margin=dict(l=12, r=12, t=54, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
    )
    figure.update_xaxes(title="x (m, stretched display)", range=[x0, x1], showgrid=False)
    figure.update_yaxes(title="y (m)", range=[y1, y0], showgrid=False)
    return figure


def plan_figure(
    frame: pd.DataFrame,
    racks: pd.DataFrame,
    aisles: pd.DataFrame,
    dispatch: tuple[float, float] | None,
    selected_id: str | None,
    color_mode: str = "ABC class",
    title: str = "",
    zone_box=None,
    cross_box=None,
    route_overlay=None,
    show_ids: bool = False,
) -> go.Figure:
    """True-coordinate plan view built from topology: rack footprints, aisle bands, bins."""
    figure = go.Figure()
    for row in aisles.itertuples(index=False):
        figure.add_shape(
            type="rect", x0=row.x_min, x1=row.x_max, y0=row.y_min, y1=row.y_max,
            line=dict(width=0), fillcolor="#f2f4f6", layer="below",
        )
    for row in racks.itertuples(index=False):
        figure.add_shape(
            type="rect", x0=row.x_min, x1=row.x_max, y0=row.y_min, y1=row.y_max,
            line=dict(color="#7f8c8d", width=1), fillcolor="#e5e8eb", layer="below",
        )

    if color_mode == "ABC class":
        for cls in dd.CLASS_ORDER:
            subset = frame[frame["abc_class"] == cls]
            if subset.empty:
                continue
            figure.add_trace(go.Scatter(
                x=subset["x_m"], y=subset["y_m"], mode="markers",
                name=f"Class {cls}" if cls != "unassigned" else "Unassigned",
                marker=dict(symbol="square", size=9, color=dd.CLASS_COLORS[cls], line=dict(width=0.5, color="#ffffff")),
                customdata=subset[["location_id", "sku_id"]].astype(str).values,
                hovertemplate=(
                    f"Class {cls}<br>%{{customdata[0]}}<br>SKU %{{customdata[1]}}<extra></extra>"
                ),
            ))
    elif color_mode == "Utilization":
        figure.add_trace(go.Scatter(
            x=frame["x_m"], y=frame["y_m"], mode="markers", name="Bin volume utilization",
            marker=dict(
                symbol="square", size=9,
                color=pd.to_numeric(frame["bin_volume_util_pct"], errors="coerce").fillna(0.0),
                colorscale="Blues", cmin=0, cmax=100, showscale=True,
                colorbar=dict(title="% used"),
                line=dict(width=0.5, color="#ffffff"),
            ),
            customdata=frame[["location_id", "sku_id", "bin_volume_util_pct"]].astype(str).values,
            hovertemplate="%{customdata[0]}<br>SKU %{customdata[1]}<br>Utilization %{customdata[2]}%<extra></extra>",
        ))
    elif color_mode == "Constraint status":
        colors = {"OK": "#27ae60", "FAIL": "#c0392b", "UNKNOWN": "#b3b6b7"}
        for status in ("OK", "FAIL", "UNKNOWN"):
            subset = frame[frame["constraint_status"] == status]
            if subset.empty:
                continue
            figure.add_trace(go.Scatter(
                x=subset["x_m"], y=subset["y_m"], mode="markers",
                name=f"Validation: {status}",
                marker=dict(symbol="square", size=9, color=colors[status], line=dict(width=0.5, color="#ffffff")),
                customdata=subset[["location_id", "failed_rules"]].astype(str).values,
                hovertemplate="%{customdata[0]}<br>Failed rules: %{customdata[1]}<extra></extra>",
            ))
    else:  # assignment change
        colors = {True: "#8e44ad", False: "#b3b6b7"}
        for changed in (True, False):
            subset = frame[frame["changed"] == changed]
            if subset.empty:
                continue
            figure.add_trace(go.Scatter(
                x=subset["x_m"], y=subset["y_m"], mode="markers",
                name="SKU changed vs baseline" if changed else "SKU unchanged",
                marker=dict(symbol="square", size=9, color=colors[changed], line=dict(width=0.5, color="#ffffff")),
                customdata=subset[["location_id", "baseline_sku", "optimized_sku"]].astype(str).values,
                hovertemplate="%{customdata[0]}<br>Baseline %{customdata[1]}<br>Optimized %{customdata[2]}<extra></extra>",
            ))

    if selected_id is not None and not frame.empty:
        selected = frame[frame["location_id"].astype(str) == str(selected_id)]
        if not selected.empty:
            figure.add_trace(go.Scatter(
                x=selected["x_m"], y=selected["y_m"], mode="markers", name="Selected bin",
                marker=dict(symbol="circle-open", size=20, color="#111111", line=dict(width=3)),
                hoverinfo="skip", showlegend=False,
            ))
    if dispatch is not None:
        figure.add_trace(go.Scatter(
            x=[dispatch[0]], y=[dispatch[1]], mode="markers+text", name="Dispatch / I-O",
            marker=dict(symbol="star", size=16, color="#f1c40f", line=dict(width=1, color="#7d6608")),
            text=["Dispatch / I-O"], textposition="top center",
            hovertemplate="Configured dispatch point<br>(%{x:.1f}, %{y:.1f}) m<extra></extra>",
        ))
    # optional zone boundary / cross-aisle bands (used by the layout view)
    if zone_box is not None:
        try:
            zx0, zx1, zy0, zy1 = zone_box
            figure.add_shape(
                type="rect", x0=zx0, x1=zx1, y0=zy0, y1=zy1,
                line=dict(color="#2c3e50", width=1.5), fillcolor="rgba(0,0,0,0)", layer="below",
            )
        except (TypeError, ValueError):
            pass
    if cross_box is not None:
        try:
            if len(cross_box) == 2:
                cx0, cx1 = cross_box
                ys = pd.to_numeric(frame["y_m"], errors="coerce")
                cy0, cy1 = float(ys.min()), float(ys.max())
            else:
                cx0, cx1, cy0, cy1 = cross_box
            figure.add_shape(
                type="rect", x0=cx0, x1=cx1, y0=cy0, y1=cy1,
                line=dict(width=0), fillcolor="#dfe6e9", layer="below",
            )
        except (TypeError, ValueError):
            pass

    # route overlay (pick path) drawn on top of the warehouse layout
    if route_overlay is not None:
        try:
            ro = route_overlay
            xs = ro["x_m"] if not ro.empty else []
            ys = ro["y_m"] if not ro.empty else []
            labels = ["" if str(s) == "DEPOT" else str(s) for s in ro.get("sequence", [])] if not ro.empty else []
            figure.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", name="Route sequence",
                line=dict(color=ACCENT, width=2, dash="dot"),
            ))
            figure.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers+text", name="Pick stops",
                marker=dict(size=9, color="#2471a3", line=dict(width=1, color="#ffffff")),
                text=labels, textposition="top center",
            ))
        except Exception:
            pass

    if show_ids and not frame.empty and "location_id" in frame.columns:
        figure.add_trace(go.Scatter(
            x=frame["x_m"], y=frame["y_m"], mode="text", name="Bin ids",
            text=frame["location_id"].astype(str), textposition="bottom center",
            showlegend=False,
        ))

    figure.update_layout(
        title=title,
        height=PLOT_HEIGHT,
        margin=dict(l=10, r=10, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        plot_bgcolor="#ffffff",
    )
    figure.update_xaxes(title="x (m, stretched display)", showgrid=False)
    figure.update_yaxes(title="y (m)", showgrid=False)
    return figure


def elevation_figure(
    frame: pd.DataFrame,
    selected_id: str | None,
    golden_levels: list[int],
    color_mode: str = "ABC class",
    title: str = "",
) -> go.Figure:
    """Rack elevation: renders one whole side of a zone (8 bays x 4 shelves = 64 bins).

    Physical boxes displaying items in rows of racks are linearly sized according to
    the item's dimensions (width x height) relative to the bin dimensions.
    """
    figure = go.Figure()
    if frame is None or frame.empty:
        figure.update_layout(title=title or "Rack elevation (no data)", height=PLOT_HEIGHT)
        return figure

    data_frame = frame.copy()
    data_frame["shelf_level"] = pd.to_numeric(data_frame["shelf_level"], errors="coerce").fillna(0).astype(int)
    slots = sorted({(int(row.bay), float(row.x_m)) for row in data_frame.itertuples(index=False)})
    slot_index = {slot: index for index, slot in enumerate(slots)}
    data_frame["slot"] = [slot_index[(int(r.bay), float(r.x_m))] for r in data_frame.itertuples(index=False)]
    max_slot = max(len(slots) - 1, 0)
    levels = sorted(data_frame["shelf_level"].unique())
    if not levels:
        levels = [0, 1, 2, 3]

    # 1. Golden shelf level background highlight
    for level in levels:
        if level in golden_levels:
            figure.add_shape(
                type="rect", x0=-0.6, x1=max_slot + 0.6, y0=level - 0.46, y1=level + 0.46,
                line=dict(width=0), fillcolor="#fef5e7", layer="below",
            )

    # 2. Outer rack frame & steel shelf beams
    figure.add_shape(
        type="rect", x0=-0.6, x1=max_slot + 0.6, y0=min(levels) - 0.5, y1=max(levels) + 0.5,
        line=dict(color="#2c3e50", width=3), fillcolor="rgba(0,0,0,0)", layer="below",
    )
    for level in levels:
        # Steel load beam supporting each shelf tier
        figure.add_shape(
            type="rect", x0=-0.6, x1=max_slot + 0.6, y0=level - 0.50, y1=level - 0.45,
            line=dict(width=0), fillcolor="#7f8c8d", layer="below",
        )

    # 3. Empty bin outlines & linearly sized physical item boxes
    marker_sizes = []
    custom_rows = []
    for row in data_frame.itertuples(index=False):
        slot = getattr(row, "slot", 0)
        level = getattr(row, "shelf_level", 0)
        bw = float(getattr(row, "width_cm", 60.0) or 60.0)
        bh = float(getattr(row, "height_cm", 40.0) or 40.0)
        sku = getattr(row, "sku_id", None)
        assigned = pd.notna(sku) and str(sku) not in ("", "nan", "None", "<NA>")

        # Bin dashed compartment boundary
        figure.add_shape(
            type="rect", x0=slot - 0.44, x1=slot + 0.44, y0=level - 0.44, y1=level + 0.44,
            line=dict(color="#d5d8dc", width=1, dash="dot"), fillcolor="rgba(245,247,250,0.5)", layer="below",
        )

        if assigned:
            sw = float(getattr(row, "sku_width_cm", 0.0) or 0.0)
            sh = float(getattr(row, "sku_height_cm", 0.0) or 0.0)
            sd = float(getattr(row, "sku_depth_cm", 0.0) or 0.0)
            if sw <= 0:
                sw = bw * 0.45
            if sh <= 0:
                sh = bh * 0.45

            # Linear scaling: item dimensions divided by bin dimensions
            lin_w = min(1.0, max(0.25, sw / bw))
            lin_h = min(1.0, max(0.25, sh / bh))
            w_box = 0.84 * lin_w
            h_box = 0.82 * lin_h

            # Color determined by selected color mode
            cls = str(getattr(row, "abc_class", "unassigned"))
            if color_mode == "ABC class":
                box_color = dd.CLASS_COLORS.get(cls, "#95a5a6")
            elif color_mode == "Utilization":
                u = float(getattr(row, "bin_volume_util_pct", 0.0) or 0.0)
                box_color = "#1b4f72" if u > 60 else ("#2980b9" if u > 30 else "#85c1e9")
            elif color_mode == "Constraint status":
                st_val = str(getattr(row, "constraint_status", "OK"))
                box_color = "#27ae60" if st_val == "OK" else ("#c0392b" if st_val == "FAIL" else "#f39c12")
            else:
                box_color = "#2471a3"

            # Draw physical box resting on shelf beam
            bx0 = slot - w_box / 2.0
            bx1 = slot + w_box / 2.0
            by0 = level - 0.44
            by1 = level - 0.44 + h_box
            figure.add_shape(
                type="rect", x0=bx0, x1=bx1, y0=by0, y1=by1,
                line=dict(color="#ffffff", width=1.5), fillcolor=box_color, layer="below",
            )

    # 4. Interactive Scatter markers with hover information
    if color_mode == "ABC class":
        for cls in dd.CLASS_ORDER:
            subset = data_frame[data_frame["abc_class"] == cls]
            if subset.empty:
                continue
            lin_w_vals = [
                min(1.0, max(0.25, float(getattr(r, "sku_width_cm", 0) or 25) / float(getattr(r, "width_cm", 60) or 60)))
                for r in subset.itertuples(index=False)
            ]
            custom_data = [
                [
                    str(getattr(r, "location_id", "")),
                    str(getattr(r, "sku_id", "—")),
                    str(getattr(r, "shelf_level", "")),
                    str(getattr(r, "bay", "")),
                    str(getattr(r, "product_name", "—")),
                    f"{float(getattr(r, 'sku_width_cm', 0) or 0):g}x{float(getattr(r, 'sku_height_cm', 0) or 0):g}x{float(getattr(r, 'sku_depth_cm', 0) or 0):g} cm",
                    f"{float(getattr(r, 'width_cm', 60) or 60):g}x{float(getattr(r, 'height_cm', 40) or 40):g} cm",
                    f"{lw*100:.0f}%",
                    f"{float(getattr(r, 'unit_weight_kg', 0) or 0):g}",
                    cls,
                ]
                for r, lw in zip(subset.itertuples(index=False), lin_w_vals)
            ]
            figure.add_trace(go.Scatter(
                x=subset["slot"], y=subset["shelf_level"], mode="markers",
                name=f"Class {cls}" if cls != "unassigned" else "Unassigned",
                marker=dict(
                    symbol="square",
                    size=[16 + 16 * lw for lw in lin_w_vals],
                    color=dd.CLASS_COLORS[cls],
                    line=dict(width=1.5, color="#ffffff"),
                ),
                customdata=custom_data,
                hovertemplate=(
                    "<b>%{customdata[0]}</b> (Bay %{customdata[3]}, Shelf L%{customdata[2]})<br>"
                    "SKU: <b>%{customdata[1]}</b> · %{customdata[4]}<br>"
                    "Box size: <b>%{customdata[5]}</b> (linear fill: %{customdata[7]})<br>"
                    "Bin size: %{customdata[6]}<br>"
                    "Weight: %{customdata[8]} kg · ABC Class: <b>%{customdata[9]}</b><extra></extra>"
                ),
            ))
    else:
        subset = data_frame
        values = (
            pd.to_numeric(subset["bin_volume_util_pct"], errors="coerce").fillna(0.0)
            if color_mode == "Utilization"
            else subset["constraint_status"].map({"OK": 1.0, "FAIL": 0.0, "UNKNOWN": 0.5}).fillna(0.5)
        )
        colorscale = "Blues" if color_mode == "Utilization" else "RdYlGn"
        lin_w_vals = [
            min(1.0, max(0.25, float(getattr(r, "sku_width_cm", 0) or 25) / float(getattr(r, "width_cm", 60) or 60)))
            for r in subset.itertuples(index=False)
        ]
        figure.add_trace(go.Scatter(
            x=subset["slot"], y=subset["shelf_level"], mode="markers",
            name=color_mode,
            marker=dict(
                symbol="square",
                size=[16 + 16 * lw for lw in lin_w_vals],
                color=values, colorscale=colorscale, cmin=0, cmax=100 if color_mode == "Utilization" else 1,
                line=dict(width=1.5, color="#ffffff"),
            ),
            customdata=subset[["location_id", "sku_id", "shelf_level"]].astype(str).values,
            hovertemplate="<b>%{customdata[0]}</b><br>SKU: %{customdata[1]}<br>Shelf L%{customdata[2]}<extra></extra>",
        ))

    if selected_id is not None:
        selected = data_frame[data_frame["location_id"].astype(str) == str(selected_id)]
        if not selected.empty:
            figure.add_trace(go.Scatter(
                x=selected["slot"], y=selected["shelf_level"], mode="markers", name="Selected bin",
                marker=dict(symbol="circle-open", size=36, color="#111111", line=dict(width=3.5)),
                hoverinfo="skip", showlegend=False,
            ))

    figure.update_layout(
        title=title or "Zone Edge Rack Elevation (8 Bays x 4 Shelf Levels = 64 Bins)",
        height=PLOT_HEIGHT,
        margin=dict(l=10, r=10, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        plot_bgcolor="#fdfefe",
    )
    figure.update_xaxes(
        title="Bay / bin position across this edge of the zone (8 Bays x 2 Bins = 16 Bins)",
        tickmode="array",
        tickvals=[slot_index[s] for s in slots],
        ticktext=[f"Bay {bay+1}.{i%2+1}" for i, (bay, _x) in enumerate(slots)],
        showgrid=False,
    )
    figure.update_yaxes(
        title="Shelf level (0 = floor level)",
        tickmode="array",
        tickvals=levels,
        ticktext=[f"L{level}" + (" · golden" if level in golden_levels else "") for level in levels],
        showgrid=False,
    )
    return figure


def _detail_line(label: str, value) -> None:
    st.markdown(f"**{label}:** {value}")


def render_location_detail(data: dict, state: pd.DataFrame, location_id: str, layout: str) -> None:
    row = state[state["location_id"].astype(str) == str(location_id)]
    if row.empty:
        st.info("Select a storage location to inspect its assignment.")
        return
    record = row.iloc[0]
    products = data.get("products")
    demand = data.get("demand")
    inventory = data.get("inventory")

    sku_id = record.get("sku_id")
    sku = None
    if products is not None and pd.notna(sku_id):
        match = products[products["sku_id"] == sku_id]
        if not match.empty:
            sku = match.iloc[0]
    demand_frequency = None
    abc_class = record.get("abc_class")
    if demand is not None and pd.notna(sku_id):
        match = demand[demand["sku_id"] == sku_id]
        if not match.empty:
            demand_frequency = _num(match.iloc[0].get("demand_frequency"))
            abc_class = match.iloc[0].get("abc_class")
    on_hand = None
    if inventory is not None and pd.notna(sku_id):
        match = inventory[inventory["sku_id"] == sku_id]
        if not match.empty:
            on_hand = int(match["quantity_on_hand"].sum())

    st.subheader(f"Location {record['location_id']}")
    left, middle, right = st.columns(3)
    with left:
        st.markdown("**Structure**")
        _detail_line("Zone / aisle / rack", f"{record.get('zone_id', '—')} · {record.get('aisle_id', '—')} · {record.get('rack_id', '—')}")
        _detail_line("Bay / shelf level", f"{record.get('bay', '—')} · L{record.get('shelf_level', '—')}")
        _detail_line("Coordinates (x, y, z)", f"({fmt_number(record.get('x_m'), 2)}, {fmt_number(record.get('y_m'), 2)}, {fmt_number(record.get('z_m'), 2)}) m")
        _detail_line("Shelf height / ergonomics", f"{fmt_number(record.get('z_m'), 2)} m · {'golden zone' if record.get('golden_zone') else str(record.get('ergonomic_zone', '—'))}")
        _detail_line("Zone type / allowed handling", f"{record.get('zone_type', '—')} · {record.get('allowed_handling', '—')}")
        _detail_line("Allowed hazard classes", str(record.get("allowed_hazard", "—")))

    with middle:
        st.markdown("**Assigned SKU**")
        if pd.isna(sku_id):
            st.info("No SKU assigned in the selected layout.")
        else:
            _detail_line("SKU", f"{sku_id} — {record.get('product_name', '')}")
            _detail_line("Quantity in bin / on hand", f"{fmt_number(record.get('assigned_quantity'))} / {fmt_number(on_hand)}")
            _detail_line("ABC class / demand velocity", f"{abc_class} · {fmt_number(demand_frequency)} picks")
            _detail_line("Dimensions (W×H×D)", f"{fmt_number(record.get('width_cm'), 1)} × {fmt_number(record.get('height_cm'), 1)} × {fmt_number(record.get('depth_cm'), 1)} cm")
            _detail_line("Unit volume / weight", f"{fmt_number(record.get('unit_volume_cm3'), 1)} cm³ · {fmt_number(record.get('unit_weight_kg'), 3)} kg")
            _detail_line("Handling / hazard", f"{record.get('handling_type', '—')} · {record.get('hazard_class', '—')}")
            _detail_line("Category compatibility", "OK" if record.get("hazard_ok") and record.get("handling_ok") else "CHECK")
            _detail_line("Heavy shelf-height rule", "OK" if record.get("heavy_height_ok") else "FAIL (heavy above level 2)")

    with right:
        st.markdown("**Utilization**")
        _detail_line("Bin volume", f"{fmt_number(record.get('bin_volume_util_pct'), 1)} % of {fmt_number(record.get('usable_volume_cm3'), 0)} cm³")
        _detail_line("Bin weight", f"{fmt_number(record.get('bin_weight_util_pct'), 1)} % of {fmt_number(record.get('max_weight_kg'), 1)} kg")
        _detail_line("Shelf load", f"{fmt_number(record.get('shelf_load_util_pct'), 1)} % of {fmt_number(record.get('shelf_max_weight_kg'), 1)} kg")
        _detail_line("Rack load", f"{fmt_number(record.get('rack_load_util_pct'), 1)} % of {fmt_number(record.get('rack_max_weight_kg'), 1)} kg")
        status = record.get("constraint_status", "UNKNOWN")
        if status == "FAIL":
            st.error(f"Constraint status: FAIL — {record.get('failed_rules', '')}")
        elif status == "OK":
            st.success("Constraint status: OK — all checks for this bin passed")
        else:
            st.warning("Constraint status: not validated for this layout")

        st.markdown("**Baseline vs optimized**")
        base_sku = record.get("baseline_sku")
        opt_sku = record.get("optimized_sku")
        _detail_line("Baseline SKU at this bin", "—" if pd.isna(base_sku) else base_sku)
        _detail_line("Optimized SKU at this bin", "—" if pd.isna(opt_sku) else opt_sku)
        _detail_line("Assignment changed", "Yes" if record.get("changed") else "No")

    checks = data.get(f"checks_{layout}")
    if checks is not None and not checks.empty:
        subset = checks[checks["location_id"].astype(str) == str(location_id)]
        st.markdown("**Validation results for this location**")
        if subset.empty:
            st.caption("No validation rows reference this location directly (checks are recorded per assignment).")
        else:
            display = subset[["rule_id", "rule_name", "passed", "observed", "limit", "unit", "explanation"]].copy()
            display["passed"] = display["passed"].astype(str)
            st.dataframe(display, hide_index=True, width="stretch")

# --------------------------------------------------------------------------- layout tab
def render_layout(data: dict, layout: str) -> None:
    availability = dd.data_availability(data, layout)
    state = dd.location_state(data, layout)
    locations = data.get("locations")
    if state is None or locations is None:
        _unavailable(availability["layout"][1])
        return
    if not availability["assignments"][0]:
        st.warning(
            f"**Assignment data unavailable.** {availability['assignments'][1]} "
            "Bins are shown as unassigned rather than with fabricated SKUs."
        )

    topology = dd.topology_summary(locations)
    racks = dd.rack_geometry(locations)
    aisles = dd.aisle_geometry(locations)
    dispatch = dd.dispatch_point(data)
    st.caption(
        f"Recorded topology: {topology.get('zones')} zones · {topology.get('aisles')} aisles · "
        f"{topology.get('racks')} racks · {topology.get('bins', 0):,} bins · "
        f"{topology.get('shelf_levels')} shelf levels. The dataset stores zones as sequential "
        "bands along Y; the plan below uses those coordinates and stretches the display aspect. "
        "It is a logical schematic, not a CAD floor plan."
    )

    zones = sorted(locations["zone_id"].astype(str).unique())
    default_zone_index = zones.index("Z1") if "Z1" in zones else 0
    view = st.radio("View", ["Zone plan", "Rack elevation"], horizontal=True, key="layout_view")

    control_a, control_b, control_c, control_d = st.columns(4)
    zone = control_a.selectbox("Zone", zones, index=default_zone_index, key="layout_zone")
    zone_racks = sorted(locations.loc[locations["zone_id"].astype(str) == zone, "rack_id"].astype(str).unique())
    selected_rack = control_b.selectbox(
        "Rack", zone_racks,
        format_func=lambda r: f"{r} ({_rack_side_name(r)} side · 8 bays)",
        key="layout_rack",
    )
    color_mode = control_c.selectbox(
        "Colour by", ["ABC class", "Utilization", "Constraint status", "Assignment change"],
        key="layout_color",
    )
    assigned_only = control_d.checkbox("Assigned bins only", value=False, key="layout_assigned_only")

    all_locs = sorted(locations["location_id"].astype(str).unique())
    with st.expander("Measure a corridor path", expanded=False):
        ruler_a, ruler_b = st.columns(2)
        loc_a = ruler_a.selectbox("Start location", all_locs, index=0, key="ruler_loc_a")
        loc_b = ruler_b.selectbox(
            "End location", all_locs, index=min(500, len(all_locs) - 1), key="ruler_loc_b"
        )
        ruler_res = dd.ruler_path(loc_a, loc_b, locations)
        show_ruler = st.checkbox("Show this path on the plan", value=False, key="ruler_show")
        if ruler_res.get("distance") is not None:
            st.markdown(
                f'<div class="status-strip"><strong>{ruler_res["distance"]} m</strong> measured along the '
                "modeled corridor graph. This is a graph distance, not a tape measurement.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("Select two locations to measure the modeled corridor distance.")

    st.subheader("Warehouse plan — recorded coordinate extents")
    st.caption(
        "Zone boxes are min/max bin-footprint extents from `locations.csv`; the highlighted rack is the "
        "current selection. Hover for coordinates. The Y axis is about 174 m, so the display is stretched."
    )
    st.plotly_chart(
        warehouse_plan_figure(
            locations, selected_zone=zone, selected_rack=selected_rack,
            dispatch=dispatch, ruler_overlay=ruler_res if show_ruler else None, racks=racks,
        ),
        width="stretch", key="warehouse_plan_overview",
    )

    abc_filter = st.multiselect("ABC class", dd.CLASS_ORDER, default=dd.CLASS_ORDER, key="layout_abc")
    hazard_options = ["All"] + sorted(locations["allowed_hazard"].astype(str).str.split("|").explode().unique())
    hazard_choice = st.selectbox("Stored hazard class", hazard_options, key="layout_hazard")
    status_choice = st.selectbox(
        "Constraint status", ["All", "OK", "FAIL", "UNKNOWN"], key="layout_status"
    )

    if color_mode == "Assignment change" and "baseline" not in data:
        st.info("Assignment comparison needs both baseline and optimized outputs; falling back to ABC colouring.")
        color_mode = "ABC class"

    golden_levels = topology.get("golden_levels", [1, 2])

    if view == "Rack elevation":
        rack_frame = dd.filter_locations(
            state,
            abc_classes=[c for c in abc_filter if c in dd.CLASS_ORDER],
            zone=zone,
            rack=selected_rack,
            hazard=None if hazard_choice == "All" else hazard_choice,
            constraint_status=None if status_choice == "All" else status_choice,
            assigned_only=assigned_only,
        )
        if rack_frame.empty:
            st.info("No bins in this rack match the current filters.")
            return
        st.subheader(f"{zone} · {_rack_side_name(selected_rack)} edge rack ({selected_rack}) — elevation")
        st.caption("One side of the zone: 8 bays × 4 shelf levels = 64 bins. Box size is a linear footprint, not a 3-D packing model.")
        if color_mode == "ABC class":
            st.markdown(_class_legend_html(rack_frame), unsafe_allow_html=True)
        else:
            st.caption(
                "Class colours are fixed across the app (A = red, B = amber, C = blue, unassigned = grey). "
                "Switch Colour by back to ABC class for the demand legend."
            )
        event = st.plotly_chart(
            elevation_figure(
                rack_frame, None, golden_levels, color_mode,
                f"{zone} · {_rack_side_name(selected_rack)} side ({selected_rack}) — elevation ({layout})",
            ),
            width="stretch", on_select="rerun", selection_mode="points", key="layout_elevation_chart",
        )
        clicked = _selection_point(event)
        options = sorted(rack_frame["location_id"].astype(str).unique())
        if clicked in options:
            st.session_state["layout_selected"] = clicked
        current = st.session_state.get("layout_selected")
        if current not in options:
            st.session_state["layout_selected"] = options[0]
        location_id = st.selectbox(
            "Inspect storage location", options, key="layout_selected",
            help="Click a bin on the elevation or choose a location id here.",
        )
        highlight = elevation_figure(
            rack_frame, location_id, golden_levels, color_mode,
            f"{zone} · {selected_rack} · bin {location_id}",
        )
        with st.expander("Highlight selected bin", expanded=False):
            highlight.update_layout(height=340)
            st.plotly_chart(highlight, width="stretch", key="highlight_rack", config={"displayModeBar": False})
        render_location_detail(data, state, location_id, layout)
    else:
        zone_frame = dd.filter_locations(
            state,
            abc_classes=[c for c in abc_filter if c in dd.CLASS_ORDER],
            zone=zone,
            hazard=None if hazard_choice == "All" else hazard_choice,
            constraint_status=None if status_choice == "All" else status_choice,
            assigned_only=assigned_only,
        )
        if zone_frame.empty:
            st.info("No bins in this zone match the current filters.")
            return
        options = sorted(zone_frame["location_id"].astype(str).unique())
        location_id = st.selectbox(
            "Inspect storage location", options, key="layout_selected_plan",
            help="Choose a bin to highlight it on the zone plan.",
        )
        st.subheader(f"{zone} — zone plan ({layout})")
        st.caption("Bins are drawn at their recorded coordinates; the display aspect is stretched to fit the zone strip.")
        st.plotly_chart(
            plan_figure(
                zone_frame, racks[racks["zone_id"].astype(str) == zone],
                aisles[aisles["zone_id"].astype(str) == zone], dispatch,
                location_id, color_mode, f"{zone} — bin assignment ({layout})",
            ),
            width="stretch", key="layout_zone_plan",
        )
        if color_mode == "ABC class":
            st.markdown(_class_legend_html(zone_frame), unsafe_allow_html=True)
        render_location_detail(data, state, location_id, layout)

    st.subheader("Assignment comparison")
    if "baseline" in data and "optimized" in data:
        changed = int(state["changed"].sum())
        assigned_bins = int(state["assigned"].sum())
        cols = st.columns(3)
        cols[0].metric("Assigned bins", f"{assigned_bins:,} / {len(state):,}")
        cols[1].metric("Bins whose SKU changed", f"{changed:,}")
        cols[2].metric("Unassigned bins", f"{len(state) - assigned_bins:,}")
        comparison = state[state["changed"]][
            ["location_id", "zone_id", "rack_id", "shelf_level", "baseline_sku", "optimized_sku", "abc_class"]
        ].head(200)
        with st.expander(f"Changed bins (showing {len(comparison)} of {changed:,})"):
            st.dataframe(comparison, hide_index=True, width="stretch")
    else:
        st.caption("Baseline/optimized comparison unavailable: one of the assignment files is missing.")


# --------------------------------------------------------------------------- demand / ABC
def render_demand(data: dict) -> None:
    abc = data.get("abc")
    if abc is None:
        _unavailable(dd.data_availability(data)["demand"][1])
        return
    summary = dd.abc_summary(abc)
    st.subheader("Demand classification (ABC)")
    st.caption(dd.abc_rule_text(data.get("config")))
    if summary is not None:
        columns = st.columns(len(summary))
        for column, row in zip(columns, summary.itertuples(index=False)):
            column.metric(
                f"Class {row.abc_class}",
                f"{row.skus:,} SKUs",
                delta=f"{row.share_of_demand_pct:.1f}% of demand",
                delta_color="off",
            )
            column.caption(f"{row.share_of_skus_pct:.1f}% of the SKU catalogue")

    chart_left, chart_right = st.columns(2)
    ordered = abc.sort_values("rank")
    with chart_left:
        figure = go.Figure()
        figure.add_trace(go.Scatter(
            x=ordered["rank"], y=ordered["cumulative_share"] * 100, mode="lines",
            line=dict(color=ACCENT, width=2), name="Cumulative demand share",
        ))
        for share, label in ((80, "A/B boundary (80%)"), (95, "B/C boundary (95%)")):
            figure.add_hline(y=share, line_dash="dash", line_color="#566573",
                             annotation_text=label, annotation_position="bottom right")
        figure.update_layout(
            title="Pareto curve — cumulative demand share", height=380,
            xaxis_title="SKU rank by demand frequency", yaxis_title="Cumulative share (%)",
            margin=dict(l=10, r=10, t=60, b=40),
        )
        st.plotly_chart(figure, width="stretch")
    with chart_right:
        if summary is not None:
            figure = go.Figure(go.Bar(
                x=[f"Class {row.abc_class}" for row in summary.itertuples(index=False)],
                y=[row.share_of_demand_pct for row in summary.itertuples(index=False)],
                marker_color=[dd.CLASS_COLORS.get(row.abc_class, NEUTRAL) for row in summary.itertuples(index=False)],
                text=[f"{row.share_of_demand_pct:.1f}%" for row in summary.itertuples(index=False)],
                textposition="outside",
            ))
            figure.update_layout(
                title="Demand contribution by class", height=380,
                yaxis_title="Share of total demand (%)", margin=dict(l=10, r=10, t=60, b=40),
            )
            st.plotly_chart(figure, width="stretch")

    table = dd.sku_table(data, "optimized")
    if table is None or table.empty:
        st.info("SKU-level demand table unavailable.")
    else:
        st.subheader("SKU ranking and placement")
        access = table.copy()
        access["demand_units"] = access["demand"] * pd.to_numeric(access["assigned_qty"], errors="coerce").fillna(0)
        access["golden_units"] = access["demand_units"].where(access["golden_zone"], 0.0)
        grouped = access.groupby("abc_class").agg(
            skus=("sku_id", "nunique"),
            demand_units=("demand_units", "sum"),
            golden_demand_units=("golden_units", "sum"),
        ).reset_index()
        grouped["golden_share_pct"] = (
            grouped["golden_demand_units"] / grouped["demand_units"].replace(0, pd.NA) * 100
        ).round(2)
        grouped = grouped.rename(columns={
            "abc_class": "Class", "skus": "SKUs", "demand_units": "Total demand units",
            "golden_share_pct": "Demand-weighted golden-zone share (%)",
        })[["Class", "SKUs", "Total demand units", "Demand-weighted golden-zone share (%)"]]
        st.caption(
            "Prime accessibility is assessed with the demand-weighted share of units placed on golden shelf levels. "
            "No threshold is invented — reported as measured."
        )
        st.dataframe(grouped, hide_index=True, width="stretch")

        controls = st.columns(4)
        class_filter = controls[0].multiselect("Class", dd.CLASS_ORDER, default=["A", "B", "C"], key="demand_class")
        search = controls[1].text_input("Search SKU or product", key="demand_search")
        sort_by = controls[2].selectbox(
            "Sort by", ["Demand (high to low)", "Demand (low to high)", "SKU id", "Assigned quantity"],
            key="demand_sort",
        )
        golden_only = controls[3].checkbox("Golden-zone stock only", value=False, key="demand_golden")
        view = table[table["abc_class"].isin(class_filter)] if class_filter else table
        if search:
            mask = (
                view["sku_id"].astype(str).str.contains(search, case=False, na=False)
                | view.get("product_name", pd.Series("", index=view.index)).astype(str).str.contains(search, case=False, na=False)
            )
            view = view[mask]
        if golden_only:
            view = view[view["golden_zone"]]
        if sort_by == "Demand (high to low)":
            view = view.sort_values("demand", ascending=False)
        elif sort_by == "Demand (low to high)":
            view = view.sort_values("demand", ascending=True)
        elif sort_by == "Assigned quantity":
            view = view.sort_values("assigned_qty", ascending=False)
        else:
            view = view.sort_values("sku_id")
        columns = [
            "sku_id", "product_name", "abc_class", "demand", "rank", "cumulative_share",
            "on_hand", "assigned_qty", "location_id", "shelf_level", "golden_zone",
        ]
        display = view[[c for c in columns if c in view.columns]].head(300)
        st.dataframe(display, hide_index=True, width="stretch")
        st.caption(f"Showing {len(display):,} of {len(view):,} SKUs after filtering.")


# --------------------------------------------------------------------------- affinity
def render_affinity(data: dict, layout: str) -> None:
    pairs = dd.affinity_table(data)
    availability = dd.data_availability(data)
    if pairs is None:
        _unavailable(availability["affinity"][1])
        return
    st.subheader("Order affinity and co-occurrence")
    st.caption(
        "Association rules computed from the order history (scenario used for affinity analysis). "
        "Support = pair frequency in all orders; confidence = conditional probability; lift = "
        "observed co-occurrence / independence expectation."
    )
    controls = st.columns(3)
    min_co = controls[0].slider("Minimum co-orders", 1, int(pairs["co_count"].max()), 2, key="aff_min_co")
    min_lift = controls[1].slider("Minimum lift", 0.0, float(pairs["lift"].max()), 1.0, key="aff_min_lift")
    top_n = controls[2].slider("Rows shown", 10, 200, 40, step=10, key="aff_top")
    filtered = pairs[(pairs["co_count"] >= min_co) & (pairs["lift"] >= min_lift)]
    st.dataframe(
        filtered[["sku_a", "sku_b", "co_count", "support", "confidence_ab", "confidence_ba", "lift"]].head(top_n),
        hide_index=True, width="stretch",
    )

    chart_left, chart_right = st.columns([1, 1])
    with chart_left:
        matrix, skus = dd.affinity_heatmap(data, top_skus=18)
        if matrix is None:
            st.info("Not enough affinity data for a co-occurrence heatmap.")
        else:
            figure = go.Figure(go.Heatmap(
                z=matrix.values, x=matrix.columns, y=matrix.index, colorscale="Blues",
                hovertemplate="%{y} + %{x}<br>co-orders: %{z}<extra></extra>",
            ))
            figure.update_layout(
                title="Co-occurrence heatmap (top SKUs by co-orders)", height=520,
                margin=dict(l=10, r=10, t=60, b=40), xaxis_title=None, yaxis_title=None,
            )
            st.plotly_chart(figure, width="stretch")
    with chart_right:
        rows = {row["key"]: row for row in dd.kpi_rows(data.get("metrics"))}
        entry = rows.get("affinity_separation_m")
        st.markdown("**Before vs after — affinity separation**")
        if entry and entry.get("available"):
            figure = _bar_compare(rows, "affinity_separation_m", "Weighted aisle distance between related SKUs")
            if figure is not None:
                st.plotly_chart(figure, width="stretch")
            st.caption(
                f"Baseline {metric_text('affinity_separation_m', entry['baseline'])} → "
                f"optimized {metric_text('affinity_separation_m', entry['optimized'])} · "
                f"{change_label(entry)}. Weighted by co-order count over pairs that were evaluated."
            )
            summary = data.get("eval_summary") or {}
            base_aff = (summary.get("baseline") or {}).get("affinity_pairs_evaluated")
            opt_aff = (summary.get("optimized") or {}).get("affinity_pairs_evaluated")
            st.caption(f"Pairs evaluated: baseline {fmt_number(base_aff)}, optimized {fmt_number(opt_aff)}.")
        else:
            _unavailable("Affinity separation was not evaluated; run the simulation phase.")

        st.markdown("**Pair inspector**")
        if filtered.empty:
            st.info("No pairs match the current filters.")
            return
        labels = {
            f"{row.sku_a} + {row.sku_b} (lift {row.lift:.1f})": (row.sku_a, row.sku_b)
            for row in filtered.head(60).itertuples(index=False)
        }
        choice = st.selectbox("Co-ordered pair", list(labels), key="aff_pair")
        sku_a, sku_b = labels[choice]
        detail_cols = st.columns(2)
        baseline_detail = dd.pair_location_detail(data, sku_a, sku_b, "baseline")
        optimized_detail = dd.pair_location_detail(data, sku_a, sku_b, layout)
        for column, (title, detail) in zip(detail_cols, (("Baseline", baseline_detail), (layout.title(), optimized_detail))):
            with column:
                st.markdown(f"**{title}**")
                for label, key in ((sku_a, "a"), (sku_b, "b")):
                    info = detail.get(key) or {}
                    st.caption(
                        f"{label}: bin {info.get('primary') or 'unassigned'} · "
                        f"zone {info.get('zone_id') or '—'} · shelf L{info.get('shelf_level') if info.get('shelf_level') is not None else '—'}"
                    )
                st.caption(
                    f"Aisle-network distance between the selected bins: {fmt_number(detail.get('network_distance_m'), 1)} m · "
                    f"same aisle: {'yes' if detail.get('same_aisle') else 'no'}"
                )
        if baseline_detail.get("network_distance_m") and optimized_detail.get("network_distance_m"):
            reduction = dd.pct_reduction(
                baseline_detail["network_distance_m"], optimized_detail["network_distance_m"]
            )
            st.caption(f"Change for this pair: {fmt_number(reduction, 1)}% reduction" if reduction is not None else "")

    clusters = data.get("clusters")
    if clusters is not None and not clusters.empty:
        st.subheader("Affinity clusters")
        sizes = clusters.groupby("affinity_cluster_id")["sku_id"].nunique().reset_index(
            name="SKUs"
        ).rename(columns={"affinity_cluster_id": "Cluster"})
        st.dataframe(sizes.sort_values("SKUs", ascending=False), hide_index=True, width="stretch")
        st.caption("Cluster membership is produced by the affinity analysis output; it never overrides hard constraints.")


# --------------------------------------------------------------------------- routes
def route_figure(stops: pd.DataFrame, racks: pd.DataFrame, dispatch, title: str) -> go.Figure:
    """Pick routes in the recorded coordinate system.

    The dataset is a long zone strip (Y extent ~174 m), not the 40.8 m square that an
    earlier schematic assumed. Axes are fitted to the drawn geometry so no route leaves
    the plot, and the display aspect is explicitly stretched.
    """
    figure = go.Figure()
    xs: list[float] = []
    ys: list[float] = []
    if stops is not None and not stops.empty:
        xs = pd.to_numeric(stops["x_m"], errors="coerce").dropna().tolist()
        ys = pd.to_numeric(stops["y_m"], errors="coerce").dropna().tolist()
    if dispatch is not None:
        xs.append(float(dispatch[0]))
        ys.append(float(dispatch[1]))
    if racks is not None and not racks.empty:
        xs.extend([float(racks["x_min"].min()), float(racks["x_max"].max())])
        ys.extend([float(racks["y_min"].min()), float(racks["y_max"].max())])
    if not xs or not ys:
        figure.update_layout(title=title or "Route (no data)", height=520)
        return figure
    x0, x1 = min(xs) - 2.0, max(xs) + 2.0
    y0, y1 = min(ys) - 4.0, max(ys) + 4.0

    figure.add_shape(
        type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
        line=dict(color="#334155", width=1.5), fillcolor="#ffffff", layer="below",
    )
    if racks is not None and not racks.empty:
        for row in racks.itertuples(index=False):
            figure.add_shape(
                type="rect", x0=row.x_min, x1=row.x_max, y0=row.y_min, y1=row.y_max,
                line=dict(color="#cbd5e1", width=0.4), fillcolor="#eef2f7", layer="below",
            )
        zones = racks.groupby("zone_id", as_index=False).agg(
            x0=("x_min", "min"), x1=("x_max", "max"), y0=("y_min", "min"), y1=("y_max", "max")
        )
        for row in zones.itertuples(index=False):
            figure.add_annotation(
                x=float(row.x0) + 0.2, y=(float(row.y0) + float(row.y1)) / 2,
                text=f"<b>{row.zone_id}</b>", showarrow=False,
                font=dict(size=10, color="#64748b"), xanchor="left",
            )

    if stops is not None and not stops.empty:
        figure.add_trace(go.Scatter(
            x=stops["x_m"], y=stops["y_m"], mode="lines", name="Route sequence",
            line=dict(color=ACCENT, width=2.2),
            hovertemplate="Stop %{text}<extra></extra>", text=stops.get("sequence", []),
        ))
        labels = ["" if str(stop) == "DEPOT" else str(stop) for stop in stops.get("sequence", [])]
        custom_cols = [c for c in ["location_id", "skus", "leg_distance_m", "cumulative_distance_m"] if c in stops.columns]
        cdata = stops[custom_cols].astype(str).values if custom_cols else None
        figure.add_trace(go.Scatter(
            x=stops["x_m"], y=stops["y_m"], mode="markers+text", name="Pick stops",
            marker=dict(size=8, color=ACCENT, line=dict(width=1, color="#ffffff")),
            text=labels, textposition="top center",
            customdata=cdata,
            hovertemplate=(
                "Stop %{text} · %{customdata[0]}<br>SKUs %{customdata[1]}<br>"
                "Leg %{customdata[2]} m · cumulative %{customdata[3]} m<extra></extra>"
                if cdata is not None and len(custom_cols) >= 4 else "Stop %{text}<extra></extra>"
            ),
        ))

    dp_x, dp_y = (20.4, 0.5) if dispatch is None else dispatch
    figure.add_trace(go.Scatter(
        x=[dp_x], y=[dp_y], mode="markers+text", name="Dispatch / I-O",
        marker=dict(symbol="star", size=16, color="#f59e0b", line=dict(width=1, color="#92400e")),
        text=["I-O"], textposition="bottom center",
        hovertemplate="Dispatch point (%{x:.1f}, %{y:.1f}) m<extra></extra>",
    ))

    figure.update_layout(
        title=title, height=600, margin=dict(l=12, r=12, t=58, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        xaxis_title="x (m, stretched display)", yaxis_title="y (m)",
    )
    figure.update_xaxes(range=[x0, x1], showgrid=False)
    figure.update_yaxes(range=[y0, y1], showgrid=False)
    return figure


def render_routes(data: dict) -> None:
    availability = dd.data_availability(data)
    batches = dd.route_batches(data)
    if batches is None or not availability["routes"][0]:
        _unavailable(availability["routes"][1])
        return
    if data.get("route_stops_baseline") is None or data.get("route_stops_optimized") is None:
        _unavailable("Route stop sequences were not generated; ordered pick locations are unavailable.")
        return
    st.subheader("Pick-path simulation")
    batch_ids = sorted(batches["batch_id"].unique())
    default_batch = int(batch_ids[0]) if batch_ids else 0
    batch_id = st.selectbox(
        "Pick batch", batch_ids, index=batch_ids.index(default_batch), key="route_batch",
        format_func=lambda value: f"Batch {value}",
    )
    rows = {}
    for candidate in ("baseline", "optimized"):
        row = dd.route_summary_row(data, candidate, int(batch_id))
        if row:
            rows[candidate] = row
    if not rows:
        _unavailable("No simulated route for this batch.")
        return

    base = rows.get("baseline")
    opt = rows.get("optimized")
    cols = st.columns(4)
    if base and opt:
        cols[0].metric("Orders in batch", f"{fmt_number(base.get('n_orders'))}")
        distance_reduction = dd.pct_reduction(base.get("distance_m"), opt.get("distance_m"))
        time_reduction = dd.pct_reduction(base.get("cycle_time_sec"), opt.get("cycle_time_sec"))
        cols[1].metric("Travel distance", f"{fmt_number(opt.get('distance_m'), 1)} m")
        cols[1].markdown(
            f'<span class="kpi-change good">↓ {distance_reduction:,.1f}% lower</span>'
            if distance_reduction is not None else '<span class="kpi-change neutral">not defined</span>',
            unsafe_allow_html=True,
        )
        cols[2].metric("Cycle time", f"{fmt_number(opt.get('cycle_time_sec'), 1)} s")
        cols[2].markdown(
            f'<span class="kpi-change good">↓ {time_reduction:,.1f}% lower</span>'
            if time_reduction is not None else '<span class="kpi-change neutral">not defined</span>',
            unsafe_allow_html=True,
        )
        location_delta = _num(opt.get("n_locations")) - _num(base.get("n_locations"))
        location_label = (
            "no change" if abs(location_delta) < 1e-9
            else f"↓ {abs(location_delta):,.0f} fewer" if location_delta < 0
            else f"↑ {abs(location_delta):,.0f} more"
        )
        cols[3].metric("Pick locations", f"{fmt_number(opt.get('n_locations'))}")
        cols[3].markdown(
            f'<span class="kpi-change neutral">{location_label} vs baseline</span>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"Baseline distance {fmt_number(base.get('distance_m'), 1)} m; "
            f"baseline cycle {fmt_number(base.get('cycle_time_sec'), 1)} s. "
            "Both routes use the same orders, graph, routing heuristic and time assumptions."
        )

    locations = data.get("locations")
    racks = dd.rack_geometry(locations) if locations is not None else pd.DataFrame()
    dispatch = dd.dispatch_point(data)
    left, right = st.columns(2)
    for column, layout in ((left, "baseline"), (right, "optimized")):
        stops = dd.stops_with_coordinates(data, layout, int(batch_id))
        with column:
            if stops is None:
                _unavailable(f"No stop sequence for the {layout} layout.")
            else:
                st.plotly_chart(
                    route_figure(stops, racks, dispatch, f"{layout.title()} route — batch {batch_id}"),
                    width="stretch", key=f"route_{layout}",
                )
                st.caption(
                    "Plan schematic: axes are metres, both axes are fitted to the drawn geometry, "
                    "and the display aspect is stretched so the full route is visible."
                )

    st.subheader("Ordered pick stops")
    table_layout = st.radio("Stops for", ["optimized", "baseline"], horizontal=True, key="route_table_layout")
    stops = dd.route_stops(data, table_layout, int(batch_id))
    if stops is None:
        _unavailable("Stop table unavailable for this layout.")
    else:
        st.dataframe(stops, hide_index=True, width="stretch")

    assumptions = (data.get("eval_summary") or {}).get("assumptions") or {}
    with st.expander("Route assumptions"):
        st.json(assumptions or {"note": "No assumptions recorded."})


# --------------------------------------------------------------------------- constraints
def render_constraints(data: dict, layout: str) -> None:
    availability = dd.data_availability(data, layout)
    checks = data.get(f"checks_{layout}")
    verdict = dd.safety_status(data, layout)

    st.subheader("Physical constraints and safety inspection")
    st.caption(
        "Every row below is a rule evaluation that actually ran in the validator. Safety and physical "
        "feasibility are hard constraints: they are never traded against the optimization objective. "
        "Failed assignments and unassigned SKUs are shown, not hidden."
    )
    cols = st.columns(4)
    cols[0].metric("Safety verdict", verdict["status"])
    st.caption(f"Layout under review: {layout}")
    cols[1].metric("Rule checks run", f"{verdict['checks_run']:,}")
    cols[2].metric("Failed checks", f"{verdict['failed_checks']:,}")
    cols[3].metric("High-severity failures", f"{verdict['hard_violations']:,}" if verdict["hard_violations"] is not None else "—")

    if verdict["status"] == "PASS":
        st.success(
            f"PASS — {verdict['checks_run']:,} hard-constraint checks ran for the {layout} layout and none failed. "
            "This claim is backed by the exported validation rows, not assumed."
        )
    short = dd.unassigned_skus(data, layout)
    if short is not None and not short.empty:
        st.warning(
            f"{len(short):,} SKUs with on-hand inventory are not fully placed in this layout; they are "
            "listed in the Optimization tab and are never silently discarded."
        )
    elif verdict["status"] == "FAIL":
        st.error(
            f"FAIL — {verdict['failed_checks']:,} of {verdict['checks_run']:,} checks failed. "
            f"Affected rules: {', '.join(verdict['rules_failed'])}. "
            "The layout must not be treated as compliant until these are resolved."
        )
    else:
        _unavailable(verdict["reason"], "Safety not verified")

    if checks is None or checks.empty:
        _unavailable(availability["constraints"][1])
        return

    filter_cols = st.columns(4)
    groups = sorted(checks["rule_group"].astype(str).unique())
    group_filter = filter_cols[0].multiselect("Rule group", groups, default=groups, key="con_group")
    only_failed = filter_cols[1].checkbox("Only failed checks", value=False, key="con_failed")
    severity = filter_cols[2].selectbox("Severity", ["All", "high", "medium", "info"], key="con_severity")
    search = filter_cols[3].text_input("SKU or location contains", key="con_search")

    filtered = checks.copy()
    if group_filter:
        filtered = filtered[filtered["rule_group"].astype(str).isin(group_filter)]
    if only_failed:
        filtered = filtered[~filtered["passed"].astype(str).str.lower().isin(["true", "1"])]
    if severity != "All":
        filtered = filtered[filtered["severity"].astype(str).str.lower() == severity]
    if search:
        mask = (
            filtered["sku_id"].astype(str).str.contains(search, case=False, na=False)
            | filtered["location_id"].astype(str).str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]

    st.markdown("**Rule summary**")
    summary = dd.validation_by_rule(filtered)
    if summary is None or summary.empty:
        st.info("No checks match the current filters.")
    else:
        st.dataframe(summary, hide_index=True, width="stretch")

    st.markdown("**Validation detail**")
    detail = filtered.sort_values(["rule_group", "rule_id"]).copy()
    observed_numeric = pd.to_numeric(detail["observed"], errors="coerce")
    limit_numeric = pd.to_numeric(detail["limit"], errors="coerce")
    measurable = observed_numeric.notna() & limit_numeric.notna()
    remaining = (limit_numeric - observed_numeric).round(2).astype("string")
    detail["remaining"] = remaining.where(measurable, "")
    display = detail[[
        "rule_id", "rule_name", "rule_group", "passed", "severity", "sku_id", "location_id",
        "observed", "limit", "remaining", "unit", "explanation",
    ]].head(1000)
    st.dataframe(display, hide_index=True, width="stretch")
    st.caption(
        f"Showing {len(display):,} of {len(filtered):,} filtered checks "
        f"({len(checks):,} total for the {layout} layout)."
    )

    st.download_button(
        "Download filtered audit (CSV)",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name=f"constraint_checks_{layout}.csv",
        mime="text/csv",
        key="download_constraint_checks",
    )

    with st.expander("What each constraint group enforces"):
        st.markdown(
            "- **Spatial & volumetric** — `SP-01` per-dimension fit (width/height/depth), `VD-01` stored "
            "volume vs usable bin volume. Dimensional fit and volume fit are separate checks.\n"
            "- **Structural load** — `LD-01` load per bin, `SL-01` load per shelf level, `RK-01` load per "
            "rack frame, each against its configured limit.\n"
            "- **Hazard & safety** — `HZ-01` hazard/zone compatibility, `HD-01` handling/zone compatibility, "
            "`ER-01` heavy items above permitted shelf levels, `AS-01` single-SKU bins, `CP-01` co-storage "
            "category compatibility.\n"
            "- **Integrity** — referential integrity, positive quantities, completeness (every SKU with "
            "inventory has a home), and inventory conservation (assigned units equal on-hand units).\n"
            "\nNot modeled: SKU rotation/orientation permutations. Dimensional fit is checked against the "
            "axis-aligned bounding box only, and the “remaining” column is `limit − observed` for "
            "numerically comparable checks (loads in kg, volumes in cm³)."
        )


# --------------------------------------------------------------------------- ergonomics
def render_ergonomics(data: dict, layout: str) -> None:
    locations = data.get("locations")
    state = dd.location_state(data, layout)
    if locations is None or state is None:
        _unavailable("Topology data unavailable for the ergonomics view.")
        return
    st.subheader("Ergonomics and replenishment")
    topology = dd.topology_summary(locations)
    golden_levels = topology.get("golden_levels", [])
    st.caption(
        f"Golden-zone shelf levels are read from the topology (`ergonomic_zone = golden`): "
        f"levels {golden_levels or 'none configured'}. Heavy items are restricted to shelf levels 0–2 by rule ER-01."
    )

    shelf = locations.groupby("shelf_level", as_index=False).agg(
        height_min_m=("z_m", "min"), height_max_m=("z_m", "max"),
        bin_height_cm=("height_cm", "min"), bins=("location_id", "nunique"),
    )
    shelf["golden"] = shelf["shelf_level"].isin(golden_levels)
    assigned = state[state["assigned"]]
    per_level = assigned.groupby("shelf_level", as_index=False).agg(
        assigned_bins=("location_id", "nunique"), units=("assigned_quantity", "sum")
    )
    per_level["a_class_units"] = (
        assigned.assign(a_units=assigned["assigned_quantity"].where(assigned["abc_class"] == "A", 0))
        .groupby("shelf_level")["a_units"].sum()
        .reindex(per_level["shelf_level"]).fillna(0).astype(int).values
    )
    shelf = shelf.merge(per_level, on="shelf_level", how="left")
    shelf[["assigned_bins", "units", "a_class_units"]] = shelf[["assigned_bins", "units", "a_class_units"]].fillna(0).astype(int)
    if bool((shelf["height_min_m"] == shelf["height_max_m"]).all()):
        shelf = shelf.drop(columns=["height_max_m"]).rename(columns={"height_min_m": "Shelf height (m)"})
    else:
        shelf = shelf.rename(columns={"height_min_m": "Height min (m)", "height_max_m": "Height max (m)"})
    shelf["golden"] = shelf["golden"].map({True: "Yes", False: "No"})
    shelf = shelf.rename(columns={
        "shelf_level": "Shelf level",
        "bin_height_cm": "Bin height (cm)", "bins": "Locations", "golden": "Golden zone",
        "assigned_bins": "Assigned bins", "units": "Units stored", "a_class_units": "Class A units",
    })
    st.markdown("**Golden-zone boundaries and shelf usage**")
    st.dataframe(shelf, hide_index=True, width="stretch")

    rows = {row["key"]: row for row in dd.kpi_rows(data.get("metrics"))}
    card_cols = st.columns(3)
    for column, key in zip(card_cols, ("golden_zone_demand_share_pct", "class_a_skus_outside_golden", "constraint_violations")):
        row = rows.get(key)
        if row and row.get("available"):
            column.metric(row["label"], metric_text(key, row["optimized"]))
            column.markdown(_metric_badge_html(row), unsafe_allow_html=True)
            column.caption(_metric_note(row))
        else:
            column.metric(row["label"] if row else key, "—")
            column.caption("Not calculated in the current outputs.")

    chart_cols = st.columns(2)
    with chart_cols[0]:
        figure = _bar_compare(rows, "golden_zone_demand_share_pct", "Demand-weighted share of units in the golden zone")
        if figure is not None:
            st.plotly_chart(figure, width="stretch")
    with chart_cols[1]:
        figure = _bar_compare(rows, "class_a_skus_outside_golden", "Class A SKUs without golden-zone stock")
        if figure is not None:
            st.plotly_chart(figure, width="stretch")

    table = dd.sku_table(data, layout)
    if table is not None and not table.empty:
        exceptions = table[(table["abc_class"] == "A") & (~table["golden_zone"])].sort_values("demand", ascending=False)
        st.markdown("**Class A exceptions — no unit on a golden shelf level**")
        if exceptions.empty:
            st.success("Every Class A SKU has stock on a golden shelf level in this layout.")
        else:
            st.caption(
                f"{len(exceptions):,} Class A SKUs have no unit on a golden shelf level. They remain placed in "
                "feasible locations; the reason is capacity, zone eligibility (hazard/handling) or hard "
                "structural limits, not a relaxation of safety rules."
            )
            st.dataframe(
                exceptions[["sku_id", "product_name", "demand", "assigned_qty", "location_id", "zone_id", "shelf_level"]].head(100),
                hide_index=True, width="stretch",
            )

        heavy = table[table["handling_type"].astype(str) == "heavy"]
        st.markdown("**Heavy-item placement restrictions**")
        if heavy.empty:
            st.caption("No heavy-handling SKUs in the active catalogue.")
        else:
            above = heavy[pd.to_numeric(heavy["shelf_level"], errors="coerce") > 2]
            heavy_cols = st.columns(3)
            heavy_cols[0].metric("Heavy SKUs", f"{len(heavy):,}")
            heavy_cols[1].metric("Heavy SKUs stored above level 2", f"{len(above):,}")
            checks = data.get(f"checks_{layout}")
            er_checks = checks[checks["rule_id"] == "ER-01"] if checks is not None else pd.DataFrame()
            if not er_checks.empty:
                failed = (~er_checks["passed"].astype(str).str.lower().isin(["true", "1"])).sum()
                heavy_cols[2].metric("ER-01 rule checks failed", f"{int(failed):,}")
            if not above.empty:
                st.dataframe(above[["sku_id", "product_name", "assigned_qty", "location_id", "shelf_level"]], hide_index=True, width="stretch")

    st.markdown("**Replenishment metrics**")
    st.warning(
        "Not modeled. The dataset contains no replenishment policy, reorder points, lead times, or "
        "replenishment events, so no replenishment performance is claimed. Any replenishment KPI here "
        "would be fabricated."
    )
    st.caption(
        "Available measured proxies: units stored per shelf level (table above) and per-SKU on-hand "
        "inventory from inventory.csv. These are stock measurements, not replenishment performance."
    )

# --------------------------------------------------------------------------- optimization
def render_optimization(data: dict) -> None:
    st.subheader("Optimization controls and results")
    message = st.session_state.pop("optimization_run_message", None)
    if message:
        if message.get("ok"):
            st.success(message["text"])
        else:
            st.error(message["text"])

    summary = data.get("opt_summary")
    if summary:
        cols = st.columns(4)
        feasible = bool(summary.get("feasibility"))
        cols[0].metric("Solver status", "FEASIBLE" if feasible else "INFEASIBLE")
        cols[1].metric("Runtime", f"{fmt_number(summary.get('runtime_sec'), 2)} s")
        cols[2].metric("Moves evaluated", fmt_number(summary.get("moves_evaluated")))
        cols[3].metric("Globally optimal", "No" if not summary.get("globally_optimal") else "Yes")
        st.caption(
            f"Algorithm: {summary.get('algorithm', 'n/a')} · stopping reason: "
            f"{summary.get('stopping_reason', 'n/a')} · violations: {summary.get('n_violations', 'n/a')} · "
            f"units placed {fmt_number(summary.get('units_placed'))} of {fmt_number(summary.get('inventory_units'))}."
        )
        with st.expander("Optimization log and configuration"):
            st.json(summary)
        if summary.get("top_violations"):
            st.error("The optimizer returned violations:\n- " + "\n- ".join(summary["top_violations"]))
    else:
        _unavailable("No optimization summary found. Run the optimizer below or via the CLI.")

    st.markdown("**Run optimization**")
    st.caption(
        "Inputs are validated before the engine runs. Weights must be finite and non-negative with a "
        "positive sum, and the seed must be an integer. The run is only reported as successful when the "
        "backend returns a feasible, validated layout; evaluation is re-run on the same workload."
    )
    with st.form("optimization_form"):
        inputs = st.columns(5)
        alpha = inputs[0].number_input("α travel weight", min_value=0.0, max_value=100.0, value=1.0, step=0.1)
        beta = inputs[1].number_input("β affinity weight", min_value=0.0, max_value=100.0, value=0.4, step=0.1)
        gamma = inputs[2].number_input("γ ergonomics weight", min_value=0.0, max_value=100.0, value=0.3, step=0.1)
        delta = inputs[3].number_input("δ utilization weight", min_value=0.0, max_value=100.0, value=0.2, step=0.1)
        seed = inputs[4].number_input("Random seed", min_value=0, max_value=2_147_483_647, value=42, step=1)
        baseline_method = st.selectbox(
            "Baseline method",
            ["Canonical baseline dataset (storage_assignments_baseline.csv)"],
            help="Only the canonical baseline is implemented; it is the reference layout used for all comparisons.",
        )
        submitted = st.form_submit_button("Validate and run optimization", type="primary")

    if submitted:
        problems = []
        weights = {"alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta}
        for name, value in weights.items():
            if value is None or not float(value) == float(value) or not float("inf") > float(value) >= 0:
                problems.append(f"{name} must be a finite number ≥ 0.")
        if sum(float(v) for v in weights.values()) <= 0:
            problems.append("At least one objective weight must be greater than zero.")
        if not float(seed).is_integer() or seed < 0:
            problems.append("Seed must be a non-negative integer.")
        if problems:
            st.error("Input validation failed: " + " ".join(problems))
        else:
            try:
                from src.models.config import Config
                from src.optimization.pipeline import run_phase5
                from src.simulation.pipeline import run_phase6

                config = Config.from_json(PROJECT_ROOT / "configs" / "benchmark.json")
                config.optimization.alpha = float(alpha)
                config.optimization.beta = float(beta)
                config.optimization.gamma = float(gamma)
                config.optimization.delta = float(delta)
                config.dataset.seed = int(seed)
                with st.spinner("Running optimizer and re-simulating the identical workload…"):
                    result = run_phase5(dd.DATA_DIR, config, dd.OPT)
                    run_phase6(
                        dd.DATA_DIR,
                        scenario="A",
                        out=dd.EVAL,
                        separation_radius_m=config.separation_radius_m,
                    )
                _load_cached.clear()
                ok = bool(result.get("feasibility")) and result.get("n_violations") == 0
                st.session_state["optimization_run_message"] = {
                    "ok": ok,
                    "text": (
                        f"Optimization {'completed and validated' if ok else 'completed but is NOT feasible'}: "
                        f"{result.get('n_violations', 'n/a')} violations, "
                        f"{fmt_number(result.get('units_placed'))} of {fmt_number(result.get('inventory_units'))} units placed, "
                        f"runtime {fmt_number(result.get('runtime_sec'), 2)} s."
                    ),
                }
                st.rerun()
            except Exception as exc:  # surfaced to the operator, never hidden
                st.error(f"Optimization failed: {exc.__class__.__name__}: {exc}")

    st.caption("Validation results for this run are in the Constraints & Safety tab.")
    st.markdown("**Infeasible or unassigned SKUs**")
    short = dd.unassigned_skus(data, "optimized")
    if short is None:
        _unavailable("Assignment or inventory data unavailable, so completeness cannot be assessed.")
    elif short.empty:
        st.success("No unassigned or under-stored SKUs: every SKU with on-hand inventory is fully placed.")
    else:
        st.warning(f"{len(short):,} SKUs are not fully placed in the optimized layout.")
        st.dataframe(short.head(200), hide_index=True, width="stretch")

    st.markdown("**Completed runs**")
    history = data.get("run_history")
    if not history:
        _unavailable(dd.data_availability(data)["run_history"][1])
    else:
        frame = pd.DataFrame(history)
        st.dataframe(frame, hide_index=True, width="stretch")
        st.caption("Recorded from actual completed optimizer runs (objective weights, feasibility, runtime, stopping reason).")

    with st.expander("What the optimizer does and does not guarantee"):
        st.markdown(
            "- Greedy velocity-ordered starter followed by simulated annealing over bin swaps/moves.\n"
            "- Inventory conservation is invariant: a layout relocates stock, it never adds or drops units.\n"
            "- Every candidate is re-validated with the full hard-constraint validator before acceptance.\n"
            "- `globally_optimal` is false: this is a heuristic, so no global-optimality claim is made.\n"
            "- Baseline and optimized layouts are evaluated with identical orders, geometry and routing."
        )


# --------------------------------------------------------------------------- exports
def render_exports(data: dict, layout: str) -> None:
    st.subheader("Exports and reports")
    evaluation = data.get("eval_summary") or {}
    if evaluation.get("evaluation_status") == "BLOCKED_INFEASIBLE_LAYOUT":
        st.error(
            "This evaluation is **BLOCKED_INFEASIBLE_LAYOUT**: the metrics in these exports are "
            "diagnostic only and must not be presented as a valid baseline-vs-optimized comparison."
        )
    st.caption(
        "Every export contains the same results shown on screen; tabular outputs are CSV and structured "
        "run metadata is JSON. PDF report generation is not implemented — the JSON report carries the "
        "methodology, assumptions, results and safety audit."
    )
    checks = data.get(f"checks_{layout}")
    comparison = pd.DataFrame([
        {key: row[key] for key in ("key", "label", "unit", "baseline", "optimized", "delta", "change_pct", "change_pp", "definition")}
        for row in dd.kpi_rows(data.get("metrics")) if row.get("available")
    ])
    report = dd.report_payload(data, layout)
    optimization_meta = {
        "run": data.get("opt_summary"),
        "dataset_config": data.get("config"),
        "history": data.get("run_history"),
        "evaluation_assumptions": (data.get("eval_summary") or {}).get("assumptions"),
    }

    left, right = st.columns(2)
    exports = [
        (left, "Baseline assignments (CSV)", data.get("baseline"), "baseline_assignments.csv", "text/csv"),
        (left, "Optimized assignments (CSV)", data.get("optimized"), "optimized_assignments.csv", "text/csv"),
        (left, f"Constraint validation audit — {layout} (CSV)", checks, f"constraint_checks_{layout}.csv", "text/csv"),
        (left, "SKU demand / ABC analysis (CSV)", data.get("abc"), "abc_classification.csv", "text/csv"),
        (left, "Affinity analysis results (CSV)", data.get("affinity"), "affinity_pairs.csv", "text/csv"),
        (right, "Baseline vs optimized KPI report (CSV)", comparison, "kpi_comparison.csv", "text/csv"),
        (right, "Optimization configuration and run summary (JSON)", optimization_meta, "optimization_run.json", "application/json"),
        (right, "Full evaluation report (JSON)", report, "warehouse_slotting_report.json", "application/json"),
    ]
    for column, label, payload, file_name, mime in exports:
        if payload is None:
            column.button(label, disabled=True, key=f"disabled_{file_name}", help="Data unavailable")
            column.caption(f"**Not available** — {file_name} has no backing data.")
            continue
        if isinstance(payload, pd.DataFrame):
            if payload.empty:
                column.button(label, disabled=True, key=f"disabled_{file_name}", help="No rows")
                column.caption(f"**Not available** — {file_name} is empty.")
                continue
            text = payload.to_csv(index=False)
        else:
            text = json.dumps(payload, indent=2, default=str)
        column.download_button(label, data=text.encode("utf-8"), file_name=file_name, mime=mime, key=f"download_{file_name}")

    st.markdown("**Report contents**")
    st.caption(
        "Methodology and ABC rule · evaluation conditions · assumptions (walker speed, pick/setup time, "
        "batch size) · baseline and optimized metrics · safety audit verdicts for both layouts · "
        "optimization run metadata · unassigned-SKU list · stated limitations."
    )
    with st.expander("Preview report metadata"):
        st.json({key: report[key] for key in ("generated_at_utc", "methodology", "assumptions", "safety", "limitations")})


# --------------------------------------------------------------------------- main
def render_inventory_management(data: dict) -> None:
    """Inventory management page with empty-first state, Add Item allocation, and invisible ruler path calculation."""
    st.subheader("Inventory Management & Zonal Edge-Rack Allocation")

    locations = data.get("locations")
    products = data.get("products")
    inventory = data.get("inventory")
    optimized = data.get("optimized")

    if locations is None or products is None or inventory is None:
        st.warning("Data not available. Run the pipeline to generate dataset outputs.")
        return

    # Initialize empty-first state in session state if not set
    if "warehouse_empty_state" not in st.session_state:
        st.session_state["warehouse_empty_state"] = False
    if "custom_allocations" not in st.session_state:
        st.session_state["custom_allocations"] = {}

    loc_lookup = {}
    for _, row in locations.iterrows():
        lid = str(row["location_id"])
        if lid not in loc_lookup:
            loc_lookup[lid] = row

    col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1.5, 2])
    if col_btn1.button("🗑️ Set All Bins to Empty", type="secondary"):
        st.session_state["warehouse_empty_state"] = True
        st.session_state["custom_allocations"] = {}
        st.toast("All 2,304 bins across all racks are now empty! Use Add Item to place stock.", icon="ℹ️")
        st.rerun()

    if col_btn2.button("📦 Populate All 1,425 Items", type="primary"):
        st.session_state["warehouse_empty_state"] = False
        st.session_state["custom_allocations"] = {}
        st.toast("Populated all items into zone edge racks!", icon="✅")
        st.rerun()

    is_empty = st.session_state["warehouse_empty_state"]
    custom_count = len(st.session_state["custom_allocations"])
    total_locations = len(locations)

    inv_df = inventory.groupby("sku_id")["quantity_on_hand"].sum().reset_index()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Warehouse Bins", f"{total_locations:,} (9 zones x 4 racks)")
    if is_empty:
        m2.metric("Allocated Items", f"{custom_count:,}")
        m3.metric("Empty Bins", f"{total_locations - custom_count:,}")
        m4.metric("Warehouse Status", "Empty-First Mode" if custom_count == 0 else "Partially Populated")
    else:
        used_bins = optimized["location_id"].nunique() if (optimized is not None and not optimized.empty) else len(inv_df)
        m2.metric("SKUs in Inventory", f"{len(inv_df):,}")
        m3.metric("Occupied Bins", f"{used_bins:,}")
        m4.metric("Empty Bins", f"{total_locations - used_bins:,}")

    tab_add, tab_search, tab_delete = st.tabs(["Add item", "Search item", "Delete item"])

    with tab_add:
        st.markdown("**Add Item to Zone Edge Racks**")
        st.caption(
            "Enter details or select an item. The system calculates the best empty bin on a zone edge rack, "
            "verifying dimensions, weight, hazard and handling rules, and computes corridor distance from dispatch via the invisible ruler."
        )

        with st.form("add_item_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            with col1:
                product_name = st.text_input("Product name", value="Hydraulic Bearing Seal", placeholder="e.g. Widget A")
                handling = st.selectbox("Handling type", ["standard", "fragile", "heavy", "temperature_controlled"])
                hazard = st.selectbox("Hazard class", ["NONE", "flammable", "corrosive", "toxic", "compressed_gas"])
                width = st.number_input("Width (cm)", min_value=0.1, value=25.0, step=1.0)
                height = st.number_input("Height (cm)", min_value=0.1, value=15.0, step=1.0)
            with col2:
                depth = st.number_input("Depth (cm)", min_value=0.1, value=20.0, step=1.0)
                weight = st.number_input("Unit weight (kg)", min_value=0.1, value=3.5, step=0.5)
                quantity = st.number_input("Quantity on hand", min_value=1, value=5, step=1)
                abc_class = st.selectbox("ABC class priority", ["A", "B", "C"])

            submitted = st.form_submit_button("Find Best Location & Add to Zone", type="primary", width="stretch")

            if submitted:
                # Find best compatible empty bin on zone edge racks
                target_zone = "Z9" if hazard != "NONE" else ("Z7" if handling == "heavy" else ("Z1" if abc_class == "A" else "Z2"))
                allocated_loc = None

                # Search locations for target zone
                for _, loc in locations.iterrows():
                    lid = str(loc["location_id"])
                    if lid in st.session_state["custom_allocations"]:
                        continue
                    if loc.get("zone_id") == target_zone:
                        # Check hazard
                        allowed_haz = str(loc.get("allowed_hazard", "")).split("|")
                        if hazard != "NONE" and hazard not in allowed_haz:
                            continue
                        allocated_loc = loc
                        break

                if allocated_loc is None:
                    # Fallback to any empty bin
                    for _, loc in locations.iterrows():
                        lid = str(loc["location_id"])
                        if lid not in st.session_state["custom_allocations"]:
                            allocated_loc = loc
                            break

                if allocated_loc is not None:
                    loc_id = str(allocated_loc["location_id"])
                    zid = allocated_loc.get("zone_id", "Z1")
                    rid = allocated_loc.get("rack_id", "R1-1-1")
                    bay = allocated_loc.get("bay", 0)
                    shelf = allocated_loc.get("shelf_level", 0)

                    # Measure distance from Depot via the Invisible Ruler strictly along corridors
                    ruler = dd.ruler_path("DEPOT", loc_id, locations)
                    ruler_dist = ruler.get("distance", 0.0)

                    new_sku_id = f"SKU_{abs(hash(product_name)) % 1000000:06d}"
                    st.session_state["custom_allocations"][loc_id] = {
                        "sku_id": new_sku_id,
                        "product_name": product_name,
                        "quantity": quantity,
                        "weight_kg": weight,
                        "dimensions": f"{width:g}x{height:g}x{depth:g} cm",
                        "zone_id": zid,
                        "rack_id": rid,
                        "bay": bay,
                        "shelf_level": shelf,
                        "ruler_dist_m": ruler_dist,
                    }

                    st.success(
                        f"✅ Successfully slotted **{product_name}** ({new_sku_id}) into **{loc_id}**!\n\n"
                        f"- **Zone & Edge:** Zone {zid} · Rack {rid} ({_rack_side_name(rid)} side)\n"
                        f"- **Bay & Shelf:** Bay {int(bay)+1} · Shelf Level L{shelf}\n"
                        f"- **Invisible Ruler Distance from Depot:** **{ruler_dist} m** (strictly along inter-zone corridors)"
                    )
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Location ID", loc_id)
                    c2.metric("Box Size (linear)", f"{width:g} × {height:g} cm")
                    c3.metric("Corridor Ruler Distance", f"{ruler_dist} m")
                else:
                    st.error("No empty bin available that satisfies the item constraints.")

    with tab_search:
        st.caption("Find where an item is stored across all 9 zones.")
        search_sku = st.text_input("SKU ID or Product Name to search", key="search_sku_input", placeholder="e.g. SKU000001 or Hydraulic")
        if (st.button("Search", type="primary", key="search_btn") or search_sku) and search_sku:
            results = []
            if not is_empty and optimized is not None and not optimized.empty:
                sku_matches = optimized[optimized["sku_id"].astype(str).str.contains(search_sku, case=False, na=False)]
                if not sku_matches.empty:
                    for _, row in sku_matches.iterrows():
                        loc_id = str(row["location_id"])
                        loc = loc_lookup.get(loc_id, {})
                        ruler = dd.ruler_path("DEPOT", loc_id, locations)
                        results.append({
                            "SKU ID": row["sku_id"],
                            "Location ID": loc_id,
                            "Zone": loc.get("zone_id", "—"),
                            "Rack": f"{loc.get('rack_id', '—')} ({_rack_side_name(loc.get('rack_id', ''))})",
                            "Bay": f"Bay {int(loc.get('bay', 0))+1}",
                            "Shelf": f"L{loc.get('shelf_level', '—')}",
                            "Quantity": row.get("assigned_quantity", 0),
                            "Ruler Distance from Depot (m)": ruler.get("distance", "—"),
                        })
            for loc_id, item in st.session_state["custom_allocations"].items():
                if search_sku.lower() in item["sku_id"].lower() or search_sku.lower() in item["product_name"].lower():
                    results.append({
                        "SKU ID": item["sku_id"],
                        "Location ID": loc_id,
                        "Zone": item["zone_id"],
                        "Rack": f"{item['rack_id']} ({_rack_side_name(item['rack_id'])})",
                        "Bay": f"Bay {int(item['bay'])+1}",
                        "Shelf": f"L{item['shelf_level']}",
                        "Quantity": item["quantity"],
                        "Ruler Distance from Depot (m)": item.get("ruler_dist_m", "—"),
                    })
            if results:
                st.success(f"Found {len(results)} assigned location(s):")
                st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
            else:
                st.warning(f"No item matching '{search_sku}' was found in active bin allocations.")

    with tab_delete:
        st.caption("Remove an item from its assigned bin.")
        del_loc = st.selectbox("Select Location to de-allocate", list(st.session_state["custom_allocations"].keys()) or ["None allocated via Add Item"], key="del_loc_select")
        if st.button("Clear Location Bin", type="secondary", key="clear_bin_btn") and del_loc in st.session_state["custom_allocations"]:
            cleared = st.session_state["custom_allocations"].pop(del_loc)
            st.success(f"Bin {del_loc} has been cleared of SKU {cleared.get('sku_id')} ({cleared.get('product_name')}).")
            st.rerun()

def render_experiments(data: dict) -> None:
    """Read-only views of the Phase 3 and Phase 4 machine contracts.

    Nothing is recalculated here: the tables come from ``app.phase5_views``, which only
    selects and labels contract fields. Infeasible or unverified comparisons are shown as
    blocked rather than as successful results.
    """
    p3 = p5v.phase3_view(data.get("phase3"))
    p4 = p5v.phase4_view(data.get("phase4"))

    st.subheader("Controlled experiments — Phases 3 & 4")
    st.caption(
        "Every value below is read from `outputs/phase3/phase3_experiments.json` and "
        "`outputs/phase4/phase4_experiments.json` through the existing contracts. The "
        "dashboard does not recompute metrics. Phase 3 travel is a demand-weighted "
        "order-line metric (metres / resolved line); Phase 4 travel is simulated batch-route "
        "distance. They are different metrics and are not combined."
    )

    with st.expander("Phase 6 reproducibility runs", expanded=False):
        registry_base = PROJECT_ROOT / "outputs" / "phase6" / "runs"
        latest = p6r.latest_run(registry_base)
        if not latest["available"]:
            st.info(f"Run registry unavailable: {latest['reason']}")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Latest run", latest["run_id"])
            c2.metric("Status", latest["status"])
            c3.metric("Failed stages", latest["n_failed_stages"])
            st.caption(
                f"Finished {latest['finished_at_utc']} · dataset `{str(latest['dataset_sha256'])[:16]}…` · "
                f"config `{str(latest['config_sha256'])[:16]}…`"
            )
            if latest.get("failed_stage"):
                st.error(f"Failed stage: {latest['failed_stage']}")
            if not latest["stages_table"].empty:
                st.dataframe(latest["stages_table"], hide_index=True, use_container_width=True)
        runs = p6r.load_runs(registry_base)
        if not runs.empty:
            st.markdown("**Recorded runs**")
            statuses = ["All"] + sorted(runs["status"].dropna().unique().tolist())
            chosen = st.selectbox("Run status", statuses, key="phase6_run_status")
            st.dataframe(
                p5v.filter_frame(runs, "status", chosen),
                hide_index=True,
                use_container_width=True,
            )
        st.caption(
            "This registry is read-only. Launching runs, editing weights and per-segment "
            "filters remain outside the current dashboard scope (D28/D44 partial)."
        )

    tab3, tab4 = st.tabs(["Phase 3 — demand metrics", "Phase 4 — simulation"])

    with tab3:
        if not p3["available"]:
            st.warning(f"Phase 3 contract unavailable: {p3['reason']}")
        else:
            if p3["blocked"]:
                st.error(
                    "Phase 3 comparison is blocked by the Phase 2 feasibility gate. "
                    "Cells are diagnostic only and must not be read as a successful result."
                )
            st.markdown(
                f"**Experiment:** `{p3['experiment_id']}` · **Baseline:** "
                f"`{p3['baseline_variant']}` · **Scenario:** `{p3['scenario']}` · "
                f"**Evaluation:** {p3['evaluation_status']} · "
                f"**Leakage checked:** {p3['leakage_checked']}"
            )

            cells = p3["cells"]
            if not cells.empty:
                b1 = cells[cells["Cell"] == "B1"]
                a1 = cells[cells["Cell"] == "A1"]
                c1, c2, c3 = st.columns(3)
                if not b1.empty:
                    c1.metric("Cell B1 — optimized × as-is", f"{b1.iloc[0]['Travel (m, line metric)']:,.1f} m")
                if not a1.empty:
                    c2.metric("Cell A1 — baseline × as-is", f"{a1.iloc[0]['Travel (m, line metric)']:,.1f} m")
                effects = p3["effects"]
                if not effects.empty:
                    placement = effects[effects["Effect"] == "Placement"]
                    if not placement.empty:
                        value = float(placement.iloc[0]["Value (m)"])
                        pct = float(placement.iloc[0]["Percent of A1"])
                        c3.metric("Placement main effect", f"{value:,.1f} m")
                        c3.markdown(
                            f'<span class="kpi-change {"good" if value < 0 else "bad"}">'
                            f'{"↓" if value < 0 else "↑"} {abs(pct):,.2f}% of A1</span>',
                            unsafe_allow_html=True,
                        )
                st.caption(
                    "Placement effect is the averaged main effect: mean(B1, B2) − mean(A1, A2), "
                    "not the direct B1 − A1 pair. The published percent is normalized to A1. "
                    "The fragmentation factor is a real bin-consolidation treatment; the "
                    "pick-rule sensitivity is a separate design shown below."
                )
                st.dataframe(cells, hide_index=True, width="stretch")

            if not p3["effects"].empty:
                st.markdown("**Main effects and interaction**")
                st.dataframe(p3["effects"], hide_index=True, use_container_width=True)
                st.caption(
                    "Difference-in-differences on this single deterministic workload: "
                    "negative metres means less travel. These are not significance tests."
                )

            if not p3["split"].empty:
                st.markdown("**Fit / holdout split**")
                st.dataframe(p3["split"], hide_index=True, use_container_width=True)
                checks = p3.get("split_checks") or {}
                st.caption(
                    f"Method: {checks.get('method', 'temporal_order_level')} · "
                    f"all leakage checks passed: {checks.get('all_passed')} · "
                    "the optimized layout was fitted on A_FIT only."
                )

            if not p3["replenishment"].empty:
                st.markdown("**Replenishment proxy**")
                st.dataframe(p3["replenishment"], hide_index=True, use_container_width=True)
                st.caption(
                    "14-day cover assumption; zero-demand SKUs make zero trips. This is a "
                    "travel proxy, not a schedule or cost model."
                )

            if not p3["sweep"].empty:
                st.markdown("**Objective-weight sensitivity**")
                st.dataframe(p3["sweep"], hide_index=True, use_container_width=True)
                if p3.get("sweep_note"):
                    st.caption(p3["sweep_note"])

            if not p3["pick_rule"].empty:
                st.markdown("**Secondary sensitivity — layout × pick-rule accounting**")
                st.dataframe(p3["pick_rule"], hide_index=True, use_container_width=True)
                st.caption(
                    "This isolates how much a raw comparison depends on charging every bin a "
                    "SKU occupies. It is not the fragmentation treatment above."
                )

            with st.expander("Provenance and reproducibility"):
                st.json(
                    {
                        "experiment_id": p3["experiment_id"],
                        "generated_at_utc": (data.get("phase3") or {}).get("generated_at_utc"),
                        "split_checks": p3.get("split_checks"),
                        "sweep_selected_by_fit_travel": p3.get("sweep_selected"),
                        "caveat": p3.get("caveat"),
                    }
                )

    with tab4:
        if not p4["available"]:
            st.warning(f"Phase 4 contract unavailable: {p4['reason']}")
        else:
            if p4["blocked"]:
                st.error(
                    "Phase 4 comparison is blocked by the feasibility gate. No cell is "
                    "presented as a successful result."
                )
            verification = p4.get("verification") or {}
            st.markdown(
                f"**Experiment:** `{p4['experiment_id']}` · **Baseline:** "
                f"`{p4['baseline_variant']}` · **Evaluation:** {p4['evaluation_status']} · "
                f"**Independent verification:** {'PASS' if verification.get('all_passed') else 'NOT VERIFIED'}"
                f" ({verification.get('n_checks', 0)} checks, {verification.get('n_failed', 0)} failed)"
            )
            workload = p4.get("workload") or {}
            if workload:
                st.caption(
                    f"Workload `{workload.get('workload_id')}` · {workload.get('orders')} orders · "
                    f"{workload.get('lines')} lines · scenario `{workload.get('scenario')}`"
                )

            cells = p4["cells"]
            if not cells.empty:
                b1 = cells[(cells["Cell"] == "B1")]
                a1 = cells[(cells["Cell"] == "A1")]
                if not b1.empty and not a1.empty:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("B1 travel (simulated)", f"{b1.iloc[0]['Travel (m)']:,.1f} m")
                    c2.metric("B1 cycle time", f"{b1.iloc[0]['Cycle (s)']:,.1f} s")
                    c3.metric("B1 throughput", f"{b1.iloc[0]['Throughput (orders/h)']:.2f} /h")
                    st.caption(
                        f"A1 reference values: travel {a1.iloc[0]['Travel (m)']:,.1f} m · "
                        f"cycle {a1.iloc[0]['Cycle (s)']:,.1f} s · "
                        f"throughput {a1.iloc[0]['Throughput (orders/h)']:.2f} orders/h. "
                        "Changes and interaction are read from the effects table below; the "
                        "dashboard does not recompute them."
                    )
                st.dataframe(cells, hide_index=True, use_container_width=True)

            if not p4["effects"].empty:
                st.markdown("**Layout × picking-policy effects**")
                st.dataframe(p4["effects"], hide_index=True, use_container_width=True)
                st.caption(
                    "Factor A is layout, factor B is picking policy. The layout effect is the "
                    "change that survives either route policy; the policy effect is the "
                    "accounting sensitivity."
                )

            if not p4["regimes"].empty:
                st.markdown("**Held-out demand regimes**")
                regime_values = ["All"] + p4["regimes"]["Regime"].dropna().unique().tolist()
                regime_choice = st.selectbox(
                    "Regime filter", regime_values, key="phase4_regime_filter"
                )
                st.dataframe(
                    p5v.filter_frame(p4["regimes"], "Regime", regime_choice),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption(
                    "Regime B and C are different synthetic demand generators, not resamples "
                    "of A. They were not used to fit or select the layout."
                )

            if not p4["headroom"].empty:
                st.markdown("**Structural headroom**")
                st.dataframe(p4["headroom"], hide_index=True, use_container_width=True)
                st.caption(
                    "Near-limit utilisation is a risk, not a target. Hard constraints were not "
                    "weakened to create headroom."
                )

            if p4.get("diagnostics"):
                with st.expander("Rejection diagnostics"):
                    st.json(p4["diagnostics"])

            with st.expander("Identity and verification"):
                st.json(
                    {
                        "frozen_layouts": p4.get("frozen_layouts"),
                        "verification": verification,
                        "caveat": p4.get("caveat"),
                    }
                )


def main() -> None:
    st.markdown(_APP_CSS, unsafe_allow_html=True)
    data = _load_cached()
    locations = data.get("locations")
    topology = dd.topology_summary(locations)

    st.markdown(
        '<div class="hero">'
        '<div class="eyebrow">Warehouse decision support</div>'
        '<h1>Smart Warehouse Slotting &amp; Optimization Engine</h1>'
        '<p>Constraint-aware slotting with ABC demand classification, order affinity, golden-zone '
        'ergonomics and measured baseline-vs-optimized pick-path performance. Every value comes '
        'from the generated dataset and pipeline artifacts.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">Warehouse decision support</div>'
            '<div class="sidebar-title">Run context</div>',
            unsafe_allow_html=True,
        )
        if topology:
            st.markdown(
                f"**Warehouse topology**  \n"
                f"{topology.get('zones')} zones · {topology.get('aisles')} aisles · "
                f"{topology.get('racks')} racks  \n"
                f"{topology.get('bins', 0):,} bins · {topology.get('shelf_levels')} shelf levels  \n"
                f"Golden levels {topology.get('golden_levels')} · "
                f"{fmt_number(topology.get('usable_volume_m3'), 1)} m³ usable"
            )
        else:
            st.warning("Topology data not loaded.")
        layout_label = st.radio(
            "Detail view shows", ["Optimized", "Baseline"], index=0,
            help="Controls the detail views only. The Overview always compares both layouts.",
            key="sidebar_layout",
        )
        layout = "optimized" if layout_label == "Optimized" else "baseline"
        verdict = dd.safety_status(data, "optimized")
        status = verdict["status"]
        if status == "PASS":
            st.success(f"Safety: PASS · {verdict['checks_run']:,} checks")
        elif status == "FAIL":
            st.error(f"Safety: FAIL · {verdict['failed_checks']:,} failed checks")
        else:
            st.warning("Safety: not verified")

        with st.expander("Data sources"):
            for key, (available, reason) in dd.data_availability(data, layout).items():
                st.markdown(f"- **{key}**: {'available' if available else 'unavailable'} — {reason}")
            evaluation = data.get("eval_summary") or {}
            st.caption(
                f"Scenario {evaluation.get('scenario', 'n/a')} · "
                f"inventory {fmt_number(evaluation.get('inventory_units'))} units · "
                f"{fmt_number(evaluation.get('skus_with_inventory'))} SKUs"
            )

    tabs = st.tabs([
        "Overview", "Warehouse Layout", "Pick Routes", "Ergonomics", "Exports",
        "Experiments", "Inventory",
    ])
    with tabs[0]:
        _safe_render("Overview", render_overview, data)
    with tabs[1]:
        _safe_render("Warehouse Layout", render_layout, data, layout)
    with tabs[2]:
        _safe_render("Pick Routes", render_routes, data)
    with tabs[3]:
        _safe_render("Ergonomics", render_ergonomics, data, layout)
    with tabs[4]:
        _safe_render("Exports", render_exports, data, layout)
    with tabs[5]:
        _safe_render("Experiments", render_experiments, data)
    with tabs[6]:
        _safe_render("Inventory", render_inventory_management, data)


if __name__ == "__main__":
    main()


