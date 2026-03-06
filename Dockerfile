FROM python:3.11-slim-bookworm

# Install Chromium — apt resolves all dependencies automatically (multi-arch: amd64 + arm64)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Bake in the Chromium paths so they are available at runtime
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV HEADLESS=True

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY script_clean.py .
COPY catalant_cookies.json .

CMD ["python", "-u", "script_clean.py"]
