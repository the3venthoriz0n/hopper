import { renderHook, waitFor } from '@testing-library/react';
import { act } from 'react';
import { useAuth } from '../../hooks/useAuth';
import axios from '../../services/api';
import { getApiUrl } from '../../services/api';

jest.mock('../../services/api', () => ({
  __esModule: true,
  getApiUrl: jest.fn(() => 'http://localhost:8000/api'),
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    patch: jest.fn(),
    defaults: {
      withCredentials: true,
      xsrfCookieName: 'csrf_token_client',
      xsrfHeaderName: 'X-CSRF-Token',
    },
    interceptors: {
      request: { use: jest.fn(), eject: jest.fn() },
      response: { use: jest.fn(), eject: jest.fn() },
    },
  },
}));

describe('useAuth', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getApiUrl.mockReturnValue('http://localhost:8000/api');
    axios.get.mockResolvedValue({ data: { user: null } });
  });

  test('returns loading state initially', () => {
    axios.get.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useAuth());

    expect(result.current.authLoading).toBe(true);
    expect(result.current.user).toBe(null);
    expect(result.current.isAdmin).toBe(false);
  });

  test('fetches user data on mount', async () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    axios.get.mockResolvedValue({
      data: { user: mockUser },
    });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(axios.get).toHaveBeenCalledWith('http://localhost:8000/api/auth/me');
    expect(result.current.user).toEqual(mockUser);
    expect(result.current.isAdmin).toBe(false);
  });

  test('sets user and isAdmin from API response', async () => {
    const mockAdminUser = { id: 2, email: 'admin@example.com', is_admin: true };
    axios.get.mockResolvedValue({
      data: { user: mockAdminUser },
    });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(result.current.user).toEqual(mockAdminUser);
    expect(result.current.isAdmin).toBe(true);
  });

  test('handles API errors gracefully', async () => {
    const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    axios.get.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(result.current.user).toBe(null);
    expect(result.current.isAdmin).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith('Auth check failed:', expect.any(Error));

    consoleErrorSpy.mockRestore();
  });

  test('handles null user response', async () => {
    axios.get.mockResolvedValue({
      data: { user: null },
    });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(result.current.user).toBe(null);
    expect(result.current.isAdmin).toBe(false);
  });

  test('provides checkAuth function', async () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    axios.get.mockResolvedValue({
      data: { user: mockUser },
    });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(typeof result.current.checkAuth).toBe('function');

    const newUser = { id: 2, email: 'new@example.com', is_admin: true };
    axios.get.mockResolvedValue({
      data: { user: newUser },
    });

    await act(async () => {
      await result.current.checkAuth();
    });

    await waitFor(() => {
      expect(result.current.user).toEqual(newUser);
      expect(result.current.isAdmin).toBe(true);
    });
  });
});
