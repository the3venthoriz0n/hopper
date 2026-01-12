import React from 'react';
import { render, screen, waitFor } from '../../test-utils';
import ProtectedRoute from '../../../components/auth/ProtectedRoute';
import { useAuth } from '../../../hooks/useAuth';

const mockNavigate = jest.fn();

jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
  Navigate: ({ to }) => {
    // Simply call navigate immediately without useEffect
    mockNavigate(to);
    return null; // Return null instead of a div
  },
}));

jest.mock('../../../hooks/useAuth');

jest.mock('../../../components/common/LoadingScreen', () => {
  return function LoadingScreen() {
    return <div data-testid="loading-screen">Loading...</div>;
  };
});

const TestChild = ({ user, isAdmin }) => (
  <div data-testid="protected-content">
    Protected Content - User: {user?.email || 'None'} - Admin: {isAdmin ? 'Yes' : 'No'}
  </div>
);

describe('ProtectedRoute', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders loading screen during auth check', () => {
    useAuth.mockReturnValue({
      user: null,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: true,
    });

    render(
      <ProtectedRoute>
        <TestChild />
      </ProtectedRoute>
    );

    expect(screen.getByTestId('loading-screen')).toBeInTheDocument();
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  test('redirects to /login when user is not authenticated', () => {
    useAuth.mockReturnValue({
      user: null,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <ProtectedRoute>
        <TestChild />
      </ProtectedRoute>,
      { initialEntries: ['/app'] }
    );

    expect(mockNavigate).toHaveBeenCalledWith('/login');
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  test('renders children when user is authenticated', () => {
    const mockUser = { id: 1, email: 'test@example.com' };
    useAuth.mockReturnValue({
      user: mockUser,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <ProtectedRoute>
        <TestChild />
      </ProtectedRoute>
    );

    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
    expect(screen.getByText(/test@example.com/)).toBeInTheDocument();
  });

  test('passes user props to children', () => {
    const mockUser = { id: 1, email: 'test@example.com' };
    useAuth.mockReturnValue({
      user: mockUser,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <ProtectedRoute>
        <TestChild />
      </ProtectedRoute>
    );

    const content = screen.getByTestId('protected-content');
    expect(content).toHaveTextContent('test@example.com');
    expect(content).toHaveTextContent('Admin: No');
  });

  test('redirects non-admin users from admin routes', () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    useAuth.mockReturnValue({
      user: mockUser,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <ProtectedRoute requireAdmin>
        <TestChild />
      </ProtectedRoute>,
      { initialEntries: ['/admin'] }
    );

    expect(mockNavigate).toHaveBeenCalledWith('/app');
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  test('allows admin users to access admin routes', () => {
    const mockUser = { id: 1, email: 'admin@example.com', is_admin: true };
    useAuth.mockReturnValue({
      user: mockUser,
      isAdmin: true,
      setUser: jest.fn(),
      authLoading: false,
    });

    render(
      <ProtectedRoute requireAdmin>
        <TestChild />
      </ProtectedRoute>
    );

    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
    expect(screen.getByText(/admin@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/Admin: Yes/)).toBeInTheDocument();
  });
});