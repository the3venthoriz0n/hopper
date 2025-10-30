#!/bin/bash

echo "🚀 Setting up Hopper..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from example..."
    cp env.example .env
    echo "⚠️  Please edit .env and add your YouTube API credentials"
    echo ""
fi

# Setup backend
echo "🐍 Setting up Python backend..."
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt
cd ..

# Setup frontend
echo "📦 Setting up Node.js frontend..."
cd frontend
npm install
cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your YouTube API credentials"
echo "2. Run the backend: cd backend && source venv/bin/activate && uvicorn main:app --reload"
echo "3. Run the frontend: cd frontend && npm run dev"
echo ""
echo "Or use Docker: docker-compose up"

