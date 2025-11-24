import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

function Terms() {
  useEffect(() => {
    document.title = 'Terms of Service - Hopper';
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
      }}>Terms of Service</h1>
      <p><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>1. Acceptance of Terms</h2>
      <p>By accessing and using this service, you accept and agree to be bound by these Terms of Service.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>2. Use of Service</h2>
      <p>You agree to use this service only for lawful purposes and in accordance with these Terms. You are responsible for all content you upload or transmit through the service.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>3. User Responsibilities</h2>
      <p>You are responsible for maintaining the confidentiality of your account credentials and for all activities that occur under your account.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>4. Limitation of Liability</h2>
      <p>The service is provided "as is" without warranties of any kind. We are not liable for any damages arising from your use of the service.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>5. Changes to Terms</h2>
      <p>We reserve the right to modify these Terms at any time. Continued use of the service after changes constitutes acceptance of the modified Terms.</p>
      
      <p style={{ marginTop: '2rem' }}>
        <Link to="/privacy" style={{ color: '#0066cc', textDecoration: 'none' }}>Privacy Policy</Link> | <Link to="/" style={{ color: '#0066cc', textDecoration: 'none' }}>Home</Link>
      </p>
    </div>
  );
}

export default Terms;

