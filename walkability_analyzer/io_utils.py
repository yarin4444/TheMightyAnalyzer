"""
I/O utilities for loading route data, sensor CSVs, and descriptions.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from walkability_analyzer.config import DEFAULT_COLUMN_MAPPING
from walkability_analyzer.data_structures import RouteData, SensorRecording

logger = logging.getLogger(__name__)


def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find the first matching column name from a list of candidates.
    
    Args:
        df: DataFrame to search in
        candidates: List of possible column names
        
    Returns:
        The first matching column name, or None if not found
    """
    for col in candidates:
        if col in df.columns:
            return col
    return None


def load_sensor_csv(
    csv_path: Path,
    column_mapping: Dict[str, List[str]] = None
) -> pd.DataFrame:
    """Load and standardize a sensor CSV file.
    
    Args:
        csv_path: Path to the CSV file
        column_mapping: Optional custom column mapping
        
    Returns:
        DataFrame with standardized column names
    """
    if column_mapping is None:
        column_mapping = DEFAULT_COLUMN_MAPPING
    
    logger.info(f"Loading sensor CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    
    # Create a mapping from found columns to standard names
    rename_map = {}
    for standard_name, candidates in column_mapping.items():
        found_col = find_column(df, candidates)
        if found_col:
            rename_map[found_col] = standard_name
    
    df = df.rename(columns=rename_map)
    
    # Parse timestamp
    if "timestamp" in df.columns:
        # Try to parse as datetime first
        try:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            # Convert to seconds from start
            df["time_seconds"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
        except:
            # Assume it's already numeric (seconds)
            df["time_seconds"] = df["timestamp"]
    else:
        # Create a time index based on row number
        logger.warning(f"No timestamp column found in {csv_path}, using row index")
        df["time_seconds"] = df.index * 0.01  # Assume 100 Hz if no timestamp
    
    # Set time as index
    df = df.set_index("time_seconds")
    
    return df


def estimate_sampling_rate(df: pd.DataFrame) -> float:
    """Estimate the sampling rate from the time index.
    
    Args:
        df: DataFrame with time_seconds index
        
    Returns:
        Estimated sampling rate in Hz
    """
    if len(df) < 2:
        return 100.0  # Default
    
    time_diffs = df.index.to_series().diff().dropna()
    median_dt = time_diffs.median()
    
    if median_dt > 0:
        return 1.0 / median_dt
    else:
        return 100.0  # Default


def load_description(route_path: Path) -> Optional[str]:
    """Load the description text file for a route.
    
    Args:
        route_path: Path to the route directory
        
    Returns:
        Description text or None if not found
    """
    desc_candidates = ["description.txt", "Description.txt", "README.txt"]
    
    for candidate in desc_candidates:
        desc_path = route_path / candidate
        if desc_path.exists():
            logger.info(f"Loading description from {desc_path}")
            return desc_path.read_text(encoding="utf-8")
    
    return None


def find_video_file(route_path: Path) -> Optional[Path]:
    """Find a video file in the route directory.
    
    Args:
        route_path: Path to the route directory
        
    Returns:
        Path to video file or None if not found
    """
    video_extensions = [".mp4", ".avi", ".mov", ".MP4", ".AVI", ".MOV"]
    
    for file in route_path.iterdir():
        if file.is_file() and file.suffix in video_extensions:
            logger.info(f"Found video file: {file}")
            return file
    
    return None


def load_route(route_path: Path) -> RouteData:
    """Load all data for a single route.
    
    Args:
        route_path: Path to the route directory
        
    Returns:
        RouteData object containing all route information
    """
    route_path = Path(route_path)
    route_id = route_path.name
    location = route_path.parent.name  # Get parent folder name
    
    logger.info(f"Loading route: {route_id}")
    
    # Find all CSV files (sensor recordings) — exclude Polar watch files
    csv_files = sorted(route_path.glob("*.csv"))

    # Import here to avoid circular imports at module load time
    try:
        from walkability_analyzer.physiology.polar_parser import is_polar_csv as _is_polar
    except ImportError:
        _is_polar = None  # fallback: no filtering

    sensor_recordings = []
    for csv_path in csv_files:
        # Skip Polar CSV files — they are handled by the physiology pipeline
        if _is_polar is not None and _is_polar(csv_path):
            logger.debug(f"Skipping Polar file (not a sensor recording): {csv_path.name}")
            continue
        try:
            df = load_sensor_csv(csv_path)
            sampling_rate = estimate_sampling_rate(df)
            
            recording = SensorRecording(
                recording_id=csv_path.stem,
                df=df,
                sampling_rate=sampling_rate,
                metadata={"source_file": str(csv_path)}
            )
            sensor_recordings.append(recording)
            logger.info(f"Loaded recording: {csv_path.stem} ({len(df)} samples, {sampling_rate:.1f} Hz)")
        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
    
    # Load description
    description = load_description(route_path)
    
    # Find video file
    video_path = find_video_file(route_path)
    
    return RouteData(
        route_id=route_id,
        sensor_recordings=sensor_recordings,
        description=description,
        video_path=video_path,
        location=location
    )


def discover_routes(data_root: Path) -> List[Path]:
    """Discover all route directories in the data root.
    
    Args:
        data_root: Root directory containing route folders
        
    Returns:
        List of paths to route directories
    """
    data_root = Path(data_root)
    
    if not data_root.exists():
        raise ValueError(f"Data root does not exist: {data_root}")
    
    # Find all directories that contain at least one CSV file
    route_paths = []
    for item in data_root.iterdir():
        if item.is_dir():
            csv_files = list(item.glob("*.csv"))
            if csv_files:
                route_paths.append(item)
    
    logger.info(f"Discovered {len(route_paths)} routes in {data_root}")
    return sorted(route_paths)
