#!/usr/bin/env python3
"""
patch_honest_status.py
Run from the repo root:  python patch_honest_status.py

Fixes four lies in the status bars:

  1. ALL SPORTS — injury_news_daily RUNNING silently passed as ready.
     Now: if injury is required and the task is still running or pending,
     the league is NOT counted as fully operational.

  2. MLB specifically — mlb_stats_daily running/pending also blocks full_ready.

  3. Startup Pipeline 100% — mlb_stats_daily is outside the 9-step counter.
     Folded in as an extra step so bar only hits 100% when pitching DB is built.

  4. Matchup Load 100% — label changed from "fully loaded" to "odds loaded"
     so it doesn't claim full readiness before pitching/injury detail is ready.
"""

import shutil
from pathlib import Path

TARGET = Path("air_density_full_app_FINAL_TODAYSLATE_FULL.py")

if not TARGET.exists():
    raise SystemExit(f"ERROR: {TARGET} not found. Run from the repo root.")

src = TARGET.read_text(encoding="utf-8")
patches_applied = 0

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1 — ALL SPORTS: injury running/pending blocks full_ready
#
# Old logic:
#   if injury_required and (not injury_ready) and inj_task_status != "running":
#       issues.append(...)
# This meant: if injury IS running, NO issue was appended → league counted ready.
#
# New logic: running or pending both block full_ready; show progress in the label.
# ─────────────────────────────────────────────────────────────────────────────
OLD1 = """            if injury_required and (not injury_ready) and inj_task_status != "running":
                issues.append(_inj_state_detail or "injury file pending")"""

NEW1 = """            if injury_required and (not injury_ready):
                if inj_task_status == "running":
                    issues.append("injury/news data building...")
                else:
                    issues.append(_inj_state_detail or "injury file pending")"""

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    patches_applied += 1
    print("PATCH 1 applied: ALL sports — injury running now blocks full_ready")
else:
    print("PATCH 1 SKIPPED: injury block not found (already patched?)")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2 — MLB: mlb_stats_daily running/pending also blocks full_ready
# ─────────────────────────────────────────────────────────────────────────────
OLD2 = """            if lg == "MLB":
                if mlb_task_status == "failed":
                    issues.append(f"mlb stats failed: {mlb_task_error[:64] or 'unknown error'}")
            issue_txt = " | ".join(issues)
            if not issue_txt:
                full_ready += 1
            else:
                issue_count += 1"""

NEW2 = """            if lg == "MLB":
                if mlb_task_status == "failed":
                    issues.append(f"mlb stats failed: {mlb_task_error[:64] or 'unknown error'}")
                elif mlb_task_status in ("running", "pending", "queued", ""):
                    issues.append(f"mlb stats DB building ({int(round(mlb_task_pct))}%)")
            issue_txt = " | ".join(issues)
            if not issue_txt:
                full_ready += 1
            else:
                issue_count += 1"""

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    patches_applied += 1
    print("PATCH 2 applied: MLB not fully operational until mlb_stats_daily is done")
else:
    print("PATCH 2 SKIPPED: MLB block not found (already patched?)")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3a — Startup Pipeline: +1 step for mlb_stats_daily
# ─────────────────────────────────────────────────────────────────────────────
OLD3 = """    _step_total = len(_STATS_SOS_LEAGUES) + 3  # init + stats + each SOS + finalize"""

NEW3 = """    _step_total = len(_STATS_SOS_LEAGUES) + 4  # init + stats + each SOS + finalize + mlb_stats_daily"""

if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)
    patches_applied += 1
    print("PATCH 3a applied: startup step_total +1 for mlb_stats_daily")
else:
    print("PATCH 3a SKIPPED: step_total line not found")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3b — Startup bar hits 100% only after mlb_stats_daily completes
# ─────────────────────────────────────────────────────────────────────────────
OLD3B = """        if proc.returncode == 0:
            log("✅ mlb_stats_daily.py auto-boot complete — DB populated.", "info")
            _startup_task_mark(_task_name, "success", progress_pct=100.0, detail="mlb pre-game stats loaded")
            root.after(0, lambda: m_status_var.set(
                "✅ MLB pre-game stats loaded — double-click any game for full breakdown."))"""

NEW3B = """        if proc.returncode == 0:
            log("✅ mlb_stats_daily.py auto-boot complete — DB populated.", "info")
            _startup_task_mark(_task_name, "success", progress_pct=100.0, detail="mlb pre-game stats loaded")
            root.after(0, lambda: m_status_var.set(
                "✅ MLB pre-game stats loaded — double-click any game for full breakdown."))
            # Advance startup pipeline bar — this was the final step
            try:
                _set_startup_progress_pct(100.0, "daily startup data already complete")
            except Exception:
                pass"""

if OLD3B in src:
    src = src.replace(OLD3B, NEW3B, 1)
    patches_applied += 1
    print("PATCH 3b applied: startup bar hits 100% only after mlb_stats_daily done")
else:
    print("PATCH 3b SKIPPED: mlb success block not found")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 4 — Matchup Load: "fully loaded" → "odds loaded"
# ─────────────────────────────────────────────────────────────────────────────
OLD4 = """    _set_matchup_load_progress(100.0, f"fully loaded - {len(data_df)} game(s) ready")"""

NEW4 = """    _set_matchup_load_progress(100.0, f"odds loaded - {len(data_df)} game(s) ready (double-click for full detail)")"""

if OLD4 in src:
    src = src.replace(OLD4, NEW4, 1)
    patches_applied += 1
    print("PATCH 4 applied: matchup bar says 'odds loaded' not 'fully loaded'")
else:
    print("PATCH 4 SKIPPED: matchup load line not found")

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
    print(f"{patches_applied}/5 patches applied to {TARGET}")

    import py_compile
    try:
        py_compile.compile(str(TARGET), doraise=True)
        print("Syntax check: OK")
    except py_compile.PyCompileError as e:
        print(f"SYNTAX ERROR — restoring backup: {e}")
        shutil.copy2(backup, TARGET)
        raise SystemExit(1)
