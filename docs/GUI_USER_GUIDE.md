# Walkability Analyzer GUI — User Guide

> **Audience:** Researchers running walkability analysis sessions.
> **Prerequisite:** Python environment set up with all dependencies installed (`pip install -r requirements.txt`).

---

## Table of Contents

1. [Launching the GUI](#1-launching-the-gui)
2. [Tab Overview](#2-tab-overview)
3. [Running a Test — Step by Step](#3-running-a-test--step-by-step)
   - [Step 1 — Set Data Locations (Setup tab)](#step-1--set-data-locations-setup-tab)
   - [Step 2 — Choose a Scoring Preset (Setup tab)](#step-2--choose-a-scoring-preset-setup-tab)
   - [Step 3 — (Optional) Adjust Metric Settings (Scoring tab)](#step-3--optional-adjust-metric-settings-scoring-tab)
   - [Step 4 — (Optional) Advanced Windowing (Advanced tab)](#step-4--optional-advanced-windowing-advanced-tab)
   - [Step 5 — Dry Run to Preview Config](#step-5--dry-run-to-preview-config)
   - [Step 6 — Run the Analysis](#step-6--run-the-analysis)
   - [Step 7 — View the Results](#step-7--view-the-results)
4. [Saving and Loading Configurations](#4-saving-and-loading-configurations)
5. [Preset Reference](#5-preset-reference)
6. [Metric Reference](#6-metric-reference)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Launching the GUI

Open a terminal (PowerShell or Command Prompt), navigate to the project folder, and run:

```powershell
cd "path\to\TheMightyAnalyzer"
python run_gui.py
```

The main window opens with four tabs across the top: **Setup**, **Scoring**, **Advanced**, and **Log**.

---

## 2. Tab Overview

| Tab | Purpose |
|---|---|
| **Setup** | Set input/output folders, choose a scoring preset, and set run options |
| **Scoring** | Fine-tune which modules and metrics are active, and their relative weights |
| **Advanced** | Change windowing parameters (window size, overlap, hotspot threshold) |
| **Log** | Live output of the analysis as it runs |

The **action bar** at the bottom is always visible:

| Button | Action |
|---|---|
| **▶ Run Analysis** | Runs the full analysis |
| **Dry Run** | Prints the resolved configuration without running any analysis |
| **Save Config…** | Saves the current settings to a `.json` file |
| **Load Config…** | Loads a previously saved `.json` config |
| **Open Report** | Opens the HTML report in your browser (enabled after a successful run) |

---

## 3. Running a Test — Step by Step

### Step 1 — Set Data Locations (Setup tab)

The **Setup** tab is the first screen you see.

1. **Data root folder** — click **Browse…** and select the folder containing your route subfolders.  
   Example: `test_records\BG_20-10-25`  
   The folder must contain `.csv` or `.mat` sensor log files (directly or in subfolders).

2. **Output folder** — where HTML reports and map files will be saved.  
   Default: `output` (inside the project folder). Leave unchanged for most runs.

3. **Physiology folder** _(optional)_ — if you have heart-rate/HRV data (`.json` or `.csv`), click **Browse…** and point to its folder. Leave blank if not available.

4. **Route subfolder** _(optional)_ — to process only one specific route (e.g. `Route1`), type its name here. Leave blank to process **all** routes found under the data root.

---

### Step 2 — Choose a Scoring Preset (Setup tab)

Select one of the five radio buttons:

| Preset | When to use |
|---|---|
| **motion_only** | You have only IMU + GPS data. Recommended default. |
| **motion_plus_physiology** | You also have heart-rate / HRV data. |
| **motion_plus_environment** | You also have video / environmental annotations. |
| **full_multimodal** | You have all three data types. |
| **custom** | You want to manually configure every module and metric in the Scoring tab. |

The preset auto-selects the correct modules. You can refine them further in the **Scoring** tab.

Also on this screen:
- ☑ **Open report after analysis** — automatically opens the HTML report in your browser when the run finishes.
- ☑ **Verbose logging** — shows detailed DEBUG-level messages in the Log tab.

---

### Step 3 — (Optional) Adjust Metric Settings (Scoring tab)

Click the **Scoring** tab to see all modules and their metrics.

Each **module** (Motion, Environment, Physiology) has:
- A checkbox to **enable or disable** the entire module.
- A **Module weight** field — the relative importance of this module in the final OWI score. Weights are automatically renormalized, so you can enter any positive numbers.

Each **metric** inside a module has:
- A checkbox to **enable or disable** that metric.
- A **Weight** field — the relative importance of this metric within its module.

**Example:** To focus only on speed and regularity for the Motion module:
1. Uncheck **Cadence**, **Stop Ratio**, and **Abnormal Motion**.
2. Adjust the weights of **Speed** and **Regularity** as desired (e.g. 0.6 and 0.4).
3. Auto-renormalization will handle the rest.

> **Note:** If you change the preset in the Setup tab, all scoring values are reset to that preset's defaults.

---

### Step 4 — (Optional) Advanced Windowing (Advanced tab)

Click the **Advanced** tab to change windowing parameters:

| Field | Default | Meaning |
|---|---|---|
| **Window length (sec)** | `5.0` | Duration of each scoring window in seconds |
| **Window overlap (0–1)** | `0.5` | Fraction of overlap between consecutive windows (0.5 = 50%) |
| **Hotspot threshold (pts)** | `35.0` | Windows scoring below this value are flagged as walkability hotspots |
| **Auto-renormalize weights** | ☑ checked | Automatically rescales weights when metrics are disabled. Recommended. |

For most test runs, the defaults are appropriate.

---

### Step 5 — Dry Run to Preview Config

Before committing to a full analysis run, click **Dry Run**.

The **Log** tab opens automatically and prints:
- The resolved data root, output root, and route filter.
- The full scoring profile summary — which modules are active, their weights, and which metrics are enabled.

This is the safest way to verify your configuration is correct **without** processing any data.

---

### Step 6 — Run the Analysis

Click **▶ Run Analysis**.

- The **Log** tab opens automatically.
- Progress messages appear in real time (white = info, yellow = warning, red = error).
- The UI remains responsive — you can scroll the log or switch tabs while the analysis runs.
- The status bar at the bottom shows `Running…` in orange while active.

When finished:
- Status bar changes to **"Analysis complete."** in green.
- The **Open Report** button in the bottom-right becomes active.

**Typical run time:** a few seconds per route for motion-only analysis on a modern laptop.

---

### Step 7 — View the Results

Click **Open Report**. If multiple routes were processed, a picker dialog lists all generated reports — select the one you want.

The HTML report opens in your default browser and contains:
- **Overall OWI score** for the route.
- **Per-module scores** (MSI / EEI / PCI).
- **Interactive map** with colour-coded walkability hotspots.
- **Time-series plots** of speed, cadence, and scoring windows.
- **Scoring configuration** section showing exactly what settings were used.

HTML map files are saved alongside the reports in the output folder (e.g. `output\BG_20-10-25\Route1\`).

---

## 4. Saving and Loading Configurations

To reuse a carefully tuned configuration:

1. Set up the modules and metrics as desired.
2. Click **Save Config…** → choose a filename (e.g. `configs/my_run.json`).
3. Next time: click **Load Config…** → select the file. All settings restore instantly.

Pre-built example configs are available in the `configs/` folder:

| File | Description |
|---|---|
| `scoring_default.json` | Balanced default weighting |
| `scoring_motion_only.json` | IMU + GPS only |
| `scoring_motion_physiology.json` | IMU + GPS + heart-rate |
| `scoring_motion_environment.json` | IMU + GPS + environment |
| `scoring_heat_focus.json` | Heat / shade emphasis |
| `scoring_safety_focus.json` | Safety / crossing emphasis |

---

## 5. Preset Reference

| Preset | Motion | Environment | Physiology |
|---|---|---|---|
| `motion_only` | ✓ | — | — |
| `motion_plus_physiology` | ✓ | — | ✓ |
| `motion_plus_environment` | ✓ | ✓ | — |
| `full_multimodal` | ✓ | ✓ | ✓ |
| `custom` | configurable | configurable | configurable |

---

## 6. Metric Reference

### Motion module (MSI)

| Metric | Default weight | What it measures |
|---|---|---|
| Speed | 0.30 | How close walking speed is to personal baseline |
| Cadence | 0.25 | How close step rate is to personal baseline |
| Regularity | 0.20 | Consistency of step intervals (lower CV = better) |
| Stop Ratio | 0.15 | Fraction of time spent stationary (fewer stops = better) |
| Abnormal Motion | 0.10 | Fraction of windows with high jerk (smoother = better) |

### Environment module (EEI)

| Metric | Default weight | What it measures |
|---|---|---|
| Obstacle Load | 0.25 | Density of physical obstacles on the path |
| Traffic Exposure | 0.25 | Proximity and volume of vehicle traffic |
| Crowding | 0.20 | Pedestrian crowding density |
| Crossing Complexity | 0.20 | Difficulty/safety of road crossings |
| Shade | 0.10 | Availability of shade along the route |

### Physiology module (PCI)

| Metric | Default weight | What it measures |
|---|---|---|
| Heart Rate | 0.40 | Elevation of HR above personal resting baseline |
| RMSSD | 0.50 | Heart rate variability (higher = more relaxed) |
| Heart Rate Slope | 0.10 | Rate of HR rise during the walk |

**OWI route score formula:**
```
OWI_route = 0.70 × mean(window scores) + 0.30 × P10(window scores)
```
The P10 term penalizes routes with frequent short-but-bad segments.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Data root not found` error | Path entered manually with a typo | Use the **Browse…** button instead |
| Log shows `No windows generated` | Recording is too short | Use a recording of at least 10–15 seconds |
| Log shows `No routes found` | Data root contains no `.csv` or `.mat` files | Check the folder structure; files must be inside subfolders named `Route1`, `Route2`, etc. |
| Score is 0.0 or missing | All motion data was filtered out | Check GPS accuracy; try with `sigma_speed` relaxed in `score_config.py` |
| Open Report button stays grey | Analysis produced no HTML output | Check the Log tab for errors |
| GUI exits with exit code 1 in VS Code | VS Code Python terminal quirk | Run `python run_gui.py` in a standard PowerShell terminal instead |
