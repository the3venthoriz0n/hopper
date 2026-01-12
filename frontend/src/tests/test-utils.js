import React from 'react';
import { render } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import axios from 'axios';

jest.mock('axios');
jest.mock('../services/api', () => ({
  getApiUrl: () => 'http://localhost:8000/api',
  default: axios,
}));

export const mockUseAuth = (overrides = {}) => ({
  user: null,
  isAdmin: false,
  setUser: jest.fn(),
  authLoading: false,
  checkAuth: jest.fn(),
  ...overrides,
});

export const mockUser = {
  id: 1,
  email: 'test@example.com',
  is_admin: false,
};

export const mockAdminUser = {
  id: 2,
  email: 'admin@example.com',
  is_admin: true,
};

export const renderWithRouter = (ui, { route = '/' } = {}) => {
  window.history.pushState({}, 'Test page', route);
  return render(ui, { wrapper: BrowserRouter });
};

export const mockAxiosGet = (response) => {
  axios.get.mockResolvedValue(response);
};

export const mockAxiosPost = (response) => {
  axios.post.mockResolvedValue(response);
};

export const mockAxiosError = (error) => {
  axios.get.mockRejectedValue(error);
  axios.post.mockRejectedValue(error);
};
