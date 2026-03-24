#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Dodge AI ERP Graph System — One-click setup
# Usage: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║     Dodge AI — ERP Graph Intelligence System         ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── Check Python ─────────────────────────────────────────────────────────────
echo -e "${BOLD}[1/5] Checking Python version...${RESET}"
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo -e "${RED}❌ Python 3 not found. Please install Python 3.11+${RESET}"
    exit 1
fi
PYVER=$($PYTHON --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✅ Found Python ${PYVER}${RESET}"

# ── .env setup ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[2/5] Setting up environment...${RESET}"
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${YELLOW}⚠️  Created .env from template.${RESET}"
    echo ""
    echo -e "${BOLD}Please set your GEMINI_API_KEY in .env${RESET}"
    echo -e "  Get a free key at: ${CYAN}https://ai.google.dev${RESET}"
    echo ""
    read -p "Enter your Gemini API key now (or press Enter to skip): " KEY
    if [ -n "$KEY" ]; then
        sed -i "s/your_gemini_api_key_here/$KEY/" .env
        echo -e "${GREEN}✅ API key saved to .env${RESET}"
    else
        echo -e "${YELLOW}⚠️  No key set — system will run in offline mode (limited NL queries)${RESET}"
    fi
else
    echo -e "${GREEN}✅ .env already exists${RESET}"
fi

# ── Install Python deps ───────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[3/5] Installing Python dependencies...${RESET}"
cd backend
$PYTHON -m pip install -r requirements.txt --quiet
echo -e "${GREEN}✅ Dependencies installed${RESET}"

# ── Initialize database ───────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[4/5] Initializing database...${RESET}"
$PYTHON -c "from db import init_db; init_db()"
echo -e "${GREEN}✅ Database ready${RESET}"
cd ..

# ── Raw data check ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[5/5] Checking for additional data...${RESET}"
if [ -d "raw_data" ] && [ "$(ls -A raw_data 2>/dev/null)" ]; then
    echo -e "${CYAN}Found raw_data/ folder — running data loader...${RESET}"
    cd backend
    $PYTHON data_loader.py
    $PYTHON -c "from db import init_db; init_db()"
    cd ..
    echo -e "${GREEN}✅ Full dataset loaded${RESET}"
else
    echo -e "${YELLOW}ℹ️  No raw_data/ folder found — using uploaded dataset (12 tables)${RESET}"
    echo -e "   To add the full Google Drive dataset, see README.md"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  ✅ Setup complete! Start the system:                ║${RESET}"
echo -e "${BOLD}${GREEN}║                                                      ║${RESET}"
echo -e "${BOLD}${GREEN}║  Backend:  cd backend && uvicorn main:app --port 8000║${RESET}"
echo -e "${BOLD}${GREEN}║  Frontend: open frontend/index.html                  ║${RESET}"
echo -e "${BOLD}${GREEN}║                                                      ║${RESET}"
echo -e "${BOLD}${GREEN}║  Or run both at once:  bash start.sh                 ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
