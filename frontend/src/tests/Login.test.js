import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from '../Login';
import axios from 'axios';

jest.mock('axios');
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => jest.fn(),
}));

const mockNavigate = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  require('react-router-dom').useNavigate = () => mockNavigate;
  window.history.replaceState = jest.fn();
});

describe('Login', () => {
  test('toggles between login and register modes', async () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const loginTab = screen.getByText('Login');
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
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const submitButton = screen.getByRole('button', { name: /login/i });

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(new RegExp(errorMessage, 'i'))).toBeInTheDocument();
    });
  });

  test('calls API with correct credentials on login', async () => {
    const mockUser = { id: 1, email: 'test@example.com', is_admin: false };
    axios.post.mockResolvedValue({
      data: {
        user: mockUser,
      },
    });

    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const submitButton = screen.getByRole('button', { name: /login/i });

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining('/auth/login'),
        {
          email: 'test@example.com',
          password: 'password123',
        },
        { withCredentials: true }
      );
    });
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
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const submitButton = screen.getByRole('button', { name: /login/i });

    fireEvent.change(emailInput, { target: { value: 'test@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/successful/i)).toBeInTheDocument();
    });

    jest.advanceTimersByTime(500);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/app');
    });

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
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    const emailInput = screen.getByPlaceholderText(/email/i);
    const passwordInput = screen.getByPlaceholderText(/password/i);
    const submitButton = screen.getByRole('button', { name: /login/i });

    fireEvent.change(emailInput, { target: { value: 'admin@example.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/successful/i)).toBeInTheDocument();
    });

    jest.advanceTimersByTime(500);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/admin');
    });

    jest.useRealTimers();
  });
});
