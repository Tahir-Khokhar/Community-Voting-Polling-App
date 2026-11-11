@echo off
REM One-command launcher for the Community Voting & Polling App (Windows).
cd /d "%~dp0"

REM 1. Dependencies
python -c "import django" 2>nul
if errorlevel 1 (
    echo >> Installing dependencies (first run only)...
    pip install -r requirements.txt
)

REM 2. Database
python manage.py migrate --noinput

REM 3. Seed demo data if empty (first run only)
for /f %%i in ('python -c "from polls.models import Poll; print(Poll.objects.count())" 2^>nul') do set PCOUNT=%%i
if "%PCOUNT%"=="0" (
    echo >> Seeding demo polls...
    python manage.py seed_polls
)

REM 4. Start the dev server
echo.
echo ================================================
echo   Polling app running at http://127.0.0.1:8000
echo   Demo login: demo / demo1234
echo   Press Ctrl+C to stop.
echo ================================================
echo.
python manage.py runserver
