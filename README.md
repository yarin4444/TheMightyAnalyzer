# Walkability Analyzer

A comprehensive Python tool for analyzing walking experiments from sensor (IMU + GPS) and video data.

## Features

- **Sensor Data Processing**: Reads and processes accelerometer, gyroscope, and GPS data from CSV files
- **Walking Segmentation**: Automatically detects walking segments using stomp events
- **Gait Analysis**: Computes step detection, cadence, step length, and walking speed
- **Anomaly Detection**: Identifies stops, changes in walking patterns, and unusual segments
- **Video Analysis**: Synchronizes video with sensor data, detects crowd levels, lighting conditions
- **Interactive Visualization**: Generates time-series plots and interactive maps with satellite imagery
- **Walkability Scoring**: Computes a composite walkability score based on multiple factors
- **HTML Reports**: Creates comprehensive reports combining all analysis results

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

### With Video Processing

```bash
python -m walkability_analyzer --data-root ./data --output-root ./output --process-video
```

### Skip Video Processing

```bash
python -m walkability_analyzer --data-root ./data --output-root ./output --no-video
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
    sensors_run1_plot.png       # Time series visualization
    sensors_run1_map.html       # Interactive map
    sensors_run1_report.html    # Combined HTML report
    sensors_run2_plot.png
    sensors_run2_map.html
    sensors_run2_report.html
  Route2/
    ...
  routes_summary.csv            # Summary of all routes
```

## Walkability Score

The walkability score (0-100) is computed from:

- **Speed**: Comfortable walking pace
- **Variability**: Consistency of walking speed
- **Stops**: Frequency and duration of stops
- **Crowd**: Crowding level (from video)
- **Shade**: Availability of shade (from video)
- **Crosswalks**: Safety infrastructure (from video)
- **Surface**: Surface quality (from acceleration variance)

Higher scores indicate better walkability.

## Project Structure

```
walkability_analyzer/
  __init__.py
  __main__.py
  cli.py                  # Command-line interface
  main.py                 # Main analysis pipeline
  config.py               # Configuration and constants
  data_structures.py      # Data classes
  io_utils.py             # Data loading utilities
  sensor_processing/
    preprocessing.py      # Data cleaning and feature extraction
    segmentation.py       # Stomp and step detection
    features.py           # Metrics computation
    anomalies.py          # Anomaly detection
  video_processing/
    sync.py              # Video-sensor synchronization
    analysis.py          # Video content analysis
  visualization/
    timeseries.py        # Time series plots
    mapping.py           # Interactive maps
    reporting.py         # HTML report generation
  scoring/
    walkability.py       # Walkability score computation
```

## Configuration

Default parameters can be found in `walkability_analyzer/config.py`:

- Stomp detection thresholds
- Step detection parameters
- Stop detection criteria
- Video analysis settings
- Walkability score weights

## Dependencies

Key libraries used:

- **pandas**: Data manipulation
- **numpy/scipy**: Numerical operations and signal processing
- **matplotlib**: Plotting
- **folium**: Interactive maps
- **opencv-python**: Video processing
- **librosa**: Audio analysis (clap detection)
- **scikit-learn**: Machine learning utilities

## Troubleshooting

### No GPS data
If GPS data is missing, the tool will still process IMU data and generate limited metrics.

### Video processing fails
Ensure `opencv-python` and `librosa` are installed. If issues persist, use `--no-video`.

### Import errors
Make sure all dependencies are installed: `pip install -r requirements.txt`

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
