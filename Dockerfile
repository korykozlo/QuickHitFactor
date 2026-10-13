# ────────────────────────────────────────────────────────────────────────
# Base image – use official Node LTS (includes npm) on Debian
# ────────────────────────────────────────────────────────────────────────
FROM node:20-slim AS base

# Install system dependencies required by Playwright & Chromium
#   - ca-certificates, fonts, libgbm, libasound2, libx11‑dev, etc.
#   - Also install python3 and pip for the helper script
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    libgbm1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgcc1 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxshmfence1 \
    libxss1 \
    libxtst6 \
    python3 \
    python3-pip \
    python3-venv && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# ────────────────────────────────────────────────────────────────────────
# Install Node dependencies
# ────────────────────────────────────────────────────────────────────────
COPY package*.json ./
RUN npm install --production

# Install Python dependencies in a virtual environment
COPY tools/requirements.txt tools/requirements.txt
RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --no-cache-dir -r tools/requirements.txt && \
    /app/venv/bin/python -m playwright install chromium

# Copy source files
COPY . .

# ────────────────────────────────────────────────────────────────────────
# Expose the port the server listens on (default 8000)
# ────────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ────────────────────────────────────────────────────────────────────────
# Runtime command – start the Node server
# ────────────────────────────────────────────────────────────────────────
CMD ["node", "server/server.js"]
