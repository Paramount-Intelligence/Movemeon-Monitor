import sys
import time
import smtplib
import json
import os
import re

# Ensure UTF-8 output on all platforms (fixes Windows emoji crash)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from pymongo import MongoClient, UpdateOne
from datetime import datetime, timezone, timedelta

PKT = timezone(timedelta(hours=5))  # Pakistan Standard Time (UTC+5)
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================
# CONFIGURATION
# ============================
class Config:
    """Load configuration from environment variables"""
    PLATFORM_NAME = os.getenv("PLATFORM_NAME", "movemeon")
    PROJECTS_COLLECTION = os.getenv("PROJECTS_COLLECTION", "movemeon_projects")
    SESSION_KEY = os.getenv("SESSION_KEY", "movemeon_cookies")
    
    EMAIL = os.getenv("MOVEMEON_EMAIL")
    PASSWORD = os.getenv("MOVEMEON_PASSWORD")
    DASHBOARD_URL = os.getenv("MOVEMEON_DASHBOARD_URL", "https://portal.movemeon.com/dashboard/candidate/jobs")
    JOBS_URL = os.getenv("MOVEMEON_JOBS_URL", "https://portal.movemeon.com/dashboard/candidate/jobs")
    
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    RECIPIENT_EMAILS = [e.strip() for e in os.getenv("RECIPIENT_EMAILS", "").split(",") if e.strip()]
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
    MAX_AGE_MINUTES = int(os.getenv("MAX_AGE_MINUTES", 60))
    HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"
    COOKIES_FILE = f"{PLATFORM_NAME}_cookies.json"
    MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

JOB_SESSION_SELECTOR = "div.rounded-xl.border.bg-card, a[href*='/jobs/']"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# ============================
# SESSION MANAGEMENT
# ============================
_mongo_client = None

def _get_session_collection():
    """MongoDB collection for storing session cookies."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(Config.MONGO_URI)
    return _mongo_client["office_monitor"]["sessions"]

def save_cookies(driver):
    """Save session cookies to MongoDB AND local file as fallback."""
    cookies = driver.get_cookies()
    # MongoDB (primary)
    try:
        from datetime import timezone
        _get_session_collection().update_one(
            {"_id": Config.SESSION_KEY},
            {"$set": {"cookies": cookies, "saved_at": datetime.now(timezone.utc)}},
            upsert=True
        )
    except Exception as e:
        print(f"  ⚠️ Could not save cookies to MongoDB: {e}")
    # Local file fallback
    try:
        with open(Config.COOKIES_FILE, 'w') as f:
            json.dump(cookies, f)
    except Exception:
        pass
    return True

def load_cookies(driver):
    """Load cookies from MongoDB first, fall back to local file."""
    cookies = None
    # Try MongoDB first
    try:
        doc = _get_session_collection().find_one({"_id": Config.SESSION_KEY})
        if doc and doc.get("cookies"):
            cookies = doc["cookies"]
            print(f"  Loaded cookies from MongoDB ({Config.SESSION_KEY})")
    except Exception as e:
        print(f"  ⚠️ Could not load cookies from MongoDB: {e}")
    # Fall back to local file
    if not cookies:
        if not os.path.exists(Config.COOKIES_FILE):
            return False
        try:
            with open(Config.COOKIES_FILE, 'r') as f:
                cookies = json.load(f)
            print(f"  Loaded cookies from local file ({Config.COOKIES_FILE})")
        except Exception:
            return False
    if not cookies:
        return False
    try:
        driver.get(Config.DASHBOARD_URL)
        time.sleep(2)
        driver.delete_all_cookies()
        for cookie in cookies:
            # Update domain check: accept if it contains movemeon.com
            if 'domain' in cookie and 'movemeon.com' in cookie['domain']:
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    pass
        return True
    except Exception:
        return False

def _save_page_debug(driver, basename):
    """Save screenshot and HTML dump for post-mortem debugging."""
    try:
        driver.save_screenshot(f"{basename}.png")
        print(f"  Saved screenshot: {basename}.png")
    except Exception as e:
        print(f"  Could not save screenshot: {type(e).__name__}: {repr(e)}")
    try:
        with open(f"{basename}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"  Saved HTML: {basename}.html")
    except Exception as e:
        print(f"  Could not save HTML: {type(e).__name__}: {repr(e)}")

def _log_page_state(driver, label="page"):
    """Log URL, title, and body snippet without assuming failure cause."""
    try:
        print(f"  [{label}] URL: {driver.current_url}")
        print(f"  [{label}] Title: {driver.title}")
        body_text = driver.find_element(By.TAG_NAME, "body").text[:3000]
        print(f"  [{label}] Body (first 3000 chars):\n{body_text}")
    except Exception as e:
        print(f"  [{label}] Could not read page state: {type(e).__name__}: {repr(e)}")

def _find_visible_input(driver, selectors, timeout=20):
    """Try selectors in order; return the first visible input element."""
    def _locator(d):
        for selector in selectors:
            for elem in d.find_elements(By.CSS_SELECTOR, selector):
                if elem.is_displayed():
                    return elem
        return False

    return WebDriverWait(driver, timeout).until(_locator)

def perform_login(driver):
    """Perform login to MoveMeOn"""
    try:
        print(f"  Navigating to signin page...")
        driver.get("https://portal.movemeon.com/auth/signin")
        driver.maximize_window()
        time.sleep(3)
        
        # Check if already logged in
        if "dashboard" in driver.current_url:
            print("  Already logged in.")
            return True

        # Step 1: Enter Email
        print(f"  Entering email: {Config.EMAIL}...")
        email_field = _find_visible_input(driver, [
            "input[type='email']",
            "input[name*='email' i]",
            "input[placeholder*='email' i]",
            "#email",
        ])
        email_field.send_keys(Config.EMAIL)
        email_field.send_keys(Keys.ENTER)
        
        # Transition wait for password field
        print(f"  Waiting for password field...")
        time.sleep(3)
        
        # Step 2: Enter Password (wait for it to appear)
        password_field = _find_visible_input(driver, [
            "input[type='password']",
            "input[name*='password' i]",
            "input[placeholder*='password' i]",
            "#password",
        ])
        print(f"  Entering password...")
        password_field.send_keys(Config.PASSWORD)
        password_field.send_keys(Keys.ENTER)
        
        # Wait for any dashboard element to confirm login
        print(f"  Waiting for post-login redirect...")
        WebDriverWait(driver, 30).until(
            lambda d: "dashboard" in d.current_url or d.find_elements(By.CSS_SELECTOR, "[href*='dashboard']")
        )
        print(f"  Login successful. Current URL: {driver.current_url}")

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
        
        save_cookies(driver)
        
        # Now explicitly navigate to the jobs page
        _navigate_to_search(driver)
        
        # Verify we can see job cards
        print(f"  Verifying job cards are visible...")
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, JOB_SESSION_SELECTOR))
            )
            print("✅ Session established -> Discover Jobs")
            return True
        except Exception as timeout_err:
            print(f"⏳ Timeout waiting for job cards after login.")
            raise timeout_err
            
    except Exception as e:
        print(f"❌ Login failed: {type(e).__name__}: {repr(e)}")
        _log_page_state(driver, "login")
        _save_page_debug(driver, "movemeon_login_failed")
        return False

# ============================
# PROJECT EXTRACTION
# ============================
def extract_project_data(card):
    """Extract data from a MoveMeOn job card"""
    try:
        # Title and URL extraction - try multiple common patterns
        title_elem = None
        for selector in ["h3 a", "a[href*='/jobs/']", "a.title", ".job-title a"]:
            try:
                title_elem = card.find_element(By.CSS_SELECTOR, selector)
                if title_elem: break
            except: continue
            
        if not title_elem:
            # print("DEBUG: Could not find title element in card")
            return None
            
        title = title_elem.text.strip()
        url = title_elem.get_attribute("href")
        
        if not title or not url:
            return None
        
        # Unique Job ID from URL
        project_id = url.split("/")[-1] if "/" in url else url

        # Metadata extraction (Location, Salary, Job Type)
        # Look for the metadata row - usually a container with slate text
        location = ""
        budget = ""
        duration = ""
        company = ""
        
        try:
            metadata_items = card.find_elements(By.CSS_SELECTOR, "div.flex.items-center.gap-1, .metadata-item, [class*='text-slate-500']")
            
            for i, item in enumerate(metadata_items):
                text = item.text.strip()
                if not text: continue
                
                if i == 0 and not any(kw in text.lower() for kw in ["permanent", "contract", "full-time", "$", "£", "€"]):
                    company = text
                elif any(curr in text for curr in ["$", "£", "€", "k", "K", "Salary", "Budget"]):
                    budget = text
                elif any(type_word in text.lower() for type_word in ["permanent", "contract", "full-time", "part-time", "temporary"]):
                    duration = text
                elif not location:
                    location = text
        except:
            pass

        # Description
        description = ""
        try:
            desc_elem = card.find_element(By.CSS_SELECTOR, "p.text-slate-600, .description, .summary")
            description = desc_elem.text.strip()
        except:
            pass

        return {
            "id": project_id,
            "title": f"{title} ({company})" if company else title,
            "description": description,
            "location": location,
            "budget": budget,
            "duration": duration,
            "time_posted": "Recently",
            "status": "New",
            "url": url,
            "detected_at": datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return None

def scan_for_projects(driver):
    """Scan Curated Jobs page for job cards"""
    try:
        # Give the page a moment to render JS content
        time.sleep(5)
        
        # MoveMeOn Job Card Selector (Resilient version)
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, JOB_SESSION_SELECTOR))
        )
        
        # Get all job cards
        project_cards = driver.find_elements(By.CSS_SELECTOR, "div.rounded-xl.border.bg-card")
        
        # Fallback if the class-based selector fails but the links exist
        if not project_cards:
            # Try to find containers of the job links
            project_cards = driver.find_elements(By.XPATH, "//a[contains(@href, '/jobs/')]/ancestor::div[contains(@class, 'border')]")
        
        projects = []
        for card in project_cards:
            project = extract_project_data(card)
            if project and project.get('title') and project.get('id'):
                projects.append(project)
        
        print(f"✅ Extracted {len(projects)} valid jobs")
        return projects
    except TimeoutException:
        print("⏳ Timeout waiting for jobs")
        return []
    except Exception as e:
        print(f"❌ Error scanning: {e}")
        return []

# ============================
# PROJECT DATABASE (MongoDB)
# ============================
_projects_client = None

def _get_collection():
    """Return the MongoDB projects collection dynamically based on Config."""
    global _projects_client
    if _projects_client is None:
        _projects_client = MongoClient(Config.MONGO_URI)
    return _projects_client["office_monitor"][Config.PROJECTS_COLLECTION]

def init_db():
    """Ensure a unique index on 'project_id' exists."""
    try:
        _get_collection().create_index("project_id", unique=True, name="idx_project_id_unique")
    except Exception:
        pass

def db_is_cold_start():
    """True if the collection has no MoveMeOn documents."""
    return _get_collection().find_one({"platform": Config.PLATFORM_NAME}, {"_id": 1}) is None

def get_seen_ids():
    """Return set of MoveMeOn project IDs already in DB."""
    try:
        docs = _get_collection().find({"platform": Config.PLATFORM_NAME}, {"project_id": 1, "_id": 0})
        return {d["project_id"] for d in docs if d.get("project_id")}
    except Exception:
        return set()

def insert_project(project, emailed=True):
    """Upsert one project record."""
    try:
        doc = {
            "project_id":       project.get("id"),
            "title":            project.get("title"),
            "description":      project.get("description"),
            "location":         project.get("location"),
            "budget":           project.get("budget"),
            "duration":         project.get("duration"),
            "time_posted":      project.get("time_posted"),
            "status":           project.get("status"),
            "url":              project.get("url"),
            "detected_at":      project.get("detected_at"),
            "platform":         Config.PLATFORM_NAME,
            "emailed":          bool(emailed),
        }
        _get_collection().update_one(
            {"project_id": doc["project_id"]},
            {"$setOnInsert": doc},
            upsert=True,
        )
    except Exception as e:
        print(f"⚠️ DB insert failed: {e}")

def bulk_insert_projects(projects, emailed=False):
    """Upsert many projects at once."""
    try:
        ops = []
        for p in projects:
            if not p.get("id"):
                continue
            doc = {
                "project_id":  p.get("id"),
                "title":       p.get("title"),
                "description": p.get("description"),
                "location":    p.get("location"),
                "budget":      p.get("budget"),
                "duration":    p.get("duration"),
                "time_posted": p.get("time_posted"),
                "status":      p.get("status"),
                "url":         p.get("url"),
                "detected_at": p.get("detected_at"),
                "platform":    Config.PLATFORM_NAME,
                "emailed":     bool(emailed),
            }
            ops.append(UpdateOne({"project_id": doc["project_id"]}, {"$setOnInsert": doc}, upsert=True))
        if ops:
            result = _get_collection().bulk_write(ops, ordered=False)
            print(f"  DB: inserted {result.upserted_count} records (emailed={'yes' if emailed else 'no'})")
    except Exception as e:
        print(f"⚠️ DB bulk insert failed: {e}")

def parse_posted_minutes(time_str):
    """Convert a scraped 'time_posted' string into minutes."""
    if not time_str or time_str == "Unknown" or time_str == "Recently":
        return None
    s = time_str.lower().strip()
    if any(w in s for w in ("just", "moment", "second")):
        return 0
    match = re.search(r'(\d+)\s*(minute|hour|day|week|month)', s)
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    return val * {"minute": 1, "hour": 60, "day": 1440, "week": 10080, "month": 43200}[unit]

def filter_new_projects(all_projects, seen_ids):
    """Filter out already-seen IDs."""
    result = []
    for p in all_projects:
        if not p.get("id") or p["id"] in seen_ids:
            continue
        result.append(p)
    return result

# ============================
# DETAIL PAGE FETCH
# ============================

# Headings that mark the START of the description section
_DESC_START_HEADINGS = [
    "description", "job description", "the role", "about the role",
    "role description", "overview", "about the job", "the opportunity",
    "what you'll do", "about this role",
]
# Headings that mark the END of the description section
_DESC_STOP_HEADINGS = [
    "requirements", "about you", "skills", "benefits",
    "apply", "location", "compensation", "salary", "what we offer",
    "qualifications", "experience", "responsibilities", "how to apply",
]

def _extract_description_from_text(body_text):
    """Extract description from page body text using heading landmarks."""
    lines = body_text.splitlines()
    capturing = False
    collected = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        # Check if this line is a stop heading
        if capturing and any(lower == h or lower.startswith(h + " ") or lower.startswith(h + ":") for h in _DESC_STOP_HEADINGS):
            break

        # Check if this line is a start heading
        if not capturing and any(lower == h or lower.startswith(h + " ") or lower.startswith(h + ":") for h in _DESC_START_HEADINGS):
            capturing = True
            continue  # skip the heading itself

        if capturing and stripped:
            collected.append(stripped)

    return "\n".join(collected).strip()


def fetch_job_details(driver, url):
    """Open job detail page, extract full description, then return to jobs list."""
    details = {"description": ""}
    try:
        print(f"  Fetching full job details: {url}")
        driver.get(url)
        time.sleep(4)

        description = ""

        # --- Strategy 1: CSS selector priority list ---
        css_selectors = [
            "[class*='description']",
            "[class*='job-description']",
            "[class*='JobDescription']",
            "[class*='details']",
            "[class*='content']",
            "div.prose",
            "main",
            "article",
        ]
        for sel in css_selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elems:
                    text = elem.text.strip()
                    if len(text) > 100:  # ignore tiny snippets
                        description = text
                        break
                if description:
                    break
            except:
                continue

        # --- Strategy 2: Body-text heading extraction ---
        if not description:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                description = _extract_description_from_text(body_text)
            except:
                pass

        if description:
            print(f"  Description extracted successfully ({len(description)} chars)")
            details["description"] = description
        else:
            print(f"  Description not found")

    except Exception as e:
        print(f"  Detail fetch failed: {e}")
    finally:
        # Always return to the jobs list page
        try:
            driver.get(Config.JOBS_URL)
            time.sleep(6)
        except:
            pass

    return details

# ============================
# EMAIL NOTIFICATIONS
# ============================
def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _section_header(icon, title, color):
    return (
        f'<tr><td colspan="2" style="padding:14px 16px 6px;background:{color};'
        f'color:#fff;font-size:12px;font-weight:bold;'
        f'text-transform:uppercase;letter-spacing:1px;">'
        f'{icon}&nbsp; {title}</td></tr>'
    )

def _row(label, value, alt=False, bold_value=False):
    if not value:
        return ""
    bg   = "background:#f8f9fa;" if alt else "background:#fff;"
    bold = "font-weight:bold;" if bold_value else ""
    return (
        f"<tr>"
        f"<td style='padding:9px 16px;color:#555;width:200px;{bg}border-bottom:1px solid #eee;'>"
        f"<strong>{_esc(label)}</strong></td>"
        f"<td style='padding:9px 16px;{bg}{bold}border-bottom:1px solid #eee;'>{_esc(str(value))}</td>"
        f"</tr>"
    )

def create_email_html(project):
    title         = project.get('title', 'Untitled Job')
    url           = project.get('url', Config.DASHBOARD_URL)
    time_posted   = project.get('time_posted', '')
    detected_at   = project.get('detected_at', '')
    project_id    = project.get('id', '')
    description   = project.get('description', '')
    location      = project.get('location', '')
    budget        = project.get('budget', '') or 'Not provided'
    duration      = project.get('duration', '')

    hdr_grad   = "linear-gradient(135deg,#0056b3,#007bff)"
    sec_desc   = "#0056b3"
    sec_logist = "#004085"
    sec_budget = "#28a745"
    btn_color  = "#007bff"

    desc_html = ""
    if description:
        paragraphs = _esc(description).replace("\n\n", "|||").replace("\n", " ")
        paras = [f"<p style='margin:0 0 10px;'>{p}</p>" for p in paragraphs.split("|||")]
        desc_html = "".join(paras)

    desc_section = ""
    if desc_html:
        desc_section = (
            _section_header('📋', 'Description', sec_desc) +
            f"<tr><td colspan='2' style='padding:14px 16px;background:#f9fafb;"
            f"font-size:14px;line-height:1.75;color:#333;border-bottom:2px solid #e5e7eb;'>"
            f"{desc_html}</td></tr>"
        )

    logistics_rows = (
        _row("Location", location or "Not specified", alt=False) +
        _row("Job Type / Duration", duration or "Not specified", alt=True)
    )
    logistics_section = _section_header('📦', 'Job Details', sec_logist) + logistics_rows

    budget_section = (
        _section_header('💰', 'Compensation', sec_budget) +
        _row("Salary / Rate", budget, bold_value=True)
    )

    meta_rows = (
        _row("Posted",      time_posted if time_posted else "—", alt=False) +
        _row("Detected at", detected_at, alt=True) +
        _row("Job ID",      project_id, alt=False)
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#333;">
  <div style="max-width:700px;margin:30px auto;background:#fff;border-radius:10px;
       overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.12);">

    <div style="background:{hdr_grad};padding:24px 28px;">
      <p style="margin:0;color:rgba(255,255,255,0.75);font-size:11px;
          letter-spacing:1.5px;text-transform:uppercase;">MoveMeOn Job Monitor</p>
      <h2 style="margin:6px 0 0;color:#fff;font-size:24px;font-weight:700;">🚀 New Job Opportunity</h2>
    </div>

    <div style="padding:22px 28px 4px;">
      <h3 style="margin:0 0 10px;color:#1a252f;font-size:20px;line-height:1.4;">{_esc(title)}</h3>
    </div>

    <div style="padding:0 28px 28px;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;
             border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        {desc_section}
        {logistics_section}
        {budget_section}
        {_section_header('🕒', 'Detection Info', '#6b7280')}
        {meta_rows}
      </table>
      <div style="text-align:center;margin-top:28px;">
        <a href="{url}" style="display:inline-block;background:{btn_color};color:#fff;
                   padding:14px 36px;text-decoration:none;border-radius:6px;
                   font-weight:bold;font-size:15px;letter-spacing:0.3px;">
          View Full Job on MoveMeOn →
        </a>
      </div>
    </div>

    <div style="background:#f8f9fa;padding:14px 28px;border-top:1px solid #eee;
         font-size:12px;color:#999;text-align:center;">
      MoveMeOn Job Monitor &nbsp;|&nbsp; Automated alert &nbsp;|&nbsp; {detected_at}
    </div>
  </div>
</body></html>"""

def send_notification(project):
    """Send email notification for a new job"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 MoveMeOn: {project.get('title', 'New Job')}"
        msg["From"] = Config.SENDER_EMAIL
        msg["To"] = ", ".join(Config.RECIPIENT_EMAILS)
        
        msg.attach(MIMEText(create_email_html(project), "html"))
        
        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SENDER_EMAIL, Config.SENDER_PASSWORD)
            server.send_message(msg)
        
        print(f"📧 Email sent: {project.get('title', 'Unknown')[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False

# ============================
# DRIVER INITIALIZATION
# ============================
def _find_binary(env_var, candidates):
    import shutil
    val = os.getenv(env_var, "")
    if val and os.path.exists(val):
        return val
    for path in candidates:
        if os.path.exists(path):
            return path
    found = shutil.which(candidates[-1].split('/')[-1])
    return found or ""

def initialize_driver():
    import subprocess
    from selenium.webdriver.chrome.service import Service

    print("🔧 Initializing Chromium driver...", flush=True)

    chrome_bin = os.getenv("CHROME_BIN")
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")

    options = Options()

    if chrome_bin and os.path.exists(chrome_bin):
        print(f"Chrome binary override: {chrome_bin}", flush=True)
        options.binary_location = chrome_bin
        try:
            print(subprocess.check_output([chrome_bin, "--version"]).decode(), flush=True)
        except Exception as e:
            print(f"Chrome version check failed: {e}", flush=True)
    else:
        # Fallback to default linux paths if they exist
        for default_path in ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]:
            if os.path.exists(default_path):
                print(f"Found default Chrome binary: {default_path}", flush=True)
                options.binary_location = default_path
                break

    if chromedriver_path and os.path.exists(chromedriver_path):
        print(f"ChromeDriver override path: {chromedriver_path}", flush=True)
        service = Service(chromedriver_path)
        try:
            print(subprocess.check_output([chromedriver_path, "--version"]).decode(), flush=True)
        except Exception as e:
            print(f"ChromeDriver version check failed: {e}", flush=True)
    else:
        # Fallback to default linux paths if they exist
        default_driver = None
        for default_path in ["/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"]:
            if os.path.exists(default_path):
                default_driver = default_path
                break
        
        if default_driver:
            print(f"Found default ChromeDriver: {default_driver}", flush=True)
            service = Service(default_driver)
        else:
            print("Using default ChromeDriver via Selenium Manager", flush=True)
            service = Service()

    if Config.HEADLESS:
        options.add_argument("--headless=new")
    else:
        print("Running in headed mode (HEADLESS=False)", flush=True)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument(f"user-agent={USER_AGENT}")

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": USER_AGENT
    })
    return driver


def _navigate_to_search(driver):
    """Navigate to Curated Jobs page."""
    driver.get(Config.JOBS_URL)
    time.sleep(8)
    if "onboarding" in driver.current_url:
        print("  [Navigation] Redirected to onboarding page. Attempting to click 'Skip'...")
        try:
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
                print("  [Navigation] Clicked 'Skip' on onboarding page.")
                time.sleep(8)
            else:
                print("  [Navigation] Could not find 'Skip' button.")
        except Exception as e_skip:
            print(f"  [Navigation] Failed to skip onboarding: {e_skip}")

def setup_session(driver):
    """Setup browser session with cookies or login"""
    if load_cookies(driver):
        _navigate_to_search(driver)
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, JOB_SESSION_SELECTOR))
            )
            print("Logged in via cookies -> Curated Jobs")
            return True
        except Exception as e:
            print(f"Cookie session validation failed: {type(e).__name__}: {repr(e)}")
            _log_page_state(driver, "cookie session")
            _save_page_debug(driver, "cookie_session_failed")
            print("Cookies may be invalid, expired, or page did not render as expected.")
    return perform_login(driver)

# ============================
# MAIN MONITORING LOOP
# ============================
def main():
    print("=" * 50)
    print(f"🚀 {Config.PLATFORM_NAME.capitalize()} Job Monitor")
    print("=" * 50)
    
    driver = initialize_driver()
    
    try:
        if not setup_session(driver):
            print("❌ Failed to establish session")
            print(
                "Login/session failed. Check movemeon_login_failed.png/html "
                "or cookie_session_failed.png/html on the server."
            )
            return
        
        init_db()
        seen_ids = get_seen_ids()
        print(f"📁 DB loaded — {len(seen_ids)} jobs on record\n")

        # ── STARTUP RECONCILIATION ───────────────────────────────────────────
        print(f"⚙️  Startup — reconciling current page silently (no emails sent)...")
        seed_projects = scan_for_projects(driver)
        if seed_projects:
            bulk_insert_projects(seed_projects, emailed=False)
            seen_ids = get_seen_ids()
            print(f"✅ Reconciled — {len(seed_projects)} jobs saved to DB. Only NEW posts will trigger emails.\n")
        else:
            print("⚠️  Could not reconcile on startup — will retry next cycle.\n")

        check_count = 0
        while True:
            try:
                check_count += 1
                print(f"\n{'='*30}")
                print(f"🔄 Check #{check_count} - {datetime.now(PKT).strftime('%H:%M:%S')} PKT")
                print(f"{'='*30}")

                _navigate_to_search(driver)
                all_projects = scan_for_projects(driver)

                if not all_projects:
                    print("⚠️ No jobs found")
                    time.sleep(Config.CHECK_INTERVAL)
                    continue

                new_projects = filter_new_projects(all_projects, seen_ids)

                if new_projects:
                    print(f"🎯 Found {len(new_projects)} NEW job(s)!")
                    for project in new_projects:
                        print(f"  → {project['title'][:60]}...")
                        # Fetch full description from detail page before emailing
                        details = fetch_job_details(driver, project['url'])
                        project.update(details)
                        
                        # Send email AFTER description is fetched
                        emailed = send_notification(project)
                        # Insert into DB AFTER email attempt
                        insert_project(project, emailed=emailed)
                        seen_ids.add(project['id'])
                    
                    # After processing all new jobs, return to jobs list
                    _navigate_to_search(driver)
                else:
                    print("⏳ No new jobs")

                print(f"📊 Stats: {len(all_projects)} visible, {len(seen_ids)} in DB")
                time.sleep(Config.CHECK_INTERVAL)

            except KeyboardInterrupt:
                raise
            except Exception as loop_err:
                print(f"⚠️ Check failed: {loop_err} — retrying...")
                time.sleep(Config.CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n⏹️ Stopped by user")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
