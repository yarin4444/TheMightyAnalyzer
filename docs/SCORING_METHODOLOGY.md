# Walkability Score Methodology

## Overview

The walkability score is a composite metric ranging from **0 to 100** that quantifies the quality of walking conditions on a route. Higher scores indicate better walkability.

This methodology follows the framework from Cardoso et al. (2024) for walkability assessment using smartphone sensors.

**Last Updated:** January 3, 2026

---

## Score Components

The walkability score is calculated as a weighted sum of seven normalized indicators:

### 1. **Stops Density (Weight: 20%)**
- **What it measures:** Frequency of complete stops per kilometer
- **Rationale:** Fewer stops indicate better flow and fewer obstacles (Cardoso et al., 2024)
- **Raw Metric:** `stops_per_km = num_stops / max(L_km, eps)`
  - Stop detected when: `speed < stop_speed_threshold` continuously for ≥ `stop_min_duration_sec`
  - Length-normalized to account for route distance
- **Normalization (Cardoso Eq. 2-3):**
  - Min-max scaling: `x_scaled = (stops_per_km - min_stops) / (max_stops - min_stops)`
  - Inverted (lower is better): `normalized = 1 - x_scaled`
  - Clipped to [0, 1]
- **Calculation Examples:**
  - 0 stops/km → scaled = 0.00 → normalized = **1.00** → contributes 0.20 × 1.00 = **20.0 points**
  - 2 stops/km → scaled = 0.40 → normalized = **0.60** → contributes 0.20 × 0.60 = **12.0 points**
  - 5 stops/km → scaled = 1.00 → normalized = **0.00** → contributes 0.20 × 0.00 = **0.0 points**

### 2. **Median Speed (Weight: 15%)**
- **What it measures:** Typical walking pace during the route
- **Rationale:** Higher median speed indicates comfortable, unobstructed walking
- **Raw Metric:** `speed_med = median(speed)` over walking segment (m/s)
- **Normalization (Cardoso Eq. 2):**
  - Min-max scaling: `x_scaled = (speed_med - min_speed) / (max_speed - min_speed)`
  - Higher is better (no inversion needed)
  - Clipped to [0, 1]
- **Calculation Examples:**
  - 0.5 m/s → scaled = 0.00 → normalized = **0.00** → contributes 0.15 × 0.00 = **0.0 points**
  - 1.0 m/s → scaled = 0.33 → normalized = **0.33** → contributes 0.15 × 0.33 = **5.0 points**
  - 1.5 m/s → scaled = 0.67 → normalized = **0.67** → contributes 0.15 × 0.67 = **10.0 points**
  - 2.0 m/s → scaled = 1.00 → normalized = **1.00** → contributes 0.15 × 1.00 = **15.0 points**

### 3. **Speed Variability (Weight: 10%)**
- **What it measures:** Standard deviation of walking speed
- **Rationale:** Lower variability indicates smooth, unobstructed walking
- **Raw Metric:** `speed_var = std(speed)` over walking segment (m/s)
- **Normalization (Cardoso Eq. 2-3):**
  - Min-max scaling: `x_scaled = (speed_var - min_var) / (max_var - min_var)`
  - Inverted (lower is better): `normalized = 1 - x_scaled`
  - Clipped to [0, 1]
- **Calculation Examples:**
  - 0.0 m/s → scaled = 0.00 → normalized = **1.00** → contributes 0.10 × 1.00 = **10.0 points**
  - 0.2 m/s → scaled = 0.40 → normalized = **0.60** → contributes 0.10 × 0.60 = **6.0 points**
  - 0.4 m/s → scaled = 0.80 → normalized = **0.20** → contributes 0.10 × 0.20 = **2.0 points**
  - 0.5 m/s → scaled = 1.00 → normalized = **0.00** → contributes 0.10 × 0.00 = **0.0 points**

### 4. **Turns Density (Weight: 10%)**
- **What it measures:** Frequency of significant directional changes per kilometer
- **Rationale:** Fewer turns indicate straighter, more comfortable routes (Cardoso et al., 2024)
- **Raw Metric:** `turns_per_km = num_turns / max(L_km, eps)`
  - Turn detected when: `abs(delta_course) >= 45°` with wraparound handling
  - Length-normalized to account for route distance
- **Normalization (Cardoso Eq. 2-3):**
  - Min-max scaling: `x_scaled = (turns_per_km - min_turns) / (max_turns - min_turns)`
  - Inverted (lower is better): `normalized = 1 - x_scaled`
  - Clipped to [0, 1]
- **Calculation Examples:**
  - 0 turns/km → scaled = 0.00 → normalized = **1.00** → contributes 0.10 × 1.00 = **10.0 points**
  - 3 turns/km → scaled = 0.30 → normalized = **0.70** → contributes 0.10 × 0.70 = **7.0 points**
  - 7 turns/km → scaled = 0.70 → normalized = **0.30** → contributes 0.10 × 0.30 = **3.0 points**
  - 10 turns/km → scaled = 1.00 → normalized = **0.00** → contributes 0.10 × 0.00 = **0.0 points**

### 5. **Crowding Index (Weight: 10%)**
- **What it measures:** Pedestrian density from video analysis
- **Rationale:** Less crowded sidewalks allow for comfortable walking
- **Raw Metric:** `crowding_index ∈ [0, 1]` (0 = empty, 1 = very crowded)
- **Normalization (Cardoso Eq. 2-3):**
  - Min-max scaling: `x_scaled = (crowding_index - 0) / (1 - 0)`
  - Inverted (lower is better): `normalized = 1 - x_scaled`
  - Clipped to [0, 1]
- **Default:** 0.5 (neutral) if video not available
- **Calculation Examples:**
  - Crowding = 0.0 (empty) → scaled = 0.00 → normalized = **1.00** → contributes 0.10 × 1.00 = **10.0 points**
  - Crowding = 0.3 (light) → scaled = 0.30 → normalized = **0.70** → contributes 0.10 × 0.70 = **7.0 points**
  - Crowding = 0.5 (moderate) → scaled = 0.50 → normalized = **0.50** → contributes 0.10 × 0.50 = **5.0 points**
  - Crowding = 1.0 (packed) → scaled = 1.00 → normalized = **0.00** → contributes 0.10 × 0.00 = **0.0 points**

### 6. **Shade Coverage (Weight: 15%)**
- **What it measures:** Proportion of route with shade coverage from video
- **Rationale:** Shade provides thermal comfort, especially in hot weather (Cardoso et al., 2024)
- **Raw Metric:** `shade_ratio ∈ [0, 1]` (0 = no shade, 1 = full shade)
- **Normalization (Cardoso Eq. 2):**
  - Min-max scaling: `x_scaled = (shade_ratio - 0) / (1 - 0)`
  - Higher is better (no inversion needed)
  - Clipped to [0, 1]
- **Default:** 0.5 (neutral) if video not available
- **Calculation Examples:**
  - Shade = 0.0 (no shade) → scaled = 0.00 → normalized = **0.00** → contributes 0.15 × 0.00 = **0.0 points**
  - Shade = 0.3 (30% shaded) → scaled = 0.30 → normalized = **0.30** → contributes 0.15 × 0.30 = **4.5 points**
  - Shade = 0.5 (half shaded) → scaled = 0.50 → normalized = **0.50** → contributes 0.15 × 0.50 = **7.5 points**
  - Shade = 1.0 (full shade) → scaled = 1.00 → normalized = **1.00** → contributes 0.15 × 1.00 = **15.0 points**

### 7. **Crosswalk Density (Weight: 10%)**
- **What it measures:** Frequency of marked crosswalks per kilometer
- **Rationale:** Crosswalks indicate pedestrian-friendly infrastructure (Cardoso et al., 2024)
- **Raw Metric:** `crosswalks_per_km = crosswalk_count / max(L_km, eps)`
  - Length-normalized to account for route distance
- **Normalization (Cardoso Eq. 2):**
  - Min-max scaling: `x_scaled = (crosswalks_per_km - min_cw) / (max_cw - min_cw)`
  - Higher is better (no inversion needed)
  - Clipped to [0, 1]
- **Default:** 0.5 (neutral) if video not available
- **Calculation Examples:**
  - 0 crosswalks/km → scaled = 0.00 → normalized = **0.00** → contributes 0.10 × 0.00 = **0.0 points**
  - 2 crosswalks/km → scaled = 0.40 → normalized = **0.40** → contributes 0.10 × 0.40 = **4.0 points**
  - 4 crosswalks/km → scaled = 0.80 → normalized = **0.80** → contributes 0.10 × 0.80 = **8.0 points**
  - 5 crosswalks/km → scaled = 1.00 → normalized = **1.00** → contributes 0.10 × 1.00 = **10.0 points**

### 8. **Surface Quality (Weight: 10%)**
- **What it measures:** Smoothness and evenness of walking surface from IMU
- **Rationale:** Smooth surfaces reduce trip hazards and improve comfort
- **Raw Metric:** Roughness proxy from vertical acceleration (e.g., RMS of high-pass filtered Az or jerk RMS)
  - Converted to 0–1 quality score (rougher → lower quality)
- **Normalization (Cardoso Eq. 2-3):**
  - Min-max scaling: `x_scaled = (surface_quality - 0) / (1 - 0)`
  - Higher is better (no inversion needed, already inverted from roughness)
  - Clipped to [0, 1]
- **Default:** 0.5 (neutral) if not yet implemented
- **Calculation Examples:**
  - Quality = 0.0 (very rough) → scaled = 0.00 → normalized = **0.00** → contributes 0.10 × 0.00 = **0.0 points**
  - Quality = 0.4 (some roughness) → scaled = 0.40 → normalized = **0.40** → contributes 0.10 × 0.40 = **4.0 points**
  - Quality = 0.7 (good) → scaled = 0.70 → normalized = **0.70** → contributes 0.10 × 0.70 = **7.0 points**
  - Quality = 1.0 (perfect) → scaled = 1.00 → normalized = **1.00** → contributes 0.10 × 1.00 = **10.0 points**

---

## Final Score Calculation

The final walkability score is computed following Cardoso et al. (2024) Equation 4:

```
score_0_1 = Σ (w_i × x_norm_i)

where:
  w_stops = 0.20
  w_speed = 0.15
  w_speed_var = 0.10
  w_turns = 0.10
  w_crowding = 0.10
  w_shade = 0.15
  w_crosswalks = 0.10
  w_surface = 0.10
  
  Total: 1.00 (100%)
```

**Final score:** `walkability_score = 100 × score_0_1`

**Total weights:** 100% (0.20 + 0.15 + 0.10 + 0.10 + 0.10 + 0.15 + 0.10 + 0.10 = 1.00)

---

## Normalization Method (Cardoso 2024, Method A)

All indicators are normalized using **min-max scaling** with a global calibration file:

### Cardoso Equation 2 (Min-Max Scaling):
```
x_scaled = (x - min_x) / (max_x - min_x)
```

### Cardoso Equation 3 (Inversion for "Lower is Better"):
```
x_norm = 1 - x_scaled
```

### Calibration File Structure:
A JSON file stores global min/max values across all analyzed routes:

```json
{
  "stops_per_km": {"min": 0.0, "max": 5.0},
  "speed_med": {"min": 0.5, "max": 2.0},
  "speed_var": {"min": 0.0, "max": 0.5},
  "turns_per_km": {"min": 0.0, "max": 10.0},
  "crowding_index": {"min": 0.0, "max": 1.0},
  "shade_ratio": {"min": 0.0, "max": 1.0},
  "crosswalks_per_km": {"min": 0.0, "max": 5.0},
  "surface_quality": {"min": 0.0, "max": 1.0}
}
```

**Note:** All normalized values are clipped to [0, 1] to handle outliers.

---

## Complete Example Calculation

**Scenario:** Urban route with moderate conditions

**Input Data:**
- Route length: L = 1200 m (L_km = 1.2)
- Number of stops: 2 stops
- Median speed: 1.4 m/s
- Speed std deviation: 0.25 m/s
- Number of turns (≥45°): 8 turns
- Crowding index: 0.5 (no video, default)
- Shade ratio: 0.5 (no video, default)
- Crosswalk count: 3 crosswalks
- Surface quality: 0.5 (not implemented, default)

**Step 1: Compute Raw Indicators**
1. `stops_per_km = 2 / 1.2 = 1.67 stops/km`
2. `speed_med = 1.4 m/s`
3. `speed_var = 0.25 m/s`
4. `turns_per_km = 8 / 1.2 = 6.67 turns/km`
5. `crowding_index = 0.5` (default)
6. `shade_ratio = 0.5` (default)
7. `crosswalks_per_km = 3 / 1.2 = 2.5 crosswalks/km`
8. `surface_quality = 0.5` (default)

**Step 2: Normalize Using Calibration (Min-Max)**

Assuming calibration ranges from above:

1. **Stops:** `x_scaled = (1.67 - 0) / (5 - 0) = 0.33` → `x_norm = 1 - 0.33 = 0.67`
2. **Speed:** `x_scaled = (1.4 - 0.5) / (2.0 - 0.5) = 0.60` → `x_norm = 0.60`
3. **Speed Var:** `x_scaled = (0.25 - 0) / (0.5 - 0) = 0.50` → `x_norm = 1 - 0.50 = 0.50`
4. **Turns:** `x_scaled = (6.67 - 0) / (10 - 0) = 0.67` → `x_norm = 1 - 0.67 = 0.33`
5. **Crowding:** `x_scaled = (0.5 - 0) / (1 - 0) = 0.50` → `x_norm = 1 - 0.50 = 0.50`
6. **Shade:** `x_scaled = (0.5 - 0) / (1 - 0) = 0.50` → `x_norm = 0.50`
7. **Crosswalks:** `x_scaled = (2.5 - 0) / (5 - 0) = 0.50` → `x_norm = 0.50`
8. **Surface:** `x_scaled = (0.5 - 0) / (1 - 0) = 0.50` → `x_norm = 0.50`

**Step 3: Weighted Sum (Cardoso Eq. 4)**

```
score_0_1 = 0.20×0.67 + 0.15×0.60 + 0.10×0.50 + 0.10×0.33 + 
            0.10×0.50 + 0.15×0.50 + 0.10×0.50 + 0.10×0.50
          
          = 0.134 + 0.090 + 0.050 + 0.033 + 0.050 + 0.075 + 0.050 + 0.050
          = 0.532
```

**Final Score:** `100 × 0.532 = 53.2 / 100` (Poor)

---

## Score Interpretation

| Score Range | Rating | Interpretation |
|-------------|--------|----------------|
| 80-100 | Excellent | Outstanding walkability with minimal issues |
| 70-79 | Good | Generally comfortable walking conditions |
| 60-69 | Fair | Acceptable but with some limitations |
| 40-59 | Poor | Significant obstacles or discomfort |
| 0-39 | Very Poor | Severe walkability problems |

---

## Sensor Data Sources

### Required Sensors (from smartphone CSV)
- **GPS:** Latitude, longitude, speed, course, hacc (horizontal accuracy)
  - Used for: Distance calculation, speed metrics, turn detection
  - Invalid data handling: Ignore points with missing coordinates or excessive hacc
- **Accelerometer:** Acceleration_X, Acceleration_Y, Acceleration_Z
  - Used for: Step detection, stop detection, surface quality (future)
- **Gyroscope:** AngularVelocity_X, AngularVelocity_Y, AngularVelocity_Z
  - Used for: Walking stability, balance analysis
- **Orientation:** Orientation_X, Orientation_Y, Orientation_Z
  - Used for: Coordinate frame transformations
- **Clock:** Timestamp
  - Used for: Time synchronization, duration calculations

### Optional Data (from video)
- **Pedestrian counting:** Estimates crowding index
- **Shade detection:** Identifies covered/shaded areas
- **Infrastructure detection:** Counts crosswalks and amenities
- **Surface analysis:** Visual pavement quality (future enhancement)

**Default behavior:** When video is unavailable, video-based metrics default to **0.5 (neutral)**.

---

## Configuration Parameters

Key thresholds and parameters used in scoring (from `config.py`):

### GPS and Distance
- `hacc_threshold`: Maximum horizontal accuracy for valid GPS points
- `min_segment_length_km`: Minimum route length (epsilon to avoid division by zero)

### Stop Detection
- `stop_speed_threshold`: Speed below which motion is considered stopped (m/s)
- `stop_min_duration_sec`: Minimum continuous duration to count as a stop event

### Turn Detection
- `turn_angle_threshold`: Minimum heading change to count as a turn (default: 45°)
- Wraparound handling: 359° → 1° = 2° change

### Speed Metrics
- Calibrated from data: `min_speed_med`, `max_speed_med`
- Calibrated from data: `min_speed_var`, `max_speed_var`

### Calibration Ranges (Method A)
All min/max values are stored in a global calibration JSON file that updates as new routes are analyzed:
- `stops_per_km`: {min, max}
- `speed_med`: {min, max}
- `speed_var`: {min, max}
- `turns_per_km`: {min, max}
- `crowding_index`: {0.0, 1.0} (fixed range)
- `shade_ratio`: {0.0, 1.0} (fixed range)
- `crosswalks_per_km`: {min, max}
- `surface_quality`: {0.0, 1.0} (fixed range)

---

## Known Limitations

### Current Implementation (v2.0)
1. **Surface quality** uses default 0.5 (neutral) - IMU-based roughness detection not yet implemented
2. **Video analysis** is optional - defaults to 0.5 when unavailable
3. **Calibration file** must be manually initialized for first run
4. **Route length normalization** critical - densities (stops, turns, crosswalks) are per-km
5. **GPS quality** varies - invalid points (missing coords, high hacc) are filtered
6. **Turn detection** uses course changes ≥45° - may miss subtle directional changes
7. **Weather and time-of-day** not factored into scoring

### Data Quality Requirements
- **Minimum route length:** Should be > 100m to avoid unstable per-km metrics
- **GPS accuracy:** Points with hacc > threshold are ignored
- **Sampling rate:** Assumes ~100 Hz for accelerometer/gyroscope
- **Video sync:** If using video, requires proper timestamp alignment

### Future Improvements Planned
- IMU-based surface roughness detection (RMS of high-pass filtered vertical acceleration)
- Adaptive calibration file updates as dataset grows
- Weather impact adjustment
- Accessibility scoring (ramps, curb cuts, obstacles)
- Time-of-day weighting (rush hour, nighttime safety)

---

## Version History

### Version 2.0 (January 3, 2026)
- **Methodology alignment:** Updated to follow Cardoso et al. (2024) framework
- **Normalization method:** Switched to Method A (min-max scaling) with global calibration file
- **New indicators:**
  - Added **turns density** (10% weight) for route directness
  - Changed from mean to **median speed** (15% weight) for robustness
  - All density metrics now **length-normalized** (per-km)
- **Weight redistribution:**
  - Stops: 25% → **20%** (still highest priority)
  - Speed: 20% → **15%** (median instead of mean)
  - Shade: 10% → **15%** (increased importance based on Cardoso)
  - Added turns: **10%** (new metric)
  - Speed variability: 15% → **10%**
  - Crowding, crosswalks, surface: remain **10%** each
- **Calibration:** All metrics now use adaptive min-max ranges from global calibration file
- **Surface quality:** Changed default from 0.0 to 0.5 (neutral) pending implementation

### Version 1.0 (December 4, 2025)
- Initial scoring methodology
- Seven-component weighted system
- Sensor-based metrics with optional video analysis
- Fixed thresholds and weights

---

## References

### Academic Background
- **Cardoso, B. J., et al. (2024).** "Exploring the effect of heat on pedestrian walking…" - Primary methodology source for min-max normalization (Method A, Equations 1-4) and walkability indicators
- **Bohannon, R.W. (1997).** Comfortable and maximum walking speed norms
- **Highway Capacity Manual (2010).** Pedestrian comfort and service level metrics

### Implementation
- Code location: `walkability_analyzer/scoring/walkability.py`
- Configuration: `walkability_analyzer/config.py`
- Data structures: `walkability_analyzer/data_structures.py`
- Calibration file: `walkability_calibration.json` (global min/max ranges)

---

## Maintenance Notes

**When updating the scoring methodology:**

1. **Update documentation:**
   - This file with new weights, indicators, or normalization methods
   - Document the rationale for changes
   - Update version history with date and summary

2. **Update code implementation:**
   - Modify `walkability.py` to implement new indicators or weights
   - Update `config.py` if new thresholds/parameters needed
   - Update `features.py` if new raw metrics need computation

3. **Update calibration file:**
   - Add new indicator ranges to `walkability_calibration.json`
   - Run calibration script on existing dataset to establish min/max
   - Ensure backward compatibility or version migration

4. **Validation:**
   - Test on existing routes to validate changes
   - Compare scores before/after to understand impact
   - Update test cases and expected outputs

5. **Update related documentation:**
   - `PROJECT_STATUS.md` to reflect scoring improvements
   - `README.md` if user-facing changes
   - HTML report templates if new metrics displayed

**Critical:** When changing weights or normalization, document the academic justification and expected impact on scores.
