# Project Status: Walkability Analyzer

**Project:** TheMightyAnalyzer - Automated Walkability Assessment System  
**Last Updated:** June 13, 2026  
**Version:** 1.3.0

---

## Project Overview

The Walkability Analyzer is a comprehensive system for automatically evaluating pedestrian route quality using smartphone sensor data and optional video recordings. The system processes acceleration, gyroscope, and GPS data to detect walking patterns, compute metrics, and generate detailed visual reports.

---

## Completed Features

### ✅ Core Infrastructure (Completed: Dec 4, 2025)

#### 1. **Project Structure**
- 8-package modular architecture
- 27 Python files with clear separation of concerns
- Configuration management system
- Custom data structures for type safety
- Comprehensive logging throughout

#### 2. **Data Loading & Processing**
- **Flexible CSV parsing** with automatic column detection
  - Supports multiple column naming conventions
  - Handles programmatic names (e.g., `Acceleration_X_1`)
  - Handles descriptive names (e.g., `Acceleration x (m/s^2)`)
- **Data validation** and cleaning pipeline
- **Sensor data types:** Accelerometer, Gyroscope, GPS, Timestamps
- **Sampling rate detection** and validation
- **Location extraction** from folder structure

#### 3. **Sensor Processing Pipeline**
- **Stomp Detection**
  - Identifies force application at start/end of walk
  - Uses acceleration magnitude peak detection
  - Configurable time windows and thresholds
  - Fallback mechanisms for missing stomps
  
- **Walking Segment Extraction**
  - Isolates actual walking data between stomps
  - Removes stationary periods before/after walk
  - Preserves all sensor channels
  
- **Step Detection**
  - Counts individual steps using peak detection
  - Computes step times and cadence
  - Filters noise using minimum distance thresholds
  - Handles 512 steps detected in 382.9s test case
  
- **Stop Detection**
  - Identifies complete stops during walking
  - Uses GPS speed thresholds (< 0.3 m/s)
  - Tracks stop duration and frequency
  
- **GPS Feature Computation**
  - Calculates speed from position deltas
  - Estimates distance traveled
  - Computes heading and trajectory

#### 4. **Metrics Computation**
- **Recording-level metrics:**
  - Total walking time
  - Total distance traveled
  - Mean and median speed
  - Step count and cadence (steps/minute)
  - Step length statistics
  - Number and duration of stops
  - Stop time fraction
  
- **Route-level aggregation:**
  - Combines metrics from multiple recordings
  - Weighted averages by time/distance
  - Summary statistics across recordings

#### 5. **Walkability Scoring System**
- **Seven-component weighted score (0-100 scale):**
  1. Walking Speed (20% weight)
  2. Speed Variability (15% weight)
  3. Number of Stops (25% weight)
  4. Crowding Index (10% weight) - video optional
  5. Shade Coverage (10% weight) - video optional
  6. Crosswalk Count (10% weight) - video optional
  7. Surface Quality (10% weight) - planned for future
  
- **Normalization** of all components to [0, 1]
- **Configurable thresholds** and weights
- **Default values** for missing data
- **Detailed breakdown** of score components
- See `SCORING_METHODOLOGY.md` for complete details

#### 6. **Visualization System**

##### **Time Series Plots**
- **Dual subplot layout:**
  - Top: GPS speed over time
  - Bottom: Acceleration magnitude over time
- **Visual markers:**
  - Dark green dashed line: Start force (stomp)
  - Dark orange dashed line: End force (stomp)
  - Red triangles: Detected steps
- **Enhanced styling:**
  - Thinner lines (0.8 linewidth) for clarity
  - Purple fill under acceleration curve (20% opacity)
  - Thinner stomp markers (linewidth=2)
  - Clean, readable legends
- **Saved as PNG files** in output directory

##### **Interactive Maps**
- **Folium-based mapping** with satellite imagery
- **Route visualization:**
  - Blue line showing walking path
  - GPS points plotted along route
- **Event markers:**
  - Green icon: Start position
  - Red icon: End position
  - Optional: Stop locations, anomalies
- **Satellite basemap** (Esri World Imagery)
- **Saved as standalone HTML** for browser viewing

##### **HTML Reports**
- **Professional design** with gradient headers
- **Comprehensive sections:**
  1. **Metadata:** Route ID, Location, Recording date/time
  2. **Key Metrics Grid:** 8 metric cards with values/units
  3. **Walking Profile:** Embedded time series plot
  4. **Detected Events:** Lists stops and anomalies
  5. **Route Map:** Embedded interactive map (iframe)
  6. **Walkability Score:** Large visual display at bottom
     - Color-coded by score (green/orange/red)
     - Prominent font size and styling
     - Explanatory text
- **Responsive layout** with CSS styling
- **Self-contained files** with relative paths

#### 7. **Command-Line Interface**
- **Flexible arguments:**
  - `--data-root`: Input data directory
  - `--output-root`: Output directory
  - `--route`: Specific route to process (optional)
  - `--verbose`: Detailed logging
- **Automatic discovery** of routes and recordings
- **Progress reporting** with INFO/DEBUG logs
- **Summary CSV** generation for all routes

#### 8. **Video Processing (Fully Implemented — SAM2)**
- **Pluggable per-frame detector architecture** (`detectors.py`)
  - `brightness_detector` — mean pixel luminance → 1–10 score
  - `crosswalk_detector` — Hough lines on HSV white mask (classical CV fallback)
  - `crowd_detector` — MOG2 background subtraction (classical CV fallback)
  - `surface_roughness_detector` — Laplacian variance on lower-half ROI
- **SAM2FrameAnalyzer** (`sam2_detector.py`) — single SAM2 pass per frame yields:
  - `crowd_count` — person-scale mask count (replaces MOG2)
  - `obstacle_count` — medium objects in walking path
  - `shade_fraction` — green/dark upper-frame mask coverage (0–1)
  - `crosswalk_confidence` — wide horizontal stripe masks (replaces Hough)
  - `crosswalk_detected` — binary flag
- **Auto-detection**: SAM2 is loaded automatically if `torch`+`sam2` installed and checkpoint present
- **Laptop optimisations**: `sam2_frame_sample_rate=0.2 Hz`, `max_input_width=640px`, `points_per_side=12`
- **Single-pass pipeline** (`pipeline.py`): `process_video_to_csv()` runs all detectors in one frame loop → windowed CSV
- **EEI wiring** (`owi_modular.py`): `video_csv_df_to_env_windows()` converts pipeline CSV to `env_window_data` for OWI EEI module with configurable normalisation (`eei_crowd_max`, `eei_obstacle_max`)
- **GUI controls**: “Process video” + “Use SAM2” checkboxes in Setup tab; SAM2 status label; auto-ticks when available
- **Validated on** `test_records/VideoAnalyzeTestFile.mp4` (422 MB, 56 s):
  - SAM2: crowd 21–33 (stable, realistic) vs. classical CV: 0–265 (garbage)
  - Crosswalk: fires in 3/12 windows (SAM2) vs. 12/12 (CV, all false positives)
  - New metrics: obstacle_count 4–15, shade_fraction 0–0.42
- **CLI flags:** `--process-video`, `--use-sam2`

---

## Testing & Validation

### ✅ Test Data
- **Location:** `test_records/BG_20-10-25/`
- **5 routes** with multiple recordings each
- **Real smartphone sensor data** from BGU campus
- **CSV format** with 100 Hz sampling rate

### ✅ Validated Functionality
- **Route1 Processing (BG 20-10-25)** — sensor + Polar, no video:
  - Recording 12-41-11: OWI=64.6, MSI=0.554, PCI=0.898, 624m / 372s
  - Recording 12-48-09: OWI=47.7, MSI=0.293, PCI=0.906, 515m / 383s
  - Polar HR aligned at 100% window coverage (reduced_pci mode)
  - Outputs: plots, maps, HTML reports, routes_summary.csv
- **VideoAnalyzeTestFile.mp4** (422 MB, 56 s):
  - SAM2 multi-metric pipeline: crowd 21–33, obstacles 4–15, shade 0–0.42, crosswalk in 3/12 windows
  - Classical CV comparison: crowd 0–265, crosswalk fires every window (all false positives)
  - CSV saved to `output/test_pipeline_sam2.csv`

### ✅ Edge Cases Handled
- Missing stomp detection (uses fallback)
- Missing columns (flexible mapping)
- GPS data gaps (handled gracefully)
- Empty/invalid recordings (skipped with logging)

---

## Bug Fixes & Improvements

### Session 1: Initial Generation & Debugging
1. **Fixed NameError:** Added `Tuple` to typing imports
2. **Fixed AttributeError:** Used `np.abs()` instead of pandas `.abs()`
3. **Fixed KeyError:** Initialized all metric dictionary keys

### Session 2: Report Enhancements
4. **Fixed date format:** Used `strftime('%Y-%m-%d %H:%M:%S')` instead of Unix timestamp
5. **Added location field:** Extracted from parent folder name
6. **Fixed plot display:** Made acceleration plot mandatory, removed conditional logic
7. **Enhanced stomp display:** Changed colors to darkgreen/darkorange, increased visibility

### Session 3: Data Loading Crisis Resolution
8. **Fixed column mapping:** Updated `DEFAULT_COLUMN_MAPPING` to recognize underscore format
   - Added patterns: `"Acceleration_X_1"`, `"Acceleration_Y_1"`, `"Acceleration_Z_1"`
   - Added patterns: `"AngularVelocity_X_2"`, `"AngularVelocity_Y_2"`, `"AngularVelocity_Z_2"`
   - Result: Acceleration data properly loaded from CSV files

### Session 6: Video Processing Integration (May 30, 2026)
13. **Fixed `mapping.py` — `'Index' object has no attribute 'abs'`:**
    - `(walking_segment.index - segment_mid_time).abs()` → `.to_series().abs()`
    - Affects video annotation marker placement on route maps

14. **Fixed `owi_modular.py` — `'VideoAnnotation' object has no attribute 'get'`:**
    - `_get_env_window()` previously expected plain dicts with `t_start`/`t_end` keys
    - Added `_video_annotation_to_env_dict()` converter; `_get_env_window` now accepts both `VideoAnnotation` objects and legacy dicts
    - Maps `annotation_type` (`crowd_high`, `crosswalk`, `light_dark`, etc.) → EEI keys (`crowding_w`, `crossing_complexity_w`, `shade_ratio_w`)
    - Multiple overlapping annotations in a window are merged

### Session 4: Visualization Refinement
9. **Enhanced acceleration plot:**
   - Initial: Thicker line (2.5), fill area (15% opacity), anomaly detection
   - Adjustment: Removed excessive anomaly markers (962 was too many)
   - Final: Thinner line (0.8), better fill (20% opacity), cleaner appearance
   
10. **Optimized stomp markers:**
    - Reduced from linewidth=3 to linewidth=2
    - Maintained dark green (start) and dark orange (end) colors
    - Kept "START"/"END" text labels (removed later for cleaner look)

### Session 5: Score Display & Documentation
11. **Added walkability score to reports:**
    - Large color-coded display at bottom of HTML reports
    - Green (≥70), Orange (40-69), Red (<40)
    - "out of 100" label with explanatory text
    - Computed per-recording for individual reports
    
12. **Created comprehensive documentation:**
    - `SCORING_METHODOLOGY.md`: Complete scoring explanation
    - `PROJECT_STATUS.md`: This file

---

## Current Capabilities Summary

### What Works Now ✅
- ✅ Load CSV sensor data from smartphone apps
- ✅ Detect walking segments (start/end stomps)
- ✅ Count steps and compute cadence
- ✅ Track GPS trajectory and distance
- ✅ Identify stops and walking patterns
- ✅ Compute 8+ walking metrics
- ✅ OWI v1 Modular score (MSI + EEI + PCI, per-window, 0–100)
- ✅ Six preset scoring profiles (JSON) + GUI profile editor
- ✅ Polar HR/HRV integration (absolute timestamp sync, reduced/full PCI)
- ✅ HR spike detection on route map
- ✅ Video processing: clap sync, single-pass frame pipeline, windowed CSV
- ✅ SAM2FrameAnalyzer: crowd, obstacles, shade, crosswalk in one pass
- ✅ SAM2 auto-detect at startup (checkpoint + package present)
- ✅ EEI module live: video CSV → crowd/obstacle/shade/crosswalk → OWI score
- ✅ GUI: preset selector, module/metric weight editor, video + SAM2 toggles
- ✅ Generate time series visualizations, interactive route maps, HTML reports
- ✅ Batch processing across multiple routes
- ✅ Summary CSV with OWI + MSI/EEI/PCI columns

### What’s Partially Implemented ⚠️
- ⚠️ `traffic_exposure` EEI metric (no vehicle detector yet; always None)
- ⚠️ EEI normalisation constants (`eei_crowd_max=40`, `eei_obstacle_max=20`) are configurable but not yet calibrated on annotated ground-truth routes
- ⚠️ Audio extraction requires ffmpeg for optimal speed; falls back to slow `audioread`
- ⚠️ Surface roughness score computed but not yet wired into EEI

### What’s Not Yet Implemented ❌
- ❌ `traffic_exposure` from SAM2 vehicle-shaped masks
- ❌ End-to-end test on a route with *both* sensor data and GoPro video
- ❌ Real-time processing mode
- ❌ Mobile app integration
- ❌ Weather condition integration

---

## Known Issues & Limitations

### Data Collection
- **Requires manual start/stop stomps** for segment extraction
- **GPS accuracy** depends on device and environment
- **No automatic sensor calibration**
- **Video synchronization** implemented via clap detection; requires ffmpeg for fastest audio extraction

### Processing
- **Single-threaded execution** (could be parallelized)
- **High memory usage** for long recordings
- **No incremental processing** (processes entire file)

### Visualization
- **Static plots** (no interactive time series)
- **Basic map styling** (could add more features)
- **No animation** of walking trajectory

### Scoring
- **Subjective weight choices** (not validated against ground truth)
- **Limited environmental factors** (no weather, time-of-day)
- **No comparison database** for percentile scores

---

## Dependencies

### Python Version
- Python 3.13.5

### Core Libraries
- `pandas>=2.0.0` - Data manipulation
- `numpy>=1.24.0` - Numerical computations
- `scipy>=1.10.0` - Signal processing (peak detection)
- `matplotlib>=3.7.0` - Plotting
- `folium>=0.14.0` - Interactive maps

### Video Processing (Future)
- `opencv-python>=4.8.0` - Video analysis
- `librosa>=0.10.0` - Audio processing
- `soundfile>=0.12.0` - Audio I/O

### Machine Learning (Planned)
- `scikit-learn>=1.3.0` - Anomaly detection

---

## File Organization

```
TheMightyAnalyzer/
├── walkability_analyzer/          # Main package
│   ├── __init__.py
│   ├── __main__.py                # Entry point
│   ├── cli.py                     # Command-line interface
│   ├── config.py                  # Configuration constants
│   ├── data_structures.py         # Type definitions
│   ├── io_utils.py                # Data loading
│   ├── main.py                    # Pipeline orchestration
│   │
│   ├── sensor_processing/         # Sensor analysis
│   │   ├── __init__.py
│   │   ├── preprocessing.py       # Data cleaning
│   │   ├── segmentation.py        # Stomp/step detection
│   │   ├── features.py            # Metric computation
│   │   └── anomalies.py           # Stop detection
│   │
│   ├── scoring/                   # Walkability scoring
│   │   ├── __init__.py
│   │   └── walkability.py         # Score calculation
│   │
│   ├── visualization/             # Output generation
│   │   ├── __init__.py
│   │   ├── timeseries.py          # Time series plots
│   │   ├── mapping.py             # Interactive maps
│   │   └── reporting.py           # HTML reports
│   │
│   └── video_processing/          # Video analysis (stubs)
│       ├── __init__.py
│       ├── sync.py                # Synchronization
│       └── analysis.py            # Environmental detection
│
├── test_records/                  # Test data
│   └── BG_20-10-25/               # BGU campus routes
│       ├── Route1/ ... Route5/    # Multiple routes
│       └── Tirat Carmel/          # Additional location
│
├── output/                        # Generated results
│   ├── routes_summary.csv         # Summary statistics
│   └── Route1/ ... Route5/        # Per-route outputs
│       ├── *_plot.png             # Time series plots
│       ├── *_map.html             # Interactive maps
│       └── *_report.html          # Complete reports
│
├── SCORING_METHODOLOGY.md         # Scoring explanation
├── PROJECT_STATUS.md              # This file
├── README.md                      # User guide
├── QUICKSTART.md                  # Quick start tutorial
├── requirements.txt               # Dependencies
└── setup.py                       # Installation config
```

---

## Next Steps & Roadmap

### High Priority 🔴
1. **Implement video processing pipeline:**
   - Pedestrian detection and counting
   - Shade/shadow detection
   - Crosswalk and infrastructure recognition
   - Surface condition analysis

2. **Validate scoring methodology:**
   - Compare against expert ratings
   - Adjust weights based on user studies
   - Add confidence intervals

3. **Improve step detection accuracy:**
   - Machine learning-based classifier
   - Handle different walking styles
   - Reduce false positives/negatives

### Medium Priority 🟡
4. **Add real-time processing mode:**
   - Stream sensor data
   - Live walkability estimation
   - Mobile app integration

5. **Enhance visualizations:**
   - Interactive time series (Plotly)
   - Animation of walking trajectory
   - Heat maps for problem areas

6. **Database integration:**
   - Store routes and metrics
   - Historical comparisons
   - City-wide dashboards

### Low Priority 🟢
7. **Weather integration:**
   - Fetch historical weather data
   - Adjust scores for conditions
   - Track seasonal variations

8. **Accessibility scoring:**
   - Detect ramps and curb cuts
   - Measure sidewalk width
   - Identify obstacles

9. **Multi-user support:**
   - User profiles and preferences
   - Personalized score weights
   - Social features

---

## Version History

### v1.0.0 (December 4, 2025)
- Initial working implementation
- Complete sensor processing pipeline
- Walkability scoring system
- Visualization and reporting
- Command-line interface
- Documentation and test data

---

## Maintenance Instructions

### When Adding a Major Feature:
1. **Update this file:**
   - Add to "Completed Features" section
   - Move from "Next Steps" if applicable
   - Update "Current Capabilities Summary"
   
2. **Update other docs:**
   - README.md if user-facing changes
   - SCORING_METHODOLOGY.md if scoring changes
   - QUICKSTART.md if new workflows added
   
3. **Test thoroughly:**
   - Run on all test routes
   - Validate outputs
   - Check for regressions
   
4. **Update version number:**
   - Increment in setup.py
   - Tag git commit
   - Update version history in this file

### When Fixing a Bug:
1. Document in "Bug Fixes & Improvements" section
2. Include date, issue description, and solution
3. Add test case if possible
4. Update version patch number if significant

---

## Contact & Support

**Project Location:** `c:\Users\שני הויזלר\Documents\רובוטיקה- בן גוריון\תזה\TheMightyAnalyzer`

**Maintainer:** Shani Weisler  
**Institution:** Ben-Gurion University  
**Project Type:** Thesis Research  
**Topic:** Automated Walkability Assessment Using Smartphone Sensors

---

## License & Usage

This is academic research software developed for thesis purposes at Ben-Gurion University. All rights reserved.
