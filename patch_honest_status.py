#!/usr/bin/env python3
"""
patch_honest_status.py
Run from the repo root:  python patch_honest_status.py

Fixes three lies in the status bars:

  1. MLB "fully operational" — now requires mlb_stats_daily to be SUCCESS,
     not just stats/SOS/injury files present.

  2. Startup Pipeline 100% — mlb_stats_daily is a separate subprocess outside
     the 9-step counter. We fold it in as an extra step so the bar only hits
     100% when the pitching DB is actually built.

  3. Matchup Load 100% — fires when odds rows are loaded but before deep detail
     (pitching/injury) is ready. Label now says "odds loaded" instead of
     "fully loaded" so it doesn't overclaim.
"""

import shutil
from pathlib import Path

TARGET = Path("air_density_full_app_FINAL_TODAYSLATE_FULL.py")

if not TARGET.exists():
    raise SystemExit(f"ERROR: {TARGET} not found. Run from the repo root.")

src = TARGET.read_text(encoding="utf-8")
patches_applied = 0

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1 — MLB full_ready only increments when mlb_stats_daily is SUCCESS
# ─────────────────────────────────────────────────────────────────────────────
OLD1 = """            if lg == "MLB":
                if mlb_task_status == "failed":
                    issues.append(f"mlb stats failed: {mlb_task_error[:64] or 'unknown error'}")
            issue_txt = " | ".join(issues)
            if not issue_txt:
                full_ready += 1
            else:
                issue_count += 1"""

NEW1 = """            if lg == "MLB":
                if mlb_task_status == "failed":
                    issues.append(f"mlb stats failed: {mlb_task_error[:64] or 'unknown error'}")
                elif mlb_task_status in ("running", "pending", "queued", ""):
                    issues.append(f"mlb stats DB building ({int(round(mlb_task_pct))}%)")
            issue_txt = " | ".join(issues)
            if not issue_txt:
                full_ready += 1
            else:
                issue_count += 1"""

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    patches_applied += 1
    print("PATCH 1 applied: MLB not fully operational until mlb_stats_daily is done")
else:
    print("PATCH 1 SKIPPED: block not found (already patched?)")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2a — Startup Pipeline: +1 step for mlb_stats_daily
# ─────────────────────────────────────────────────────────────────────────────
OLD2 = """    _step_total = len(_STATS_SOS_LEAGUES) + 3  # init + stats + each SOS + finalize"""

NEW2 = """    _step_total = len(_STATS_SOS_LEAGUES) + 4  # init + stats + each SOS + finalize + mlb_stats_daily"""

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    patches_applied += 1
    print("PATCH 2a applied: startup step_total +1 for mlb_stats_daily")
else:
    print("PATCH 2a SKIPPED: step_total line not found")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2b — Startup bar hits 100% only after mlb_stats_daily completes
# ─────────────────────────────────────────────────────────────────────────────
OLD2B = """        if proc.returncode == 0:
            log("✅ mlb_stats_daily.py auto-boot complete — DB populated.", "info")
            _startup_task_mark(_task_name, "success", progress_pct=100.0, detail="mlb pre-game stats loaded")
            root.after(0, lambda: m_status_var.set(
                "✅ MLB pre-game stats loaded — double-click any game for full breakdown."))"""

NEW2B = """        if proc.returncode == 0:
            log("✅ mlb_stats_daily.py auto-boot complete — DB populated.", "info")
            _startup_task_mark(_task_name, "success", progress_pct=100.0, detail="mlb pre-game stats loaded")
            root.after(0, lambda: m_status_var.set(
                "✅ MLB pre-game stats loaded — double-click any game for full breakdown."))
            # Advance startup pipeline bar — this was the final step
            try:
                _set_startup_progress_pct(100.0, "daily startup data already complete")
            except Exception:
                pass"""

if OLD2B in src:
    src = src.replace(OLD2B, NEW2B, 1)
    patches_applied += 1
    print("PATCH 2b applied: startup bar hits 100% only after mlb_stats_daily done")
else:
    print("PATCH 2b SKIPPED: mlb success block not found")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3 — Matchup Load: "fully loaded" → "odds loaded"
# ─────────────────────────────────────────────────────────────────────────────
OLD3 = """    _set_matchup_load_progress(100.0, f"fully loaded - {len(data_df)} game(s) ready")"""

NEW3 = """    _set_matchup_load_progress(100.0, f"odds loaded - {len(data_df)} game(s) ready (double-click for full detail)")"""

if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)
    patches_applied += 1
    print("PATCH 3 applied: matchup bar says 'odds loaded' not 'fully loaded'")
else:
    print("PATCH 3 SKIPPED: matchup load line not found")

# ─────────────────────────────────────────────────────────────────────────────
# Write output
# ─────────────────────────────────────────────────────────────────────────────
if patches_applied == 0:
    print("\nNothing to do — all patches already applied or blocks not matched.")
else:
    backup = TARGET.with_suffix(".py.bak2")
    shutil.copy2(TARGET, backup)
    print(f"\nBackup written: {backup}")
    TARGET.write_text(src, encoding="utf-8")
    print(f"{patches_applied}/4 patches applied to {TARGET}")

    import py_compile
    try:
        py_compile.compile(str(TARGET), doraise=True)
        print("Syntax check: OK")
    except py_compile.PyCompileError as e:
        print(f"SYNTAX ERROR — restoring backup: {e}")
        shutil.copy2(backup, TARGET)
        raise SystemExit(1)
