# Google Sheets Integration Setup Guide

This guide will help you set up Google Sheets integration for the Boulevard automation script.

## Prerequisites

1. A Google Cloud Project
2. A Google Sheet where you want to append data
3. Python packages installed (run `pip install -r requirements.txt`)

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Note down your project name

## Step 2: Enable Google Sheets API

1. In your Google Cloud Project, go to "APIs & Services" > "Library"
2. Search for "Google Sheets API"
3. Click "Enable"
4. Also enable "Google Drive API"

## Step 3: Create Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Enter a name (e.g., "boulevard-automation")
4. Click "Create and Continue"
5. Skip the optional permissions (click "Continue")
6. Click "Done"

## Step 4: Create Service Account Key

1. Click on the service account you just created
2. Go to the "Keys" tab
3. Click "Add Key" > "Create New Key"
4. Choose "JSON" format
5. Click "Create"
6. A JSON file will be downloaded - **keep this file secure!**

## Step 5: Encode Credentials to Base64

The credentials need to be base64 encoded to store in the `.env` file.

### On Windows (PowerShell):
```powershell
$jsonContent = Get-Content -Path "path\to\your\credentials.json" -Raw
$bytes = [System.Text.Encoding]::UTF8.GetBytes($jsonContent)
$base64 = [Convert]::ToBase64String($bytes)
$base64 | Out-File -FilePath "credentials_base64.txt" -NoNewline
```

### On Mac/Linux:
```bash
base64 -i path/to/your/credentials.json > credentials_base64.txt
```

### Using Python:
```python
import base64

with open('path/to/your/credentials.json', 'r') as f:
    json_content = f.read()

base64_encoded = base64.b64encode(json_content.encode()).decode()
print(base64_encoded)
```

## Step 6: Create/Find Your Google Sheet

1. Create a new Google Sheet or use an existing one
2. Copy the Spreadsheet ID from the URL:
   - URL format: `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`
   - Example: If URL is `https://docs.google.com/spreadsheets/d/1AbC123-xYz/edit`
   - Then SPREADSHEET_ID is: `1AbC123-xYz`

## Step 7: Share Sheet with Service Account

1. Open your Google Sheet
2. Click "Share" button
3. Add the service account email (found in the JSON file as `client_email`)
   - It looks like: `boulevard-automation@your-project.iam.gserviceaccount.com`
4. Give it "Editor" permissions
5. Click "Share"

## Step 8: Configure Environment Variables

1. Open your `.env` file
2. Add the following variables:

```env
# Google Sheets Credentials (Base64 encoded service account JSON)
GOOGLE_CREDENTIALS_B64=<paste your base64 encoded credentials here>

# Google Sheets ID
SPREADSHEET_ID=<paste your spreadsheet ID here>
```

## Step 9: Test the Integration

Run the script and it should:
1. Create sheets named "October", "November", "December" if they don't exist
2. Add headers in Title Case if they don't exist
3. Append data to the sheet corresponding to yesterday's month

## How It Works

- **Monthly Sheets**: The script creates and uses separate sheets for October, November, and December
- **Dynamic Sheet Selection**: Data is appended to the sheet corresponding to yesterday's date
  - If today is November 1, data goes to October sheet (for October 31 data)
  - If today is November 15, data goes to November sheet (for November 14 data)
- **Headers**: Field names are converted from `snake_case` to `Title Case`
  - Example: `client_name` → `Client Name`
  - Example: `next_appointment_date` → `Next Appointment Date`
- **Automatic Creation**: Missing sheets and headers are created automatically

## Troubleshooting

### "Permission denied" error
- Make sure you shared the sheet with the service account email
- Check that the service account has Editor permissions

### "Credentials invalid" error
- Verify the base64 encoding is correct (no extra spaces or line breaks)
- Make sure the JSON file was downloaded correctly from Google Cloud

### "Spreadsheet not found" error
- Double-check the SPREADSHEET_ID in your .env file
- Ensure the sheet is shared with the service account

### "API not enabled" error
- Go to Google Cloud Console and enable both:
  - Google Sheets API
  - Google Drive API

## Security Notes

- **Never commit** your credentials JSON file or .env file to version control
- Keep your service account key secure
- The `.gitignore` file should include `.env` and `*.json` to prevent accidental commits
- Rotate service account keys periodically for security

## Column Order in Google Sheets

The columns will appear in this order:
1. Number
2. New Client Daily Count
3. Appointment Date
4. Next Appointment Date
5. Client Name
6. Phone Number
7. Service Name
8. Price
9. Membership
10. Visit
11. Booked Date
12. Front Desk
13. Provider Name
14. Date Treatment Plan Set
15. Photos
16. Charting
17. Occupation
18. Referral Source
19. Referral Source 2
20. Referral Name
21. Form Compliance
22. Interest 1 through Interest 10 (10 columns)
