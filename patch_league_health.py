#!/usr/bin/env python3
"""
patch_league_health.py
Run from the repo root:  python patch_league_health.py

Patches air_density_full_app_FINAL_TODAYSLATE_FULL.py with:
  1. Replaces the two-bar "Pipeline Status" frame with one "Overall Readiness" master bar.
  2. Reorders the League Health bars to: MLB, NFL, NCAAF, NBA, NCAAB, NHL (one bar each).
  3. Updates the master bar every time _refresh_league_ingest_board fires.
"""

import re
import shutil
from pathlib import Path

TARGET = Path("air_density_full_app_FINAL_TODAYSLATE_FULL.py")

if not TARGET.exists():
    raise SystemExit(f"ERROR: {TARGET} not found. Run this script from the repo root.")

src = TARGET.read_text(encoding="utf-8")
original = src
patches_applied = 0

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1 — Replace two-bar Pipeline Status frame with one master bar
# ─────────────────────────────────────────────────────────────────────────────
OLD1 = """# Dashboard landing section: startup/load progress at a glance.
dashboard_progress_frame = ttk.LabelFrame(dashboard_body, text="Pipeline Status", padding=10, style="Card.TLabelframe")
dashboard_progress_frame.pack(fill=tk.X, padx=6, pady=(6, 4))
ttk.Label(dashboard_progress_frame, text="Startup Pipeline", width=18).grid(row=0, column=0, sticky="w", **pad)
ttk.Progressbar(
    dashboard_progress_frame,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_startup_progress_pct_var,
    length=360,
    style="Pipeline.Horizontal.TProgressbar",
).grid(row=0, column=1, sticky="ew", **pad)
ttk.Label(
    dashboard_progress_frame,
    textvariable=_startup_progress_text_var,
    style="SubtleCard.TLabel",
).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

ttk.Label(dashboard_progress_frame, text="Matchup Load", width=18).grid(row=2, column=0, sticky="w", **pad)
ttk.Progressbar(
    dashboard_progress_frame,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_matchup_progress_pct_var,
    length=360,
    style="Pipeline.Horizontal.TProgressbar",
).grid(row=2, column=1, sticky="ew", **pad)
ttk.Label(
    dashboard_progress_frame,
    textvariable=_matchup_progress_text_var,
    style="SubtleCard.TLabel",
).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
dashboard_progress_frame.grid_columnconfigure(1, weight=1)"""

NEW1 = """# Dashboard landing section: one master overall readiness bar.
_master_readiness_pct_var  = tk.DoubleVar(value=0.0)
_master_readiness_text_var = tk.StringVar(value="Overall readiness: standing by")
dashboard_progress_frame = ttk.LabelFrame(dashboard_body, text="Overall Readiness", padding=10, style="Card.TLabelframe")
dashboard_progress_frame.pack(fill=tk.X, padx=6, pady=(6, 4))
ttk.Label(dashboard_progress_frame, text="All Leagues", width=18).grid(row=0, column=0, sticky="w", **pad)
ttk.Progressbar(
    dashboard_progress_frame,
    orient=tk.HORIZONTAL,
    mode="determinate",
    maximum=100.0,
    variable=_master_readiness_pct_var,
    length=360,
    style="Pipeline.Horizontal.TProgressbar",
).grid(row=0, column=1, sticky="ew", **pad)
ttk.Label(
    dashboard_progress_frame,
    textvariable=_master_readiness_text_var,
    style="SubtleCard.TLabel",
).grid(row=1, column=0, columnspan=2, sticky="w", **pad)
dashboard_progress_frame.grid_columnconfigure(1, weight=1)"""

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    patches_applied += 1
    print("PATCH 1 applied: master readiness bar")
else:
    print("PATCH 1 SKIPPED: block not found (already patched?)")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2 — Reorder league loop: MLB, NFL, NCAAF, NBA, NCAAB, NHL
# ─────────────────────────────────────────────────────────────────────────────
OLD2 = """_league_ingest_widgets = {}
for _idx, _lg in enumerate(_STATS_SOS_LEAGUES, start=1):
    _pct_var = tk.DoubleVar(value=0.0)
    _summary_var = tk.StringVar(value="queued")
    _issue_var = tk.StringVar(value="")
    ttk.Label(league_ingest_frame, text=f"{_lg}", width=7).grid(row=_idx, column=0, sticky="w", **pad)
    ttk.Progressbar(
        league_ingest_frame,
        orient=tk.HORIZONTAL,
        mode="determinate",
        maximum=100.0,
        variable=_pct_var,
        length=260,
        style="League.Horizontal.TProgressbar",
    ).grid(row=_idx, column=1, sticky="w", **pad)
    ttk.Label(
        league_ingest_frame,
        textvariable=_summary_var,
        style="StatusCard.TLabel",
        width=54,
        wraplength=520,
        justify="left",
    ).grid(row=_idx, column=2, sticky="w", **pad)
    ttk.Label(
        league_ingest_frame,
        textvariable=_issue_var,
        style="AlertCard.TLabel",
        wraplength=980,
        justify="left",
    ).grid(row=_idx, column=3, sticky="w", **pad)
    _league_ingest_widgets[_lg] = {
        "pct": _pct_var,
        "summary": _summary_var,
        "issue": _issue_var,
    }

league_ingest_frame.grid_columnconfigure(3, weight=1)"""

NEW2 = """# One bar per sport in display order: MLB, NFL, NCAAF, NBA, NCAAB, NHL
_LEAGUE_HEALTH_DISPLAY_ORDER = ["MLB", "NFL", "NCAAF", "NBA", "NCAAB", "NHL"]

_league_ingest_widgets = {}
for _idx, _lg in enumerate(_LEAGUE_HEALTH_DISPLAY_ORDER, start=1):
    _pct_var = tk.DoubleVar(value=0.0)
    _summary_var = tk.StringVar(value="queued")
    _issue_var = tk.StringVar(value="")
    ttk.Label(league_ingest_frame, text=f"{_lg}", width=7).grid(row=_idx, column=0, sticky="w", **pad)
    ttk.Progressbar(
        league_ingest_frame,
        orient=tk.HORIZONTAL,
        mode="determinate",
        maximum=100.0,
        variable=_pct_var,
        length=260,
        style="League.Horizontal.TProgressbar",
    ).grid(row=_idx, column=1, sticky="ew", **pad)
    ttk.Label(
        league_ingest_frame,
        textvariable=_summary_var,
        style="StatusCard.TLabel",
        width=54,
        wraplength=520,
        justify="left",
    ).grid(row=_idx, column=2, sticky="w", **pad)
    ttk.Label(
        league_ingest_frame,
        textvariable=_issue_var,
        style="AlertCard.TLabel",
        wraplength=980,
        justify="left",
    ).grid(row=_idx, column=3, sticky="w", **pad)
    _league_ingest_widgets[_lg] = {
        "pct": _pct_var,
        "summary": _summary_var,
        "issue": _issue_var,
    }

league_ingest_frame.grid_columnconfigure(1, weight=1)
league_ingest_frame.grid_columnconfigure(3, weight=1)"""

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    patches_applied += 1
    print("PATCH 2 applied: league display order MLB/NFL/NCAAF/NBA/NCAAB/NHL")
else:
    print("PATCH 2 SKIPPED: block not found (already patched?)")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3 — Drive master bar from _refresh_league_ingest_board
# ─────────────────────────────────────────────────────────────────────────────
OLD3 = """    _dashboard_league_status_var.set(
        f"League readiness: {full_ready}/{len(_STATS_SOS_LEAGUES)} fully operational | open issues: {issue_count}"
    )
    try:
        _update_dashboard_hero(full_ready=full_ready, issue_count=issue_count)
    except Exception:
        pass"""

NEW3 = """    _dashboard_league_status_var.set(
        f"League readiness: {full_ready}/{len(_STATS_SOS_LEAGUES)} fully operational | open issues: {issue_count}"
    )
    # Push average of all per-league pcts into the master bar
    try:
        _all_pcts = [
            _league_ingest_widgets[_lg]["pct"].get()
            for _lg in _STATS_SOS_LEAGUES
            if _lg in _league_ingest_widgets
        ]
        _master_pct = sum(_all_pcts) / len(_all_pcts) if _all_pcts else 0.0
        _master_readiness_pct_var.set(float(_master_pct))
        _master_readiness_text_var.set(
            f"Overall readiness: {int(round(_master_pct))}%  |  "
            f"{full_ready}/{len(_STATS_SOS_LEAGUES)} leagues ready  |  "
            f"{issue_count} issue{'s' if issue_count != 1 else ''}"
        )
    except Exception:
        pass
    try:
        _update_dashboard_hero(full_ready=full_ready, issue_count=issue_count)
    except Exception:
        pass"""

if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)
    patches_applied += 1
    print("PATCH 3 applied: master bar driven from refresh function")
else:
    print("PATCH 3 SKIPPED: block not found (already patched?)")

# ─────────────────────────────────────────────────────────────────────────────
# Write output
# ─────────────────────────────────────────────────────────────────────────────
if patches_applied == 0:
    print("\nNothing to do — all patches already applied or blocks not matched.")
else:
    backup = TARGET.with_suffix(".py.bak")
    shutil.copy2(TARGET, backup)
    print(f"\nBackup written: {backup}")
    TARGET.write_text(src, encoding="utf-8")
    print(f"{patches_applied}/3 patches applied to {TARGET}")

    # Syntax check
    import py_compile, tempfile, os
    try:
        py_compile.compile(str(TARGET), doraise=True)
        print("Syntax check: OK")
    except py_compile.PyCompileError as e:
        print(f"SYNTAX ERROR — restoring backup: {e}")
        shutil.copy2(backup, TARGET)
        raise SystemExit(1)
