import React from 'react';
import { Link } from 'react-router-dom';
import Footer from '../common/Footer';

/**
 * Public landing page for unauthenticated visitors
 */
export default function PublicLanding() {
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';

  return (
    <div className="landing-container">
      <header className="landing-header">
        <div className="landing-logo">
          <span className="landing-logo-icon">🐸</span>
          <span>{appTitle.replace('🐸 ', '')}</span>
        </div>
        <nav className="landing-nav">
          <Link to="/pricing" className="landing-nav-link">
            Pricing
          </Link>
          <Link to="/help" className="landing-nav-link">
            Help
          </Link>
          <Link to="/login" className="landing-nav-button">
            Login
          </Link>
        </nav>
      </header>

      <main className="landing-main">
        <div className="landing-content">
          <p className="landing-tagline">
            Creator upload automation
          </p>
          <h1 className="landing-title">
            Upload once.<br />hopper handles YouTube, TikTok, and Instagram for you.
          </h1>
          <p className="landing-description">
            hopper is a creator tool that automates multi-platform uploads and scheduling.
            Connect your accounts, drag in videos, and let hopper handle the rest.
          </p>
          <div className="landing-cta">
            <Link to="/login" className="landing-cta-button">
              Log in
            </Link>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}
