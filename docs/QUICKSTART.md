# Quick Start Guide

## Installation

1. Create and activate virtual environment:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:
```powershell
pip install -r requirements.txt
```

## Running the Analyzer

### Test with Your Existing Data

Using your BG_20-10-25 dataset:

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output"
```

### Process a Specific Route

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output" --route Route1
```

### With Verbose Logging

```powershell
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output" --verbose
```

## Output Files

After running, check the `output/` directory:

- `Route1/` - Contains reports for Route1
  - `<recording>_report.html` - Main report (open in browser)
  - `<recording>_map.html` - Interactive map
  - `<recording>_plot.png` - Time series visualization
- `routes_summary.csv` - Summary of all routes

## Troubleshooting

### Module not found errors
Make sure you're in the project root directory and have activated the virtual environment.

### No routes found
Check that your CSV files are in the correct directory structure.

### Missing GPS data
The tool will still work with IMU data only, but some features will be limited.

## Next Steps

1. Review the generated HTML reports
2. Check the walkability scores in `routes_summary.csv`
3. Adjust parameters in `walkability_analyzer/config.py` if needed
4. Process additional routes

## Example with All Routes

```powershell
# Process all routes in BG dataset
python -m walkability_analyzer --data-root ".\test_records\BG_20-10-25" --output-root ".\output\bg_analysis"

# Process Tirat Carmel dataset  
python -m walkability_analyzer --data-root ".\test_records\Tirat Carmel" --output-root ".\output\tirat_analysis"
```
