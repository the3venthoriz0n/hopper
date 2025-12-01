import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

function DeleteYourData() {
  useEffect(() => {
    document.title = 'Delete Your Data - hopper';
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
      }}>Delete Your Data</h1>
      <p><strong>Last updated:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>1. How to Delete Your Account</h2>
      <p>To permanently delete your account and all associated data, log in to your Hopper account, click the settings icon in the top-right corner next to your email address, navigate to Account Settings, scroll to the Danger Zone section, and click "Delete My Account". You will be asked to confirm your decision before deletion.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>2. What Gets Deleted</h2>
      <p>When you delete your account, we permanently remove your account and login credentials, all uploaded videos and files, all settings and preferences, all connected social media accounts, and all OAuth tokens and session data.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>3. Deletion is Permanent</h2>
      <p>Account deletion is permanent and cannot be undone. Your data is deleted immediately after confirmation. There is no waiting period or recovery option.</p>
      
      <h2 style={{ color: '#444', marginTop: '2rem' }}>4. Need Help?</h2>
      <p>If you have trouble deleting your data or have questions about data privacy, please contact us at support@{window.location.hostname.split(':')[0]}</p>
      
      <p style={{ marginTop: '2rem' }}>
        <Link to="/terms" style={{ color: '#0066cc', textDecoration: 'none' }}>Terms of Service</Link> | <Link to="/privacy" style={{ color: '#0066cc', textDecoration: 'none' }}>Privacy Policy</Link> | <Link to="/" style={{ color: '#0066cc', textDecoration: 'none' }}>Home</Link>
      </p>
    </div>
  );
}

export default DeleteYourData;
