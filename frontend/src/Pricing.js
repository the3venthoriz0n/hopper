import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './App.css';
import { HOPPER_COLORS } from './App';

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
        const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
        const API = `${backendUrl}/api`;
        
        try {
          const response = await fetch(`${API}/stripe/config`);
          if (response.ok) {
            const data = await response.json();
            if (data.publishable_key) {
              setPublishableKey(data.publishable_key);
            } else {
              console.warn('No publishable_key in API response');
            }
            if (data.pricing_table_id) {
              setPricingTableId(data.pricing_table_id);
            } else {
              console.warn('No pricing_table_id in API response. Make sure STRIPE_PRICING_TABLE_ID is set in backend .env');
            }
          } else {
            console.error(`Failed to load Stripe config: ${response.status} ${response.statusText}`);
            const errorText = await response.text();
            console.error('Error response:', errorText);
          }
        } catch (err) {
          console.error('Failed to load Stripe config:', err);
          console.error('API URL attempted:', `${API}/stripe/config`);
        }
      } catch (err) {
        console.error('Error loading Stripe config:', err);
      } finally {
        setLoading(false);
      }
    };
    
    loadStripeConfig();
  }, []);

  // Load Stripe pricing table script when config is ready
  useEffect(() => {
    if (publishableKey && pricingTableId) {
      const scriptId = 'stripe-pricing-table-script';
      // Check if script already exists
      if (!document.getElementById(scriptId)) {
        const script = document.createElement('script');
        script.id = scriptId;
        script.src = 'https://js.stripe.com/v3/pricing-table.js';
        script.async = true;
        document.body.appendChild(script);
      }
    }
    
    return () => {
      // Cleanup script on unmount (optional, but good practice)
      const existingScript = document.getElementById('stripe-pricing-table-script');
      if (existingScript) {
        existingScript.remove();
      }
    };
  }, [publishableKey, pricingTableId]);

  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';

  return (
    <div className="landing-container">
      <header className="landing-header">
        <Link to="/" className="landing-logo">
          <span className="landing-logo-icon">🐸</span>
          <span>{appTitle.replace('🐸 ', '')}</span>
        </Link>
        <nav className="landing-nav">
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
            Pricing
          </p>
          <h1 className="landing-title">Pricing Coming Soon</h1>
          <p className="landing-description">
            We're working on our pricing plans. Check back soon!
          </p>
          <div className="landing-cta">
            <Link to="/login" className="landing-cta-button">
              Get Started
            </Link>
          </div>
        </div>
      </main>

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
  );
}

export default Pricing;

