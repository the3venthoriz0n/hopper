import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../Login';
import axios from 'axios';

const mockNavigate = jest.fn();

jest.mock('axios');
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

beforeEach(() => {
  jest.clearAllMocks();
  mockNavigate.mockClear();
  window.history.replaceState = jest.fn();
});

describe('Login', () => {
  test('toggles between login and register modes', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Login />
      </MemoryRouter>
    );

    const loginTab = screen.getByText('Login', { selector: '.login-tab' });
    const registerTab = screen.getByText('Register');

    expect(loginTab).toHaveClass('active');
    expect(registerTab).not.toHaveClass('active');

    fireEvent.click(registerTab);

    expect(registerTab).toHaveClass('active');
    expect(loginTab).not.toHaveClass('active');
  });

  test('displays error messages from API', async () => {
    const errorMessage = 'Invalid credentials';
    axios.post.mockRejectedValue({
      response: {
        data: {
          detail: errorMessage,
        },
      },
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const form = emailInput.closest('form');
    
    // Ensure form exists before submitting
    expect(form).toBeTruthy();

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.submit(form);

    // Wait for all async state updates to complete (error message appears)
    await waitFor(() => {
      expect(screen.getByText(new RegExp(errorMessage, 'i'))).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  test('calls API with correct credentials on login', async () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    axios.post.mockResolvedValue({
      data: {
        user: mockUser,
      },
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const form = emailInput.closest('form');
    
    // Ensure form exists before submitting
    expect(form).toBeTruthy();

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.submit(form);

    // Wait for all async state updates to complete (success message appears)
    // This ensures setMessage and setLoading(false) have finished
    await waitFor(() => {
      expect(screen.getByText(/Login successful/i)).toBeInTheDocument();
    }, { timeout: 3000 });

    // Verify the API was called with correct parameters
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining('/auth/login'),
      {
        email: 'test@example.com',
        password: 'password123',
      },
      { withCredentials: true }
    );
  });

  test('redirects to /app after successful login', async () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    axios.post.mockResolvedValue({
      data: {
        user: mockUser,
      },
    });

    jest.useFakeTimers();

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const form = emailInput.closest('form');
    
    // Ensure form exists before submitting
    expect(form).toBeTruthy();

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.submit(form);

    // Wait for all async state updates to complete (success message appears)
    // This ensures setMessage and setLoading(false) have finished
    await waitFor(() => {
      expect(screen.getByText(/Login successful/i)).toBeInTheDocument();
    }, { timeout: 3000 });

    // Advance timers to trigger the setTimeout navigation
    jest.advanceTimersByTime(500);

    // Wait for navigation to be called
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/app');
    }, { timeout: 3000 });

    jest.useRealTimers();
  });

  test('redirects admins to /admin after login', async () => {
    const mockAdminUser = { id: 2, email: 'admin@example.com', is_admin: true };
    axios.post.mockResolvedValue({
      data: {
        user: mockAdminUser,
      },
    });

    jest.useFakeTimers();

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const form = emailInput.closest('form');
    
    // Ensure form exists before submitting
    expect(form).toBeTruthy();

    fireEvent.change(emailInput, { target: { value: 'admin@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.submit(form);

    // Wait for all async state updates to complete (success message appears)
    // This ensures setMessage and setLoading(false) have finished
    await waitFor(() => {
      expect(screen.getByText(/Login successful/i)).toBeInTheDocument();
    }, { timeout: 3000 });

    // Advance timers to trigger the setTimeout navigation
    jest.advanceTimersByTime(500);

    // Wait for navigation to be called
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/admin');
    }, { timeout: 3000 });

    jest.useRealTimers();
  });
});
