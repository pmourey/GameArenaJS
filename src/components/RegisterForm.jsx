import React, { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigate } from 'react-router-dom'

export default function RegisterForm() {
  const [step, setStep] = useState('form') // 'form' | 'verify'
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [verificationCode, setVerificationCode] = useState('')
  
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [loading, setLoading] = useState(false)
  
  // Verification details
  const [smtpSent, setSmtpSent] = useState(false)
  const [smtpError, setSmtpError] = useState('')
  const [devCode, setDevCode] = useState('')

  const { registerRequest, verifyCode, resendCode } = useAuth()
  const navigate = useNavigate()

  const handleInitialSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccessMsg('')

    if (password !== confirmPassword) {
      setError('Les mots de passe ne correspondent pas.')
      return
    }

    if (password.length < 6) {
      setError('Le mot de passe doit comporter au moins 6 caractères.')
      return
    }

    setLoading(true)
    const result = await registerRequest(username, email, password)
    setLoading(false)

    if (result.success) {
      setSmtpSent(result.data?.smtpSent || false)
      setSmtpError(result.data?.smtpError || '')
      setDevCode(result.data?.devCode || '')
      setStep('verify')
      setSuccessMsg(`Un code de validation à 6 chiffres a été préparé pour ${email}.`)
    } else {
      setError(result.error || 'Erreur lors de la création du compte.')
    }
  }

  const handleVerifySubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccessMsg('')

    if (!verificationCode || verificationCode.trim().length !== 6) {
      setError('Veuillez entrer le code de validation à 6 chiffres.')
      return
    }

    setLoading(true)
    const result = await verifyCode(email, verificationCode.trim())
    setLoading(false)

    if (result.success) {
      setSuccessMsg('🎉 Votre compte a été validé avec succès ! Redirection en cours...')
      setTimeout(() => {
        navigate('/arena')
      }, 1200)
    } else {
      setError(result.error || 'Code invalide ou expiré.')
    }
  }

  const handleResend = async () => {
    setError('')
    setSuccessMsg('')
    setLoading(true)
    const result = await resendCode(email)
    setLoading(false)

    if (result.success) {
      setSmtpSent(result.data?.smtpSent || false)
      setSmtpError(result.data?.smtpError || '')
      if (result.data?.devCode) {
        setDevCode(result.data.devCode)
      }
      setSuccessMsg('Un nouveau code a été envoyé.')
    } else {
      setError(result.error || 'Impossible de renvoyer le code.')
    }
  }

  return (
    <div className="auth-form-container">
      <div className="auth-form" style={{ maxWidth: '440px', width: '100%' }}>
        <h2>{step === 'form' ? 'Créer un compte GameArena' : 'Validation par email'}</h2>

        {successMsg && (
          <div style={{
            padding: '10px 14px',
            marginBottom: '16px',
            background: '#d1fae5',
            color: '#065f46',
            border: '1px solid #a7f3d0',
            borderRadius: '6px',
            fontSize: '13px'
          }}>
            {successMsg}
          </div>
        )}

        {error && (
          <div className="error-message" style={{ marginBottom: '16px' }}>
            {error}
          </div>
        )}

        {step === 'form' ? (
          <form onSubmit={handleInitialSubmit}>
            <div className="form-group">
              <label>Nom d'utilisateur</label>
              <input
                type="text"
                placeholder="Ex: BotMaster99"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                disabled={loading}
              />
            </div>

            <div className="form-group">
              <label>Adresse email (pour validation)</label>
              <input
                type="email"
                placeholder="Ex: joueur@domaine.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={loading}
              />
              <small style={{ color: 'var(--muted, #666)', fontSize: '11px', marginTop: '4px', display: 'block' }}>
                Un code de confirmation sera envoyé à cette adresse.
              </small>
            </div>

            <div className="form-group">
              <label>Mot de passe</label>
              <input
                type="password"
                placeholder="Au moins 6 caractères"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                disabled={loading}
              />
            </div>

            <div className="form-group">
              <label>Confirmer le mot de passe</label>
              <input
                type="password"
                placeholder="Répétez le mot de passe"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={6}
                disabled={loading}
              />
            </div>

            <button type="submit" disabled={loading} className="btn-primary" style={{ marginTop: '8px' }}>
              {loading ? 'Envoi en cours...' : 'Continuer vers la validation'}
            </button>

            <p className="auth-switch" style={{ marginTop: '20px' }}>
              Déjà un compte ? <a href="/login">Se connecter</a>
            </p>
          </form>
        ) : (
          <div>
            <div style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              padding: '14px',
              borderRadius: '8px',
              marginBottom: '18px',
              fontSize: '13px'
            }}>
              <p style={{ margin: '0 0 8px 0', color: '#1e293b' }}>
                Un code de vérification à 6 chiffres a été généré pour :<br />
                <strong style={{ color: '#0ea5e9' }}>{email}</strong>
              </p>
              
              {smtpSent ? (
                <div style={{ color: '#15803d', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>✉️</span> Email envoyé avec succès via le serveur SMTP. Vérifiez votre boîte de réception.
                </div>
              ) : (
                <div style={{ marginTop: '8px', padding: '8px 10px', background: '#fef3c7', borderRadius: '6px', color: '#92400e', fontSize: '12px' }}>
                  <span>ℹ️</span> <strong>Code de validation instantané :</strong>{' '}
                  <span style={{ fontFamily: 'monospace', fontWeight: 'bold', fontSize: '16px', letterSpacing: '2px', background: '#fff', padding: '2px 8px', borderRadius: '4px' }}>
                    {devCode}
                  </span>
                  <div style={{ marginTop: '4px', fontSize: '11px', color: '#78350f' }}>
                    (Utilisable directement ci-dessous pour tester votre compte)
                  </div>
                </div>
              )}
            </div>

            <form onSubmit={handleVerifySubmit}>
              <div className="form-group">
                <label>Code de confirmation (6 chiffres)</label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="text"
                    maxLength={6}
                    placeholder="123456"
                    value={verificationCode}
                    onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, ''))}
                    required
                    style={{
                      fontSize: '20px',
                      letterSpacing: '6px',
                      textAlign: 'center',
                      fontFamily: 'monospace',
                      fontWeight: 'bold',
                      padding: '8px'
                    }}
                    disabled={loading}
                  />
                  {devCode && (
                    <button
                      type="button"
                      style={{
                        padding: '8px 12px',
                        fontSize: '12px',
                        cursor: 'pointer',
                        borderRadius: '6px',
                        background: '#0ea5e9',
                        color: '#fff',
                        border: 'none',
                        whiteSpace: 'nowrap'
                      }}
                      onClick={() => setVerificationCode(devCode)}
                    >
                      ⚡ Remplir
                    </button>
                  )}
                </div>
              </div>

              <button type="submit" disabled={loading} className="btn-primary" style={{ marginTop: '12px' }}>
                {loading ? 'Vérification...' : 'Valider et activer mon compte'}
              </button>
            </form>

            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '16px', fontSize: '12px' }}>
              <button
                type="button"
                onClick={handleResend}
                disabled={loading}
                style={{ background: 'none', border: 'none', color: '#0ea5e9', cursor: 'pointer', padding: 0 }}
              >
                🔄 Renvoyer un code
              </button>
              <button
                type="button"
                onClick={() => { setStep('form'); setError(''); }}
                style={{ background: 'none', border: 'none', color: 'var(--muted, #666)', cursor: 'pointer', padding: 0 }}
              >
                ✏️ Modifier mes informations
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
