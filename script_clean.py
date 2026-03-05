import time
import smtplib
import json
import os
import re
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
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================
# CONFIGURATION
# ============================
class Config:
    """Load configuration from environment variables"""
    CATALANT_EMAIL = os.getenv("CATALANT_EMAIL")
    CATALANT_PASSWORD = os.getenv("CATALANT_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    RECIPIENT_EMAILS = [e.strip() for e in os.getenv("RECIPIENT_EMAILS", "ahmedghazi459@gmail.com,ahsanuddin3522@gmail.com,muhammad.abdullahds1@gmail.com").split(",") if e.strip()]
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
    MAX_AGE_MINUTES = int(os.getenv("MAX_AGE_MINUTES", 60))
    HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"
    COOKIES_FILE = os.getenv("COOKIES_FILE", "catalant_cookies.json")
    MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# ============================
# SESSION MANAGEMENT
# ============================
def save_cookies(driver):
    """Save session cookies to file"""
    try:
        with open(Config.COOKIES_FILE, 'w') as f:
            json.dump(driver.get_cookies(), f)
        return True
    except Exception:
        return False

def load_cookies(driver):
    """Load cookies from file"""
    if not os.path.exists(Config.COOKIES_FILE):
        return False
    try:
        with open(Config.COOKIES_FILE, 'r') as f:
            cookies = json.load(f)
        driver.get("https://app.gocatalant.com")
        time.sleep(2)
        driver.delete_all_cookies()
        for cookie in cookies:
            if 'domain' in cookie and '.gocatalant.com' in cookie['domain']:
                driver.add_cookie(cookie)
        return True
    except Exception:
        return False

def perform_login(driver):
    """Perform login to Catalant"""
    try:
        driver.get("https://app.gocatalant.com/c/_/u/0/dashboard/")
        time.sleep(3)
        
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        
        driver.find_element(By.NAME, "email").send_keys(Config.CATALANT_EMAIL)
        driver.find_element(By.NAME, "password").send_keys(Config.CATALANT_PASSWORD)
        driver.find_element(By.XPATH, "//button[contains(text(), 'Login') or @type='submit']").click()
        
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".need-card-inline-name"))
        )
        
        save_cookies(driver)
        # Navigate to Search Projects page after login
        driver.get(SEARCH_URL)
        time.sleep(3)
        print(f"✅ Login successful → {SEARCH_URL}")
        return True
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False

# ============================
# PROJECT EXTRACTION
# ============================
def extract_project_data(card):
    """Extract data from a project card - returns None if invalid"""
    try:
        # Required: Title
        title_elem = card.find_element(By.CSS_SELECTOR, ".need-card-inline-name .line-clamp-2")
        title = title_elem.text.strip()
        if not title:
            return None
        
        # Required: Project ID
        try:
            like_button = card.find_element(By.CSS_SELECTOR, "[data-ajax-post*='need/']")
            match = re.search(r'/need/([^/]+)/', like_button.get_attribute("data-ajax-post"))
            if not match:
                return None
            project_id = match.group(1)
        except:
            return None
        
        # Optional fields with safe fallbacks
        categories = []
        try:
            cat_text = card.find_element(By.CSS_SELECTOR, ".need-card-inline-pools .small.text-muted").text.strip()
            categories = [c.strip() for c in cat_text.split("|") if c.strip()]
        except:
            pass
        
        description = ""
        try:
            description = card.find_element(By.CSS_SELECTOR, ".need-card-inline-details .line-clamp-2").text.strip()
        except:
            pass
        
        location = ""
        try:
            loc_text = card.find_element(By.CSS_SELECTOR, ".text-gray-25.font-weight-semibold").text.strip()
            location = loc_text if loc_text else ""
        except:
            pass

        time_posted = "Unknown"
        try:
            time_elems = card.find_elements(By.XPATH, ".//div[contains(@class, 'small') and contains(@class, 'text-gray-20') and contains(@class, 'mt-1')]//span[contains(text(), 'Posted')]")
            if time_elems:
                time_posted = time_elems[0].text.replace("Posted", "").replace("ago", "").strip()
        except:
            pass

        # Optional: Budget
        budget = ""
        try:
            budget = card.find_element(By.CSS_SELECTOR, ".need-card-inline-budget").text.strip()
        except:
            pass
        if not budget:
            try:
                for el in card.find_elements(By.XPATH, ".//*[contains(text(),'$')]"):
                    t = el.text.strip()
                    if '$' in t and len(t) < 60:
                        budget = t
                        break
            except:
                pass

        # Optional: Duration / Project Length
        duration = ""
        try:
            duration = card.find_element(By.CSS_SELECTOR, ".need-card-inline-duration").text.strip()
        except:
            pass
        if not duration:
            try:
                for el in card.find_elements(By.XPATH, ".//span[contains(@class,'text-gray') or contains(@class,'small')]"):
                    t = el.text.strip()
                    if any(w in t.lower() for w in ("week", "month", "day")) and 2 < len(t) < 40:
                        duration = t
                        break
            except:
                pass

        status = "Posted"
        try:
            card.find_element(By.CSS_SELECTOR, ".badge-success")
            status = "New Project"
        except:
            pass

        # Optional: Direct project URL
        url = f"https://app.gocatalant.com/c/_/u/0/need/{project_id}/"
        try:
            link = card.find_element(By.CSS_SELECTOR, "a[href*='need']")
            href = link.get_attribute("href") or ""
            if href and "need" in href:
                url = href
        except:
            pass

        return {
            "id": project_id,
            "title": title,
            "location": location,
            "budget": budget,
            "duration": duration,
            "time_posted": time_posted,
            "status": status,
            "url": url,
            "detected_at": datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S")
        }
    except:
        return None

def scan_for_projects(driver):
    """Scan Search Projects page for project cards - returns only valid projects"""
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".need-card-inline-name"))
        )
        
        # Get all card blocks
        all_cards = driver.find_elements(By.CSS_SELECTOR, "div.card-block")
        
        # Filter to only those with project content
        project_cards = [c for c in all_cards if c.find_elements(By.CSS_SELECTOR, ".need-card-inline")]
        
        projects = []
        for card in project_cards:
            project = extract_project_data(card)
            if project and project.get('title') and project.get('id'):
                projects.append(project)
        
        print(f"✅ Extracted {len(projects)} valid projects")
        return projects
    except TimeoutException:
        print("⏳ Timeout waiting for projects")
        return []
    except Exception as e:
        print(f"❌ Error scanning: {e}")
        return []

# ============================
# PROJECT DATABASE (MongoDB)
# ============================
_mongo_client = None

def _get_collection():
    """Return the MongoDB collection, reusing the client across calls."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(Config.MONGO_URI)
    return _mongo_client["office_monitor"]["catalant_projects"]

def init_db():
    """Ensure a unique index on 'id' exists (no-op if already created by setup_mongo.py)."""
    try:
        _get_collection().create_index("id", unique=True, name="idx_id_unique")
    except Exception:
        pass  # Index already exists — safe to ignore

def db_is_cold_start():
    """True if the collection has no documents (first ever run)."""
    return _get_collection().find_one({}, {"_id": 1}) is None

def get_seen_ids():
    """Return set of all project IDs already in DB."""
    try:
        docs = _get_collection().find({}, {"id": 1, "_id": 0})
        return {d["id"] for d in docs}
    except Exception:
        return set()

def insert_project(project, emailed=True):
    """Upsert one project record. Silently skips if ID already exists."""
    try:
        doc = {
            "id":          project.get("id"),
            "title":       project.get("title"),
            "location":    project.get("location"),
            "budget":      project.get("budget"),
            "duration":    project.get("duration"),
            "time_posted": project.get("time_posted"),
            "status":      project.get("status"),
            "url":         project.get("url"),
            "detected_at": project.get("detected_at"),
            "platform":    "catalant",
            "emailed":     emailed,
        }
        _get_collection().update_one(
            {"id": doc["id"]},
            {"$setOnInsert": doc},
            upsert=True,
        )
    except Exception as e:
        print(f"⚠️ DB insert failed: {e}")

def bulk_insert_projects(projects, emailed=False):
    """Upsert many projects at once (used for cold-start seeding)."""
    try:
        ops = []
        for p in projects:
            if not p.get("id"):
                continue
            doc = {
                "id":          p.get("id"),
                "title":       p.get("title"),
                "location":    p.get("location"),
                "budget":      p.get("budget"),
                "duration":    p.get("duration"),
                "time_posted": p.get("time_posted"),
                "status":      p.get("status"),
                "url":         p.get("url"),
                "detected_at": p.get("detected_at"),
                "platform":    "catalant",
                "emailed":     emailed,
            }
            ops.append(UpdateOne({"id": doc["id"]}, {"$setOnInsert": doc}, upsert=True))
        if ops:
            result = _get_collection().bulk_write(ops, ordered=False)
            print(f"  DB: inserted {result.upserted_count} records (emailed={'yes' if emailed else 'no'})")
    except Exception as e:
        print(f"⚠️ DB bulk insert failed: {e}")

def parse_posted_minutes(time_str):
    """Convert a scraped 'time_posted' string into minutes. Returns None if unparseable."""
    if not time_str or time_str == "Unknown":
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
# EMAIL NOTIFICATIONS
# ============================
def create_email_html(project):
    """Create HTML email for a project"""
    # ---- dynamic blocks ----
    status        = project.get('status', 'Posted')
    location      = project.get('location', '') or 'Remote / Not specified'
    time_posted   = project.get('time_posted', 'Unknown')
    budget        = project.get('budget', '')
    duration      = project.get('duration', '')
    detected_at   = project.get('detected_at', '')
    project_id    = project.get('id', 'N/A')
    title         = project.get('title', 'Untitled Project')
    url           = project.get('url', 'https://app.gocatalant.com/c/_/u/0/dashboard/')

    status_badge = "<span style='background:#e74c3c;color:white;padding:4px 10px;border-radius:3px;font-size:12px;font-weight:bold;'>🆕 New Project</span>" if status == 'New Project' else ""

    budget_row   = f"<tr><td style='padding:6px 10px;color:#555;width:160px;'>💰 <strong>Budget</strong></td><td style='padding:6px 10px;color:#27ae60;font-weight:bold;'>{budget}</td></tr>" if budget else ""
    duration_row = f"<tr><td style='padding:6px 10px;color:#555;'>⏱️ <strong>Duration</strong></td><td style='padding:6px 10px;'>{duration}</td></tr>" if duration else ""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,sans-serif;color:#333;">
        <div style="max-width:680px;margin:30px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.12);">

            <!-- Header -->
            <div style="background:linear-gradient(135deg,#1a6b3c,#27ae60);padding:22px 28px;">
                <p style="margin:0;color:rgba(255,255,255,0.8);font-size:13px;letter-spacing:1px;text-transform:uppercase;">Catalant Project Monitor</p>
                <h2 style="margin:6px 0 0;color:#fff;font-size:20px;">🚀 New Project Alert</h2>
            </div>

            <!-- Body -->
            <div style="padding:24px 28px;">

                <!-- Title + badge -->
                <h3 style="margin:0 0 10px;color:#1a252f;font-size:18px;line-height:1.4;">{title}</h3>
                {status_badge}

                <!-- Key info table -->
                <div style="margin:18px 0;border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;">
                    <table style="width:100%;border-collapse:collapse;font-size:14px;">
                        <tr style="background:#f8f9fa;">
                            <td style="padding:6px 10px;color:#555;width:160px;">📍 <strong>Location</strong></td>
                            <td style="padding:6px 10px;">{location}</td>
                        </tr>
                        <tr>
                            <td style="padding:6px 10px;color:#555;">⏰ <strong>Posted</strong></td>
                            <td style="padding:6px 10px;">{time_posted} ago</td>
                        </tr>
                        {budget_row}
                        {duration_row}
                        <tr style="background:#f8f9fa;">
                            <td style="padding:6px 10px;color:#555;">🕒 <strong>Detected at</strong></td>
                            <td style="padding:6px 10px;">{detected_at}</td>
                        </tr>
                        <tr>
                            <td style="padding:6px 10px;color:#555;">🆔 <strong>Project ID</strong></td>
                            <td style="padding:6px 10px;font-family:monospace;font-size:13px;color:#888;">{project_id}</td>
                        </tr>
                    </table>
                </div>

                <!-- CTA -->
                <div style="text-align:center;margin-top:22px;">
                    <a href="{url}"
                       style="display:inline-block;background:#27ae60;color:#fff;padding:13px 32px;text-decoration:none;border-radius:6px;font-weight:bold;font-size:15px;">
                        View Project →
                    </a>
                </div>
            </div>

            <!-- Footer -->
            <div style="background:#f8f9fa;padding:14px 28px;border-top:1px solid #eee;font-size:12px;color:#999;text-align:center;">
                Catalant Project Monitor &nbsp;|&nbsp; Auto-notification &nbsp;|&nbsp; {detected_at}
            </div>
        </div>
    </body>
    </html>
    """

def send_notification(project):
    """Send email notification for a new project"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔔 Catalant: {project.get('title', 'New Project')}"
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
def initialize_driver():
    """Initialize Chrome WebDriver"""
    options = Options()
    if Config.HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    return driver

SEARCH_URL = "https://app.gocatalant.com/c/_/u/0/search/?form_name=SearchForm&enable_pagination=True&enable_facets=True&card_action_show_need=True&use_recommended=y&display_result_count=True"

def setup_session(driver):
    """Setup browser session with cookies or login"""
    if load_cookies(driver):
        driver.get(SEARCH_URL)
        time.sleep(8)
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".need-card-inline-name"))
            )
            print(f"✅ Logged in via cookies → {SEARCH_URL}")
            return True
        except:
            pass
    
    return perform_login(driver)

# ============================
# MAIN MONITORING LOOP
# ============================
def main():
    """Main monitoring loop"""
    print("=" * 50)
    print("🚀 Catalant Project Monitor")
    print("=" * 50)
    
    driver = initialize_driver()
    
    try:
        if not setup_session(driver):
            print("❌ Failed to establish session")
            return
        
        cold_start = db_is_cold_start()
        init_db()
        seen_ids = get_seen_ids()
        print(f"📁 DB loaded — {len(seen_ids)} projects on record\n")

        # ── STARTUP RECONCILIATION ───────────────────────────────────────────
        # Jobs ≤12h old  → insert to DB silently (no email)
        # Jobs  >12h old → add to seen_ids in-memory only (no DB insert, no email)
        # This ensures NOTHING currently on the page ever triggers an email.
        # Only jobs that appear AFTER this startup scan will be emailed.
        SEED_MAX_AGE_MINUTES = 720  # 12 hours
        label = "First run" if cold_start else "Restart"
        print(f"⚙️  {label} — reconciling current page silently (no emails sent)...")
        seed_projects = scan_for_projects(driver)
        if seed_projects:
            recent, old = [], []
            for p in seed_projects:
                age = parse_posted_minutes(p.get("time_posted", ""))
                if age is None or age <= SEED_MAX_AGE_MINUTES:
                    recent.append(p)
                else:
                    old.append(p)
            bulk_insert_projects(recent, emailed=False)
            seen_ids = get_seen_ids()
            # Also mark old jobs as seen in-memory so they never trigger an email
            for p in old:
                if p.get("id"):
                    seen_ids.add(p["id"])
            print(f"✅ Reconciled — {len(recent)} recent (saved to DB), {len(old)} old (ignored). Only NEW posts will trigger emails.\n")
        else:
            print("⚠️  Could not reconcile on startup — will retry next cycle.\n")
        # ─────────────────────────────────────────────────────────────────────

        check_count = 0
        while True:
            try:
                check_count += 1
                print(f"\n{'='*30}")
                print(f"🔄 Check #{check_count} - {datetime.now(PKT).strftime('%H:%M:%S')} PKT")
                print(f"{'='*30}")

                driver.get(SEARCH_URL)
                time.sleep(8)

                all_projects = scan_for_projects(driver)

                if not all_projects:
                    print("⚠️ No projects found")
                    time.sleep(Config.CHECK_INTERVAL)
                    continue

                new_projects = filter_new_projects(all_projects, seen_ids)

                if new_projects:
                    print(f"🎯 Found {len(new_projects)} NEW project(s)!")
                    for project in new_projects:
                        print(f"  → {project['title'][:60]}...")
                        emailed = send_notification(project)
                        insert_project(project, emailed=emailed)
                        seen_ids.add(project['id'])
                else:
                    print("⏳ No new projects")

                print(f"📊 Stats: {len(all_projects)} visible, {len(seen_ids)} in DB")
                print(f"\n⏳ Next check in {Config.CHECK_INTERVAL} seconds...")
                time.sleep(Config.CHECK_INTERVAL)

            except KeyboardInterrupt:
                raise
            except Exception as loop_err:
                print(f"⚠️ Check failed: {loop_err} — retrying in {Config.CHECK_INTERVAL}s...")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(Config.CHECK_INTERVAL)
                driver = initialize_driver()
                if not setup_session(driver):
                    print("❌ Re-login failed — will retry next cycle")
            
    except KeyboardInterrupt:
        print("\n\n⏹️ Stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        driver.quit()
        print("✅ Monitor stopped")

if __name__ == "__main__":
    main()
