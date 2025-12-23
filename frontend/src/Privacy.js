import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

function Privacy() {
  useEffect(() => {
    document.title = 'Privacy Policy - hopper';
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
        
        <div className="page-footer">
          <Link to="/terms" className="page-link">Terms of Service</Link>
          <span className="page-separator">|</span>
          <Link to="/privacy" className="page-link">Privacy Policy</Link>
          <span className="page-separator">|</span>
          <Link to="/help" className="page-link">Help</Link>
          <span className="page-separator">|</span>
          <Link to="/delete-your-data" className="page-link">Delete Your Data</Link>
          <span className="page-separator">|</span>
          <Link to="/" className="page-link">Home</Link>
        </div>
      </div>
    </div>
  );
}

export default Privacy;

