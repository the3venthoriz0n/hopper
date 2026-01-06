import React from 'react';
import { Link } from 'react-router-dom';
import { HOPPER_COLORS } from '../../utils/colors';

export default function NotFound() {
  return (
    <div style={{ 
      textAlign: 'center', 
      padding: '2rem',
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      background: HOPPER_COLORS.white,
      color: HOPPER_COLORS.black
    }}>
      <h1 style={{ fontSize: '3rem', marginBottom: '1rem' }}>404</h1>
      <p style={{ fontSize: '1.2rem', marginBottom: '2rem' }}>Page Not Found</p>
      <Link 
        to="/" 
        style={{ 
          color: HOPPER_COLORS.grey, 
          textDecoration: 'none',
          fontSize: '1.1rem'
        }}
      >
        Go Home
      </Link>
    </div>
  );
}

