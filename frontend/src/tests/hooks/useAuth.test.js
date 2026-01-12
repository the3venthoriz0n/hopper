import { renderHook, waitFor } from '@testing-library/react';
import { useAuth } from '../hooks/useAuth';
import axios from '../services/api';
import { getApiUrl } from '../services/api';

const mockAxiosGet = jest.fn();

jest.mock('../services/api', () => {
  const actualAxios = jest.requireActual('axios');
  return {
    getApiUrl: jest.fn(() => 'http://localhost:8000/api'),
    default: {
      ...actualAxios.default,
      get: mockAxiosGet,
    },
  };
});

describe('useAuth', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getApiUrl.mockReturnValue('http://localhost:8000/api');
    mockAxiosGet.mockClear();
  });

  test('returns loading state initially', () => {
    mockAxiosGet.mockImplementation(() => new Promise(() => {}));

    const { result } = renderHook(() => useAuth());

    expect(result.current.authLoading).toBe(true);
    expect(result.current.user).toBe(null);
    expect(result.current.isAdmin).toBe(false);
  });

  test('fetches user data on mount', async () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    mockAxiosGet.mockResolvedValue({
      data: { user: mockUser },
    });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(mockAxiosGet).toHaveBeenCalledWith('http://localhost:8000/api/auth/me');
    expect(result.current.user).toEqual(mockUser);
    expect(result.current.isAdmin).toBe(false);
  });

  test('sets user and isAdmin from API response', async () => {
    const mockAdminUser = { id: 2, email: 'admin@example.com', is_admin: true };
    mockAxiosGet.mockResolvedValue({
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
    mockAxiosGet.mockRejectedValue(new Error('Network error'));

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
    mockAxiosGet.mockResolvedValue({
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
    mockAxiosGet.mockResolvedValue({
      data: { user: mockUser },
    });

    const { result } = renderHook(() => useAuth());

    await waitFor(() => {
      expect(result.current.authLoading).toBe(false);
    });

    expect(typeof result.current.checkAuth).toBe('function');

    const newUser = { id: 2, email: 'new@example.com', is_admin: true };
    mockAxiosGet.mockResolvedValue({
      data: { user: newUser },
    });

    await result.current.checkAuth();

    await waitFor(() => {
      expect(result.current.user).toEqual(newUser);
      expect(result.current.isAdmin).toBe(true);
    });
  });
});
