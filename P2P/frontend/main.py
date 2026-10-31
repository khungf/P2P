import math
import os
import threading
import time

import flet as ft
import requests

BACKEND_URL = "https://p2p-ati8.onrender.com"
CUSTOMER_PHONE = "0901234567"
HELPER_NAME = "ĐỖ KHÁNH HÙNG"
TIMEOUT = 5
POLL_INTERVAL = 1


def extract_order(res_data):
    if isinstance(res_data, dict):
        return res_data.get("data") or res_data.get("order") or (res_data if "status" in res_data else None)
    return None


def main(page: ft.Page):
    page.title = "P2P SOS - Cứu Hộ Giao Thông"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 0
    page.bgcolor = "#F8F9FA"
    page.window_width = 400
    page.window_height = 800

    is_active = False
    current_tab = "GOI_CUU_HO"
    last_sig = {"customer": None, "helper": None}

    status_switch = ft.Ref[ft.Switch]()
    bottom_container = ft.Ref[ft.Container]()

    content_column = ft.Column(expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    txt_status_header = ft.Text("Tạm nghỉ", size=13, color=ft.colors.GREY_700)

    txt_condition = ft.TextField(
        label="Mô tả sự cố (VD: Hết xăng, thủng lốp...)",
        border_radius=10,
        focused_border_color="#EE4D2D",
        prefix_icon=ft.icons.WARNING_AMBER_ROUNDED,
        expand=True
    )
    txt_price = ft.TextField(
        label="Giá đề xuất ban đầu (VNĐ)",
        value="50000",
        keyboard_type=ft.KeyboardType.NUMBER,
        border_radius=10,
        focused_border_color="#EE4D2D",
        prefix_icon=ft.icons.ATTACH_MONEY,
        expand=True
    )
    txt_cancel_reason = ft.TextField(label="Lý do hủy đơn", border_radius=10, expand=True)
    txt_chat_input = ft.TextField(
        hint_text="Nhập thông tin...",
        border_radius=20,
        border_color=ft.colors.GREY_400,
        focused_border_color="#EE4D2D",
        content_padding=ft.padding.symmetric(horizontal=15, vertical=10),
        expand=True
    )

    rescue_orders_list = ft.ListView(expand=1, spacing=12, padding=10)
    txt_slider_label = ft.Text("Sẵn sàng hoạt động", size=15, color=ft.colors.WHITE, weight=ft.FontWeight.BOLD)

    tab_goi_cuu_ho = ft.Container(
        content=ft.Text("GỌI CỨU HỘ", weight=ft.FontWeight.BOLD, color=ft.colors.GREY_800),
        alignment=ft.alignment.center, expand=True, padding=14,
        border=ft.border.only(bottom=ft.BorderSide(3, "#EE4D2D"))
    )
    tab_di_cuu_ho = ft.Container(
        content=ft.Text("ĐI CỨU HỘ", weight=ft.FontWeight.BOLD, color=ft.colors.GREY_800),
        alignment=ft.alignment.center, expand=True, padding=14
    )

    def show_snack(text):
        page.snack_bar = ft.SnackBar(ft.Text(text))
        page.snack_bar.open = True
        page.update()

    def parse_price(raw):
        cleaned = (raw or "").replace(",", "").replace(".", "").replace(" ", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            return None
        return value if value > 0 else None

    def render_resting_view():
        content_column.controls = [
            ft.Container(
                expand=True, alignment=ft.alignment.center, padding=20,
                content=ft.Column([
                    ft.Container(content=ft.Icon(ft.icons.BUILD_ROUNDED, size=60, color="#EE4D2D"), bgcolor=ft.colors.ORANGE_50, padding=25, border_radius=50),
                    ft.Container(height=20),
                    ft.Text("Bạn đang ở chế độ Tạm nghỉ", weight=ft.FontWeight.BOLD, size=18, color="#212529"),
                    ft.Container(height=8),
                    ft.Text("Bật trạng thái hoạt động ở menu hoặc trượt bên dưới để bắt đầu nhận đơn cứu hộ.", text_align=ft.TextAlign.CENTER, color=ft.colors.GREY_600, size=13),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            )
        ]

    def render_sos_form():
        content_column.controls = [
            ft.Container(
                expand=True, padding=15,
                content=ft.Card(
                    elevation=4, expand=True,
                    content=ft.Container(
                        padding=25, border_radius=15, bgcolor=ft.colors.WHITE,
                        content=ft.Column([
                            ft.Row([ft.Icon(ft.icons.SOS, color="#EE4D2D", size=32), ft.Text("PHÁT TÍN HIỆU GẶP NẠN", size=18, weight=ft.FontWeight.BOLD, color="#212529")], alignment=ft.MainAxisAlignment.START),
                            ft.Text("Hệ thống tự động định vị GPS vị trí của bạn", size=13, color=ft.colors.GREY_600),
                            ft.Container(height=20),
                            txt_condition,
                            ft.Container(height=15),
                            txt_price,
                            ft.Container(height=25),
                            ft.ElevatedButton(
                                text="PHÁT TÍN HIỆU SOS NGAY", color=ft.colors.WHITE, bgcolor="#EE4D2D", height=50,
                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)), on_click=submit_sos_request, expand=True
                            ),
                            ft.Container(height=20),
                            ft.Divider(),
                            ft.Container(height=10),
                            ft.Row([
                                ft.ElevatedButton("📞 Gọi 113", bgcolor=ft.colors.RED_600, color=ft.colors.WHITE, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)), url="tel:113", expand=True),
                                ft.Container(width=15),
                                ft.ElevatedButton("🚑 Gọi 115", bgcolor=ft.colors.BLUE_600, color=ft.colors.WHITE, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)), url="tel:115", expand=True),
                            ])
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                    )
                )
            )
        ]
        page.update()

    DEFAULT_LOCATION = (10.762622, 106.660172)
    gps_state = {"geolocator": None, "fails": 0, "permitted": False}
    ip_cache = {"pos": None, "at": 0.0}

    def setup_geolocator():
        cls = getattr(ft, "Geolocator", None)
        if cls is None:
            print("Bản Flet này không có ft.Geolocator, sẽ dùng vị trí theo IP.")
            return
        try:
            gl = cls()
            page.overlay.append(gl)
            page.update()
            gps_state["geolocator"] = gl
        except Exception as ex:
            print(f"Không khởi tạo được Geolocator: {ex}")

    def gps_location():
        gl = gps_state["geolocator"]
        if gl is None or gps_state["fails"] >= 2:
            return None
        result = {}

        def work():
            try:
                if not gps_state["permitted"]:
                    try:
                        gl.request_permission()
                    except Exception:
                        pass
                    gps_state["permitted"] = True
                pos = gl.get_current_position()
                result["pos"] = (float(pos.latitude), float(pos.longitude))
            except Exception as ex:
                result["err"] = ex

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(12)
        if "pos" in result:
            gps_state["fails"] = 0
            return result["pos"]
        gps_state["fails"] += 1
        print(f"GPS không khả dụng ({result.get('err', 'quá thời gian chờ')}), dùng vị trí theo IP.")
        return None

    def ip_location():
        if ip_cache["pos"] and time.time() - ip_cache["at"] < 600:
            return ip_cache["pos"]
        try:
            r = requests.get("http://ip-api.com/json/?fields=status,lat,lon", timeout=TIMEOUT).json()
            if r.get("status") == "success":
                ip_cache["pos"] = (float(r["lat"]), float(r["lon"]))
                ip_cache["at"] = time.time()
        except Exception as ex:
            print(f"Lỗi định vị theo IP: {ex}")
        return ip_cache["pos"]

    loc_cache = {"val": None, "at": 0.0}

    def get_location():
        if loc_cache["val"] and time.time() - loc_cache["at"] < 4:
            return loc_cache["val"]
        pos = gps_location()
        if pos:
            val = (pos[0], pos[1], "gps")
        else:
            pos = ip_location()
            val = (pos[0], pos[1], "ip") if pos else (DEFAULT_LOCATION[0], DEFAULT_LOCATION[1], "default")
        loc_cache["val"], loc_cache["at"] = val, time.time()
        return val

    def post_location(order_id, role, lat, lng, src):
        try:
            requests.post(f"{BACKEND_URL}/api/location/update", json={"order_id": order_id, "role": role, "lat": lat, "lng": lng, "source": src}, timeout=TIMEOUT)
        except Exception as ex:
            print(f"Lỗi gửi vị trí: {ex}")

    def location_loop():
        last_customer_push = 0.0
        last_heartbeat = 0.0
        while True:
            time.sleep(3)
            try:
                if time.time() - last_heartbeat >= 5:
                    send_heartbeat()
                    last_heartbeat = time.time()
                if is_active:
                    rh = requests.get(f"{BACKEND_URL}/api/rescue/current-helper/{HELPER_NAME}", timeout=TIMEOUT).json().get("data")
                    if rh and rh.get("status") == "NEGOTIATING":
                        lat, lng, src = get_location()
                        post_location(rh["id"], "helper", lat, lng, src)
                if time.time() - last_customer_push >= 6:
                    rc = requests.get(f"{BACKEND_URL}/api/sos/current/{CUSTOMER_PHONE}", timeout=TIMEOUT).json().get("data")
                    if rc and rc.get("status") in ("PENDING", "WAITING_APPROVAL", "CHATTING", "NEGOTIATING", "ARRIVED"):
                        lat, lng, src = get_location()
                        post_location(rc["id"], "customer", lat, lng, src)
                    last_customer_push = time.time()
            except Exception as ex:
                print(f"Lỗi vòng lặp vị trí: {ex}")

    settings = {"radius_km": 5.0, "auto_accept": False}
    offer_state = {"order_id": None, "dialog": None, "txt_left": None}

    def send_heartbeat():
        try:
            lat, lng, _src = get_location()
            requests.post(f"{BACKEND_URL}/api/helper/heartbeat", json={"helper_name": HELPER_NAME, "lat": lat, "lng": lng, "is_active": is_active}, timeout=TIMEOUT)
        except Exception as ex:
            print(f"Lỗi heartbeat: {ex}")

    def load_settings():
        try:
            r = requests.get(f"{BACKEND_URL}/api/helper/settings/{HELPER_NAME}", timeout=TIMEOUT).json().get("data")
            if r:
                settings.update(radius_km=float(r["radius_km"]), auto_accept=bool(r["auto_accept"]))
        except Exception as ex:
            print(f"Lỗi tải cài đặt: {ex}")

    def open_settings_dialog(e=None):
        page.drawer.open = False
        slider = ft.Slider(min=1, max=20, divisions=19, value=min(20, max(1, settings["radius_km"])), active_color="#EE4D2D")
        txt_radius = ft.Text(f"{int(slider.value)} km", weight=ft.FontWeight.BOLD, color="#EE4D2D", size=16)
        sw_auto = ft.Switch(value=settings["auto_accept"], active_color="#EE4D2D")

        def on_slide(ev):
            txt_radius.value = f"{int(slider.value)} km"
            page.update()

        slider.on_change = on_slide

        def save(ev):
            settings.update(radius_km=float(slider.value), auto_accept=bool(sw_auto.value))
            try:
                requests.post(f"{BACKEND_URL}/api/helper/settings", json={"helper_name": HELPER_NAME, "radius_km": settings["radius_km"], "auto_accept": settings["auto_accept"]}, timeout=TIMEOUT)
            except Exception as ex:
                print(f"Lỗi lưu cài đặt: {ex}")
            dialog.open = False
            last_sig["helper"] = None
            page.update()
            show_snack("Đã lưu cài đặt nhận đơn")
            threading.Thread(target=send_heartbeat, daemon=True).start()
            if current_tab == "DI_CUU_HO" and is_active:
                fetch_helper_working_view()

        dialog = ft.AlertDialog(
            shape=ft.RoundedRectangleBorder(radius=15),
            title=ft.Text("Cài đặt nhận đơn", weight=ft.FontWeight.BOLD, size=17),
            content=ft.Column([
                ft.Row([ft.Text("Khoảng cách nhận đơn", weight=ft.FontWeight.W_500), txt_radius], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                slider,
                ft.Text("Chỉ hiện những đơn nằm trong bán kính này tính từ vị trí của bạn.", size=12, color=ft.colors.GREY_600),
                ft.Divider(),
                ft.Row([
                    ft.Column([
                        ft.Text("Tự động nhận đơn", weight=ft.FontWeight.W_500),
                        ft.Text("Khi có đơn trong khoảng cách nhận đơn, hệ thống chọn 1 tài xế phù hợp nhất (gần nhất, đang rảnh) và hiện popup để nhận.", size=12, color=ft.colors.GREY_600),
                    ], expand=True, spacing=4),
                    sw_auto,
                ], vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Text("Cần bật \"Trạng thái hoạt động\" để nhận popup.", size=12, color=ft.colors.ORANGE_800),
            ], tight=True, width=320, spacing=8),
            actions=[
                ft.TextButton("Hủy", on_click=lambda ev: setattr(dialog, "open", False) or page.update()),
                ft.ElevatedButton("Lưu", bgcolor="#EE4D2D", color=ft.colors.WHITE, on_click=save),
            ]
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    def close_offer_dialog():
        dlg = offer_state["dialog"]
        if dlg is not None:
            dlg.open = False
        offer_state.update(order_id=None, dialog=None, txt_left=None)
        page.update()

    def respond_offer(order_id, action, price=None):
        payload = {"order_id": order_id, "helper_name": HELPER_NAME, "action": action}
        if price is not None:
            payload["proposed_price"] = price
        try:
            res = requests.post(f"{BACKEND_URL}/api/rescue/offer-response", json=payload, timeout=TIMEOUT)
            if res.status_code != 200:
                show_snack(res.json().get("detail", "Không thực hiện được"))
        except Exception as ex:
            print(f"Lỗi phản hồi đơn: {ex}")
        close_offer_dialog()
        last_sig["helper"] = None
        if action == "accept":
            switch_tab("DI_CUU_HO")

    def show_offer_dialog(offer):
        oid = offer["id"]
        customer_price = float(offer.get("price", 0))
        txt_left = ft.Text(f"Tự động chuyển cho tài xế khác sau {offer.get('seconds_left', 0)}s", size=12, color=ft.colors.RED_700)
        dist = offer.get("distance_km")
        txt_offer_price = ft.TextField(
            label="Giá đề nghị của bạn (VNĐ)",
            value=str(int(customer_price)),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10,
            focused_border_color="#EE4D2D",
            prefix_icon=ft.icons.LOCAL_OFFER,
        )

        def send_counter_price(ev):
            new_price = parse_price(txt_offer_price.value)
            if new_price is None:
                txt_offer_price.error_text = "Giá không hợp lệ"
                page.update()
                return
            txt_offer_price.error_text = None
            respond_offer(oid, "accept", new_price)

        dialog = ft.AlertDialog(
            modal=True,
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Row([ft.Icon(ft.icons.SOS, color="#EE4D2D", size=28), ft.Text("ĐƠN CỨU HỘ PHÙ HỢP VỚI BẠN", weight=ft.FontWeight.BOLD, size=15)]),
            content=ft.Column([
                ft.Row([ft.Text("Mã đơn:", color=ft.colors.GREY_700), ft.Text(f"#{oid}", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("Sự cố:", color=ft.colors.GREY_700), ft.Text(offer.get("condition", ""), weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([ft.Text("Cách bạn:", color=ft.colors.GREY_700), ft.Text(f"{dist:.1f} km" if dist is not None else "--", weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(
                    padding=12, bgcolor=ft.colors.GREEN_50, border_radius=8,
                    content=ft.Row([ft.Text("Giá khách đề xuất:", color=ft.colors.GREY_800), ft.Text(f"{customer_price:,.0f} VNĐ", color=ft.colors.GREEN_700, weight=ft.FontWeight.BOLD, size=16)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ),
                txt_offer_price,
                ft.Row([
                    ft.OutlinedButton("Đồng ý giá khách", expand=True, on_click=lambda ev: respond_offer(oid, "accept", customer_price)),
                    ft.ElevatedButton("Gửi giá đề nghị", expand=True, bgcolor="#EE4D2D", color=ft.colors.WHITE, on_click=send_counter_price),
                ], spacing=8),
                txt_left,
            ], tight=True, width=320, spacing=10),
            actions=[
                ft.TextButton("Từ chối", on_click=lambda ev: respond_offer(oid, "decline"), style=ft.ButtonStyle(color=ft.colors.RED)),
            ]
        )
        offer_state.update(order_id=oid, dialog=dialog, txt_left=txt_left)
        page.dialog = dialog
        dialog.open = True
        page.update()

    def check_offer():
        r = requests.get(f"{BACKEND_URL}/api/rescue/offer/{HELPER_NAME}", timeout=TIMEOUT).json().get("data")
        if not r:
            if offer_state["order_id"] is not None:
                close_offer_dialog()
            return
        if offer_state["order_id"] == r["id"]:
            offer_state["txt_left"].value = f"Tự động chuyển cho tài xế khác sau {r.get('seconds_left', 0)}s"
            page.update()
            return
        if page.dialog is not None and page.dialog.open:
            return
        show_offer_dialog(r)

    TILE_URL = "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
    MAP_W, MAP_H = 320, 240
    MARKER = 40

    def latlng_to_px(lat, lng, z):
        n = 256 * (2 ** z)
        x = (lng + 180.0) / 360.0 * n
        s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
        y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
        return x, y

    def fit_zoom(points):
        for z in range(17, 2, -1):
            px = [latlng_to_px(la, ln, z) for la, ln in points]
            xs = [a for a, _ in px]
            ys = [b for _, b in px]
            if max(xs) - min(xs) <= MAP_W - 110 and max(ys) - min(ys) <= MAP_H - 110:
                return z
        return 3

    def build_live_map(order):
        state = {}
        holder = ft.Container(width=MAP_W, height=MAP_H, border_radius=12, clip_behavior=ft.ClipBehavior.HARD_EDGE, bgcolor="#E9EFE6")

        def points(o):
            return [(o.get("lat"), o.get("lng")), (o.get("helper_lat"), o.get("helper_lng"))]

        def marker_px(o):
            (clat, clng), (hlat, hlng) = points(o)
            cx, cy = latlng_to_px(clat, clng, state["z"])
            hx, hy = latlng_to_px(hlat, hlng, state["z"])
            return (cx - state["tlx"], cy - state["tly"]), (hx - state["tlx"], hy - state["tly"])

        def place_markers(o):
            (cx, cy), (hx, hy) = marker_px(o)
            state["pin"].left = cx - 20
            state["pin"].top = cy - 40
            state["driver"].left = hx - MARKER / 2
            state["driver"].top = hy - MARKER / 2
            return (cx, cy), (hx, hy)

        def layout(o):
            pts = points(o)
            z = fit_zoom(pts)
            px = [latlng_to_px(la, ln, z) for la, ln in pts]
            mid_x = (min(a for a, _ in px) + max(a for a, _ in px)) / 2
            mid_y = (min(b for _, b in px) + max(b for _, b in px)) / 2
            state.update({"z": z, "tlx": mid_x - MAP_W / 2, "tly": mid_y - MAP_H / 2})

            state["pin"] = ft.Container(
                content=ft.Icon(ft.icons.LOCATION_ON, color=ft.colors.RED, size=40),
                animate_position=ft.animation.Animation(500, ft.AnimationCurve.LINEAR),
            )
            state["driver"] = ft.Container(
                width=MARKER, height=MARKER, border_radius=MARKER / 2, bgcolor="#EE4D2D",
                alignment=ft.alignment.center,
                content=ft.Icon(ft.icons.TWO_WHEELER, color=ft.colors.WHITE, size=22),
                shadow=ft.BoxShadow(spread_radius=1, blur_radius=6, color=ft.colors.BLACK38),
                animate_position=ft.animation.Animation(1000, ft.AnimationCurve.LINEAR),
            )

            n = 2 ** z
            children = []
            for tx in range(int(state["tlx"] // 256), int((state["tlx"] + MAP_W) // 256) + 1):
                for ty in range(int(state["tly"] // 256), int((state["tly"] + MAP_H) // 256) + 1):
                    if ty < 0 or ty >= n:
                        continue
                    children.append(ft.Container(
                        left=tx * 256 - state["tlx"], top=ty * 256 - state["tly"], width=256, height=256,
                        content=ft.Image(src=TILE_URL.format(z=z, x=tx % n, y=ty), width=256, height=256),
                    ))
            place_markers(o)
            children += [
                state["pin"], state["driver"],
                ft.Container(right=4, bottom=2, padding=2, bgcolor=ft.colors.with_opacity(0.7, ft.colors.WHITE),
                             content=ft.Text("© OpenStreetMap, © CARTO", size=8, color=ft.colors.GREY_800)),
            ]
            holder.content = ft.Stack(children, width=MAP_W, height=MAP_H)

        def update(o):
            (cx, cy), (hx, hy) = marker_px(o)
            out = any(not (12 <= a <= MAP_W - 12 and 12 <= b <= MAP_H - 12) for a, b in ((cx, cy - 20), (hx, hy)))
            if out or fit_zoom(points(o)) >= state["z"] + 2:
                layout(o)
            else:
                place_markers(o)

        layout(order)
        return holder, update

    tracking = {"order_id": None, "root": None, "map_update": None, "title": None, "eta": None, "dist": None}
    helper_map = {"order_id": None, "root": None, "update": None}

    def update_tracking(order):
        progress = order.get("progress") or 0.0
        status = order.get("status")
        tracking["map_update"](order)

        if status == "ARRIVED":
            tracking["title"].value = "Thợ đã đến điểm sửa xe!"
            tracking["eta"].value = "Đã đến nơi"
            tracking["dist"].value = "0 m"
        else:
            tracking["title"].value = "Thợ đang di chuyển đến bạn..."
            eta = int(order.get("eta_seconds") or 0)
            tracking["eta"].value = "Sắp tới nơi" if progress >= 1 else f"Dự kiến còn {eta // 60:02d}:{eta % 60:02d}"
            d = order.get("distance_m") or 0
            tracking["dist"].value = f"{d:,.0f} m" if d < 1000 else f"{d / 1000:.1f} km"

    def build_tracking_view(order):
        map_view, map_update = build_live_map(order)
        title = ft.Text("", weight=ft.FontWeight.BOLD, size=17, color="#212529")
        eta = ft.Text("", weight=ft.FontWeight.BOLD, size=14, color="#EE4D2D")
        dist = ft.Text("", size=14, color=ft.colors.GREY_700)

        card = ft.Card(
            elevation=6,
            content=ft.Container(
                padding=15, border_radius=15, bgcolor=ft.colors.WHITE,
                content=ft.Column([
                    title,
                    ft.Row([ft.Row([ft.Icon(ft.icons.SCHEDULE, size=18, color="#EE4D2D"), eta]), dist], width=MAP_W, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    map_view,
                    ft.Divider(),
                    ft.Row([ft.Text("Thợ cứu hộ:", color=ft.colors.GREY_700), ft.Text(order.get("helper_name", ""), weight=ft.FontWeight.BOLD)], width=MAP_W, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([ft.Text("Giá chốt:", color=ft.colors.GREY_700), ft.Text(f"{order.get('price', 0):,.0f} VNĐ", weight=ft.FontWeight.BOLD, color=ft.colors.GREEN, size=16)], width=MAP_W, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
            )
        )

        tracking.update({"order_id": order.get("id"), "root": card, "map_update": map_update, "title": title, "eta": eta, "dist": dist})
        update_tracking(order)
        content_column.controls = [ft.Container(height=15), card]

    def poll_customer_order():
        try:
            res = requests.get(f"{BACKEND_URL}/api/sos/current/{CUSTOMER_PHONE}", timeout=TIMEOUT)
            if res.status_code == 200:
                order = extract_order(res.json())

                if not order:
                    render_sos_form()
                    return

                status = order.get("status")
                oid = order.get("id")

                if status == "COMPLETED":
                    render_sos_form()
                    return

                if status == "PENDING":
                    content_column.controls = [
                        ft.Container(height=50),
                        ft.Card(
                            elevation=4, expand=True,
                            content=ft.Container(
                                padding=30, border_radius=15, bgcolor=ft.colors.WHITE, alignment=ft.alignment.center,
                                content=ft.Column([
                                    ft.ProgressRing(color="#EE4D2D", width=50, height=50),
                                    ft.Container(height=20),
                                    ft.Text(f"Đang phát tín hiệu SOS #{oid}", weight=ft.FontWeight.BOLD, size=18, color="#212529"),
                                    ft.Container(height=10),
                                    ft.Text("Hệ thống đang kết nối với các thợ sửa xe gần nhất...", text_align=ft.TextAlign.CENTER, color=ft.colors.GREY_700, size=14),
                                    ft.Container(height=30),
                                    ft.ElevatedButton("Hủy yêu cầu", bgcolor=ft.colors.RED_50, color=ft.colors.RED_700, elevation=0, width=220, on_click=lambda e: open_cancel_dialog(oid))
                                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                            )
                        )
                    ]
                elif status == "WAITING_APPROVAL":
                    content_column.controls = [
                        ft.Container(height=20),
                        ft.Card(
                            elevation=6, expand=True,
                            content=ft.Container(
                                padding=25, border_radius=15, bgcolor=ft.colors.WHITE,
                                content=ft.Column([
                                    ft.Container(content=ft.Icon(ft.icons.LOCAL_OFFER, size=40, color=ft.colors.WHITE), bgcolor="#EE4D2D", padding=15, border_radius=35),
                                    ft.Container(height=10),
                                    ft.Text("THỢ ĐÃ ĐỀ NGHỊ GIÁ", weight=ft.FontWeight.BOLD, size=18, color="#212529"),
                                    ft.Divider(height=25),
                                    ft.Row([ft.Text("Thợ sửa xe:", color=ft.colors.GREY_700), ft.Text(order.get('helper_name', ''), weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                    ft.Row([ft.Text("Giá khách:", color=ft.colors.GREY_700), ft.Text(f"{order.get('price', 0):,.0f} VNĐ")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                    ft.Container(height=5),
                                    ft.Container(
                                        padding=15, bgcolor=ft.colors.ORANGE_50, border_radius=10,
                                        content=ft.Row([
                                            ft.Text("Giá thợ đề xuất:", weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE_900),
                                            ft.Text(f"{order.get('proposed_price', 0):,.0f} VNĐ", weight=ft.FontWeight.BOLD, color="#EE4D2D", size=18)
                                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                                    ),
                                    ft.Container(height=25),
                                    ft.Row([
                                        ft.ElevatedButton("Đồng ý", bgcolor="#2ECC71", color=ft.colors.WHITE, expand=True, on_click=lambda e: handle_price_action(oid, "accept")),
                                        ft.Container(width=10),
                                        ft.OutlinedButton("Thương lượng", expand=True, on_click=lambda e: handle_price_action(oid, "reject"))
                                    ]),
                                    ft.Container(height=10),
                                    ft.TextButton("Hủy đơn", on_click=lambda e: open_cancel_dialog(oid), style=ft.ButtonStyle(color=ft.colors.RED))
                                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                            )
                        )
                    ]
                elif status == "CHATTING":
                    messages = order.get("messages", [])
                    chat_listView = ft.ListView(expand=1, spacing=10, padding=10)

                    chat_listView.controls.append(
                        ft.Row([
                            ft.Container(
                                content=ft.Text("Chào bạn, hệ thống P2P SOS rất vui được hỗ trợ bạn thương lượng giá!", size=13, color=ft.colors.BLACK87),
                                bgcolor=ft.colors.WHITE, padding=12, border_radius=12, width=320,
                                shadow=ft.BoxShadow(spread_radius=1, blur_radius=2, color=ft.colors.BLACK12)
                            )
                        ], alignment=ft.MainAxisAlignment.START)
                    )

                    for m in messages:
                        is_me = m.get("sender") == "customer"
                        chat_listView.controls.append(
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Text(m.get('message', ''), color=ft.colors.WHITE if is_me else ft.colors.BLACK87, size=13),
                                        bgcolor="#EE4D2D" if is_me else ft.colors.WHITE,
                                        padding=12, border_radius=12, width=260,
                                        shadow=None if is_me else ft.BoxShadow(spread_radius=1, blur_radius=2, color=ft.colors.BLACK12)
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.END if is_me else ft.MainAxisAlignment.START
                            )
                        )

                    def send_msg(e):
                        if not txt_chat_input.value:
                            return
                        try:
                            requests.post(f"{BACKEND_URL}/api/sos/chat/send", json={"order_id": oid, "sender": "customer", "message": txt_chat_input.value}, timeout=TIMEOUT)
                        except Exception as ex:
                            print(f"Lỗi gửi chat: {ex}")
                        txt_chat_input.value = ""
                        poll_customer_order()

                    content_column.controls = [
                        ft.Container(
                            expand=True, bgcolor="#F2F2F2", padding=10,
                            content=ft.Column([
                                ft.Container(
                                    padding=10, bgcolor=ft.colors.WHITE, border_radius=8,
                                    content=ft.Row([ft.Icon(ft.icons.SUPPORT_AGENT, color="#EE4D2D"), ft.Text("Hỗ trợ thương lượng giá trực tuyến", weight=ft.FontWeight.BOLD, size=13)])
                                ),
                                ft.Container(height=5),
                                ft.Container(content=chat_listView, expand=True),
                                ft.Row([
                                    ft.Chip(label=ft.Text("Đồng ý chốt giá"), on_click=lambda e: handle_price_action(oid, "accept")),
                                    ft.Chip(label=ft.Text("Đang chờ thợ..."))
                                ], scroll=ft.ScrollMode.AUTO),
                                ft.Container(height=5),
                                ft.Container(
                                    padding=ft.padding.symmetric(horizontal=10, vertical=8), bgcolor=ft.colors.WHITE, border_radius=ft.border_radius.all(25),
                                    content=ft.Row([txt_chat_input, ft.IconButton(icon=ft.icons.SEND_ROUNDED, icon_color="#EE4D2D", on_click=send_msg)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                                )
                            ])
                        )
                    ]
                elif status in ["NEGOTIATING", "ARRIVED"]:
                    if tracking["order_id"] == oid and len(content_column.controls) > 1 and content_column.controls[1] is tracking["root"]:
                        update_tracking(order)
                    else:
                        build_tracking_view(order)

                page.update()
            else:
                render_sos_form()
        except Exception as ex:
            print(f"Lỗi polling: {ex}")
            render_sos_form()

    def submit_sos_request(e):
        cond = txt_condition.value
        price = parse_price(txt_price.value)
        if not cond or price is None:
            show_snack("Vui lòng điền đủ thông tin sự cố và giá hợp lệ!")
            return

        try:
            my_lat, my_lng, _src = get_location()
            res = requests.post(f"{BACKEND_URL}/api/sos/create", json={
                "customer_phone": CUSTOMER_PHONE,
                "condition": cond,
                "price": price,
                "lat": my_lat,
                "lng": my_lng
            }, timeout=TIMEOUT)
            if res.status_code != 200:
                detail = res.json().get("detail", "Lỗi tạo đơn")
                show_snack(detail)
            last_sig["customer"] = None
            poll_customer_order()
        except Exception as ex:
            print(f"Lỗi: {ex}")
            show_snack("Không kết nối được server!")

    def handle_price_action(order_id, action):
        try:
            requests.post(f"{BACKEND_URL}/api/sos/price-action", json={"order_id": order_id, "action": action}, timeout=TIMEOUT)
        except Exception as ex:
            print(f"Lỗi price-action: {ex}")
        last_sig["customer"] = None
        poll_customer_order()

    def open_cancel_dialog(order_id):
        def confirm_cancel(e):
            reason = txt_cancel_reason.value
            if not reason:
                return
            try:
                requests.post(f"{BACKEND_URL}/api/sos/cancel", json={"order_id": order_id, "reason": reason}, timeout=TIMEOUT)
            except Exception as ex:
                print(f"Lỗi hủy đơn: {ex}")
            dialog.open = False
            txt_cancel_reason.value = ""
            last_sig["customer"] = None
            poll_customer_order()

        dialog = ft.AlertDialog(
            shape=ft.RoundedRectangleBorder(radius=15),
            title=ft.Text("Hủy đơn cứu hộ", weight=ft.FontWeight.BOLD),
            content=ft.Column([ft.Text("Vui lòng ghi rõ lý do hủy:"), txt_cancel_reason], height=120, tight=True),
            actions=[
                ft.TextButton("Quay lại", on_click=lambda e: setattr(dialog, "open", False) or page.update()),
                ft.ElevatedButton("Xác nhận hủy", bgcolor=ft.colors.RED, color=ft.colors.WHITE, on_click=confirm_cancel)
            ]
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    def open_accept_dialog(order_id, customer_price):
        txt_input_price = ft.TextField(
            label="Nhập giá đề xuất mới (VNĐ)",
            value=str(int(customer_price)),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=10, focused_border_color="#EE4D2D", expand=True
        )

        def send_accept(price):
            try:
                res = requests.post(f"{BACKEND_URL}/api/rescue/accept", json={"order_id": order_id, "proposed_price": price, "helper_name": HELPER_NAME}, timeout=TIMEOUT)
                if res.status_code != 200:
                    show_snack(res.json().get("detail", "Không nhận được đơn"))
            except Exception as ex:
                print(f"Lỗi nhận đơn: {ex}")
            dialog.open = False
            switch_tab("DI_CUU_HO")

        def accept_original_price(e):
            send_accept(customer_price)

        def submit_custom_price(e):
            new_price = parse_price(txt_input_price.value)
            if new_price is None:
                txt_input_price.error_text = "Giá không hợp lệ"
                page.update()
                return
            send_accept(new_price)

        dialog = ft.AlertDialog(
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Row([ft.Icon(ft.icons.HANDSHAKE, color="#EE4D2D"), ft.Text("Xác nhận nhận đơn SOS", weight=ft.FontWeight.BOLD, size=16)]),
            content=ft.Column([
                ft.Container(
                    padding=12, bgcolor=ft.colors.GREEN_50, border_radius=8,
                    content=ft.Row([ft.Text("Giá khách đề xuất:", color=ft.colors.GREY_800), ft.Text(f"{customer_price:,.0f} VNĐ", color=ft.colors.GREEN_700, weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ),
                ft.Container(height=10),
                txt_input_price,
            ], height=150, tight=True),
            actions=[
                ft.TextButton("Hủy", on_click=lambda e: setattr(dialog, "open", False) or page.update()),
                ft.OutlinedButton("Đồng ý giá khách", on_click=accept_original_price),
                ft.ElevatedButton("Gửi giá đề nghị", bgcolor="#EE4D2D", color=ft.colors.WHITE, on_click=submit_custom_price),
            ]
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    def open_chat_and_reoffer_dialog(order_id):
        txt_reoffer_price = ft.TextField(label="Đề xuất giá mới sau thương lượng (VNĐ)", border_radius=8, keyboard_type=ft.KeyboardType.NUMBER, expand=True)
        txt_helper_chat = ft.TextField(label="Nhập tin nhắn...", border_radius=8, expand=True)
        chat_history_list = ft.ListView(expand=1, spacing=8, padding=10)

        def load_chat_messages():
            try:
                res = requests.get(f"{BACKEND_URL}/api/sos/current/{CUSTOMER_PHONE}", timeout=TIMEOUT)
                if res.status_code == 200:
                    order_data = extract_order(res.json())
                    if order_data:
                        chat_history_list.controls.clear()
                        for m in order_data.get("messages", []):
                            is_me = m.get("sender") == "helper"
                            chat_history_list.controls.append(
                                ft.Row(
                                    [ft.Container(content=ft.Text(m.get('message', ''), size=13), bgcolor=ft.colors.BLUE_50 if is_me else ft.colors.WHITE, padding=10, border_radius=10, expand=True)],
                                    alignment=ft.MainAxisAlignment.END if is_me else ft.MainAxisAlignment.START
                                )
                            )
                        page.update()
            except Exception as ex:
                print(f"Lỗi tải chat: {ex}")

        def send_helper_msg(e):
            if not txt_helper_chat.value:
                return
            try:
                requests.post(f"{BACKEND_URL}/api/sos/chat/send", json={"order_id": order_id, "sender": "helper", "message": txt_helper_chat.value}, timeout=TIMEOUT)
            except Exception as ex:
                print(f"Lỗi gửi chat: {ex}")
            txt_helper_chat.value = ""
            load_chat_messages()

        def submit_reoffer(e):
            price = parse_price(txt_reoffer_price.value)
            if price is None:
                txt_reoffer_price.error_text = "Giá không hợp lệ"
                page.update()
                return
            try:
                requests.post(f"{BACKEND_URL}/api/sos/new-price-offer", json={"order_id": order_id, "new_proposed_price": price}, timeout=TIMEOUT)
            except Exception as ex:
                print(f"Lỗi gửi giá mới: {ex}")
            dialog.open = False
            switch_tab("DI_CUU_HO")

        load_chat_messages()

        dialog = ft.AlertDialog(
            shape=ft.RoundedRectangleBorder(radius=15),
            title=ft.Text("Thương lượng giá với Khách", weight=ft.FontWeight.BOLD, size=16),
            content=ft.Column([
                ft.Text("Lịch sử trò chuyện:", size=12, color=ft.colors.GREY_700),
                ft.Container(content=chat_history_list, border=ft.border.all(1, ft.colors.GREY_300), border_radius=8, padding=5, expand=True),
                ft.Container(height=5),
                ft.Row([txt_helper_chat, ft.ElevatedButton("Gửi", bgcolor="#EE4D2D", color=ft.colors.WHITE, on_click=send_helper_msg)]),
                ft.Container(height=5),
                txt_reoffer_price
            ], height=350, tight=True),
            actions=[
                ft.TextButton("Đóng", on_click=lambda e: setattr(dialog, "open", False) or page.update()),
                ft.ElevatedButton("Gửi giá mới", bgcolor="#EE4D2D", color=ft.colors.WHITE, on_click=submit_reoffer)
            ]
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    def update_helper_status(order_id, new_status):
        try:
            requests.post(f"{BACKEND_URL}/api/rescue/update-status", json={"order_id": order_id, "status": new_status}, timeout=TIMEOUT)
        except Exception as ex:
            print(f"Lỗi cập nhật trạng thái: {ex}")
        switch_tab("DI_CUU_HO")

    slider_state = {"x": 0.0}
    slider_width = 330

    def on_pan_update(e: ft.DragUpdateEvent):
        new_x = slider_state["x"] + e.delta_x
        new_x = max(0, min(new_x, slider_width - 55))
        slider_state["x"] = new_x
        draggable_btn.left = new_x
        draggable_btn.update()

    def on_pan_end(e: ft.DragEndEvent):
        if slider_state["x"] >= (slider_width - 55) * 0.7:
            slider_state["x"] = slider_width - 55
            draggable_btn.left = slider_state["x"]
            draggable_btn.update()

            if not is_active:
                set_active_state(True)
            else:
                try:
                    res_working = requests.get(f"{BACKEND_URL}/api/rescue/current-helper/{HELPER_NAME}", timeout=TIMEOUT)
                    if res_working.status_code == 200:
                        order = extract_order(res_working.json())
                        if order:
                            oid = order.get("id")
                            status = order.get("status")
                            if status == "NEGOTIATING":
                                update_helper_status(oid, "ARRIVED")
                            elif status == "ARRIVED":
                                update_helper_status(oid, "COMPLETED")
                except Exception as ex:
                    print(f"Lỗi slider: {ex}")

        slider_state["x"] = 0.0
        draggable_btn.left = 0.0
        draggable_btn.update()

    draggable_btn = ft.Container(
        content=ft.Icon(ft.icons.ARROW_FORWARD_IOS_ROUNDED, color="#EE4D2D", size=18),
        bgcolor=ft.colors.WHITE, width=50, height=48, border_radius=8, alignment=ft.alignment.center, left=0,
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=3, color=ft.colors.BLACK12)
    )

    slider_track = ft.GestureDetector(
        on_pan_update=on_pan_update,
        on_pan_end=on_pan_end,
        content=ft.Container(
            bgcolor="#EE4D2D", expand=True, height=56, border_radius=12, padding=4,
            content=ft.Stack([
                ft.Row([ft.Container(content=txt_slider_label, alignment=ft.alignment.center, expand=True)], alignment=ft.MainAxisAlignment.CENTER),
                draggable_btn
            ], alignment=ft.alignment.center_left)
        )
    )

    def fetch_helper_working_view(e=None):
        nonlocal rescue_orders_list
        try:
            res_working = requests.get(f"{BACKEND_URL}/api/rescue/current-helper/{HELPER_NAME}", timeout=TIMEOUT)
            if res_working.status_code == 200:
                order = extract_order(res_working.json())

                if order:
                    oid = order.get("id")
                    status = order.get("status")
                    cust_lat, cust_lng = order.get("lat"), order.get("lng")
                    google_maps_url = f"https://www.google.com/maps/search/?api=1&query={cust_lat},{cust_lng}"

                    if status == "NEGOTIATING":
                        txt_slider_label.value = "Trượt: Đã đến điểm sửa"
                    elif status == "ARRIVED":
                        txt_slider_label.value = "Trượt: Đã sửa xong"

                    bottom_container.current.visible = True

                    map_view, map_update = build_live_map(order)
                    root = ft.Container(
                        expand=True, padding=10,
                        content=ft.Card(
                            elevation=6,
                            content=ft.Container(
                                padding=15, border_radius=15, bgcolor=ft.colors.WHITE,
                                content=ft.Column([
                                    ft.Row([
                                        ft.Row([ft.Icon(ft.icons.BUILD_ROUNDED, color="#EE4D2D"), ft.Text(f"ĐANG THỰC HIỆN ĐƠN #{oid}", weight=ft.FontWeight.BOLD, size=14, color="#EE4D2D")], expand=True),
                                        ft.IconButton(icon=ft.icons.MAP_ROUNDED, icon_color=ft.colors.BLUE_600, icon_size=28, tooltip="Mở Google Maps chỉ đường", url=google_maps_url),
                                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                    map_view,
                                    ft.Row([ft.Text("Khách hàng:", color=ft.colors.GREY_700), ft.Text(order.get('customer_phone', ''), weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                    ft.Row([ft.Text("Sự cố:", color=ft.colors.GREY_700), ft.Text(order.get('condition', ''), weight=ft.FontWeight.BOLD)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                    ft.Row([ft.Text("Giá chốt:", color=ft.colors.GREY_700), ft.Text(f"{order.get('price', 0):,.0f} VNĐ", weight=ft.FontWeight.BOLD, color=ft.colors.GREEN, size=16)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ], horizontal_alignment=ft.CrossAxisAlignment.START, spacing=10, scroll=ft.ScrollMode.AUTO)
                            )
                        )
                    )
                    helper_map.update({"order_id": oid, "root": root, "update": map_update})
                    content_column.controls = [root]
                    page.update()
                    return

            res = requests.get(f"{BACKEND_URL}/api/rescue/pending", params={"helper_name": HELPER_NAME}, timeout=TIMEOUT)
            res_all = requests.get(f"{BACKEND_URL}/api/sos/current/{CUSTOMER_PHONE}", timeout=TIMEOUT)

            rescue_orders_list = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

            if res.status_code == 200:
                for item in res.json().get("data", []):
                    oid = item.get('id')
                    c_price = item.get('price', 0)
                    rescue_orders_list.controls.append(
                        ft.Card(
                            elevation=3,
                            content=ft.Container(
                                padding=15, border_radius=12, bgcolor=ft.colors.WHITE,
                                content=ft.Column([
                                    ft.Row([
                                        ft.Row([ft.Icon(ft.icons.WARNING_ROUNDED, color=ft.colors.RED, size=20), ft.Text(f"Yêu cầu SOS #{oid}", weight=ft.FontWeight.BOLD, color=ft.colors.RED_700)]),
                                        ft.Text(f"{c_price:,.0f} VNĐ", weight=ft.FontWeight.BOLD, color=ft.colors.GREEN_700, size=15)
                                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                    ft.Text(f"Sự cố: {item.get('condition', '')}", size=13, color=ft.colors.GREY_800),
                                    ft.Text(f"Cách bạn {item.get('distance_km'):.1f} km", size=12, color=ft.colors.GREY_600) if item.get("distance_km") is not None else ft.Container(height=0),
                                    ft.Container(height=5),
                                    ft.Row([ft.ElevatedButton("Nhận đơn này", bgcolor="#EE4D2D", color=ft.colors.WHITE, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)), on_click=lambda e, id=oid, price=c_price: open_accept_dialog(id, price), expand=True)])
                                ])
                            )
                        )
                    )

            if res_all.status_code == 200:
                cur_order = extract_order(res_all.json())

                if cur_order and cur_order.get("status") == "CHATTING":
                    oid = cur_order.get('id')
                    rescue_orders_list.controls.append(
                        ft.Card(
                            elevation=3,
                            content=ft.Container(
                                padding=15, border_radius=12, bgcolor=ft.colors.ORANGE_50,
                                content=ft.Column([
                                    ft.Text(f"💬 Đơn #{oid} đang thương lượng giá", weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE_900),
                                    ft.Text(f"Sự cố: {cur_order.get('condition', '')}", size=13),
                                    ft.Row([ft.ElevatedButton("Vào Chat & Đề xuất lại giá", bgcolor=ft.colors.BLUE, color=ft.colors.WHITE, on_click=lambda e, id=oid: open_chat_and_reoffer_dialog(id), expand=True)])
                                ])
                            )
                        )
                    )

            real_count = len(rescue_orders_list.controls)

            if not rescue_orders_list.controls:
                rescue_orders_list.controls.append(
                    ft.Container(
                        padding=60, alignment=ft.alignment.center,
                        content=ft.Column([
                            ft.Icon(ft.icons.RADAR, size=60, color=ft.colors.GREY_400),
                            ft.Container(height=10),
                            ft.Text("Chưa có đơn cứu hộ nào quanh đây...", color=ft.colors.GREY_600, size=14)
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                    )
                )

            if is_active:
                bottom_container.current.visible = False

            content_column.controls = [
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=15, vertical=8),
                    content=ft.Row([
                        ft.Text(f"DANH SÁCH ĐƠN CỨU HỘ ({real_count})", weight=ft.FontWeight.BOLD, size=15, color="#212529"),
                        ft.IconButton(icon=ft.icons.REFRESH_ROUNDED, icon_color="#EE4D2D", on_click=fetch_helper_working_view)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ),
                ft.Container(content=rescue_orders_list, expand=True, padding=ft.padding.symmetric(horizontal=10))
            ]
            page.update()
        except Exception as ex:
            print(f"Lỗi tải danh sách thợ: {ex}")

    def switch_tab(tab_name):
        nonlocal current_tab
        current_tab = tab_name
        last_sig["customer"] = None
        last_sig["helper"] = None

        if tab_name == "GOI_CUU_HO":
            tab_goi_cuu_ho.border = ft.border.only(bottom=ft.BorderSide(3, "#EE4D2D"))
            tab_di_cuu_ho.border = None
            bottom_container.current.visible = False
            poll_customer_order()
        else:
            tab_goi_cuu_ho.border = None
            tab_di_cuu_ho.border = ft.border.only(bottom=ft.BorderSide(3, "#EE4D2D"))
            if is_active:
                fetch_helper_working_view()
            else:
                txt_slider_label.value = "Sẵn sàng hoạt động"
                render_resting_view()
                bottom_container.current.visible = True
        page.update()

    def set_active_state(active: bool):
        nonlocal is_active
        is_active = active
        last_sig["helper"] = None
        if active:
            txt_status_header.value = "Đang hoạt động"
            txt_slider_label.value = "Trượt để bắt đầu"
            bottom_container.current.visible = False
            if current_tab == "DI_CUU_HO":
                fetch_helper_working_view()
        else:
            txt_status_header.value = "Tạm nghỉ"
            txt_slider_label.value = "Sẵn sàng hoạt động"
            if current_tab == "DI_CUU_HO":
                render_resting_view()
                bottom_container.current.visible = True

        if status_switch.current:
            status_switch.current.value = active
        page.update()
        threading.Thread(target=send_heartbeat, daemon=True).start()

    def auto_refresh():
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                if is_active and settings["auto_accept"]:
                    check_offer()
                elif offer_state["order_id"] is not None:
                    close_offer_dialog()

                if current_tab == "DI_CUU_HO" and is_active:
                    res = requests.get(f"{BACKEND_URL}/api/rescue/pending", params={"helper_name": HELPER_NAME}, timeout=TIMEOUT).json()
                    res_h = requests.get(f"{BACKEND_URL}/api/rescue/current-helper/{HELPER_NAME}", timeout=TIMEOUT).json()
                    res_c = requests.get(f"{BACKEND_URL}/api/sos/current/{CUSTOMER_PHONE}", timeout=TIMEOUT).json()
                    helper_order = res_h.get("data") or {}
                    cust_order = res_c.get("data") or {}
                    sig = (
                        tuple(o["id"] for o in res.get("data", [])),
                        helper_order.get("id"), helper_order.get("status"),
                        cust_order.get("id") if cust_order.get("status") == "CHATTING" else None,
                        len(cust_order.get("messages", [])) if cust_order.get("status") == "CHATTING" else 0,
                    )
                    if sig != last_sig["helper"]:
                        last_sig["helper"] = sig
                        fetch_helper_working_view()

                    if (helper_order.get("status") in ("NEGOTIATING", "ARRIVED")
                            and helper_map["order_id"] == helper_order.get("id")
                            and content_column.controls and content_column.controls[0] is helper_map["root"]):
                        helper_map["update"](helper_order)
                        page.update()

                elif current_tab == "GOI_CUU_HO":
                    res = requests.get(f"{BACKEND_URL}/api/sos/current/{CUSTOMER_PHONE}", timeout=TIMEOUT).json()
                    o = res.get("data") or {}
                    sig = (o.get("id"), o.get("status"), o.get("proposed_price"), o.get("price"), len(o.get("messages", [])))
                    if o.get("status") in ("NEGOTIATING", "ARRIVED"):
                        last_sig["customer"] = sig
                        poll_customer_order()
                    elif sig != last_sig["customer"]:
                        last_sig["customer"] = sig
                        poll_customer_order()
            except Exception as ex:
                print(f"Lỗi auto refresh: {ex}")

    drawer_content = ft.NavigationDrawer(
        bgcolor=ft.colors.WHITE,
        controls=[
            ft.Container(
                content=ft.Column([
                    ft.CircleAvatar(radius=35, content=ft.Icon(ft.icons.PERSON, size=35, color=ft.colors.WHITE), bgcolor="#EE4D2D"),
                    ft.Container(height=10),
                    ft.Text(HELPER_NAME, weight=ft.FontWeight.BOLD, size=16),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=25
            ),
            ft.Divider(height=1),
            ft.ListTile(title=ft.Row([ft.Text("Trạng thái hoạt động", weight=ft.FontWeight.W_500), ft.Switch(ref=status_switch, value=False, active_color="#EE4D2D", on_change=lambda e: set_active_state(e.control.value))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)),
            ft.Divider(height=1),
            ft.ListTile(leading=ft.Icon(ft.icons.NOTIFICATIONS_OUTLINED, color="#EE4D2D"), title=ft.Text("Thông báo"), on_click=lambda e: print("Thông báo")),
            ft.ListTile(leading=ft.Icon(ft.icons.ACCOUNT_BALANCE_WALLET_OUTLINED, color="#EE4D2D"), title=ft.Text("Thu nhập"), on_click=lambda e: print("Thu nhập")),
            ft.ListTile(leading=ft.Icon(ft.icons.HISTORY_ROUNDED, color="#EE4D2D"), title=ft.Text("Lịch sử cứu hộ"), on_click=lambda e: print("Lịch sử cứu hộ")),
            ft.ListTile(leading=ft.Icon(ft.icons.WARNING_AMBER_ROUNDED, color="#EE4D2D"), title=ft.Text("Lịch sử sự cố"), on_click=lambda e: print("Lịch sử sự cố")),
            ft.ListTile(leading=ft.Icon(ft.icons.HELP_OUTLINE_ROUNDED, color="#EE4D2D"), title=ft.Text("Trung tâm trợ giúp"), on_click=lambda e: print("Trung tâm trợ giúp")),
            ft.ListTile(leading=ft.Icon(ft.icons.SETTINGS_OUTLINED, color="#EE4D2D"), title=ft.Text("Cài đặt"), on_click=open_settings_dialog),
            ft.Divider(height=1),
            ft.ListTile(leading=ft.Icon(ft.icons.PHONE_CALLBACK, color=ft.colors.RED), title=ft.Text("Gọi 113 - Công an"), url="tel:113"),
            ft.ListTile(leading=ft.Icon(ft.icons.LOCAL_HOSPITAL, color=ft.colors.RED), title=ft.Text("Gọi 115 - Cấp cứu"), url="tel:115"),
        ],
    )
    page.drawer = drawer_content

    header = ft.Container(
        bgcolor=ft.colors.WHITE, padding=12,
        content=ft.Row([
            ft.GestureDetector(on_tap=lambda e: setattr(page.drawer, "open", True) or page.update(), content=ft.CircleAvatar(radius=20, content=ft.Icon(ft.icons.PERSON, color=ft.colors.WHITE, size=20), bgcolor="#EE4D2D")),
            ft.Container(width=10),
            ft.Column([ft.Text(HELPER_NAME, weight=ft.FontWeight.BOLD, size=14, color="#212529"), txt_status_header], spacing=0)
        ])
    )

    tab_goi_cuu_ho.on_click = lambda e: switch_tab("GOI_CUU_HO")
    tab_di_cuu_ho.on_click = lambda e: switch_tab("DI_CUU_HO")

    tabs_bar = ft.Container(
        bgcolor=ft.colors.WHITE,
        content=ft.Row([tab_goi_cuu_ho, tab_di_cuu_ho])
    )

    content_area_container = ft.Container(expand=True, padding=0, content=content_column)

    bottom_slider_container = ft.Container(
        ref=bottom_container, bgcolor=ft.colors.WHITE, padding=15, alignment=ft.alignment.center, content=slider_track, visible=False
    )

    shell = ft.Container(
        content=ft.Column([header, tabs_bar, content_area_container, bottom_slider_container], spacing=0, expand=True),
        width=min(page.width or 420, 420),
        bgcolor="#F8F9FA",
    )

    def on_page_resize(e):
        shell.width = min(page.width or 420, 420)
        page.update()

    page.on_resize = on_page_resize
    page.bgcolor = "#DEE2E6"
    page.add(ft.Row([shell], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.STRETCH, expand=True))
    switch_tab("GOI_CUU_HO")
    threading.Thread(target=auto_refresh, daemon=True).start()
    setup_geolocator()
    threading.Thread(target=load_settings, daemon=True).start()
    threading.Thread(target=location_loop, daemon=True).start()


port = os.environ.get("PORT")
if port:
    ft.app(target=main, view=None, host="0.0.0.0", port=int(port))
else:
    ft.app(target=main)