You are an expert Python developer. Build a working, maintainable Python project according to the following specification.

==================================================
PROJECT CONTEXT
==================================================
I have pilot recordings from walking experiments. For each walking route, I recorded:
- Inertial and position data from an iPhone (IMU + GPS), placed in the pedestrian's pocket.
- The data was originally saved as .mat and converted to .csv using a MATLAB script.
- Optionally, there is also a GoPro video recording of the walk.
- Each route has its own folder.

Goal: Build a generic analysis tool that:
1) Reads and processes sensor CSV recordings per route.
2) Detects the walking segment (start/end) using a distinct stomp event at the beginning and at the end.
3) Visualizes the walking profile (time series) and the route on a satellite/imagery map, with markers for "weird" segments (stops, changes in walking).
4) (If video exists) Loads the video, detects start/end using a clap in the audio and the video frames, synchronizes it with the sensor timeline, and identifies interesting segments (crowding, crossings, light/shade, etc.) and marks them on the map.
5) Computes basic gait and route metrics (step length, average pace, total distance, etc.).
6) Proposes and computes a first version of a mathematical Walkability score per route.
7) Is written in clean, modular Python code, easy to extend for many future recordings.

==================================================
TECH STACK AND GENERAL REQUIREMENTS
==================================================
- Language: Python 3.10+.
- Use virtualenv or venv; provide a `requirements.txt`.
- Use these main libraries (when appropriate):
  - pandas (CSV handling, data manipulation)
  - numpy (numerical operations)
  - matplotlib (time-series plots)
  - folium (for interactive maps with tiles; use a satellite/imagery provider such as Esri.WorldImagery via a tile URL)
  - geopandas / shapely (optional, if useful)
  - opencv-python (cv2) for video handling
  - librosa or pydub for audio-based clap detection (from the video audio track)
  - scikit-learn (optional, for anomaly detection / clustering of "weird" segments)
- The project must run from the command line, e.g.:
  `python -m walkability_analyzer --data-root ./data --output-root ./output`
- Organize code as a package, e.g.:

  walkability_analyzer/
    __init__.py
    cli.py              # argument parsing / main entry
    config.py           # paths, constants, thresholds
    io_utils.py         # loading CSVs, descriptions, etc.
    sensor_processing/
        __init__.py
        preprocessing.py
        segmentation.py
        features.py
        anomalies.py
    video_processing/
        __init__.py
        sync.py         # audio-based clap detection + time alignment with sensors
        analysis.py      # crowding, crossings, light/shade heuristics
    visualization/
        __init__.py
        timeseries.py
        mapping.py
        reporting.py
    scoring/
        __init__.py
        walkability.py  # walkability index logic (see details below)

- Provide docstrings and type hints for public functions.
- Where logic is non-trivial, add short comments explaining what you do.

==================================================
DATA ORGANIZATION
==================================================
Assume the following directory structure (make it configurable):

data_root/
  route_01/
    sensors_run1.csv
    sensors_run2.csv        # (optional, 0..N sensor files per route)
    description.txt         # short free-text description of what happened on that route
    video.mp4               # (optional) GoPro or other video recording
  route_02/
    sensors_run1.csv
    description.txt
    # ...

Make the following assumptions about sensor CSV files, but keep it configurable:
- There is a timestamp column (e.g. "timestamp" in seconds or ISO string).
- There are accelerometer columns: accel_x, accel_y, accel_z (device frame).
- There may be gyroscope columns: gyro_x, gyro_y, gyro_z.
- There may be orientation columns (quaternion or Euler).
- There are GPS columns: latitude, longitude (and optionally altitude).
- Implement a simple configuration / detection logic so the code can adapt to different column names if needed (e.g. via a YAML/JSON config or simple mapping dictionary).

Implement a helper function:
  load_route(route_path: Path) -> RouteData
Where RouteData is a dataclass containing:
  - route_id (str)
  - list of SensorRecording objects
  - optional description text
  - optional video file path

SensorRecording dataclass:
  - recording_id (str)
  - df: pandas.DataFrame         # cleaned and time-indexed
  - sampling_rate (float)
  - metadata (dict)

==================================================
SENSOR PROCESSING (IMU + GPS)
==================================================

Goal: For each sensor recording:
1) Clean and synchronize data.
2) Detect the stomp at the beginning and end of the walking segment.
3) Extract the "active walking" segment.
4) Compute basic per-step and per-route metrics.
5) Detect "weird" segments (stops, sudden changes).
6) Prepare data for visualization and scoring.

Details:

1) Preprocessing
- Implement functions to:
  - Parse timestamps and set a proper datetime or float time index (seconds from start).
  - Handle missing values (simple interpolation or dropping, as appropriate).
  - Compute acceleration magnitude: acc_mag = sqrt(ax^2 + ay^2 + az^2).
  - If GPS is available, create a GeoDataFrame with (lat, lon) points for the recording.

2) Detect stomp-based start/end
- At the beginning and the end of each route, the participant performs a strong stomp on the foot that carries the phone.
- Implement a simple algorithm:
  - Use acceleration magnitude (possibly high-pass filtered).
  - Detect strong peaks above a dynamic threshold (e.g. mean + N * std).
  - Search for the first strong peak within the initial few seconds → start stomp.
  - Search for the last strong peak within the last seconds → end stomp.
  - Validate that start < end and produce warnings if detection fails.
- Return:
  - t_start_stomp, t_end_stomp (in seconds or timestamps)
  - A boolean mask or index range for the active walking segment.

3) Walking segment and gait cycles
- Extract the walking segment between t_start_stomp and t_end_stomp.
- Within this segment, detect steps:
  - Use a peak-detection on vertical acceleration (or acc magnitude) as a first approximation.
  - Compute step times and step frequency (cadence).
- Compute approximate step length and speed:
  - If GPS is available, compute distance between consecutive GPS points using haversine.
  - Option 1: Derive mean speed (total distance / walking time) and estimate step length = total distance / number_of_steps.
  - Option 2 (optional): use a simple regression of step frequency and acceleration amplitude to estimate speed (keep this part simple and transparent).

4) Detect "weird" segments
- A "weird" segment may include:
  - Stops or pauses (speed near zero, very low acceleration variance).
  - Changes in walking pattern (sudden change in speed, turning, high jerk).
- Implement anomaly detection with simple heuristics:
  - Compute a sliding-window average speed and acceleration variance.
  - Mark windows where:
    - speed < threshold_stop for longer than X seconds → "stop"
    - |d(speed)/dt| > threshold_jump or acceleration variance changes abruptly → "change in walking".
- Optionally use a simple clustering (e.g. KMeans on features [speed, acc_var]) to mark unusual clusters as "weird".

- Return:
  - A list of SegmentAnnotations with:
      - segment_type (e.g. "stop", "change", "normal")
      - start_time, end_time
      - optional label string
  - These annotations will be displayed on the time-series plot and on the map.

5) Metrics per recording and per route
For each recording, compute:
- total_walking_time (seconds)
- total_distance (meters, if GPS exists; else None)
- mean_speed (m/s or km/h)
- median_step_length (m) and standard deviation (if steps detected)
- mean_cadence (steps/min)
- number_of_stops
- fraction_of_time_stopped
- any additional simple metrics you find meaningful.

Aggregate per-route (if multiple recordings per route) into a RouteMetrics dataclass.

==================================================
VISUALIZATION (GRAPH + MAP + TEXT)
==================================================

General idea:
- For each sensor recording, create one "window" (e.g. one HTML report or one figure) with:
  - Top: time-series plot ("walking profile").
  - Bottom: interactive map with the route and markers for weird segments.
  - Above: title with the recording ID and route ID.
  - Side or below: text summary with computed metrics.

Implementation details:

1) Time-series plot
- Use matplotlib.
- For the walking segment, plot:
  - speed vs. time (if GPS available; else acceleration magnitude)
  - optionally, vertical acceleration or step events as markers.
- Overlay vertical colored bands or markers for "weird segments":
  - "stop" segments in one color
  - "change in walking" in another.
- Mark the stomp start/end as vertical lines.
- Include legend, axis labels, and clear title.

2) Map (satellite / imagery)
- Use folium to build an interactive map:
  - Center the map on the mean latitude/longitude of the route.
  - Use a satellite/imagery tile provider, e.g.:
    folium.TileLayer(
        tiles='https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri World Imagery'
    ).add_to(map)
- Draw the route as a polyline.
- For each "weird segment":
  - Place a marker at the median GPS location of that segment.
  - The popup should show the segment type and start/end times.

3) Report generation
- For each route and recording, generate an HTML report file, e.g.:
  output_root/
    route_01/
      sensors_run1_report.html
- You can embed:
  - A static image of the matplotlib plot (saved as PNG).
  - The folium map (as an iframe or directly saved into the HTML).

Implement helper functions:
- create_time_series_plot(recording, annotations, output_path)
- create_route_map(recording, annotations, output_path)
- create_html_report(route_data, recording, metrics, annotations, plot_path, map_path, output_html_path)

==================================================
VIDEO PROCESSING (OPTIONAL PER ROUTE)
==================================================

If a video file exists for a route (e.g., video.mp4):

Goals:
1) Load the video and extract the audio.
2) Detect the clap at the beginning and the clap at the end of the walking segment from the audio signal.
3) Synchronize the video time axis with the sensor time axis.
4) Analyze a few simple interesting properties from the video:
   - Rough crowding level (e.g., number of detected moving objects / people).
   - Presence of marked crosswalks.
   - Light vs. shadow segments (brightness).
5) Attach these annotations to the same time axis used for the sensor data and show them on the map.

Keep this part as a FIRST WORKING VERSION, not perfect research-grade:

1) Clap detection (audio-based)
- Use librosa or pydub to load the audio track from the video.
- Convert to mono.
- Compute the short-time energy of the signal.
- Detect large peaks above a high threshold as candidate claps.
- Assume:
  - The first high-energy peak near the beginning is the start clap.
  - The last high-energy peak near the end is the end clap.
- Return t_clap_start_video, t_clap_end_video in seconds (video time).

2) Sensor-video synchronization
- The sensor stomp start/end times (t_stomp_start, t_stomp_end) are in sensor time.
- The video clap start/end times (t_clap_start_video, t_clap_end_video) are in video time.
- Compute a linear time-alignment:
  - Assume t_sensor = a * t_video + b
  - Solve for a, b using two pairs: (t_clap_start_video -> t_stomp_start) and (t_clap_end_video -> t_stomp_end).
- Implement a small helper:
  class TimeSync:
      def __init__(self, a: float, b: float): ...
      def video_to_sensor(self, t_video: float) -> float: ...
      def sensor_to_video(self, t_sensor: float) -> float: ...
- This allows mapping any video frame time to the sensor timeline.

3) Simple video analysis heuristics
- Implement a very simple first-pass analysis:
  - Crowd level:
    - Use frame sampling (e.g., every 0.5–1.0s).
    - Use background subtraction or simple motion detection to estimate how many moving blobs exist.
    - Categorize into LOW / MEDIUM / HIGH crowding per time window.
  - Crosswalk detection:
    - Optional: use simple color/edge heuristics to detect zebra-style crosswalk (white stripes).
    - Or leave a TODO with a placeholder, but define the interface.
  - Light vs. shade:
    - Compute average brightness of the frame.
    - Label windows as BRIGHT / SHADED / DARK based on thresholds.

- Produce a list of VideoAnnotations with:
  - annotation_type (e.g. "crowd_high", "crosswalk", "shade")
  - t_start_sensor, t_end_sensor (converted using the TimeSync model)
  - optional extra info (e.g. crowd_level score).

4) Integration with map and report
- On the folium map, optionally:
  - Add markers or colored segments for high-crowding areas.
  - Add markers for crosswalks.
  - Use different icon colors to differentiate video-derived annotations from sensor-derived ones.

- In the report, include a short table summarizing:
  - Max/mean crowd level along the route.
  - Occurrences of crosswalks.
  - Distribution of light/shade along the route.

==================================================
WALKABILITY SCORING (FIRST VERSION)
==================================================

Implement a "WalkabilityScore" module that computes a numeric score per route, based on both sensor and (if available) video data.

Design a simple, transparent scoring function like this:

Inputs (per route):
- avg_speed: average walking speed (m/s)
- speed_variability: std of speed
- stop_ratio: fraction of time spent stopped
- num_stops_per_km
- step_length_mean, step_length_std
- crowding_index: e.g. 0–1, from video analysis (0 = empty, 1 = very crowded)
- shade_ratio: fraction of route in shade (from light/shade detection)
- crosswalk_count_per_km
- surface_quality_proxy: OPTIONAL, can be approximated by acceleration variance at low speeds to indicate uneven surface.

For now, implement a simple weighted sum:
  walkability = w_speed * normalized_speed
              + w_variability * (1 - normalized_speed_variability)
              + w_stops * (1 - normalized_stop_ratio)
              + w_crowd * (1 - normalized_crowding)
              + w_shade * normalized_shade_ratio
              + w_crosswalk * normalized_crosswalk_density
              + w_surface * (1 - normalized_surface_roughness)

Where:
- All sub-indicators are normalized to [0, 1] using reasonable min/max values.
- Higher walkability score = more comfortable, less disturbed, better shaded, safer feeling.
- For now, choose reasonable default weights (document them in code and make them configurable).

Output:
- A WalkabilityResult dataclass per route:
  - score (float)
  - breakdown (dict from component_name to partial_score)
  - raw_indicators (dict from indicator_name to raw_value)

==================================================
CLI AND OUTPUT
==================================================

Implement a CLI (`cli.py`) that:

- Accepts arguments:
  - --data-root PATH
  - --output-root PATH
  - optional flags: --process-video, --no-video, --config PATH, etc.
- For each route directory inside data_root:
  - Load route data.
  - For each sensor CSV:
    - Preprocess, detect stomps, extract walking segment.
    - Compute metrics and weird segments.
    - If video exists and --process-video:
      - Analyze video, sync with sensor, compute video-based annotations.
    - Create plot, map, and HTML report.
  - Aggregate metrics per route.
  - Compute the Walkability score per route.
  - Save a summary CSV at:
    output_root/routes_summary.csv
    with columns like:
      route_id, num_recordings, total_distance, avg_speed, walkability_score, etc.

==================================================
GENERAL CODING STYLE
==================================================

- Prefer small, testable functions.
- Use dataclasses for structured objects (RouteData, SensorRecording, RouteMetrics, WalkabilityResult, SegmentAnnotation, VideoAnnotation, etc.).
- Do not hard-code absolute paths; always use arguments or configuration.
- Be explicit about units (seconds, meters, etc.) in comments and docstrings.
- Add TODO comments where the implementation is coarse and could be improved (e.g., video crowding estimation, crosswalk detection, surface roughness).
- Make sure the code runs without crashing even if some data is missing (e.g., no GPS, no video). In such cases, degrade gracefully and skip the relevant features.

Now, implement this project step by step. Start by scaffolding the package structure and the main CLI, then fill in the modules in a sensible order (I/O, sensor preprocessing, segmentation, visualization, scoring, video).
