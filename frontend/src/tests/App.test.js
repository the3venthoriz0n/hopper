import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from '../App';
import { useAuth } from '../hooks/useAuth';

jest.mock('../hooks/useAuth');
jest.mock('../components/layout/LandingOrApp', () => {
  return function LandingOrApp() {
    return <div data-testid="landing-or-app">LandingOrApp</div>;
  };
});
jest.mock('../Login', () => {
  return function Login() {
    return <div data-testid="login">Login</div>;
  };
});
jest.mock('../Pricing', () => {
  return function Pricing() {
    return <div data-testid="pricing">Pricing</div>;
  };
});
jest.mock('../Terms', () => {
  return function Terms() {
    return <div data-testid="terms">Terms</div>;
  };
});
jest.mock('../Privacy', () => {
  return function Privacy() {
    return <div data-testid="privacy">Privacy</div>;
  };
});
jest.mock('../DeleteYourData', () => {
  return function DeleteYourData() {
    return <div data-testid="delete-your-data">DeleteYourData</div>;
  };
});
jest.mock('../Help', () => {
  return function Help() {
    return <div data-testid="help">Help</div>;
  };
});
jest.mock('../components/common/NotFound', () => {
  return function NotFound() {
    return <div data-testid="not-found">NotFound</div>;
  };
});
jest.mock('../components/auth/ProtectedRoute', () => {
  return function ProtectedRoute({ children, requireAdmin }) {
    return <div data-testid={`protected-route-${requireAdmin ? 'admin' : 'app'}`}>{children}</div>;
  };
});
jest.mock('../routes/AppRoutes', () => {
  return function AppRoutes() {
    return <div data-testid="app-routes">AppRoutes</div>;
  };
});
jest.mock('../AdminDashboard', () => {
  return function AdminDashboard() {
    return <div data-testid="admin-dashboard">AdminDashboard</div>;
  };
});

describe('App', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuth.mockReturnValue({
      user: null,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });
  });

  test('renders public routes', () => {
    const { unmount: unmount1 } = render(
      <MemoryRouter initialEntries={['/login']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('login')).toBeInTheDocument();
    unmount1();

    const { unmount: unmount2 } = render(
      <MemoryRouter initialEntries={['/pricing']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('pricing')).toBeInTheDocument();
    unmount2();

    const { unmount: unmount3 } = render(
      <MemoryRouter initialEntries={['/terms']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('terms')).toBeInTheDocument();
    unmount3();

    const { unmount: unmount4 } = render(
      <MemoryRouter initialEntries={['/privacy']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('privacy')).toBeInTheDocument();
    unmount4();

    const { unmount: unmount5 } = render(
      <MemoryRouter initialEntries={['/delete-your-data']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('delete-your-data')).toBeInTheDocument();
    unmount5();

    render(
      <MemoryRouter initialEntries={['/help']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('help')).toBeInTheDocument();
  });

  test('renders protected app routes under /app/*', () => {
    render(
      <MemoryRouter initialEntries={['/app']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('protected-route-app')).toBeInTheDocument();
    expect(screen.getByTestId('app-routes')).toBeInTheDocument();
  });

  test('renders admin route with protection', () => {
    render(
      <MemoryRouter initialEntries={['/admin']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('protected-route-admin')).toBeInTheDocument();
    expect(screen.getByTestId('admin-dashboard')).toBeInTheDocument();
  });

  test('renders 404 for unknown routes', () => {
    render(
      <MemoryRouter initialEntries={['/unknown-route']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('not-found')).toBeInTheDocument();
  });

  test('renders LandingOrApp for root path', () => {
    render(
      <MemoryRouter initialEntries={['/']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId('landing-or-app')).toBeInTheDocument();
  });
});
