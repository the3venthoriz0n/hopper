@echo off
echo Setting up Hopper...

REM Check if .env exists
if not exist .env (
    echo Creating .env file from example...
    copy env.example .env
    echo Please edit .env and add your YouTube API credentials
    echo.
)

REM Setup backend
echo Setting up Python backend...
cd backend
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements.txt
cd ..

REM Setup frontend
echo Setting up Node.js frontend...
cd frontend
call npm install
cd ..

echo.
echo Setup complete!
echo.
echo Next steps:
echo 1. Edit .env and add your YouTube API credentials
echo 2. Run the backend: cd backend ^&^& venv\Scripts\activate ^&^& uvicorn main:app --reload
echo 3. Run the frontend: cd frontend ^&^& npm run dev
echo.
echo Or use Docker: docker-compose up
pause

