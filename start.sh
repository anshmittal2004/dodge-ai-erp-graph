#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Dodge AI ERP — Start backend + frontend in one command
# Usage: bash start.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

GREEN="\033[32m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

# Load env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo -e "${BOLD}${CYAN}Starting Dodge AI ERP Graph System...${RESET}"

# Kill any existing backend on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Start backend
cd backend
echo -e "${GREEN}▶ Starting backend on http://localhost:8000${RESET}"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# Wait for backend to be ready
echo -n "  Waiting for backend"
for i in $(seq 1 15); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e " ${GREEN}✅${RESET}"
        break
    fi
    echo -n "."
    sleep 1
done

# Open frontend
echo -e "${GREEN}▶ Opening frontend...${RESET}"
if command -v xdg-open &> /dev/null; then
    xdg-open frontend/index.html
elif command -v open &> /dev/null; then
    open frontend/index.html
else
    echo "  Open frontend/index.html in your browser"
fi

echo ""
echo -e "${BOLD}System running:${RESET}"
echo -e "  Backend API:  ${CYAN}http://localhost:8000${RESET}"
echo -e "  API Docs:     ${CYAN}http://localhost:8000/docs${RESET}"
echo -e "  Frontend:     ${CYAN}frontend/index.html${RESET}"
echo ""
echo "Press Ctrl+C to stop."

# Wait for backend
wait $BACKEND_PID
