"""
Fetch data from Google Sheets and export to JSON file.

This script reads data from the October sheet in Google Sheets
and saves it to a JSON file.
"""

import os
import json
import base64
import logging
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fetch_sheets.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Google Sheets Configuration
GOOGLE_CREDENTIALS_B64 = os.getenv("GOOGLE_CREDENTIALS_B64")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")


def fetch_sheet_data(sheet_name: str = "October", output_file: str = "october_data.json") -> bool:
    """
    Fetch data from specified Google Sheet and save to JSON file.

    Args:
        sheet_name: Name of the worksheet to fetch (default: "October")
        output_file: Name of the output JSON file (default: "october_data.json")

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("=" * 60)
        logger.info(f"Fetching data from Google Sheets: {sheet_name}")
        logger.info("=" * 60)

        # Check if credentials are set
        if not GOOGLE_CREDENTIALS_B64 or not SPREADSHEET_ID:
            logger.error("Google Sheets credentials not configured in .env file")
            logger.error("Please set GOOGLE_CREDENTIALS_B64 and SPREADSHEET_ID")
            return False

        # Decode base64 credentials
        try:
            credentials_json = base64.b64decode(GOOGLE_CREDENTIALS_B64).decode('utf-8')
            credentials_dict = json.loads(credentials_json)
            logger.info("Successfully decoded Google credentials")
        except Exception as e:
            logger.error(f"Error decoding Google credentials: {e}")
            return False

        # Set up Google Sheets authentication
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly'
        ]

        credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        logger.info("Successfully authorized with Google Sheets API")

        # Open the spreadsheet
        try:
            spreadsheet = gc.open_by_key(SPREADSHEET_ID)
            logger.info(f"Successfully opened spreadsheet: {spreadsheet.title}")
        except Exception as e:
            logger.error(f"Error opening spreadsheet: {e}")
            return False

        # Get the specified worksheet
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
            logger.info(f"Successfully accessed worksheet: {sheet_name}")
        except Exception as e:
            logger.error(f"Error accessing worksheet '{sheet_name}': {e}")
            logger.info(f"Available worksheets: {[ws.title for ws in spreadsheet.worksheets()]}")
            return False

        # Get all values from the worksheet
        all_values = worksheet.get_all_values()

        if not all_values:
            logger.warning(f"No data found in worksheet: {sheet_name}")
            return False

        logger.info(f"Found {len(all_values)} rows (including header)")

        # Extract headers (first row)
        headers = all_values[0]
        logger.info(f"Headers: {headers}")

        # Convert to list of dictionaries
        data = []
        for row_index, row in enumerate(all_values[1:], start=2):  # Skip header row
            if not any(row):  # Skip empty rows
                logger.debug(f"Skipping empty row {row_index}")
                continue

            # Create dictionary with headers as keys
            row_dict = {}
            for col_index, header in enumerate(headers):
                # Convert header from "Title Case" back to "snake_case"
                key = header.lower().replace(' ', '_')

                # Get value, handle rows with fewer columns than headers
                value = row[col_index] if col_index < len(row) else ''

                # Convert empty strings to appropriate types
                if value == '':
                    value = ''
                # Try to convert numbers
                elif value.replace('.', '').replace('-', '').isdigit():
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass

                row_dict[key] = value

            data.append(row_dict)

        logger.info(f"Converted {len(data)} data rows to dictionary format")

        # Save to JSON file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully saved data to: {output_file}")
        logger.info("=" * 60)
        logger.info(f"SUMMARY: Fetched {len(data)} records from '{sheet_name}' sheet")
        logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"Error fetching data from Google Sheets: {e}", exc_info=True)
        return False


def main():
    """
    Main function to fetch data from Google Sheets.
    """
    logger.info("Starting Google Sheets data fetch...")

    # You can customize these parameters:
    sheet_name = "October"  # Change to "November" or "December" as needed
    output_file = "october_data.json"  # Output filename

    success = fetch_sheet_data(sheet_name, output_file)

    if success:
        logger.info("✓ Data fetch completed successfully!")
    else:
        logger.error("✗ Data fetch failed. Check logs for details.")

    return success


if __name__ == "__main__":
    import sys

    # Allow command line arguments for sheet name and output file
    if len(sys.argv) > 1:
        sheet_name = sys.argv[1]
        output_file = f"{sheet_name.lower()}_data.json"

        if len(sys.argv) > 2:
            output_file = sys.argv[2]

        logger.info(f"Fetching from sheet: {sheet_name}")
        logger.info(f"Output file: {output_file}")

        success = fetch_sheet_data(sheet_name, output_file)
    else:
        success = main()

    sys.exit(0 if success else 1)
