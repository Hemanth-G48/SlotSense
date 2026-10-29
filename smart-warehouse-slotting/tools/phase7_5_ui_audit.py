"""Capture the live dashboard tab-by-tab before/after evidence with Playwright."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def audit(out_dir: Path, width: int, height: int, prefix: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"viewport": [width, height], "tabs": {}, "console": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/chromium",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": width, "height": height})
        page.on(
            "console",
            lambda m: report["console"].append(f"{m.type}: {m.text}")
            if m.type in ("error", "warning")
            else None,
        )
        page.goto("http://localhost:8501", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3500)
        tabs = page.get_by_role("tab")
        names = tabs.all_inner_texts()
        report["tabs_found"] = names
        for i, name in enumerate(names):
            tab = tabs.nth(i)
            tab.click()
            page.wait_for_timeout(1800)
            slug = f"{i:02d}_{name.lower().replace(' ', '_').replace('/', '_')}"
            path = out_dir / f"{prefix}_{slug}_{width}.png"
            page.screenshot(path=str(path), full_page=True)
            pane_text = page.locator('[role="tabpanel"]').last.inner_text()[:1200]
            report["tabs"][name] = {
                "screenshot": str(path),
                "text_excerpt": pane_text,
                "selectboxes": page.get_by_role("combobox").count(),
                "buttons": page.get_by_role("button").count(),
                "tables": page.locator("table").count(),
                "plotly_charts": page.locator(".js-plotly-plot").count(),
            }
        report["console"] = report["console"][-30:]
        browser.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "outputs" / "phase7_5" / "before"))
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--prefix", default="overview")
    args = ap.parse_args()
    result = audit(Path(args.out), args.width, args.height, args.prefix)
    (Path(args.out) / f"audit_{args.width}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"tabs": result["tabs_found"], "console": result["console"]}, indent=2))
    for k, v in result["tabs"].items():
        print(k, "charts", v["plotly_charts"], "tables", v["tables"], "buttons", v["buttons"])


if __name__ == "__main__":
    main()
