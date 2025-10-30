# Backend Setup Instructions

## Get YouTube API Credentials

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/

2. **Create a New Project**
   - Click "Select a project" → "New Project"
   - Give it a name (e.g., "Hopper")
   - Click "Create"

3. **Enable YouTube Data API v3**
   - Go to "APIs & Services" → "Library"
   - Search for "YouTube Data API v3"
   - Click on it and press "Enable"

4. **Create OAuth 2.0 Credentials**
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - If prompted, configure the OAuth consent screen:
     - User Type: External
     - App name: Hopper
     - User support email: your email
     - Developer contact: your email
     - Save and continue through the rest
   - Application type: **Web application**
   - Name: Hopper Backend
   - Authorized redirect URIs: `http://localhost:8000/api/youtube/callback`
   - Click "Create"

5. **Download Credentials**
   - Google will show your Client ID and Client Secret
   - Click "Download JSON"
   - Replace the contents of `backend/client_secrets.json` with the downloaded file
   
   OR manually fill in `client_secrets.json`:
   - Replace `YOUR_CLIENT_ID.apps.googleusercontent.com` with your Client ID
   - Replace `YOUR_CLIENT_SECRET` with your Client Secret
   - Replace `your-project-id` with your project ID

6. **Done!**
   - Now you can run the app and connect to YouTube

## Security Note

- `client_secrets.json` is already in `.gitignore`
- Never commit this file to version control
- Keep your Client Secret private

