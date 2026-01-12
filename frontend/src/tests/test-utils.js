import React from 'react';
import { render } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';

jest.mock('axios', () => ({
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
}));

jest.mock('../services/api', () => ({
  getApiUrl: () => 'http://localhost:8000/api',
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
  const axios = require('axios');
  axios.get.mockResolvedValue(response);
};

export const mockAxiosPost = (response) => {
  const axios = require('axios');
  axios.post.mockResolvedValue(response);
};

export const mockAxiosError = (error) => {
  const axios = require('axios');
  axios.get.mockRejectedValue(error);
  axios.post.mockRejectedValue(error);
};
