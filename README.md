# Walkability Analyzer

A comprehensive Python tool for analyzing walking experiments from sensor (IMU + GPS) and video data.

## Features

- **Sensor Data Processing**: Reads and processes accelerometer, gyroscope, and GPS data from CSV files
- **Walking Segmentation**: Automatically detects walking segments using stomp events
- **Gait Analysis**: Computes step detection, cadence, step length, and walking speed
- **Anomaly Detection**: Identifies stops, changes in walking patterns, and unusual segments
- **Video Analysis (SAM2)**: Single-pass SAM2 segmentation yields crowd count, obstacle count, shade fraction, and crosswalk confidence per window — replacing weak classical-CV heuristics
- **OWI Modular Scoring**: Three-module index (MSI motion, EEI environment, PCI physiology) with per-window aggregation and JSON-configurable scoring profiles
- **Polar Heart-Rate Integration**: Aligns Polar CSV exports to sensor timeline; computes HRV-based PCI module
- **Interactive Visualization**: Generates time-series plots and interactive maps with satellite imagery
- **HTML Reports**: Creates comprehensive reports combining all analysis results
- **GUI**: Tkinter interface with preset selector, scoring weights editor, video/SAM2 toggles

## Installation

### Prerequisites

- Python 3.10 or higher
- pip

### Setup

1. Clone or download this repository
2. Create a virtual environment:

```bash
python -m venv venv
```

3. Activate the virtual environment:

**Windows:**
```powershell
.\venv\Scripts\Activate.ps1
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. *(Optional but recommended)* Install SAM2 for accurate video analysis:

```powershell
# CPU-only (laptop)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install git+https://github.com/facebookresearch/sam2.git
```

Then download the checkpoint (once):
```
https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt
```
Place it at: `walkability_analyzer/video_processing/checkpoints/sam2.1_hiera_tiny.pt`

SAM2 is **auto-detected** at runtime — no flags needed once the checkpoint is present.

## Data Organization

Organize your data in the following structure:

```
data_root/
  Route1/
    sensors_run1.csv
    sensors_run2.csv
    description.txt      # Optional: route description
    video.mp4           # Optional: GoPro recording
  Route2/
    sensors_run1.csv
    description.txt
  ...
```

### Sensor CSV Format

The tool automatically detects column names, but expects:
- Timestamp column (e.g., `timestamp`, `time`)
- Accelerometer: `accel_x`, `accel_y`, `accel_z`
- Gyroscope (optional): `gyro_x`, `gyro_y`, `gyro_z`
- GPS: `latitude`, `longitude` (optional `altitude`)

## Usage

### Basic Usage

Process all routes in a data directory:

```bash
python -m walkability_analyzer --data-root ./test_records/BG_20-10-25 --output-root ./output
```

### Process Specific Route

```bash
python -m walkability_analyzer --data-root ./data --output-root ./output --route Route1
```

### With Video Processing (SAM2 auto-detected)

```bash
python -m walkability_analyzer --data-root ./data --output-root ./output --process-video
```

### Force SAM2 on / off

```bash
# Explicitly enable SAM2
python -m walkability_analyzer --data-root ./data --output-root ./output --process-video --use-sam2

# Force classical CV even if SAM2 is installed
python -m walkability_analyzer --data-root ./data --output-root ./output --process-video --no-video
```

### GUI (recommended for interactive use)

```bash
python run_gui.py
```

### Verbose Output

```bash
python -m walkability_analyzer --data-root ./data --output-root ./output --verbose
```

## Output

The tool generates:

```
output_root/
  Route1/
    <recording>_plot.png            # Time series visualization
    <recording>_map.html            # Interactive map with video annotations
    <recording>_report.html         # Combined HTML report with OWI breakdown
    <recording>_video_scores.csv    # Per-window video metrics (when video processed)
  Route2/
    ...
  routes_summary.csv               # Summary of all routes (OWI + MSI/EEI/PCI)
```

## Walkability Score (OWI v1 Modular)

The Open Walkability Index (0–100) combines three modules:

| Module | Key | Metrics | Data source |
|---|---|---|---|
| **MSI** | Motion Stability | speed, cadence, regularity, stop ratio, abnormal motion | iPhone IMU + GPS |
| **EEI** | Environmental Exposure | crowd, obstacle load, shade, crosswalk complexity, traffic | GoPro video + SAM2 |
| **PCI** | Physiological Comfort | heart rate elevation, HRV (RMSSD), HR slope | Polar watch CSV |

Modules are optional — missing data is skipped and weights renormalised automatically.  
Six preset scoring profiles are included in `configs/`; custom profiles can be built in the GUI.

Higher scores indicate better walkability.

## Project Structure

```
walkability_analyzer/
  __init__.py
  __main__.py
  cli.py                     # Command-line interface (--process-video, --use-sam2)
  main.py                    # Main analysis pipeline
  config.py                  # Configuration (VideoConfig, SensorConfig, etc.)
  data_structures.py         # Data classes
  io_utils.py                # Data loading utilities
  sensor_processing/
    preprocessing.py         # Data cleaning and feature extraction
    segmentation.py          # Stomp and step detection
    features.py              # Metrics computation
    anomalies.py             # Anomaly detection
  video_processing/
    sync.py                  # Video-sensor synchronization (clap detection)
    analysis.py              # Video content analysis (brightness, crowd, crosswalk)
    detectors.py             # Pluggable per-frame detector callables
    pipeline.py              # Single-pass frame sampling → windowed CSV export
    sam2_detector.py         # SAM2FrameAnalyzer: one SAM2 pass → 5 EEI metrics
    checkpoints/             # SAM2 model checkpoint (sam2.1_hiera_tiny.pt)
  physiology/
    polar_parser.py          # Polar CSV export parsing
    sync.py                  # Polar ↔ sensor timeline alignment
    window_aggregation.py    # Per-window HR / HRV metrics
  scoring/
    walkability.py           # Legacy Cardoso v2 scorer
    owi_modular.py           # OWI v1 Modular (MSI + EEI + PCI)
    score_config.py          # ScoringProfile, ModuleConfig, MetricConfig
  visualization/
    timeseries.py            # Time series plots
    mapping.py               # Interactive maps
    reporting.py             # HTML report generation
cconfigs/                    # Preset scoring profiles (JSON)
run_gui.py                   # Tkinter GUI launcher
run_walkability.py           # CLI wizard launcher
```

## Configuration

Default parameters can be found in `walkability_analyzer/config.py`:

- Stomp detection thresholds
- Step detection parameters
- Stop detection criteria
- Video analysis settings
- Walkability score weights

## Dependencies

| Library | Purpose |
|---|---|
| pandas, numpy, scipy | Data manipulation and signal processing |
| matplotlib | Time series plots |
| folium | Interactive route maps |
| opencv-python | Frame sampling, classical CV detectors |
| librosa, soundfile | Audio clap detection for video sync |
| torch, torchvision | SAM2 backbone (optional, CPU or CUDA) |
| sam2 | SAM2 segmentation model (optional) |
| scikit-learn | Anomaly detection utilities |

## Troubleshooting

### No GPS data
The tool still processes IMU data and generates limited metrics.

### Video processing fails
Ensure `opencv-python` and `librosa` are installed. If clap sync fails, the video step is skipped gracefully.

### SAM2 not loading
Check that the checkpoint exists at `walkability_analyzer/video_processing/checkpoints/sam2.1_hiera_tiny.pt` and that `torch` + `sam2` are installed in the active venv.

### Import errors
```bash
pip install -r requirements.txt
```

## Future Enhancements

- Custom configuration files (YAML/JSON)
- Advanced video analysis (object detection, crosswalk recognition)
- Real-time analysis mode
- Export to additional formats (JSON, Excel)
- Web-based dashboard

## License

This project is provided as-is for research and educational purposes.

## Authors

Walkability Research Team

## Citation

If you use this tool in your research, please cite appropriately.
