import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  timeout: 30000,
});

const PUBLIC_AUTH_PATHS = new Set(['/auth/login/', '/auth/register/']);

// Request interceptor: attach auth token
api.interceptors.request.use((config) => {
  const requestPath = config.url ?? '';
  if (PUBLIC_AUTH_PATHS.has(requestPath)) {
    return config;
  }

  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Token ${token}`;
  }
  return config;
});

// Response interceptor: auto-logout on 401 (skip for login/register endpoints)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestPath = error.config?.url ?? '';
    if (error.response?.status === 401 && !PUBLIC_AUTH_PATHS.has(requestPath)) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
