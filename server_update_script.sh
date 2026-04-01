#!/bin/bash

# --- CONFIGURATION ---
APP_DIR="/home/ubuntu/Structure-Comparision"
VENV_PYTHON="$APP_DIR/rtstructcomp-env/bin/python3"
GUNICORN_SERVICE="gunicorn"
NGINX_SERVICE="nginx"

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}==> Starting automated update for compare.chavi.ai...${NC}"

# 1. MOVE TO PROJECT DIRECTORY
cd $APP_DIR || { echo -e "${RED}[ERROR] Directory not found!${NC}"; exit 1; }

# 2. PULL LATEST CHANGES
echo -e "${GREEN}--> Pulling changes from GitHub...${NC}"
git pull origin main

# 3. INSTALL REQUIREMENTS (Using the direct venv python to avoid PEP 668 error)
echo -e "${GREEN}--> Updating dependencies...${NC}"
$VENV_PYTHON -m pip install -r requirements.txt

# 4. DATABASE MIGRATIONS
echo -e "${GREEN}--> Checking for database migrations...${NC}"
$VENV_PYTHON manage.py makemigrations --noinput
$VENV_PYTHON manage.py migrate --noinput

# 5. COLLECT STATIC FILES
echo -e "${GREEN}--> Collecting static files...${NC}"
$VENV_PYTHON manage.py collectstatic --noinput

# 6. RESTART SERVICES
echo -e "${GREEN}--> Restarting Gunicorn & Nginx...${NC}"
sudo systemctl restart $GUNICORN_SERVICE
sudo systemctl restart $NGINX_SERVICE

# 7. FINAL STATUS CHECK
if systemctl is-active --quiet $GUNICORN_SERVICE; then
    echo -e "${GREEN}==> [SUCCESS] Application updated and services restarted.${NC}"
else
    echo -e "${RED}==> [ERROR] Gunicorn failed to restart correctly.${NC}"
    exit 1
fi