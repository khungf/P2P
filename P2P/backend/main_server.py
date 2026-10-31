import math
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


def get_helper(name):
    if name not in helpers_db:
        helpers_db[name] = {
            "name": name, "is_active": False, "lat": None, "lng": None,
            "radius_km": 5.0, "auto_accept": False, "last_seen": 0.0,
        }
    return helpers_db[name]


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
    h["lat"], h["lng"] = data.lat, data.lng
    h["is_active"] = data.is_active
    h["last_seen"] = time.time()
    return {"success": True}


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
    h = helpers_db.get(helper_name) if helper_name else None
    pending = []
    for r in rescue_orders_db:
        if r["status"] != "PENDING":
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_server:app", host="127.0.0.1", port=8000, reload=True)