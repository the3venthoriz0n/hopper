import React from 'react';
import { HOPPER_COLORS } from '../../utils/colors';

export default function LoadingScreen() {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      background: HOPPER_COLORS.white,
      color: HOPPER_COLORS.black
    }}>
      <div>Loading...</div>
    </div>
  );
}

