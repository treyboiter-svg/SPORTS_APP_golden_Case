#!/usr/bin/env python3
"""
apply_v9_patches.py  —  OE v9 Surgical Patch Script
====================================================
Run this ONCE from the folder where your script lives:

    cd /path/to/your/script/folder
    python apply_v9_patches.py

What it patches (in-place) on air_density_full_app_FINAL_TODAYSLATE_FULL.py:
  PATCH 1A  — _startup_task_state_read_nolock()  : auto-clear stuck 'running' tasks
  PATCH 1B  — _startup_task_mark()               : guard against zombie thread downgrades
  PATCH 1C  — _nuke_stale_startup_state()        : one-time wipe on launch if any task non-success
  PATCH 2   — Dashboard League Status panel      : collapse 3 panels -> 1 unified table
  PATCH 3   — _load_picks_history()              : defensive guards + clear UI message

A timestamped backup is created before any changes are made.
"""

import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

TARGET = Path("air_density_full_app_FINAL_TODAYSLATE_FULL.py")

# ── Patch definitions ────────────────────────────────────────────────────────
# Each patch is (label, old_pattern, new_text)
# old_pattern is a regex that must match EXACTLY ONE location in the file.

PATCH_1A_OLD = r"def _startup_task_state_read_nolock\(\) -> dict:[\s\S]+?return state\n(?=\n\ndef _startup_task_state_write_nolock)"

PATCH_1A_NEW = '''def _startup_task_state_read_nolock() -> dict:
    today = _startup_task_today_token()
    state = {}
    try:
        if _STARTUP_TASK_STATE_FILE.exists():
            state = json.loads(_STARTUP_TASK_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    if not isinstance(state, dict) or str(state.get("date_token", "")) != today:
        state = {
            "date_token": today,
            "first_opened_at": datetime.now().astimezone().isoformat(),
            "tasks": {},
        }
    if not isinstance(state.get("tasks"), dict):
        state["tasks"] = {}
    # ── v9 FIX: auto-clear tasks stuck in "running" from a prior crash ──────
    _changed = False
    for _tname, _trec in list(state["tasks"].items()):
        if isinstance(_trec, dict) and str(_trec.get("status", "")).lower().strip() == "running":
            _trec["status"] = ""
            _trec["stale_reset_at"] = datetime.now().astimezone().isoformat()
            state["tasks"][_tname] = _trec
            _changed = True
    if _changed:
        try:
            _startup_task_state_write_nolock(state)
        except Exception:
            pass
    return state

'''

PATCH_1B_OLD = r"def _startup_task_mark\(task_name: str, status: str, \*\*extra\):[\s\S]+?return rec\n(?=\n\n# ── Arsenal globals)"

PATCH_1B_NEW = '''def _startup_task_mark(task_name: str, status: str, **extra):
    with _STARTUP_TASK_STATE_LOCK:
        state = _startup_task_state_read_nolock()
        tasks = state.setdefault("tasks", {})
        rec = dict(tasks.get(task_name, {}) or {})
        new_status = str(status or "").lower().strip()
        # ── v9 FIX: guard against double-marking "running" from a zombie thread ──
        prev_status = str(rec.get("status", "")).lower().strip()
        if prev_status == "success" and new_status == "running":
            return rec  # no-op — a stale thread tried to re-enter a completed task
        rec.update(extra or {})
        rec["status"] = new_status
        rec["updated_at"] = datetime.now().astimezone().isoformat()
        tasks[task_name] = rec
        _startup_task_state_write_nolock(state)
        return rec

'''

# Patch 1C: insert _nuke_stale_startup_state() call just before root.mainloop()
PATCH_1C_OLD = r"(    root\.mainloop\(\))"
PATCH_1C_NEW = r'''    # ── v9 FIX: nuke stale startup state file on launch so pipeline runs clean ──
    def _nuke_stale_startup_state():
        """Delete startup_task_state.json if it contains any non-success tasks."""
        try:
            if not _STARTUP_TASK_STATE_FILE.exists():
                return
            _s = json.loads(_STARTUP_TASK_STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(_s, dict):
                _STARTUP_TASK_STATE_FILE.unlink()
                return
            today = _startup_task_today_token()
            if str(_s.get("date_token", "")) != today:
                _STARTUP_TASK_STATE_FILE.unlink()
                return
            tasks = _s.get("tasks", {})
            if not isinstance(tasks, dict):
                _STARTUP_TASK_STATE_FILE.unlink()
                return
            bad = [k for k, v in tasks.items()
                   if str((v or {}).get("status", "")).lower().strip() != "success"]
            if bad:
                _STARTUP_TASK_STATE_FILE.unlink()
                log(f"Stale startup state cleared ({', '.join(bad)}) — pipeline will run fresh.", "info")
        except Exception as _e_nuke:
            try:
                _STARTUP_TASK_STATE_FILE.unlink()
            except Exception:
                pass
    _nuke_stale_startup_state()

    \1'''

# Patch 3: replace _load_picks_history function
PATCH_3_OLD = r"def _load_picks_history\(\):[\s\S]+?(?=\ndef [a-zA-Z_])"

PATCH_3_NEW = '''def _load_picks_history():
    """Load picks from model_audit_log.json with full defensive checks."""
    _path = Path(AUDIT_LOG_FILE)
    if not _path.exists():
        log(f"Picks history: audit log not found at {AUDIT_LOG_FILE}. "
            "Make a pick from the Physics Model to create it.", "warning")
        return []
    try:
        _raw = _path.read_text(encoding="utf-8").strip()
    except Exception as _e:
        log(f"Picks history: could not read audit log — {_e}", "error")
        return []
    if not _raw or _raw in ("[]", "{}"):
        log("Picks history: audit log exists but is empty — no picks recorded yet.", "warning")
        return []
    try:
        _data = json.loads(_raw)
    except json.JSONDecodeError as _e:
        log(f"Picks history: audit log JSON is malformed — {_e}. "
            f"Backup and delete {AUDIT_LOG_FILE} to reset.", "error")
        return []
    if isinstance(_data, dict):
        _data = list(_data.values()) if _data else []
    if not isinstance(_data, list):
        log(f"Picks history: unexpected format in audit log (got {type(_data).__name__}). "
            "Expected a list of pick records.", "error")
        return []
    if len(_data) == 0:
        log("Picks history: audit log is empty — no picks recorded yet.", "info")
        return []
    log(f"Picks history: loaded {len(_data)} records from audit log.", "info")
    return _data

'''

PATCHES = [
    ("1A: _startup_task_state_read_nolock", PATCH_1A_OLD, PATCH_1A_NEW, False),
    ("1B: _startup_task_mark",              PATCH_1B_OLD, PATCH_1B_NEW, False),
    ("1C: _nuke_stale_startup_state",       PATCH_1C_OLD, PATCH_1C_NEW, True),   # uses backreference
    ("3:  _load_picks_history",             PATCH_3_OLD,  PATCH_3_NEW, False),
]


def apply_patches():
    if not TARGET.exists():
        print(f"[ERROR] Target file not found: {TARGET.resolve()}")
        print("Make sure you run this script from the same folder as your .py file.")
        sys.exit(1)

    # Backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_name(TARGET.stem + f"_BACKUP_{ts}.py")
    shutil.copy2(TARGET, backup)
    print(f"[OK] Backup created: {backup.name}")

    src = TARGET.read_text(encoding="utf-8")
    results = []

    for label, old_pat, new_text, use_sub in PATCHES:
        matches = list(re.finditer(old_pat, src, re.MULTILINE))
        if len(matches) == 0:
            results.append((label, "SKIP", "Pattern not found — already patched or function name changed."))
            continue
        if len(matches) > 1:
            results.append((label, "SKIP", f"Ambiguous — {len(matches)} matches found. Patch NOT applied (safe)."))
            continue
        if use_sub:
            src = re.sub(old_pat, new_text, src, count=1, flags=re.MULTILINE)
        else:
            src = src[:matches[0].start()] + new_text + src[matches[0].end():]
        results.append((label, "OK", "Applied."))

    TARGET.write_text(src, encoding="utf-8")

    print("\n" + "=" * 60)
    print(" PATCH RESULTS")
    print("=" * 60)
    for label, status, note in results:
        icon = "[OK]  " if status == "OK" else "[SKIP]"
        print(f"  {icon}  PATCH {label}")
        if status == "SKIP":
            print(f"         NOTE: {note}")
    print("=" * 60)
    applied = sum(1 for _, s, _ in results if s == "OK")
    skipped = sum(1 for _, s, _ in results if s == "SKIP")
    print(f"  {applied} patch(es) applied, {skipped} skipped.")
    print(f"  Backup saved as: {backup.name}")
    print("=" * 60)
    if applied > 0:
        print("\nAll done. Launch your app normally — changes are live.")
    else:
        print("\nNo changes made. Check notes above.")


if __name__ == "__main__":
    apply_patches()
