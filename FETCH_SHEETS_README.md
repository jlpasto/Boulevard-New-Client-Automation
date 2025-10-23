# Fetch Data from Google Sheets

This script fetches data from Google Sheets and exports it to a JSON file.

## Purpose

The `fetch_from_sheets.py` script allows you to:
- Read data from any sheet in your Google Spreadsheet
- Convert the data to JSON format
- Save it to a local file
- Use the data for analysis, reporting, or other purposes

## Prerequisites

1. Google Sheets credentials configured (same as main app)
2. Python packages installed: `pip install -r requirements.txt`
3. `.env` file with `GOOGLE_CREDENTIALS_B64` and `SPREADSHEET_ID`

## Usage

### Basic Usage (Fetch October Sheet)

```bash
python fetch_from_sheets.py
```

This will:
- Fetch data from the "October" sheet
- Save to `october_data.json`

### Fetch Specific Sheet

```bash
python fetch_from_sheets.py November
```

This will:
- Fetch data from the "November" sheet
- Save to `november_data.json`

### Custom Output Filename

```bash
python fetch_from_sheets.py October my_custom_file.json
```

This will:
- Fetch data from the "October" sheet
- Save to `my_custom_file.json`

## How It Works

1. **Authentication**: Uses the same base64 credentials from your `.env` file
2. **Read-Only Access**: Uses read-only scopes for security
3. **Header Conversion**: Converts "Title Case" headers back to "snake_case"
   - "Client Name" → `client_name`
   - "Phone Number" → `phone_number`
4. **Type Conversion**: Automatically converts numeric strings to numbers
5. **Empty Row Handling**: Skips completely empty rows
6. **JSON Output**: Creates formatted, readable JSON with proper indentation

## Output Format

The JSON file will contain an array of objects, where each object represents one row:

```json
[
  {
    "number": 1,
    "new_client_daily_count": "",
    "appointment_date": "10/15/2024",
    "next_appointment_date": "11/18/2024",
    "client_name": "John Doe",
    "phone_number": "555-1234",
    "service_name": "Initial Consultation",
    "price": 150.00,
    "membership": "10/01/2024",
    "visit": 1,
    "booked_date": "10/14/2024",
    "front_desk": "Jane Smith",
    "provider_name": "Dr. Anderson",
    "date_treatment_plan_set": "",
    "photos": "Yes",
    "charting": "Yes",
    "occupation": "Software Engineer",
    "referral_source": "Google",
    "referral_source_2": "N/A",
    "referral_name": "",
    "form_compliance": "Completed",
    "interest_1": "Wellness",
    "interest_2": "Sports",
    "interest_3": "",
    ...
  },
  {
    "number": 2,
    ...
  }
]
```

## Logging

The script creates two types of logs:
1. **Console output**: Real-time progress
2. **Log file**: `fetch_sheets.log` - Detailed logs for troubleshooting

## Example Log Output

```
2024-10-23 10:30:15 - __main__ - INFO - ============================================================
2024-10-23 10:30:15 - __main__ - INFO - Fetching data from Google Sheets: October
2024-10-23 10:30:15 - __main__ - INFO - ============================================================
2024-10-23 10:30:15 - __main__ - INFO - Successfully decoded Google credentials
2024-10-23 10:30:16 - __main__ - INFO - Successfully authorized with Google Sheets API
2024-10-23 10:30:16 - __main__ - INFO - Successfully opened spreadsheet: Boulevard Client Data
2024-10-23 10:30:16 - __main__ - INFO - Successfully accessed worksheet: October
2024-10-23 10:30:17 - __main__ - INFO - Found 45 rows (including header)
2024-10-23 10:30:17 - __main__ - INFO - Converted 44 data rows to dictionary format
2024-10-23 10:30:17 - __main__ - INFO - Successfully saved data to: october_data.json
2024-10-23 10:30:17 - __main__ - INFO - ============================================================
2024-10-23 10:30:17 - __main__ - INFO - SUMMARY: Fetched 44 records from 'October' sheet
2024-10-23 10:30:17 - __main__ - INFO - ============================================================
2024-10-23 10:30:17 - __main__ - INFO - ✓ Data fetch completed successfully!
```

## Customizing the Script

You can modify the `main()` function in the script to change defaults:

```python
def main():
    # Customize these:
    sheet_name = "November"  # Change to any sheet name
    output_file = "my_data.json"  # Change output filename

    success = fetch_sheet_data(sheet_name, output_file)
    return success
```

## Use Cases

### 1. Backup Data
```bash
# Backup all monthly sheets
python fetch_from_sheets.py October october_backup.json
python fetch_from_sheets.py November november_backup.json
python fetch_from_sheets.py December december_backup.json
```

### 2. Data Analysis
```python
# Load the JSON file for analysis
import json

with open('october_data.json', 'r') as f:
    data = json.load(f)

# Analyze the data
total_clients = len(data)
completed_forms = sum(1 for record in data if record['form_compliance'] == 'Completed')
print(f"Total clients: {total_clients}")
print(f"Completed forms: {completed_forms}")
```

### 3. Generate Reports
```python
# Create a summary report
import json

with open('october_data.json', 'r') as f:
    data = json.load(f)

# Group by provider
from collections import defaultdict
by_provider = defaultdict(list)

for record in data:
    provider = record['provider_name']
    by_provider[provider].append(record)

for provider, clients in by_provider.items():
    print(f"{provider}: {len(clients)} clients")
```

## Troubleshooting

### "Worksheet not found" Error
- Check that the sheet name exists in your spreadsheet
- Sheet names are case-sensitive ("October" ≠ "october")
- Run the script to see available worksheets in the error message

### "Permission denied" Error
- Ensure your service account has access to the spreadsheet
- The script uses read-only permissions, so "Viewer" access is sufficient

### Empty Output File
- Check that the sheet has data
- Verify the sheet has a header row
- Check logs for empty row warnings

### Wrong Data Types
- The script auto-converts numeric strings to numbers
- To force text format, prefix numbers with an apostrophe in Google Sheets

## Security Notes

- Uses **read-only scopes** for safety
- Cannot modify or delete data from Google Sheets
- Same credentials as main app (no additional setup needed)

## Integration with Main App

This script is independent but uses the same configuration:
- Same `.env` file
- Same Google credentials
- Same spreadsheet

You can run this script anytime to export current data from Google Sheets without affecting the main automation workflow.
