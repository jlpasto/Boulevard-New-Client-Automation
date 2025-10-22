# Boulevard New Client Automation

Automated system for logging into Boulevard dashboard and processing client orders from GoHighLevel webhooks.

## Features

- Automated login to Boulevard dashboard
- Client record creation and verification
- Google Sheets integration for order tracking
- Comprehensive logging system
- FastAPI webhook endpoint for GoHighLevel integration
- Background task processing

## Prerequisites

- Python 3.8 or higher
- Google Cloud Service Account with Sheets API enabled
- Boulevard account credentials
- GoHighLevel webhook setup

## Installation

1. Clone or navigate to the project directory:
```bash
cd "Boulevard New Client Automation"
```

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

4. Create a `.env` file by copying the example:
```bash
copy .env.example .env
```

5. Edit the `.env` file with your credentials:
   - `BLVD_EMAIL`: Your Boulevard email
   - `BLVD_PASSWORD`: Your Boulevard password
   - `GOOGLE_CREDENTIALS_B64`: Base64-encoded Google Service Account JSON
   - `SPREADSHEET_ID`: Your Google Sheets spreadsheet ID

## Configuration

### Google Sheets Setup

1. Create a Google Cloud Service Account
2. Enable Google Sheets API
3. Download the service account JSON file
4. Encode it to Base64:
```bash
# On Windows (PowerShell):
[Convert]::ToBase64String([System.IO.File]::ReadAllBytes("path\to\credentials.json"))

# On Linux/Mac:
base64 -i credentials.json
```
5. Add the Base64 string to your `.env` file

### Google Sheets Format

Your spreadsheet should have the following columns:
1. Contact ID
2. First Name
3. Email
4. Phone
5. Full Address
6. Transaction ID
7. Payment Status
8. Product Title
9. Subtotal
10. Total Amount
11. Gateway
12. Card Brand
13. Card Last 4
14. Currency Code
15. Created On
16. Status (pending/completed/failed)
17. Timestamp

## Usage

### Running the API Server

Start the FastAPI server:
```bash
python app.py
```

Or using uvicorn directly:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`

### API Endpoints

- `GET /` - Root endpoint (health check)
- `GET /health` - Health check with system status
- `POST /webhook/ghl-order` - Webhook endpoint for GoHighLevel orders

### GoHighLevel Webhook Setup

Configure your GoHighLevel webhook to send POST requests to:
```
http://your-server-address:8000/webhook/ghl-order
```

## Logging

The application logs to both:
- Console output
- `boulevard_automation.log` file

Log levels:
- INFO: General operations and status updates
- WARNING: Non-critical issues
- ERROR: Critical errors with stack traces

### Log Examples

```
2025-10-22 10:30:45 - __main__ - INFO - Starting Boulevard automation...
2025-10-22 10:30:46 - __main__ - INFO - Launching browser...
2025-10-22 10:30:50 - __main__ - INFO - Login form detected. Performing login...
2025-10-22 10:31:00 - __main__ - INFO - Successfully logged in to Boulevard
2025-10-22 10:31:05 - __main__ - INFO - Client found: John Doe
2025-10-22 10:31:10 - __main__ - INFO - Boulevard automation completed successfully
```

## Project Structure

```
Boulevard New Client Automation/
├── app.py                      # Main application file
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (not in repo)
├── .env.example               # Environment variables template
├── README.md                  # This file
├── session.json               # Saved browser session (auto-generated)
└── boulevard_automation.log   # Application logs (auto-generated)
```

## Key Functions

### `login(context, page)`
Performs login to Boulevard dashboard and saves session state.

### `check_client_record(page, name)`
Searches for a client by name and returns whether they exist.

### `create_client_record(page, client)`
Creates a new client record in Boulevard with provided information.

### `run_playwright(payload)`
Main automation function that:
1. Launches browser
2. Logs into Boulevard
3. Searches for client
4. Creates client if needed
5. Updates Google Sheets status

## Error Handling

The application includes comprehensive error handling:
- Failed logins are logged with appropriate error messages
- Google Sheets errors are caught and logged
- Browser automation errors update the order status to "failed"
- All exceptions include stack traces in logs

## Security Notes

- Never commit your `.env` file to version control
- Keep your service account credentials secure
- Use environment variables for all sensitive data
- Regularly rotate your passwords and API keys

## Troubleshooting

### Browser doesn't launch
```bash
playwright install chromium
```

### Google Sheets connection fails
- Verify your service account has access to the spreadsheet
- Check that the Base64 encoding is correct (no line breaks)
- Ensure Google Sheets API is enabled in your Google Cloud project

### Login fails
- Verify Boulevard credentials in `.env`
- Check if Boulevard requires 2FA (not currently supported)
- Review logs for specific error messages

## Development

To run in development mode with auto-reload:
```bash
uvicorn app:app --reload --log-level debug
```

## License

Proprietary - All rights reserved

## Support

For issues or questions, please contact the development team.
