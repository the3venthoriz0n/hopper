# 🎥 Hopper

Drag videos, upload to YouTube. Simple as that.

## Setup

### 1. YouTube API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project
3. Enable **YouTube Data API v3**
4. Create **OAuth 2.0 Client ID** (Web application)
5. Add redirect URI: `http://localhost:8000/api/auth/youtube/callback`
6. Download JSON → save as `backend/client_secrets.json`

### 2. Run

```bash
docker compose up
```

Open http://localhost:3000

## Usage

1. Click "Connect" next to YouTube
2. Authorize the app
3. Toggle YouTube ON
4. Drag videos into the drop zone
5. Click "Upload to YouTube"

Done! Videos upload as private.

## Structure

```
hopper/
├── backend/
│   ├── main.py              # API (150 lines)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.js           # UI (170 lines)
│       └── App.css
└── docker-compose.yml
```

## What's Next

Add these features later:
- More platforms (TikTok, Instagram, Twitter)
- Upload scheduling
- Custom titles/descriptions
- Progress tracking

## License

MIT

