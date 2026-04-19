# patch_02_dashboard_collapse.py
# ============================================================
# Patch 2 — Dashboard Panel Collapse
#
# Adds a collapse/expand toggle button to the Dashboard tab so
# the hero band + action row can be hidden to reclaim vertical
# space for the league status panels below.
#
# HOW TO APPLY:
#   This patch is a self-contained surgical replacement.
#   In air_density_full_app_FINAL_TODAYSLATE_FULL.py, find the
#   block that begins with:
#
#       dashboard_hero = ttk.Frame(dashboard_body, style="Hero.TFrame", padding=12)
#
#   Replace EVERYTHING from that line through:
#
#       _dashboard_top_var = tk.StringVar(value="Top opportunities: waiting for slate load.")
#       ttk.Label(
#           dashboard_action_row,
#           textvariable=_dashboard_top_var,
#           style="SubtleCard.TLabel",
#       ).pack(side=tk.LEFT, padx=(14, 0))
#
#   ...with the block below.
# ============================================================

# ── Collapse state ───────────────────────────────────────────
_dashboard_panels_collapsed = False

def _toggle_dashboard_panels():
    global _dashboard_panels_collapsed
    _dashboard_panels_collapsed = not _dashboard_panels_collapsed
    if _dashboard_panels_collapsed:
        dashboard_hero.pack_forget()
        dashboard_action_row_inner.pack_forget()
        _dashboard_collapse_btn.config(text="\u25bc  Show Dashboard")
    else:
        # Re-pack in original order: hero first, then action row, then toggle bar
        dashboard_hero.pack(fill=tk.X, padx=6, pady=(6, 6), before=dashboard_collapse_bar)
        dashboard_action_row_inner.pack(fill=tk.X, padx=6, pady=(0, 4), before=dashboard_collapse_bar)
        _dashboard_collapse_btn.config(text="\u25b2  Hide Dashboard")

# ── Hero band ────────────────────────────────────────────────
dashboard_hero = ttk.Frame(dashboard_body, style="Hero.TFrame", padding=12)
dashboard_hero.pack(fill=tk.X, padx=6, pady=(6, 6))
dashboard_hero.grid_columnconfigure(0, weight=1)
dashboard_hero.grid_columnconfigure(1, weight=1)
dashboard_hero_left = ttk.Frame(dashboard_hero, style="Hero.TFrame")
dashboard_hero_left.grid(row=0, column=0, sticky="w")
ttk.Label(
    dashboard_hero_left,
    text="Command Dashboard",
    style="HeroTitle.TLabel",
).pack(anchor="w")
ttk.Label(
    dashboard_hero_left,
    text="Decision-first visibility with disciplined execution.",
    style="HeroSubtitle.TLabel",
).pack(anchor="w", pady=(2, 0))

dashboard_hero_chips = ttk.Frame(dashboard_hero, style="Hero.TFrame")
dashboard_hero_chips.grid(row=0, column=1, sticky="e")
_dashboard_status_chip = ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_status_chip_var, style="HeroChipWarn.TLabel"
)
_dashboard_status_chip.grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="e")
_dashboard_operational_chip = ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_operational_chip_var, style="HeroChip.TLabel"
)
_dashboard_operational_chip.grid(row=0, column=1, padx=(0, 6), pady=(0, 6), sticky="e")
_dashboard_issues_chip = ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_issues_chip_var, style="HeroChip.TLabel"
)
_dashboard_issues_chip.grid(row=0, column=2, pady=(0, 6), sticky="e")
ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_slate_chip_var, style="HeroChip.TLabel"
).grid(row=1, column=0, padx=(0, 6), sticky="e")
ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_startup_chip_var, style="HeroChip.TLabel"
).grid(row=1, column=1, padx=(0, 6), sticky="e")
ttk.Label(
    dashboard_hero_chips, textvariable=_dashboard_load_chip_var, style="HeroChip.TLabel"
).grid(row=1, column=2, sticky="e")
if _brand_assets.get("icon") is not None:
    ttk.Label(
        dashboard_hero_chips,
        image=_brand_assets["icon"],
        style="BrandHero.TLabel",
    ).grid(row=0, column=3, rowspan=2, padx=(12, 0), sticky="e")

# ── Action row (inner frame so we can pack_forget it independently) ──
dashboard_action_row = ttk.Frame(dashboard_body, style="Card.TFrame")
dashboard_action_row.pack(fill=tk.X, padx=6, pady=(0, 0))
dashboard_action_row_inner = ttk.Frame(dashboard_action_row, style="Card.TFrame")
dashboard_action_row_inner.pack(fill=tk.X, pady=(0, 4))
ttk.Button(
    dashboard_action_row_inner,
    text="Open Slate",
    style="Accent.TButton",
    command=lambda: main_tabs.select(games_frame),
).pack(side=tk.LEFT, padx=(0, 6))
ttk.Button(
    dashboard_action_row_inner,
    text="Refresh Pulse",
    command=lambda: _refresh_pipeline_pulse(log_summary=True),
).pack(side=tk.LEFT, padx=(0, 6))
ttk.Button(
    dashboard_action_row_inner,
    text="Open Reports",
    command=lambda: main_tabs.select(reports_frame) if "reports_frame" in globals() else None,
).pack(side=tk.LEFT)

_dashboard_top_var = tk.StringVar(value="Top opportunities: waiting for slate load.")
ttk.Label(
    dashboard_action_row_inner,
    textvariable=_dashboard_top_var,
    style="SubtleCard.TLabel",
).pack(side=tk.LEFT, padx=(14, 0))

# ── Collapse toggle bar ──────────────────────────────────────
dashboard_collapse_bar = ttk.Frame(dashboard_body, style="Card.TFrame")
dashboard_collapse_bar.pack(fill=tk.X, padx=6, pady=(0, 4))
_dashboard_collapse_btn = ttk.Button(
    dashboard_collapse_bar,
    text="\u25b2  Hide Dashboard",
    command=_toggle_dashboard_panels,
)
_dashboard_collapse_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=2)
