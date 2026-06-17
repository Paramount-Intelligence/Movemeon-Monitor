import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException

# Load environment variables
load_dotenv()

# ============================
# CONFIGURATION
# ============================
class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    DB_NAME = "office_monitor"
    COLLECTION_NAME = "sessions"
    SESSION_ID = "movemeon_cookies"
    
    MOVEMEON_EMAIL = os.getenv("MOVEMEON_EMAIL")
    MOVEMEON_PASSWORD = os.getenv("MOVEMEON_PASSWORD")
    TARGET_URL = "https://portal.movemeon.com/dashboard/candidate/jobs"
    SIGNIN_URL = "https://portal.movemeon.com/auth/signin"
    
    HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"
    COOKIES_FILE = "movemeon_cookies.json"
    
    CHROME_BIN = os.getenv("CHROME_BIN")
    CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH")

# ============================
# DRIVER SETUP
# ============================
def initialize_driver():
    """Initialize Chrome WebDriver with specialized options for scraping."""
    options = Options()
    if Config.HEADLESS:
        options.add_argument("--headless=new")
    
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    options.add_argument(f"user-agent={user_agent}")

    if Config.CHROME_BIN:
        options.binary_location = Config.CHROME_BIN

    if Config.CHROMEDRIVER_PATH:
        service = Service(executable_path=Config.CHROMEDRIVER_PATH)
    else:
        service = Service()

    driver = webdriver.Chrome(service=service, options=options)
    
    # Anti-detection script
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    
    return driver

# ============================
# DATABASE SETUP
# ============================
def get_session_collection():
    """Get MongoDB session collection."""
    try:
        client = MongoClient(Config.MONGO_URI)
        return client[Config.DB_NAME][Config.COLLECTION_NAME]
    except Exception as e:
        print(f"FAILED: MongoDB connection error: {e}")
        return None

# ============================
# CORE LOGIC
# ============================
def is_logged_in(driver):
    """Check if the current session is valid."""
    try:
        current_url = driver.current_url
        if "dashboard/candidate/jobs" in current_url:
            # Check for actual job cards or dashboard elements
            cards = driver.find_elements(By.CSS_SELECTOR, "div.rounded-xl.border.bg-card, a[href*='/jobs/']")
            return len(cards) > 0
        return False
    except:
        return False

def save_cookies(driver):
    """Save browser cookies and LocalStorage to MongoDB and local JSON file."""
    try:
        cookies = driver.get_cookies()
        # Also capture LocalStorage
        local_storage = driver.execute_script("return window.localStorage;")
        
        if not cookies:
            print("WARNING: No cookies found to save.")
            return False

        session_data = {
            "cookies": cookies,
            "local_storage": local_storage,
            "saved_at": datetime.now(timezone.utc).isoformat()
        }

        # Save to local JSON
        with open(Config.COOKIES_FILE, "w") as f:
            json.dump(session_data, f)
        print(f"SUCCESS: Session data (cookies + LocalStorage) saved to local file: {Config.COOKIES_FILE}")

        # Save to MongoDB
        collection = get_session_collection()
        if collection is not None:
            collection.update_one(
                {"_id": Config.SESSION_ID},
                {"$set": session_data},
                upsert=True
            )
            print(f"SUCCESS: Session data saved to MongoDB (ID: {Config.SESSION_ID})")
            print(f"Total cookies saved: {len(cookies)}")
            return True
    except Exception as e:
        print(f"ERROR: Error saving session data: {e}")
    return False

def restore_local_storage(driver, local_storage_data):
    """Restore LocalStorage data to the browser."""
    try:
        for key, value in local_storage_data.items():
            driver.execute_script(f"window.localStorage.setItem(arguments[0], arguments[1]);", key, value)
        return True
    except Exception as e:
        print(f"WARNING: Failed to restore LocalStorage: {e}")
        return False

def perform_login(driver):
    """Attempt automated login to MoveMeOn."""
    try:
        print(f"Opening MoveMeOn sign-in page...")
        driver.get(Config.SIGNIN_URL)
        driver.maximize_window()
        time.sleep(3)

        print(f"Automated login attempted for: {Config.MOVEMEON_EMAIL}")
        
        # Step 1: Email
        email_selectors = ["input[type='email']", "input[name='email']", "input[id*='email']"]
        email_field = None
        for sel in email_selectors:
            try:
                email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                if email_field: break
            except: continue
        
        if not email_field:
            raise Exception("Email field not found")

        email_field.send_keys(Config.MOVEMEON_EMAIL)
        email_field.send_keys(Keys.ENTER)
        
        # Transition wait
        time.sleep(3)
        
        # Step 2: Password
        pass_selectors = ["input[type='password']", "input[name='password']", "input[id*='password']"]
        pass_field = None
        for sel in pass_selectors:
            try:
                pass_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, sel)))
                if pass_field: break
            except: continue
            
        if not pass_field:
            raise Exception("Password field not found")

        pass_field.send_keys(Config.MOVEMEON_PASSWORD)
        pass_field.send_keys(Keys.ENTER)
        
        # Wait for redirect
        WebDriverWait(driver, 20).until(
            lambda d: "dashboard" in d.current_url or d.find_elements(By.CSS_SELECTOR, "div.rounded-xl.border.bg-card")
        )
        if "onboarding" in driver.current_url:
            print("  Detecting onboarding page. Attempting to click 'Skip'...")
            try:
                time.sleep(5)
                skip_btn = None
                for selector in [
                    "//button[contains(text(), 'Skip')]",
                    "//a[contains(text(), 'Skip')]",
                    "//*[contains(text(), 'Skip')]",
                    "button[class*='skip']",
                    "a[class*='skip']"
                ]:
                    try:
                        if selector.startswith("//"):
                            skip_btn = driver.find_element(By.XPATH, selector)
                        else:
                            skip_btn = driver.find_element(By.CSS_SELECTOR, selector)
                        if skip_btn and skip_btn.is_displayed():
                            break
                    except:
                        continue
                if skip_btn:
                    driver.execute_script("arguments[0].click();", skip_btn)
                    print("  Clicked 'Skip' on onboarding page.")
                    time.sleep(5)
                else:
                    print("  Could not find 'Skip' button. Will proceed with navigation.")
            except Exception as e_skip:
                print(f"  Failed to skip onboarding: {e_skip}")
        return True
    except Exception as e:
        print(f"WARNING: Automated login failed or timed out: {e}")
        return False

# ============================
# MAIN EXECUTION
# ============================
def main():
    print("==================================================")
    print("STARTING: MoveMeOn Cookie Saver")
    print("==================================================")
    
    driver = initialize_driver()
    try:
        print(f"Opening MoveMeOn curated jobs page...")
        driver.get(Config.TARGET_URL)
        time.sleep(5)

        if is_logged_in(driver):
            print("SUCCESS: Login detected automatically via existing session.")
        else:
            print("LOGIN REQUIRED.")
            success = perform_login(driver)
            
            if not success:
                print("\n" + "!"*50)
                print("MANUAL LOGIN REQUIRED")
                print("Please complete login manually in the browser window.")
                print("Solve any CAPTCHAs or MFA if they appear.")
                print("Press Enter here after the curated jobs page is fully loaded.")
                print("!"*50 + "\n")
                input("Press Enter to continue...")

        # Final check and save
        if "dashboard/candidate/jobs" in driver.current_url or is_logged_in(driver):
            save_cookies(driver)
            
            # Validation
            print("\nValidating cookies (waiting 10s for Clerk to settle)...")
            driver.get(Config.TARGET_URL)
            time.sleep(10)
            if is_logged_in(driver):
                print("SUCCESS: Cookie validation successful: Logged in and jobs visible.")
            else:
                print("FAILED: Cookie validation failed: Redirected to login.")
        else:
            print("FAILED: Failed to reach the Discover Jobs page.")

    except Exception as e:
        print(f"ERROR: An error occurred in main: {e}")
    finally:
        print("Done. Closing browser.")
        driver.quit()

if __name__ == "__main__":
    main()
