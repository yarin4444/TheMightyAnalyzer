"""
Interactive map creation using Folium.
"""

import logging
from pathlib import Path
from typing import List, Optional

import folium
import numpy as np
import pandas as pd

from walkability_analyzer.data_structures import SegmentAnnotation, VideoAnnotation

logger = logging.getLogger(__name__)


def create_route_map(
    walking_segment: pd.DataFrame,
    sensor_annotations: List[SegmentAnnotation],
    video_annotations: Optional[List[VideoAnnotation]] = None,
    output_path: Path = None,
    title: str = "Route Map"
) -> folium.Map:
    """Create an interactive map of the walking route.
    
    Args:
        walking_segment: DataFrame with GPS data
        sensor_annotations: List of sensor-based annotations
        video_annotations: Optional list of video-based annotations
        output_path: Optional path to save the map HTML
        title: Map title
        
    Returns:
        Folium Map object
    """
    if "latitude" not in walking_segment.columns or "longitude" not in walking_segment.columns:
        logger.warning("No GPS data available for mapping")
        # Create a dummy map
        m = folium.Map(location=[32.0, 34.8], zoom_start=13)
        folium.Marker(
            [32.0, 34.8],
            popup="No GPS data available",
            icon=folium.Icon(color='red', icon='info-sign')
        ).add_to(m)
        
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            m.save(str(output_path))
        
        return m
    
    # Remove NaN values
    gps_data = walking_segment[["latitude", "longitude"]].dropna()
    
    if len(gps_data) == 0:
        logger.warning("No valid GPS points for mapping")
        m = folium.Map(location=[32.0, 34.8], zoom_start=13)
        if output_path:
            m.save(str(output_path))
        return m
    
    # Calculate center of the route
    center_lat = gps_data["latitude"].mean()
    center_lon = gps_data["longitude"].mean()
    
    # Create map with satellite imagery
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=16,
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri World Imagery'
    )
    
    # Add OpenStreetMap overlay for reference (optional, with transparency)
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='Street Names',
        overlay=True,
        control=True,
        opacity=0.4
    ).add_to(m)
    
    # Draw the route as a polyline
    route_coords = [[lat, lon] for lat, lon in zip(gps_data["latitude"], gps_data["longitude"])]
    
    folium.PolyLine(
        route_coords,
        color='blue',
        weight=4,
        opacity=0.7,
        popup='Walking Route'
    ).add_to(m)
    
    # Add start marker
    folium.Marker(
        route_coords[0],
        popup='Start',
        icon=folium.Icon(color='green', icon='play', prefix='fa')
    ).add_to(m)
    
    # Add end marker
    folium.Marker(
        route_coords[-1],
        popup='End',
        icon=folium.Icon(color='red', icon='stop', prefix='fa')
    ).add_to(m)
    
    # Add markers for sensor annotations
    for ann in sensor_annotations:
        # Find GPS coordinates at the median time of this segment
        segment_mid_time = (ann.start_time + ann.end_time) / 2
        
        # Find closest GPS point to this time
        closest_idx = np.abs(walking_segment.index - segment_mid_time).argmin()
        
        if closest_idx < len(walking_segment):
            lat = walking_segment.iloc[closest_idx]["latitude"]
            lon = walking_segment.iloc[closest_idx]["longitude"]
            
            if pd.notna(lat) and pd.notna(lon):
                if ann.segment_type == "stop":
                    icon_color = 'orange'
                    icon_name = 'pause'
                elif ann.segment_type == "change":
                    icon_color = 'cadetblue'
                    icon_name = 'exclamation'
                elif ann.segment_type == "hr_spike":
                    icon_color = 'darkred'
                    icon_name = 'heartbeat'
                else:
                    icon_color = 'blue'
                    icon_name = 'info-sign'

                if ann.segment_type == "hr_spike":
                    meta = ann.metadata or {}
                    popup_text = "<b>&#10084; HR SPIKE</b><br>"
                    popup_text += f"Peak: <b>{meta.get('peak_hr', 0):.0f} bpm</b><br>"
                    popup_text += f"Baseline: {meta.get('baseline_hr', 0):.0f} bpm &nbsp; Threshold: {meta.get('threshold_bpm', 0):.0f} bpm<br>"
                    popup_text += f"Duration: {ann.end_time - ann.start_time:.0f}s &nbsp; ({ann.start_time:.1f}s\u2013{ann.end_time:.1f}s)"
                else:
                    popup_text = f"<b>{ann.segment_type.upper()}</b><br>"
                    popup_text += f"{ann.label or ''}<br>"
                    popup_text += f"Time: {ann.start_time:.1f}s - {ann.end_time:.1f}s"
                
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(popup_text, max_width=200),
                    icon=folium.Icon(color=icon_color, icon=icon_name, prefix='fa')
                ).add_to(m)
    
    # Add markers for video annotations (if available)
    if video_annotations:
        for v_ann in video_annotations:
            segment_mid_time = (v_ann.t_start_sensor + v_ann.t_end_sensor) / 2
            closest_idx = (walking_segment.index - segment_mid_time).abs().argmin()
            
            if closest_idx < len(walking_segment):
                lat = walking_segment.iloc[closest_idx]["latitude"]
                lon = walking_segment.iloc[closest_idx]["longitude"]
                
                if pd.notna(lat) and pd.notna(lon):
                    if "crowd" in v_ann.annotation_type.lower():
                        icon_color = 'purple'
                        icon_name = 'users'
                    elif "crosswalk" in v_ann.annotation_type.lower():
                        icon_color = 'white'
                        icon_name = 'road'
                    elif "shade" in v_ann.annotation_type.lower() or "dark" in v_ann.annotation_type.lower():
                        icon_color = 'black'
                        icon_name = 'moon'
                    else:
                        icon_color = 'pink'
                        icon_name = 'video-camera'
                    
                    popup_text = f"<b>VIDEO: {v_ann.annotation_type}</b><br>"
                    popup_text += f"Time: {v_ann.t_start_sensor:.1f}s - {v_ann.t_end_sensor:.1f}s<br>"
                    if v_ann.extra_info:
                        for key, value in v_ann.extra_info.items():
                            popup_text += f"{key}: {value}<br>"
                    
                    folium.Marker(
                        [lat, lon],
                        popup=folium.Popup(popup_text, max_width=200),
                        icon=folium.Icon(color=icon_color, icon=icon_name, prefix='fa')
                    ).add_to(m)
    
    # Add HTML legend overlay
    legend_html = """
<div style="position:fixed;bottom:24px;left:14px;z-index:9999;background:white;
     padding:10px 16px;border-radius:8px;border:2px solid #bbb;font-size:13px;
     box-shadow:2px 2px 8px rgba(0,0,0,0.25);line-height:2.0;pointer-events:none;">
  <b style="font-size:14px;">Map Legend</b><br>
  <span style="color:#2ca02c;font-size:18px;font-weight:bold;">&#9654;</span>&nbsp; Route Start<br>
  <span style="color:#d62728;font-size:18px;font-weight:bold;">&#9632;</span>&nbsp; Route End<br>
  <span style="color:#e67e22;font-size:16px;">&#9646;</span>&nbsp; Stop<br>
  <span style="color:#1a78a8;font-size:16px;">&#9998;</span>&nbsp; Gait change<br>
  <span style="color:#c0392b;font-size:16px;">&#10084;</span>&nbsp; HR spike<br>
  <span style="color:#9b59b6;font-size:16px;">&#128101;</span>&nbsp; Crowding (video)<br>
</div>
"""
    m.get_root().html.add_child(folium.Element(legend_html))

    # Add layer control
    folium.LayerControl().add_to(m)
    
    # Save map if output path is provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        m.save(str(output_path))
        logger.info(f"Map saved to {output_path}")
    
    return m
