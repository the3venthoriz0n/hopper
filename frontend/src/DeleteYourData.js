import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';
import { HOPPER_COLORS } from './App';

function DeleteYourData() {
  useEffect(() => {
    document.title = 'Delete Your Data - hopper';
  }, []);

  return (
    <div className="page-container">
      <div className="page-content">
        <h1>Delete Your Data</h1>
        <p className="page-meta"><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
        
        <h2>1. How to Delete Your Account</h2>
        <p>To permanently delete your account and all associated data, log in to your Hopper account, click the settings icon in the top-right corner next to your email address, navigate to Account Settings, scroll to the Danger Zone section, and click "Delete My Account". You will be asked to confirm your decision before deletion.</p>
        
        <h2>2. What Gets Deleted</h2>
        <p>When you delete your account, we permanently remove your account and login credentials, all uploaded videos and files, all settings and preferences, all connected social media accounts, and all OAuth tokens and session data.</p>
        
        <h2>3. Deletion is Permanent</h2>
        <p>Account deletion is permanent and cannot be undone. Your data is deleted immediately after confirmation. There is no waiting period or recovery option.</p>
        
        <h2>4. Need Help?</h2>
        <p>If you have trouble deleting your data or have questions about data privacy, please contact us at{' '}
          <a href="mailto:andrewkpln+hopper@gmail.com" className="page-link">
            andrewkpln+hopper@gmail.com
          </a>
          .
        </p>
        
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

export default DeleteYourData;
