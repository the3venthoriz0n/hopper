import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ProtectedRoute from '../../components/auth/ProtectedRoute';
import { useAuth } from '../../hooks/useAuth';
import LoadingScreen from '../../components/common/LoadingScreen';

jest.mock('../../hooks/useAuth');
jest.mock('../../components/common/LoadingScreen', () => {
  return function LoadingScreen() {
    return <div>Loading...</div>;
  };
});

const TestChild = ({ user, isAdmin }) => (
  <div data-testid="protected-content">
    Protected Content - User: {user?.email || 'None'} - Admin: {isAdmin ? 'Yes' : 'No'}
  </div>
);

describe('ProtectedRoute', () => {
  const mockNavigate = jest.fn();
  
  beforeEach(() => {
    jest.clearAllMocks();
    require('react-router-dom').useNavigate = () => mockNavigate;
  });

  test('renders loading screen during auth check', () => {
    useAuth.mockReturnValue({
      user: null,
      isAdmin: false,
      setUser: jest.fn(),
      authLoading: true,
    });

    render(
      <MemoryRouter>
        <ProtectedRoute>
          <TestChild />
        </ProtectedRoute>
      </MemoryRouter>
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
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
      <MemoryRouter initialEntries={['/app']}>
        <ProtectedRoute>
          <TestChild />
        </ProtectedRoute>
      </MemoryRouter>
    );

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
      <MemoryRouter>
        <ProtectedRoute>
          <TestChild />
        </ProtectedRoute>
      </MemoryRouter>
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
      <MemoryRouter>
        <ProtectedRoute>
          <TestChild />
        </ProtectedRoute>
      </MemoryRouter>
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
      <MemoryRouter initialEntries={['/admin']}>
        <ProtectedRoute requireAdmin>
          <TestChild />
        </ProtectedRoute>
      </MemoryRouter>
    );

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
      <MemoryRouter>
        <ProtectedRoute requireAdmin>
          <TestChild />
        </ProtectedRoute>
      </MemoryRouter>
    );

    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
    expect(screen.getByText(/admin@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/Admin: Yes/)).toBeInTheDocument();
  });
});
