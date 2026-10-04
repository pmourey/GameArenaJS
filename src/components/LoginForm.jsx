import React, { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigate, useSearchParams } from 'react-router-dom'

export default function LoginForm() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const result = await login(username, password)
      
      if (result.success) {
        const redirectTo = searchParams.get('redirect') || '/arena'
        navigate(redirectTo)
      } else {
        setError(result.error || 'Échec de la connexion')
      }
    } catch (err) {
      setError('Erreur de connexion. Veuillez réessayer.')
      console.error('Login error:', err)
    } finally {
      setLoading(false)
    }
  }

  const redirectFrom = searchParams.get('redirect')
  const isPlaygroundRedirect = redirectFrom === '/playground'

  return (
    <div className="auth-form-container">
      <div className="auth-form">
        <h2>Connexion</h2>
        {isPlaygroundRedirect && (
          <div style={{ 
            padding: '12px', 
            marginBottom: '16px', 
            background: '#fff3cd', 
            border: '1px solid #ffc107', 
            borderRadius: '4px',
            color: '#856404',
            fontSize: '14px'
          }}>
            🔒 Le Playground nécessite une authentification. Veuillez vous connecter pour continuer.
          </div>
        )}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Nom d'utilisateur</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              disabled={loading}
            />
          </div>
          <div className="form-group">
            <label>Mot de passe</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
            />
          </div>
          {error && <div className="error-message">{error}</div>}
          <button type="submit" disabled={loading} className="btn-primary">
            {loading ? 'Connexion...' : 'Se connecter'}
          </button>
        </form>

        <div style={{ marginTop: '16px', padding: '10px', background: 'rgba(0,0,0,0.03)', borderRadius: '6px', fontSize: '12px' }}>
          <div style={{ fontWeight: 600, marginBottom: '6px', color: 'var(--muted, #666)' }}>Comptes de démonstration (cliquez pour tester) :</div>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            <button
              type="button"
              style={{ padding: '4px 8px', fontSize: '11px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', background: '#fff' }}
              onClick={() => { setUsername('philrg'); setPassword('password123'); }}
            >
              👤 philrg (Ligue Gold)
            </button>
            <button
              type="button"
              style={{ padding: '4px 8px', fontSize: '11px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', background: '#fff' }}
              onClick={() => { setUsername('alice'); setPassword('password123'); }}
            >
              👤 alice (Wood 2)
            </button>
            <button
              type="button"
              style={{ padding: '4px 8px', fontSize: '11px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', background: '#fff' }}
              onClick={() => { setUsername('bob'); setPassword('password123'); }}
            >
              👤 bob (Silver)
            </button>
          </div>
        </div>

        <p className="auth-switch">
          Pas encore de compte ? <a href="/register">S'inscrire</a>
        </p>
      </div>
    </div>
  )
}
