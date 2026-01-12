import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import LandingOrApp from '../../../components/layout/LandingOrApp';
import { useAuth } from '../../../hooks/useAuth';
import LoadingScreen from '../../../components/common/LoadingScreen';
import PublicLanding from '../../../components/auth/PublicLanding';

jest.mock('../../../hooks/useAuth');
jest.mock('../../../components/common/LoadingScreen', () => {
  return function LoadingScreen() {
    return <div>Loading...</div>;
  };
});
jest.mock('../../../components/auth/PublicLanding', () => {
  return function PublicLanding() {
    return <div data-testid="public-landing">Public Landing</div>;
  };
});

describe('LandingOrApp', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('shows loading screen during auth check', () => {
    useAuth.mockReturnValue({
      user: null,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: true,
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LandingOrApp />
      </MemoryRouter>
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByTestId('public-landing')).not.toBeInTheDocument();
  });

  test('redirects authenticated users to /app', () => {
    const mockUser = { id: 1, email: 'test@example.com' };
    useAuth.mockReturnValue({
      user: mockUser,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LandingOrApp />
      </MemoryRouter>
    );

    expect(screen.queryByTestId('public-landing')).not.toBeInTheDocument();
  });

  test('shows public landing for unauthenticated users', () => {
    useAuth.mockReturnValue({
      user: null,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LandingOrApp />
      </MemoryRouter>
    );

    expect(screen.getByTestId('public-landing')).toBeInTheDocument();
    expect(screen.getByText('Public Landing')).toBeInTheDocument();
  });
});
