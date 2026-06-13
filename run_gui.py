#!/usr/bin/env python3
"""
Walkability Analyzer — Tkinter GUI
====================================
Launch with:
    python run_gui.py
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from copy import deepcopy
from pathlib import Path
from tkinter import (
    BooleanVar,
    DoubleVar,
    StringVar,
    Text,
    Tk,
    filedialog,
    messagebox,
    scrolledtext,
)
import tkinter as tk
import tkinter.ttk as ttk

# ---------------------------------------------------------------------------
# Bootstrap: ensure the package root is importable
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from walkability_analyzer.scoring.score_config import ScoringProfile

# ---------------------------------------------------------------------------
# Theme constants
# ---------------------------------------------------------------------------
BG       = "#f5f5f5"
ACCENT   = "#2563eb"   # blue
SUCCESS  = "#16a34a"
WARNING  = "#d97706"
DANGER   = "#dc2626"
BTN_RUN  = "#2563eb"
BTN_FG   = "#ffffff"
FONT_H1  = ("Segoe UI", 12, "bold")
FONT_H2  = ("Segoe UI", 10, "bold")
FONT_BODY= ("Segoe UI", 9)
FONT_MONO= ("Consolas", 9)
PAD      = 8

PRESET_DESCRIPTIONS = {
    "motion_only":             "IMU + GPS only  ← recommended when no extras",
    "motion_plus_physiology":  "IMU + GPS + heart-watch",
    "motion_plus_environment": "IMU + GPS + video / environment",
    "full_multimodal":         "All three modules (IMU + physiology + video)",
    "custom":                  "Manual configuration",
}

MODULE_LABELS = {
    "motion":      "Motion (MSI)",
    "environment": "Environment (EEI)",
    "physiology":  "Physiology (PCI)",
}

METRIC_LABELS = {
    # motion
    "speed":           "Speed",
    "cadence":         "Cadence",
    "regularity":      "Regularity",
    "stop_ratio":      "Stop Ratio",
    "abnormal_motion": "Abnormal Motion",
    # environment
    "obstacle_load":       "Obstacle Load",
    "traffic_exposure":    "Traffic Exposure",
    "crowding":            "Crowding",
    "crossing_complexity": "Crossing Complexity",
    "shade":               "Shade",
    # physiology
    "heart_rate":       "Heart Rate",
    "rmssd":            "RMSSD",
    "heart_rate_slope": "Heart Rate Slope",
}

# ---------------------------------------------------------------------------
# Logging bridge: redirect logging records to a Queue for the GUI
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class WalkabilityGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Walkability Analyzer")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(860, 680)

        # -- State --------------------------------------------------------
        self._profile: ScoringProfile = ScoringProfile.get_preset("motion_only")
        self._log_queue: queue.Queue = queue.Queue()
        self._analysis_thread: threading.Thread | None = None
        self._report_paths: list[Path] = []

        # -- String / bool vars -------------------------------------------
        self._data_root        = StringVar(value=str(_THIS_DIR / "test_records"))
        self._data_files_info  = StringVar(value="")   # shows "N files selected"
        self._output_root      = StringVar(value=str(_THIS_DIR / "output"))
        self._physio_root      = StringVar(value="")
        self._physio_file_info = StringVar(value="")   # shows selected file name
        self._route            = StringVar(value="")
        self._preset           = StringVar(value="motion_only")
        self._dry_run     = BooleanVar(value=False)
        self._open_report = BooleanVar(value=True)
        self._verbose     = BooleanVar(value=False)
        self._process_video = BooleanVar(value=False)
        self._use_sam2    = BooleanVar(value=False)
        self._save_config = StringVar(value="")

        # Windowing vars
        self._window_len     = DoubleVar(value=5.0)
        self._window_overlap = DoubleVar(value=0.5)
        self._hotspot_thr    = DoubleVar(value=35.0)
        self._auto_renorm    = BooleanVar(value=True)

        # Scoring vars per-module / per-metric built dynamically
        self._mod_enabled : dict[str, BooleanVar] = {}
        self._mod_weight  : dict[str, StringVar]  = {}
        self._met_enabled : dict[str, dict[str, BooleanVar]] = {}
        self._met_weight  : dict[str, dict[str, StringVar]]  = {}

        # -- Build UI -----------------------------------------------------
        self._build_ui()
        self._load_profile_to_vars(self._profile)

        # -- Start log pump -----------------------------------------------
        self._pump_log()

    # =====================================================================
    # UI construction
    # =====================================================================

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",        background=BG)
        style.configure("TNotebook.Tab",    font=FONT_H2, padding=[10, 4])
        style.configure("TFrame",           background=BG)
        style.configure("TLabel",           background=BG, font=FONT_BODY)
        style.configure("TCheckbutton",     background=BG, font=FONT_BODY)
        style.configure("TEntry",           font=FONT_BODY)
        style.configure("Accent.TButton",
                        font=FONT_H2, foreground=BTN_FG, background=ACCENT)
        style.map("Accent.TButton",
                  background=[("active", "#1d4ed8"), ("disabled", "#93c5fd")])
        style.configure("TLabelframe",       background=BG)
        style.configure("TLabelframe.Label", background=BG, font=FONT_H2)

        # ---- Header -----------------------------------------------------
        hdr = tk.Frame(self, bg=ACCENT, height=48)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text=" Walkability Analyzer",
            bg=ACCENT, fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=16, pady=8)

        # ---- Notebook ---------------------------------------------------
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))

        self._tab_setup    = ttk.Frame(self._nb)
        self._tab_scoring  = ttk.Frame(self._nb)
        self._tab_advanced = ttk.Frame(self._nb)
        self._tab_log      = ttk.Frame(self._nb)

        self._nb.add(self._tab_setup,    text="  Setup  ")
        self._nb.add(self._tab_scoring,  text="  Scoring  ")
        self._nb.add(self._tab_advanced, text="  Advanced  ")
        self._nb.add(self._tab_log,      text="  Log  ")

        self._build_setup_tab()
        self._build_scoring_tab()
        self._build_advanced_tab()
        self._build_log_tab()

        # ---- Bottom action bar ------------------------------------------
        bar = tk.Frame(self, bg="#e2e8f0", pady=8)
        bar.pack(fill="x", padx=PAD, pady=PAD)

        self._btn_run = ttk.Button(
            bar, text="▶  Run Analysis", style="Accent.TButton",
            command=self._on_run,
        )
        self._btn_run.pack(side="left", padx=(0, 6))

        ttk.Button(bar, text="Dry Run", command=self._on_dry_run).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Save Config…", command=self._on_save_config).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Load Config…", command=self._on_load_config).pack(side="left", padx=(0, 6))

        self._btn_report = ttk.Button(
            bar, text="Open Report", state="disabled", command=self._on_open_report,
        )
        self._btn_report.pack(side="right", padx=(6, 0))

        # Status bar
        self._status_var = StringVar(value="Ready.")
        self._status_lbl = tk.Label(
            self, textvariable=self._status_var,
            bg="#e2e8f0", font=FONT_BODY, anchor="w", padx=8, pady=3,
        )
        self._status_lbl.pack(fill="x", side="bottom")

    # ------------------------------------------------------------------
    # Setup tab
    # ------------------------------------------------------------------

    def _build_setup_tab(self) -> None:
        f = self._tab_setup
        f.columnconfigure(1, weight=1)

        row = 0

        def _lbl(text, r, c=0, **kw):
            tk.Label(f, text=text, bg=BG, font=FONT_BODY, **kw).grid(
                row=r, column=c, sticky="w", padx=(PAD*2 if c == 0 else 4), pady=3,
            )

        tk.Label(f, text="Data Locations", bg=BG, font=FONT_H1).grid(
            row=row, column=0, columnspan=4, sticky="w", padx=PAD*2, pady=(PAD*2, 4),
        )
        row += 1

        # ---- Data root row (folder OR specific files) ------------------
        _lbl("Sensor data (CSV / MAT):", row)
        ttk.Entry(f, textvariable=self._data_root, font=FONT_BODY).grid(
            row=row, column=1, sticky="ew", padx=4, pady=3,
        )
        ttk.Button(
            f, text="Browse Folder…",
            command=lambda: self._browse_dir(self._data_root),
        ).grid(row=row, column=2, padx=(0, 4), pady=3)
        ttk.Button(
            f, text="Browse Files…",
            command=self._browse_data_files,
        ).grid(row=row, column=3, padx=(0, PAD*2), pady=3)
        row += 1
        # Info label that shows how many files were picked
        tk.Label(
            f, textvariable=self._data_files_info,
            bg=BG, font=FONT_BODY, fg="#2563eb",
        ).grid(row=row, column=1, columnspan=3, sticky="w", padx=4)
        row += 1

        # ---- Output folder row -----------------------------------------
        _lbl("Output folder:", row)
        ttk.Entry(f, textvariable=self._output_root, font=FONT_BODY).grid(
            row=row, column=1, sticky="ew", padx=4, pady=3,
        )
        ttk.Button(
            f, text="Browse Folder…",
            command=lambda: self._browse_dir(self._output_root),
        ).grid(row=row, column=2, columnspan=2, sticky="w", padx=(0, PAD*2), pady=3)
        row += 1

        # ---- Physiology row (folder OR single file) --------------------
        _lbl("Physiology (optional):", row)
        ttk.Entry(f, textvariable=self._physio_root, font=FONT_BODY).grid(
            row=row, column=1, sticky="ew", padx=4, pady=3,
        )
        ttk.Button(
            f, text="Browse Folder…",
            command=lambda: self._browse_dir(self._physio_root),
        ).grid(row=row, column=2, padx=(0, 4), pady=3)
        ttk.Button(
            f, text="Browse File…",
            command=self._browse_physio_file,
        ).grid(row=row, column=3, padx=(0, PAD*2), pady=3)
        row += 1
        tk.Label(
            f, textvariable=self._physio_file_info,
            bg=BG, font=FONT_BODY, fg="#2563eb",
        ).grid(row=row, column=1, columnspan=3, sticky="w", padx=4)
        row += 1

        # ---- Route filter row ------------------------------------------
        _lbl("Route subfolder (blank = all):", row)
        ttk.Entry(f, textvariable=self._route, font=FONT_BODY).grid(
            row=row, column=1, sticky="ew", padx=4, pady=3,
        )
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=PAD*2, pady=PAD,
        )
        row += 1

        tk.Label(f, text="Scoring Preset", bg=BG, font=FONT_H1).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=(4, 4),
        )
        row += 1

        preset_frame = tk.Frame(f, bg=BG)
        preset_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=PAD*2, pady=4)
        for name, desc in PRESET_DESCRIPTIONS.items():
            rb = ttk.Radiobutton(
                preset_frame, text=f"{name}  —  {desc}",
                variable=self._preset, value=name,
                command=self._on_preset_changed,
            )
            rb.pack(anchor="w", pady=2)
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=PAD*2, pady=PAD,
        )
        row += 1

        # Options row
        opts = tk.Frame(f, bg=BG)
        opts.grid(row=row, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=4)
        ttk.Checkbutton(opts, text="Open report after analysis", variable=self._open_report).pack(side="left", padx=8)
        ttk.Checkbutton(opts, text="Verbose logging",            variable=self._verbose).pack(side="left", padx=8)
        row += 1

        # Video processing options row
        vid_opts = tk.Frame(f, bg=BG)
        vid_opts.grid(row=row, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=(0, 4))
        ttk.Checkbutton(
            vid_opts, text="Process video (GoPro)",
            variable=self._process_video,
            command=self._on_video_toggle,
        ).pack(side="left", padx=8)
        self._chk_sam2 = ttk.Checkbutton(
            vid_opts, text="Use SAM2 (better accuracy, slower)",
            variable=self._use_sam2,
            state="disabled",
        )
        self._chk_sam2.pack(side="left", padx=8)

        # SAM2 availability label
        _sam2_ok = self._check_sam2_available()
        _sam2_color = SUCCESS if _sam2_ok else WARNING
        _sam2_text  = "SAM2: installed ✓" if _sam2_ok else "SAM2: not installed (pip install torch sam2)"
        self._sam2_status_lbl = tk.Label(
            f, text=_sam2_text, bg=BG, font=FONT_BODY, fg=_sam2_color,
        )
        self._sam2_status_lbl.grid(row=row + 1, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=(0, 4))

    # ------------------------------------------------------------------
    # Scoring tab
    # ------------------------------------------------------------------

    def _build_scoring_tab(self) -> None:
        outer = self._tab_scoring

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb   = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._scoring_frame = tk.Frame(canvas, bg=BG)
        canvas_window = canvas.create_window((0, 0), window=self._scoring_frame, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        self._scoring_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._build_scoring_content()

    def _build_scoring_content(self) -> None:
        """Build (or rebuild) module/metric widgets from current profile."""
        f = self._scoring_frame
        for w in f.winfo_children():
            w.destroy()

        self._mod_enabled.clear()
        self._mod_weight.clear()
        self._met_enabled.clear()
        self._met_weight.clear()

        tk.Label(f, text="Module & Metric Configuration", bg=BG, font=FONT_H1).pack(
            anchor="w", padx=PAD*2, pady=(PAD*2, 4),
        )
        tk.Label(
            f,
            text="Enable/disable modules and metrics, and set their relative weights.\n"
                 "Weights are automatically renormalized unless you disable that option.",
            bg=BG, font=FONT_BODY, fg="#64748b", justify="left",
        ).pack(anchor="w", padx=PAD*2, pady=(0, PAD))

        for mod_name, mod_cfg in self._profile.modules.items():
            self._mod_enabled[mod_name] = BooleanVar(value=mod_cfg.enabled)
            self._mod_weight[mod_name]  = StringVar(value=f"{mod_cfg.weight:.3f}")
            self._met_enabled[mod_name] = {}
            self._met_weight[mod_name]  = {}

            lf = ttk.LabelFrame(
                f,
                text=MODULE_LABELS.get(mod_name, mod_name.capitalize()),
                padding=8,
            )
            lf.pack(fill="x", padx=PAD*2, pady=4)

            # Module header row
            hdr = tk.Frame(lf, bg=BG)
            hdr.pack(fill="x")
            ttk.Checkbutton(
                hdr, text="Enabled", variable=self._mod_enabled[mod_name],
            ).pack(side="left")
            tk.Label(hdr, text="Module weight:", bg=BG, font=FONT_BODY).pack(side="left", padx=(PAD*3, 4))
            ttk.Entry(hdr, textvariable=self._mod_weight[mod_name], width=7, font=FONT_BODY).pack(side="left")
            tk.Label(hdr, text="(relative; auto-renorm applied)", bg=BG, font=FONT_BODY, fg="#64748b").pack(side="left", padx=6)

            ttk.Separator(lf, orient="horizontal").pack(fill="x", pady=6)

            # Metrics grid
            mgrid = tk.Frame(lf, bg=BG)
            mgrid.pack(fill="x")
            mgrid.columnconfigure(2, weight=1)

            tk.Label(mgrid, text="Metric",  bg=BG, font=FONT_H2, width=22, anchor="w").grid(row=0, column=1, sticky="w")
            tk.Label(mgrid, text="Weight",  bg=BG, font=FONT_H2, width=8,  anchor="w").grid(row=0, column=2, sticky="w", padx=4)

            for r, (met_name, met_cfg) in enumerate(mod_cfg.metrics.items(), start=1):
                en_var = BooleanVar(value=met_cfg.enabled)
                wt_var = StringVar(value=f"{met_cfg.weight:.3f}")
                self._met_enabled[mod_name][met_name] = en_var
                self._met_weight[mod_name][met_name]  = wt_var

                ttk.Checkbutton(mgrid, variable=en_var).grid(row=r, column=0, padx=(0, 4))
                tk.Label(
                    mgrid, text=METRIC_LABELS.get(met_name, met_name),
                    bg=BG, font=FONT_BODY, anchor="w",
                ).grid(row=r, column=1, sticky="w", pady=2)
                ttk.Entry(mgrid, textvariable=wt_var, width=7, font=FONT_BODY).grid(
                    row=r, column=2, sticky="w", padx=4,
                )

    # ------------------------------------------------------------------
    # Advanced tab
    # ------------------------------------------------------------------

    def _build_advanced_tab(self) -> None:
        f = self._tab_advanced
        f.columnconfigure(1, weight=1)
        row = 0

        def _row(label, var, r, tooltip=""):
            tk.Label(f, text=label, bg=BG, font=FONT_BODY).grid(
                row=r, column=0, sticky="w", padx=(PAD*2, 8), pady=4,
            )
            ttk.Entry(f, textvariable=var, width=10, font=FONT_BODY).grid(
                row=r, column=1, sticky="w", padx=4, pady=4,
            )
            if tooltip:
                tk.Label(f, text=tooltip, bg=BG, font=FONT_BODY, fg="#64748b").grid(
                    row=r, column=2, sticky="w", padx=8,
                )

        tk.Label(f, text="Windowing & Aggregation", bg=BG, font=FONT_H1).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=(PAD*2, PAD),
        )
        row += 1

        _row("Window length (sec):", self._window_len, row, "Scoring window size. Default: 5.0")
        row += 1
        _row("Window overlap (0–1):", self._window_overlap, row, "Fraction of overlap between windows. Default: 0.5")
        row += 1
        _row("Hotspot threshold (pts):", self._hotspot_thr, row, "Windows scoring below this are flagged as hotspots. Default: 35")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=PAD*2, pady=PAD,
        )
        row += 1

        tk.Label(f, text="Weight Behaviour", bg=BG, font=FONT_H1).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=(4, PAD),
        )
        row += 1

        ttk.Checkbutton(
            f, text="Auto-renormalize weights (recommended)",
            variable=self._auto_renorm,
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=PAD*2, pady=4)
        row += 1

    # ------------------------------------------------------------------
    # Log tab
    # ------------------------------------------------------------------

    def _build_log_tab(self) -> None:
        f = self._tab_log
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        self._log_text = scrolledtext.ScrolledText(
            f, font=FONT_MONO, bg="#1e293b", fg="#94a3b8",
            insertbackground="white", state="disabled",
            wrap="none", relief="flat",
        )
        self._log_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self._log_text.tag_config("INFO",    foreground="#94a3b8")
        self._log_text.tag_config("DEBUG",   foreground="#475569")
        self._log_text.tag_config("WARNING", foreground="#fbbf24")
        self._log_text.tag_config("ERROR",   foreground="#f87171")
        self._log_text.tag_config("PLAIN",   foreground="#e2e8f0")

        btn_bar = tk.Frame(f, bg=BG)
        btn_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        ttk.Button(btn_bar, text="Clear log", command=self._clear_log).pack(side="right")

    # =====================================================================
    # Profile ↔ Vars sync
    # =====================================================================

    def _load_profile_to_vars(self, profile: ScoringProfile) -> None:
        """Push a ScoringProfile into all tkinter vars."""
        self._window_len.set(profile.window_length_sec)
        self._window_overlap.set(profile.window_overlap)
        self._hotspot_thr.set(profile.hotspot_threshold)
        self._auto_renorm.set(profile.auto_renormalize_modules)

        # Rebuild scoring widgets to match potentially new module/metric structure
        self._profile = profile
        self._build_scoring_content()

    def _vars_to_profile(self) -> ScoringProfile:
        """Read all UI vars back into a ScoringProfile copy."""
        from copy import deepcopy
        p = deepcopy(self._profile)

        p.window_length_sec      = self._window_len.get()
        p.window_overlap         = self._window_overlap.get()
        p.hotspot_threshold      = self._hotspot_thr.get()
        p.auto_renormalize_modules = self._auto_renorm.get()

        for mod_name, mod_cfg in p.modules.items():
            if mod_name in self._mod_enabled:
                mod_cfg.enabled = self._mod_enabled[mod_name].get()
            if mod_name in self._mod_weight:
                try:
                    mod_cfg.weight = float(self._mod_weight[mod_name].get())
                except ValueError:
                    pass
            for met_name, met_cfg in mod_cfg.metrics.items():
                if met_name in self._met_enabled.get(mod_name, {}):
                    met_cfg.enabled = self._met_enabled[mod_name][met_name].get()
                if met_name in self._met_weight.get(mod_name, {}):
                    try:
                        met_cfg.weight = float(self._met_weight[mod_name][met_name].get())
                    except ValueError:
                        pass
        return p

    # =====================================================================
    # Event handlers
    # =====================================================================

    def _check_sam2_available(self) -> bool:
        """Return True if SAM2 is importable and the checkpoint exists."""
        try:
            from walkability_analyzer.video_processing.sam2_detector import (
                SAM2_AVAILABLE, _DEFAULT_CKPT,
            )
            return SAM2_AVAILABLE and _DEFAULT_CKPT.exists()
        except Exception:
            return False

    def _on_video_toggle(self) -> None:
        """Enable/disable the SAM2 checkbox based on the process-video toggle."""
        if self._process_video.get():
            self._chk_sam2.configure(state="normal")
            # Auto-check SAM2 if it's available
            if self._check_sam2_available():
                self._use_sam2.set(True)
        else:
            self._use_sam2.set(False)
            self._chk_sam2.configure(state="disabled")

    def _browse_dir(self, var: StringVar) -> None:
        initial = var.get() if Path(var.get()).is_dir() else str(_THIS_DIR)
        d = filedialog.askdirectory(initialdir=initial)
        if d:
            var.set(d)

    def _browse_data_files(self) -> None:
        """Let user pick one or more CSV/MAT sensor files.

        Auto-fills data_root (parent's parent) and route (parent folder name)
        so the existing engine path works without modification.
        """
        initial = self._data_root.get()
        initial_dir = initial if Path(initial).is_dir() else str(_THIS_DIR)
        files = filedialog.askopenfilenames(
            initialdir=initial_dir,
            title="Select sensor CSV / MAT files",
            filetypes=[
                ("Sensor files", "*.csv *.mat"),
                ("CSV files", "*.csv"),
                ("MAT files", "*.mat"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return

        paths = [Path(f) for f in files]
        parents = {p.parent for p in paths}

        if len(parents) > 1:
            messagebox.showwarning(
                "Multiple folders",
                "All selected files must be in the same folder.\n"
                "Please select files from a single route folder.",
            )
            return

        route_folder = next(iter(parents))          # e.g. …/BG_20-10-25/Route1
        data_root    = route_folder.parent           # e.g. …/BG_20-10-25

        self._data_root.set(str(data_root))
        self._route.set(route_folder.name)
        self._data_files_info.set(
            f"{len(paths)} file(s) selected from {route_folder.name}/"
        )
        self._set_status(
            f"Data: {len(paths)} file(s) in {route_folder.name}/", color=ACCENT,
        )

    def _browse_physio_file(self) -> None:
        """Let user pick a single physiology file (CSV or JSON).

        Auto-fills physio_root with the file's parent folder.
        """
        initial = self._physio_root.get()
        initial_dir = initial if Path(initial).is_dir() else str(_THIS_DIR)
        fp = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Select physiology file",
            filetypes=[
                ("Physiology files", "*.csv *.json"),
                ("CSV files", "*.csv"),
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not fp:
            return

        p = Path(fp)
        self._physio_root.set(str(p.parent))
        self._physio_file_info.set(f"File: {p.name}")
        self._set_status(f"Physiology: {p.name}", color=ACCENT)

    def _browse_file(self, var: StringVar) -> None:
        initial_dir = str(_THIS_DIR)
        fp = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if fp:
            var.set(fp)

    def _on_preset_changed(self) -> None:
        name = self._preset.get()
        try:
            p = ScoringProfile.get_preset(name)
            self._load_profile_to_vars(p)
            self._set_status(f"Preset loaded: {name}", color="#16a34a")
        except Exception as exc:
            messagebox.showerror("Preset error", str(exc))

    def _on_save_config(self) -> None:
        p = self._vars_to_profile()
        fp = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON configs", "*.json")],
            initialdir=str(_THIS_DIR / "configs"),
        )
        if fp:
            p.save_json(Path(fp))
            self._set_status(f"Config saved: {fp}", color=SUCCESS)

    def _on_load_config(self) -> None:
        fp = filedialog.askopenfilename(
            filetypes=[("JSON configs", "*.json")],
            initialdir=str(_THIS_DIR / "configs"),
        )
        if fp:
            try:
                p = ScoringProfile.load_json(Path(fp))
                self._load_profile_to_vars(p)
                self._set_status(f"Config loaded: {fp}", color=SUCCESS)
            except Exception as exc:
                messagebox.showerror("Load error", str(exc))

    def _on_dry_run(self) -> None:
        self._run(dry_run=True)

    def _on_run(self) -> None:
        self._run(dry_run=False)

    def _run(self, dry_run: bool) -> None:
        if self._analysis_thread and self._analysis_thread.is_alive():
            messagebox.showwarning("Already running", "An analysis is still in progress.")
            return

        data_root = Path(self._data_root.get().strip())
        if not data_root.exists():
            messagebox.showerror("Invalid path", f"Data root not found:\n{data_root}")
            return

        profile = self._vars_to_profile()

        self._btn_run.configure(state="disabled")
        self._btn_report.configure(state="disabled")
        self._report_paths.clear()
        self._nb.select(self._tab_log)
        self._clear_log()
        self._set_status("Running…", color=WARNING)

        self._analysis_thread = threading.Thread(
            target=self._analysis_worker,
            args=(data_root, profile, dry_run),
            daemon=True,
        )
        self._analysis_thread.start()

    def _analysis_worker(
        self,
        data_root: Path,
        profile: ScoringProfile,
        dry_run: bool,
    ) -> None:
        """Background thread: runs the analysis and pushes log via queue."""

        # Set up logging to queue
        log_queue = self._log_queue
        handler = _QueueHandler(log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s", "%H:%M:%S"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        level = logging.DEBUG if self._verbose.get() else logging.INFO
        root_logger.setLevel(level)

        try:
            output_root = Path(self._output_root.get().strip())
            physio_str  = self._physio_root.get().strip()
            physio_root = Path(physio_str) if physio_str else None
            route       = self._route.get().strip() or None

            log_queue.put(("__PLAIN__", f"Data root   : {data_root}"))
            log_queue.put(("__PLAIN__", f"Output root : {output_root}"))
            log_queue.put(("__PLAIN__", f"Route       : {route or '(all)'}"))
            log_queue.put(("__PLAIN__", f"Preset      : {self._preset.get()}"))
            log_queue.put(("__PLAIN__", "Profile summary:"))
            for line in profile.summary_lines():
                log_queue.put(("__PLAIN__", line))
            log_queue.put(("__PLAIN__", ""))

            # ---- Score calculation description -------------------------
            log_queue.put(("__PLAIN__", "─" * 60))
            log_queue.put(("__PLAIN__", "SCORE CALCULATION DESCRIPTION"))
            log_queue.put(("__PLAIN__", "─" * 60))
            log_queue.put(("__PLAIN__", ""))
            log_queue.put(("__PLAIN__", "  The recording is split into sliding windows of"))
            log_queue.put(("__PLAIN__", f"  {profile.window_length_sec:.1f}s each, with {int(profile.window_overlap*100)}% overlap between consecutive"))
            log_queue.put(("__PLAIN__", "  windows. Each window receives an OWI score [0–100]."))
            log_queue.put(("__PLAIN__", ""))

            # Per active module describe its metrics
            mod_wts = profile.resolved_module_weights()
            active_mods = [n for n, m in profile.modules.items() if m.enabled]

            for mod_name in active_mods:
                mod = profile.modules[mod_name]
                mw  = mod_wts.get(mod_name, 0.0)
                rw  = mod.resolved_metric_weights()

                if mod_name == "motion":
                    log_queue.put(("__PLAIN__", f"  [MSI — Motion Stability Index]  module weight = {mw:.0%}"))
                    log_queue.put(("__PLAIN__", "  Per-window sub-scores (all in [0,1]):"))
                    for met, w in rw.items():
                        if met == "speed":
                            log_queue.put(("__PLAIN__", f"    speed           (w={w:.3f})  exp(-|v_window - v_baseline| / σ_speed)"))
                        elif met == "cadence":
                            log_queue.put(("__PLAIN__", f"    cadence         (w={w:.3f})  exp(-|cad_window - cad_baseline| / σ_cadence)"))
                        elif met == "regularity":
                            log_queue.put(("__PLAIN__", f"    regularity      (w={w:.3f})  1 - min(CV_step_intervals / CV_max, 1)"))
                        elif met == "stop_ratio":
                            log_queue.put(("__PLAIN__", f"    stop_ratio      (w={w:.3f})  1 - fraction_of_samples_below_stop_speed"))
                        elif met == "abnormal_motion":
                            log_queue.put(("__PLAIN__", f"    abnormal_motion (w={w:.3f})  1 - min(fraction_high_jerk / abnormal_max, 1)"))
                    log_queue.put(("__PLAIN__", "  MSI_window = Σ(weight_i × sub_score_i) / Σ(weight_i)"))

                elif mod_name == "environment":
                    log_queue.put(("__PLAIN__", f"  [EEI — Environmental Exposure Index]  module weight = {mw:.0%}"))
                    log_queue.put(("__PLAIN__", "  Per-window sub-scores (all in [0,1]):"))
                    for met, w in rw.items():
                        if met == "shade":
                            log_queue.put(("__PLAIN__", f"    {met:<22s}(w={w:.3f})  higher is better  (normalize to [0,1])"))
                        else:
                            log_queue.put(("__PLAIN__", f"    {met:<22s}(w={w:.3f})  lower is better   (1 - normalize to [0,1])"))
                    log_queue.put(("__PLAIN__", "  EEI_window = Σ(weight_i × sub_score_i) / Σ(weight_i)"))

                elif mod_name == "physiology":
                    log_queue.put(("__PLAIN__", f"  [PCI — Physiological Comfort Index]  module weight = {mw:.0%}"))
                    log_queue.put(("__PLAIN__", "  Per-window sub-scores (all in [0,1]):"))
                    for met, w in rw.items():
                        if met == "heart_rate":
                            log_queue.put(("__PLAIN__", f"    heart_rate      (w={w:.3f})  1 - clip((HR_window - HR_baseline) / HR_std / 3, 0, 1)"))
                        elif met == "rmssd":
                            log_queue.put(("__PLAIN__", f"    rmssd           (w={w:.3f})  1 - clip((RMSSD_baseline - RMSSD_window) / RMSSD_std / 3, 0, 1)"))
                        elif met == "heart_rate_slope":
                            log_queue.put(("__PLAIN__", f"    heart_rate_slope(w={w:.3f})  1 - clip((slope_window - slope_baseline) / slope_std / 3, 0, 1)"))
                    log_queue.put(("__PLAIN__", "  PCI_window = Σ(weight_i × sub_score_i) / Σ(weight_i)"))

                log_queue.put(("__PLAIN__", ""))

            # Window-level OWI
            log_queue.put(("__PLAIN__", "  Window-level OWI:"))
            parts = []
            for mod_name in active_mods:
                abbr = {"motion": "α·MSI", "environment": "β·EEI", "physiology": "γ·PCI"}[mod_name]
                w    = mod_wts.get(mod_name, 0.0)
                parts.append(f"{abbr}  [α={w:.3f}]" if mod_name == "motion" else
                              f"{abbr}  [β={w:.3f}]" if mod_name == "environment" else
                              f"{abbr}  [γ={w:.3f}]")
            numerator = " + ".join(p.split("  ")[0] for p in parts)
            denominator = "W_avail (sum of weights for modules with data)"
            log_queue.put(("__PLAIN__", f"    OWI_window = 100 × ({numerator}) / {denominator}"))
            log_queue.put(("__PLAIN__", ""))

            # Route-level aggregation
            log_queue.put(("__PLAIN__", "  Route-level aggregation:"))
            log_queue.put(("__PLAIN__", f"    OWI_route = {profile.route_mean_weight:.0%} × mean(OWI_windows)"))
            log_queue.put(("__PLAIN__", f"              + {profile.route_p10_weight:.0%} × P10(OWI_windows)"))
            log_queue.put(("__PLAIN__", "  (P10 = 10th percentile — penalizes routes with bad segments)"))
            log_queue.put(("__PLAIN__", f"  Hotspot: any window with OWI < {profile.hotspot_threshold:.0f} pts"))
            log_queue.put(("__PLAIN__", ""))
            log_queue.put(("__PLAIN__", "─" * 60))
            log_queue.put(("__PLAIN__", ""))

            # ---- Physiology / Polar source description ----------------
            if physio_str:
                log_queue.put(("__PLAIN__", "PHYSIOLOGY DATA SOURCE"))
                log_queue.put(("__PLAIN__", "─" * 60))
                log_queue.put(("__PLAIN__", f"  Folder : {physio_str}"))
                log_queue.put(("__PLAIN__", "  → Will scan for Polar CSV files (name starting with 'polar_'"))
                log_queue.put(("__PLAIN__", "    or header Timestamp,HR,...  without IMU columns)."))
                log_queue.put(("__PLAIN__", "  → Polar samples aligned to iPhone recording via absolute timestamps."))
                log_queue.put(("__PLAIN__", "  → Reduced PCI : HR mean + HR slope  (weights 80 % / 20 %)"))
                log_queue.put(("__PLAIN__", "  → Full PCI    : enabled automatically if RR_ms / IBI_ms /"))
                log_queue.put(("__PLAIN__", "                  HRV_RMSSD_ms columns found in the Polar file."))
                log_queue.put(("__PLAIN__", "  → Physiology section added to each HTML report."))
                log_queue.put(("__PLAIN__", ""))
            else:
                if "physiology" in active_mods:
                    log_queue.put(("__PLAIN__", "  ⚠  No physiology folder set — PCI module will be inactive"))
                    log_queue.put(("__PLAIN__", "     unless a Polar CSV is found inside the recording folder."))
                    log_queue.put(("__PLAIN__", ""))


            if dry_run:
                log_queue.put(("__PLAIN__", "=== DRY RUN — no analysis performed ==="))
                log_queue.put(("__OK__", None))
                return

            from walkability_analyzer.main import run_analysis
            scoring_config = profile.to_scoring_config()
            run_analysis(
                data_root=data_root,
                output_root=output_root,
                process_video=self._process_video.get(),
                specific_route=route,
                scoring_config=scoring_config,
                physio_root=physio_root,
                scoring_profile=profile,
                use_sam2=self._use_sam2.get(),
            )

            reports = sorted(output_root.rglob("*_report.html"))
            log_queue.put(("__PLAIN__", ""))
            log_queue.put(("__PLAIN__", f"Analysis complete. {len(reports)} report(s) generated."))
            for rp in reports:
                log_queue.put(("__PLAIN__", f"  → {rp}"))
            log_queue.put(("__OK__", reports))

        except Exception as exc:
            import traceback
            log_queue.put(("__PLAIN__", ""))
            log_queue.put(("__PLAIN__", "=== ERROR ==="))
            log_queue.put(("__PLAIN__", traceback.format_exc()))
            log_queue.put(("__ERR__", str(exc)))
        finally:
            root_logger.removeHandler(handler)

    # =====================================================================
    # Log pump  (runs on main thread via after())
    # =====================================================================

    def _pump_log(self) -> None:
        try:
            while True:
                item = self._log_queue.get_nowait()
                if isinstance(item, tuple):
                    kind, payload = item
                    if kind == "__OK__":
                        self._btn_run.configure(state="normal")
                        if payload:
                            self._report_paths = payload
                            self._btn_report.configure(state="normal")
                        self._set_status("Analysis complete.", color=SUCCESS)
                    elif kind == "__ERR__":
                        self._btn_run.configure(state="normal")
                        self._set_status(f"Error: {payload}", color=DANGER)
                    elif kind == "__PLAIN__":
                        self._append_log(str(payload), "PLAIN")
                else:
                    # Plain string from logging handler
                    tag = "PLAIN"
                    s = str(item)
                    for level in ("WARNING", "ERROR", "DEBUG", "INFO"):
                        if level in s:
                            tag = level
                            break
                    self._append_log(s, tag)
        except queue.Empty:
            pass
        self.after(80, self._pump_log)

    def _append_log(self, text: str, tag: str = "PLAIN") -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text + "\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    # =====================================================================
    # Open report
    # =====================================================================

    def _on_open_report(self) -> None:
        if not self._report_paths:
            return
        if len(self._report_paths) == 1:
            webbrowser.open(self._report_paths[0].as_uri())
        else:
            # Multiple reports — show a picker dialog
            _ReportPicker(self, self._report_paths)

    # =====================================================================
    # Status bar
    # =====================================================================

    def _set_status(self, msg: str, color: str = "#374151") -> None:
        self._status_var.set(msg)
        self._status_lbl.configure(fg=color)


# ---------------------------------------------------------------------------
# Report picker (shown when multiple reports exist)
# ---------------------------------------------------------------------------

class _ReportPicker(tk.Toplevel):
    def __init__(self, parent: tk.Tk, paths: list[Path]) -> None:
        super().__init__(parent)
        self.title("Open Report")
        self.configure(bg=BG)
        self.resizable(False, False)
        tk.Label(self, text="Select a report to open:", bg=BG, font=FONT_H2).pack(padx=16, pady=(12, 4))
        lb = tk.Listbox(self, font=FONT_MONO, width=70, height=min(len(paths), 12), selectmode="single")
        lb.pack(padx=16, pady=4)
        for p in paths:
            lb.insert("end", str(p))
        lb.selection_set(0)

        def _open():
            sel = lb.curselection()
            if sel:
                webbrowser.open(paths[sel[0]].as_uri())
            self.destroy()

        ttk.Button(self, text="Open", command=_open).pack(pady=(4, 12))
        self.transient(parent)
        self.grab_set()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = WalkabilityGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
