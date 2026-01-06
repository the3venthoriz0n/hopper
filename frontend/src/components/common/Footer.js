import React from 'react';
import { Link } from 'react-router-dom';
import { HOPPER_COLORS, rgba } from '../../utils/colors';

export default function Footer() {
  return (
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
        onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
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
        onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
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
        onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
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
          marginLeft: '1rem',
          transition: 'color 0.2s'
        }}
        onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
        onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
      >
        Delete Your Data
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
          onMouseEnter={(e) => e.target.style.color = rgba(HOPPER_COLORS.rgb.accent, 0.7)}
          onMouseLeave={(e) => e.target.style.color = HOPPER_COLORS.accent}
        >
          {process.env.REACT_APP_VERSION || 'dev'}
        </a>
      </div>
    </footer>
  );
}

