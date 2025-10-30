# 🎥 Hopper

Dead simple video uploader for YouTube.

## What it does

1. Connect to YouTube
2. Drag videos in
3. Upload

That's it.

## Setup

### 1. Get YouTube API Credentials

Go to [Google Cloud Console](https://console.cloud.google.com/):
- Create a project
- Enable YouTube Data API v3
- Create OAuth 2.0 credentials (Web application)
- Add redirect URI: `http://localhost:8000/api/youtube/callback`
- Download as `backend/client_secrets.json`

### 2. Run

**Option A: Docker (recommended)**
```bash
docker-compose up
```

**Option B: Local**
```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py

# Frontend (new terminal)
cd frontend
npm install
npm start
```

Open http://localhost:3000

## Usage

1. Click "Connect YouTube"
2. Authorize the app
3. Drag video files into the drop zone
4. Click "Upload to YouTube"

Videos upload as private by default.

## Structure

```
hopper/
├── backend/
│   ├── main.py          # All backend code
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.js       # All frontend code
│       └── App.css
└── docker-compose.yml
```

## Coming Later

- Multiple destinations (TikTok, Instagram, etc.)
- Upload scheduling
- Title/description templates
- Progress tracking

## License

MIT
