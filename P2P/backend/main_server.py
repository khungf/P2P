import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

app = FastAPI(title="P2P SOS Rescue API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TRAVEL_SECONDS = 90
REAL_MODE_MIN_DISTANCE_M = 100
SPEED_MPS = 7.0
ACTIVE_STATUSES = ["PENDING", "WAITING_APPROVAL", "CHATTING", "NEGOTIATING", "ARRIVED"]
BUSY_STATUSES = ["WAITING_APPROVAL", "CHATTING", "NEGOTIATING", "ARRIVED"]
OFFER_SECONDS = 20
HELPER_ONLINE_SECONDS = 30


class RegisterRequest(BaseModel):
    full_name: str
    birth_date: str
    phone: str
    email: Optional[str] = None
    cccd: str
    city: str = "TP. Hồ Chí Minh"
    vehicle_type: str = "Xe máy"
    license_plate: str
    services: List[str] = []
    password: str
    avatar_image: Optional[str] = None
    cccd_image: Optional[str] = None
    license_image: Optional[str] = None
    agreed_terms: bool = False


class LoginRequest(BaseModel):
    phone: str
    password: str


class UploadRequest(BaseModel):
    kind: str            # avatar | cccd | license
    filename: str = ""
    data_base64: str


class AccountStatusRequest(BaseModel):
    status: str          # APPROVED | REJECTED | PENDING_REVIEW


class StatusUpdate(BaseModel):
    is_active: bool


class SOSCreateRequest(BaseModel):
    customer_phone: str = "0901234567"
    condition: str
    price: float = 50000.0
    lat: float = 10.762622
    lng: float = 106.660172


class PriceActionRequest(BaseModel):
    order_id: int
    action: str


class NewPriceOfferRequest(BaseModel):
    order_id: int
    new_proposed_price: float


class SendMessageRequest(BaseModel):
    order_id: int
    sender: str
    message: str


class CancelOrderRequest(BaseModel):
    order_id: int
    reason: str


class AcceptOrderRequest(BaseModel):
    order_id: int
    proposed_price: float
    helper_name: str = "ĐỖ KHÁNH HÙNG"


class LocationUpdate(BaseModel):
    order_id: int
    role: str
    lat: float
    lng: float
    source: str = "gps"


class HelperSettings(BaseModel):
    helper_name: str
    radius_km: float = 5.0
    auto_accept: bool = False


class HelperHeartbeat(BaseModel):
    helper_name: str
    lat: float
    lng: float
    is_active: bool = True


class OfferResponse(BaseModel):
    order_id: int
    helper_name: str
    action: str
    proposed_price: Optional[float] = None


current_shipper_status = {
    "shipper_name": "ĐỖ KHÁNH HÙNG",
    "is_active": False
}

rescue_orders_db = []
helpers_db = {}
accounts_db = {}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def public_account(account):
    return {k: v for k, v in account.items() if k not in ("salt", "password_hash")}


def _seed_demo_account():
    salt = os.urandom(16)
    accounts_db["0901234567"] = {
        "full_name": "ĐỖ KHÁNH HÙNG", "phone": "0901234567", "city": "TP. Hồ Chí Minh",
        "status": "APPROVED", "created_at": time.time(),
        "salt": salt.hex(), "password_hash": hash_password("123456", salt),
    }


def get_helper(name):
    if name not in helpers_db:
        helpers_db[name] = {
            "name": name, "is_active": False, "lat": None, "lng": None,
            "radius_km": 5.0, "auto_accept": False, "last_seen": 0.0,
        }
    return helpers_db[name]


# =====================================================================
# LƯU TRỮ BỀN VỮNG (SQLite) + THƯ MỤC ẢNH
#   - P2P_DB_PATH     : đường dẫn file database (mặc định: p2p_data.db cạnh file này)
#   - P2P_UPLOAD_DIR  : thư mục lưu ảnh hồ sơ  (mặc định: private_uploads cạnh file này)
#   - P2P_ADMIN_KEY   : mật khẩu quản trị để xem ảnh / duyệt hồ sơ (bắt buộc đặt mới dùng được)
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("P2P_DB_PATH", str(BASE_DIR / "p2p_data.db"))
UPLOAD_DIR = Path(os.environ.get("P2P_UPLOAD_DIR", str(BASE_DIR / "private_uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ADMIN_KEY = os.environ.get("P2P_ADMIN_KEY", "")

TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "EXPIRED")

_db_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
try:
    _db.execute("PRAGMA journal_mode=WAL")
except sqlite3.DatabaseError:
    pass
_db.execute(
    "CREATE TABLE IF NOT EXISTS docs ("
    "kind TEXT NOT NULL, key TEXT NOT NULL, doc TEXT NOT NULL, updated_at REAL NOT NULL, "
    "PRIMARY KEY (kind, key))"
)
_db.commit()

_saved_docs = {}        # (kind, key) -> chuỗi JSON đã ghi gần nhất
_final_orders = set()   # id các đơn đã kết thúc và đã lưu xong, khỏi kiểm tra lại


def _to_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def load_state():
    """Nạp tài khoản, đơn hàng và cài đặt của thợ từ database khi server khởi động."""
    with _db_lock:
        rows = _db.execute("SELECT kind, key, doc FROM docs").fetchall()
    orders = []
    for kind, key, doc in rows:
        data = json.loads(doc)
        _saved_docs[(kind, key)] = doc
        if kind == "account":
            accounts_db[key] = data
        elif kind == "order":
            orders.append(data)
            if data.get("status") in TERMINAL_STATUSES:
                _final_orders.add(key)
        elif kind == "helper":
            h = get_helper(key)
            h["radius_km"] = data.get("radius_km", 5.0)
            h["auto_accept"] = data.get("auto_accept", False)
    orders.sort(key=lambda o: o["id"])
    rescue_orders_db.extend(orders)


def persist_changes():
    """Ghi xuống database những gì đã thay đổi kể từ lần ghi trước."""
    with _db_lock:
        docs = []
        for phone, acc in list(accounts_db.items()):
            docs.append(("account", phone, acc))
        for o in list(rescue_orders_db):
            if str(o["id"]) in _final_orders:
                continue
            docs.append(("order", str(o["id"]), o))
        for name, h in list(helpers_db.items()):
            docs.append(("helper", name, {"radius_km": h["radius_km"], "auto_accept": h["auto_accept"]}))

        pending = []
        for kind, key, obj in docs:
            doc = _to_json(obj)
            if _saved_docs.get((kind, key)) != doc:
                pending.append((kind, key, doc, obj))
        if not pending:
            return

        now = time.time()
        with _db:
            _db.executemany(
                "INSERT INTO docs (kind, key, doc, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(kind, key) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at",
                [(k, key, d, now) for k, key, d, _ in pending],
            )
        for k, key, d, obj in pending:
            _saved_docs[(k, key)] = d
            if k == "order" and obj.get("status") in TERMINAL_STATUSES:
                _final_orders.add(key)


def cleanup_orphan_uploads(max_age_seconds=24 * 3600):
    """Xóa ảnh đã tải lên nhưng không gắn với hồ sơ nào sau 24 giờ (tránh đầy ổ đĩa)."""
    used = set()
    for acc in list(accounts_db.values()):
        for k in ("avatar_image", "cccd_image", "license_image"):
            if acc.get(k):
                used.add(acc[k])
    now = time.time()
    try:
        for f in UPLOAD_DIR.iterdir():
            if f.is_file() and f.name not in used and now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
    except OSError:
        pass


load_state()
if "0901234567" not in accounts_db:
    _seed_demo_account()
persist_changes()
cleanup_orphan_uploads()


@app.middleware("http")
async def persist_after_request(request: Request, call_next):
    response = await call_next(request)
    try:
        await run_in_threadpool(persist_changes)
    except Exception as ex:  # nếu lỡ trùng lúc dữ liệu đang đổi, lần gọi sau sẽ ghi lại
        print("Cảnh báo: chưa ghi được database:", repr(ex))
    return response


@app.on_event("shutdown")
def save_on_shutdown():
    try:
        persist_changes()
    except Exception as ex:
        print("Cảnh báo: chưa ghi được database khi tắt server:", repr(ex))


def helper_approved(name):
    """Thợ chỉ được hoạt động / nhận đơn khi hồ sơ (cùng tên) đã được duyệt."""
    return any(
        (a.get("full_name") or "").upper() == name and a.get("status") == "APPROVED"
        for a in accounts_db.values()
    )


def helper_phones(name):
    """Các số điện thoại thuộc tài khoản có tên thợ này (để thợ không nhận đơn do chính mình tạo)."""
    return {
        a.get("phone") for a in accounts_db.values()
        if (a.get("full_name") or "").upper() == name
    }


def helper_online(h):
    return h["is_active"] and h["lat"] is not None and (time.time() - h["last_seen"]) <= HELPER_ONLINE_SECONDS


def helper_is_busy(name):
    return any(o.get("helper_name") == name and o["status"] in BUSY_STATUSES for o in rescue_orders_db)


def check_expired_orders():
    now = time.time()
    for order in rescue_orders_db:
        if order["status"] == "PENDING" and (now - order["created_at"]) > 900:
            order["status"] = "EXPIRED"


def distance_m(lat1, lng1, lat2, lng2):
    dy = (lat2 - lat1) * 111320
    dx = (lng2 - lng1) * 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def update_helper_position(order):
    status = order["status"]
    if status not in ("NEGOTIATING", "ARRIVED"):
        return

    if order.get("use_real_helper"):
        d = distance_m(order["helper_lat"], order["helper_lng"], order["lat"], order["lng"])
        initial = max(order.get("initial_distance_m") or d, 1.0)
        if status == "ARRIVED":
            order["progress"], order["distance_m"], order["eta_seconds"] = 1.0, 0.0, 0
        else:
            order["progress"] = max(0.0, min(1.0, 1 - d / initial))
            order["distance_m"] = d
            order["eta_seconds"] = int(d / SPEED_MPS)
        return

    if status == "ARRIVED":
        progress = 1.0
    else:
        started = order.get("accepted_at") or time.time()
        progress = min(1.0, (time.time() - started) / TRAVEL_SECONDS)

    s_lat, s_lng = order["helper_start_lat"], order["helper_start_lng"]
    order["progress"] = progress
    order["helper_lat"] = s_lat + (order["lat"] - s_lat) * progress
    order["helper_lng"] = s_lng + (order["lng"] - s_lng) * progress
    order["distance_m"] = distance_m(order["helper_lat"], order["helper_lng"], order["lat"], order["lng"])
    order["eta_seconds"] = int(TRAVEL_SECONDS * (1 - progress))


def dispatch_offers():
    check_expired_orders()
    now = time.time()
    for order in rescue_orders_db:
        if order["status"] != "PENDING":
            order["offered_to"] = None
            continue

        if order.get("offered_to") and now > (order.get("offer_expires_at") or 0):
            order["declined_by"].append(order["offered_to"])
            order["offered_to"] = None

        if order.get("offered_to"):
            h = helpers_db.get(order["offered_to"])
            if h and helper_online(h) and not helper_is_busy(h["name"]):
                continue
            order["offered_to"] = None

        best, best_d = None, None
        for h in helpers_db.values():
            if not (helper_online(h) and h["auto_accept"]):
                continue
            if h["name"] in order["declined_by"] or helper_is_busy(h["name"]):
                continue
            if order["customer_phone"] in helper_phones(h["name"]):
                continue
            d = distance_m(h["lat"], h["lng"], order["lat"], order["lng"])
            if d > h["radius_km"] * 1000:
                continue
            if best is None or d < best_d:
                best, best_d = h, d
        if best:
            order["offered_to"] = best["name"]
            order["offer_expires_at"] = now + OFFER_SECONDS


@app.get("/")
def read_root():
    return {"message": "P2P SOS API Server is running!"}


@app.get("/api/shipper/status")
def get_status():
    return current_shipper_status


@app.post("/api/shipper/status")
def update_status(data: StatusUpdate):
    current_shipper_status["is_active"] = data.is_active
    return {"success": True}


@app.post("/api/sos/create")
def create_sos(data: SOSCreateRequest):
    check_expired_orders()
    for order in rescue_orders_db:
        if order["customer_phone"] == data.customer_phone and order["status"] in ACTIVE_STATUSES:
            raise HTTPException(status_code=400, detail="Bạn đang có một đơn SOS chưa hoàn thành!")

    start_lat = data.lat + 0.006
    start_lng = data.lng - 0.008
    new_order = {
        "id": len(rescue_orders_db) + 1,
        "customer_phone": data.customer_phone,
        "condition": data.condition,
        "price": data.price,
        "lat": data.lat,
        "lng": data.lng,
        "status": "PENDING",
        "helper_name": None,
        "proposed_price": None,
        "created_at": time.time(),
        "accepted_at": None,
        "helper_start_lat": start_lat,
        "helper_start_lng": start_lng,
        "helper_lat": start_lat,
        "helper_lng": start_lng,
        "progress": 0.0,
        "distance_m": distance_m(start_lat, start_lng, data.lat, data.lng),
        "eta_seconds": TRAVEL_SECONDS,
        "cancel_reason": None,
        "offered_to": None,
        "offer_expires_at": None,
        "declined_by": [],
        "use_real_helper": None,
        "initial_distance_m": None,
        "helper_live_at": None,
        "helper_source": None,
        "customer_source": None,
        "messages": []
    }
    rescue_orders_db.append(new_order)
    return {"success": True, "data": new_order}


@app.post("/api/location/update")
def update_location(data: LocationUpdate):
    for order in rescue_orders_db:
        if order["id"] != data.order_id:
            continue
        if data.role == "customer":
            if order["status"] in ACTIVE_STATUSES:
                order["lat"], order["lng"] = data.lat, data.lng
                order["customer_source"] = data.source
        elif data.role == "helper":
            if order["status"] in ("NEGOTIATING", "ARRIVED"):
                order["helper_source"] = data.source
                order["helper_live_at"] = time.time()
                if order.get("use_real_helper") is None:
                    d = distance_m(data.lat, data.lng, order["lat"], order["lng"])
                    if d > REAL_MODE_MIN_DISTANCE_M:
                        order["use_real_helper"] = True
                        order["initial_distance_m"] = d
                    else:
                        order["use_real_helper"] = False
                if order["use_real_helper"]:
                    order["helper_lat"], order["helper_lng"] = data.lat, data.lng
        else:
            raise HTTPException(status_code=400, detail="role phải là customer hoặc helper")
        update_helper_position(order)
        return {"success": True, "data": order}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.get("/api/helper/settings/{helper_name}")
def get_helper_settings(helper_name: str):
    h = get_helper(helper_name)
    return {"success": True, "data": {"radius_km": h["radius_km"], "auto_accept": h["auto_accept"]}}


@app.post("/api/helper/settings")
def save_helper_settings(data: HelperSettings):
    h = get_helper(data.helper_name)
    h["radius_km"] = max(0.5, min(50.0, data.radius_km))
    h["auto_accept"] = data.auto_accept
    return {"success": True, "data": {"radius_km": h["radius_km"], "auto_accept": h["auto_accept"]}}


@app.post("/api/helper/heartbeat")
def helper_heartbeat(data: HelperHeartbeat):
    h = get_helper(data.helper_name)
    approved = helper_approved(data.helper_name)
    h["lat"], h["lng"] = data.lat, data.lng
    h["is_active"] = bool(data.is_active and approved)
    h["last_seen"] = time.time()
    return {"success": True, "approved": approved}


@app.get("/api/rescue/offer/{helper_name}")
def get_offer(helper_name: str):
    dispatch_offers()
    h = helpers_db.get(helper_name)
    now = time.time()
    for o in rescue_orders_db:
        if o["status"] == "PENDING" and o.get("offered_to") == helper_name:
            item = dict(o)
            item["seconds_left"] = max(0, int(o["offer_expires_at"] - now))
            if h and h["lat"] is not None:
                item["distance_km"] = distance_m(h["lat"], h["lng"], o["lat"], o["lng"]) / 1000
            return {"success": True, "data": item}
    return {"success": True, "data": None}


@app.post("/api/rescue/offer-response")
def offer_response(data: OfferResponse):
    for order in rescue_orders_db:
        if order["id"] != data.order_id:
            continue
        if order["status"] != "PENDING" or order.get("offered_to") != data.helper_name:
            raise HTTPException(status_code=400, detail="Đơn này không còn được giao cho bạn!")
        if data.action == "accept":
            if not helper_approved(data.helper_name):
                raise HTTPException(status_code=403, detail="Hồ sơ của bạn chưa được duyệt nên chưa thể nhận đơn!")
            if order["customer_phone"] in helper_phones(data.helper_name):
                raise HTTPException(status_code=403, detail="Bạn không thể nhận đơn do chính mình tạo!")
            price = data.proposed_price if data.proposed_price and data.proposed_price > 0 else order["price"]
            order["status"] = "WAITING_APPROVAL"
            order["helper_name"] = data.helper_name
            order["proposed_price"] = price
            order["offered_to"] = None
            return {"success": True, "message": "Đã gửi đề nghị giá đến khách, chờ khách xác nhận.", "data": order}
        order["declined_by"].append(data.helper_name)
        order["offered_to"] = None
        dispatch_offers()
        return {"success": True, "message": "Đã từ chối đơn."}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.get("/api/rescue/pending")
def get_pending_requests(helper_name: str = None):
    check_expired_orders()
    if helper_name and not helper_approved(helper_name):
        return {"success": True, "data": []}
    h = helpers_db.get(helper_name) if helper_name else None
    pending = []
    own_phones = helper_phones(helper_name) if helper_name else set()
    for r in rescue_orders_db:
        if r["status"] != "PENDING":
            continue
        if r["customer_phone"] in own_phones:
            continue
        item = dict(r)
        if h and h["lat"] is not None:
            d = distance_m(h["lat"], h["lng"], r["lat"], r["lng"])
            if d > h["radius_km"] * 1000:
                continue
            item["distance_km"] = d / 1000
        pending.append(item)
    return {"success": True, "data": pending}


@app.post("/api/rescue/accept")
def helper_accept_order(data: AcceptOrderRequest):
    check_expired_orders()
    for order in rescue_orders_db:
        if order["id"] == data.order_id:
            if not helper_approved(data.helper_name):
                raise HTTPException(status_code=403, detail="Hồ sơ của bạn chưa được duyệt nên chưa thể nhận đơn!")
            if order["customer_phone"] in helper_phones(data.helper_name):
                raise HTTPException(status_code=403, detail="Bạn không thể nhận đơn do chính mình tạo!")
            if order["status"] != "PENDING":
                raise HTTPException(status_code=400, detail="Đơn này không còn ở trạng thái chờ!")

            order["status"] = "WAITING_APPROVAL"
            order["helper_name"] = data.helper_name
            order["proposed_price"] = data.proposed_price
            return {"success": True, "message": "Đã gửi đề xuất giá đến khách!", "data": order}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.post("/api/sos/price-action")
def price_action(data: PriceActionRequest):
    for order in rescue_orders_db:
        if order["id"] == data.order_id:
            if data.action == "accept":
                order["status"] = "NEGOTIATING"
                order["price"] = order["proposed_price"]
                order["accepted_at"] = time.time()
                order["helper_start_lat"] = order["lat"] + 0.006
                order["helper_start_lng"] = order["lng"] - 0.008
                order["helper_lat"] = order["helper_start_lat"]
                order["helper_lng"] = order["helper_start_lng"]
                order["use_real_helper"] = None
                order["initial_distance_m"] = None
                update_helper_position(order)
                return {"success": True, "message": "Đã chốt giá!", "data": order}
            else:
                order["status"] = "CHATTING"
                return {"success": True, "message": "Chuyển sang chat thương lượng.", "data": order}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.post("/api/sos/new-price-offer")
def helper_new_price_offer(data: NewPriceOfferRequest):
    for order in rescue_orders_db:
        if order["id"] == data.order_id:
            order["proposed_price"] = data.new_proposed_price
            order["status"] = "WAITING_APPROVAL"
            return {"success": True, "message": "Đã gửi lại giá mới cho khách duyệt!", "data": order}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.post("/api/sos/chat/send")
def send_chat_message(data: SendMessageRequest):
    for order in rescue_orders_db:
        if order["id"] == data.order_id:
            order["messages"].append({"sender": data.sender, "message": data.message})
            return {"success": True, "data": order["messages"]}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.get("/api/rescue/current-helper/{helper_name}")
def get_current_helper_order(helper_name: str):
    for order in rescue_orders_db:
        if order.get("helper_name") == helper_name and order["status"] in ["NEGOTIATING", "ARRIVED"]:
            update_helper_position(order)
            return {"success": True, "data": order}
    return {"success": True, "data": None}


@app.get("/api/rescue/chatting/{helper_name}")
def get_helper_chatting_order(helper_name: str):
    """Đơn mà thợ này đã nhận và đang được khách chuyển sang chat thương lượng giá."""
    for order in reversed(rescue_orders_db):
        if order.get("helper_name") == helper_name and order["status"] == "CHATTING":
            return {"success": True, "data": order}
    return {"success": True, "data": None}


@app.post("/api/rescue/update-status")
def update_order_status(data: dict):
    order_id = data.get("order_id")
    new_status = data.get("status")
    for order in rescue_orders_db:
        if order["id"] == order_id:
            order["status"] = new_status
            update_helper_position(order)
            return {"success": True, "data": order}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.get("/api/sos/current/{phone}")
def get_current_sos(phone: str):
    check_expired_orders()
    for order in reversed(rescue_orders_db):
        if order["customer_phone"] == phone and order["status"] not in ["CANCELLED", "EXPIRED"]:
            update_helper_position(order)
            return {"success": True, "data": order}
    return {"success": True, "data": None}


@app.post("/api/sos/cancel")
def cancel_order(data: CancelOrderRequest):
    if not data.reason.strip():
        raise HTTPException(status_code=400, detail="Bắt buộc phải ghi lý do hủy đơn!")
    for order in rescue_orders_db:
        if order["id"] == data.order_id:
            order["status"] = "CANCELLED"
            order["cancel_reason"] = data.reason
            return {"success": True, "message": "Đã hủy đơn thành công."}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.post("/api/sos/complete/{order_id}")
def complete_order(order_id: int):
    for order in rescue_orders_db:
        if order["id"] == order_id:
            order["status"] = "COMPLETED"
            return {"success": True, "message": "Đơn cứu hộ đã hoàn thành!"}
    raise HTTPException(status_code=404, detail="Không tìm thấy đơn.")


@app.post("/api/auth/register")
def register_account(data: RegisterRequest):
    full_name = " ".join(data.full_name.split())
    phone = data.phone.replace(" ", "")
    cccd = data.cccd.strip()
    email = (data.email or "").strip() or None
    plate = data.license_plate.strip().upper()

    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Vui lòng nhập họ và tên!")

    try:
        born = datetime.strptime(data.birth_date.strip(), "%d/%m/%Y").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Ngày sinh phải theo định dạng DD/MM/YYYY!")
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if age < 18 or age > 80:
        raise HTTPException(status_code=400, detail="Bạn phải từ đủ 18 tuổi để đăng ký!")

    if not (phone.isdigit() and len(phone) == 10 and phone.startswith("0")):
        raise HTTPException(status_code=400, detail="Số điện thoại không hợp lệ!")
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Email không hợp lệ!")
    if not (cccd.isdigit() and len(cccd) in (9, 12)):
        raise HTTPException(status_code=400, detail="Số CCCD/CMND không hợp lệ!")
    if len(plate.replace(" ", "")) < 5:
        raise HTTPException(status_code=400, detail="Vui lòng nhập biển số xe!")
    if not data.services:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất 1 dịch vụ hỗ trợ!")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu tối thiểu 6 ký tự!")
    for file_id, kind in ((data.avatar_image, "avatar"), (data.cccd_image, "cccd"), (data.license_image, "license")):
        if (not file_id or not FILE_ID_RE.match(file_id) or not file_id.startswith(kind + "_")
                or not (UPLOAD_DIR / file_id).is_file()):
            raise HTTPException(status_code=400, detail="Ảnh hồ sơ chưa tải lên thành công, vui lòng chọn lại ảnh!")
    if not data.agreed_terms:
        raise HTTPException(status_code=400, detail="Bạn cần đồng ý Điều khoản sử dụng!")

    if phone in accounts_db:
        raise HTTPException(status_code=409, detail="Số điện thoại này đã được đăng ký!")
    if any(a.get("cccd") == cccd for a in accounts_db.values()):
        raise HTTPException(status_code=409, detail="Số CCCD/CMND này đã được đăng ký!")
    if any(a.get("license_plate") == plate for a in accounts_db.values()):
        raise HTTPException(status_code=409, detail="Biển số xe này đã được đăng ký!")
    if email and any(a.get("email") == email for a in accounts_db.values()):
        raise HTTPException(status_code=409, detail="Email này đã được đăng ký!")

    salt = os.urandom(16)
    account = {
        "full_name": full_name,
        "birth_date": data.birth_date.strip(),
        "phone": phone,
        "email": email,
        "cccd": cccd,
        "city": data.city,
        "vehicle_type": data.vehicle_type,
        "license_plate": plate,
        "services": data.services,
        "avatar_image": data.avatar_image,
        "cccd_image": data.cccd_image,
        "license_image": data.license_image,
        "salt": salt.hex(),
        "password_hash": hash_password(data.password, salt),
        "status": "PENDING_REVIEW",
        "created_at": time.time(),
    }
    accounts_db[phone] = account
    get_helper(full_name.upper())
    return {"success": True, "message": "Đã nhận hồ sơ, đang chờ xét duyệt.", "data": public_account(account)}


@app.post("/api/auth/login")
def login_account(data: LoginRequest):
    phone = data.phone.replace(" ", "")
    account = accounts_db.get(phone)
    if not account:
        raise HTTPException(status_code=404, detail="Số điện thoại chưa đăng ký tài khoản!")
    actual = hash_password(data.password, bytes.fromhex(account["salt"]))
    if not hmac.compare_digest(actual, account["password_hash"]):
        raise HTTPException(status_code=401, detail="Sai mật khẩu!")
    if account.get("status") == "REJECTED":
        raise HTTPException(status_code=403, detail="Hồ sơ của bạn chưa được chấp nhận. Vui lòng liên hệ hỗ trợ!")
    return {"success": True, "data": public_account(account)}


@app.get("/api/auth/status/{phone}")
def get_account_status(phone: str):
    account = accounts_db.get(phone.replace(" ", ""))
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    return {"success": True, "data": {"status": account.get("status", "PENDING_REVIEW")}}


# ---------------- Tải ảnh hồ sơ ----------------
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
UPLOAD_KINDS = ("avatar", "cccd", "license")
FILE_ID_RE = re.compile(r"^(avatar|cccd|license)_[0-9a-f]{32}\.(jpg|png|webp|heic)$")


def detect_image_ext(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[4:8] == b"ftyp" and raw[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
        return "heic"
    return None


@app.post("/api/upload")
def upload_image(data: UploadRequest):
    if data.kind not in UPLOAD_KINDS:
        raise HTTPException(status_code=400, detail="Loại ảnh không hợp lệ!")
    if len(data.data_base64) > MAX_UPLOAD_BYTES * 4 // 3 + 16:
        raise HTTPException(status_code=413, detail="Ảnh quá lớn (tối đa 8MB)!")
    try:
        raw = base64.b64decode(data.data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Dữ liệu ảnh không hợp lệ!")
    if not raw:
        raise HTTPException(status_code=400, detail="File ảnh rỗng!")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Ảnh quá lớn (tối đa 8MB)!")
    ext = detect_image_ext(raw)
    if not ext:
        raise HTTPException(status_code=400, detail="Chỉ nhận ảnh JPG, PNG, WEBP hoặc HEIC!")

    file_id = f"{data.kind}_{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / file_id).write_bytes(raw)
    cleanup_orphan_uploads()
    return {"success": True, "file_id": file_id, "size": len(raw)}


# ---------------- Quản trị: xem hồ sơ, xem ảnh, duyệt / từ chối ----------------
# Trang web quản trị: mở http://127.0.0.1:8000/admin rồi nhập khóa P2P_ADMIN_KEY
ADMIN_PAGE_HTML = r'''<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>P2P SOS - Duyệt hồ sơ</title>
<style>
  :root { --bg:#f4f5f7; --card:#fff; --text:#212529; --muted:#6c757d; --line:#dee2e6; --brand:#ee4d2d; --ok:#198754; --bad:#dc3545; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16181b; --card:#212529; --text:#f1f3f5; --muted:#adb5bd; --line:#343a40; }
  }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, "Segoe UI", Roboto, Arial, sans-serif; background:var(--bg); color:var(--text); }
  header { background:var(--brand); color:#fff; padding:14px 20px; font-weight:700; font-size:18px; }
  main { max-width:1000px; margin:0 auto; padding:16px; }
  .bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:14px; }
  input, select, button { font:inherit; padding:8px 10px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--text); }
  button { cursor:pointer; }
  button.primary { background:var(--brand); color:#fff; border-color:var(--brand); }
  button.ok { background:var(--ok); color:#fff; border-color:var(--ok); }
  button.bad { background:var(--bad); color:#fff; border-color:var(--bad); }
  .msg { color:var(--muted); margin:8px 0; }
  .msg.err { color:var(--bad); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; }
  .card h3 { margin:0 0 6px; font-size:17px; }
  .badge { display:inline-block; padding:2px 8px; border-radius:20px; font-size:12px; font-weight:600; color:#fff; }
  .PENDING_REVIEW { background:#f59f00; } .APPROVED { background:var(--ok); } .REJECTED { background:var(--bad); }
  dl { display:grid; grid-template-columns:130px 1fr; gap:4px 12px; margin:10px 0; }
  dt { color:var(--muted); } dd { margin:0; word-break:break-word; }
  .imgs { display:flex; flex-wrap:wrap; gap:10px; margin:10px 0; }
  .imgs figure { margin:0; text-align:center; font-size:12px; color:var(--muted); }
  .imgs img { width:220px; max-width:100%; height:160px; object-fit:cover; border-radius:8px; border:1px solid var(--line); cursor:zoom-in; background:rgba(128,128,128,.15); }
  .actions { display:flex; flex-wrap:wrap; gap:8px; }
</style>
</head>
<body>
<header>P2P SOS · Duyệt hồ sơ đối tác</header>
<main>
  <div class="bar">
    <input id="key" type="password" placeholder="Khóa quản trị (P2P_ADMIN_KEY)" size="28">
    <select id="filter">
      <option value="PENDING_REVIEW">Chờ duyệt</option>
      <option value="APPROVED">Đã duyệt</option>
      <option value="REJECTED">Đã từ chối</option>
      <option value="">Tất cả</option>
    </select>
    <button class="primary" id="load">Tải danh sách</button>
  </div>
  <div id="msg" class="msg">Nhập khóa quản trị rồi bấm "Tải danh sách".</div>
  <div id="list"></div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const LABEL = { PENDING_REVIEW: "Chờ duyệt", APPROVED: "Đã duyệt", REJECTED: "Đã từ chối" };
let KEY = "";
try { KEY = sessionStorage.getItem("p2p_admin_key") || ""; } catch (e) {}
$("key").value = KEY;

function el(tag, props, kids) {
  const n = document.createElement(tag);
  Object.keys(props || {}).forEach((k) => {
    if (k === "text") n.textContent = props[k];
    else if (k === "class") n.className = props[k];
    else if (k === "onclick") n.onclick = props[k];
    else n.setAttribute(k, props[k]);
  });
  (kids || []).forEach((c) => n.appendChild(c));
  return n;
}
function say(text, isErr) { const m = $("msg"); m.textContent = text; m.className = "msg" + (isErr ? " err" : ""); }

async function call(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign({ "X-Admin-Key": KEY, "Content-Type": "application/json" }, opts.headers || {});
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error((body && body.detail) || ("Lỗi " + res.status));
  return body;
}

function imgFigure(phone, kind, title) {
  const src = "/api/admin/accounts/" + encodeURIComponent(phone) + "/image/" + kind + "?key=" + encodeURIComponent(KEY);
  const img = el("img", { src: src, alt: title, loading: "lazy" });
  img.onclick = () => window.open(src, "_blank");
  return el("figure", {}, [img, el("div", { text: title })]);
}

function row(dl, label, value) {
  dl.appendChild(el("dt", { text: label }));
  dl.appendChild(el("dd", { text: value || "—" }));
}

async function setStatus(phone, status) {
  try {
    await call("/api/admin/accounts/" + encodeURIComponent(phone) + "/status", { method: "POST", body: JSON.stringify({ status: status }) });
    await load(true);
    say("Đã cập nhật " + phone + " → " + LABEL[status]);
  } catch (e) { say(e.message, true); }
}

function card(a) {
  const dl = el("dl");
  row(dl, "Số điện thoại", a.phone);
  row(dl, "Ngày sinh", a.birth_date);
  row(dl, "CCCD/CMND", a.cccd);
  row(dl, "Email", a.email);
  row(dl, "Loại xe", a.vehicle_type);
  row(dl, "Biển số", a.license_plate);
  row(dl, "Khu vực", a.city);
  row(dl, "Dịch vụ", (a.services || []).join(", "));
  row(dl, "Gửi lúc", a.created_at ? new Date(a.created_at * 1000).toLocaleString("vi-VN") : "");

  const imgs = el("div", { class: "imgs" });
  if (a.avatar_image) imgs.appendChild(imgFigure(a.phone, "avatar", "Ảnh chân dung"));
  if (a.cccd_image) imgs.appendChild(imgFigure(a.phone, "cccd", "CCCD / CMND"));
  if (a.license_image) imgs.appendChild(imgFigure(a.phone, "license", "Bằng lái / Cà vẹt"));

  const actions = el("div", { class: "actions" }, [
    el("button", { class: "ok", text: "Duyệt", onclick: () => setStatus(a.phone, "APPROVED") }),
    el("button", { class: "bad", text: "Từ chối", onclick: () => setStatus(a.phone, "REJECTED") }),
    el("button", { text: "Đưa về chờ duyệt", onclick: () => setStatus(a.phone, "PENDING_REVIEW") }),
  ]);

  const head = el("h3", { text: a.full_name || a.phone });
  const badge = el("span", { class: "badge " + a.status, text: LABEL[a.status] || a.status });
  return el("div", { class: "card" }, [head, badge, dl, imgs, actions]);
}

async function load(keepMsg) {
  KEY = $("key").value.trim();
  try { sessionStorage.setItem("p2p_admin_key", KEY); } catch (e) {}
  const status = $("filter").value;
  try {
    const body = await call("/api/admin/accounts" + (status ? "?status=" + encodeURIComponent(status) : ""));
    const list = $("list");
    list.textContent = "";
    body.data.forEach((a) => list.appendChild(card(a)));
    if (!keepMsg) say(body.data.length ? ("Có " + body.data.length + " hồ sơ.") : "Không có hồ sơ nào.");
  } catch (e) { $("list").textContent = ""; say(e.message, true); }
}
$("load").onclick = () => load(false);
$("filter").onchange = () => load(false);
if (KEY) load(false);
</script>
</body>
</html>
'''


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return HTMLResponse(ADMIN_PAGE_HTML)


def require_admin(header_key, query_key=None):
    if not ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Server chưa cấu hình biến môi trường P2P_ADMIN_KEY.")
    given = header_key or query_key or ""
    if not hmac.compare_digest(given.encode("utf-8"), ADMIN_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Sai khóa quản trị!")


@app.get("/api/admin/accounts")
def admin_list_accounts(status: Optional[str] = None, key: Optional[str] = None,
                        x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key, key)
    items = [public_account(a) for a in accounts_db.values() if not status or a.get("status") == status]
    items.sort(key=lambda a: a.get("created_at", 0), reverse=True)
    return {"success": True, "data": items}


@app.get("/api/admin/accounts/{phone}/image/{kind}")
def admin_get_image(phone: str, kind: str, key: Optional[str] = None,
                    x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key, key)
    account = accounts_db.get(phone)
    field = {"avatar": "avatar_image", "cccd": "cccd_image", "license": "license_image"}.get(kind)
    if not account or not field or not account.get(field):
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    file_id = account[field]
    if not FILE_ID_RE.match(file_id) or not (UPLOAD_DIR / file_id).is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    return FileResponse(UPLOAD_DIR / file_id)


@app.post("/api/admin/accounts/{phone}/status")
def admin_set_account_status(phone: str, data: AccountStatusRequest, key: Optional[str] = None,
                             x_admin_key: Optional[str] = Header(None)):
    require_admin(x_admin_key, key)
    if data.status not in ("APPROVED", "REJECTED", "PENDING_REVIEW"):
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ!")
    account = accounts_db.get(phone)
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    account["status"] = data.status
    return {"success": True, "data": public_account(account)}


if __name__ == "__main__":
    import uvicorn
    _port_env = os.environ.get("PORT")
    if _port_env:  # chạy trên máy chủ (hosting): mở ra ngoài, không bật reload
        uvicorn.run("main_server:app", host="0.0.0.0", port=int(_port_env))
    else:          # chạy ở máy cá nhân như cũ
        uvicorn.run("main_server:app", host="127.0.0.1", port=8000, reload=True)