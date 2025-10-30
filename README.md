# Hopper - Video Upload Manager

A web application for managing and scheduling video uploads to YouTube (with support for additional platforms coming soon).

## Features

- 🔐 **YouTube OAuth Integration** - Securely connect your YouTube account
- 📤 **Drag & Drop Upload** - Easy video file management
- 🎯 **Multiple Destinations** - Toggle upload destinations on/off
- ⏰ **Upload Scheduling** - Schedule videos for future upload
- ✏️ **Title & Description Management** - Edit metadata before upload
- 🐳 **Docker Support** - Run in containers for easy deployment

## Tech Stack

**Frontend:**
- React 18 with TypeScript
- Vite for fast development
- React Router for navigation
- Axios for API calls
- React Dropzone for file uploads

**Backend:**
- Python 3.11
- FastAPI for REST API
- SQLAlchemy with AsyncIO
- SQLite database
- Google OAuth 2.0

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+
- YouTube API credentials (OAuth 2.0 Client ID)

### YouTube API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the YouTube Data API v3
4. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized redirect URIs: `http://localhost:3000/auth/callback`
5. Copy the Client ID and Client Secret

### Local Development

#### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp env.example .env
# Edit .env and add your YouTube credentials

# Run the backend
uvicorn main:app --reload --port 8000
```

The backend will be available at `http://localhost:8000`
API documentation: `http://localhost:8000/docs`

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run the development server
npm run dev
```

The frontend will be available at `http://localhost:3000`

### Docker Deployment

```bash
# Copy and configure environment variables
cp env.example .env
# Edit .env and add your YouTube credentials

# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop containers
docker-compose down
```

## Usage

1. **Connect YouTube Account**
   - Enter your email
   - Click "Connect YouTube Account"
   - Authorize the application

2. **Upload Videos**
   - Drag and drop video files into the hopper
   - Supported formats: MP4, MOV, AVI, MKV, WebM

3. **Configure Videos**
   - Click "Edit" on any video
   - Set title and description
   - Choose upload destinations
   - Schedule upload time (optional)
   - Click "Save"

4. **Upload**
   - Click "Upload Now" to trigger immediate upload
   - Or scheduled uploads will process automatically

## Project Structure

```
hopper/
├── backend/
│   ├── routers/          # API route handlers
│   │   ├── auth.py       # OAuth and authentication
│   │   ├── destinations.py # Destination management
│   │   └── videos.py     # Video upload and management
│   ├── config.py         # Configuration and settings
│   ├── database.py       # Database setup
│   ├── models.py         # SQLAlchemy models
│   ├── main.py           # FastAPI application
│   └── requirements.txt  # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── pages/        # Page components
│   │   ├── utils/        # Utilities and API client
│   │   ├── App.tsx       # Main application
│   │   └── main.tsx      # Entry point
│   ├── package.json      # Node dependencies
│   └── vite.config.ts    # Vite configuration
├── docker-compose.yml    # Docker Compose configuration
├── Dockerfile.backend    # Backend Docker image
├── Dockerfile.frontend   # Frontend Docker image
└── README.md            # This file
```

## API Endpoints

### Authentication
- `GET /api/auth/youtube/url` - Get YouTube OAuth URL
- `POST /api/auth/youtube/callback` - Complete OAuth flow

### Destinations
- `GET /api/destinations/user/{user_id}` - Get user's destinations
- `PATCH /api/destinations/{destination_id}` - Toggle destination on/off
- `DELETE /api/destinations/{destination_id}` - Remove destination

### Videos
- `POST /api/videos/upload` - Upload video to hopper
- `GET /api/videos/user/{user_id}` - Get user's videos
- `PATCH /api/videos/{video_id}` - Update video metadata
- `DELETE /api/videos/{video_id}` - Delete video
- `POST /api/videos/{video_id}/upload` - Trigger upload

## Security Notes

- Never commit `.env` files with real credentials
- Keep your `SECRET_KEY` secure and random
- Use HTTPS in production
- Store OAuth tokens securely (currently encrypted in database)

## Future Enhancements

- Additional platforms (TikTok, Vimeo, etc.)
- Bulk upload operations
- Video thumbnail generation
- Upload progress tracking
- Background worker for scheduled uploads
- Video format conversion
- Upload analytics and history

## License

See LICENSE file for details.
