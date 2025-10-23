from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv
import logging
import os
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from urllib.parse import quote
import gspread
from google.oauth2.service_account import Credentials

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

# Google Sheets Configuration
GOOGLE_CREDENTIALS_B64 = os.getenv("GOOGLE_CREDENTIALS_B64")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# Configuration constants
MAX_LOGIN_ATTEMPTS = 3
LOGIN_TIMEOUT = 30000  # 30 seconds
PAGE_LOAD_TIMEOUT = 15000  # 15 seconds

# Testing configuration
TEST_ENV = False  # Set to True to test with only 1 record, False for production


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
        logger.info(f"Received {len(data)} events from API")

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
            logger.info(f"Found {len(new_client_events)} new client events")
        else:
            logger.info("No new client events found in the date range")

        logger.info("=" * 60)

        return new_client_events

    except Exception as e:
        logger.error(f"Error filtering new client events: {e}", exc_info=True)
        return []


async def getAppointmentDetails(page: Page, client_name: str, appointment_date: str) -> Optional[Dict[str, Any]]:
    """
    Get appointment details for a specific client and date by navigating to sales orders page.

    Args:
        page: Playwright page object with active session
        client_name: Name of the client
        appointment_date: Appointment date in MM/DD/YYYY format

    Returns:
        Dictionary containing extracted details (phone_number, etc.), or None if failed
    """
    try:
        logger.info(f"Called getAppointmentDetails for client: '{client_name}' on date: '{appointment_date}'")

        # Convert appointment_date from MM/DD/YYYY to YYYY-MM-DD format
        try:
            date_obj = datetime.strptime(appointment_date, '%m/%d/%Y')
            formatted_date = date_obj.strftime('%Y-%m-%d')
            logger.info(f"Converted date from {appointment_date} to {formatted_date}")
        except Exception as e:
            logger.error(f"Failed to convert date format: {e}")
            formatted_date = appointment_date

        # URL encode the client name for safe URL formatting
        encoded_client_name = quote(client_name)

        # Construct the sales orders URL with the client name parameter
        sales_orders_url = f"https://dashboard.boulevard.io/sales/orders?clientName={encoded_client_name}&limit=100&page=1"

        logger.info(f"Navigating to: {sales_orders_url}")

        # Navigate to the sales orders page
        await page.goto(sales_orders_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)

        # Wait for the table to load
        await page.wait_for_timeout(3000)

        logger.info(f"Successfully navigated to sales orders page for client: '{client_name}'")

        # Find and click the row matching the appointment date
        logger.info(f"Looking for order row with date: {formatted_date}")

        # Wait for the table body to be visible
        await page.wait_for_selector('tbody[md-body]', timeout=10000)

        # Find all table rows
        rows = await page.query_selector_all('tr[md-row][ng-repeat*="order in"]')

        logger.info(f"Found {len(rows)} order rows")

        # Search for the row with matching date
        row_found = False
        for idx, row in enumerate(rows, 1):
            # Get all cells in the row
            cells = await row.query_selector_all('td[md-cell]')

            if len(cells) >= 2:
                # The date is in the second cell (index 1)
                date_cell = cells[1]
                date_text = await date_cell.inner_text()
                date_text = date_text.strip()

                logger.debug(f"Row {idx} date: '{date_text}'")

                if date_text == formatted_date:
                    logger.info(f"Found matching row with date: {formatted_date}")

                    # Click the row
                    await row.click()
                    logger.info(f"Clicked order row for date: {formatted_date}")

                    # Wait for navigation or modal to open
                    await page.wait_for_timeout(3000)

                    row_found = True
                    break

        if not row_found:
            logger.warning(f"No order row found with date: {formatted_date}")
            return None

        # Initialize details dictionary
        appointment_details = {}

        # Extract phone number from the opened order details
        logger.info("Extracting phone number from order details...")

        try:
            # Find the smartphone SVG icon
            phone_container = await page.query_selector('svg.smartphone_svg__feather-smartphone')

            if phone_container:
                # Navigate up to find the parent div that contains the phone number
                # The structure is: svg -> i.icon-container -> div.tw-flex -> div.tw-pl-4 -> span
                parent_div = await phone_container.evaluate_handle('el => el.closest("div.tw-flex")')

                if parent_div:
                    # Find the span containing the phone number within this parent div
                    phone_span = await parent_div.query_selector('div.tw-pl-4 span')

                    if phone_span:
                        phone_number = await phone_span.inner_text()
                        phone_number = phone_number.strip()
                        logger.info(f"Extracted phone number: {phone_number}")
                        appointment_details['phone_number'] = phone_number
                    else:
                        logger.warning("Phone span not found within parent div")
                        appointment_details['phone_number'] = 'N/A'
                else:
                    logger.warning("Parent div with tw-flex not found")
                    appointment_details['phone_number'] = 'N/A'
            else:
                logger.warning("Smartphone SVG icon not found on page")
                appointment_details['phone_number'] = 'N/A'

        except Exception as e:
            logger.error(f"Error extracting phone number: {e}", exc_info=True)
            appointment_details['phone_number'] = 'N/A'

        # Click the "View Appointment" button
        logger.info("Looking for 'View Appointment' button...")

        try:
            # Find the View Appointment button
            view_appointment_button = await page.query_selector('button.link-module_link__3ZzUy:has-text("View Appointment")')

            if view_appointment_button:
                logger.info("Found 'View Appointment' button, clicking...")
                await view_appointment_button.click()

                # Wait for the modal to open
                await page.wait_for_timeout(2000)
                logger.info("'View Appointment' modal should be open")

                # Extract "booked by" information from the modal
                logger.info("Extracting 'booked by' information from modal...")

                try:
                    # Find all span elements with class 'update-entry-actor'
                    actor_spans = await page.query_selector_all('span.update-entry-actor')

                    booked_by = 'N/A'
                    booked_date = 'N/A'

                    for span in actor_spans:
                        span_text = await span.inner_text()
                        span_text = span_text.strip()

                        # Check if the text contains "booked"
                        if 'booked' in span_text.lower():
                            logger.info(f"Found span with 'booked': {span_text}")

                            # Extract the text before "booked"
                            parts = span_text.split('booked')
                            if len(parts) > 0:
                                booked_by = parts[0].strip()
                                logger.info(f"Extracted booked_by: {booked_by}")
                                appointment_details['booked_by'] = booked_by

                            # Extract the text after "booked ·"
                            if len(parts) > 1:
                                # The second part contains " · Mon Oct 6 @ 3:48pm CDT"
                                after_booked = parts[1].strip()

                                # Remove the leading "·" if present
                                if after_booked.startswith('·'):
                                    after_booked = after_booked[1:].strip()

                                booked_date = after_booked
                                logger.info(f"Extracted booked_date: {booked_date}")
                                appointment_details['booked_date'] = booked_date

                            break

                    if booked_by == 'N/A':
                        logger.warning("No span element containing 'booked' found in modal")
                        appointment_details['booked_by'] = 'N/A'
                        appointment_details['booked_date'] = 'N/A'

                except Exception as e:
                    logger.error(f"Error extracting 'booked by' information: {e}", exc_info=True)
                    appointment_details['booked_by'] = 'N/A'
                    appointment_details['booked_date'] = 'N/A'

                # Extract provider name from services section
                logger.info("Extracting provider name from services section...")

                try:
                    # Find the services section
                    services_section = await page.query_selector('section.services')

                    if services_section:
                        # Find the first row in tbody
                        first_service_row = await services_section.query_selector('tbody tr[ng-repeat]')

                        if first_service_row:
                            # Find the employee cell (td.employee)
                            employee_cell = await first_service_row.query_selector('td.employee')

                            if employee_cell:
                                # Find the span containing the employee name
                                employee_span = await employee_cell.query_selector('span')

                                if employee_span:
                                    provider_name = await employee_span.inner_text()
                                    provider_name = provider_name.strip()
                                    logger.info(f"Extracted provider_name: {provider_name}")
                                    appointment_details['provider_name'] = provider_name
                                else:
                                    logger.warning("Employee span not found in employee cell")
                                    appointment_details['provider_name'] = 'N/A'
                            else:
                                logger.warning("Employee cell not found in first service row")
                                appointment_details['provider_name'] = 'N/A'
                        else:
                            logger.warning("First service row not found in services section")
                            appointment_details['provider_name'] = 'N/A'
                    else:
                        logger.warning("Services section not found in modal")
                        appointment_details['provider_name'] = 'N/A'

                except Exception as e:
                    logger.error(f"Error extracting provider name: {e}", exc_info=True)
                    appointment_details['provider_name'] = 'N/A'

                # Extract charting status from Charts section
                logger.info("Checking for completed charts in Charts section...")

                try:
                    # Step 1: Find the Charts heading span
                    charts_heading = await page.query_selector('span.MuiTypography-textParagraphLargeHeavy:has-text("Charts")')

                    if not charts_heading:
                        logger.warning("Charts heading not found")
                        appointment_details['hasCharting'] = False
                    else:
                        # Step 2: Get the parent container of the Charts heading
                        charts_parent = await charts_heading.query_selector('xpath=ancestor::div[contains(@class, "MuiBox-root")][1]')

                        if not charts_parent:
                            logger.warning("Charts parent container not found")
                            appointment_details['hasCharting'] = False
                        else:
                            # Step 3: Navigate to the grandparent to get access to sibling divs
                            charts_grandparent = await charts_parent.query_selector('xpath=..')

                            if not charts_grandparent:
                                logger.warning("Charts grandparent container not found")
                                appointment_details['hasCharting'] = False
                            else:
                                # Step 4: Find all divs with data-testid containing "form-list-item" within this section
                                chart_items = await charts_grandparent.query_selector_all('div[data-testid*="form-list-item"]')

                                logger.info(f"Found {len(chart_items)} chart item(s)")

                                has_completed = False

                                # Step 5: Check each chart item for "Completed" text
                                for item in chart_items:
                                    item_text = await item.text_content()
                                    if item_text and "Completed" in item_text:
                                        logger.info("Found completed chart")
                                        has_completed = True
                                        break

                                appointment_details['hasCharting'] = has_completed

                                if not has_completed:
                                    logger.info("No completed charts found")

                except Exception as e:
                    logger.error(f"Error extracting charting status: {e}", exc_info=True)
                    appointment_details['hasCharting'] = False

                # Extract New PT Intake Form completion status from Forms section
                logger.info("Checking for completed 'New PT Intake Form' in Forms section...")

                try:
                    # Step 1: Find the Forms heading span
                    forms_heading = await page.query_selector('span.MuiTypography-textParagraphLargeHeavy:has-text("Forms")')

                    if not forms_heading:
                        logger.warning("Forms heading not found")
                        appointment_details['hasCompletedPTIntakeForm'] = False
                    else:
                        # Step 2: Get the parent container of the Forms heading
                        forms_parent = await forms_heading.query_selector('xpath=ancestor::div[contains(@class, "MuiBox-root")][1]')

                        if not forms_parent:
                            logger.warning("Forms parent container not found")
                            appointment_details['hasCompletedPTIntakeForm'] = False
                        else:
                            # Step 3: Navigate to the grandparent to get access to sibling divs
                            forms_grandparent = await forms_parent.query_selector('xpath=..')

                            if not forms_grandparent:
                                logger.warning("Forms grandparent container not found")
                                appointment_details['hasCompletedPTIntakeForm'] = False
                            else:
                                # Step 4: Find all divs with data-testid containing "form-list-item" within this section
                                form_items = await forms_grandparent.query_selector_all('div[data-testid*="form-list-item"]')

                                logger.info(f"Found {len(form_items)} form item(s)")

                                has_completed_pt_intake = False

                                # Step 5: Check each form item for "New PT Intake Form" AND "Completed"
                                for item in form_items:
                                    item_text = await item.text_content()
                                    if item_text and "New PT Intake Form" in item_text and "Completed" in item_text:
                                        logger.info("Found completed 'New PT Intake Form'")
                                        has_completed_pt_intake = True
                                        break

                                appointment_details['hasCompletedPTIntakeForm'] = has_completed_pt_intake

                                if not has_completed_pt_intake:
                                    logger.info("'New PT Intake Form' is not completed or not found")
                                else:
                                    # Extract details from New PT Intake Form modal
                                    logger.info("Clicking on 'New PT Intake Form' to extract details...")

                                    try:
                                        # Find and click the New PT Intake Form item
                                        for item in form_items:
                                            item_text = await item.text_content()
                                            if item_text and "New PT Intake Form" in item_text and "Completed" in item_text:
                                                await item.click()
                                                logger.info("Clicked on 'New PT Intake Form'")

                                                # Wait for the modal to open
                                                await page.wait_for_timeout(2000)

                                                # Extract form fields
                                                pt_intake_details = {}

                                                # Extract Birthday
                                                try:
                                                    birthday_input = await page.query_selector('input[placeholder="MM/DD/YYYY"]')
                                                    if birthday_input:
                                                        birthday_value = await birthday_input.get_attribute('value')
                                                        pt_intake_details['birthday'] = birthday_value if birthday_value else 'N/A'
                                                        logger.info(f"Extracted birthday: {pt_intake_details['birthday']}")
                                                    else:
                                                        pt_intake_details['birthday'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting birthday: {e}", exc_info=True)
                                                    pt_intake_details['birthday'] = 'N/A'

                                                # Extract Home Address
                                                try:
                                                    address_label = await page.query_selector('label:has-text("Home address")')
                                                    if address_label:
                                                        label_for = await address_label.get_attribute('for')
                                                        if label_for:
                                                            address_textarea = await page.query_selector(f'textarea#{label_for}')
                                                            if address_textarea:
                                                                address_value = await address_textarea.input_value()
                                                                pt_intake_details['home_address'] = address_value if address_value else 'N/A'
                                                                logger.info(f"Extracted home address: {pt_intake_details['home_address']}")
                                                            else:
                                                                pt_intake_details['home_address'] = 'N/A'
                                                        else:
                                                            pt_intake_details['home_address'] = 'N/A'
                                                    else:
                                                        pt_intake_details['home_address'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting home address: {e}", exc_info=True)
                                                    pt_intake_details['home_address'] = 'N/A'

                                                # Extract Cell Phone
                                                try:
                                                    cell_phone_label = await page.query_selector('label:has-text("Cell Phone")')
                                                    if cell_phone_label:
                                                        label_for = await cell_phone_label.get_attribute('for')
                                                        if label_for:
                                                            cell_phone_input = await page.query_selector(f'input#{label_for}')
                                                            if cell_phone_input:
                                                                cell_phone_value = await cell_phone_input.get_attribute('value')
                                                                pt_intake_details['cell_phone'] = cell_phone_value if cell_phone_value else 'N/A'
                                                                logger.info(f"Extracted cell phone: {pt_intake_details['cell_phone']}")
                                                            else:
                                                                pt_intake_details['cell_phone'] = 'N/A'
                                                        else:
                                                            pt_intake_details['cell_phone'] = 'N/A'
                                                    else:
                                                        pt_intake_details['cell_phone'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting cell phone: {e}", exc_info=True)
                                                    pt_intake_details['cell_phone'] = 'N/A'

                                                # Extract Phone Carrier
                                                try:
                                                    carrier_label = await page.query_selector('label:has-text("Phone Carrier")')
                                                    if carrier_label:
                                                        label_for = await carrier_label.get_attribute('for')
                                                        if label_for:
                                                            carrier_input = await page.query_selector(f'input#{label_for}')
                                                            if carrier_input:
                                                                carrier_value = await carrier_input.get_attribute('value')
                                                                pt_intake_details['phone_carrier'] = carrier_value if carrier_value else 'N/A'
                                                                logger.info(f"Extracted phone carrier: {pt_intake_details['phone_carrier']}")
                                                            else:
                                                                pt_intake_details['phone_carrier'] = 'N/A'
                                                        else:
                                                            pt_intake_details['phone_carrier'] = 'N/A'
                                                    else:
                                                        pt_intake_details['phone_carrier'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting phone carrier: {e}", exc_info=True)
                                                    pt_intake_details['phone_carrier'] = 'N/A'

                                                # Extract Occupation
                                                try:
                                                    occupation_label = await page.query_selector('label:has-text("Occupation")')
                                                    if occupation_label:
                                                        label_for = await occupation_label.get_attribute('for')
                                                        if label_for:
                                                            occupation_input = await page.query_selector(f'input#{label_for}')
                                                            if occupation_input:
                                                                occupation_value = await occupation_input.get_attribute('value')
                                                                pt_intake_details['occupation'] = occupation_value if occupation_value else 'N/A'
                                                                logger.info(f"Extracted occupation: {pt_intake_details['occupation']}")
                                                            else:
                                                                pt_intake_details['occupation'] = 'N/A'
                                                        else:
                                                            pt_intake_details['occupation'] = 'N/A'
                                                    else:
                                                        pt_intake_details['occupation'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting occupation: {e}", exc_info=True)
                                                    pt_intake_details['occupation'] = 'N/A'

                                                # Extract Best Way To Contact (radio button)
                                                try:
                                                    contact_method_label = await page.query_selector('label:has-text("Best Way To Contact You")')
                                                    if contact_method_label:
                                                        # Find the checked radio button
                                                        checked_radio = await page.query_selector('input[type="radio"][name*="mui"]:checked')
                                                        if checked_radio:
                                                            # Get the parent label to find the text
                                                            parent_label = await checked_radio.query_selector('xpath=ancestor::label[1]')
                                                            if parent_label:
                                                                label_text = await parent_label.text_content()
                                                                # Extract just the contact method text
                                                                if 'Phone' in label_text:
                                                                    pt_intake_details['best_contact_method'] = 'Phone'
                                                                elif 'Text' in label_text:
                                                                    pt_intake_details['best_contact_method'] = 'Text'
                                                                elif 'Email' in label_text:
                                                                    pt_intake_details['best_contact_method'] = 'Email'
                                                                else:
                                                                    pt_intake_details['best_contact_method'] = 'N/A'
                                                                logger.info(f"Extracted best contact method: {pt_intake_details['best_contact_method']}")
                                                            else:
                                                                pt_intake_details['best_contact_method'] = 'N/A'
                                                        else:
                                                            pt_intake_details['best_contact_method'] = 'N/A'
                                                    else:
                                                        pt_intake_details['best_contact_method'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting best contact method: {e}", exc_info=True)
                                                    pt_intake_details['best_contact_method'] = 'N/A'

                                                # Extract Referral Choice (radio button)
                                                try:
                                                    referral_label = await page.query_selector('label:has-text("Referral Choice")')
                                                    if referral_label:
                                                        # Find parent container and then find checked radio within it
                                                        referral_container = await referral_label.query_selector('xpath=ancestor::div[contains(@class, "MuiFormControl-root")][1]')
                                                        if referral_container:
                                                            checked_referral = await referral_container.query_selector('input[type="radio"]:checked')
                                                            if checked_referral:
                                                                parent_label = await checked_referral.query_selector('xpath=ancestor::label[1]')
                                                                if parent_label:
                                                                    referral_text = await parent_label.text_content()
                                                                    # Clean up the text to extract just the referral source
                                                                    referral_text = referral_text.strip()
                                                                    pt_intake_details['referral_source'] = referral_text if referral_text else 'N/A'
                                                                    logger.info(f"Extracted referral source: {pt_intake_details['referral_source']}")
                                                                else:
                                                                    pt_intake_details['referral_source'] = 'N/A'
                                                            else:
                                                                pt_intake_details['referral_source'] = 'N/A'
                                                        else:
                                                            pt_intake_details['referral_source'] = 'N/A'
                                                    else:
                                                        pt_intake_details['referral_source'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting referral source: {e}", exc_info=True)
                                                    pt_intake_details['referral_source'] = 'N/A'

                                                # Extract Referral Name
                                                try:
                                                    referral_name_label = await page.query_selector('label:has-text("Name of referral")')
                                                    if referral_name_label:
                                                        label_for = await referral_name_label.get_attribute('for')
                                                        if label_for:
                                                            referral_name_input = await page.query_selector(f'input#{label_for}')
                                                            if referral_name_input:
                                                                referral_name_value = await referral_name_input.get_attribute('value')
                                                                pt_intake_details['referral_name'] = referral_name_value if referral_name_value else 'N/A'
                                                                logger.info(f"Extracted referral name: {pt_intake_details['referral_name']}")
                                                            else:
                                                                pt_intake_details['referral_name'] = 'N/A'
                                                        else:
                                                            pt_intake_details['referral_name'] = 'N/A'
                                                    else:
                                                        pt_intake_details['referral_name'] = 'N/A'
                                                except Exception as e:
                                                    logger.error(f"Error extracting referral name: {e}", exc_info=True)
                                                    pt_intake_details['referral_name'] = 'N/A'

                                                # Extract All Interests (checked checkboxes)
                                                try:
                                                    interests_label = await page.query_selector('label:has-text("All Interests")')
                                                    if interests_label:
                                                        # Find parent container
                                                        interests_container = await interests_label.query_selector('xpath=ancestor::div[contains(@class, "MuiFormControl-root")][1]')
                                                        if interests_container:
                                                            # Find all checked checkboxes within this container
                                                            checked_checkboxes = await interests_container.query_selector_all('input[type="checkbox"]:checked')

                                                            interests_list = []
                                                            for checkbox in checked_checkboxes:
                                                                # Get the parent label to find the interest text
                                                                parent_label = await checkbox.query_selector('xpath=ancestor::label[1]')
                                                                if parent_label:
                                                                    interest_text = await parent_label.text_content()
                                                                    # Clean up the text to extract just the interest name
                                                                    interest_text = interest_text.strip()
                                                                    if interest_text:
                                                                        interests_list.append(interest_text)

                                                            pt_intake_details['interests'] = interests_list if interests_list else []
                                                            logger.info(f"Extracted {len(interests_list)} interest(s): {interests_list}")
                                                        else:
                                                            pt_intake_details['interests'] = []
                                                    else:
                                                        pt_intake_details['interests'] = []
                                                except Exception as e:
                                                    logger.error(f"Error extracting interests: {e}", exc_info=True)
                                                    pt_intake_details['interests'] = []

                                                # Add PT Intake details to appointment_details
                                                appointment_details['pt_intake_form'] = pt_intake_details
                                                logger.info(f"Successfully extracted PT Intake Form details")

                                                # Close the modal by pressing Escape or clicking close button
                                                await page.keyboard.press('Escape')
                                                await page.wait_for_timeout(1000)

                                                break

                                    except Exception as e:
                                        logger.error(f"Error extracting PT Intake Form details: {e}", exc_info=True)
                                        appointment_details['pt_intake_form'] = {}

                except Exception as e:
                    logger.error(f"Error extracting PT Intake Form status: {e}", exc_info=True)
                    appointment_details['hasCompletedPTIntakeForm'] = False

            else:
                logger.warning("'View Appointment' button not found")

        except Exception as e:
            logger.error(f"Error clicking 'View Appointment' button: {e}", exc_info=True)

        return appointment_details

    except Exception as e:
        logger.error(f"Error in getAppointmentDetails for client '{client_name}': {e}", exc_info=True)
        return None


async def getMembershipInfo(page: Page, client_id: str) -> Dict[str, Any]:
    """
    Navigate to client's membership page and extract membership details.

    Args:
        page: Playwright page object
        client_id: The client ID to fetch membership info for

    Returns:
        Dictionary containing membership details (status, start_date, price)
    """
    membership_info = {
        'status': 'N/A',
        'start_date': 'N/A',
        'price': 'N/A'
    }

    try:
        logger.info(f"Fetching membership info for client_id: {client_id}")

        # Navigate to client's page
        client_url = f"https://dashboard.boulevard.io/clients/{client_id}"
        await page.goto(client_url)
        logger.info(f"Navigated to: {client_url}")

        # Wait for page to load (we're on Overview tab by default)
        await page.wait_for_timeout(2000)

        # Extract scheduled appointments first (we're already on Overview tab)
        logger.info("Extracting scheduled appointments from Overview tab...")
        scheduled_appointments = []

        try:
            # Check for scheduled appointments section
            scheduled_heading = await page.query_selector('h5.title:has-text("Scheduled Appointments")')

            if scheduled_heading:
                logger.info("Found Scheduled Appointments section")

                # Find all appointment rows in the table
                appointment_rows = await page.query_selector_all('tr[ng-repeat*="appointment"]')

                logger.info(f"Found {len(appointment_rows)} scheduled appointment(s)")

                for row in appointment_rows:
                    try:
                        appointment = {}

                        # Extract service name
                        service_name_div = await row.query_selector('div.service-name')
                        if service_name_div:
                            service_text = await service_name_div.text_content()
                            appointment['service'] = service_text.strip() if service_text else 'N/A'
                        else:
                            appointment['service'] = 'N/A'

                        # Extract date and time
                        date_div = await row.query_selector('div.date')
                        if date_div:
                            date_text = await date_div.text_content()
                            appointment['date_time'] = date_text.strip() if date_text else 'N/A'
                        else:
                            appointment['date_time'] = 'N/A'

                        scheduled_appointments.append(appointment)
                        logger.info(f"Extracted appointment: {appointment}")

                    except Exception as e:
                        logger.error(f"Error extracting individual appointment: {e}", exc_info=True)
                        continue

                membership_info['scheduled_appointments'] = scheduled_appointments
                logger.info(f"Successfully extracted {len(scheduled_appointments)} scheduled appointment(s)")
            else:
                logger.info("No Scheduled Appointments section found")
                membership_info['scheduled_appointments'] = []

        except Exception as e:
            logger.error(f"Error extracting scheduled appointments: {e}", exc_info=True)
            membership_info['scheduled_appointments'] = []

        # Now click on Memberships tab to extract membership details
        logger.info("Looking for Memberships tab...")
        memberships_tab = await page.query_selector('md-tab-item:has-text("Memberships")')

        if memberships_tab:
            await memberships_tab.click()
            logger.info("Clicked on Memberships tab")

            # Wait for membership content to load
            await page.wait_for_timeout(2000)

            # Look for Overview card to confirm there's membership data
            overview_card = await page.query_selector('span.MuiTypography-h5:has-text("Overview")')

            if not overview_card:
                logger.info("No membership Overview found - client may not have an active membership")
            else:
                logger.info("Found membership Overview section")

                # Extract Status
                try:
                    status_label = await page.query_selector('span.MuiTypography-textv2BodyHeavy:has-text("Status")')
                    if status_label:
                        # Find the parent container and then the status value
                        parent = await status_label.query_selector('xpath=ancestor::div[contains(@class, "MuiBox-root")][1]')
                        if parent:
                            status_value = await parent.query_selector('span.MuiTypography-textLabelSmallDefault')
                            if status_value:
                                status_text = await status_value.text_content()
                                membership_info['status'] = status_text.strip() if status_text else 'N/A'
                                logger.info(f"Extracted status: {membership_info['status']}")
                except Exception as e:
                    logger.error(f"Error extracting membership status: {e}", exc_info=True)

                # Extract Start date
                try:
                    start_date_label = await page.query_selector('span.MuiTypography-textv2BodyHeavy:has-text("Start date")')
                    if start_date_label:
                        # Find the parent container and then the date value
                        parent = await start_date_label.query_selector('xpath=ancestor::div[contains(@class, "MuiBox-root")][1]')
                        if parent:
                            date_div = await parent.query_selector('div.css-164r41r')
                            if date_div:
                                date_text = await date_div.text_content()
                                membership_info['start_date'] = date_text.strip() if date_text else 'N/A'
                                logger.info(f"Extracted start date: {membership_info['start_date']}")
                except Exception as e:
                    logger.error(f"Error extracting membership start date: {e}", exc_info=True)

                # Extract Price
                try:
                    price_label = await page.query_selector('span.MuiTypography-textv2BodyHeavy:has-text("Price")')
                    if price_label:
                        # Find the parent container and then the price value
                        parent = await price_label.query_selector('xpath=ancestor::div[contains(@class, "MuiBox-root")][1]')
                        if parent:
                            price_div = await parent.query_selector('div.css-164r41r')
                            if price_div:
                                price_text = await price_div.text_content()
                                membership_info['price'] = price_text.strip() if price_text else 'N/A'
                                logger.info(f"Extracted price: {membership_info['price']}")
                except Exception as e:
                    logger.error(f"Error extracting membership price: {e}", exc_info=True)
        else:
            logger.warning("Memberships tab not found")

        # Click Gallery tab and extract first date (outside of membership section)
        try:
            logger.info("Looking for Gallery tab...")
            gallery_tab = await page.query_selector('md-tab-item:has-text("Gallery")')

            if gallery_tab:
                await gallery_tab.click()
                logger.info("Clicked on Gallery tab")

                # Wait for gallery content to load
                await page.wait_for_timeout(2000)

                # Check for Gallery heading presence
                gallery_heading = await page.query_selector('span.MuiTypography-textv2HeadingPage:has-text("Gallery")')

                if gallery_heading:
                    logger.info("Found Gallery heading")

                    # Extract first date span
                    first_date_span = await page.query_selector('span.MuiTypography-textv2HeadingDetail')
                    if first_date_span:
                        date_text = await first_date_span.text_content()
                        if date_text:
                            date_text = date_text.strip()
                            try:
                                # Convert from "September 24, 2025" to "10/07/2025" format
                                parsed_date = datetime.strptime(date_text, "%B %d, %Y")
                                membership_info['gallery_first_date'] = parsed_date.strftime("%m/%d/%Y")
                                logger.info(f"Extracted gallery first date: {membership_info['gallery_first_date']}")
                            except ValueError as e:
                                logger.error(f"Error parsing gallery date '{date_text}': {e}")
                                membership_info['gallery_first_date'] = date_text  # Keep original if parsing fails
                        else:
                            membership_info['gallery_first_date'] = 'N/A'
                    else:
                        logger.info("No date span found in Gallery")
                        membership_info['gallery_first_date'] = 'N/A'
                else:
                    logger.info("Gallery heading not found")
                    membership_info['gallery_first_date'] = 'N/A'
            else:
                logger.warning("Gallery tab not found")
                membership_info['gallery_first_date'] = 'N/A'
        except Exception as e:
            logger.error(f"Error extracting gallery date: {e}", exc_info=True)
            membership_info['gallery_first_date'] = 'N/A'

        logger.info(f"Successfully extracted membership info: {membership_info}")

    except Exception as e:
        logger.error(f"Error in getMembershipInfo for client_id '{client_id}': {e}", exc_info=True)

    return membership_info


async def extract_new_client_fields(page: Page, new_client_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract specific fields from new client events with proper formatting.
    Calls getAppointmentDetails for each extracted record.

    Args:
        page: Playwright page object with active session
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
        if TEST_ENV:
            logger.info("*** TEST MODE: Processing only 1 record ***")
        logger.info("=" * 60)

        extracted_data = []

        # Limit to 1 record if in TEST_ENV mode
        events_to_process = new_client_events[:1] if TEST_ENV else new_client_events
        total_available = len(new_client_events)

        if TEST_ENV and total_available > 0:
            logger.info(f"Testing with 1 record out of {total_available} available new client events")

        for idx, event in enumerate(events_to_process, 1):
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
                    'recurring_appointment_id': event.get('recurring_appointment_id', None),
                    'visit_count': 1
                }

                extracted_data.append(extracted_record)

                logger.info(f"{idx}. {extracted_record['client_name']} - "
                          f"{extracted_record['appointment_date']} - "
                          f"{extracted_record['service_name']} - "
                          f"${extracted_record['price']}")

                # Call getAppointmentDetails for this record and get additional details
                appointment_details = await getAppointmentDetails(
                    page=page,
                    client_name=extracted_record['client_name'],
                    appointment_date=extracted_record['appointment_date']
                )

                # Add appointment details to the extracted record
                if appointment_details:
                    # Add phone number
                    extracted_record['phone_number'] = appointment_details.get('phone_number', 'N/A')
                    logger.info(f"Added phone number to record: {appointment_details.get('phone_number', 'Not found')}")

                    # Add any other extracted details from the dictionary
                    for key, value in appointment_details.items():
                        if key != 'phone_number':  # Phone number already added above
                            extracted_record[key] = value
                            logger.info(f"Added {key} to record: {value}")
                else:
                    logger.warning("No appointment details returned")
                    extracted_record['phone_number'] = 'N/A'

            except Exception as e:
                logger.warning(f"Error extracting fields from event {idx}: {e}")
                continue

            # Extract membership information and add it to extracted_record
            membership_details = await getMembershipInfo(page, extracted_record['client_id'])

            # Append individual membership fields to extracted_record
            extracted_record['membership_status'] = membership_details.get('status', 'N/A')
            extracted_record['membership_start_date'] = membership_details.get('start_date', 'N/A')
            extracted_record['membership_price'] = membership_details.get('price', 'N/A')
            extracted_record['scheduled_appointments'] = membership_details.get('scheduled_appointments', [])
            extracted_record['gallery_first_date'] = membership_details.get('gallery_first_date', 'N/A')

            # Compare appointment_date with gallery_first_date to determine hasPhotos
            appointment_date = extracted_record.get('appointment_date', 'N/A')
            gallery_date = extracted_record['gallery_first_date']

            if appointment_date != 'N/A' and gallery_date != 'N/A':
                extracted_record['hasPhotos'] = (appointment_date == gallery_date)
                logger.info(f"Comparing dates - Appointment: {appointment_date}, Gallery: {gallery_date}, hasPhotos: {extracted_record['hasPhotos']}")
            else:
                extracted_record['hasPhotos'] = False
                logger.info(f"Missing date data - Appointment: {appointment_date}, Gallery: {gallery_date}, hasPhotos: False")

            logger.info(f"Added membership_status to record: {extracted_record['membership_status']}")
            logger.info(f"Added membership_start_date to record: {extracted_record['membership_start_date']}")
            logger.info(f"Added membership_price to record: {extracted_record['membership_price']}")
            logger.info(f"Added scheduled_appointments to record: {len(extracted_record['scheduled_appointments'])} appointment(s)")
            logger.info(f"Added gallery_first_date to record: {extracted_record['gallery_first_date']}")
            logger.info(f"Added hasPhotos to record: {extracted_record['hasPhotos']}")

        logger.info("=" * 60)
        logger.info(f"Successfully extracted {len(extracted_data)} new client records")
        logger.info("=" * 60)

        return extracted_data

    except Exception as e:
        logger.error(f"Error extracting new client fields: {e}", exc_info=True)
        return []


def get_last_row_number_from_sheets() -> int:
    """
    Fetch the last row number from Google Sheets (yesterday's month sheet).

    Returns:
        int: The last number value from the 'number' column, or 0 if sheet is empty or error occurs
    """
    try:
        # Check if credentials are set
        if not GOOGLE_CREDENTIALS_B64 or not SPREADSHEET_ID:
            logger.warning("Google Sheets credentials not configured, starting from 1")
            return 0

        # Decode base64 credentials
        credentials_json = base64.b64decode(GOOGLE_CREDENTIALS_B64).decode('utf-8')
        credentials_dict = json.loads(credentials_json)

        # Set up Google Sheets authentication
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets.readonly',
            'https://www.googleapis.com/auth/drive.readonly'
        ]

        credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        gc = gspread.authorize(credentials)

        # Open the spreadsheet
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)

        # Determine target sheet based on yesterday's date
        yesterday = datetime.now() - timedelta(days=1)
        target_month = yesterday.strftime("%B")  # Full month name (e.g., "October")

        logger.info(f"Fetching last row number from {target_month} sheet...")

        # Get the target worksheet
        try:
            worksheet = spreadsheet.worksheet(target_month)
        except Exception:
            logger.warning(f"Sheet '{target_month}' not found, starting from 1")
            return 0

        # Get all values from the first column (number column)
        all_values = worksheet.col_values(1)  # Column A (number column)

        if len(all_values) <= 1:  # Only header or empty
            logger.info("Sheet is empty or only has headers, starting from 1")
            return 0

        # Get the last value (skip header)
        last_value = all_values[-1]

        # Try to convert to integer
        try:
            last_number = int(last_value)
            logger.info(f"Last row number in {target_month} sheet: {last_number}")
            return last_number
        except ValueError:
            logger.warning(f"Could not parse last row number '{last_value}', starting from 1")
            return 0

    except Exception as e:
        logger.error(f"Error fetching last row number from Google Sheets: {e}", exc_info=True)
        return 0


def clean_data(extracted_data: List[Dict[str, Any]], start_number: int = 1) -> List[Dict[str, Any]]:
    """
    Clean and transform extracted data into the final format.

    Args:
        extracted_data: List of extracted client records
        start_number: Starting number for the 'number' field (default: 1)

    Returns:
        List of cleaned records with transformed fields
    """
    import re

    cleaned_records = []

    # Get current year dynamically
    current_year = datetime.now().year

    for idx, record in enumerate(extracted_data, start=start_number):
        # Extract next appointment date from scheduled_appointments
        next_appointment_date = "N/A"
        scheduled_appointments = record.get('scheduled_appointments', [])
        if scheduled_appointments and len(scheduled_appointments) > 0:
            # Get first scheduled appointment's date_time
            date_time_str = scheduled_appointments[0].get('date_time', '')
            if date_time_str and date_time_str != 'N/A':
                # Extract date from format like "Tuesday, Nov 18 @ 2:00pm"
                # Match pattern: Month Day
                match = re.search(r'([A-Za-z]+)\s+(\d+)', date_time_str)
                if match:
                    month_str = match.group(1)
                    day_str = match.group(2)

                    # Convert month name to number
                    month_map = {
                        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12',
                        'January': '01', 'February': '02', 'March': '03', 'April': '04',
                        'June': '06', 'July': '07', 'August': '08', 'September': '09',
                        'October': '10', 'November': '11', 'December': '12'
                    }

                    month_num = month_map.get(month_str, '01')
                    day_num = day_str.zfill(2)
                    next_appointment_date = f"{month_num}/{day_num}/{current_year}"

        # Format booked_date from "Mon Oct 6 @ 3:48pm CDT" to "10/06/2025"
        booked_date_formatted = ""
        booked_date = record.get('booked_date', '')
        if booked_date and booked_date != 'N/A':
            # Extract date from format like "Mon Oct 6 @ 3:48pm CDT"
            match = re.search(r'([A-Za-z]+)\s+(\d+)', booked_date)
            if match:
                month_str = match.group(1)
                day_str = match.group(2)

                # Convert month name to number
                month_map = {
                    'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                    'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                    'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                }

                month_num = month_map.get(month_str, '01')
                day_num = day_str.zfill(2)
                booked_date_formatted = f"{month_num}/{day_num}/{current_year}"
            else:
                booked_date_formatted = booked_date

        # Get PT intake form data
        pt_intake_form = record.get('pt_intake_form', {})
        interests = pt_intake_form.get('interests', []) if pt_intake_form else []

        # Build cleaned record
        cleaned_record = {
            'number': idx,
            'new_client_daily_count': '',
            'appointment_date': record.get('appointment_date', 'N/A'),
            'next_appointment_date': next_appointment_date,
            'client_name': record.get('client_name', 'N/A'),
            'phone_number': record.get('phone_number', 'N/A'),
            'service_name': record.get('service_name', 'N/A'),
            'price': record.get('price', 0.0),
            'membership': record.get('membership_start_date', 'N/A'),
            'visit': record.get('visit_count', 1),
            'booked_date': booked_date_formatted,
            'front_desk': record.get('booked_by', 'N/A'),
            'provider_name': record.get('provider_name', 'N/A'),
            'date_treatment_plan_set': '',
            'photos': 'Yes' if record.get('hasPhotos', False) else 'No',
            'charting': 'Yes' if record.get('hasCharting', False) else 'No',
            'occupation': pt_intake_form.get('occupation', '') if pt_intake_form else '',
            'referral_source': pt_intake_form.get('referral_source', 'N/A') if pt_intake_form else 'N/A',
            'referral_source_2': 'N/A',
            'referral_name': pt_intake_form.get('referral_name', 'N/A') if pt_intake_form else 'N/A',
            'form_compliance': 'Completed' if record.get('hasCompletedPTIntakeForm', False) else 'Not Completed',
            'interest_1': interests[0] if len(interests) > 0 else '',
            'interest_2': interests[1] if len(interests) > 1 else '',
            'interest_3': interests[2] if len(interests) > 2 else '',
            'interest_4': interests[3] if len(interests) > 3 else '',
            'interest_5': interests[4] if len(interests) > 4 else '',
            'interest_6': interests[5] if len(interests) > 5 else '',
            'interest_7': interests[6] if len(interests) > 6 else '',
            'interest_8': interests[7] if len(interests) > 7 else '',
            'interest_9': interests[8] if len(interests) > 8 else '',
            'interest_10': interests[9] if len(interests) > 9 else ''
        }

        cleaned_records.append(cleaned_record)

    logger.info(f"Cleaned {len(cleaned_records)} records")
    return cleaned_records


def append_to_google_sheets(cleaned_data: List[Dict[str, Any]]) -> bool:
    """
    Append cleaned data to Google Sheets.
    Creates monthly sheets (October, November, December) if they don't exist.
    Adds headers if they don't exist.
    Appends data to the sheet corresponding to yesterday's date.

    Args:
        cleaned_data: List of cleaned records to append

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info("=" * 60)
        logger.info("Starting Google Sheets integration...")
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
        except Exception as e:
            logger.error(f"Error decoding Google credentials: {e}")
            return False

        # Set up Google Sheets authentication
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        gc = gspread.authorize(credentials)

        # Open the spreadsheet
        try:
            spreadsheet = gc.open_by_key(SPREADSHEET_ID)
            logger.info(f"Successfully opened spreadsheet: {spreadsheet.title}")
        except Exception as e:
            logger.error(f"Error opening spreadsheet: {e}")
            return False

        # Determine target sheet based on yesterday's date
        yesterday = datetime.now() - timedelta(days=1)
        target_month = yesterday.strftime("%B")  # Full month name (e.g., "October")

        logger.info(f"Target month for data: {target_month} (yesterday was {yesterday.strftime('%Y-%m-%d')})")

        # List of month sheets to ensure exist
        month_sheets = ["October", "November", "December"]

        # Create sheets if they don't exist
        existing_sheets = [ws.title for ws in spreadsheet.worksheets()]

        for month in month_sheets:
            if month not in existing_sheets:
                logger.info(f"Creating sheet: {month}")
                spreadsheet.add_worksheet(title=month, rows=1000, cols=30)
            else:
                logger.info(f"Sheet already exists: {month}")

        # Get the target worksheet
        try:
            worksheet = spreadsheet.worksheet(target_month)
            logger.info(f"Using worksheet: {target_month}")
        except Exception as e:
            logger.error(f"Error accessing worksheet '{target_month}': {e}")
            return False

        # Define headers (capitalized version of field names)
        if cleaned_data:
            # Get field names from first record and convert to Title Case
            headers = [key.replace('_', ' ').title() for key in cleaned_data[0].keys()]

            # Check if headers exist
            existing_values = worksheet.get_all_values()

            if not existing_values or not existing_values[0]:
                # No headers exist, add them
                logger.info("Adding headers to worksheet")
                worksheet.insert_row(headers, index=1)
            else:
                # Verify headers match
                existing_headers = existing_values[0]
                if existing_headers != headers:
                    logger.warning(f"Existing headers don't match. Expected: {headers}, Found: {existing_headers}")
                    # Update headers
                    worksheet.update('A1', [headers])
                    logger.info("Updated headers to match data structure")

            # Prepare data rows
            data_rows = []
            for record in cleaned_data:
                row = [record.get(key, '') for key in cleaned_data[0].keys()]
                data_rows.append(row)

            # Append data rows
            if data_rows:
                logger.info(f"Appending {len(data_rows)} rows to {target_month} sheet")
                worksheet.append_rows(data_rows, value_input_option='USER_ENTERED')
                logger.info(f"Successfully appended {len(data_rows)} records to Google Sheets")
            else:
                logger.warning("No data rows to append")

            logger.info("=" * 60)
            logger.info("Google Sheets integration completed successfully")
            logger.info("=" * 60)
            return True
        else:
            logger.warning("No cleaned data to append")
            return False

    except Exception as e:
        logger.error(f"Error appending to Google Sheets: {e}", exc_info=True)
        return False


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
                    extracted_data = await extract_new_client_fields(page, new_client_events)

                    if extracted_data:
                        # Get the last row number from Google Sheets
                        logger.info(f"\n{'='*60}")
                        logger.info("Fetching last row number from Google Sheets...")
                        logger.info(f"{'='*60}")
                        last_row_number = get_last_row_number_from_sheets()
                        start_number = last_row_number + 1
                        logger.info(f"Starting number for new records: {start_number}")

                        # Clean the extracted data
                        logger.info(f"\n{'='*60}")
                        logger.info("Cleaning extracted data...")
                        logger.info(f"{'='*60}")
                        cleaned_data = clean_data(extracted_data, start_number=start_number)

                        # Save cleaned data to JSON file
                        extracted_filename = "new_client_events_extracted.json"
                        with open(extracted_filename, 'w', encoding='utf-8') as f:
                            json.dump(cleaned_data, f, indent=2, ensure_ascii=False)

                        logger.info(f"\nCleaned data saved to: {extracted_filename}")

                        # Append to Google Sheets
                        sheets_success = append_to_google_sheets(cleaned_data)

                        logger.info(f"\n{'='*60}")
                        logger.info(f"FINAL SUMMARY: Processed {len(cleaned_data)} new client records")
                        logger.info(f"{'='*60}")
                        logger.info("\nGenerated files:")
                        logger.info("  Output file:")
                        logger.info("    - new_client_events_extracted.json (cleaned client data with specific fields)")
                        if sheets_success:
                            logger.info("  Google Sheets:")
                            logger.info("    - Data successfully appended to monthly sheet")
                        else:
                            logger.warning("  Google Sheets:")
                            logger.warning("    - Failed to append data (check logs above for details)")
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
