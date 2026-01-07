import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';
import { HOPPER_COLORS } from './utils/colors';

function Privacy() {
  useEffect(() => {
    document.title = 'Privacy Policy - hopper';
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="page-container">
      <div className="page-content">
        <h1>Privacy Policy</h1>
        <p className="page-meta"><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
        
        <p>
          This website is operated by syndic. Throughout the site, the terms 'we', 'us' and 'our' refer to syndic.
        </p>
        
        <h2>1. Information We Collect</h2>
        <p>We collect information you provide directly to us, including account credentials and content you upload. We also collect usage data and technical information automatically when you use the service.</p>
        
        <h2>2. How We Use Information</h2>
        <p>We use the information we collect to provide, maintain, and improve our services, process your requests, and communicate with you.</p>
        
        <h2>3. Information Sharing</h2>
        <p>We do not sell your personal information. We may share information with third-party service providers who assist us in operating our service, subject to confidentiality obligations.</p>
        
        <h2>4. Data Security</h2>
        <p>We implement appropriate technical and organizational measures to protect your information. However, no method of transmission over the internet is 100% secure.</p>
        
        <h2>5. Your Rights</h2>
        <p>You have the right to access, update, or delete your personal information. You may also opt out of certain data collection practices.</p>
        
        <h2>6. Changes to Privacy Policy</h2>
        <p>We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new policy on this page.</p>
        
        <h2>7. Contact</h2>
        <p>
          If you have any questions about this Privacy Policy or how your data is handled, you can
          contact us at{' '}
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

export default Privacy;

