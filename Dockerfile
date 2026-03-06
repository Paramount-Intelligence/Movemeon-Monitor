FROM python:3.11-slim-bookworm

# Install Chromium (multi-arch: works on amd64 AND arm64)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    xdg-utils \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Bake in the Chromium paths so they are available at runtime
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache the chromedriver so the first run doesn't need to download it
RUN python -c "\
from webdriver_manager.chrome import ChromeDriverManager; \
from webdriver_manager.core.os_manager import ChromeType; \
path = ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install(); \
print('Chromedriver cached at:', path)" || true

COPY script_clean.py .
COPY catalant_cookies.json .

# Force headless — no display available on a server
ENV HEADLESS=True

CMD ["python", "-u", "script_clean.py"]
