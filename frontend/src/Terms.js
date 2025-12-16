import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

function Terms() {
  useEffect(() => {
    document.title = 'Terms of Service - hopper';
  }, []);

  return (
    <div className="page-container">
      <div className="page-content">
        <h1>Terms of Service</h1>
        <p className="page-meta"><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
        
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
        
        <div className="page-footer">
          <Link to="/pricing" className="page-link">Pricing</Link>
          <span className="page-separator">|</span>
          <Link to="/privacy" className="page-link">Privacy Policy</Link>
          <span className="page-separator">|</span>
          <Link to="/" className="page-link">Home</Link>
        </div>
      </div>
    </div>
  );
}

export default Terms;

