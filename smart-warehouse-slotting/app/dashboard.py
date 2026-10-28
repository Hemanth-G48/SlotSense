"""Interactive warehouse slotting & optimization dashboard (Streamlit + Plotly).

Every number, chart, map and table is derived from the generated artifacts in
``../dataset/processed`` and ``outputs/`` through :mod:`app.dashboard_data`. Nothing is
hardcoded: missing backend data produces an explicit "data unavailable" state instead of a
fabricated result.

Run with: ``streamlit run app/dashboard.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from app import dashboard_data as dd
except ModuleNotFoundError:  # streamlit run app/dashboard.py puts app/ on sys.path
    import dashboard_data as dd  # type: ignore[no-redef]

st.set_page_config(page_title="Smart Warehouse Slotting", page_icon="🏭", layout="wide")

PLOT_HEIGHT = 600
NEUTRAL = "#95a5a6"
ACCENT = "#2471a3"
BASELINE_COLOR = "#95a5a6"
OPTIMIZED_COLOR = "#2471a3"


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
        if kind == "reduction":
            return f"▼ {value:,.1f}% (reduction)"
        return f"▲ {value:,.1f}% (increase)"
    if row.get("change_pp") is not None:
        return f"{row['change_pp']:+,.2f} pp"
    if row.get("delta") is not None:
        return f"{row['delta']:+,.0f}"
    return "not defined"


def _metric_note(row: dict) -> str:
    direction = row.get("direction") or ""
    return f"Baseline: {metric_text(row['key'], row['baseline'])} · {change_label(row)} · {direction}".strip()


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
    st.subheader("Baseline vs optimized — operational KPIs")
    st.caption(
        "Same order workload, warehouse geometry, routing method and on-hand inventory in both "
        "layouts. Percent changes are computed from the baseline and optimized values shown. "
        "Utilization is reported in percentage points (pp)."
    )

    cards = [key for key in _CARD_KEYS if key in rows]
    for start in range(0, len(cards), 4):
        columns = st.columns(4)
        for column, key in zip(columns, cards[start:start + 4]):
            row = rows[key]
            if key == "valid_assignments":
                required = _num(rows.get("required_assignments", {}).get("optimized"))
                value = f"{fmt_number(row['optimized'])} / {fmt_number(required)}"
            else:
                value = metric_text(key, row["optimized"])
            with column:
                st.metric(f"{row['label']}", value, delta=change_label(row), delta_color="off", help=row.get("definition"))
                st.caption(_metric_note(row))

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
        delta=f"{checks_run:,} checks run" if checks_run else "no validation run",
        delta_color="off",
        help="PASS is shown only when the validator ran on this layout and returned zero failed checks.",
    )

    # ---- solver status ------------------------------------------------------
    st.subheader("Optimization run")
    optimization = data.get("opt_summary")
    if optimization:
        cols = st.columns(4)
        cols[0].metric("Solver status", "FEASIBLE" if optimization.get("feasibility") else "INFEASIBLE")
        cols[1].metric("Optimization runtime", f"{fmt_number(optimization.get('runtime_sec'), 2)} s")
        cols[2].metric("Moves evaluated", fmt_number(optimization.get("moves_evaluated")))
        cols[3].metric("Globally optimal", "No" if not optimization.get("globally_optimal") else "Yes")
        st.caption(
            f"Algorithm: {optimization.get('algorithm', 'n/a')} · "
            f"stopping reason: {optimization.get('stopping_reason', 'n/a')} · "
            f"objective {fmt_number(optimization.get('final_objective'), 1)} "
            f"(baseline {fmt_number(optimization.get('baseline_objective'), 1)})."
        )
    else:
        _unavailable("No optimization summary found. Run `python app/main.py optimize` first.")

    # ---- comparison charts --------------------------------------------------
    st.subheader("Comparison charts")
    st.plotly_chart(
        _normalized_figure(
            rows,
            [
                "total_travel_distance_m",
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
def plan_figure(
    frame: pd.DataFrame,
    racks: pd.DataFrame,
    aisles: pd.DataFrame,
    dispatch: tuple[float, float] | None,
    selected_id: str | None,
    color_mode: str = "ABC class",
    title: str = "",
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
    figure.update_layout(
        title=title,
        height=PLOT_HEIGHT,
        margin=dict(l=10, r=10, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        plot_bgcolor="#ffffff",
    )
    figure.update_xaxes(title="x (m)", showgrid=False)
    figure.update_yaxes(title="y (m)", scaleanchor="x", scaleratio=1, showgrid=False)
    return figure


def elevation_figure(
    frame: pd.DataFrame,
    selected_id: str | None,
    golden_levels: list[int],
    color_mode: str = "ABC class",
    title: str = "",
) -> go.Figure:
    """Rack elevation: bays/bins along x, shelf levels along y, golden band highlighted."""
    figure = go.Figure()
    data_frame = frame.copy()
    data_frame["shelf_level"] = pd.to_numeric(data_frame["shelf_level"], errors="coerce").fillna(0).astype(int)
    slots = sorted({(int(row.bay), float(row.x_m)) for row in data_frame.itertuples(index=False)})
    slot_index = {slot: index for index, slot in enumerate(slots)}
    data_frame["slot"] = [slot_index[(int(r.bay), float(r.x_m))] for r in data_frame.itertuples(index=False)]
    max_slot = max(len(slots) - 1, 0)
    levels = sorted(data_frame["shelf_level"].unique())

    for level in levels:
        if level in golden_levels:
            figure.add_shape(
                type="rect", x0=-0.6, x1=max_slot + 0.6, y0=level - 0.42, y1=level + 0.42,
                line=dict(width=0), fillcolor="#fef5e7", layer="below",
            )
    figure.add_shape(
        type="rect", x0=-0.6, x1=max_slot + 0.6, y0=min(levels) - 0.5, y1=max(levels) + 0.5,
        line=dict(color="#7f8c8d", width=2), fillcolor="rgba(0,0,0,0)", layer="below",
    )

    if color_mode == "ABC class":
        for cls in dd.CLASS_ORDER:
            subset = data_frame[data_frame["abc_class"] == cls]
            if subset.empty:
                continue
            figure.add_trace(go.Scatter(
                x=subset["slot"], y=subset["shelf_level"], mode="markers",
                name=f"Class {cls}" if cls != "unassigned" else "Unassigned",
                marker=dict(symbol="square", size=26, color=dd.CLASS_COLORS[cls], line=dict(width=1, color="#ffffff")),
                customdata=subset[["location_id", "sku_id", "shelf_level"]].astype(str).values,
                hovertemplate="%{customdata[0]}<br>SKU %{customdata[1]}<br>Shelf level %{customdata[2]}<extra></extra>",
            ))
    else:
        subset = data_frame
        values = (
            pd.to_numeric(subset["bin_volume_util_pct"], errors="coerce").fillna(0.0)
            if color_mode == "Utilization"
            else subset["constraint_status"].map({"OK": 1.0, "FAIL": 0.0, "UNKNOWN": 0.5}).fillna(0.5)
        )
        colorscale = "Blues" if color_mode == "Utilization" else "RdYlGn"
        figure.add_trace(go.Scatter(
            x=subset["slot"], y=subset["shelf_level"], mode="markers",
            name=color_mode,
            marker=dict(symbol="square", size=26, color=values, colorscale=colorscale, cmin=0, cmax=100 if color_mode == "Utilization" else 1,
                        line=dict(width=1, color="#ffffff")),
            customdata=subset[["location_id", "sku_id"]].astype(str).values,
            hovertemplate="%{customdata[0]}<br>SKU %{customdata[1]}<extra></extra>",
        ))

    if selected_id is not None:
        selected = data_frame[data_frame["location_id"].astype(str) == str(selected_id)]
        if not selected.empty:
            figure.add_trace(go.Scatter(
                x=selected["slot"], y=selected["shelf_level"], mode="markers", name="Selected bin",
                marker=dict(symbol="circle-open", size=34, color="#111111", line=dict(width=3)),
                hoverinfo="skip", showlegend=False,
            ))
    figure.update_layout(
        title=title,
        height=PLOT_HEIGHT,
        margin=dict(l=10, r=10, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
    )
    figure.update_xaxes(
        title="Bay / bin position across the rack",
        tickmode="array",
        tickvals=[slot_index[s] for s in slots],
        ticktext=[f"b{bay}.{i}" for i, (bay, _x) in enumerate(slots)],
    )
    figure.update_yaxes(
        title="Shelf level (0 = floor level)",
        tickmode="array",
        tickvals=levels,
        ticktext=[f"L{level}" + (" · golden" if level in golden_levels else "") for level in levels],
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
        _detail_line("Distance to dispatch", f"{fmt_number(record.get('distance_to_dispatch_m'), 1)} m (network)")
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
    st.caption(
        f"Topology read from locations.csv: {topology.get('zones')} zones · "
        f"{topology.get('aisles')} aisles · {topology.get('racks')} racks · "
        f"{topology.get('bins', 0):,} bins · {topology.get('shelf_levels')} shelf levels "
        f"(golden levels {topology.get('golden_levels')}) · usable volume "
        f"{fmt_number(topology.get('usable_volume_m3'), 1)} m³. Showing the **{layout}** assignment "
        "(switch the detail layout in the sidebar to compare). Aisle connections and cross-aisles are "
        "modeled in the routing graph (aisle-entrance and zone-hub nodes); the plan draws the aisle bands."
    )

    zones = sorted(locations["zone_id"].astype(str).unique())
    view = st.radio("View", ["Plan (zone)", "Rack elevation"], horizontal=True, key="layout_view")
    control_a, control_b, control_c, control_d = st.columns(4)
    default_zone_index = zones.index("Z1") if "Z1" in zones else 0
    zone = control_a.selectbox("Zone", zones, index=default_zone_index, key="layout_zone")
    levels = sorted(int(v) for v in locations.loc[locations["zone_id"].astype(str) == zone, "shelf_level"].unique())
    golden_levels = topology.get("golden_levels", [])
    default_level = golden_levels[0] if golden_levels else levels[0]
    level = control_b.selectbox(
        "Shelf level", levels,
        index=levels.index(default_level) if default_level in levels else 0,
        key="layout_level",
    )
    zone_racks = sorted(locations.loc[locations["zone_id"].astype(str) == zone, "rack_id"].astype(str).unique())
    selected_rack = control_b.selectbox("Rack (elevation)", zone_racks, key="layout_rack") if view == "Rack elevation" else None
    color_mode = control_c.selectbox(
        "Colour by", ["ABC class", "Utilization", "Constraint status", "Assignment change"],
        key="layout_color",
    )
    assigned_only = control_d.checkbox("Assigned bins only", value=False, key="layout_assigned_only")

    filter_a, filter_b, filter_c, filter_d = st.columns(4)
    abc_filter = filter_a.multiselect("ABC class", dd.CLASS_ORDER, default=dd.CLASS_ORDER, key="layout_abc")
    aisles = ["All"] + sorted(locations.loc[locations["zone_id"].astype(str) == zone, "aisle_id"].astype(str).unique())
    aisle_choice = filter_b.selectbox("Aisle", aisles, key="layout_aisle")
    racks = ["All"] + zone_racks
    rack_choice = filter_c.selectbox("Rack", racks, key="layout_rack_filter") if view == "Plan (zone)" else "All"
    hazard_options = ["All"] + sorted(locations["allowed_hazard"].astype(str).str.split("|").explode().unique())
    hazard_choice = filter_d.selectbox("Stored hazard class", hazard_options, key="layout_hazard")

    filter_e, filter_f = st.columns(2)
    min_util = filter_e.slider("Minimum bin utilization (%)", 0, 100, 0, key="layout_min_util")
    status_choice = filter_f.selectbox(
        "Constraint status", ["All", "OK", "FAIL", "UNKNOWN"], key="layout_status"
    )

    if color_mode == "Assignment change" and "baseline" not in data:
        st.info("Assignment comparison needs both baseline and optimized outputs; falling back to ABC colouring.")
        color_mode = "ABC class"

    zone_locations = locations[locations["zone_id"].astype(str) == zone]
    if not zone_locations.empty:
        zone_profile = zone_locations.iloc[0]
        st.caption(
            f"Zone {zone} · type **{zone_profile.get('zone_type', 'n/a')}** · "
            f"allowed handling: {zone_profile.get('allowed_handling', 'n/a')} · "
            f"allowed hazard classes: {zone_profile.get('allowed_hazard', 'n/a')} · "
            f"bin module: {fmt_number(zone_profile.get('width_cm'), 0)} × "
            f"{fmt_number(zone_profile.get('height_cm'), 0)} × "
            f"{fmt_number(zone_profile.get('depth_cm'), 0)} cm. "
            "Hazard, heavy and small-parts zones are separate physical zones in the topology."
        )
    rack_geometry = dd.rack_geometry(zone_locations)
    aisle_geometry = dd.aisle_geometry(zone_locations)
    dispatch = dd.dispatch_point(data)

    frame = dd.filter_locations(
        state,
        abc_classes=[c for c in abc_filter if c in dd.CLASS_ORDER],
        zone=zone,
        aisle=None if aisle_choice == "All" else aisle_choice,
        rack=None if rack_choice == "All" or view != "Plan (zone)" else rack_choice,
        shelf=level if view == "Plan (zone)" else None,
        hazard=None if hazard_choice == "All" else hazard_choice,
        min_utilization=float(min_util),
        constraint_status=None if status_choice == "All" else status_choice,
        assigned_only=assigned_only,
    )

    if frame.empty:
        st.info("No storage locations match the current filters. Widen the filters to see bins.")
        return

    if view == "Plan (zone)":
        title = f"{zone} · shelf level {level} — plan view ({layout})"
        if level in golden_levels:
            title += " · golden shelf level"
        figure = plan_figure(frame, rack_geometry, aisle_geometry, dispatch, None, color_mode, title)
        chart_key = "layout_plan_chart"
    else:
        rack_frame = dd.filter_locations(
            state,
            abc_classes=[c for c in abc_filter if c in dd.CLASS_ORDER],
            zone=zone,
            aisle=None if aisle_choice == "All" else aisle_choice,
            rack=selected_rack,
            hazard=None if hazard_choice == "All" else hazard_choice,
            min_utilization=float(min_util),
            constraint_status=None if status_choice == "All" else status_choice,
            assigned_only=assigned_only,
        )
        if rack_frame.empty:
            st.info("No bins in this rack match the current filters.")
            return
        frame = rack_frame
        figure = elevation_figure(
            rack_frame, None, golden_levels, color_mode,
            f"{zone} · rack {selected_rack} — elevation ({layout})",
        )
        chart_key = "layout_elevation_chart"

    if color_mode == "ABC class":
        st.markdown(_class_legend_html(frame), unsafe_allow_html=True)
    else:
        st.caption(
            "Class colours are fixed across the app (A = red, B = amber, C = blue, unassigned = grey). "
            "Switch “Colour by” back to ABC class for the demand legend."
        )

    event = st.plotly_chart(
        figure, width="stretch", on_select="rerun", selection_mode="points", key=chart_key
    )
    clicked = _selection_point(event)
    options = sorted(frame["location_id"].astype(str).unique())
    if clicked in options:
        st.session_state["layout_selected"] = clicked
    current = st.session_state.get("layout_selected")
    if current not in options:
        st.session_state["layout_selected"] = options[0]
    location_id = st.selectbox(
        "Inspect storage location", options, key="layout_selected",
        help="Click a bin on the map or pick a location id here.",
    )

    highlight = plan_figure(
        frame, rack_geometry, aisle_geometry, dispatch, location_id, color_mode,
        f"{zone} · bin {location_id}" if view == "Plan (zone)" else f"rack {selected_rack} · bin {location_id}",
    ) if view == "Plan (zone)" else elevation_figure(
        frame, location_id, golden_levels, color_mode, f"rack {selected_rack} · bin {location_id}",
    )
    with st.expander("Highlight selected bin", expanded=False):
        highlight.update_layout(height=340)
        st.plotly_chart(highlight, width="stretch", key=f"highlight_{view}", config={"displayModeBar": False})

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
            avg_distance=("distance_to_dispatch_m", "mean"),
            demand_units=("demand_units", "sum"),
            golden_demand_units=("golden_units", "sum"),
        ).reset_index()
        grouped["golden_share_pct"] = (
            grouped["golden_demand_units"] / grouped["demand_units"].replace(0, pd.NA) * 100
        ).round(2)
        grouped = grouped.rename(columns={
            "abc_class": "Class", "skus": "SKUs", "avg_distance": "Avg distance to dispatch (m)",
            "golden_share_pct": "Demand-weighted golden-zone share (%)",
        })[["Class", "SKUs", "Avg distance to dispatch (m)", "Demand-weighted golden-zone share (%)"]]
        st.caption(
            "Prime accessibility is assessed with two measured values: aisle-network distance from the "
            "assigned bin to dispatch, and the demand-weighted share of units on golden shelf levels. "
            "No threshold is invented — both are reported as measured."
        )
        st.dataframe(grouped, hide_index=True, width="stretch")

        controls = st.columns(4)
        class_filter = controls[0].multiselect("Class", dd.CLASS_ORDER, default=["A", "B", "C"], key="demand_class")
        search = controls[1].text_input("Search SKU or product", key="demand_search")
        sort_by = controls[2].selectbox(
            "Sort by", ["Demand (high to low)", "Demand (low to high)", "SKU id", "Distance to dispatch"],
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
        elif sort_by == "Distance to dispatch":
            view = view.sort_values("distance_to_dispatch_m", ascending=False)
        else:
            view = view.sort_values("sku_id")
        columns = [
            "sku_id", "product_name", "abc_class", "demand", "rank", "cumulative_share",
            "on_hand", "assigned_qty", "location_id", "distance_to_dispatch_m", "shelf_level", "golden_zone",
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
                        f"zone {info.get('zone_id') or '—'} · shelf L{info.get('shelf_level') if info.get('shelf_level') is not None else '—'} · "
                        f"distance to dispatch {fmt_number(info.get('distance_to_dispatch_m'), 1)} m"
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
    figure = go.Figure()
    for row in racks.itertuples(index=False):
        figure.add_shape(
            type="rect", x0=row.x_min, x1=row.x_max, y0=row.y_min, y1=row.y_max,
            line=dict(color="#d5d8dc", width=0.5), fillcolor="#f8f9f9", layer="below",
        )
    figure.add_trace(go.Scatter(
        x=stops["x_m"], y=stops["y_m"], mode="lines", name="Route sequence",
        line=dict(color=ACCENT, width=2, dash="dot"),
        hovertemplate="Stop %{text}<extra></extra>", text=stops["sequence"],
    ))
    labels = ["" if str(stop) == "DEPOT" else str(stop) for stop in stops["sequence"]]
    figure.add_trace(go.Scatter(
        x=stops["x_m"], y=stops["y_m"], mode="markers+text", name="Pick stops",
        marker=dict(size=11, color="#2471a3", line=dict(width=1, color="#ffffff")),
        text=labels, textposition="top center",
        customdata=stops[["location_id", "skus", "leg_distance_m", "cumulative_distance_m"]].astype(str).values,
        hovertemplate=(
            "Stop %{text} · %{customdata[0]}<br>SKUs %{customdata[1]}<br>"
            "Leg %{customdata[2]} m · cumulative %{customdata[3]} m<extra></extra>"
        ),
    ))
    if dispatch is not None:
        figure.add_trace(go.Scatter(
            x=[dispatch[0]], y=[dispatch[1]], mode="markers+text", name="Dispatch / I-O",
            marker=dict(symbol="star", size=18, color="#f1c40f", line=dict(width=1, color="#7d6608")),
            text=["I-O"], textposition="bottom center",
            hovertemplate="Dispatch point (%{x:.1f}, %{y:.1f}) m<extra></extra>",
        ))
    figure.update_layout(
        title=title, height=560, margin=dict(l=10, r=10, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        xaxis_title="x (m)", yaxis_title="y (m)",
    )
    figure.update_yaxes(scaleanchor="x", scaleratio=1)
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
        cols[1].metric(
            "Travel distance", f"{fmt_number(opt.get('distance_m'), 1)} m",
            delta=f"▼ {distance_reduction:.1f}% vs baseline" if distance_reduction is not None else "not defined",
            delta_color="off",
        )
        cols[2].metric(
            "Cycle time", f"{fmt_number(opt.get('cycle_time_sec'), 1)} s",
            delta=f"▼ {time_reduction:.1f}% vs baseline" if time_reduction is not None else "not defined",
            delta_color="off",
        )
        cols[3].metric("Pick locations", f"{fmt_number(opt.get('n_locations'))}", delta=f"baseline {fmt_number(base.get('n_locations'))}", delta_color="off")
        st.caption(
            f"Baseline: {fmt_number(base.get('distance_m'), 1)} m / {fmt_number(base.get('cycle_time_sec'), 1)} s · "
            f"Optimized: {fmt_number(opt.get('distance_m'), 1)} m / {fmt_number(opt.get('cycle_time_sec'), 1)} s. "
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
                st.caption("Plan schematic: axes are metres; the display aspect is stretched so the full route fits.")

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
    cols[0].metric("Safety verdict", verdict["status"], delta=f"{layout} layout", delta_color="off")
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
    shelf = shelf.rename(columns={
        "shelf_level": "Shelf level", "height_min_m": "Height min (m)", "height_max_m": "Height max (m)",
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
            column.metric(row["label"], metric_text(key, row["optimized"]), delta=change_label(row), delta_color="off")
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
                exceptions[["sku_id", "product_name", "demand", "assigned_qty", "location_id", "zone_id", "shelf_level", "distance_to_dispatch_m"]].head(100),
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
                    run_phase6(dd.DATA_DIR, scenario="A", out=dd.EVAL)
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
def main() -> None:
    data = _load_cached()
    locations = data.get("locations")
    topology = dd.topology_summary(locations)

    st.title("Smart Warehouse Slotting & Optimization Engine")
    st.caption(
        "Constraint-aware slotting with ABC demand classification, order affinity, golden-zone ergonomics "
        "and measured baseline-vs-optimized pick-path performance. All values are computed from the "
        "generated dataset and pipeline outputs."
    )

    with st.sidebar:
        st.header("Run context")
        if topology:
            st.markdown(
                f"**Warehouse topology**\n\n"
                f"{topology.get('zones')} zones · {topology.get('aisles')} aisles · "
                f"{topology.get('racks')} racks\n\n"
                f"{topology.get('bins', 0):,} bins · {topology.get('shelf_levels')} shelf levels · "
                f"golden levels {topology.get('golden_levels')}\n\n"
                f"Usable volume {fmt_number(topology.get('usable_volume_m3'), 1)} m³"
            )
        else:
            st.warning("Topology data not loaded.")
        layout_label = st.radio(
            "Detail layout", ["Optimized", "Baseline"], index=0,
            help="Controls the layout, constraints, ergonomics and affinity detail views. The overview always compares both.",
            key="sidebar_layout",
        )
        layout = "optimized" if layout_label == "Optimized" else "baseline"
        verdict = dd.safety_status(data, "optimized")
        status = verdict["status"]
        if status == "PASS":
            st.success(f"Safety: PASS ({verdict['checks_run']:,} checks)")
        elif status == "FAIL":
            st.error(f"Safety: FAIL ({verdict['failed_checks']:,} failed checks)")
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
        "Overview", "Warehouse Layout", "Demand & ABC", "Order Affinity", "Pick Routes",
        "Constraints & Safety", "Ergonomics", "Optimization", "Exports",
    ])
    with tabs[0]:
        render_overview(data)
    with tabs[1]:
        render_layout(data, layout)
    with tabs[2]:
        render_demand(data)
    with tabs[3]:
        render_affinity(data, layout)
    with tabs[4]:
        render_routes(data)
    with tabs[5]:
        render_constraints(data, layout)
    with tabs[6]:
        render_ergonomics(data, layout)
    with tabs[7]:
        render_optimization(data)
    with tabs[8]:
        render_exports(data, layout)


if __name__ == "__main__":
    main()


