import axios from 'axios'

let csrfToken = null

export async function getCsrfToken() {
  if (csrfToken) return csrfToken
  
  try {
    const res = await axios.get('/api/csrf-token')
    csrfToken = res.data.csrf_token
    return csrfToken
  } catch (error) {
    console.error('Failed to get CSRF token:', error)
    return null
  }
}

export function setupCsrfInterceptor() {
  axios.interceptors.request.use(async (config) => {
    if (['post', 'put', 'delete', 'patch'].includes(config.method?.toLowerCase())) {
      const token = await getCsrfToken()
      if (token) {
        config.headers['X-CSRF-Token'] = token
      }
    }
    return config
  }, (error) => Promise.reject(error))
  
  axios.interceptors.response.use(
    (response) => response,
    (error) => {
      // Do not redirect externally on network errors
      return Promise.reject(error)
    }
  )
}

export function clearCsrfToken() {
  csrfToken = null
}
