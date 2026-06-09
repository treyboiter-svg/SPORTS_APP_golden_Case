"""Circadian Rhythm Effect integration using real travel/rest data."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

log = logging.getLogger(__name__)

try:
    from travel_rest_scraper import load_travel_rest_for_game
except Exception:
    load_travel_rest_for_game = None


def _norm_team_name(name: str) -> str:
    s = str(name or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fuzzy_team_match(a: str, b: str) -> bool:
    """
    Compatibility helper used by regression checks.
    Returns False on blank input and True for exact normalized match
    or strict token-subset overlap.
    """
    na = _norm_team_name(a)
    nb = _norm_team_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta = set(na.split())
    tb = set(nb.split())
    if not ta or not tb:
        return False
    return ta.issubset(tb) or tb.issubset(ta)


def _to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _severity(rest_days, games_5d, miles_5d):
    r = _to_float(rest_days)
    g = _to_float(games_5d)
    m = _to_float(miles_5d)
    if r is None and g is None and m is None:
        return "N/A", 0.0
    score = 0.0
    if r is not None:
        if r <= 0:
            score += 1.0
        elif r >= 2:
            score -= 0.4
    if g is not None:
        if g >= 4:
            score += 1.0
        elif g <= 2:
            score -= 0.2
    if m is not None:
        if m >= 2500:
            score += 1.0
        elif m >= 1500:
            score += 0.5
    if score >= 1.8:
        return "HIGH", score
    if score >= 0.8:
        return "MODERATE", score
    if score > 0.0:
        return "LOW", score
    return "LOW", 0.0


def get_cre_for_game(away_team=None, home_team=None, game_date=None, sport=None, **kw):
    if not callable(load_travel_rest_for_game):
        return {
            "available": False,
            "reason": "travel_rest_scraper_unavailable",
        }
    try:
        tr = load_travel_rest_for_game(
            away_team=away_team,
            home_team=home_team,
            game_date=game_date,
            sport=sport,
        ) or {}
    except Exception as exc:
        return {
            "available": False,
            "reason": f"travel_rest_error:{exc}",
        }
    if not isinstance(tr, dict) or not tr:
        return {
            "available": False,
            "reason": "travel_rest_empty",
        }
    a_sev, a_score = _severity(tr.get("away_rest_days"), tr.get("away_games_last_5d"), tr.get("away_travel_miles"))
    h_sev, h_score = _severity(tr.get("home_rest_days"), tr.get("home_games_last_5d"), tr.get("home_travel_miles"))
    return {
        "available": True,
        "away_severity": a_sev,
        "home_severity": h_sev,
        "away_score": a_score,
        "home_score": h_score,
        "raw": tr,
    }


def apply_cre_to_model(ou, side, conf, rec, league, rho_pct=None, **kw):
    out = {
        "final_ou_lean": ou,
        "final_side_lean": side,
        "final_confidence": conf,
        "cre_contributed": False,
        "cre_summary": "CRE unavailable",
        "compound_signal": False,
        "cre_weight_applied": 0.0,
        "away_severity": "N/A",
        "home_severity": "N/A",
        "cre_ou_lean": "NEUTRAL",
        "cre_side_lean": "NEUTRAL",
        "notes": [],
    }
    if not isinstance(rec, dict) or not rec.get("available"):
        out["cre_summary"] = str((rec or {}).get("reason") or "CRE unavailable")
        return out

    away_s = _to_float(rec.get("away_score")) or 0.0
    home_s = _to_float(rec.get("home_score")) or 0.0
    delta = away_s - home_s
    out["away_severity"] = str(rec.get("away_severity") or "N/A")
    out["home_severity"] = str(rec.get("home_severity") or "N/A")
    out["cre_summary"] = f"travel_rest_delta={delta:.2f}"

    # Side signal: more fatigued away team tilts toward home.
    if delta >= 0.8:
        out["cre_side_lean"] = "HOME"
        out["final_side_lean"] = "HOME" if str(side).upper() == "NEUTRAL" else side
        out["cre_contributed"] = True
        out["cre_weight_applied"] = min(0.20, 0.08 + 0.04 * delta)
    elif delta <= -0.8:
        out["cre_side_lean"] = "AWAY"
        out["final_side_lean"] = "AWAY" if str(side).upper() == "NEUTRAL" else side
        out["cre_contributed"] = True
        out["cre_weight_applied"] = min(0.20, 0.08 + 0.04 * abs(delta))

    # OU signal: heavy fatigue on both sides tends to suppress pace/efficiency.
    if (away_s + home_s) >= 2.5:
        out["cre_ou_lean"] = "UNDER"
        if str(ou).upper() == "NEUTRAL":
            out["final_ou_lean"] = "UNDER"
        out["cre_contributed"] = True

    if out["cre_contributed"]:
        c = _to_float(conf)
        if c is not None:
            out["final_confidence"] = min(10.0, max(0.0, c + 0.3))
    return out


def cre_display_block(*a, **kw):
    return ""
