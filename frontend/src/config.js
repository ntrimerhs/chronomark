// Base URL for the backend API. Defaults to localhost for local development;
// set VITE_API_URL (e.g. in frontend/.env.local) to point at a remote/tunneled backend.
export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
