from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv
import logging
import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('boulevard_automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Boulevard Configuration
LOGIN_URL = "https://dashboard.boulevard.io/login-v2"
CALENDAR_URL = "https://dashboard.boulevard.io/calendar"

EMAIL = os.getenv("BLVD_EMAIL")
PASSWORD = os.getenv("BLVD_PASSWORD")
SESSION_FILE = "session.json"

# Configuration constants
MAX_LOGIN_ATTEMPTS = 3
LOGIN_TIMEOUT = 30000  # 30 seconds
PAGE_LOAD_TIMEOUT = 15000  # 15 seconds


async def is_on_login_page(page: Page) -> bool:
    """
    Check if the current page is the login page.

    Args:
        page: Playwright page object

    Returns:
        True if on login page, False otherwise
    """
    try:
        current_url = page.url
        is_login = "login" in current_url.lower()
        has_login_form = await page.is_visible("input[name='email']", timeout=3000)
        return is_login or has_login_form
    except Exception:
        return False


async def verify_logged_in(page: Page) -> bool:
    """
    Verify if user is logged in by checking for authenticated page elements.

    Args:
        page: Playwright page object

    Returns:
        True if logged in, False otherwise
    """
    try:
        logger.info("Verifying login status...")
        # Check for elements that only appear when logged in
        is_visible = await page.is_visible("css=horizontal-menu", timeout=5000)
        logger.info(f"Login verification: {'Success' if is_visible else 'Failed'}")
        return is_visible
    except Exception as e:
        logger.warning(f"Login verification failed: {e}")
        return False


async def perform_login(context: BrowserContext, page: Page) -> bool:
    """
    Perform login to Boulevard dashboard.

    Args:
        context: Playwright browser context
        page: Playwright page object

    Returns:
        True if login successful, False otherwise
    """
    try:
        logger.info(f"Navigating to login page: {LOGIN_URL}")
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

        # Wait for login form to be visible
        logger.info("Waiting for login form to appear...")
        await page.wait_for_selector("input[name='email']", timeout=LOGIN_TIMEOUT)

        # Check if we're actually on the login page
        if not await is_on_login_page(page):
            logger.info("Not on login page, might already be logged in")
            return await verify_logged_in(page)

        logger.info("Filling in login credentials...")
        await page.fill("input[name='email']", EMAIL)
        await page.fill("input[name='password']", PASSWORD)

        logger.info("Submitting login form...")
        await page.click("button[type='submit']")

        # Wait for navigation after login
        logger.info("Waiting for login to complete...")
        try:
            await page.wait_for_selector("horizontal-menu", timeout=LOGIN_TIMEOUT)
        except PlaywrightTimeoutError:
            logger.warning("Timeout waiting for horizontal-menu, checking login status...")

        # Verify login was successful
        if await verify_logged_in(page):
            # Save session state
            await context.storage_state(path=SESSION_FILE)
            logger.info("Login successful, session saved.")
            return True
        else:
            logger.error("Login failed - unable to verify logged in state")
            return False

    except Exception as e:
        logger.error(f"Error during login: {e}", exc_info=True)
        return False


async def navigate_to_calendar_with_retry(context: BrowserContext, page: Page, max_attempts: int = MAX_LOGIN_ATTEMPTS) -> bool:
    """
    Navigate to calendar page with retry logic if redirected to login.

    Args:
        context: Playwright browser context
        page: Playwright page object
        max_attempts: Maximum number of login retry attempts

    Returns:
        True if successfully navigated to calendar, False otherwise
    """
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"Attempt {attempt}/{max_attempts}: Navigating to calendar page...")
            await page.goto(CALENDAR_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

            # Wait a moment for any redirects to occur
            await page.wait_for_timeout(2000)

            # Check if we got redirected to login
            if await is_on_login_page(page):
                logger.warning(f"Redirected to login page on attempt {attempt}")

                if attempt < max_attempts:
                    logger.info("Attempting to log in again...")
                    login_success = await perform_login(context, page)

                    if not login_success:
                        logger.error(f"Login failed on attempt {attempt}")
                        continue

                    # After successful login, try navigating to calendar again
                    logger.info("Retrying navigation to calendar after login...")
                    continue
                else:
                    logger.error("Max login attempts reached")
                    return False

            # Check if we're on the calendar page
            current_url = page.url
            if "calendar" in current_url.lower():
                logger.info("Successfully navigated to calendar page")

                # Wait for calendar to load
                logger.info("Waiting for calendar content to load...")
                try:
                    # Wait for calendar-specific elements to appear - "New Appointment" button
                    await page.wait_for_selector("button:has-text('New Appointment')", timeout=10000)
                    logger.info("Calendar page loaded successfully - 'New Appointment' button found")
                except PlaywrightTimeoutError:
                    logger.warning("'New Appointment' button not found, but URL is correct")

                # Save the rendered HTML for inspection
                try:
                    html_content = await page.content()
                    html_filename = "calendar_page.html"
                    with open(html_filename, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    logger.info(f"Calendar page HTML saved to {html_filename}")
                except Exception as e:
                    logger.warning(f"Failed to save HTML: {e}")

                return True
            else:
                logger.warning(f"Unexpected URL: {current_url}")
                if attempt < max_attempts:
                    continue
                return False

        except Exception as e:
            logger.error(f"Error navigating to calendar on attempt {attempt}: {e}", exc_info=True)
            if attempt < max_attempts:
                logger.info("Retrying...")
                await page.wait_for_timeout(2000)
                continue
            return False

    return False


async def fetch_calendar_events(
    page: Page,
    business_id: str,
    location_id: str,
    start_date: str,
    end_date: str,
    include_zero_minute: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Fetch calendar events from Boulevard API endpoint.

    Args:
        page: Playwright page object with active session
        business_id: Boulevard business ID
        location_id: Location ID to filter events
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        include_zero_minute: Include zero-minute appointments

    Returns:
        Dictionary containing calendar events data, or None if failed
    """
    try:
        logger.info("=" * 60)
        logger.info("Fetching calendar events via API endpoint...")
        logger.info(f"Business ID: {business_id}")
        logger.info(f"Location ID: {location_id}")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info("=" * 60)

        # Construct API URL
        api_url = (
            f"https://dashboard.boulevard.io/businesses/{business_id}/calendar_events"
            f"?start={start_date}"
            f"&end={end_date}"
            f"&location_id={location_id}"
            f"&include_zero_minute={'true' if include_zero_minute else 'false'}"
        )

        logger.info(f"API URL: {api_url}")

        # Make API request using Playwright's page context (inherits cookies/auth)
        response = await page.request.get(api_url)

        # Check response status
        if response.status != 200:
            logger.error(f"API request failed with status {response.status}")
            logger.error(f"Response: {await response.text()}")
            return None

        logger.info(f"API request successful (Status: {response.status})")

        # Parse JSON response
        data = await response.json()

        # Save raw response to file with consistent name
        response_filename = "calendar_events_response.json"

        with open(response_filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Raw API response saved to: {response_filename}")

        # Also save a timestamped backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"calendar_events_response_{timestamp}.json"

        with open(backup_filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Backup saved to: {backup_filename}")

        return data

    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}", exc_info=True)
        return None


def read_json_file(filename: str) -> Optional[Dict[str, Any]]:
    """
    Read JSON data from a file.

    Args:
        filename: Path to the JSON file

    Returns:
        Dictionary containing JSON data, or None if failed
    """
    try:
        logger.info(f"Reading JSON file: {filename}")
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Successfully loaded data from {filename}")
        return data
    except Exception as e:
        logger.error(f"Error reading JSON file {filename}: {e}", exc_info=True)
        return None


def filter_new_clients_from_raw(raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Filter raw calendar events data to return only those with is_new_client = True.
    Keeps ALL original fields from the API response.

    Args:
        raw_data: Raw calendar events data from API

    Returns:
        List of events where is_new_client is True (with all original fields)
    """
    try:
        logger.info("=" * 60)
        logger.info("Filtering for new client events from raw data...")
        logger.info("=" * 60)

        # Extract events from response
        # The structure may vary - handle different possible formats
        events = []

        if isinstance(raw_data, list):
            # API returned a list directly
            events = raw_data
        elif isinstance(raw_data, dict):
            # API returned a dictionary with events nested
            events = raw_data.get('events', raw_data.get('data', []))

        if not events:
            logger.warning("No events found in raw data")
            return []

        logger.info(f"Total events in raw data: {len(events)}")

        # Show first event structure for debugging
        if events:
            logger.debug(f"Sample event keys: {list(events[0].keys())}")
            logger.debug(f"Sample is_new_client value: {events[0].get('is_new_client', 'KEY NOT FOUND')}")

        # Filter events where is_new_client is True
        # Check both direct field and nested client.is_new_client
        new_client_events = []

        logger.info("Checking events for is_new_client field...")

        for idx, event in enumerate(events, 1):
            is_new_client = False

            # Check direct field first (this is the format from Boulevard API)
            is_new_client = event.get('is_new_client', False)

            # Also check nested client object if direct field is not present
            if not is_new_client:
                client_data = event.get('client', {})
                if isinstance(client_data, dict):
                    is_new_client = client_data.get('is_new_client', False)

            # Add to filtered list if is_new_client is True
            if is_new_client:
                new_client_events.append(event)  # Keep ALL original fields
                logger.debug(f"Event {idx}: Found new client - {event.get('title', 'N/A')}")

        logger.info(f"Found {len(new_client_events)} new client events out of {len(events)} total events")

        # Log details of new client events
        if new_client_events:
            logger.info("\nNew Client Events:")
            logger.info("-" * 60)
            for idx, event in enumerate(new_client_events, 1):
                # Try to extract basic info for logging
                client_name = "N/A"
                client_data = event.get('client', {})
                if isinstance(client_data, dict):
                    client_name = client_data.get('name', event.get('client_name', 'N/A'))
                else:
                    client_name = event.get('client_name', 'N/A')

                start_time = event.get('start_time', event.get('start', 'N/A'))
                service = event.get('service', event.get('service_name', 'N/A'))

                logger.info(f"{idx}. {client_name} - {start_time} - Service: {service}")
            logger.info("-" * 60)

            # Save new client events to separate file (with ALL original fields)
            new_clients_filename = "new_client_events.json"

            with open(new_clients_filename, 'w', encoding='utf-8') as f:
                json.dump(new_client_events, f, indent=2, ensure_ascii=False)

            logger.info(f"New client events saved to: {new_clients_filename}")

            # Also save a timestamped backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"new_client_events_{timestamp}.json"

            with open(backup_filename, 'w', encoding='utf-8') as f:
                json.dump(new_client_events, f, indent=2, ensure_ascii=False)

            logger.info(f"Backup saved to: {backup_filename}")
            logger.info(f"Files contain {len(new_client_events)} events with ALL original fields")
        else:
            logger.info("No new client events found in the date range")

        logger.info("=" * 60)

        return new_client_events

    except Exception as e:
        logger.error(f"Error filtering new client events: {e}", exc_info=True)
        return []


async def getAppointmentDetails(client_name: str, appointment_date: str) -> None:
    """
    Get appointment details for a specific client and date.

    Args:
        client_name: Name of the client
        appointment_date: Appointment date in MM/DD/YYYY format
    """
    logger.info(f"Called getAppointmentDetails for client: '{client_name}' on date: '{appointment_date}'")
    # TODO: Add appointment details retrieval logic here
    pass


async def extract_new_client_fields(new_client_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract specific fields from new client events with proper formatting.
    Calls getAppointmentDetails for each extracted record.

    Args:
        new_client_events: List of filtered new client events (with all original fields)

    Returns:
        List of dictionaries with only the requested fields:
        - appointment_id: from 'id'
        - client_name: from 'title'
        - appointment_date: from 'start' formatted as MM/DD/YYYY
        - service_name: from 'service.name'
        - price: from 'price'
        - client_id: from 'client_id'
        - staff_id: from 'staff_id'
        - recurring_appointment_id: from 'recurring_appointment_id'
    """
    try:
        logger.info("=" * 60)
        logger.info("Extracting specific fields from new client events...")
        logger.info("=" * 60)

        extracted_data = []

        for idx, event in enumerate(new_client_events, 1):
            try:
                # Extract and format the date from 'start' field
                start_date_str = event.get('start', '')
                appointment_date = 'N/A'

                if start_date_str:
                    try:
                        # Parse ISO 8601 date string (e.g., "2025-10-11T10:00:00-05:00")
                        # Remove timezone info for simpler parsing
                        date_part = start_date_str.split('T')[0] if 'T' in start_date_str else start_date_str
                        parsed_date = datetime.strptime(date_part, '%Y-%m-%d')
                        appointment_date = parsed_date.strftime('%m/%d/%Y')
                    except Exception as e:
                        logger.warning(f"Could not parse date '{start_date_str}': {e}")
                        # Try alternative parsing if the first method fails
                        try:
                            # Handle datetime with timezone
                            if '+' in start_date_str or start_date_str.endswith('Z'):
                                date_part = start_date_str.split('T')[0]
                                parsed_date = datetime.strptime(date_part, '%Y-%m-%d')
                                appointment_date = parsed_date.strftime('%m/%d/%Y')
                            else:
                                appointment_date = start_date_str
                        except:
                            appointment_date = start_date_str

                # Extract service name from nested 'service' object
                service_data = event.get('service', {})
                service_name = 'N/A'
                if isinstance(service_data, dict):
                    service_name = service_data.get('name', 'N/A')

                # Build the extracted record
                extracted_record = {
                    'appointment_id': event.get('id', 'N/A'),
                    'client_name': event.get('title', 'N/A'),
                    'appointment_date': appointment_date,
                    'service_name': service_name,
                    'price': event.get('price', 0.0),
                    'client_id': event.get('client_id', 'N/A'),
                    'staff_id': event.get('staff_id', 'N/A'),
                    'recurring_appointment_id': event.get('recurring_appointment_id', None)
                }

                extracted_data.append(extracted_record)

                logger.info(f"{idx}. {extracted_record['client_name']} - "
                          f"{extracted_record['appointment_date']} - "
                          f"{extracted_record['service_name']} - "
                          f"${extracted_record['price']}")

            except Exception as e:
                logger.warning(f"Error extracting fields from event {idx}: {e}")
                continue

        # Save extracted data to file
        extracted_filename = "new_client_events_extracted.json"

        with open(extracted_filename, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False)

        logger.info(f"\nExtracted data saved to: {extracted_filename}")

        # Also save timestamped backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"new_client_events_extracted_{timestamp}.json"

        with open(backup_filename, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Backup saved to: {backup_filename}")
        logger.info("=" * 60)
        logger.info(f"Successfully extracted {len(extracted_data)} new client records")
        logger.info("=" * 60)

        return extracted_data

    except Exception as e:
        logger.error(f"Error extracting new client fields: {e}", exc_info=True)
        return []


async def main():
    """
    Main function to perform login and navigate to calendar page.
    """
    if not EMAIL or not PASSWORD:
        logger.error("Boulevard credentials not set in environment variables")
        logger.error("Please set BLVD_EMAIL and BLVD_PASSWORD in your .env file")
        return

    logger.info("=" * 60)
    logger.info("Starting Boulevard login automation...")
    logger.info("=" * 60)

    try:
        async with async_playwright() as p:
            logger.info("Launching browser...")
            browser = await p.chromium.launch(
                headless=False,
                devtools=False,
                args=['--start-maximized']  # Start browser maximized
            )

            # Create context
            logger.info("Creating browser context...")
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )

            page = await context.new_page()

            # Perform initial login
            logger.info("Performing initial login...")
            login_success = await perform_login(context, page)

            if not login_success:
                logger.error("Initial login failed")
                await browser.close()
                return

            # Fetch calendar events using API endpoint
            # Configuration for API call
            BUSINESS_ID = "bbac5187-6f75-40d0-ae6e-97288b3b160b"
            LOCATION_ID = "6df4e391-8fe5-4262-adad-ac07ce221244"
            START_DATE = "2025-10-01"
            END_DATE = "2025-10-22"

            # Fetch events from API
            events_data = await fetch_calendar_events(
                page=page,
                business_id=BUSINESS_ID,
                location_id=LOCATION_ID,
                start_date=START_DATE,
                end_date=END_DATE,
                include_zero_minute=True
            )

            if events_data:
                logger.info("Calendar events fetched successfully!")

                # Filter for new client events directly from raw data (no processing)
                new_client_events = filter_new_clients_from_raw(events_data)

                if new_client_events:
                    logger.info(f"\n{'='*60}")
                    logger.info(f"SUMMARY: Found {len(new_client_events)} new client appointments")
                    logger.info(f"{'='*60}")

                    # Extract specific fields from new client events
                    extracted_data = extract_new_client_fields(new_client_events)

                    if extracted_data:
                        logger.info(f"\n{'='*60}")
                        logger.info(f"FINAL SUMMARY: Processed {len(extracted_data)} new client records")
                        logger.info(f"{'='*60}")
                        logger.info("\nGenerated files:")
                        logger.info("  Main files (always same name):")
                        logger.info("    - calendar_events_response.json (all raw events)")
                        logger.info("    - new_client_events.json (filtered new clients - full data)")
                        logger.info("    - new_client_events_extracted.json (SPECIFIC FIELDS ONLY)")
                        logger.info("  Backup files (timestamped):")
                        logger.info("    - calendar_events_response_YYYYMMDD_HHMMSS.json")
                        logger.info("    - new_client_events_YYYYMMDD_HHMMSS.json")
                        logger.info("    - new_client_events_extracted_YYYYMMDD_HHMMSS.json")
                        logger.info("\n  To re-process existing data, use:")
                        logger.info("    data = read_json_file('calendar_events_response.json')")
                        logger.info("    new_clients = filter_new_clients_from_raw(data)")
                        logger.info("    extracted = extract_new_client_fields(new_clients)")
                    else:
                        logger.warning("Failed to extract fields from new client events")
                else:
                    logger.info("\nNo new client events found in the specified date range")
            else:
                logger.error("Failed to fetch calendar events from API")

            # Keep browser open for 10 seconds to verify
            logger.info("Browser will stay open for 10 seconds...")
            await page.wait_for_timeout(10000)






            await browser.close()
            logger.info("Browser closed. Automation completed.")

    except Exception as e:
        logger.error(f"Critical error during automation: {e}", exc_info=True)


if __name__ == "__main__":
    print("=" * 60)
    print("Boulevard Login Automation - Starting...")
    print("=" * 60)
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nScript interrupted by user")
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
