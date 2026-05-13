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

This repository is ready for **Railway.app**:
1. Connect this repo to Railway.
2. Add all variables from `.env` to the Railway service settings.
3. Railway will automatically use the `Dockerfile` to build and run the monitor.

## Manual Actions
- After login: Wait until the current URL contains: `dashboard/candidate/jobs`
