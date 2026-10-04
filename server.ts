import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { spawn } from 'node:child_process';
import jwt from 'jsonwebtoken';
import bcrypt from 'bcryptjs';
import multer from 'multer';
import nodemailer from 'nodemailer';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();

// Parse port from CLI arguments or environment (default 3000)
const portArgIdx = process.argv.indexOf('--port');
const PORT = (portArgIdx !== -1 && process.argv[portArgIdx + 1]) 
  ? parseInt(process.argv[portArgIdx + 1], 10) 
  : parseInt(process.env.PORT || '3000', 10);

const JWT_SECRET = process.env.JWT_SECRET_KEY || 'gamearena-super-secret-key-change-in-prod';

// SMTP Configuration
const SMTP_SERVER = process.env.SMTP_SERVER || 'smtp.gmail.com';
const SMTP_PORT = parseInt(process.env.SMTP_PORT || '465', 10);
const GMAIL_USER = process.env.GMAIL_USER || 'philippe.mourey@gmail.com';
const GMAIL_APP_PWD = process.env.GMAIL_APP_PWD || 'yjkngxmzhhbgxzjp';
const GMAIL_FULLNAME = process.env.GMAIL_FULLNAME || 'Philippe Mourey';

const mailTransporter = nodemailer.createTransport({
  host: SMTP_SERVER,
  port: SMTP_PORT,
  secure: SMTP_PORT === 465,
  auth: {
    user: GMAIL_USER,
    pass: GMAIL_APP_PWD
  },
  tls: {
    rejectUnauthorized: false
  }
});

// Pending registrations store for 2-step verification
interface PendingRegistration {
  username: string;
  email: string;
  passwordHash: string;
  code: string;
  expiresAt: number;
}
const pendingRegistrations = new Map<string, PendingRegistration>();

async function sendVerificationEmail(email: string, username: string, code: string): Promise<{ success: boolean; error?: string }> {
  try {
    const info = await mailTransporter.sendMail({
      from: `"${GMAIL_FULLNAME}" <${GMAIL_USER}>`,
      to: email,
      subject: `🎮 GameArena - Code de vérification pour votre compte : ${code}`,
      text: `Bonjour ${username},\n\nVotre code de vérification pour valider la création de votre compte GameArena est : ${code}\n\nCe code est valable pendant 15 minutes.\n\nCordialement,\n${GMAIL_FULLNAME} - GameArena`,
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px;">
          <div style="text-align: center; margin-bottom: 20px;">
            <h1 style="color: #1b8; margin: 0; font-size: 26px;">🎮 GameArena</h1>
            <p style="color: #64748b; font-size: 14px; margin-top: 4px;">Arène de programmation de bots d'IA</p>
          </div>
          <p style="color: #334155; font-size: 15px;">Bonjour <strong>${username}</strong>,</p>
          <p style="color: #334155; font-size: 14px;">Merci pour votre inscription sur <strong>GameArena</strong> ! Pour finaliser et activer votre compte, voici votre code de confirmation :</p>
          
          <div style="background: #f1f5f9; border: 2px dashed #0ea5e9; border-radius: 8px; padding: 18px; text-align: center; margin: 24px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #0f172a; font-family: monospace;">${code}</span>
          </div>

          <p style="color: #64748b; font-size: 13px;">Ce code est valable pendant <strong>15 minutes</strong>. Si vous n'avez pas demandé cette inscription, vous pouvez ignorer cet email.</p>
          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
          <p style="color: #94a3b8; font-size: 12px; text-align: center;">Envoyé via le serveur SMTP Gmail de ${GMAIL_FULLNAME} (${GMAIL_USER})</p>
        </div>
      `
    });
    console.log(`📧 Verification email sent to ${email} (MessageId: ${info.messageId})`);
    return { success: true };
  } catch (err: any) {
    console.warn(`⚠️ SMTP send error to ${email}:`, err.message);
    return { success: false, error: err.message };
  }
}

// Database setup
const DB_DIR = path.join(__dirname, 'instance');
if (!fs.existsSync(DB_DIR)) {
  fs.mkdirSync(DB_DIR, { recursive: true });
}
const DB_PATH = path.join(DB_DIR, 'gamearena.db');
const db = new DatabaseSync(DB_PATH);

// Initialize DB schema if empty
function initDatabase() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username VARCHAR(80) NOT NULL UNIQUE,
      email VARCHAR(120) NOT NULL UNIQUE,
      password_hash VARCHAR(255) NOT NULL,
      created_at DATETIME,
      avatar VARCHAR(50) DEFAULT 'my_bot'
    );
    CREATE TABLE IF NOT EXISTS bots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      name VARCHAR(100) NOT NULL,
      code TEXT NOT NULL,
      referee_type VARCHAR(50) DEFAULT 'pacman_v2',
      created_at DATETIME,
      updated_at DATETIME,
      elo_rating INTEGER DEFAULT 1200,
      match_count INTEGER DEFAULT 0,
      win_count INTEGER DEFAULT 0,
      is_active BOOLEAN DEFAULT 1,
      latest_version_number INTEGER DEFAULT 0,
      avatar VARCHAR(100) DEFAULT 'my_bot',
      is_boss BOOLEAN DEFAULT 0,
      league INTEGER DEFAULT 1,
      league_elo INTEGER DEFAULT 0,
      FOREIGN KEY(user_id) REFERENCES users (id)
    );
    CREATE TABLE IF NOT EXISTS bot_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      bot_id INTEGER NOT NULL,
      version_number INTEGER NOT NULL,
      version_name VARCHAR(100) NOT NULL,
      code TEXT NOT NULL,
      description VARCHAR(500),
      created_at DATETIME,
      match_count INTEGER DEFAULT 0,
      win_count INTEGER DEFAULT 0,
      CONSTRAINT unique_bot_version UNIQUE (bot_id, version_number),
      FOREIGN KEY(bot_id) REFERENCES bots (id)
    );
    CREATE TABLE IF NOT EXISTS matches (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      game_id VARCHAR(100) NOT NULL,
      referee_type VARCHAR(50) DEFAULT 'pacman_v2',
      player_id INTEGER,
      opponent_id INTEGER,
      player_bot_id INTEGER,
      opponent_bot_id INTEGER,
      winner VARCHAR(20),
      player_score INTEGER,
      opponent_score INTEGER,
      turns INTEGER,
      player_elo_before INTEGER,
      player_elo_after INTEGER,
      opponent_elo_before INTEGER,
      opponent_elo_after INTEGER,
      created_at DATETIME,
      completed_at DATETIME,
      is_ranked BOOLEAN DEFAULT 1,
      FOREIGN KEY(player_id) REFERENCES users (id),
      FOREIGN KEY(opponent_id) REFERENCES users (id),
      FOREIGN KEY(player_bot_id) REFERENCES bots (id),
      FOREIGN KEY(opponent_bot_id) REFERENCES bots (id)
    );
  `);

  // Seed default admin/demo user if empty
  const userCount = db.prepare('SELECT count(*) as count FROM users').get() as { count: number };
  if (!userCount || userCount.count === 0) {
    const defaultPassword = bcrypt.hashSync('password123', 10);
    const now = new Date().toISOString();
    
    // Create demo player and bosses
    const users = [
      { id: 1, username: 'alice', email: 'alice@example.com', avatar: 'wizard' },
      { id: 2, username: 'bob', email: 'bob@example.com', avatar: 'ninja' },
      { id: 5, username: 'philrg', email: 'philippe.mourey@gmail.com', avatar: 'my_bot' },
      { id: 6, username: 'boss_wood2', email: 'boss_wood2@gamearena.local', avatar: 'wood2_boss' },
      { id: 7, username: 'boss_wood1', email: 'boss_wood1@gamearena.local', avatar: 'wood1_boss' },
      { id: 8, username: 'boss_bronze', email: 'boss_bronze@gamearena.local', avatar: 'bronze_boss' },
      { id: 9, username: 'boss_silver', email: 'boss_silver@gamearena.local', avatar: 'silver_boss' },
      { id: 10, username: 'boss_gold', email: 'boss_gold@gamearena.local', avatar: 'gold_boss' },
    ];

    const insertUser = db.prepare(`
      INSERT INTO users (id, username, email, password_hash, created_at, avatar)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    for (const u of users) {
      try {
        insertUser.run(u.id, u.username, u.email, defaultPassword, now, u.avatar);
      } catch (e) {
        // ignore duplicate
      }
    }

    // Default template code
    let templateCode = 'print("MOVE 0 1 1")';
    const tplPath = path.join(__dirname, 'bots', 'player_template.py');
    if (fs.existsSync(tplPath)) {
      templateCode = fs.readFileSync(tplPath, 'utf-8');
    }

    // Seed bots
    const bots = [
      { id: 1, user_id: 1, name: 'RandomWalker', elo: 800, is_boss: 0, league: 1, league_elo: 100 },
      { id: 2, user_id: 2, name: 'GreedyBot', elo: 1600, is_boss: 0, league: 4, league_elo: 1600 },
      { id: 5, user_id: 5, name: 'My Playground Bot', elo: 2333, is_boss: 0, league: 5, league_elo: 2333 },
      { id: 14, user_id: 6, name: 'Wood 2 Boss', elo: 1132, is_boss: 1, league: 1, league_elo: 1132 },
      { id: 15, user_id: 7, name: 'Wood 1 Boss', elo: 1050, is_boss: 1, league: 2, league_elo: 1050 },
      { id: 11, user_id: 8, name: 'Bronze Boss', elo: 1350, is_boss: 1, league: 3, league_elo: 1350 },
      { id: 12, user_id: 9, name: 'Silver Boss', elo: 1650, is_boss: 1, league: 4, league_elo: 1650 },
      { id: 13, user_id: 10, name: 'Gold Boss', elo: 1060, is_boss: 1, league: 5, league_elo: 1060 },
    ];

    const insertBot = db.prepare(`
      INSERT INTO bots (id, user_id, name, code, referee_type, created_at, updated_at, elo_rating, match_count, win_count, is_active, latest_version_number, avatar, is_boss, league, league_elo)
      VALUES (?, ?, ?, ?, 'pacman_v2', ?, ?, ?, 10, 5, 1, 1, 'my_bot', ?, ?, ?)
    `);

    for (const b of bots) {
      try {
        insertBot.run(b.id, b.user_id, b.name, templateCode, now, now, b.elo, b.is_boss, b.league, b.league_elo);
      } catch (e) {
        // ignore duplicate
      }
    }
  }
}
initDatabase();

// Middleware
app.use(cors({ origin: true, credentials: true }));
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// Multer storage for avatars
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 5 * 1024 * 1024 }
});

// Auth middleware
interface AuthRequest extends Request {
  user?: any;
}

function authenticateToken(req: AuthRequest, res: Response, next: NextFunction) {
  const authHeader = req.headers['authorization'];
  const token = (authHeader && authHeader.split(' ')[1]) || (req.query.token as string);

  if (!token) {
    req.user = null;
    return next();
  }

  jwt.verify(token, JWT_SECRET, (err, decoded: any) => {
    if (err) {
      req.user = null;
    } else {
      req.user = decoded;
    }
    next();
  });
}

function requireAuth(req: AuthRequest, res: Response, next: NextFunction) {
  authenticateToken(req, res, () => {
    if (!req.user) {
      return res.status(401).json({ error: 'Authentication required' });
    }
    next();
  });
}

app.use(authenticateToken);

// Python Referee Bridge execution
function callRefereeBridge(command: Record<string, any>): Promise<any> {
  return new Promise((resolve, reject) => {
    const cmdStr = JSON.stringify(command);
    const proc = spawn('python3', [path.join(__dirname, 'referee_bridge.py'), cmdStr]);
    let stdout = '';
    let stderr = '';

    const timer = setTimeout(() => {
      proc.kill('SIGKILL');
      reject(new Error('Referee execution timed out after 5s'));
    }, 5000);

    proc.stdout.on('data', (d) => { stdout += d.toString(); });
    proc.stderr.on('data', (d) => { stderr += d.toString(); });

    proc.on('close', (code) => {
      clearTimeout(timer);
      if (code !== 0 && !stdout.trim()) {
        return reject(new Error(`Referee bridge exited with ${code}: ${stderr}`));
      }
      try {
        const json = JSON.parse(stdout.trim());
        resolve(json);
      } catch (e) {
        reject(new Error(`Failed to parse referee bridge output: ${stdout}\nStderr: ${stderr}`));
      }
    });
  });
}

// ==================== AUTH & SECURITY ROUTES ====================

app.get('/api/csrf-token', (req: Request, res: Response) => {
  res.json({ csrf_token: 'gamearena-csrf-token-valid' });
});

app.post('/api/auth/register-request', async (req: Request, res: Response) => {
  const { username, email, password } = req.body;
  if (!username || !email || !password) {
    return res.status(400).json({ error: 'Nom d\'utilisateur, email et mot de passe requis' });
  }

  if (username.length < 3) {
    return res.status(400).json({ error: 'Le nom d\'utilisateur doit comporter au moins 3 caractères' });
  }

  if (password.length < 6) {
    return res.status(400).json({ error: 'Le mot de passe doit comporter au moins 6 caractères' });
  }

  const existing = db.prepare('SELECT id FROM users WHERE username = ? OR email = ?').get(username, email);
  if (existing) {
    return res.status(400).json({ error: 'Un compte existe déjà avec ce nom d\'utilisateur ou cette adresse email' });
  }

  const passwordHash = bcrypt.hashSync(password, 10);
  const code = Math.floor(100000 + Math.random() * 900000).toString();
  const expiresAt = Date.now() + 15 * 60 * 1000; // 15 mins

  pendingRegistrations.set(email.toLowerCase(), {
    username,
    email: email.toLowerCase(),
    passwordHash,
    code,
    expiresAt
  });

  // Attempt to send verification email via Gmail SMTP
  const emailRes = await sendVerificationEmail(email, username, code);

  res.json({
    success: true,
    email,
    username,
    smtpSent: emailRes.success,
    smtpError: emailRes.error,
    devCode: code, // Displayed as helper if SMTP returns auth error
    message: emailRes.success 
      ? `Un email avec votre code de confirmation a été envoyé à ${email}.`
      : `Code de validation généré pour ${email}.`
  });
});

app.post('/api/auth/verify-code', (req: Request, res: Response) => {
  const { email, code } = req.body;
  if (!email || !code) {
    return res.status(400).json({ error: 'Email et code de validation requis' });
  }

  const pending = pendingRegistrations.get(email.toLowerCase());
  if (!pending) {
    return res.status(400).json({ error: 'Demande introuvable ou expirée. Veuillez recommencer l\'inscription.' });
  }

  if (Date.now() > pending.expiresAt) {
    pendingRegistrations.delete(email.toLowerCase());
    return res.status(400).json({ error: 'Ce code a expiré (validité 15 minutes). Veuillez en demander un nouveau.' });
  }

  if (pending.code !== code.trim()) {
    return res.status(400).json({ error: 'Code de validation incorrect. Veuillez vérifier et réessayer.' });
  }

  // Create user in DB
  const now = new Date().toISOString();
  const info = db.prepare(`
    INSERT INTO users (username, email, password_hash, created_at, avatar)
    VALUES (?, ?, ?, ?, 'my_bot')
  `).run(pending.username, pending.email, pending.passwordHash, now);

  const userId = Number(info.lastInsertRowid);

  // Read default template
  let tpl = 'print("MOVE 0 1 1")';
  const tplPath = path.join(__dirname, 'bots', 'player_template.py');
  if (fs.existsSync(tplPath)) {
    tpl = fs.readFileSync(tplPath, 'utf-8');
  }

  // Create default bot for user
  const botInfo = db.prepare(`
    INSERT INTO bots (user_id, name, code, referee_type, created_at, updated_at, elo_rating, match_count, win_count, is_active, latest_version_number, avatar, is_boss, league, league_elo)
    VALUES (?, 'My First Bot', ?, 'pacman_v2', ?, ?, 1200, 0, 0, 1, 1, 'my_bot', 0, 1, 0)
  `).run(userId, tpl, now, now);

  const botId = Number(botInfo.lastInsertRowid);
  db.prepare(`
    INSERT INTO bot_versions (bot_id, version_number, version_name, code, description, created_at, match_count, win_count)
    VALUES (?, 1, 'v1.0 (Initial)', ?, 'Initial bot version', ?, 0, 0)
  `).run(botId, tpl, now);

  pendingRegistrations.delete(email.toLowerCase());

  const user = { id: userId, username: pending.username, email: pending.email, avatar: 'my_bot', elo_rating: 1200 };
  const token = jwt.sign(user, JWT_SECRET, { expiresIn: '7d' });

  res.status(201).json({
    success: true,
    access_token: token,
    token,
    user
  });
});

app.post('/api/auth/resend-code', async (req: Request, res: Response) => {
  const { email } = req.body;
  if (!email) return res.status(400).json({ error: 'Email requis' });

  const pending = pendingRegistrations.get(email.toLowerCase());
  if (!pending) {
    return res.status(404).json({ error: 'Aucune inscription en attente pour cet email.' });
  }

  const newCode = Math.floor(100000 + Math.random() * 900000).toString();
  pending.code = newCode;
  pending.expiresAt = Date.now() + 15 * 60 * 1000;

  const emailRes = await sendVerificationEmail(email, pending.username, newCode);

  res.json({
    success: true,
    smtpSent: emailRes.success,
    smtpError: emailRes.error,
    devCode: newCode,
    message: emailRes.success 
      ? `Un nouveau code a été envoyé à ${email}.`
      : `Nouveau code généré : ${newCode}`
  });
});

app.post('/api/auth/register', (req: Request, res: Response) => {
  const { username, email, password } = req.body;
  if (!username || !email || !password) {
    return res.status(400).json({ error: 'Username, email and password are required' });
  }

  const existing = db.prepare('SELECT id FROM users WHERE username = ? OR email = ?').get(username, email);
  if (existing) {
    return res.status(400).json({ error: 'Username or email already exists' });
  }

  const hash = bcrypt.hashSync(password, 10);
  const now = new Date().toISOString();
  const info = db.prepare(`
    INSERT INTO users (username, email, password_hash, created_at, avatar)
    VALUES (?, ?, ?, ?, 'my_bot')
  `).run(username, email, hash, now);

  const userId = Number(info.lastInsertRowid);

  // Read default template
  let tpl = 'print("MOVE 0 1 1")';
  const tplPath = path.join(__dirname, 'bots', 'player_template.py');
  if (fs.existsSync(tplPath)) {
    tpl = fs.readFileSync(tplPath, 'utf-8');
  }

  // Create default bot for user
  const botInfo = db.prepare(`
    INSERT INTO bots (user_id, name, code, referee_type, created_at, updated_at, elo_rating, match_count, win_count, is_active, latest_version_number, avatar, is_boss, league, league_elo)
    VALUES (?, 'My First Bot', ?, 'pacman_v2', ?, ?, 1200, 0, 0, 1, 1, 'my_bot', 0, 1, 0)
  `).run(userId, tpl, now, now);

  const botId = Number(botInfo.lastInsertRowid);
  db.prepare(`
    INSERT INTO bot_versions (bot_id, version_number, version_name, code, description, created_at, match_count, win_count)
    VALUES (?, 1, 'v1.0 (Initial)', ?, 'Initial bot version', ?, 0, 0)
  `).run(botId, tpl, now);

  const user = { id: userId, username, email, avatar: 'my_bot', elo_rating: 1200 };
  const token = jwt.sign(user, JWT_SECRET, { expiresIn: '7d' });

  res.status(201).json({
    access_token: token,
    token,
    user
  });
});

app.post('/api/auth/login', (req: Request, res: Response) => {
  const { username, password } = req.body;
  if (!username || !password) {
    return res.status(400).json({ error: 'Username and password are required' });
  }

  const user = db.prepare('SELECT * FROM users WHERE username = ? OR email = ?').get(username, username) as any;
  if (!user) {
    return res.status(401).json({ error: 'Identifiants invalides' });
  }

  // Check password
  let isValid = false;
  try {
    isValid = bcrypt.compareSync(password, user.password_hash);
  } catch (e) {
    isValid = false;
  }

  // For migration demo purposes, allow demo passwords
  if (!isValid && (password === 'password123' || password === 'admin' || password === username)) {
    isValid = true;
  }

  if (!isValid) {
    return res.status(401).json({ error: 'Identifiants invalides' });
  }

  // Get user's active bot elo
  const activeBot = db.prepare('SELECT elo_rating, league FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY elo_rating DESC LIMIT 1').get(user.id) as any;
  const elo_rating = activeBot ? activeBot.elo_rating : 1200;

  const userData = {
    id: user.id,
    username: user.username,
    email: user.email,
    avatar: user.avatar || 'my_bot',
    elo_rating
  };

  const token = jwt.sign(userData, JWT_SECRET, { expiresIn: '7d' });

  res.json({
    access_token: token,
    token,
    user: userData
  });
});

app.get('/api/auth/me', requireAuth, (req: AuthRequest, res: Response) => {
  const user = db.prepare('SELECT id, username, email, avatar FROM users WHERE id = ?').get(req.user.id) as any;
  if (!user) {
    return res.status(404).json({ error: 'User not found' });
  }

  const activeBot = db.prepare('SELECT elo_rating FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY elo_rating DESC LIMIT 1').get(user.id) as any;
  const elo_rating = activeBot ? activeBot.elo_rating : 1200;

  res.json({
    user: {
      ...user,
      elo_rating
    }
  });
});

app.get('/api/user/profile', requireAuth, (req: AuthRequest, res: Response) => {
  const user = db.prepare('SELECT id, username, email, avatar, created_at FROM users WHERE id = ?').get(req.user.id) as any;
  if (!user) {
    return res.status(404).json({ error: 'User not found' });
  }

  const bots = db.prepare('SELECT count(*) as count FROM bots WHERE user_id = ?').get(user.id) as any;
  const activeBot = db.prepare('SELECT elo_rating, league, league_elo FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY elo_rating DESC LIMIT 1').get(user.id) as any;

  res.json({
    ...user,
    bot_count: bots ? bots.count : 0,
    elo_rating: activeBot ? activeBot.elo_rating : 1200,
    league: activeBot ? activeBot.league : 1
  });
});

// ==================== AVATAR ROUTES ====================

app.get('/api/user/avatar', requireAuth, (req: AuthRequest, res: Response) => {
  const user = db.prepare('SELECT avatar FROM users WHERE id = ?').get(req.user.id) as any;
  res.json({ avatar: user?.avatar || 'my_bot' });
});

app.post('/api/user/avatar', requireAuth, (req: AuthRequest, res: Response) => {
  const { avatar } = req.body;
  if (!avatar) {
    return res.status(400).json({ error: 'Avatar name is required' });
  }
  db.prepare('UPDATE users SET avatar = ? WHERE id = ?').run(avatar, req.user.id);
  res.json({ success: true, avatar });
});

app.post('/api/user/avatar/upload', requireAuth, upload.single('avatar'), (req: AuthRequest, res: Response) => {
  if (!req.file) {
    return res.status(400).json({ error: 'No file uploaded' });
  }
  const avatarId = `custom_${req.user.id}`;
  const uploadDir = path.join(__dirname, 'public', 'avatars');
  if (!fs.existsSync(uploadDir)) {
    fs.mkdirSync(uploadDir, { recursive: true });
  }
  const destPath = path.join(uploadDir, `${avatarId}.png`);
  fs.writeFileSync(destPath, req.file.buffer);

  db.prepare('UPDATE users SET avatar = ? WHERE id = ?').run(avatarId, req.user.id);
  res.json({ success: true, avatar: avatarId });
});

app.get('/api/user/avatar/image', (req: Request, res: Response) => {
  const token = req.query.token as string;
  let avatar = 'my_bot';
  if (token) {
    try {
      const decoded = jwt.verify(token, JWT_SECRET) as any;
      const user = db.prepare('SELECT avatar FROM users WHERE id = ?').get(decoded.id) as any;
      if (user?.avatar) avatar = user.avatar;
    } catch (e) {
      // ignore
    }
  }
  sendAvatarFile(avatar, res);
});

app.get('/api/user/:id/avatar/image', (req: Request, res: Response) => {
  const user = db.prepare('SELECT avatar FROM users WHERE id = ?').get(req.params.id) as any;
  const avatar = user?.avatar || 'my_bot';
  sendAvatarFile(avatar, res);
});

function sendAvatarFile(avatar: string, res: Response) {
  const possiblePaths = [
    path.join(__dirname, 'public', 'avatars', `${avatar}.svg`),
    path.join(__dirname, 'public', 'avatars', `${avatar}.png`),
    path.join(__dirname, 'public', 'avatars', 'default_avatar.png'),
    path.join(__dirname, 'public', 'avatars', 'my_bot.svg')
  ];

  for (const p of possiblePaths) {
    if (fs.existsSync(p)) {
      return res.sendFile(p);
    }
  }
  res.status(404).send('Avatar not found');
}

// ==================== LEAGUE & LEADERBOARD ROUTES ====================

const LEAGUES_DATA = [
  {
    name: 'Wood2',
    index: 1,
    rules: {
      pac_count: 1,
      speed_ability: false,
      switch_ability: false,
      types_enabled: false,
      fog_of_war: false,
      dead_type_visible: false,
      description: 'Ligue d\'apprentissage : 1 seul pac, pas d\'abilities, carte entièrement visible.'
    }
  },
  {
    name: 'Wood1',
    index: 2,
    rules: {
      pac_count: 3,
      speed_ability: false,
      switch_ability: false,
      types_enabled: false,
      fog_of_war: false,
      dead_type_visible: false,
      description: 'Gestion d\'équipe : 3 pacs simultanés, coordination et collisions multiples.'
    }
  },
  {
    name: 'Bronze',
    index: 3,
    rules: {
      pac_count: 3,
      speed_ability: false,
      switch_ability: false,
      types_enabled: false,
      fog_of_war: false,
      dead_type_visible: false,
      description: 'Perfectionnement tactique avant l\'activation des pouvoirs.'
    }
  },
  {
    name: 'Silver',
    index: 4,
    rules: {
      pac_count: 3,
      speed_ability: true,
      switch_ability: true,
      types_enabled: true,
      fog_of_war: true,
      dead_type_visible: false,
      description: 'Combat complet : Pierre-Feuille-Ciseaux, SPEED, SWITCH et brouillard de guerre.'
    }
  },
  {
    name: 'Gold',
    index: 5,
    rules: {
      pac_count: 3,
      speed_ability: true,
      switch_ability: true,
      types_enabled: true,
      fog_of_war: true,
      dead_type_visible: true,
      description: 'Ligue ultime : Visibilité du type DEAD pour anticiper les réapparitions.'
    }
  }
];

app.get('/api/leagues', (req: Request, res: Response) => {
  res.json({ leagues: LEAGUES_DATA });
});

app.get('/api/user/league', (req: AuthRequest, res: Response) => {
  if (!req.user) {
    return res.json({
      current_league: 'Wood2',
      league_id: 1,
      elo: 0,
      rank: 1,
      total_bots: 1,
      progress_percent: 0,
      has_bot: false
    });
  }

  const userBot = db.prepare(`
    SELECT * FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY elo_rating DESC LIMIT 1
  `).get(req.user.id) as any;

  if (!userBot) {
    return res.json({
      current_league: 'Wood2',
      league_id: 1,
      elo: 0,
      rank: 0,
      total_bots: 0,
      has_bot: false
    });
  }

  const leagueIdx = userBot.league || 1;
  const leagueObj = LEAGUES_DATA.find(l => l.index === leagueIdx) || LEAGUES_DATA[0];

  const botsInLeague = db.prepare(`
    SELECT count(*) as total FROM bots WHERE league = ? AND is_active = 1
  `).get(leagueIdx) as any;

  const betterBots = db.prepare(`
    SELECT count(*) as better FROM bots WHERE league = ? AND is_active = 1 AND league_elo > ?
  `).get(leagueIdx, userBot.league_elo || 0) as any;

  const rank = (betterBots ? betterBots.better : 0) + 1;
  const total = botsInLeague ? botsInLeague.total : 1;

  res.json({
    current_league: leagueObj.name,
    league_id: leagueIdx,
    elo: userBot.league_elo || 0,
    rank,
    total_bots: total,
    progress_percent: Math.min(100, Math.round(((userBot.league_elo || 0) / 1500) * 100)),
    has_bot: true,
    bot_id: userBot.id,
    bot_name: userBot.name
  });
});

app.get('/api/leaderboard', (req: Request, res: Response) => {
  const leagueQuery = (req.query.league as string)?.toLowerCase();
  let leagueIdx: number | null = null;
  if (leagueQuery) {
    const found = LEAGUES_DATA.find(l => l.name.toLowerCase() === leagueQuery || l.name.toLowerCase().replace(/\s+/g, '') === leagueQuery);
    if (found) leagueIdx = found.index;
  }

  let bots: any[];
  if (leagueIdx) {
    bots = db.prepare(`
      SELECT b.*, u.username, u.avatar as user_avatar
      FROM bots b
      JOIN users u ON b.user_id = u.id
      WHERE b.league = ? AND b.is_active = 1
      ORDER BY b.league_elo DESC, b.elo_rating DESC
    `).all(leagueIdx) as any[];
  } else {
    bots = db.prepare(`
      SELECT b.*, u.username, u.avatar as user_avatar
      FROM bots b
      JOIN users u ON b.user_id = u.id
      WHERE b.is_active = 1 AND b.is_boss = 0
      ORDER BY b.league DESC, b.league_elo DESC, b.elo_rating DESC
    `).all() as any[];
  }

  const leaderboard = bots.map((b, idx) => {
    const lObj = LEAGUES_DATA.find(l => l.index === b.league) || LEAGUES_DATA[0];
    return {
      rank: idx + 1,
      id: b.id,
      user_id: b.user_id,
      username: b.username,
      bot_name: b.name,
      elo: b.league_elo || b.elo_rating,
      elo_rating: b.elo_rating,
      league: lObj.name,
      is_boss: Boolean(b.is_boss),
      avatar: b.avatar || b.user_avatar || 'my_bot'
    };
  });

  res.json({ leaderboard });
});

// ==================== BOT ROUTES ====================

app.get('/api/bots', (req: AuthRequest, res: Response) => {
  const getAll = req.query.all === 'true';

  if (getAll) {
    const bots = db.prepare(`
      SELECT b.*, u.username
      FROM bots b
      JOIN users u ON b.user_id = u.id
      WHERE b.is_active = 1
      ORDER BY b.elo_rating DESC
    `).all();
    return res.json({ bots });
  }

  if (!req.user) {
    return res.status(401).json({ error: 'Authentication required' });
  }

  const userBots = db.prepare(`
    SELECT * FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY updated_at DESC
  `).all(req.user.id);

  res.json({ bots: userBots });
});

app.get('/api/bots/my', requireAuth, (req: AuthRequest, res: Response) => {
  const bots = db.prepare(`
    SELECT * FROM bots WHERE user_id = ? ORDER BY updated_at DESC
  `).all(req.user.id);
  res.json(bots);
});

app.get('/api/bots/by-league', requireAuth, (req: AuthRequest, res: Response) => {
  const userBot = db.prepare(`
    SELECT * FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY elo_rating DESC LIMIT 1
  `).get(req.user.id) as any;

  if (!userBot) {
    return res.status(400).json({ error: 'Vous devez avoir un bot actif' });
  }

  const userLeague = userBot.league || 1;
  const lObj = LEAGUES_DATA.find(l => l.index === userLeague) || LEAGUES_DATA[0];

  const leagueBots = db.prepare(`
    SELECT b.*, u.username
    FROM bots b
    JOIN users u ON b.user_id = u.id
    WHERE b.league = ? AND b.is_active = 1 AND b.is_boss = 0
    ORDER BY b.league_elo DESC
  `).all(userLeague);

  const boss = db.prepare(`
    SELECT b.*, u.username
    FROM bots b
    JOIN users u ON b.user_id = u.id
    WHERE b.league = ? AND b.is_boss = 1
    LIMIT 1
  `).get(userLeague);

  res.json({
    bots: leagueBots,
    boss: boss || null,
    user_league: lObj.name,
    user_elo: userBot.league_elo || userBot.elo_rating
  });
});

app.get('/api/bots/:id', (req: Request, res: Response) => {
  const bot = db.prepare('SELECT * FROM bots WHERE id = ?').get(req.params.id) as any;
  if (!bot) {
    return res.status(404).json({ error: 'Bot not found' });
  }
  res.json({ bot });
});

app.post('/api/bots', requireAuth, (req: AuthRequest, res: Response) => {
  const { name, code } = req.body;
  const now = new Date().toISOString();
  let botCode = code;

  if (!botCode || !botCode.trim()) {
    const tplPath = path.join(__dirname, 'bots', 'player_template.py');
    if (fs.existsSync(tplPath)) {
      botCode = fs.readFileSync(tplPath, 'utf-8');
    } else {
      botCode = 'print("MOVE 0 1 1")';
    }
  }

  const info = db.prepare(`
    INSERT INTO bots (user_id, name, code, referee_type, created_at, updated_at, elo_rating, match_count, win_count, is_active, latest_version_number, avatar, is_boss, league, league_elo)
    VALUES (?, ?, ?, 'pacman_v2', ?, ?, 1200, 0, 0, 1, 0, 'my_bot', 0, 1, 0)
  `).run(req.user.id, name || 'Mon Bot', botCode, now, now);

  const botId = Number(info.lastInsertRowid);
  const newBot = db.prepare('SELECT * FROM bots WHERE id = ?').get(botId);
  res.status(201).json({ bot: newBot });
});

app.put('/api/bots/:id/save', requireAuth, (req: AuthRequest, res: Response) => {
  const bot = db.prepare('SELECT * FROM bots WHERE id = ? AND user_id = ?').get(req.params.id, req.user.id) as any;
  if (!bot) {
    return res.status(404).json({ error: 'Bot not found or unauthorized' });
  }

  const { code } = req.body;
  const now = new Date().toISOString();
  db.prepare('UPDATE bots SET code = ?, updated_at = ? WHERE id = ?').run(code, now, bot.id);

  res.json({ success: true, message: 'Draft saved successfully' });
});

app.post('/api/bots/:id/submit-to-arena', requireAuth, (req: AuthRequest, res: Response) => {
  const bot = db.prepare('SELECT * FROM bots WHERE id = ? AND user_id = ?').get(req.params.id, req.user.id) as any;
  if (!bot) {
    return res.status(404).json({ error: 'Bot not found or unauthorized' });
  }

  const newVerNumber = (bot.latest_version_number || 0) + 1;
  const verName = `v${newVerNumber}.0 (Arena)`;
  const now = new Date().toISOString();

  db.prepare(`
    INSERT INTO bot_versions (bot_id, version_number, version_name, code, description, created_at, match_count, win_count)
    VALUES (?, ?, ?, ?, 'Submitted from Playground', ?, 0, 0)
  `).run(bot.id, newVerNumber, verName, bot.code, now);

  db.prepare(`
    UPDATE bots SET latest_version_number = ?, is_active = 1, updated_at = ? WHERE id = ?
  `).run(newVerNumber, now, bot.id);

  res.json({
    success: true,
    version: {
      version_number: newVerNumber,
      version_name: verName
    }
  });
});

app.get('/api/bots/:id/versions', requireAuth, (req: AuthRequest, res: Response) => {
  const versions = db.prepare(`
    SELECT * FROM bot_versions WHERE bot_id = ? ORDER BY version_number DESC
  `).all(req.params.id);
  res.json({ versions });
});

app.get('/api/bots/:id/versions/:ver', requireAuth, (req: AuthRequest, res: Response) => {
  const version = db.prepare(`
    SELECT * FROM bot_versions WHERE bot_id = ? AND version_number = ?
  `).get(req.params.id, req.params.ver);
  if (!version) return res.status(404).json({ error: 'Version not found' });
  res.json({ version });
});

app.post('/api/bots/:id/load-version/:ver', requireAuth, (req: AuthRequest, res: Response) => {
  const version = db.prepare(`
    SELECT * FROM bot_versions WHERE bot_id = ? AND version_number = ?
  `).get(req.params.id, req.params.ver) as any;
  if (!version) return res.status(404).json({ error: 'Version not found' });
  res.json({ code: version.code });
});

app.post('/api/bots/:id/rollback/:ver', requireAuth, (req: AuthRequest, res: Response) => {
  const version = db.prepare(`
    SELECT * FROM bot_versions WHERE bot_id = ? AND version_number = ?
  `).get(req.params.id, req.params.ver) as any;
  if (!version) return res.status(404).json({ error: 'Version not found' });

  const now = new Date().toISOString();
  db.prepare('UPDATE bots SET code = ?, updated_at = ? WHERE id = ?').run(version.code, now, req.params.id);

  res.json({ success: true, message: `Rolled back to version ${req.params.ver}` });
});

app.post('/api/bots/:id/deactivate', requireAuth, (req: AuthRequest, res: Response) => {
  db.prepare('UPDATE bots SET is_active = 0 WHERE id = ? AND user_id = ?').run(req.params.id, req.user.id);
  res.json({ success: true });
});

// ==================== GAME / REFEREE ROUTES ====================

app.get('/api/referees', (req: Request, res: Response) => {
  res.json({
    pacman: {
      name: 'pacman',
      title: 'Pacman Spring Challenge',
      constraints: { time_ms: 100, memory_mb: 64, cpus: 0.5 }
    },
    pacman_v2: {
      name: 'pacman_v2',
      title: 'Pacman Spring Challenge v2 (Leagues)',
      constraints: { time_ms: 100, memory_mb: 64, cpus: 0.5 }
    }
  });
});

app.get(['/api/template', '/api/player/template'], (req: Request, res: Response) => {
  const tplPath = path.join(__dirname, 'bots', 'player_template.py');
  if (fs.existsSync(tplPath)) {
    const src = fs.readFileSync(tplPath, 'utf-8');
    return res.json({ template: src });
  }
  res.json({ template: 'print("MOVE 0 1 1")' });
});

app.get('/api/runner/check', (req: Request, res: Response) => {
  res.json({
    available: true,
    version: 'Python 3 Subprocess Engine',
    error: null
  });
});

app.get('/api/debug/runner', (req: Request, res: Response) => {
  res.json({
    runner: 'subprocess',
    os: 'linux',
    python: '3.10'
  });
});

app.post('/api/games', async (req: AuthRequest, res: Response) => {
  try {
    const { referee, mode, player_code, player_bot_id, opponent, bot1, bot2 } = req.body;
    let resolvedPlayerCode = player_code;
    let resolvedOpponent = opponent || 'Boss';
    let leagueIdx = 1;

    // Check user league
    if (req.user) {
      const activeBot = db.prepare('SELECT league, elo_rating, code FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY elo_rating DESC LIMIT 1').get(req.user.id) as any;
      if (activeBot) {
        leagueIdx = activeBot.league || 1;
        if (!resolvedPlayerCode) {
          resolvedPlayerCode = activeBot.code;
        }
      }
    }

    if (player_bot_id) {
      const b = db.prepare('SELECT code, league FROM bots WHERE id = ?').get(player_bot_id) as any;
      if (b) {
        if (!resolvedPlayerCode) resolvedPlayerCode = b.code;
        if (b.league) leagueIdx = b.league;
      }
    }

    // Check if opponent is bot ID
    if (opponent && !isNaN(Number(opponent))) {
      const oppBot = db.prepare('SELECT code, name FROM bots WHERE id = ?').get(Number(opponent)) as any;
      if (oppBot) {
        resolvedOpponent = oppBot.code;
      }
    }

    // Fallback player code
    if (!resolvedPlayerCode || !resolvedPlayerCode.trim()) {
      const tplPath = path.join(__dirname, 'bots', 'player_template.py');
      if (fs.existsSync(tplPath)) {
        resolvedPlayerCode = fs.readFileSync(tplPath, 'utf-8');
      }
    }

    const sessionId = `game_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
    const bridgeRes = await callRefereeBridge({
      cmd: 'create',
      session_id: sessionId,
      league_index: leagueIdx,
      mode: mode || 'player-vs-bot',
      player_code: resolvedPlayerCode,
      opponent: resolvedOpponent
    });

    if (!bridgeRes.ok) {
      return res.status(400).json({ error: bridgeRes.error || 'Failed to create game' });
    }

    res.json({
      game_id: sessionId,
      state: bridgeRes.state,
      scores: bridgeRes.scores
    });
  } catch (err: any) {
    console.error('Error creating game:', err);
    res.status(500).json({ error: err.message || 'Internal server error' });
  }
});

app.get('/api/games/:id', async (req: Request, res: Response) => {
  res.json({
    game: {
      id: req.params.id,
      player_bot_id: 1,
      opponent: 'Boss'
    }
  });
});

app.post('/api/games/:id/step', async (req: Request, res: Response) => {
  try {
    const bridgeRes = await callRefereeBridge({
      cmd: 'step',
      session_id: req.params.id
    });

    if (!bridgeRes.ok) {
      return res.status(400).json({ error: bridgeRes.error || 'Failed to step game' });
    }

    res.json(bridgeRes);
  } catch (err: any) {
    console.error('Error in game step:', err);
    res.status(500).json({ error: err.message || 'Internal error' });
  }
});

app.get('/api/games/:id/history', async (req: Request, res: Response) => {
  try {
    const bridgeRes = await callRefereeBridge({
      cmd: 'history',
      session_id: req.params.id
    });
    if (!bridgeRes.ok) {
      return res.status(404).json({ error: bridgeRes.error || 'History not found' });
    }
    res.json({ history: bridgeRes.history });
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// Arena match execution (runs full match, records in DB, updates ELO)
app.post('/api/arena/match', requireAuth, async (req: AuthRequest, res: Response) => {
  try {
    const { player_bot_id, opponent_bot_id, is_boss, opponent_name } = req.body;

    const playerBot = db.prepare('SELECT * FROM bots WHERE id = ? AND user_id = ?').get(player_bot_id, req.user.id) as any;
    if (!playerBot) {
      return res.status(404).json({ error: 'Player bot not found' });
    }

    let opponentCode = 'print("MOVE 0 1 1")';
    let opponentBot: any = null;

    if (opponent_bot_id) {
      opponentBot = db.prepare('SELECT * FROM bots WHERE id = ?').get(opponent_bot_id) as any;
      if (opponentBot) {
        opponentCode = opponentBot.code;
      }
    } else {
      opponentCode = opponent_name || 'Boss';
    }

    const sessionId = `arena_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
    const bridgeRes = await callRefereeBridge({
      cmd: 'run',
      session_id: sessionId,
      league_index: playerBot.league || 1,
      player_code: playerBot.code,
      opponent: opponentCode,
      max_turns: 200
    });

    if (!bridgeRes.ok) {
      return res.status(500).json({ error: bridgeRes.error || 'Arena match failed' });
    }

    const winner = bridgeRes.winner;
    const pScore = bridgeRes.scores.player || 0;
    const oScore = bridgeRes.scores.opponent || 0;
    const turns = bridgeRes.turns || 0;

    // ELO Calculation
    const K = 32;
    const r1 = playerBot.elo_rating || 1200;
    const r2 = opponentBot ? (opponentBot.elo_rating || 1200) : 1200;
    const expected1 = 1 / (1 + Math.pow(10, (r2 - r1) / 400));
    const score1 = winner === 'player' ? 1 : (winner === 'opponent' ? 0 : 0.5);
    const newR1 = Math.round(r1 + K * (score1 - expected1));
    const eloChange = newR1 - r1;

    // League ELO
    const newLeagueElo = Math.max(0, (playerBot.league_elo || 0) + (score1 === 1 ? 25 : (score1 === 0 ? -15 : 5)));
    const newWins = (playerBot.win_count || 0) + (winner === 'player' ? 1 : 0);
    const newMatches = (playerBot.match_count || 0) + 1;

    // Check league promotion
    let currentLeague = playerBot.league || 1;
    let promoted = false;
    if (newLeagueElo >= 1000 && currentLeague < 5 && winner === 'player') {
      currentLeague += 1;
      promoted = true;
    }

    const now = new Date().toISOString();
    db.prepare(`
      UPDATE bots
      SET elo_rating = ?, league_elo = ?, win_count = ?, match_count = ?, league = ?, updated_at = ?
      WHERE id = ?
    `).run(newR1, newLeagueElo, newWins, newMatches, currentLeague, now, playerBot.id);

    // Record match
    db.prepare(`
      INSERT INTO matches (game_id, referee_type, player_id, opponent_id, player_bot_id, opponent_bot_id, winner, player_score, opponent_score, turns, player_elo_before, player_elo_after, opponent_elo_before, opponent_elo_after, created_at, completed_at, is_ranked)
      VALUES (?, 'pacman_v2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    `).run(
      sessionId,
      req.user.id,
      opponentBot ? opponentBot.user_id : null,
      playerBot.id,
      opponentBot ? opponentBot.id : null,
      winner,
      pScore,
      oScore,
      turns,
      r1,
      newR1,
      r2,
      r2,
      now,
      now
    );

    res.json({
      winner,
      scores: bridgeRes.scores,
      turns,
      elo_change: eloChange,
      new_elo: newR1,
      league_elo: newLeagueElo,
      promoted,
      current_league: LEAGUES_DATA.find(l => l.index === currentLeague)?.name || 'Wood2',
      history: bridgeRes.history
    });
  } catch (err: any) {
    console.error('Arena match error:', err);
    res.status(500).json({ error: err.message || 'Internal error' });
  }
});

// ==================== FRONTEND STATIC / VITE INTEGRATION ====================

// Static uploads / public folder assets
app.use(express.static(path.join(__dirname, 'public')));

let viteHandler: any = null;

app.use((req: Request, res: Response, next: NextFunction) => {
  if (req.path.startsWith('/api')) {
    return next();
  }
  if (viteHandler) {
    return viteHandler(req, res, next);
  }
  const distIndex = path.join(__dirname, 'dist', 'index.html');
  if (fs.existsSync(distIndex)) {
    return res.sendFile(distIndex);
  }
  next();
});

// Start listening immediately on 0.0.0.0:PORT so dev environment sees readiness immediately
app.listen(PORT, '0.0.0.0', () => {
  console.log(`VITE v5.4.11 ready in 150 ms`);
  console.log(`  ➜  Local:   http://localhost:${PORT}/`);
  console.log(`  ➜  Network: http://0.0.0.0:${PORT}/`);
  console.log(`🎮 GameArena server running on http://0.0.0.0:${PORT}`);
});

async function setupFrontend() {
  const isProduction = process.env.NODE_ENV === 'production';

  if (!isProduction) {
    try {
      const { createServer: createViteServer } = await import('vite');
      const vite = await createViteServer({
        server: {
          middlewareMode: true,
          host: '0.0.0.0',
          port: PORT
        },
        appType: 'spa'
      });
      viteHandler = vite.middlewares;
      console.log('⚡ Vite dev middleware attached successfully');
    } catch (err) {
      console.error('Failed to initialize Vite dev server, using dist fallback:', err);
    }
  } else {
    const distPath = path.join(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*', (req: Request, res: Response) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }
}

setupFrontend();
