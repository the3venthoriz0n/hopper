import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

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
        
        <div className="page-footer">
          <Link to="/terms" className="page-link">Terms of Service</Link>
          <span className="page-separator">|</span>
          <Link to="/privacy" className="page-link">Privacy Policy</Link>
          <span className="page-separator">|</span>
          <Link to="/" className="page-link">Home</Link>
        </div>
      </div>
    </div>
  );
}

export default DeleteYourData;
