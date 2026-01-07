import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';
import { HOPPER_COLORS } from './utils/colors';

function Terms() {
  useEffect(() => {
    document.title = 'Terms of Service - hopper';
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="page-container">
      <div className="page-content">
        <h1>Terms of Service</h1>
        <p className="page-meta"><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
        
        <p>
          This website is operated by syndic. Throughout the site, the terms 'we', 'us' and 'our' refer to syndic.
        </p>
        
        <h2>1. Acceptance of Terms</h2>
        <p>By accessing and using this service, you accept and agree to be bound by these Terms of Service.</p>
        
        <h2>2. Use of Service</h2>
        <p>You agree to use this service only for lawful purposes and in accordance with these Terms. You are responsible for all content you upload or transmit through the service.</p>
        
        <h2>3. User Responsibilities</h2>
        <p>You are responsible for maintaining the confidentiality of your account credentials and for all activities that occur under your account.</p>
        
        <h2>4. Limitation of Liability</h2>
        <p>The service is provided "as is" without warranties of any kind. We are not liable for any damages arising from your use of the service.</p>
        
        <h2>5. Changes to Terms</h2>
        <p>We reserve the right to modify these Terms at any time. Continued use of the service after changes constitutes acceptance of the modified Terms.</p>
        
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

export default Terms;

