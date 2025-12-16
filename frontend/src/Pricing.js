import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

function Pricing() {
  const [publishableKey, setPublishableKey] = useState(null);
  const [pricingTableId, setPricingTableId] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.title = 'Pricing - hopper';
    
    // Load Stripe publishable key and pricing table ID from environment or API
    const loadStripeConfig = async () => {
      try {
        // Try to get from environment variable first (set in build)
        const envKey = process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY;
        const envTableId = process.env.REACT_APP_STRIPE_PRICING_TABLE_ID;
        
        if (envKey && envTableId) {
          setPublishableKey(envKey);
          setPricingTableId(envTableId);
          setLoading(false);
          return;
        }
        
        // Fallback: try to get from API
        const API = process.env.REACT_APP_BACKEND_URL 
          ? `${process.env.REACT_APP_BACKEND_URL}/api`
          : `https://${window.location.hostname}/api`;
        
        try {
          const response = await fetch(`${API}/stripe/config`);
          if (response.ok) {
            const data = await response.json();
            setPublishableKey(data.publishable_key);
            setPricingTableId(data.pricing_table_id);
          }
        } catch (err) {
          console.error('Failed to load Stripe config:', err);
        }
      } catch (err) {
        console.error('Error loading Stripe config:', err);
      } finally {
        setLoading(false);
      }
    };
    
    loadStripeConfig();
    
    // Load Stripe pricing table script
    const script = document.createElement('script');
    script.src = 'https://js.stripe.com/v3/pricing-table.js';
    script.async = true;
    document.body.appendChild(script);
    
    return () => {
      // Cleanup script on unmount
      const existingScript = document.querySelector('script[src="https://js.stripe.com/v3/pricing-table.js"]');
      if (existingScript) {
        document.body.removeChild(existingScript);
      }
    };
  }, []);

  return (
    <div className="pricing-container">
      <header className="pricing-header">
        <Link to="/" className="pricing-logo">
          <span className="pricing-logo-icon">🐸</span>
          <span>hopper</span>
        </Link>
        <nav className="pricing-nav">
          <Link to="/privacy" className="pricing-nav-link">
            Privacy
          </Link>
          <Link to="/terms" className="pricing-nav-link">
            Terms
          </Link>
          <Link to="/login" className="pricing-nav-button">
            Login
          </Link>
        </nav>
      </header>

      <main className="pricing-main">
        <div className="pricing-content">
          <div className="pricing-intro">
            <p className="pricing-tagline">Simple, transparent pricing</p>
            <h1 className="pricing-title">Choose the plan that works for you</h1>
            <p className="pricing-description">
              All plans include multi-platform upload automation, scheduling, and priority support.
            </p>
          </div>

          {loading ? (
            <div className="pricing-loading">
              <p>Loading pricing...</p>
            </div>
          ) : publishableKey && pricingTableId ? (
            <div className="pricing-table-wrapper">
              <stripe-pricing-table
                pricing-table-id={pricingTableId}
                publishable-key={publishableKey}
              ></stripe-pricing-table>
            </div>
          ) : (
            <div className="pricing-error">
              <p>Unable to load pricing table. Please contact support.</p>
              <Link to="/login" className="pricing-cta-button">
                Get Started
              </Link>
            </div>
          )}
        </div>
      </main>

      <footer className="pricing-footer">
        © {new Date().getFullYear()} hopper. All rights reserved.
      </footer>
    </div>
  );
}

export default Pricing;

