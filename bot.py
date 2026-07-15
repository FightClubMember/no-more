#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║                     🔥 TEMP MAIL BOT — ULTIMATE EDITION 🔥                      ║
║                                                                                  ║
║  Features: Temp Email | Credit System | Referral System | Daily Check-in        ║
║  Pass/Key System | Force Join (Admin Manageable) | Admin Panel                  ║
║  Leaderboard | Stats | Broadcast | Ban/Unban | User Info                        ║
║  Advanced UI | Reply Keyboard | Pagination | Streak System                      ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

import logging
import os
import sqlite3
import random
import string
import threading
import time
import urllib.parse
import json
import html
import http.server
import socketserver
import asyncio
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Union
from collections import defaultdict
from functools import wraps

import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Load environment variables from .env file
load_dotenv()

# ================================================================================
# CONFIGURATION & CONSTANTS
# ================================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required!")

ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS environment variable is required! Get your ID from @userinfobot")

# Economy Settings
WELCOME_BONUS = 5
DAILY_BONUS = 2
REFERRAL_BONUS = 3
EMAIL_COST = 1
STREAK_MULTIPLIER_INTERVAL = 7  # Every 7 days streak, multiplier increases
STREAK_MAX_MULTIPLIER = 5       # Max 5x multiplier

# Mail.tm settings
MAIL_TM_BASE_URL = "https://api.mail.tm"

# Render Port Binding
PORT = int(os.environ.get("PORT", "10000"))

# Pagination
MESSAGES_PER_PAGE = 5
REFERRALS_PER_PAGE = 5
LEADERBOARD_LIMIT = 20

# ================================================================================
# DATABASE LAYER
# ================================================================================

class MockCursor:
    """Mock cursor for mimicking sqlite3 behaviors under PostgreSQL."""
    def __init__(self, value):
        self.value = value
    def fetchone(self):
        return (self.value,)
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class PostgresConnectionWrapper:
    """Wrapper around psycopg2 connection to intercept commit and make it a no-op."""
    def __init__(self, conn):
        self._conn = conn
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def commit(self):
        pass


class Database:
    """Complete database layer supporting SQLite and PostgreSQL dynamically, with thread safety."""
    
    def __init__(self):
        self.db_url = os.environ.get("DATABASE_URL", "")
        self.is_postgres = bool(self.db_url)
        self.conn = None
        self.lock = threading.RLock()
        self.last_rowcount = 0
        
        if self.is_postgres:
            self._connect_pg()
        else:
            self._connect_lite()
            
        self._migrate()
        logging.info(f"Database initialized successfully ({'PostgreSQL' if self.is_postgres else 'SQLite'})")
    
    def _connect_pg(self):
        import psycopg2
        import psycopg2.extras
        try:
            if self.conn is None or self.conn.closed:
                pg_conn = psycopg2.connect(self.db_url, cursor_factory=psycopg2.extras.DictCursor)
                pg_conn.autocommit = True
                self.conn = PostgresConnectionWrapper(pg_conn)
        except Exception as e:
            logging.error(f"Error connecting to PostgreSQL: {e}")
            raise e

    def _connect_lite(self):
        self.conn = sqlite3.connect("bot_data.db", check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-16000")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def _execute(self, sql: str, params: tuple = None) -> any:
        with self.lock:
            if self.is_postgres:
                self._connect_pg()
                if sql.strip().upper() == "SELECT CHANGES()":
                    return MockCursor(self.last_rowcount)
                
                sql_pg = sql.replace("?", "%s")
                # PostgreSQL doesn't support INSERT OR IGNORE, use ON CONFLICT DO NOTHING
                sql_pg = sql_pg.replace("INSERT OR IGNORE INTO stats (key, value) VALUES (%s, 0)", 
                                         "INSERT INTO stats (key, value) VALUES (%s, 0) ON CONFLICT (key) DO NOTHING")
                sql_pg = sql_pg.replace("INSERT OR IGNORE", "INSERT")
                
                cur = self.conn.cursor()
                cur.execute(sql_pg, params or ())
                self.last_rowcount = cur.rowcount
                return cur
            else:
                return self.conn.execute(sql, params or ())
    
    def _fetchone(self, sql: str, params: tuple = None) -> Optional[dict]:
        with self.lock:
            if self.is_postgres:
                try:
                    with self._execute(sql, params) as cur:
                        row = cur.fetchone()
                        return dict(row) if row else None
                except Exception as e:
                    logging.error(f"PostgreSQL fetchone error: {e}")
                    return None
            else:
                row = self._execute(sql, params).fetchone()
                return dict(row) if row else None
    
    def _fetchall(self, sql: str, params: tuple = None) -> List[dict]:
        with self.lock:
            if self.is_postgres:
                try:
                    with self._execute(sql, params) as cur:
                        rows = cur.fetchall()
                        return [dict(row) for row in rows] if rows else []
                except Exception as e:
                    logging.error(f"PostgreSQL fetchall error: {e}")
                    return []
            else:
                rows = self._execute(sql, params).fetchall()
                return [dict(row) for row in rows] if rows else []

    def _migrate(self):
        """Create all tables and run migrations."""
        with self.lock:
            if self.is_postgres:
                self._connect_pg()
                schema = """
                    -- Users Table
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT DEFAULT '',
                        first_name TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        credits REAL DEFAULT 0,
                        total_earned REAL DEFAULT 0,
                        referral_code TEXT UNIQUE,
                        referred_by BIGINT DEFAULT NULL,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_checkin TEXT DEFAULT NULL,
                        is_banned INTEGER DEFAULT 0,
                        total_emails INTEGER DEFAULT 0,
                        language TEXT DEFAULT 'en'
                    );
                    
                    -- Referral Log
                    CREATE TABLE IF NOT EXISTS referral_log (
                        id SERIAL PRIMARY KEY,
                        referrer_id BIGINT NOT NULL,
                        referred_id BIGINT NOT NULL,
                        bonus REAL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    
                    -- Pass/Key System
                    CREATE TABLE IF NOT EXISTS passes (
                        id SERIAL PRIMARY KEY,
                        code TEXT UNIQUE NOT NULL,
                        credits REAL DEFAULT 0,
                        uses_left INTEGER DEFAULT 1,
                        max_uses INTEGER DEFAULT 1,
                        created_by BIGINT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP DEFAULT NULL
                    );
                    
                    -- Used Passes Tracking
                    CREATE TABLE IF NOT EXISTS used_passes (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        pass_code TEXT NOT NULL,
                        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    
                    -- Daily Check-in
                    CREATE TABLE IF NOT EXISTS daily_checkin (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        checkin_date TEXT NOT NULL,
                        bonus REAL DEFAULT 0,
                        UNIQUE(user_id, checkin_date)
                    );
                    
                    -- Force Join Channels (Admin Manageable)
                    CREATE TABLE IF NOT EXISTS force_channels (
                        id SERIAL PRIMARY KEY,
                        channel_id TEXT UNIQUE NOT NULL,
                        channel_name TEXT DEFAULT '',
                        added_by BIGINT DEFAULT 0,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active INTEGER DEFAULT 1
                    );
                    
                    -- Bot Statistics
                    CREATE TABLE IF NOT EXISTS stats (
                        key TEXT PRIMARY KEY,
                        value INTEGER DEFAULT 0
                    );
                    
                    -- Seen Messages Tracker
                    CREATE TABLE IF NOT EXISTS seen_messages (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        message_id TEXT NOT NULL,
                        email TEXT NOT NULL,
                        seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, message_id)
                    );
                    
                    -- Admin Logs
                    CREATE TABLE IF NOT EXISTS admin_logs (
                        id SERIAL PRIMARY KEY,
                        admin_id BIGINT NOT NULL,
                        action TEXT NOT NULL,
                        target TEXT DEFAULT '',
                        details TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    
                    -- Broadcast History
                    CREATE TABLE IF NOT EXISTS broadcast_history (
                        id SERIAL PRIMARY KEY,
                        admin_id BIGINT NOT NULL,
                        message TEXT NOT NULL,
                        sent_count INTEGER DEFAULT 0,
                        failed_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """
                with self.conn.cursor() as cur:
                    cur.execute(schema)
                
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_referral_referrer ON referral_log(referrer_id)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_referred ON referral_log(referred_id)",
                    "CREATE INDEX IF NOT EXISTS idx_daily_user_date ON daily_checkin(user_id, checkin_date)",
                    "CREATE INDEX IF NOT EXISTS idx_seen_user ON seen_messages(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_used_passes_user ON used_passes(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id)",
                ]
                with self.conn.cursor() as cur:
                    for idx in indexes:
                        cur.execute(idx)
                
                default_stats = [
                    'total_users', 'total_emails', 'total_checkins', 'total_referrals',
                    'total_passes_created', 'total_pass_redemptions', 'total_broadcasts',
                    'total_bans', 'total_unbans'
                ]
                with self.conn.cursor() as cur:
                    for key in default_stats:
                        cur.execute("INSERT INTO stats (key, value) VALUES (%s, 0) ON CONFLICT (key) DO NOTHING", (key,))
            else:
                self.conn.executescript("""
                    -- Users Table
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT DEFAULT '',
                        first_name TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        credits REAL DEFAULT 0,
                        total_earned REAL DEFAULT 0,
                        referral_code TEXT UNIQUE,
                        referred_by INTEGER DEFAULT NULL,
                        joined_at TEXT DEFAULT (datetime('now')),
                        last_checkin TEXT DEFAULT NULL,
                        is_banned INTEGER DEFAULT 0,
                        total_emails INTEGER DEFAULT 0,
                        language TEXT DEFAULT 'en'
                    );
                    
                    -- Referral Log
                    CREATE TABLE IF NOT EXISTS referral_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        referrer_id INTEGER NOT NULL,
                        referred_id INTEGER NOT NULL,
                        bonus REAL DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now'))
                    );
                    
                    -- Pass/Key System
                    CREATE TABLE IF NOT EXISTS passes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        code TEXT UNIQUE NOT NULL,
                        credits REAL DEFAULT 0,
                        uses_left INTEGER DEFAULT 1,
                        max_uses INTEGER DEFAULT 1,
                        created_by INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now')),
                        expires_at TEXT DEFAULT NULL
                    );
                    
                    -- Used Passes Tracking
                    CREATE TABLE IF NOT EXISTS used_passes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        pass_code TEXT NOT NULL,
                        used_at TEXT DEFAULT (datetime('now'))
                    );
                    
                    -- Daily Check-in
                    CREATE TABLE IF NOT EXISTS daily_checkin (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        checkin_date TEXT NOT NULL,
                        bonus REAL DEFAULT 0,
                        UNIQUE(user_id, checkin_date)
                    );
                    
                    -- Force Join Channels (Admin Manageable)
                    CREATE TABLE IF NOT EXISTS force_channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id TEXT UNIQUE NOT NULL,
                        channel_name TEXT DEFAULT '',
                        added_by INTEGER DEFAULT 0,
                        added_at TEXT DEFAULT (datetime('now')),
                        is_active INTEGER DEFAULT 1
                    );
                    
                    -- Bot Statistics
                    CREATE TABLE IF NOT EXISTS stats (
                        key TEXT PRIMARY KEY,
                        value INTEGER DEFAULT 0
                    );
                    
                    -- Seen Messages Tracker
                    CREATE TABLE IF NOT EXISTS seen_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        message_id TEXT NOT NULL,
                        email TEXT NOT NULL,
                        seen_at TEXT DEFAULT (datetime('now')),
                        UNIQUE(user_id, message_id)
                    );
                    
                    -- Admin Logs
                    CREATE TABLE IF NOT EXISTS admin_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        admin_id INTEGER NOT NULL,
                        action TEXT NOT NULL,
                        target TEXT DEFAULT '',
                        details TEXT DEFAULT '',
                        created_at TEXT DEFAULT (datetime('now'))
                    );
                    
                    -- Broadcast History
                    CREATE TABLE IF NOT EXISTS broadcast_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        admin_id INTEGER NOT NULL,
                        message TEXT NOT NULL,
                        sent_count INTEGER DEFAULT 0,
                        failed_count INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now'))
                    );
                """)
                
                indexes = [
                    "CREATE INDEX IF NOT EXISTS idx_referral_referrer ON referral_log(referrer_id)",
                    "CREATE INDEX IF NOT EXISTS idx_referral_referred ON referral_log(referred_id)",
                    "CREATE INDEX IF NOT EXISTS idx_daily_user_date ON daily_checkin(user_id, checkin_date)",
                    "CREATE INDEX IF NOT EXISTS idx_seen_user ON seen_messages(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_used_passes_user ON used_passes(user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id)",
                ]
                for idx in indexes:
                    self.conn.execute(idx)
                
                default_stats = [
                    'total_users', 'total_emails', 'total_checkins', 'total_referrals',
                    'total_passes_created', 'total_pass_redemptions', 'total_broadcasts',
                    'total_bans', 'total_unbans'
                ]
                for key in default_stats:
                    self.conn.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)", (key,))
                
                self.conn.commit()
    
    # ==========================================================================
    # USER MANAGEMENT
    # ==========================================================================
    
    def register_user(self, user_id: int, username: str, first_name: str, referred_by: Optional[int] = None) -> Tuple[bool, str, bool]:
        """
        Register or update a user.
        Returns: (is_new_user, referral_code, received_welcome_bonus)
        """
        existing = self._fetchone("SELECT user_id, referral_code FROM users WHERE user_id = ?", (user_id,))
        
        if existing:
            # Update existing user info
            self._execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username or '', first_name or '', user_id)
            )
            self.conn.commit()
            return False, existing['referral_code'], False
        
        # Generate unique referral code
        code = self._generate_unique_code()
        
        # Insert new user with welcome bonus
        self._execute(
            "INSERT INTO users (user_id, username, first_name, credits, total_earned, referral_code, referred_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username or '', first_name or '', WELCOME_BONUS, WELCOME_BONUS, code, referred_by)
        )
        
        # Process referral bonus for referrer
        if referred_by:
            ref_user = self._fetchone("SELECT user_id FROM users WHERE user_id = ? AND is_banned = 0", (referred_by,))
            if ref_user and ref_user['user_id'] != user_id:
                self._execute(
                    "UPDATE users SET credits = credits + ?, total_earned = total_earned + ? WHERE user_id = ?",
                    (REFERRAL_BONUS, REFERRAL_BONUS, referred_by)
                )
                self._execute(
                    "INSERT INTO referral_log (referrer_id, referred_id, bonus) VALUES (?, ?, ?)",
                    (referred_by, user_id, REFERRAL_BONUS)
                )
                self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_referrals'")
        
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_users'")
        self.conn.commit()
        return True, code, True
    
    def _generate_unique_code(self) -> str:
        """Generate a unique referral code."""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not self._fetchone("SELECT 1 FROM users WHERE referral_code = ?", (code,)):
                return code
    
    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        """Get user by ID."""
        return self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    def ban_user(self, user_id: int, admin_id: int) -> bool:
        """Ban a user. Returns True if successful."""
        user = self._fetchone("SELECT user_id FROM users WHERE user_id = ? AND is_banned = 0", (user_id,))
        if not user:
            return False
        self._execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_bans'")
        self._log_admin(admin_id, 'ban', str(user_id))
        self.conn.commit()
        return True
    
    def unban_user(self, user_id: int, admin_id: int) -> bool:
        """Unban a user. Returns True if successful."""
        user = self._fetchone("SELECT user_id FROM users WHERE user_id = ? AND is_banned = 1", (user_id,))
        if not user:
            return False
        self._execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_unbans'")
        self._log_admin(admin_id, 'unban', str(user_id))
        self.conn.commit()
        return True
    
    def get_credits(self, user_id: int) -> float:
        """Get user credits."""
        row = self._fetchone("SELECT credits FROM users WHERE user_id = ?", (user_id,))
        return row['credits'] if row else 0.0
    
    def deduct_credits(self, user_id: int, amount: float) -> bool:
        """Deduct credits. Returns True if successful."""
        user = self._fetchone("SELECT credits FROM users WHERE user_id = ? AND is_banned = 0", (user_id,))
        if not user or user['credits'] < amount:
            return False
        self._execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (amount, user_id))
        self.conn.commit()
        return True
    
    def get_all_user_ids(self) -> List[int]:
        """Get all non-banned user IDs."""
        rows = self._fetchall("SELECT user_id FROM users WHERE is_banned = 0")
        return [row['user_id'] for row in rows]
    
    # ==========================================================================
    # REFERRAL SYSTEM
    # ==========================================================================
    
    def get_referral_stats(self, user_id: int) -> dict:
        """Get referral stats for a user."""
        count = self._fetchone(
            "SELECT COUNT(*) as cnt FROM referral_log WHERE referrer_id = ?", (user_id,)
        )
        total_bonus = self._fetchone(
            "SELECT COALESCE(SUM(bonus), 0) as total FROM referral_log WHERE referrer_id = ?", (user_id,)
        )
        return {'count': count['cnt'] if count else 0, 'total_bonus': total_bonus['total'] if total_bonus else 0.0}
    
    def get_referrals(self, user_id: int, page: int = 0, per_page: int = REFERRALS_PER_PAGE) -> Tuple[List[sqlite3.Row], int]:
        """Get paginated referrals for a user."""
        offset = page * per_page
        rows = self._fetchall(
            "SELECT rl.*, u.username, u.first_name, u.joined_at FROM referral_log rl "
            "JOIN users u ON rl.referred_id = u.user_id "
            "WHERE rl.referrer_id = ? ORDER BY rl.created_at DESC LIMIT ? OFFSET ?",
            (user_id, per_page, offset)
        )
        total = self._fetchone(
            "SELECT COUNT(*) as cnt FROM referral_log WHERE referrer_id = ?", (user_id,)
        )['cnt']
        return rows, total
    
    # ==========================================================================
    # DAILY CHECK-IN SYSTEM
    # ==========================================================================
    
    def can_checkin(self, user_id: int) -> bool:
        """Check if user can check in today."""
        today = datetime.now().strftime("%Y-%m-%d")
        row = self._fetchone(
            "SELECT 1 FROM daily_checkin WHERE user_id = ? AND checkin_date = ?", (user_id, today)
        )
        return row is None
    
    def do_checkin(self, user_id: int) -> dict:
        """
        Perform daily check-in.
        Returns dict with bonus, streak, multiplier info.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Check if user checked in yesterday (for streak continuity)
        yesterday_checkin = self._fetchone(
            "SELECT 1 FROM daily_checkin WHERE user_id = ? AND checkin_date = ?", (user_id, yesterday)
        )
        
        # Get current streak info
        streak_info = self.get_streak_info(user_id)
        current_streak = streak_info['streak']
        
        # If user didn't check in yesterday, reset streak
        if not yesterday_checkin:
            current_streak = 0
        
        new_streak = current_streak + 1
        
        # Calculate bonus with streak multiplier
        multiplier = 1 + (new_streak // STREAK_MULTIPLIER_INTERVAL)
        if multiplier > STREAK_MAX_MULTIPLIER:
            multiplier = STREAK_MAX_MULTIPLIER
        
        bonus = DAILY_BONUS * multiplier
        
        # Record check-in
        self._execute(
            "INSERT INTO daily_checkin (user_id, checkin_date, bonus) VALUES (?, ?, ?)",
            (user_id, today, bonus)
        )
        self._execute(
            "UPDATE users SET credits = credits + ?, total_earned = total_earned + ?, "
            "last_checkin = ? WHERE user_id = ?",
            (bonus, bonus, today, user_id)
        )
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_checkins'")
        self.conn.commit()
        
        return {
            'bonus': bonus,
            'streak': new_streak,
            'multiplier': multiplier,
            'multiplier_active': multiplier > 1
        }
    
    def get_streak_info(self, user_id: int) -> dict:
        """Get streak information for a user."""
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Check if checked in today
        checked_today = self._fetchone(
            "SELECT 1 FROM daily_checkin WHERE user_id = ? AND checkin_date = ?", (user_id, today)
        )
        
        if not checked_today:
            checked_yesterday = self._fetchone(
                "SELECT 1 FROM daily_checkin WHERE user_id = ? AND checkin_date = ?", (user_id, yesterday)
            )
            if not checked_yesterday:
                return {'streak': 0, 'can_checkin': True}
        
        # Count consecutive check-ins going backward
        streak = 0
        check_date = datetime.now()
        while True:
            date_str = check_date.strftime("%Y-%m-%d")
            row = self._fetchone(
                "SELECT 1 FROM daily_checkin WHERE user_id = ? AND checkin_date = ?", (user_id, date_str)
            )
            if row:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break
        
        can_checkin = checked_today is None
        return {'streak': streak, 'can_checkin': can_checkin}
    
    # ==========================================================================
    # EMAIL MANAGEMENT
    # ==========================================================================
    
    def set_email(self, user_id: int, email: str) -> None:
        """Set or update user's email."""
        self._execute("UPDATE users SET email = ? WHERE user_id = ?", (email, user_id))
        self._execute("UPDATE users SET total_emails = total_emails + 1 WHERE user_id = ?", (user_id,))
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_emails'")
        self.conn.commit()
    
    def mark_message_seen(self, user_id: int, message_id: str, email: str) -> bool:
        """Mark a message as seen. Returns False if already seen."""
        try:
            self._execute(
                "INSERT INTO seen_messages (user_id, message_id, email) VALUES (?, ?, ?)",
                (user_id, message_id, email)
            )
            self.conn.commit()
            return True
        except Exception:
            return False
    
    def is_message_seen(self, user_id: int, message_id: str) -> bool:
        """Check if a message has been seen."""
        row = self._fetchone(
            "SELECT 1 FROM seen_messages WHERE user_id = ? AND message_id = ?", (user_id, message_id)
        )
        return row is not None
    
    # ==========================================================================
    # PASS/KEY SYSTEM
    # ==========================================================================
    
    def create_pass(self, code: str, credits: float, max_uses: int, created_by: int, expires_days: int = 0) -> bool:
        """Create a pass code. Returns True if successful."""
        expires_at = None
        if expires_days > 0:
            expires_at = (datetime.now() + timedelta(days=expires_days)).strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            self._execute(
                "INSERT INTO passes (code, credits, uses_left, max_uses, created_by, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (code, credits, max_uses, max_uses, created_by, expires_at)
            )
            self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_passes_created'")
            self._log_admin(created_by, 'create_pass', code)
            self.conn.commit()
            return True
        except Exception:
            return False
    
    def redeem_pass(self, code: str, user_id: int) -> Tuple[bool, str]:
        """
        Redeem a pass code.
        Returns (success, message).
        """
        code = code.upper()
        pass_info = self._fetchone("SELECT * FROM passes WHERE code = ?", (code,))
        
        if not pass_info:
            return False, "Pass code not found."
        
        if pass_info['uses_left'] <= 0:
            return False, "This pass has been fully redeemed."
        
        # Check expiry
        if pass_info['expires_at']:
            if isinstance(pass_info['expires_at'], datetime):
                expires = pass_info['expires_at']
            else:
                expires = datetime.strptime(str(pass_info['expires_at']), "%Y-%m-%d %H:%M:%S")
            if expires < datetime.now():
                return False, "This pass has expired."
        
        # Check if user already used this pass
        already_used = self._fetchone(
            "SELECT 1 FROM used_passes WHERE user_id = ? AND pass_code = ?", (user_id, code)
        )
        if already_used:
            return False, "You have already redeemed this pass."
        
        # Process redemption
        self._execute(
            "UPDATE passes SET uses_left = uses_left - 1 WHERE code = ?", (code,)
        )
        self._execute(
            "UPDATE users SET credits = credits + ?, total_earned = total_earned + ? WHERE user_id = ?",
            (pass_info['credits'], pass_info['credits'], user_id)
        )
        self._execute(
            "INSERT INTO used_passes (user_id, pass_code) VALUES (?, ?)", (user_id, code)
        )
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_pass_redemptions'")
        self.conn.commit()
        
        return True, f"Redeemed `{pass_info['credits']}` credits from pass `{code}`!"
    
    def list_passes(self) -> List[sqlite3.Row]:
        """List all passes."""
        return self._fetchall("SELECT * FROM passes ORDER BY created_at DESC")
    
    def delete_pass(self, code: str) -> bool:
        """Delete a pass."""
        code = code.upper()
        self._execute("DELETE FROM passes WHERE code = ?", (code,))
        self._execute("DELETE FROM used_passes WHERE pass_code = ?", (code,))
        self.conn.commit()
        return True
    
    def get_pass_info(self, code: str) -> Optional[sqlite3.Row]:
        """Get pass information."""
        return self._fetchone("SELECT * FROM passes WHERE code = ?", (code.upper(),))
    
    # ==========================================================================
    # FORCE JOIN CHANNEL MANAGEMENT
    # ==========================================================================
    
    def add_force_channel(self, channel_id: str, channel_name: str = '', admin_id: int = 0) -> Tuple[bool, str]:
        """Add a force join channel."""
        try:
            self._execute(
                "INSERT INTO force_channels (channel_id, channel_name, added_by) VALUES (?, ?, ?)",
                (channel_id, channel_name, admin_id)
            )
            self._log_admin(admin_id, 'force_join_add', channel_id)
            self.conn.commit()
            return True, f"Channel `{channel_id}` added to force join list."
        except Exception:
            return False, f"Channel `{channel_id}` already exists in force join list."
    
    def remove_force_channel(self, channel_id: str, admin_id: int = 0) -> Tuple[bool, str]:
        """Remove a force join channel."""
        self._execute(
            "DELETE FROM force_channels WHERE channel_id = ?", (channel_id,)
        )
        if self._execute("SELECT changes()").fetchone()[0] > 0:
            self._log_admin(admin_id, 'force_join_remove', channel_id)
            self.conn.commit()
            return True, f"Channel `{channel_id}` removed from force join list."
        return False, f"Channel `{channel_id}` not found in force join list."
    
    def list_force_channels(self) -> List[sqlite3.Row]:
        """List all force join channels."""
        return self._fetchall("SELECT * FROM force_channels ORDER BY added_at DESC")
    
    def get_force_channel_ids(self) -> List[str]:
        """Get active force channel IDs."""
        rows = self._fetchall("SELECT channel_id FROM force_channels WHERE is_active = 1")
        return [row['channel_id'] for row in rows]
    
    # ==========================================================================
    # STATISTICS
    # ==========================================================================
    
    def get_stats(self) -> dict:
        """Get comprehensive bot statistics."""
        result = {}
        rows = self._fetchall("SELECT key, value FROM stats")
        for row in rows:
            result[row['key']] = row['value']
        
        # Compute additional stats
        result['total_users'] = self._fetchone("SELECT COUNT(*) as c FROM users")['c']
        
        # Active today
        today = datetime.now().strftime("%Y-%m-%d")
        result['active_today'] = self._fetchone(
            "SELECT COUNT(DISTINCT user_id) as c FROM daily_checkin WHERE checkin_date = ?", (today,)
        )['c']
        
        result['total_passes'] = self._fetchone("SELECT COUNT(*) as c FROM passes")['c']
        result['total_force_channels'] = self._fetchone("SELECT COUNT(*) as c FROM force_channels")['c']
        
        return result
    
    def increment_stat(self, key: str) -> None:
        """Increment a stat counter."""
        self._execute("UPDATE stats SET value = value + 1 WHERE key = ?", (key,))
        self.conn.commit()
    
    # ==========================================================================
    # ADMIN LOGS
    # ==========================================================================
    
    def _log_admin(self, admin_id: int, action: str, target: str = '', details: str = '') -> None:
        """Log an admin action."""
        self._execute(
            "INSERT INTO admin_logs (admin_id, action, target, details) VALUES (?, ?, ?, ?)",
            (admin_id, action, target, details)
        )
        self.conn.commit()
    
    def get_admin_logs(self, limit: int = 30) -> List[sqlite3.Row]:
        """Get recent admin logs."""
        rows = self._fetchall(
            "SELECT al.*, u.username as admin_name FROM admin_logs al "
            "LEFT JOIN users u ON al.admin_id = u.user_id "
            "ORDER BY al.created_at DESC LIMIT ?", (limit,)
        )
        return rows
    
    def log_broadcast(self, admin_id: int, message: str, sent_count: int, failed_count: int) -> None:
        """Log a broadcast action."""
        self._execute(
            "INSERT INTO broadcast_history (admin_id, message, sent_count, failed_count) VALUES (?, ?, ?, ?)",
            (admin_id, message, sent_count, failed_count)
        )
        self._execute("UPDATE stats SET value = value + 1 WHERE key = 'total_broadcasts'")
        self._log_admin(admin_id, 'broadcast', f"Sent:{sent_count} Failed:{failed_count}")
        self.conn.commit()


# ================================================================================
# UI HELPER CLASS
# ================================================================================

class UI:
    """Unified UI helpers for consistent message formatting using HTML."""
    
    @staticmethod
    def box(title: str, body: str) -> str:
        """Create a boxed message with title and body using premium ASCII headers."""
        header = (
            f"<b>╔═════════════════════════════════╗</b>\n"
            f"   ⚡️ <b>{title.upper()}</b>\n"
            f"<b>╚═════════════════════════════════╝</b>"
        )
        return f"{header}\n\n{body}"
    
    @staticmethod
    def back_button(callback_data: str = "noop") -> InlineKeyboardMarkup:
        """Create a back button."""
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back to Menu", callback_data=callback_data)
        ]])
    
    @staticmethod
    def get_reply_keyboard() -> ReplyKeyboardMarkup:
        """Get the persistent reply keyboard with Redeem Key button."""
        keyboard = [
            [KeyboardButton("📥 INBOX"), KeyboardButton("🆕 NEW EMAIL")],
            [KeyboardButton("📅 DAILY CHECK-IN"), KeyboardButton("💰 BALANCE")],
            [KeyboardButton("👥 REFERRALS"), KeyboardButton("🔑 REDEEM KEY")],
            [KeyboardButton("🏆 LEADERBOARD"), KeyboardButton("📊 MY STATS")],
            [KeyboardButton("❓ HELP")],
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ================================================================================
# DECORATORS
# ================================================================================

def admin_only(func):
    """Decorator to restrict commands to admins only."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Access denied. This command is for admins only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def require_registration(func):
    """Decorator to ensure user is registered and not banned."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if not user:
            # Auto-register on first interaction instead of blocking
            referred_by = None
            if context.args and context.args[0].startswith("ref_"):
                ref_code = context.args[0][4:]
                ref_user = db._fetchone("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
                if ref_user:
                    referred_by = ref_user['user_id']
            
            db.register_user(
                user_id,
                update.effective_user.username or '',
                update.effective_user.first_name or '',
                referred_by
            )
            user = db.get_user(user_id)
        
        if user and user['is_banned']:
            await update.message.reply_text("You are banned from using this bot.")
            return
        
        return await func(update, context, *args, **kwargs)
    return wrapper


# ================================================================================
# GLOBAL DATABASE INSTANCE
# ================================================================================

db = Database()


# ================================================================================
# EMAIL SERVICE (Emailnator API)
# ================================================================================

class GmailService:
    """Custom Gmail IMAP service for dot/plus sub-addressing temporary mail."""
    
    @staticmethod
    def is_configured() -> bool:
        return bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"))
        
    @staticmethod
    def generate_email(user_id: int) -> str:
        """Generate a unique Gmail plus-variant based on the master account."""
        gmail_user = os.environ.get("GMAIL_USER")
        if not gmail_user or "@" not in gmail_user:
            return ""
        username, domain = gmail_user.split("@", 1)
        random_tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{username}+{user_id}_{random_tag}@{domain}"

    @staticmethod
    async def get_messages(user_id: int, email_addr: str) -> Optional[List[dict]]:
        """Fetch emails from Gmail IMAP folder matching the sub-address."""
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
        if not gmail_user or not gmail_pass:
            return None
            
        def _fetch():
            try:
                mail = imaplib.IMAP4_SSL("imap.gmail.com")
                mail.login(gmail_user, gmail_pass)
                mail.select("inbox")
                
                # Fetch recent messages (e.g. search ALL and take the last 30)
                status, messages = mail.search(None, 'ALL')
                if status != "OK" or not messages[0]:
                    mail.logout()
                    return []
                    
                mail_ids = messages[0].split()
                # Take the last 30 messages
                recent_ids = mail_ids[-30:]
                
                result = []
                for mail_id in reversed(recent_ids):
                    status, data = mail.fetch(mail_id, "(RFC822)")
                    if status != "OK":
                        continue
                        
                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    # Check if the TO or CC headers match our target sub-address
                    to_header = str(msg["To"] or "").lower()
                    cc_header = str(msg["Cc"] or "").lower()
                    target = email_addr.lower()
                    if target not in to_header and target not in cc_header:
                        continue
                        
                    subject, encoding = decode_header(msg["Subject"] or "No Subject")[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8", errors="ignore")
                        
                    from_, encoding = decode_header(msg["From"] or "Unknown")[0]
                    if isinstance(from_, bytes):
                        from_ = from_.decode(encoding or "utf-8", errors="ignore")
                        
                    result.append({
                        "messageID": mail_id.decode(),
                        "subject": subject,
                        "from": from_,
                        "date": msg["Date"] or ""
                    })
                    
                mail.logout()
                return result
            except Exception as e:
                logging.error(f"Gmail IMAP fetch error: {e}")
                return None
                
        return await asyncio.to_thread(_fetch)

    @staticmethod
    async def get_message_content(user_id: int, email_addr: str, message_id: str) -> Optional[str]:
        """Fetch body of specific IMAP message."""
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
        if not gmail_user or not gmail_pass:
            return None
            
        def _fetch_body():
            try:
                mail = imaplib.IMAP4_SSL("imap.gmail.com")
                mail.login(gmail_user, gmail_pass)
                mail.select("inbox")
                
                status, data = mail.fetch(message_id, "(RFC822)")
                if status != "OK":
                    return None
                    
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                            break
                        elif content_type == "text/html" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
                    
                mail.logout()
                return body or "No content"
            except Exception as e:
                logging.error(f"Gmail IMAP fetch body error: {e}")
                return None
                
        return await asyncio.to_thread(_fetch_body)


class MailTmService:
    """Mail.tm API service for generating and checking temporary emails."""
    
    @staticmethod
    def _get_password(user_id: int) -> str:
        return f"Pwd_{user_id}_MailBot!"
    
    @staticmethod
    async def get_token(user_id: int, email: str) -> Optional[str]:
        password = MailTmService._get_password(user_id)
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    f"{MAIL_TM_BASE_URL}/token",
                    json={"address": email, "password": password}
                )
                if resp.status_code == 200:
                    return resp.json().get("token")
                logging.warning(f"Failed to get Mail.tm token for {email}: {resp.status_code} {resp.text}")
                return None
            except Exception as e:
                logging.error(f"Error getting token: {e}")
                return None
    
    @staticmethod
    async def generate_email(user_id: int) -> Optional[str]:
        """Generate a new temporary email on Mail.tm."""
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(f"{MAIL_TM_BASE_URL}/domains")
                if resp.status_code != 200:
                    logging.error(f"Failed to fetch domains: {resp.text}")
                    return None
                
                domains = resp.json().get("hydra:member", [])
                if not domains:
                    logging.error("No active domains found on Mail.tm")
                    return None
                
                domain = domains[0]["domain"]
                
                username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
                email = f"{username}@{domain}"
                password = MailTmService._get_password(user_id)
                
                resp_create = await client.post(
                    f"{MAIL_TM_BASE_URL}/accounts",
                    json={"address": email, "password": password}
                )
                if resp_create.status_code in (200, 201):
                    return email
                
                logging.error(f"Failed to create account: {resp_create.text}")
                return None
            except Exception as e:
                logging.error(f"Email generation error: {e}")
                return None
    
    @staticmethod
    async def get_messages(user_id: int, email: str) -> Optional[List[dict]]:
        """Get messages for an email address."""
        token = await MailTmService.get_token(user_id, email)
        if not token:
            return None
            
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                headers = {"Authorization": f"Bearer {token}"}
                resp = await client.get(f"{MAIL_TM_BASE_URL}/messages", headers=headers)
                if resp.status_code == 200:
                    messages = resp.json().get("hydra:member", [])
                    mapped_messages = []
                    for m in messages:
                        from_obj = m.get("from", {})
                        from_name = from_obj.get("name", "")
                        from_addr = from_obj.get("address", "")
                        from_str = f"{from_name} <{from_addr}>" if from_name else from_addr
                        
                        mapped_messages.append({
                            "messageID": m.get("id"),
                            "subject": m.get("subject", "No Subject"),
                            "from": from_str,
                            "date": m.get("createdAt", "")
                        })
                    return mapped_messages
                return None
            except Exception as e:
                logging.error(f"Get messages error: {e}")
                return None
    
    @staticmethod
    async def get_message_content(user_id: int, email: str, message_id: str) -> Optional[str]:
        """Get full content of a specific message."""
        token = await MailTmService.get_token(user_id, email)
        if not token:
            return None
            
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                headers = {"Authorization": f"Bearer {token}"}
                resp = await client.get(f"{MAIL_TM_BASE_URL}/messages/{message_id}", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("text") or data.get("html") or "No content"
                return None
            except Exception as e:
                logging.error(f"Get message content error: {e}")
                return None


class EmailService:
    """Unified API service selecting between Gmail IMAP and Mail.tm dynamically."""
    
    @staticmethod
    async def generate_email(user_id: int) -> Optional[str]:
        if GmailService.is_configured():
            return GmailService.generate_email(user_id)
        else:
            return await MailTmService.generate_email(user_id)
            
    @staticmethod
    async def get_messages(user_id: int, email: str) -> Optional[List[dict]]:
        if GmailService.is_configured() and "@gmail.com" in email:
            return await GmailService.get_messages(user_id, email)
        else:
            return await MailTmService.get_messages(user_id, email)
            
    @staticmethod
    async def get_message_content(user_id: int, email: str, message_id: str) -> Optional[str]:
        if GmailService.is_configured() and "@gmail.com" in email:
            return await GmailService.get_message_content(user_id, email, message_id)
        else:
            return await MailTmService.get_message_content(user_id, email, message_id)


# ================================================================================
# FORCE JOIN CHECK
# ================================================================================

async def check_force_join(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
    """
    Check if user has joined all required channels.
    Returns (passed, message).
    """
    channels = db.get_force_channel_ids()
    if not channels:
        return True, ""
    
    not_joined = []
    
    for channel in channels:
        try:
            # Handle both @username and -100xxx formats
            chat_id = channel
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ('left', 'kicked'):
                not_joined.append(channel)
        except Exception as e:
            logging.warning(f"Force join check failed for {channel}: {e}")
            not_joined.append(channel)
    
    if not_joined:
        msg = "Please join the following channels to use this bot:\n\n"
        for ch in not_joined:
            msg += f"Join @{ch.replace('@', '')}\n"
        msg += "\nThen press /start again."
        return False, msg
    
    return True, ""


# ================================================================================
# USER COMMANDS
# ================================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - registration and welcome."""
    user_id = update.effective_user.id
    username = update.effective_user.username or ''
    first_name = update.effective_user.first_name or ''
    
    # Check for referral
    referred_by = None
    if context.args and context.args[0].startswith("ref_"):
        ref_code = context.args[0][4:]
        ref_user = db._fetchone("SELECT user_id FROM users WHERE referral_code = ?", (ref_code,))
        if ref_user:
            referred_by = ref_user['user_id']
    
    # Check if banned first
    user = db.get_user(user_id)
    if user and user['is_banned']:
        await update.message.reply_text("⛔️ <b>You are banned from using this bot.</b>", parse_mode=ParseMode.HTML)
        return
    
    # Register or update
    is_new, ref_code, welcome_bonus = db.register_user(user_id, username, first_name, referred_by)
    user = db.get_user(user_id)
    
    # Force join check
    passed, msg = await check_force_join(user_id, context)
    if not passed:
        await update.message.reply_text(
            UI.box("Join Required", msg),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Welcome message
    body = f"👋 Welcome, <b>{html.escape(first_name)}</b>! 🎉\n"
    body += "━━━━━━━━━━━━━━━━━━━━━\n"
    if is_new:
        body += f"✨ <code>+{WELCOME_BONUS} credits</code> welcome bonus added!\n"
        if referred_by:
            body += "🎁 Referral bonus applied successfully!\n"
    else:
        body += "✨ Welcome back to the ultimate mail dashboard!\n"
    
    email = user.get('email', '')
    if email:
        body += f"\n📧 <b>Your Address:</b>\n<code>{email}</code>\n"
    else:
        body += "\n📧 <i>You don't have an email address yet.</i>\n👉 Tap <b>NEW EMAIL</b> to generate one.\n"
    
    body += f"\n💰 <b>Balance:</b> <code>{user['credits']} credits</code>\n"
    body += f"🔗 <b>Referral Code:</b> <code>ref_{ref_code}</code>\n\n"
    body += "📱 Use the reply menu below or send /help to list all commands."
    
    await update.message.reply_text(
        UI.box("Temp Mail Bot", body),
        parse_mode=ParseMode.HTML,
        reply_markup=UI.get_reply_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    body = (
        "📌 <b>EMAIL MANAGEMENT</b>\n"
        "• /newemail - Generate a new temporary address\n"
        "• /inbox - Read incoming messages\n"
        "• /read_&lt;id&gt; - Open specific email\n\n"
        "💰 <b>ECONOMY & CREDITS</b>\n"
        "• /daily - Daily check-in rewards\n"
        "• /referral - View referral stats & link\n"
        "• /redeem - Use a pass/key code\n"
        "• /balance - Quick wallet check\n\n"
        "📊 <b>INFORMATION</b>\n"
        "• /mystats - Detailed account logs\n"
        "• /leaderboard - Top users ranking\n"
        "• /help - Display this manual"
    )
    await update.message.reply_text(
        UI.box("Bot Commands Help", body),
        parse_mode=ParseMode.HTML,
        reply_markup=UI.get_reply_keyboard()
    )


async def new_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /newemail command - generate a new temp email."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    # Check credits
    if user['credits'] < EMAIL_COST:
        await update.message.reply_text(
            f"⚠️ <b>Not enough credits!</b> You need <code>{EMAIL_COST} credit</code>.\n👉 Use /daily or refer friends to earn more.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Deduct credits
    if not db.deduct_credits(user_id, EMAIL_COST):
        await update.message.reply_text("⚠️ Transaction failed. Try again.", parse_mode=ParseMode.HTML)
        return
    
    # Generate email
    status_msg = await update.message.reply_text("⚙️ <b>Generating your premium address...</b>", parse_mode=ParseMode.HTML)
    
    email = await EmailService.generate_email(user_id)
    if not email:
        db._execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (EMAIL_COST, user_id))
        db.conn.commit()
        await status_msg.edit_text("❌ <b>Failed to generate email. Please try again later.</b>", parse_mode=ParseMode.HTML)
        return
    
    db.set_email(user_id, email)
    
    body = (
        f"📧 <b>Your New Temporary Email:</b>\n"
        f"<code>{email}</code>\n\n"
        f"💰 <b>Cost:</b> <code>{EMAIL_COST} credit</code>\n"
    )
    
    if not GmailService.is_configured():
        body += "💡 <i>Pro Tip: Add GMAIL_USER & GMAIL_APP_PASSWORD to Render variables to generate real <b>@gmail.com</b> addresses!</i>\n\n"
        
    body += "📥 <i>Tap the <b>INBOX</b> button below to check your mail!</i>"
    
    await status_msg.edit_text(
        UI.box("Email Generated", body),
        parse_mode=ParseMode.HTML,
        reply_markup=UI.get_reply_keyboard()
    )


async def inbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /inbox command - display inbox with pagination."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    email = user.get('email', '')
    if not email:
        await update.message.reply_text("📧 <b>No email found.</b> Tap <b>NEW EMAIL</b> to generate one.", parse_mode=ParseMode.HTML)
        return
    
    messages = await EmailService.get_messages(user_id, email)
    if messages is None:
        await update.message.reply_text("❌ <b>Error fetching inbox.</b> Your email session may have expired. Please generate a 🆕 <b>NEW EMAIL</b>.", parse_mode=ParseMode.HTML)
        return
    
    if not messages:
        await update.message.reply_text("📥 <b>Your inbox is currently empty.</b>", parse_mode=ParseMode.HTML)
        return
    
    # Sort by newest first (by date)
    messages.sort(key=lambda m: m.get('date', ''), reverse=True)
    
    # Paginate
    page = 0
    if context.args and context.args[0].isdigit():
        page = int(context.args[0])
    
    total_pages = (len(messages) + MESSAGES_PER_PAGE - 1) // MESSAGES_PER_PAGE
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start = page * MESSAGES_PER_PAGE
    end = start + MESSAGES_PER_PAGE
    page_messages = messages[start:end]
    
    body = f"📧 <b>Mailbox:</b> <code>{email}</code>\n"
    body += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for msg_data in page_messages:
        mid = msg_data.get('messageID', '?')
        subject = msg_data.get('subject', msg_data.get('from', 'No Subject'))
        from_addr = msg_data.get('from', 'Unknown')
        
        # Check if seen
        seen = db.is_message_seen(user_id, mid)
        icon = "✉️" if not seen else "📖"
        
        body += (
            f"{icon} <b>Subject:</b> {html.escape(subject[:40])}\n"
            f"👤 <b>From:</b> {html.escape(from_addr[:40])}\n"
            f"🔗 <b>Open Message:</b> /read_{mid}\n\n"
        )
    
    body += f"📖 <b>Page {page + 1} of {total_pages}</b> | {len(messages)} total messages"
    
    # Build navigation buttons
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"inbox_{page - 1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"inbox_{page + 1}"))
    
    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
    
    await update.message.reply_text(
        UI.box("Your Inbox", body),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /read_<id> command - read specific message."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    # Extract message ID from command text
    text = update.message.text.strip()
    if "_" not in text:
        return
    
    # Handle /read_123 or /read_123@botname
    message_id = text.split('_', 1)[1].split('@', 1)[0]
    email = user.get('email', '')
    
    if not email:
        await update.message.reply_text("📧 <b>No email found.</b> Tap <b>NEW EMAIL</b> to generate one.", parse_mode=ParseMode.HTML)
        return
    
    # Get message content
    content = await EmailService.get_message_content(user_id, email, message_id)
    if not content:
        await update.message.reply_text("❌ <b>Message not found or could not be retrieved.</b>", parse_mode=ParseMode.HTML)
        return
    
    # Mark as seen
    db.mark_message_seen(user_id, message_id, email)
    
    # Truncate if too long
    if len(content) > 3500:
        content = content[:3500] + "\n\n...(truncated)"
    
    escaped_content = html.escape(content)
    body = f"<b>Message Content:</b>\n\n<pre>{escaped_content}</pre>"
    await update.message.reply_text(
        UI.box("Message Content", body),
        parse_mode=ParseMode.HTML
    )


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /daily command - daily check-in."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    if not db.can_checkin(user_id):
        streak_info = db.get_streak_info(user_id)
        body = (
            f"❌ <b>You have already checked in today!</b>\n\n"
            f"🔥 <b>Current Streak:</b> <code>{streak_info['streak']} days</code>\n"
            f"⏳ <i>Come back tomorrow to keep the streak going!</i>"
        )
        await update.message.reply_text(UI.box("Daily Check-in", body), parse_mode=ParseMode.HTML)
        return
    
    result = db.do_checkin(user_id)
    credits = db.get_credits(user_id)
    
    body = (
        f"🎁 <b>Check-in successful!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Reward:</b> <code>+{result['bonus']} credits</code>\n"
    )
    if result['multiplier_active']:
        body += f"✨ <b>Multiplier Active:</b> <code>{result['multiplier']}x</code> 🔥\n"
    body += (
        f"🔥 <b>New Streak:</b> <code>{result['streak']} days</code>\n"
        f"💳 <b>New Wallet Balance:</b> <code>{credits} credits</code>"
    )
    
    await update.message.reply_text(
        UI.box("Daily Check-in", body),
        parse_mode=ParseMode.HTML
    )


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referral command - display referral info."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    ref_code = user['referral_code']
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{ref_code}"
    
    ref_stats = db.get_referral_stats(user_id)
    
    body = (
        f"🔗 <b>Your Exclusive Invite Link:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 <b>Total Invited:</b> <code>{ref_stats['count']} users</code>\n"
        f"💰 <b>Total Earned:</b> <code>{ref_stats['total_bonus']} credits</code>\n\n"
        f"📣 <i>Share your link! You will earn <code>{REFERRAL_BONUS} credits</code> for every user who registers.</i>"
    )
    
    await update.message.reply_text(
        UI.box("Referral Program", body),
        parse_mode=ParseMode.HTML
    )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance command."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    ref_stats = db.get_referral_stats(user_id)
    streak_info = db.get_streak_info(user_id)
    
    body = (
        f"💳 <b>Wallet Balance:</b> <code>{user['credits']} credits</code>\n"
        f"📈 <b>Lifetime Earnings:</b> <code>{user['total_earned']} credits</code>\n\n"
        f"👥 <b>Referrals:</b> <code>{ref_stats['count']} users</code>\n"
        f"🔥 <b>Streak:</b> <code>{streak_info['streak']} days</code>\n\n"
        f"💡 <i>Earn more via /daily, invite friends /referral, or redeem a key /redeem</i>"
    )
    await update.message.reply_text(
        UI.box("Wallet Balance", body),
        parse_mode=ParseMode.HTML
    )


async def mystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mystats command."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    ref_stats = db.get_referral_stats(user_id)
    streak_info = db.get_streak_info(user_id)
    
    body = (
        f"👤 <b>Name:</b> {html.escape(user['first_name'])}\n"
        f"🆔 <b>Account ID:</b> <code>{user_id}</code>\n"
        f"📧 <b>Current Mail:</b> <code>{user.get('email', 'N/A')}</code>\n"
        f"📅 <b>Joined:</b> <code>{str(user['joined_at'])[:10]}</code>\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Wallet Balance:</b> <code>{user['credits']} cr</code>\n"
        f"📈 <b>Lifetime Earned:</b> <code>{user['total_earned']} cr</code>\n"
        f"👥 <b>Total Referrals:</b> <code>{ref_stats['count']}</code>\n"
        f"🔥 <b>Check-in Streak:</b> <code>{streak_info['streak']} days</code>\n"
        f"📧 <b>Emails Generated:</b> <code>{user['total_emails']}</code>"
    )
    await update.message.reply_text(
        UI.box("Account Statistics", body),
        parse_mode=ParseMode.HTML
    )


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /leaderboard command."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    # Get top users by credits
    top_users = db._fetchall(
        "SELECT user_id, first_name, username, credits FROM users "
        "WHERE is_banned = 0 ORDER BY credits DESC LIMIT ?",
        (LEADERBOARD_LIMIT,)
    )
    
    body = "🏆 <b>TOP CREDITS LEADERBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top_users):
        rank = i + 1
        medal = medals[i] if i < 3 else f"<code>{rank:02d}.</code>"
        name = u['first_name'] or f"User {u['user_id']}"
        if u['username']:
            name = f"@{u['username']}"
        
        highlight = " 🌟 (You)" if u['user_id'] == user_id else ""
        body += f"{medal} <b>{html.escape(name)}</b> - <code>{u['credits']} credits</code>{highlight}\n"
    
    await update.message.reply_text(
        UI.box("Leaderboard", body),
        parse_mode=ParseMode.HTML
    )


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /redeem command - redeem a pass code."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("⚠️ Please use /start first to register.", parse_mode=ParseMode.HTML)
        return
    
    if user['is_banned']:
        await update.message.reply_text("⛔️ You are banned from using this bot.", parse_mode=ParseMode.HTML)
        return
    
    if not context.args:
        await update.message.reply_text(
            "💡 <b>Usage:</b> <code>/redeem &lt;CODE&gt;</code>\n\nExample: <code>/redeem GIFT50CREDITS</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    code = context.args[0].upper()
    success, message = db.redeem_pass(code, user_id)
    
    await update.message.reply_text(f"🔑 <b>Redeem Pass:</b>\n\n{message}", parse_mode=ParseMode.HTML)


# ================================================================================
# REPLY KEYBOARD HANDLER
# ================================================================================

async def redeem_btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start redeeming process from reply keyboard."""
    context.user_data['awaiting_redeem'] = True
    await update.message.reply_text(
        "🔑 <b>Please enter the pass code you want to redeem:</b>",
        parse_mode=ParseMode.HTML
    )


async def reply_keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reply keyboard button presses."""
    text = update.message.text.strip()
    
    # Check if user is awaiting pass redeem code
    if context.user_data.get('awaiting_redeem'):
        context.user_data['awaiting_redeem'] = False
        code = text.upper()
        success, message = db.redeem_pass(code, update.effective_user.id)
        await update.message.reply_text(f"🔑 <b>Redeem Pass:</b>\n\n{message}", parse_mode=ParseMode.HTML)
        return

    command_map = {
        "INBOX": inbox_command,
        "DAILY CHECK-IN": daily_command,
        "REFERRALS": referral_command,
        "BALANCE": balance_command,
        "MY STATS": mystats_command,
        "LEADERBOARD": leaderboard_command,
        "HELP": help_command,
        "NEW EMAIL": new_email_command,
        "REDEEM KEY": redeem_btn_handler,
    }
    
    # Strip emoji prefixes for matching
    for prefix in ["📥 ", "📅 ", "👥 ", "💰 ", "📊 ", "🏆 ", "❓ ", "🆕 ", "🔑 "]:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    
    handler = command_map.get(text)
    if handler:
        await handler(update, context)
    else:
        await update.message.reply_text(
            "Unknown option. Please use the buttons below.",
            reply_markup=UI.get_reply_keyboard()
        )


# ================================================================================
# CALLBACK QUERY HANDLER
# ================================================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # Check ban status (allow unregistered users through)
    user = db.get_user(user_id)
    if user and user['is_banned']:
        await query.edit_message_text("You are banned from using this bot.")
        return
        
    # Admin Panel callback routing
    if data.startswith("admin_"):
        if user_id not in ADMIN_IDS:
            await query.edit_message_text("Access denied. Admin only.")
            return
            
        action = data.split("_")[1]
        
        if action == "menu":
            await _show_admin_menu(query)
        elif action == "passes":
            await _show_admin_passes(query)
        elif action == "listpass":
            await _show_admin_listpass(query)
        elif action == "channels":
            await _show_admin_channels(query)
        elif action == "listchannels":
            await _show_admin_listchannels(query)
        elif action == "users":
            await _show_admin_users(query)
        elif action == "stats":
            await _show_admin_stats(query)
        elif action == "logs":
            await _show_admin_logs(query)
        elif action == "broadcast":
            await _show_admin_broadcast(query)
        elif action == "close":
            try:
                await query.delete_message()
            except:
                pass
        return
    
    # Inbox pagination
    if data.startswith("inbox_"):
        parts = data.split("_")
        page = int(parts[1]) if len(parts) > 1 else 0
        await _display_inbox_page(query, context, user_id, page)
    
    # No-op (for back buttons that just go to menu)
    elif data == "noop":
        pass


async def _display_inbox_page(query, context, user_id: int, page: int):
    """Display a specific inbox page via callback."""
    user = db.get_user(user_id)
    if not user:
        await query.edit_message_text("Please use /start first.")
        return
    
    email = user.get('email', '')
    if not email:
        await query.edit_message_text("No email found. Use /newemail to generate one.")
        return
    
    messages = await EmailService.get_messages(user_id, email)
    if messages is None:
        await query.edit_message_text("Error fetching inbox. Your email session may have expired. Please generate a 🆕 NEW EMAIL.")
        return
        
    if not messages:
        await query.edit_message_text("Inbox is empty.")
        return
    
    messages.sort(key=lambda m: m.get('date', ''), reverse=True)
    
    total_pages = (len(messages) + MESSAGES_PER_PAGE - 1) // MESSAGES_PER_PAGE
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1
    
    start = page * MESSAGES_PER_PAGE
    end = start + MESSAGES_PER_PAGE
    page_messages = messages[start:end]
    body = f"📧 <b>Mailbox:</b> <code>{email}</code>\n"
    body += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for msg_data in page_messages:
        mid = msg_data.get('messageID', '?')
        subject = msg_data.get('subject', msg_data.get('from', 'No Subject'))
        from_addr = msg_data.get('from', 'Unknown')
        
        seen = db.is_message_seen(user_id, mid)
        icon = "✉️" if not seen else "📖"
        
        body += (
            f"{icon} <b>Subject:</b> {html.escape(subject[:40])}\n"
            f"👤 <b>From:</b> {html.escape(from_addr[:40])}\n"
            f"🔗 <b>Open Message:</b> /read_{mid}\n\n"
        )
    
    body += f"📖 <b>Page {page + 1} of {total_pages}</b> | {len(messages)} total messages"
    
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"inbox_{page - 1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"inbox_{page + 1}"))
        
    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
    
    await query.edit_message_text(
        UI.box("Your Inbox", body),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


# ================================================================================
# INTERACTIVE ADMIN PANEL SUITE
# ================================================================================

async def _send_admin_menu_content():
    body = (
        "⚙️ <b>ADMIN OPERATIONS PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome, Admin! Select a category below to perform system management:"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Pass Manager", callback_data="admin_passes"),
            InlineKeyboardButton("📢 Force Join Lock", callback_data="admin_channels")
        ],
        [
            InlineKeyboardButton("👤 User Moderator", callback_data="admin_users"),
            InlineKeyboardButton("📊 System Stats", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("📑 Audit Logs", callback_data="admin_logs"),
            InlineKeyboardButton("📡 Broadcast Alert", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")
        ]
    ])
    return UI.box("Admin Console", body), keyboard


async def _show_admin_menu(query):
    text, reply_markup = await _send_admin_menu_content()
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def _show_admin_passes(query):
    body = (
        "🔑 <b>PASS MANAGER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "To manage passes, use these commands in chat:\n"
        "• <code>/createpass &lt;cr&gt; [uses=1] [days=0]</code>\n"
        "• <code>/delpass &lt;code&gt;</code>\n"
        "• <code>/passinfo &lt;code&gt;</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Active Passes", callback_data="admin_listpass")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_menu")]
    ])
    await query.edit_message_text(
        UI.box("Pass Manager", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_listpass(query):
    passes = db.list_passes()
    if not passes:
        body = "📋 <b>No active passes created yet.</b>"
    else:
        body = "📋 <b>ACTIVE PASSES (LATEST 20)</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        for p in passes[:20]:
            expiry = f"Exp: {str(p['expires_at'])[:10]}" if p['expires_at'] else "No expiry"
            body += f"🔑 <code>{p['code']}</code>\n💰 <code>{p['credits']} cr</code> | 🔄 <code>{p['uses_left']}/{p['max_uses']}</code> | ⏰ {expiry}\n\n"
            
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Pass Manager", callback_data="admin_passes")]
    ])
    await query.edit_message_text(
        UI.box("Pass List", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_channels(query):
    body = (
        "📢 <b>FORCE JOIN CHANNELS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "To manage lock channels, use these commands in chat:\n"
        "• <code>/addchannel &lt;@username&gt;</code>\n"
        "• <code>/removechannel &lt;@username&gt;</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Locked Channels", callback_data="admin_listchannels")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_menu")]
    ])
    await query.edit_message_text(
        UI.box("Force Join Lock", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_listchannels(query):
    channels = db.list_force_channels()
    if not channels:
        body = "⚠️ <b>No force join channels configured.</b>"
    else:
        body = ""
        active_count = 0
        for ch in channels:
            status = "🟢 Active" if ch['is_active'] else "🔴 Inactive"
            if ch['is_active']:
                active_count += 1
            body += f"📢 <code>{ch['channel_id']}</code> - {status}\n📅 Added: <code>{str(ch['added_at'])[:10]}</code>\n\n"
        body = f"👥 <b>Active:</b> <code>{active_count}</code> | <b>Total:</b> <code>{len(channels)}</code>\n━━━━━━━━━━━━━━━━━━━━━\n\n" + body
        
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Channel Lock", callback_data="admin_channels")]
    ])
    await query.edit_message_text(
        UI.box("Force Channels", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_users(query):
    body = (
        "👤 <b>USER MODERATION PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Perform user management by typing these commands in chat:\n"
        "• <code>/ban &lt;user_id&gt;</code>\n"
        "• <code>/unban &lt;user_id&gt;</code>\n"
        "• <code>/userinfo &lt;user_id&gt;</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_menu")]
    ])
    await query.edit_message_text(
        UI.box("User Moderator", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_stats(query):
    stats = db.get_stats()
    body = (
        f"👥 <b>USER BASE METRICS</b>\n"
        f"• <b>Total Registered:</b> <code>{stats['total_users']} users</code>\n"
        f"• <b>Active Today:</b> <code>{stats['active_today']} users</code>\n\n"
        f"📨 <b>BOT ACTIVITY STATS</b>\n"
        f"• <b>Emails Generated:</b> <code>{stats['total_emails']} addresses</code>\n"
        f"• <b>Check-ins Claimed:</b> <code>{stats['total_checkins']} daily</code>\n"
        f"• <b>Successful Referrals:</b> <code>{stats['total_referrals']} signups</code>\n\n"
        f"🔑 <b>CREDIT KEY SYSTEM</b>\n"
        f"• <b>Keys Created:</b> <code>{stats['total_passes_created']} keys</code>\n"
        f"• <b>Keys Redeemed:</b> <code>{stats['total_pass_redemptions']} keys</code>\n"
        f"• <b>Unredeemed Active:</b> <code>{stats['total_passes']} keys</code>\n\n"
        f"⚙️ <b>SYSTEM CONFIG</b>\n"
        f"• <b>Locked Channels:</b> <code>{stats['total_force_channels']} channels</code>\n"
        f"• <b>Total Bans Enforced:</b> <code>{stats['total_bans']} users</code>\n"
        f"• <b>Total Broadcasts:</b> <code>{stats['total_broadcasts']} alerts</code>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_stats"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_menu")
        ]
    ])
    await query.edit_message_text(
        UI.box("Bot Statistics", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_logs(query):
    logs = db.get_admin_logs(30)
    if not logs:
        body = "⚠️ <b>No admin logs found.</b>"
    else:
        body = ""
        for log in logs[:20]:
            action_emoji = {
                'ban': '🔨', 'unban': '✅', 'force_join_add': '📢', 'force_join_remove': '🗑️',
                'broadcast': '📡', 'create_pass': '🔑'
            }.get(log['action'], '🔹')
            body += f"{action_emoji} <b>{log['action'].upper()}</b> ➔ <code>{log['target']}</code>\n👤 Admin: <code>{html.escape(log['admin_name'] or str(log['admin_id']))}</code> | 🕐 {str(log['created_at'])[:16]}\n\n"
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Logs", callback_data="admin_logs"),
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_menu")
        ]
    ])
    await query.edit_message_text(
        UI.box("Admin Logs", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


async def _show_admin_broadcast(query):
    body = (
        "📡 <b>BROADCAST ALERT SYSTEM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "To broadcast an announcement, type this command in chat:\n"
        "<code>/broadcast &lt;message&gt;</code>\n\n"
        "<i>Note: You can use HTML formatting tags like &lt;b&gt;bold&lt;/b&gt; and &lt;code&gt;code&lt;/code&gt;!</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="admin_menu")]
    ])
    await query.edit_message_text(
        UI.box("Broadcast System", body),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )


@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open admin panel."""
    text, reply_markup = await _send_admin_menu_content()
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )


@admin_only
async def admin_createpass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a pass/key."""
    if len(context.args) < 1:
        await update.message.reply_text(
            "💡 <b>Usage:</b> <code>/createpass &lt;credits&gt; [max_uses=1] [expires_days=0]</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        credits = float(context.args[0])
        max_uses = int(context.args[1]) if len(context.args) > 1 else 1
        expires_days = int(context.args[2]) if len(context.args) > 2 else 0
    except ValueError:
        await update.message.reply_text("⚠️ <b>Invalid arguments. Use numbers.</b>", parse_mode=ParseMode.HTML)
        return
    
    if credits <= 0 or max_uses <= 0 or expires_days < 0:
        await update.message.reply_text("⚠️ <b>Values must be positive.</b>", parse_mode=ParseMode.HTML)
        return
    
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    if db.create_pass(code, credits, max_uses, update.effective_user.id, expires_days):
        expiry_text = f"Expires in {expires_days} days" if expires_days > 0 else "Never expires"
        body = (
            f"🔑 <b>Pass Code:</b> <code>{code}</code>\n"
            f"💰 <b>Credits:</b> <code>{credits}</code>\n"
            f"🔄 <b>Max Uses:</b> <code>{max_uses}</code>\n"
            f"⏰ <b>Expiry:</b> <code>{expiry_text}</code>\n\n"
            f"👉 <i>Redeem with:</i>\n<code>/redeem {code}</code>"
        )
        await update.message.reply_text(
            UI.box("Pass Created", body),
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("❌ <b>Error creating pass. Try again.</b>", parse_mode=ParseMode.HTML)


@admin_only
async def admin_listpass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all passes."""
    passes = db.list_passes()
    if not passes:
        await update.message.reply_text("⚠️ <b>No active passes created yet.</b>", parse_mode=ParseMode.HTML)
        return
    
    body = "📋 <b>ACTIVE PASSES (LATEST 20)</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for p in passes[:20]:
        expiry = f"Exp: {str(p['expires_at'])[:10]}" if p['expires_at'] else "No expiry"
        body += f"🔑 <code>{p['code']}</code>\n💰 <code>{p['credits']} cr</code> | 🔄 <code>{p['uses_left']}/{p['max_uses']}</code> | ⏰ {expiry}\n\n"
    
    await update.message.reply_text(
        UI.box("All Passes", body),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def admin_delpass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a pass."""
    if not context.args:
        await update.message.reply_text("💡 <b>Usage:</b> <code>/delpass &lt;code&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    code = context.args[0].upper()
    db.delete_pass(code)
    await update.message.reply_text(f"✅ <b>Deleted pass</b> <code>{code}</code>", parse_mode=ParseMode.HTML)


@admin_only
async def admin_passinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get pass information."""
    if not context.args:
        await update.message.reply_text("💡 <b>Usage:</b> <code>/passinfo &lt;code&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    info = db.get_pass_info(context.args[0])
    if not info:
        await update.message.reply_text("❌ <b>Pass not found.</b>", parse_mode=ParseMode.HTML)
        return
    
    expiry = f"Expires: {str(info['expires_at'])[:10]}" if info['expires_at'] else "No expiry"
    body = (
        f"🔑 <b>Code:</b> <code>{info['code']}</code>\n"
        f"💰 <b>Credits:</b> <code>{info['credits']}</code>\n"
        f"🔄 <b>Redemptions:</b> <code>{info['uses_left']}/{info['max_uses']} left</code>\n"
        f"⏰ <b>Expiry:</b> <code>{expiry}</code>\n"
        f"📅 <b>Created:</b> <code>{str(info['created_at'])[:10]}</code>"
    )
    await update.message.reply_text(
        UI.box("Pass Info", body),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def admin_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a force join channel."""
    if not context.args:
        await update.message.reply_text(
            "💡 <b>Usage:</b> <code>/addchannel &lt;channel_username_or_id&gt;</code>\n\nExample: <code>/addchannel @my_channel</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    channel_id = context.args[0]
    channel_name = ' '.join(context.args[1:]) if len(context.args) > 1 else channel_id
    
    success, message = db.add_force_channel(channel_id, channel_name, update.effective_user.id)
    await update.message.reply_text(f"📢 <b>Force Join System:</b>\n{message}", parse_mode=ParseMode.HTML)


@admin_only
async def admin_removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a force join channel."""
    if not context.args:
        await update.message.reply_text(
            "💡 <b>Usage:</b> <code>/removechannel &lt;channel_username_or_id&gt;</code>\n\nExample: <code>/removechannel @my_channel</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    channel_id = context.args[0]
    success, message = db.remove_force_channel(channel_id, update.effective_user.id)
    await update.message.reply_text(f"🗑️ <b>Force Join System:</b>\n{message}", parse_mode=ParseMode.HTML)


@admin_only
async def admin_listchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all force join channels."""
    channels = db.list_force_channels()
    
    if not channels:
        await update.message.reply_text("⚠️ <b>No force join channels configured.</b>", parse_mode=ParseMode.HTML)
        return
    
    body = ""
    active_count = 0
    for ch in channels:
        status = "🟢 Active" if ch['is_active'] else "🔴 Inactive"
        if ch['is_active']:
            active_count += 1
        body += f"📢 <code>{ch['channel_id']}</code> - {status}\n📅 Added: <code>{str(ch['added_at'])[:10]}</code>\n\n"
    
    body = f"👥 <b>Active:</b> <code>{active_count}</code> | <b>Total:</b> <code>{len(channels)}</code>\n━━━━━━━━━━━━━━━━━━━━━\n\n" + body
    
    await update.message.reply_text(
        UI.box("Force Channels", body),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user."""
    if not context.args:
        await update.message.reply_text("💡 <b>Usage:</b> <code>/ban &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        if db.ban_user(target_id, update.effective_user.id):
            await update.message.reply_text(f"🔨 <b>Successfully banned user</b> <code>{target_id}</code>", parse_mode=ParseMode.HTML)
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=UI.box("Banned", "⛔️ <b>You have been banned from using this bot.</b>\n\n<i>Contact an administrator if you believe this is an error.</i>"),
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        else:
            await update.message.reply_text(
                f"❌ Could not ban <code>{target_id}</code>. User may not exist or is already banned.",
                parse_mode=ParseMode.HTML
            )
    except ValueError:
        await update.message.reply_text("⚠️ <b>Invalid user ID. Use a numeric Telegram ID.</b>", parse_mode=ParseMode.HTML)


@admin_only
async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user."""
    if not context.args:
        await update.message.reply_text("💡 <b>Usage:</b> <code>/unban &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        if db.unban_user(target_id, update.effective_user.id):
            await update.message.reply_text(f"✅ <b>Successfully unbanned user</b> <code>{target_id}</code>", parse_mode=ParseMode.HTML)
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=UI.box("Unbanned", "🎉 <b>You have been unbanned!</b> You can now use the bot again.\n\n👉 Send /start to reload."),
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        else:
            await update.message.reply_text(
                f"❌ Could not unban <code>{target_id}</code>. User may not exist or is not banned.",
                parse_mode=ParseMode.HTML
            )
    except ValueError:
        await update.message.reply_text("⚠️ <b>Invalid user ID. Use a numeric Telegram ID.</b>", parse_mode=ParseMode.HTML)


@admin_only
async def admin_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get detailed user information."""
    if not context.args:
        await update.message.reply_text("💡 <b>Usage:</b> <code>/userinfo &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    try:
        target_id = int(context.args[0])
        u = db.get_user(target_id)
        if not u:
            await update.message.reply_text(f"❌ User <code>{target_id}</code> not found in database.", parse_mode=ParseMode.HTML)
            return
        
        ref_stats = db.get_referral_stats(target_id)
        streak_info = db.get_streak_info(target_id)
        
        body = (
            f"👤 <b>PROFILE</b>\n"
            f"• <b>User ID:</b> <code>{u['user_id']}</code>\n"
            f"• <b>First Name:</b> <code>{html.escape(u['first_name'])}</code>\n"
        )
        if u['username']:
            body += f"• <b>Username:</b> @{html.escape(u['username'])}\n"
        body += (
            f"• <b>Email:</b> <code>{u.get('email', 'N/A')}</code>\n\n"
            f"💰 <b>ECONOMY</b>\n"
            f"• <b>Credits:</b> <code>{u['credits']} cr</code>\n"
            f"• <b>Lifetime Earned:</b> <code>{u['total_earned']} cr</code>\n"
            f"• <b>Emails Generated:</b> <code>{u['total_emails']}</code>\n\n"
            f"📈 <b>ENGAGEMENT</b>\n"
            f"• <b>Referrals:</b> <code>{ref_stats['count']} users</code>\n"
            f"• <b>Daily Streak:</b> <code>{streak_info['streak']} days</code>\n"
            f"• <b>Joined Bot:</b> <code>{str(u['joined_at'])[:10]}</code>\n"
            f"• <b>Last Checkin:</b> <code>{u.get('last_checkin', 'Never')}</code>\n\n"
            f"🚫 <b>ACCOUNT STATUS</b>\n"
            f"• <b>Is Banned:</b> <code>{'🔴 YES' if u['is_banned'] else '🟢 NO'}</code>"
        )
        await update.message.reply_text(
            UI.box("User Account Details", body),
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text("⚠️ <b>Invalid user ID. Use a numeric Telegram ID.</b>", parse_mode=ParseMode.HTML)


@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get comprehensive bot statistics."""
    stats = db.get_stats()
    
    body = (
        f"👥 <b>USER BASE METRICS</b>\n"
        f"• <b>Total Registered:</b> <code>{stats['total_users']} users</code>\n"
        f"• <b>Active Today:</b> <code>{stats['active_today']} users</code>\n\n"
        f"📨 <b>BOT ACTIVITY STATS</b>\n"
        f"• <b>Emails Generated:</b> <code>{stats['total_emails']} addresses</code>\n"
        f"• <b>Check-ins Claimed:</b> <code>{stats['total_checkins']} daily</code>\n"
        f"• <b>Successful Referrals:</b> <code>{stats['total_referrals']} signups</code>\n\n"
        f"🔑 <b>CREDIT KEY SYSTEM</b>\n"
        f"• <b>Keys Created:</b> <code>{stats['total_passes_created']} keys</code>\n"
        f"• <b>Keys Redeemed:</b> <code>{stats['total_pass_redemptions']} keys</code>\n"
        f"• <b>Unredeemed Active:</b> <code>{stats['total_passes']} keys</code>\n\n"
        f"⚙️ <b>SYSTEM CONFIG</b>\n"
        f"• <b>Locked Channels:</b> <code>{stats['total_force_channels']} channels</code>\n"
        f"• <b>Total Bans Enforced:</b> <code>{stats['total_bans']} users</code>\n"
        f"• <b>Total Broadcasts:</b> <code>{stats['total_broadcasts']} alerts</code>"
    )
    await update.message.reply_text(
        UI.box("Server Administration Statistics", body),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent admin logs."""
    logs = db.get_admin_logs(30)
    
    if not logs:
        await update.message.reply_text("⚠️ <b>No admin logs found.</b>", parse_mode=ParseMode.HTML)
        return
    
    body = ""
    for log in logs[:20]:
        action_emoji = {
            'ban': '🔨', 'unban': '✅', 'force_join_add': '📢', 'force_join_remove': '🗑️',
            'broadcast': '📡', 'create_pass': '🔑'
        }.get(log['action'], '🔹')
        
        body += f"{action_emoji} <b>{log['action'].upper()}</b> ➔ <code>{log['target']}</code>\n👤 Admin: <code>{html.escape(log['admin_name'] or str(log['admin_id']))}</code> | 🕐 {str(log['created_at'])[:16]}\n\n"
    
    await update.message.reply_text(
        UI.box("Admin Security Log Trail", body),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast a message to all users."""
    if not context.args:
        body = "💡 <b>Usage:</b> <code>/broadcast &lt;message&gt;</code>\n\nExample: <code>/broadcast Premium updates released!</code>"
        await update.message.reply_text(UI.box("Broadcast System", body), parse_mode=ParseMode.HTML)
        return
    
    message = " ".join(context.args)
    users = db.get_all_user_ids()
    
    await update.message.reply_text(f"📡 <b>Initiating broadcast to {len(users)} users...</b>", parse_mode=ParseMode.HTML)
    
    sent = 0
    failed = 0
    
    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=UI.box("Notification Alert", message),
                parse_mode=ParseMode.HTML
            )
            sent += 1
            time.sleep(0.05)  # Rate limiting
        except Exception as e:
            failed += 1
            logging.warning(f"Broadcast failed for {uid}: {e}")
    
    db.log_broadcast(update.effective_user.id, message, sent, failed)
    
    body = (
        f"✅ <b>Broadcast complete!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>Sent:</b> <code>{sent} users</code>\n"
        f"🔴 <b>Failed:</b> <code>{failed} users</code>\n"
        f"👥 <b>Target Pool:</b> <code>{len(users)} users</code>"
    )
    await update.message.reply_text(
        UI.box("Broadcast Audit Result", body),
        parse_mode=ParseMode.HTML
    )


# Lightweight, non-blocking HTTP health check server for Render Web Services
def run_health_check_server(port):
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/health"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(404)
                self.end_headers()
                
        def log_message(self, format, *args):
            pass
            
    def start_listening():
        try:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as httpd:
                logging.info(f"Render health check helper server listening on port {port}")
                httpd.serve_forever()
        except Exception as e:
            logging.error(f"Health server failed: {e}")
            
    t = threading.Thread(target=start_listening, daemon=True)
    t.start()


# ================================================================================
# MAIN APPLICATION ENTRY POINT
# ================================================================================

def main():
    """Initialize and start the bot."""
    # Logging Setup
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Start health check server for Render
    run_health_check_server(PORT)
    
    logging.info("===== TEMP MAIL BOT - ULTIMATE EDITION =====")
    logging.info(f"Admins configured: {len(ADMIN_IDS)}")
    logging.info(f"Force channels in DB: {len(db.get_force_channel_ids())}")
    
    # Build Application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # User Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("inbox", inbox_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("mystats", mystats_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("newemail", new_email_command))
    
    # Read Message Handler (/read_<id>)
    app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/read_'), read_command))
    
    # Reply Keyboard Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_keyboard_handler))
    
    # Admin Command Handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("createpass", admin_createpass))
    app.add_handler(CommandHandler("listpass", admin_listpass))
    app.add_handler(CommandHandler("delpass", admin_delpass))
    app.add_handler(CommandHandler("passinfo", admin_passinfo))
    app.add_handler(CommandHandler("addchannel", admin_addchannel))
    app.add_handler(CommandHandler("removechannel", admin_removechannel))
    app.add_handler(CommandHandler("listchannels", admin_listchannels))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("userinfo", admin_userinfo))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("adminlogs", admin_logs))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    
    # Callback Query Handler
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Set Bot Commands
    async def set_commands(app):
        await app.bot.set_my_commands([
            BotCommand("start", "Start & get temp email"),
            BotCommand("inbox", "Check your inbox"),
            BotCommand("daily", "Daily check-in bonus"),
            BotCommand("referral", "Get referral link"),
            BotCommand("redeem", "Redeem a pass code"),
            BotCommand("balance", "Check your credits"),
            BotCommand("mystats", "Your statistics"),
            BotCommand("leaderboard", "Top users leaderboard"),
            BotCommand("newemail", "Generate new email"),
            BotCommand("help", "Help and commands"),
        ])
        logging.info("Bot commands registered")
    
    app.post_init = set_commands
    
    # Start Polling
    logging.info("Bot is live and ready!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()