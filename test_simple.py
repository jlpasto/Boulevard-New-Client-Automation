import sys
print("Python executable:", sys.executable)
print("Python version:", sys.version)

try:
    from dotenv import load_dotenv
    print("[OK] dotenv imported successfully")
except ImportError as e:
    print("[ERROR] Failed to import dotenv:", e)
    sys.exit(1)

try:
    from playwright.async_api import async_playwright
    print("[OK] playwright imported successfully")
except ImportError as e:
    print("[ERROR] Failed to import playwright:", e)
    print("\nPlease run: pip install playwright")
    print("Then run: playwright install chromium")
    sys.exit(1)

import os
load_dotenv()

EMAIL = os.getenv("BLVD_EMAIL")
PASSWORD = os.getenv("BLVD_PASSWORD")

print(f"\nEmail loaded: {EMAIL is not None}")
print(f"Password loaded: {PASSWORD is not None}")

if EMAIL and PASSWORD:
    print("\n[OK] Credentials loaded successfully!")
    print("\nYou can now run: python app.py")
else:
    print("\n[ERROR] Credentials not loaded!")
    print("Please check your .env file")
