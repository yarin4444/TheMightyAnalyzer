"""Test script to check the new metrics values."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from walkability_analyzer.data_structures import SensorRecording
from walkability_analyzer.sensor_processing.preprocessing import (
    clean_sensor_data, 
    compute_acceleration_magnitude, 
    compute_gps_features
)
from walkability_analyzer.sensor_processing.segmentation import detect_stomps, extract_walking_segment, detect_steps
from walkability_analyzer.sensor_processing.anomalies import detect_weird_segments
from walkability_analyzer.sensor_processing.features import compute_recording_metrics
from walkability_analyzer.config import SENSOR_CONFIG

# Load one recording
csv_path = r"test_records\BG_20-10-25\Route1\20-10-2025_12-41-11.csv"
df = pd.read_csv(csv_path, parse_dates=["Timestamp"], index_col="Timestamp")

recording = SensorRecording(
    recording_id="20-10-2025_12-41-11",
    df=df,
    sampling_rate=100.0
)

# Preprocess
df = clean_sensor_data(recording.df)
df["acc_mag"] = compute_acceleration_magnitude(df)
df = compute_gps_features(df)

# Detect stomps and extract walking segment
t_start, t_end = detect_stomps(df["acc_mag"], recording.sampling_rate, SENSOR_CONFIG)
walking_segment = extract_walking_segment(df, t_start, t_end)

# Detect steps
step_times = detect_steps(
    walking_segment["acc_mag"],
    recording.sampling_rate,
    t_start,
    t_end,
    SENSOR_CONFIG
)

# Detect stops
annotations = detect_weird_segments(walking_segment, SENSOR_CONFIG)
stops = [
    {"duration": ann.end_time - ann.start_time}
    for ann in annotations if ann.annotation_type == "stop"
]

# Compute metrics
metrics = compute_recording_metrics(recording, walking_segment, step_times, t_start, t_end, stops)

print("=" * 80)
print("NEW METRICS VALUES")
print("=" * 80)
print(f"Median speed: {metrics.get('median_speed'):.3f} m/s" if metrics.get('median_speed') else "Median speed: None")
print(f"Turns per km: {metrics.get('num_turns_per_km'):.2f}" if metrics.get('num_turns_per_km') else "Turns per km: None")
print(f"Surface quality: {metrics.get('surface_quality'):.3f}" if metrics.get('surface_quality') else "Surface quality: None")
print("=" * 80)
print("\nOTHER METRICS (for reference)")
print("=" * 80)
print(f"Mean speed: {metrics.get('mean_speed'):.3f} m/s")
print(f"Speed variability: {metrics.get('speed_variability'):.3f} m/s")
print(f"Total distance: {metrics.get('total_distance'):.1f} m")
print(f"Number of stops: {metrics.get('number_of_stops')}")
print(f"Surface roughness: {metrics.get('surface_roughness'):.3f}" if metrics.get('surface_roughness') else "Surface roughness: None")

