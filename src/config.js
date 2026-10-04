/**
 * API configuration for GameArena frontend.
 * 
 * In development, the frontend runs on Vite dev server (port 5173)
 * with proxy to Flask backend (port 3000) - no CORS issues!
 * 
 * In production, use environment variable or empty string (same origin).
 * 
 * Last updated: 2025-11-07 - Fixed CORS with proxy
 */

// Always use relative path in browser if VITE_API_BASE_URL points to localhost/127.0.0.1
// This prevents mixed-content and unreachable host errors in Cloud Run / AI Studio preview
let rawUrl = import.meta.env.VITE_API_BASE_URL || ''
if (typeof window !== 'undefined' && (rawUrl.includes('127.0.0.1') || rawUrl.includes('localhost'))) {
  rawUrl = ''
}

export const API_BASE_URL = rawUrl

console.log('🔧 API_BASE_URL:', API_BASE_URL || '(using same-origin relative path)')

export default API_BASE_URL
