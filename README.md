# MoveMeOn Job Monitor

A clean, robust Selenium-based monitoring system for the MoveMeOn portal, featuring automated two-step authentication and email notifications.

## Features

- **Platform Specific**: Tailored for the MoveMeOn "Discover Jobs" portal.
- **Two-Step Auth**: Automatically handles the dynamic Email -> Password login flow.
- **Session Persistence**: Saves both Cookies and LocalStorage to MongoDB for stable, long-term monitoring.
- **Manual Fallback**: Support for manual login/CAPTCHA resolution if needed.
- **Smart Notifications**: Sends branded HTML emails for newly detected jobs.
- **Railway Ready**: Optimized for 24/7 deployment on Railway or similar container platforms.

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file based on `.env.example`.

### 3. Initialize Database
```bash
python init_db_movemeon.py
```

### 4. Refresh Session
Before starting the monitor, run the cookie saver to establish your session:
```bash
python save_movemeon_cookies.py
```

### 5. Start Monitoring
```bash
python movemeon_monitor.py
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MOVEMEON_EMAIL` | Your MoveMeOn login email |
| `MOVEMEON_PASSWORD` | Your MoveMeOn login password |
| `MONGO_URI` | Connection string for MongoDB |
| `SENDER_EMAIL` | Gmail/SMTP address for notifications |
| `SENDER_PASSWORD` | App Password for the sender email |
| `RECIPIENT_EMAILS` | Comma-separated list of alert recipients |
| `HEADLESS` | Set to `True` for server deployment |

## Deployment

### Coolify / Contabo (Docker Compose — recommended)

Deploy this as a **Docker Compose resource** in Coolify, not a Dockerfile-only app. Chrome runs in a separate `selenium-chrome` container with noVNC; the app container connects via `SELENIUM_REMOTE_URL`.

1. Create a Docker Compose resource pointing at this repo.
2. Copy variables from `.env.example` into Coolify (see below).
3. Expose port **7900** for noVNC (Selenium port 4444 stays internal only).
4. Open noVNC in your browser:
   `http://SERVER_IP:7900/?autoconnect=1&resize=scale&password=<SE_VNC_PASSWORD>`
5. Manually open Movemeon inside noVNC once and check whether the Vercel checkpoint passes.
6. If it passes, log in manually and let the persistent Chrome profile save the session.
7. Restart only the `movemeon-monitor` service so the monitor uses the saved profile.
8. If noVNC still shows **Vercel Security Checkpoint Code 11**, the Contabo IP/browser fingerprint is blocked — code changes cannot bypass that.

### Railway (legacy single-container)

This repository can still run on **Railway.app** without remote Selenium if you install Chromium in the image and omit `SELENIUM_REMOTE_URL`:

1. Connect this repo to Railway.
2. Add all variables from `.env` to the Railway service settings.
3. Railway will use the `Dockerfile` to build and run the monitor (local Chrome mode).

## Manual Actions
- After login: Wait until the current URL contains: `dashboard/candidate/jobs`
