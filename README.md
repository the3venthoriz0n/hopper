# 🎥 Hopper

**Simple video uploader for YouTube** - drag, drop, and upload videos automatically.

## Features

- 🎯 **Super Simple** - Just connect and upload
- 📤 **Drag & Drop** - Add videos easily
- ▶️ **YouTube** - OAuth integration
- 🐳 **Docker Ready** - Run anywhere

## Quick Start

### 1. Get YouTube API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable **YouTube Data API v3**
4. Create **OAuth 2.0 Client ID** credentials:
   - Application type: Web application
   - Authorized redirect URIs: `http://localhost:8000/api/auth/youtube/callback`
5. Download the JSON file and save as `backend/client_secrets.json`

### 2. Run with Docker (Easiest)

```bash
# Make sure client_secrets.json is in backend/
docker-compose up --build
```

Access at `http://localhost:3000`

### 3. Or Run Locally

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

**Frontend:**
```bash
cd frontend
npm install
npm start
```

## How to Use

1. **Connect YouTube** - Click "Connect Account" and authorize
2. **Enable YouTube** - Toggle it on
3. **Add Videos** - Drag & drop video files into the hopper
4. **Upload** - Click "Upload Now"

Done! 🎉

## Project Structure

```
hopper/
├── backend/              # Python FastAPI backend
│   ├── main.py          # Main API
│   ├── youtube_uploader.py
│   ├── scheduler.py
│   ├── title_generator.py
│   └── requirements.txt
├── frontend/            # React frontend
│   └── src/
│       ├── App.js
│       └── App.css
└── docker-compose.yml
```

## API Endpoints

- `GET /api/destinations` - Get available destinations
- `GET /api/auth/youtube` - Start YouTube OAuth
- `POST /api/videos/upload` - Upload video file
- `POST /api/upload/start` - Start uploading to YouTube
- `GET /api/queue` - Get video queue
- `DELETE /api/queue/{id}` - Remove video from queue

## Troubleshooting

**"client_secrets.json not found"**
- Download OAuth credentials from Google Cloud Console
- Save as `backend/client_secrets.json`

**CORS errors**
- Make sure backend is on port 8000
- Make sure frontend is on port 3000

**Upload fails**
- Check YouTube API quota limits
- Verify OAuth token is valid
- Make sure video format is supported (mp4, mov, avi, etc.)

## Roadmap

- [ ] Upload scheduling
- [ ] Custom title templates
- [ ] TikTok, Instagram, Twitter support
- [ ] Progress tracking
- [ ] User accounts & persistence
- [ ] Thumbnail customization

## License

MIT

---

**Keep it simple.** 🚀
