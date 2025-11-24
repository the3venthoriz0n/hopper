import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

function Privacy() {
  useEffect(() => {
    document.title = 'Privacy Policy - Hopper';
  }, []);

  return (
    <div style={{
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif',
      maxWidth: '800px',
      margin: '0 auto',
      padding: '2rem',
      lineHeight: '1.6',
      color: '#333'
    }}>
      <h1 style={{
        color: '#222',
        borderBottom: '2px solid #eee',
        paddingBottom: '0.5rem'
      }}>Privacy Policy</h1>
      <p><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>1. Information We Collect</h2>
      <p>We collect information you provide directly to us, including account credentials and content you upload. We also collect usage data and technical information automatically when you use the service.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>2. How We Use Information</h2>
      <p>We use the information we collect to provide, maintain, and improve our services, process your requests, and communicate with you.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>3. Information Sharing</h2>
      <p>We do not sell your personal information. We may share information with third-party service providers who assist us in operating our service, subject to confidentiality obligations.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>4. Data Security</h2>
      <p>We implement appropriate technical and organizational measures to protect your information. However, no method of transmission over the internet is 100% secure.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>5. Your Rights</h2>
      <p>You have the right to access, update, or delete your personal information. You may also opt out of certain data collection practices.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>6. Changes to Privacy Policy</h2>
      <p>We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new policy on this page.</p>
      
      <p style={{ marginTop: '2rem' }}>
        <Link to="/terms" style={{ color: '#0066cc', textDecoration: 'none' }}>Terms of Service</Link> | <Link to="/" style={{ color: '#0066cc', textDecoration: 'none' }}>Home</Link>
      </p>
    </div>
  );
}

export default Privacy;

