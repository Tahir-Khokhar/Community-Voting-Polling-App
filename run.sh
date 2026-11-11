#!/usr/bin/env bash
# One-command launcher for the Community Voting & Polling App.
# Installs dependencies if needed, ensures the database exists, starts the server.
set -e
cd "$(dirname "$0")"

# 1. Dependencies
python3 -c "import django" 2>/dev/null || {
    echo ">> Installing dependencies (first run only)..."
    pip3 install -r requirements.txt
}

# 2. Database (creates db.sqlite3 + tables if missing; no-op if present)
python3 manage.py migrate --noinput

# 3. Seed demo data if the database is empty (first run only)
POLL_COUNT=$(python3 manage.py shell -c "from polls.models import Poll; print(Poll.objects.count())" 2>/dev/null | tail -1)
if [ "$POLL_COUNT" = "0" ]; then
    echo ">> Seeding demo polls..."
    python3 manage.py seed_polls
fi

# 4. Start the dev server
echo ""
echo "================================================"
echo "  Polling app running at http://127.0.0.1:8000"
echo "  Demo login: demo / demo1234"
echo "  Press Ctrl+C to stop."
echo "================================================"
echo ""
python3 manage.py runserver
