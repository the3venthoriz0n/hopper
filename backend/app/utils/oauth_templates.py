"""OAuth callback HTML templates and utilities"""
from app.core.config import settings


def get_instagram_callback_html(state: str = None) -> str:
    """Generate HTML page for Instagram OAuth callback that extracts tokens from URL fragment
    
    Facebook Login for Business uses token-based flow with URL fragments.
    Tokens are in the fragment (#access_token=...), not query parameters.
    This HTML extracts tokens from fragment and POSTs to backend.
    
    Args:
        state: OAuth state parameter (user_id)
    
    Returns:
        HTML string for Instagram OAuth callback page
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Instagram OAuth Callback</title>
    </head>
    <body>
        <p>Processing Instagram authentication...</p>
        <script>
            // Extract tokens from URL fragment (as per Facebook docs)
            const fragment = window.location.hash.substring(1);
            const params = new URLSearchParams(fragment);
            
            const accessToken = params.get('access_token');
            const longLivedToken = params.get('long_lived_token');
            const expiresIn = params.get('expires_in');
            const error = params.get('error');
            const state = params.get('state') || '{state or ""}';
            
            if (error) {{
                window.location.href = '{settings.FRONTEND_URL}?error=instagram_auth_failed&reason=' + error;
            }} else if (accessToken) {{
                // Send tokens to backend to complete authentication
                fetch('{settings.BACKEND_URL.rstrip("/")}/api/auth/instagram/complete', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    credentials: 'include',
                    body: JSON.stringify({{
                        access_token: accessToken,
                        long_lived_token: longLivedToken,
                        expires_in: expiresIn,
                        state: state
                    }})
                }})
                .then(res => res.json())
                .then(data => {{
                    if (data.success) {{
                        // ROOT CAUSE FIX: Pass connection status from authoritative source via URL
                        // This eliminates race conditions - no need for separate API call
                        const status = data.instagram ? encodeURIComponent(JSON.stringify(data.instagram)) : '';
                        window.location.href = '{settings.FRONTEND_URL}/app?connected=instagram' + (status ? '&status=' + status : '');
                    }} else {{
                        window.location.href = '{settings.FRONTEND_URL}?error=instagram_auth_failed&detail=' + encodeURIComponent(data.error || 'Unknown error');
                    }}
                }})
                .catch(err => {{
                    console.error('Error completing auth:', err);
                    window.location.href = '{settings.FRONTEND_URL}/app?error=instagram_auth_failed';
                }});
            }} else {{
                window.location.href = '{settings.FRONTEND_URL}/app?error=instagram_auth_failed&reason=missing_tokens';
            }}
        </script>
    </body>
    </html>
    """

