import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './App.css';
import { HOPPER_COLORS } from './utils/colors';
import { loadPlans } from './services/subscriptionService';

function Pricing() {
  const [publishableKey, setPublishableKey] = useState(null);
  const [pricingTableId, setPricingTableId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [plans, setPlans] = useState([]);
  const [loadingPlans, setLoadingPlans] = useState(true);
  const [plansError, setPlansError] = useState(null);

  useEffect(() => {
    document.title = 'Pricing - hopper';
    
    const fetchPlans = async () => {
      try {
        setLoadingPlans(true);
        setPlansError(null);
        const plansData = await loadPlans();
        setPlans(plansData || []);
      } catch (err) {
        console.error('Failed to load plans:', err);
        setPlansError('Failed to load pricing plans. Please try again later.');
        setPlans([]);
      } finally {
        setLoadingPlans(false);
      }
    };
    
    fetchPlans();
    
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
          <h1 className="landing-title">Choose Your Plan</h1>
          
          {loadingPlans ? (
            <p className="landing-description" style={{ marginTop: '1rem' }}>
              Loading plans...
            </p>
          ) : plansError ? (
            <p className="landing-description" style={{ marginTop: '1rem', color: HOPPER_COLORS.error }}>
              {plansError}
            </p>
          ) : plans.length === 0 ? (
            <p className="landing-description" style={{ marginTop: '1rem' }}>
              No plans available at this time.
            </p>
          ) : (
            <div style={{
              marginTop: '2rem',
              maxWidth: '1200px',
              width: '100%'
            }}
            className="pricing-plans-grid">
              {plans.map((plan) => {
                const getPriceDisplay = () => {
                  if (plan.key === 'free_daily' || plan.price?.amount_dollars === 0) {
                    return 'Free';
                  }
                  return plan.price?.formatted || `$${plan.price?.amount_dollars?.toFixed(2) || '0.00'}/month`;
                };
                
                const getTokenDisplay = () => {
                  if (plan.tokens === -1) {
                    return 'Unlimited tokens';
                  }
                  if (plan.recurring_interval === 'day') {
                    return `${plan.tokens} tokens/day`;
                  }
                  return `${plan.tokens} tokens/month`;
                };
                
                const getOverageDisplay = () => {
                  if (plan.overage_price?.amount_dollars) {
                    const overageCents = (plan.overage_price.amount_dollars * 100).toFixed(1);
                    return `${overageCents}c per additional token`;
                  }
                  return null;
                };
                
                return (
                  <div
                    key={plan.key}
                    style={{
                      background: HOPPER_COLORS.secondary,
                      border: `1px solid ${HOPPER_COLORS.greyBorder}`,
                      borderRadius: '8px',
                      padding: '1.5rem',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '1rem',
                      transition: 'transform 0.2s, box-shadow 0.2s'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.transform = 'translateY(-4px)';
                      e.currentTarget.style.boxShadow = `0 4px 12px rgba(${HOPPER_COLORS.rgb.base}, 0.3)`;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.transform = 'translateY(0)';
                      e.currentTarget.style.boxShadow = 'none';
                    }}
                  >
                    <div>
                      <h3 style={{
                        margin: 0,
                        fontSize: '1.5rem',
                        fontWeight: '600',
                        color: HOPPER_COLORS.light
                      }}>
                        {plan.name}
                      </h3>
                      <p style={{
                        margin: '0.5rem 0 0 0',
                        fontSize: '2rem',
                        fontWeight: '700',
                        color: HOPPER_COLORS.accent
                      }}>
                        {getPriceDisplay()}
                      </p>
                    </div>
                    
                    <div style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.75rem'
                    }}>
                      <p style={{
                        margin: 0,
                        fontSize: '1rem',
                        color: HOPPER_COLORS.light,
                        fontWeight: '500'
                      }}>
                        {getTokenDisplay()}
                      </p>
                      
                      {plan.description && (
                        <p style={{
                          margin: 0,
                          fontSize: '0.9rem',
                          color: HOPPER_COLORS.grey,
                          lineHeight: '1.5'
                        }}>
                          {plan.description}
                        </p>
                      )}
                      
                      {plan.max_accrual && (
                        <p style={{
                          margin: 0,
                          fontSize: '0.85rem',
                          color: HOPPER_COLORS.grey,
                          fontStyle: 'italic'
                        }}>
                          Max accrual: {plan.max_accrual} tokens
                        </p>
                      )}
                      
                      {getOverageDisplay() && (
                        <p style={{
                          margin: 0,
                          fontSize: '0.85rem',
                          color: HOPPER_COLORS.accent
                        }}>
                          {getOverageDisplay()}
                        </p>
                      )}
                    </div>
                    
                    <div style={{ marginTop: '0.5rem' }}>
                      <Link
                        to="/login"
                        className="landing-cta-button"
                        style={{
                          display: 'block',
                          textAlign: 'center',
                          textDecoration: 'none',
                          width: '100%'
                        }}
                      >
                        Get Started
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
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

