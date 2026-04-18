"""
Preprocessing functions for sensor data.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

logger = logging.getLogger(__name__)


def compute_acceleration_magnitude(df: pd.DataFrame) -> pd.Series:
    """Compute the magnitude of 3D acceleration.
    
    Args:
        df: DataFrame with accel_x, accel_y, accel_z columns
        
    Returns:
        Series with acceleration magnitude (m/s^2)
    """
    if all(col in df.columns for col in ["accel_x", "accel_y", "accel_z"]):
        acc_mag = np.sqrt(
            df["accel_x"]**2 + df["accel_y"]**2 + df["accel_z"]**2
        )
        return acc_mag
    else:
        logger.warning("Missing acceleration columns, returning zeros")
        return pd.Series(0.0, index=df.index)


def highpass_filter(
    signal: pd.Series,
    cutoff: float = 0.5,
    fs: float = 100.0,
    order: int = 4
) -> pd.Series:
    """Apply a high-pass Butterworth filter to a signal.
    
    Args:
        signal: Input signal
        cutoff: Cutoff frequency in Hz
        fs: Sampling frequency in Hz
        order: Filter order
        
    Returns:
        Filtered signal
    """
    nyquist = 0.5 * fs
    normal_cutoff = cutoff / nyquist
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    
    # Use filtfilt for zero-phase filtering
    filtered = filtfilt(b, a, signal.fillna(0))
    
    return pd.Series(filtered, index=signal.index)


def lowpass_filter(
    signal: pd.Series,
    cutoff: float = 5.0,
    fs: float = 100.0,
    order: int = 4
) -> pd.Series:
    """Apply a low-pass Butterworth filter to a signal.
    
    Args:
        signal: Input signal
        cutoff: Cutoff frequency in Hz
        fs: Sampling frequency in Hz
        order: Filter order
        
    Returns:
        Filtered signal
    """
    nyquist = 0.5 * fs
    normal_cutoff = cutoff / nyquist
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    
    filtered = filtfilt(b, a, signal.fillna(0))
    
    return pd.Series(filtered, index=signal.index)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points on Earth.
    
    Args:
        lat1, lon1: First point (degrees)
        lat2, lon2: Second point (degrees)
        
    Returns:
        Distance in meters
    """
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    
    # Earth radius in meters
    r = 6371000
    
    return c * r


def compute_gps_features(df: pd.DataFrame, interpolation_limit: int = 5) -> pd.DataFrame:
    """Compute GPS-based features (distance, speed, etc.).
    
    Args:
        df: DataFrame with latitude and longitude columns
        interpolation_limit: Max consecutive missing values to interpolate
        
    Returns:
        DataFrame with added GPS features
    """
    if "latitude" not in df.columns or "longitude" not in df.columns:
        logger.warning("No GPS data available")
        df["gps_distance"] = 0.0
        df["gps_speed"] = 0.0
        return df
    
    # Interpolate missing GPS values
    df["latitude"] = df["latitude"].interpolate(limit=interpolation_limit)
    df["longitude"] = df["longitude"].interpolate(limit=interpolation_limit)
    
    # Process course (heading) if available
    if "course" in df.columns:
        df["gps_course"] = df["course"].interpolate(limit=interpolation_limit)
        logger.debug("Processing GPS course/heading data")
    
    # Compute distance between consecutive points
    distances = []
    for i in range(len(df)):
        if i == 0:
            distances.append(0.0)
        else:
            lat1, lon1 = df.iloc[i-1][["latitude", "longitude"]]
            lat2, lon2 = df.iloc[i][["latitude", "longitude"]]
            
            if pd.notna(lat1) and pd.notna(lon1) and pd.notna(lat2) and pd.notna(lon2):
                dist = haversine_distance(lat1, lon1, lat2, lon2)
                distances.append(dist)
            else:
                distances.append(0.0)
    
    df["gps_distance"] = distances
    df["gps_cumulative_distance"] = df["gps_distance"].cumsum()
    
    # Compute speed (m/s) - use existing speed column if available
    if "speed" in df.columns:
        df["gps_speed"] = df["speed"]
        logger.debug("Using existing speed column from GPS data")
    else:
        time_diff = df.index.to_series().diff().dt.total_seconds()
        df["gps_speed"] = df["gps_distance"] / time_diff
        logger.debug("Computing speed from distance and time")
    
    # Clean up infinite/invalid speeds
    df["gps_speed"] = df["gps_speed"].replace([np.inf, -np.inf], np.nan)
    df["gps_speed"] = df["gps_speed"].fillna(0.0)
    
    # Apply some smoothing to speed
    if len(df) > 10:
        df["gps_speed"] = df["gps_speed"].rolling(window=5, center=True, min_periods=1).mean()
    
    return df


def clean_sensor_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and prepare sensor data.
    
    Args:
        df: Raw sensor DataFrame
        
    Returns:
        Cleaned DataFrame
    """
    # Handle missing values with simple interpolation
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].interpolate(method='linear', limit=10)
    
    # Drop rows with too many missing values
    df = df.dropna(thresh=len(df.columns) * 0.5)
    
    return df
