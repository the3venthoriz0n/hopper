import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';
import { HOPPER_COLORS, rgba } from './utils/colors';

function Help() {
  useEffect(() => {
    document.title = 'Help - hopper';
  }, []);

  return (
    <div className="page-container">
      <div className="page-content">
        <h1 style={{ marginBottom: '0.5rem' }}>Help & Support</h1>
        <p style={{ color: HOPPER_COLORS.greyMedium, marginBottom: '2rem', fontSize: '1rem' }}>
          Everything you need to know about using hopper
        </p>
        
        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>Getting Started</h2>
          <ol style={{ lineHeight: '1.8', paddingLeft: '1.5rem' }}>
            <li style={{ marginBottom: '0.75rem' }}><strong>Create an account</strong> or log in to your existing account</li>
            <li style={{ marginBottom: '0.75rem' }}><strong>Connect your platforms</strong> - Click "Connect" for YouTube, TikTok, and/or Instagram to authorize hopper</li>
            <li style={{ marginBottom: '0.75rem' }}><strong>Enable destinations</strong> - Toggle on the platforms you want to upload to</li>
            <li style={{ marginBottom: '0.75rem' }}><strong>Upload videos</strong> - Drag and drop videos or click to browse</li>
            <li style={{ marginBottom: '0.75rem' }}><strong>Configure settings</strong> - Set titles, descriptions, privacy levels, and other options per platform</li>
            <li style={{ marginBottom: '0.75rem' }}><strong>Upload or schedule</strong> - Click "Upload" to upload immediately or let hopper schedule them automatically</li>
          </ol>
        </section>

        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>Supported File Types</h2>
          <p style={{ marginBottom: '1rem' }}>Hopper accepts any video file with a standard video MIME type. For best compatibility across all platforms:</p>
          <ul style={{ lineHeight: '1.8', marginBottom: '1rem' }}>
            <li><strong>MP4</strong> - Recommended format, supported by all platforms (YouTube, TikTok, Instagram)</li>
            <li><strong>MOV</strong> - Supported by TikTok</li>
            <li><strong>WebM</strong> - Supported by TikTok</li>
          </ul>
          <div style={{ 
            background: rgba(HOPPER_COLORS.rgb.warning, 0.1), 
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.warning, 0.3)}`, 
            borderRadius: '6px', 
            padding: '1rem',
            fontSize: '0.9rem'
          }}>
            <strong>Note:</strong> While hopper accepts any video file type, each platform has its own format requirements. MP4 is the safest choice for maximum compatibility.
          </div>
        </section>

        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>File Size Limitations</h2>
          <ul style={{ lineHeight: '1.8' }}>
            <li><strong>Maximum file size:</strong> 10 GB per video</li>
            <li>Files are validated during upload to ensure they don't exceed this limit</li>
            <li>Large files may take longer to upload depending on your internet connection</li>
          </ul>
        </section>

        <h2>Features</h2>
        
        <div style={{ 
          background: rgba(HOPPER_COLORS.rgb.purpleViolet, 0.1), 
          border: `1px solid ${rgba(HOPPER_COLORS.rgb.purpleViolet, 0.3)}`, 
          borderRadius: '8px', 
          padding: '1.5rem', 
          marginBottom: '2rem' 
        }}>
          <h3 style={{ marginTop: 0, color: HOPPER_COLORS.purpleViolet }}>Template System</h3>
          <p>Create dynamic titles and descriptions using placeholders that are automatically replaced when videos are uploaded.</p>
          
          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem' }}>Available Placeholders</h4>
          <ul style={{ marginBottom: '1.5rem' }}>
            <li><strong><code>{'{filename}'}</code></strong> - Replaced with the video filename (without extension)</li>
            <li><strong><code>{'{random}'}</code></strong> - Replaced with a random word from your wordbank</li>
          </ul>

          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem' }}>The {'{random}'} Variable</h4>
          <p>The <code>{'{random}'}</code> placeholder is a powerful feature that lets you inject variety into your titles and descriptions:</p>
          <ul style={{ marginBottom: '1.5rem' }}>
            <li><strong>How it works:</strong> Each <code>{'{random}'}</code> in your template is replaced with a different random word from your wordbank</li>
            <li><strong>Multiple uses:</strong> You can use <code>{'{random}'}</code> multiple times in the same template - each occurrence gets a different random word</li>
            <li><strong>Works everywhere:</strong> Use <code>{'{random}'}</code> in both title and description templates</li>
            <li><strong>Wordbank required:</strong> Add words to your wordbank in Global Settings for <code>{'{random}'}</code> to work</li>
          </ul>

          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem' }}>Examples</h4>
          <div style={{ 
            background: rgba(HOPPER_COLORS.rgb.black, 0.2), 
            padding: '1rem', 
            borderRadius: '6px', 
            marginBottom: '1rem',
            fontFamily: 'monospace',
            fontSize: '0.9rem',
            lineHeight: '1.6'
          }}>
            <div style={{ marginBottom: '0.75rem' }}>
              <strong>Template:</strong><br />
              <code style={{ color: HOPPER_COLORS.purpleViolet }}>{'{random}'} {'{filename}'} - {'{random}'} Video</code>
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <strong>Wordbank:</strong> ["amazing", "epic", "incredible", "awesome"]<br />
              <strong>Filename:</strong> "my_video.mp4"
            </div>
            <div>
              <strong>Result:</strong><br />
              <code style={{ color: HOPPER_COLORS.tokenGreen }}>"epic my_video - incredible Video"</code>
            </div>
          </div>

          <div style={{ 
            background: rgba(HOPPER_COLORS.rgb.black, 0.2), 
            padding: '1rem', 
            borderRadius: '6px',
            fontFamily: 'monospace',
            fontSize: '0.9rem',
            lineHeight: '1.6'
          }}>
            <div style={{ marginBottom: '0.75rem' }}>
              <strong>Description Template:</strong><br />
              <code style={{ color: HOPPER_COLORS.purpleViolet }}>Check out this {'{random}'} {'{filename}'}! This is a {'{random}'} video you'll love.</code>
            </div>
            <div>
              <strong>Result:</strong><br />
              <code style={{ color: HOPPER_COLORS.tokenGreen }}>"Check out this amazing my_video! This is a epic video you'll love."</code>
            </div>
          </div>

          <p style={{ marginTop: '1.5rem', marginBottom: 0, fontSize: '0.9rem', color: HOPPER_COLORS.greyMedium }}>
            <strong>Tip:</strong> Set different templates for each platform (YouTube, TikTok, Instagram) to customize how your content appears on each platform.
          </p>
        </div>

        <h3 style={{ marginTop: '2rem' }}>Scheduling</h3>
        <ul>
          <li><strong>Immediate upload:</strong> Upload all videos at once to all enabled destinations</li>
          <li><strong>Spaced scheduling:</strong> Automatically space out uploads at regular intervals (e.g., every 1 hour)</li>
          <li><strong>Specific time:</strong> Schedule videos for specific dates and times</li>
        </ul>

        <h3 style={{ marginTop: '2rem' }}>Per-Video Overrides</h3>
        <ul>
          <li>Click the edit button (✏️) on any video to customize its settings</li>
          <li>Override title, description, tags, visibility, and other settings per video</li>
          <li>Custom settings take priority over template settings</li>
        </ul>

        <h3 style={{ marginTop: '2rem' }}>Retry Failed Uploads</h3>
        <ul>
          <li>If an upload fails, click the "🔄 Retry" button to attempt the upload again</li>
          <li>Failed uploads show the error message in the status</li>
        </ul>

        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>Token System</h2>
          <p style={{ marginBottom: '1rem' }}>Hopper uses a token-based system to track usage:</p>
          <ul style={{ lineHeight: '1.8' }}>
            <li>Tokens are calculated based on video file size</li>
            <li>Free plans have a hard limit - you cannot exceed your token allocation</li>
            <li>Paid plans (Starter, Creator) allow overage - you can upload beyond your included tokens</li>
            <li>Unlimited plans have no token restrictions</li>
            <li>Tokens reset monthly based on your subscription period</li>
          </ul>
        </section>

        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>Platform-Specific Notes</h2>
          
          <div style={{ 
            background: rgba(HOPPER_COLORS.rgb.orange, 0.1), 
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.orange, 0.3)}`, 
            borderRadius: '8px', 
            padding: '1.5rem', 
            marginBottom: '1.5rem' 
          }}>
            <h3 style={{ marginTop: 0, color: HOPPER_COLORS.orange }}>YouTube</h3>
            <ul style={{ lineHeight: '1.8', marginBottom: 0 }}>
              <li>Title limit: 100 characters</li>
              <li>Supports public, private, and unlisted visibility</li>
              <li>Can set "Made for Kids" flag</li>
            </ul>
          </div>

          <div style={{ 
            background: rgba(HOPPER_COLORS.rgb.cyan, 0.1), 
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.cyan, 0.3)}`, 
            borderRadius: '8px', 
            padding: '1.5rem', 
            marginBottom: '1.5rem' 
          }}>
            <h3 style={{ marginTop: 0, color: HOPPER_COLORS.cyan }}>TikTok</h3>
            <ul style={{ lineHeight: '1.8', marginBottom: '0.75rem' }}>
              <li>Title limit: 2,200 characters</li>
              <li>Supports public, private, and friends-only privacy levels</li>
              <li>Can control comments, duet, and stitch settings</li>
            </ul>
            <div style={{ 
              background: rgba(HOPPER_COLORS.rgb.warning, 0.1), 
              border: `1px solid ${rgba(HOPPER_COLORS.rgb.warning, 0.3)}`, 
              borderRadius: '6px', 
              padding: '0.75rem',
              fontSize: '0.9rem'
            }}>
              <strong>Note:</strong> Unaudited TikTok apps can only post to private accounts. Set your privacy level to "private" in settings if you see this limitation.
            </div>
          </div>

          <div style={{ 
            background: rgba(HOPPER_COLORS.rgb.instagramPinkAlt, 0.1), 
            border: `1px solid ${rgba(HOPPER_COLORS.rgb.instagramPinkAlt, 0.3)}`, 
            borderRadius: '8px', 
            padding: '1.5rem' 
          }}>
            <h3 style={{ marginTop: 0, color: HOPPER_COLORS.instagramPinkAlt }}>Instagram</h3>
            <ul style={{ lineHeight: '1.8', marginBottom: 0 }}>
              <li>Caption limit: 2,200 characters</li>
              <li>Supports location tagging</li>
              <li>Can disable comments and likes</li>
            </ul>
          </div>
        </section>

        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>Troubleshooting</h2>
          
          <div style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ marginBottom: '0.75rem' }}>Upload Failures</h3>
            <ul style={{ lineHeight: '1.8' }}>
              <li>Check that your platform accounts are connected and tokens are valid</li>
              <li>Verify you have enough tokens for the file size</li>
              <li>Check the error message displayed on failed videos</li>
              <li>Try the retry button if an upload fails</li>
            </ul>
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ marginBottom: '0.75rem' }}>Token Issues</h3>
            <ul style={{ lineHeight: '1.8' }}>
              <li>Free plan users: Ensure you have enough tokens before uploading</li>
              <li>Paid plan users: Overage is allowed, but you'll be billed for additional usage</li>
              <li>Tokens reset at the start of each billing period</li>
            </ul>
          </div>

          <div>
            <h3 style={{ marginBottom: '0.75rem' }}>Connection Issues</h3>
            <ul style={{ lineHeight: '1.8' }}>
              <li>If a platform shows "Token expires soon" or "Token expired", reconnect your account</li>
              <li>Re-authorization may be required if tokens expire</li>
            </ul>
          </div>
        </section>

        <section style={{ marginBottom: '3rem' }}>
          <h2 style={{ marginBottom: '1rem', color: HOPPER_COLORS.purpleViolet }}>Contact & Support</h2>
          <p style={{ marginBottom: '1rem' }}>For support, questions, or feedback:</p>
          <ul style={{ lineHeight: '1.8' }}>
            <li><strong>GitHub:</strong> <a href="https://github.com/the3venthoriz0n/hopper" target="_blank" rel="noopener noreferrer" style={{ color: HOPPER_COLORS.link }}>https://github.com/the3venthoriz0n/hopper</a></li>
            <li><strong>Issues:</strong> Report bugs or request features via GitHub Issues</li>
          </ul>
        </section>

        <footer style={{
          marginTop: '3rem',
          padding: '1.5rem',
          textAlign: 'center',
          borderTop: `1px solid ${HOPPER_COLORS.greyBorder}`,
          color: HOPPER_COLORS.grey,
          fontSize: '0.9rem'
        }}>
          <Link 
            to="/terms" 
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none', 
              marginRight: '1rem',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = `rgba(${HOPPER_COLORS.rgb.accent}, 0.7)`}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
          >
            Terms of Service
          </Link>
          <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
          <Link 
            to="/privacy" 
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none', 
              margin: '0 1rem',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = `rgba(${HOPPER_COLORS.rgb.accent}, 0.7)`}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
          >
            Privacy Policy
          </Link>
          <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
          <Link 
            to="/help"
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none', 
              margin: '0 1rem',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = `rgba(${HOPPER_COLORS.rgb.accent}, 0.7)`}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
          >
            Help
          </Link>
          <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
          <Link 
            to="/delete-your-data"
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none', 
              margin: '0 1rem',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = `rgba(${HOPPER_COLORS.rgb.accent}, 0.7)`}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
          >
            Delete Your Data
          </Link>
          <span style={{ color: HOPPER_COLORS.greyLight }}>|</span>
          <Link 
            to="/"
            style={{ 
              color: HOPPER_COLORS.accent, 
              textDecoration: 'none', 
              marginLeft: '1rem',
              transition: 'color 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.color = `rgba(${HOPPER_COLORS.rgb.accent}, 0.7)`}
            onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
          >
            Home
          </Link>
          <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: HOPPER_COLORS.grey }}>
            © {new Date().getFullYear()} hopper
          </div>
          <div style={{ marginTop: '0.25rem', fontSize: '0.85rem', color: HOPPER_COLORS.grey }}>
            <a 
              href={process.env.REACT_APP_VERSION && process.env.REACT_APP_VERSION !== 'dev' 
                ? `https://github.com/the3venthoriz0n/hopper/releases/tag/${process.env.REACT_APP_VERSION}`
                : 'https://github.com/the3venthoriz0n/hopper/releases'}
              target="_blank" 
              rel="noopener noreferrer"
              style={{ 
                color: HOPPER_COLORS.accent, 
                textDecoration: 'none',
                transition: 'color 0.2s'
              }}
              onMouseEnter={(e) => e.target.style.color = `rgba(${HOPPER_COLORS.rgb.accent}, 0.7)`}
              onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
            >
              {process.env.REACT_APP_VERSION || 'dev'}
            </a>
          </div>
        </footer>
      </div>
    </div>
  );
}

export default Help;

