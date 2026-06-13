# Quick Start Guide

## Installation

1. Create and activate virtual environment:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install core dependencies:
```powershell
pip install -r requirements.txt
```

3. *(Recommended)* Install SAM2 for accurate video analysis:
```powershell
# CPU-only build (suitable for most laptops)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install git+https://github.com/facebookresearch/sam2.git
```

4. Download the SAM2 checkpoint (one-time):
   - URL: https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt
   - Place at: `walkability_analyzer/video_processing/checkpoints/sam2.1_hiera_tiny.pt`
   - SAM2 is then **auto-detected** at runtime — no extra flags needed.

## Running the Analyzer

### GUI (easiest)
```powershell
python run_gui.py
```
The Setup tab lets you pick your data folder, scoring preset, physiology source, and toggle video processing + SAM2 with checkboxes.

### Command-line — sensor only

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output"
```

### Command-line — with video (SAM2 auto-detected)

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output" --process-video
```

### Process a Specific Route

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output" --route Route1
```

### With Verbose Logging

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output" --verbose
```

## Output Files

After running, check the `output/` directory:

- `Route1/` - Contains reports for Route1
  - `<recording>_report.html` - Main report with OWI score breakdown (open in browser)
  - `<recording>_map.html` - Interactive map with video annotation markers
  - `<recording>_plot.png` - Time series visualization
  - `<recording>_video_scores.csv` - Per-window video metrics (when video processed)
- `routes_summary.csv` - Summary of all routes (OWI + MSI/EEI/PCI columns)

## Troubleshooting

### Module not found errors
Make sure you're in the project root directory and the virtual environment is **activated**.

### No routes found
Check that your CSV files are in the correct directory structure (each route in its own subfolder).

### SAM2 not loading
Verify the checkpoint file exists at `walkability_analyzer/video_processing/checkpoints/sam2.1_hiera_tiny.pt` and that `torch` + `sam2` are installed in the active venv.

### Missing GPS data
The tool still works with IMU data only; GPS-based metrics will be absent.

## Next Steps

1. Review the generated HTML reports
2. Check OWI scores and MSI/EEI/PCI breakdown in `routes_summary.csv`
3. Tune scoring weights via the GUI or by editing `configs/scoring_default.json`
4. Tune SAM2 EEI normalisation in `walkability_analyzer/config.py` (`eei_crowd_max`, `eei_obstacle_max`)
5. Process additional routes
