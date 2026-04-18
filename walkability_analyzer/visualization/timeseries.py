"""
Time series plotting functions for walking profiles.
"""

import logging
from pathlib import Path
from typing import List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from walkability_analyzer.data_structures import SegmentAnnotation

logger = logging.getLogger(__name__)


def create_time_series_plot(
    walking_segment: pd.DataFrame,
    annotations: List[SegmentAnnotation],
    step_times: List[float],
    t_start: float,
    t_end: float,
    output_path: Path,
    title: str = "Walking Profile"
) -> None:
    """Create a time series plot of the walking profile.
    
    Args:
        walking_segment: DataFrame with walking data
        annotations: List of segment annotations
        step_times: List of detected step times
        t_start: Start time of walking (for marking)
        t_end: End time of walking (for marking)
        output_path: Path to save the plot
        title: Plot title
    """
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    time = walking_segment.index
    
    # Plot 1: Speed or acceleration magnitude
    ax1 = axes[0]
    
    if "gps_speed" in walking_segment.columns:
        speed = walking_segment["gps_speed"]
        ax1.plot(time, speed, 'b-', linewidth=1.5, label='GPS Speed')
        ax1.set_ylabel('Speed (m/s)', fontsize=11)
        ax1.grid(True, alpha=0.3)
        
        # Add mean speed line
        mean_speed = speed.mean()
        ax1.axhline(mean_speed, color='green', linestyle='--', 
                   linewidth=1, label=f'Mean: {mean_speed:.2f} m/s', alpha=0.7)
    else:
        # Fall back to acceleration magnitude
        if all(col in walking_segment.columns for col in ["accel_x", "accel_y", "accel_z"]):
            acc_mag = np.sqrt(
                walking_segment["accel_x"]**2 + 
                walking_segment["accel_y"]**2 + 
                walking_segment["accel_z"]**2
            )
            ax1.plot(time, acc_mag, 'r-', linewidth=1, label='Acceleration Magnitude', alpha=0.7)
            ax1.set_ylabel('Acceleration (m/s²)', fontsize=11)
            ax1.grid(True, alpha=0.3)
    
    # Mark stomp events
    ax1.axvline(t_start, color='purple', linestyle='--', linewidth=2, label='Start Stomp', alpha=0.8)
    ax1.axvline(t_end, color='orange', linestyle='--', linewidth=2, label='End Stomp', alpha=0.8)
    
    # Overlay annotations
    for ann in annotations:
        if ann.segment_type == "stop":
            ax1.axvspan(ann.start_time, ann.end_time, alpha=0.3, color='red', label='Stop' if 'Stop' not in [l.get_label() for l in ax1.get_legend_handles_labels()[0]] else '')
        elif ann.segment_type == "change":
            ax1.axvspan(ann.start_time, ann.end_time, alpha=0.2, color='yellow', label='Change' if 'Change' not in [l.get_label() for l in ax1.get_legend_handles_labels()[0]] else '')
    
    ax1.legend(loc='upper right', fontsize=9)
    ax1.set_title(title, fontsize=13, fontweight='bold')
    
    # Plot 2: Acceleration magnitude with step detection
    ax2 = axes[1]
    
    # Always plot acceleration magnitude
    if all(col in walking_segment.columns for col in ["accel_x", "accel_y", "accel_z"]):
        acc_mag = np.sqrt(
            walking_segment["accel_x"]**2 + 
            walking_segment["accel_y"]**2 + 
            walking_segment["accel_z"]**2
        )
        
        # Plot acceleration curve with thinner line and better fill for clarity
        ax2.plot(time, acc_mag, 'purple', linewidth=0.8, alpha=0.7, label='Acceleration Magnitude')
        ax2.fill_between(time, acc_mag, alpha=0.2, color='purple')
        
        # Mark detected steps if available
        if step_times:
            step_values = []
            for t in step_times:
                idx = walking_segment.index.get_indexer([t], method='nearest')[0]
                step_values.append(acc_mag.iloc[idx])
            ax2.scatter(step_times, step_values, c='red', s=50, marker='v', 
                       label=f'Detected Steps (n={len(step_times)})', zorder=5, alpha=0.7)
        
        # Mark start and end stomps with longer, thinner lines
        ax2.axvline(t_start, color='darkgreen', linestyle='--', linewidth=2, alpha=0.9, label='Start Force (Stomp)')
        ax2.axvline(t_end, color='darkorange', linestyle='--', linewidth=2, alpha=0.9, label='End Force (Stomp)')
        
        # Add text annotations for start/end forces
        y_max = acc_mag.max()
        ax2.text(t_start, y_max * 0.95, 'START', rotation=90, va='top', ha='right', 
                fontsize=9, fontweight='bold', color='darkgreen', alpha=0.8)
        ax2.text(t_end, y_max * 0.95, 'END', rotation=90, va='top', ha='right',
                fontsize=9, fontweight='bold', color='darkorange', alpha=0.8)
        
        ax2.set_ylabel('Acceleration (m/s²)', fontsize=11)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right', fontsize=9)
    else:
        ax2.text(0.5, 0.5, 'Acceleration data not available', 
                transform=ax2.transAxes, ha='center', va='center', fontsize=12)
    
    ax2.set_xlabel('Time (seconds)', fontsize=11)
    
    plt.tight_layout()
    
    # Save figure
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Time series plot saved to {output_path}")
