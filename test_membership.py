import asyncio
import json
import logging
import os
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError
from typing import Dict, Any
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Boulevard Configuration
LOGIN_URL = "https://dashboard.boulevard.io/login-v2"
EMAIL = os.getenv("BLVD_EMAIL")
PASSWORD = os.getenv("BLVD_PASSWORD")
SESSION_FILE = "session_test.json"

# Configuration constants
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

        # Wait for page to load
        await page.wait_for_timeout(3000)

        # Click on Memberships tab
        logger.info("Looking for Memberships tab...")
        memberships_tab = await page.query_selector('md-tab-item:has-text("Memberships")')

        if not memberships_tab:
            logger.warning("Memberships tab not found")
            return membership_info

        await memberships_tab.click()
        logger.info("Clicked on Memberships tab")

        # Wait for membership content to load
        await page.wait_for_timeout(2000)

        # Look for Overview card to confirm there's membership data
        overview_card = await page.query_selector('span.MuiTypography-h5:has-text("Overview")')

        if not overview_card:
            logger.info("No membership Overview found - client may not have an active membership")
            return membership_info

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

        logger.info(f"Successfully extracted membership info: {membership_info}")

    except Exception as e:
        logger.error(f"Error in getMembershipInfo for client_id '{client_id}': {e}", exc_info=True)

    return membership_info


async def main():
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        try:
            # Perform login
            logger.info("Starting login process...")
            login_success = await perform_login(context, page)

            if not login_success:
                logger.error("Login failed. Cannot proceed with membership extraction.")
                return

            logger.info("Login successful! Proceeding with membership extraction...")

            # Test the membership info extraction
            client_id = "5024fe75-2aa6-4c9d-b577-c75fdfd9c313"
            logger.info(f"\nTesting membership extraction for client: {client_id}")

            membership_info = await getMembershipInfo(page, client_id)

            # Save to JSON file
            output_file = "membership_info.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(membership_info, f, indent=2, ensure_ascii=False)

            logger.info(f"\nMembership info saved to: {output_file}")
            logger.info(f"\n{'='*50}")
            logger.info("Extracted membership info:")
            logger.info(f"{'='*50}")
            logger.info(json.dumps(membership_info, indent=2))
            logger.info(f"{'='*50}")

            # Keep browser open for a moment to see the result
            logger.info("\nKeeping browser open for 5 seconds...")
            await page.wait_for_timeout(5000)

        except Exception as e:
            logger.error(f"Error during test: {e}", exc_info=True)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
