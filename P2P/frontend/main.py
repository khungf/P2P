import base64
import math
import os
import secrets
import threading
import time
import uuid
from datetime import date, datetime

import flet as ft
import requests

BACKEND_URL = "http://127.0.0.1:8000"
CUSTOMER_PHONE = "0901234567"
HELPER_NAME = "ĐỖ KHÁNH HÙNG"
TIMEOUT = 5
POLL_INTERVAL = 1
UPLOAD_TIMEOUT = 60          # tải ảnh có thể lâu hơn các lệnh gọi thường
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Thư mục tạm để Flet nhận ảnh từ trình duyệt/điện thoại (chế độ web) trước khi gửi lên server.
# Ảnh trong thư mục này được xóa ngay sau khi gửi xong.
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flet_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
# Flet cần một khóa bí mật để ký đường dẫn tải ảnh lên (chỉ dùng trong lúc chạy)
os.environ.setdefault("FLET_SECRET_KEY", secrets.token_hex(16))


def safe_get_json(url, params=None):
    try:
        res = requests.get(url, params=params, timeout=TIMEOUT)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


def extract_order(res_data):
    if isinstance(res_data, dict):
        return res_data.get("data") or res_data.get("order") or (res_data if "status" in res_data else None)
    return None


def main(page: ft.Page):
    page.title = "P2P SOS - Cứu Hộ Giao Thông"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 0
    page.bgcolor = "#E9ECEF"
    page.window_width = 400
    page.window_height = 800

    auth_state = {"logged_in": False, "phone": "", "helper_name": HELPER_NAME, "status": ""}
    register_pickers = []

    def ic(name, fallback=ft.icons.CIRCLE):
        # Lấy icon theo tên; nếu bản Flet không có icon đó thì dùng icon dự phòng thay vì làm hỏng cả màn hình
        return getattr(ft.icons, name, fallback)

    def show_snack(text):
        snack = ft.SnackBar(
            ft.Text(text),
            behavior=ft.SnackBarBehavior.FLOATING,
            width=max(240, min(380, (page.width or 400) - 24)),
        )
        page.overlay.append(snack)
        snack.open = True
        page.update()

    def parse_price(raw):
        cleaned = (raw or "").replace(",", "").replace(".", "").replace(" ", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            return None
        return value if value > 0 else None

    # Khung chứa chính để quản lý chuyển màn hình ổn định
    main_view_container = ft.Container(expand=True)

    # ================= MÀN HÌNH ĐĂNG NHẬP =================
    def build_login_view(prefill_phone=""):
        phone_input = ft.TextField(
            label="Số điện thoại",
            value=prefill_phone,
            prefix_icon=ft.icons.PHONE,
            border_radius=10,
            focused_border_color="#EE4D2D",
            keyboard_type=ft.KeyboardType.PHONE
        )
        pass_input = ft.TextField(
            label="Mật khẩu",
            prefix_icon=ft.icons.LOCK,
            password=True,
            can_reveal_password=True,
            border_radius=10,
            focused_border_color="#EE4D2D"
        )
        
        def handle_login(e):
            phone = (phone_input.value or "").replace(" ", "")
            if not phone or not pass_input.value:
                show_snack("Vui lòng nhập số điện thoại và mật khẩu!")
                return
            try:
                res = requests.post(f"{BACKEND_URL}/api/auth/login", json={"phone": phone, "password": pass_input.value}, timeout=TIMEOUT)
            except requests.exceptions.RequestException:
                show_snack("Không kết nối được máy chủ. Vui lòng thử lại!")
                return
            if res.status_code != 200:
                try:
                    detail = res.json().get("detail")
                except ValueError:
                    detail = None
                show_snack(detail if isinstance(detail, str) else "Đăng nhập thất bại!")
                return
            account = (res.json() or {}).get("data") or {}
            auth_state["logged_in"] = True
            auth_state["phone"] = phone
            auth_state["helper_name"] = (account.get("full_name") or HELPER_NAME).upper()
            auth_state["status"] = account.get("status") or "PENDING_REVIEW"
            if auth_state["status"] == "APPROVED":
                show_snack("Đăng nhập thành công!")
            else:
                show_snack("Đăng nhập thành công! Hồ sơ đang chờ duyệt nên chưa bật được chế độ thợ.")
            load_main_app_layout()

        def go_to_register(e):
            try:
                main_view_container.content = build_register_view()
                page.update()
            except Exception as ex:
                print("Lỗi mở màn hình đăng ký:", repr(ex))
                show_snack(f"Không mở được màn hình đăng ký: {ex}")

        return ft.Container(
            expand=True,
            alignment=ft.alignment.center,
            padding=20,
            content=ft.Card(
                elevation=4,
                content=ft.Container(
                    padding=25,
                    width=350,
                    bgcolor=ft.colors.WHITE,
                    border_radius=15,
                    content=ft.Column([
                        ft.Icon(ft.icons.SOS, size=50, color="#EE4D2D"),
                        ft.Text("P2P SOS RESCUE", size=20, weight=ft.FontWeight.BOLD, color="#212529"),
                        ft.Text("Đăng nhập tài khoản cứu hộ", size=12, color=ft.colors.GREY_600),
                        ft.Container(height=15),
                        phone_input,
                        ft.Container(height=8),
                        pass_input,
                        ft.Container(height=15),
                        ft.Row([
                            ft.ElevatedButton(
                                text="ĐĂNG NHẬP",
                                color=ft.colors.WHITE,
                                bgcolor="#EE4D2D",
                                height=45,
                                expand=True,
                                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                                on_click=handle_login
                            )
                        ]),
                        ft.Text("Tài khoản demo: 0901234567 / 123456", size=11, color=ft.colors.GREY_500),
                        ft.Container(height=10),
                        ft.Row([
                            ft.Text("Chưa có tài khoản?", size=12, color=ft.colors.GREY_700),
                            ft.TextButton("Đăng ký hồ sơ mới", on_click=go_to_register, style=ft.ButtonStyle(color="#EE4D2D"))
                        ], alignment=ft.MainAxisAlignment.CENTER)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                )
            )
        )

    # ================= MÀN HÌNH ĐĂNG KÝ HỒ SƠ =================
    SERVICE_OPTIONS = ["Vá lốp / thay lốp", "Tiếp xăng khẩn cấp", "Sửa xe tại chỗ", "Kéo xe / cứu hộ"]

    def build_register_view():
        # Dọn các FilePicker của lần mở màn hình trước để overlay không bị phình ra
        for old in register_pickers:
            if old in page.overlay:
                page.overlay.remove(old)
        register_pickers.clear()

        def field(label, icon, **kw):
            return ft.TextField(label=label, prefix_icon=icon, border_radius=8, focused_border_color="#EE4D2D", **kw)

        txt_fullname = field("Họ và tên", ic("PERSON_OUTLINE"))
        txt_birth = field("Ngày sinh (DD/MM/YYYY)", ic("CAKE_OUTLINED"), keyboard_type=ft.KeyboardType.DATETIME, max_length=10)
        txt_phone = field("Số điện thoại đăng ký", ic("PHONE_ANDROID"), keyboard_type=ft.KeyboardType.PHONE)
        txt_email = field("Email (không bắt buộc)", ic("EMAIL_OUTLINED"), keyboard_type=ft.KeyboardType.EMAIL)
        txt_cccd = field("Số CCCD / CMND", ft.icons.BADGE, keyboard_type=ft.KeyboardType.NUMBER)
        txt_plate = field("Biển số xe (VD: 59A1-123.45)", ic("TWO_WHEELER"))
        txt_password = field("Mật khẩu (tối thiểu 6 ký tự)", ic("LOCK_OUTLINE"), password=True, can_reveal_password=True)
        txt_confirm = field("Nhập lại mật khẩu", ic("LOCK_OUTLINE"), password=True, can_reveal_password=True)

        dd_city = ft.Dropdown(
            label="Khu vực hoạt động", border_radius=8, focused_border_color="#EE4D2D",
            options=[ft.dropdown.Option(c) for c in ["TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Bình Dương"]],
            value="TP. Hồ Chí Minh",
        )
        dd_vehicle = ft.Dropdown(
            label="Loại phương tiện", border_radius=8, focused_border_color="#EE4D2D",
            options=[ft.dropdown.Option(v) for v in ["Xe máy", "Ô tô", "Xe tải / xe cứu hộ chuyên dụng"]],
            value="Xe máy",
        )

        service_checks = [ft.Checkbox(label=name, value=False, active_color="#EE4D2D") for name in SERVICE_OPTIONS]
        txt_services_error = ft.Text("", size=11, color=ft.colors.RED_600, visible=False)

        chk_terms = ft.Checkbox(label="Tôi cam kết thông tin chính xác và đồng ý Điều khoản sử dụng của P2P SOS", value=False, active_color="#EE4D2D")
        txt_terms_error = ft.Text("Bạn cần đồng ý điều khoản để tiếp tục", size=11, color=ft.colors.RED_600, visible=False)

        # --- chọn ảnh: chọn xong là tải thẳng lên server, lưu lại mã ảnh (file_id) ---
        IMAGE_KIND = {"avatar": "avatar", "cccd": "cccd", "gplx": "license"}
        picked = {"avatar": None, "cccd": None, "gplx": None}      # key -> file_id server trả về
        status_texts = {k: ft.Text("Chưa chọn ảnh", size=11, color=ft.colors.GREY_600) for k in picked}
        web_uploads = {}   # chế độ web: tên file gốc -> (key, tên tạm trong UPLOAD_DIR)

        def set_status(key, text, ok=None):
            status_texts[key].value = text
            status_texts[key].color = (ft.colors.GREEN_700 if ok is True
                                       else ft.colors.RED_600 if ok is False
                                       else ft.colors.GREY_600)
            page.update()

        def send_image(key, filename, raw):
            """Gửi ảnh (bytes) lên server; thành công thì nhớ file_id để đăng ký."""
            picked[key] = None
            if not raw:
                set_status(key, "File ảnh rỗng, vui lòng chọn ảnh khác", False)
                return
            if len(raw) > MAX_IMAGE_BYTES:
                set_status(key, "Ảnh quá lớn (tối đa 8MB), vui lòng chọn ảnh khác", False)
                return
            set_status(key, f"Đang tải lên {filename}...")
            try:
                res = requests.post(
                    f"{BACKEND_URL}/api/upload",
                    json={"kind": IMAGE_KIND[key], "filename": filename, "data_base64": base64.b64encode(raw).decode("ascii")},
                    timeout=UPLOAD_TIMEOUT,
                )
            except requests.exceptions.RequestException:
                set_status(key, "Không kết nối được máy chủ, hãy chọn lại ảnh", False)
                return
            if res.status_code == 200:
                picked[key] = res.json().get("file_id")
                set_status(key, f"✓ {filename} (đã tải lên)", True)
            else:
                try:
                    detail = res.json().get("detail")
                except ValueError:
                    detail = None
                set_status(key, detail if isinstance(detail, str) else "Tải ảnh thất bại, hãy chọn lại", False)

        def make_picker(key):
            def on_result(ev: ft.FilePickerResultEvent):
                if not ev.files:
                    return
                f = ev.files[0]
                picked[key] = None
                if f.size and f.size > MAX_IMAGE_BYTES:
                    set_status(key, "Ảnh quá lớn (tối đa 8MB), vui lòng chọn ảnh khác", False)
                    return
                if f.path:
                    # Chạy bản máy tính: đọc thẳng file từ ổ đĩa
                    try:
                        with open(f.path, "rb") as fh:
                            raw = fh.read()
                    except OSError:
                        set_status(key, "Không đọc được file ảnh", False)
                        return
                    send_image(key, f.name, raw)
                else:
                    # Chạy bản web (điện thoại/trình duyệt): ảnh phải được tải về app trước
                    ext = os.path.splitext(f.name)[1].lower()
                    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
                        ext = ".jpg"
                    temp_name = f"{uuid.uuid4().hex}{ext}"
                    web_uploads[f.name] = (key, temp_name)
                    set_status(key, f"Đang tải lên {f.name}...")
                    try:
                        picker.upload([ft.FilePickerUploadFile(f.name, upload_url=page.get_upload_url(temp_name, 300))])
                    except Exception as ex:
                        web_uploads.pop(f.name, None)
                        print("Lỗi tải ảnh lên (web):", repr(ex))
                        set_status(key, "Không tải được ảnh lên, hãy thử lại", False)

            def on_upload(ev: ft.FilePickerUploadEvent):
                info = web_uploads.get(ev.file_name)
                if not info:
                    return
                k, temp_name = info
                if ev.error:
                    web_uploads.pop(ev.file_name, None)
                    set_status(k, "Tải ảnh lên thất bại, hãy thử lại", False)
                    return
                if ev.progress is not None and ev.progress >= 1.0:
                    web_uploads.pop(ev.file_name, None)
                    temp_path = os.path.join(UPLOAD_DIR, temp_name)
                    try:
                        with open(temp_path, "rb") as fh:
                            raw = fh.read()
                    except OSError:
                        set_status(k, "Không đọc được ảnh vừa tải, hãy thử lại", False)
                        return
                    finally:
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                    send_image(k, ev.file_name, raw)

            picker = ft.FilePicker(on_result=on_result, on_upload=on_upload)
            page.overlay.append(picker)
            register_pickers.append(picker)
            return picker

        pickers = {k: make_picker(k) for k in picked}
        page.update()

        def upload_row(key, icon, title):
            return ft.Container(
                padding=10, border=ft.border.all(1, ft.colors.GREY_300), border_radius=8,
                content=ft.Row([
                    ft.Icon(icon, color="#EE4D2D"),
                    ft.Column([ft.Text(title, size=12, weight=ft.FontWeight.W_500), status_texts[key]], expand=True, spacing=2),
                    ft.OutlinedButton("Chọn ảnh", on_click=lambda e, k=key: pickers[k].pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)),
                ])
            )

        # Không đặt expand=True trực tiếp cho nút trong Column/ListView (chiều cao không giới hạn sẽ làm
        # Flet không vẽ được form). Bọc nút trong Row để nút giãn theo chiều ngang.
        btn_submit = ft.ElevatedButton(
            text="GỬI HỒ SƠ VÀ ĐĂNG KÝ", bgcolor="#EE4D2D", color=ft.colors.WHITE, height=48, expand=True,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )

        def validate():
            name = " ".join((txt_fullname.value or "").split())
            birth_text = (txt_birth.value or "").strip()
            phone = (txt_phone.value or "").replace(" ", "")
            email = (txt_email.value or "").strip()
            cccd = (txt_cccd.value or "").strip()
            plate = (txt_plate.value or "").strip().upper()
            pw = txt_password.value or ""
            ok = True

            for f in (txt_fullname, txt_birth, txt_phone, txt_email, txt_cccd, txt_plate, txt_password, txt_confirm):
                f.error_text = None

            if len(name) < 2:
                txt_fullname.error_text = "Vui lòng nhập họ và tên"
                ok = False

            try:
                born = datetime.strptime(birth_text, "%d/%m/%Y").date()
            except ValueError:
                born = None
            if born is None:
                txt_birth.error_text = "Nhập đúng định dạng DD/MM/YYYY"
                ok = False
            else:
                today = date.today()
                age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                if age < 18:
                    txt_birth.error_text = "Bạn phải từ đủ 18 tuổi trở lên"
                    ok = False
                elif age > 80:
                    txt_birth.error_text = "Ngày sinh không hợp lệ"
                    ok = False

            if not (phone.isdigit() and len(phone) == 10 and phone.startswith("0")):
                txt_phone.error_text = "Số điện thoại gồm 10 chữ số, bắt đầu bằng 0"
                ok = False
            if email and not ("@" in email and "." in email.split("@")[-1] and " " not in email):
                txt_email.error_text = "Email không hợp lệ"
                ok = False
            if not (cccd.isdigit() and len(cccd) in (9, 12)):
                txt_cccd.error_text = "CCCD gồm 12 số (CMND cũ gồm 9 số)"
                ok = False
            if len(plate.replace(" ", "")) < 5:
                txt_plate.error_text = "Vui lòng nhập biển số xe"
                ok = False
            if len(pw) < 6:
                txt_password.error_text = "Mật khẩu tối thiểu 6 ký tự"
                ok = False
            if txt_confirm.value != pw:
                txt_confirm.error_text = "Mật khẩu nhập lại không khớp"
                ok = False

            services = [c.label for c in service_checks if c.value]
            txt_services_error.value = "Chọn ít nhất 1 dịch vụ bạn có thể hỗ trợ"
            txt_services_error.visible = not services
            ok = ok and bool(services)

            txt_terms_error.visible = not chk_terms.value
            ok = ok and bool(chk_terms.value)

            return ok, {
                "full_name": name, "birth_date": birth_text, "phone": phone, "email": email or None,
                "cccd": cccd, "license_plate": plate, "services": services,
            }

        def submit_registration(e):

            ok, info = validate()
            page.update()
            if not ok:
                show_snack("Vui lòng kiểm tra lại các thông tin bị báo lỗi!")
                return
            if not (picked["avatar"] and picked["cccd"] and picked["gplx"]):
                show_snack("Vui lòng chọn đủ 3 ảnh (chân dung, CCCD, bằng lái/cà vẹt) và chờ tải xong dấu ✓!")
                return

            btn_submit.disabled = True
            btn_submit.text = "ĐANG GỬI HỒ SƠ..."
            page.update()

            payload = dict(info)
            payload.update({
                "city": dd_city.value,
                "vehicle_type": dd_vehicle.value,
                "password": txt_password.value,
                "avatar_image": picked["avatar"],
                "cccd_image": picked["cccd"],
                "license_image": picked["gplx"],
                "agreed_terms": bool(chk_terms.value),
            })

            try:
                res = requests.post(f"{BACKEND_URL}/api/auth/register", json=payload, timeout=TIMEOUT)
            except requests.exceptions.RequestException:
                show_snack("Không kết nối được máy chủ. Vui lòng thử lại!")
            else:
                if res.status_code == 200:
                    def close_notice(ev=None):
                        notice_dialog.open = False
                        page.update()

                    notice_dialog = ft.AlertDialog(
                        modal=True,
                        title=ft.Text("Đã gửi hồ sơ thành công"),
                        content=ft.Text(
                            "Hồ sơ của bạn đang chờ duyệt. Bạn có thể đăng nhập để dùng chức năng "
                            "Gọi cứu hộ ngay. Chế độ thợ (nhận đơn) chỉ bật được sau khi hồ sơ được duyệt."
                        ),
                        actions=[ft.TextButton("Đã hiểu", on_click=close_notice)],
                    )
                    main_view_container.content = build_login_view(info["phone"])
                    page.dialog = notice_dialog
                    notice_dialog.open = True
                    page.update()
                    return
                try:
                    detail = res.json().get("detail")
                except ValueError:
                    detail = None
                show_snack(detail if isinstance(detail, str) else "Đăng ký thất bại, vui lòng kiểm tra lại thông tin!")

            btn_submit.disabled = False
            btn_submit.text = "GỬI HỒ SƠ VÀ ĐĂNG KÝ"
            page.update()

        btn_submit.on_click = submit_registration

        def back_to_login(e):
            main_view_container.content = build_login_view()
            page.update()

        def section(title):
            return ft.Text(title, weight=ft.FontWeight.BOLD, size=13, color="#212529")

        form_column = ft.Column([
            ft.Text("Đăng ký Đối tác P2P SOS", weight=ft.FontWeight.BOLD, size=14, color="#EE4D2D"),
            ft.Text("Vui lòng nhập thông tin chính xác để hệ thống xét duyệt.", size=12, color=ft.colors.GREY_600),
            ft.Divider(),
            section("1. Thông tin cá nhân"),
            txt_fullname, txt_birth, txt_phone, txt_email, txt_cccd,
            section("2. Phương tiện & khu vực"),
            dd_vehicle, txt_plate, dd_city,
            section("3. Dịch vụ có thể hỗ trợ"),
            ft.Column(service_checks, spacing=0),
            txt_services_error,
            section("4. Mật khẩu đăng nhập"),
            txt_password, txt_confirm,
            section("5. Tải lên hồ sơ chứng thực"),
            upload_row("avatar", ic("FACE"), "Ảnh chân dung (rõ mặt)"),
            upload_row("cccd", ft.icons.CREDIT_CARD, "Ảnh Mặt trước CCCD/CMND"),
            upload_row("gplx", ft.icons.DIRECTIONS_CAR, "Ảnh Bằng lái xe / Cà vẹt xe"),
            chk_terms,
            txt_terms_error,
            ft.Row([btn_submit]),
        ], spacing=10)

        return ft.Container(
            expand=True,
            bgcolor="#F8F9FA",
            content=ft.Column([
                ft.Container(
                    bgcolor=ft.colors.WHITE, padding=12,
                    content=ft.Row([
                        ft.IconButton(icon=ft.icons.ARROW_BACK, on_click=back_to_login),
                        ft.Text("TẠO TÀI KHOẢN HỒ SƠ", weight=ft.FontWeight.BOLD, size=15, color="#212529")
                    ])
                ),
                ft.Container(
                    expand=True, padding=15,
                    content=ft.ListView([
                        ft.Card(
                            elevation=3,
                            content=ft.Container(padding=20, bgcolor=ft.colors.WHITE, border_radius=12, content=form_column)
                        )
                    ], expand=True)
                )
            ], expand=True, spacing=0)
        )

    # ================= GIAO DIỆN CHÍNH CỦA ỨNG DỤNG =================
    def load_main_app_layout():
        is_active = False
        current_tab = "GOI_CUU_HO"
        last_sig = {"customer": None, "helper": None}
        status_check = {"n": 0}

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
        # Số đơn nhỏ hiện cạnh chữ "ĐI CỨU HỘ" (ẩn khi không có đơn)
        badge_text = ft.Text("0", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
        badge_dot = ft.Container(
            content=badge_text, bgcolor="#EE4D2D", border_radius=10,
            width=18, height=18, alignment=ft.alignment.center, visible=False
        )
        badge_state = {"n": 0}

        def set_badge(n):
            """Cập nhật số đơn trên tab. Trả về True nếu có thay đổi (để gọi page.update())."""
            if n == badge_state["n"]:
                return False
            badge_state["n"] = n
            badge_text.value = str(n) if n < 100 else "99+"
            badge_dot.width = 18 if n < 10 else (24 if n < 100 else 30)
            badge_dot.visible = n > 0
            return True

        def badge_count(pending, helper_order, cust_order):
            # Đang làm dở 1 đơn -> hiện 1. Chưa có đơn nào đang làm -> đếm đơn chờ + đơn đang thương lượng.
            if helper_order:
                return 1
            if not is_active:
                return 0
            return len(pending) + (1 if (cust_order or {}).get("status") == "CHATTING" else 0)

        tab_di_cuu_ho = ft.Container(
            content=ft.Row([
                ft.Text("ĐI CỨU HỘ", weight=ft.FontWeight.BOLD, color=ft.colors.GREY_800),
                badge_dot,
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=6),
            alignment=ft.alignment.center, expand=True, padding=14
        )

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
                return
            try:
                gl = cls()
                page.overlay.append(gl)
                page.update()
                gps_state["geolocator"] = gl
            except Exception:
                pass

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
            return None

        def ip_location():
            if ip_cache["pos"] and time.time() - ip_cache["at"] < 600:
                return ip_cache["pos"]
            try:
                r = requests.get("http://ip-api.com/json/?fields=status,lat,lon", timeout=TIMEOUT).json()
                if r.get("status") == "success":
                    ip_cache["pos"] = (float(r["lat"]), float(r["lon"]))
                    ip_cache["at"] = time.time()
            except Exception:
                pass
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
            except Exception:
                pass

        def location_loop():
            last_customer_push = 0.0
            last_heartbeat = 0.0
            while True:
                time.sleep(3)
                try:
                    if time.time() - last_heartbeat >= 5:
                        send_heartbeat()
                        last_heartbeat = time.time()
                    if auth_state["helper_name"]:  # luôn báo vị trí khi còn đơn đang làm, kể cả lúc đang Tạm nghỉ
                        data = safe_get_json(f"{BACKEND_URL}/api/rescue/current-helper/{auth_state['helper_name']}")
                        rh = data.get("data") if data else None
                        if rh and rh.get("status") == "NEGOTIATING":
                            lat, lng, src = get_location()
                            post_location(rh["id"], "helper", lat, lng, src)
                    if time.time() - last_customer_push >= 6:
                        data = safe_get_json(f"{BACKEND_URL}/api/sos/current/{auth_state['phone']}")
                        rc = data.get("data") if data else None
                        if rc and rc.get("status") in ("PENDING", "WAITING_APPROVAL", "CHATTING", "NEGOTIATING", "ARRIVED"):
                            lat, lng, src = get_location()
                            post_location(rc["id"], "customer", lat, lng, src)
                        last_customer_push = time.time()
                except Exception:
                    pass

        settings = {"radius_km": 5.0, "auto_accept": False}
        offer_state = {"order_id": None, "dialog": None, "txt_left": None}

        def send_heartbeat():
            try:
                lat, lng, _src = get_location()
                requests.post(f"{BACKEND_URL}/api/helper/heartbeat", json={"helper_name": auth_state["helper_name"], "lat": lat, "lng": lng, "is_active": is_active}, timeout=TIMEOUT)
            except Exception:
                pass

        def load_settings():
            try:
                data = safe_get_json(f"{BACKEND_URL}/api/helper/settings/{auth_state['helper_name']}")
                r = data.get("data") if data else None
                if r:
                    settings.update(radius_km=float(r["radius_km"]), auto_accept=bool(r["auto_accept"]))
            except Exception:
                pass

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
                    requests.post(f"{BACKEND_URL}/api/helper/settings", json={"helper_name": auth_state["helper_name"], "radius_km": settings["radius_km"], "auto_accept": settings["auto_accept"]}, timeout=TIMEOUT)
                except Exception:
                    pass
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
                            ft.Text("Khi có đơn trong khoảng cách nhận đơn, hệ thống chọn 1 tài xế phù hợp nhất và hiện popup.", size=12, color=ft.colors.GREY_600),
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
            payload = {"order_id": order_id, "helper_name": auth_state["helper_name"], "action": action}
            if price is not None:
                payload["proposed_price"] = price
            try:
                res = requests.post(f"{BACKEND_URL}/api/rescue/offer-response", json=payload, timeout=TIMEOUT)
                if res.status_code != 200:
                    show_snack("Không thực hiện được")
            except Exception:
                pass
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
            data = safe_get_json(f"{BACKEND_URL}/api/rescue/offer/{auth_state['helper_name']}")
            r = data.get("data") if data else None
            if not r:
                if offer_state["order_id"] is not None:
                    close_offer_dialog()
                return
            if offer_state["order_id"] == r["id"]:
                if offer_state["txt_left"]:
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
                    content=ft.Icon(ic("TWO_WHEELER"), color=ft.colors.WHITE, size=22),
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

            layout(order)
            return holder, lambda o: place_markers(o)

        tracking = {"order_id": None, "root": None, "map_update": None, "title": None, "eta": None, "dist": None}
        helper_map = {"order_id": None, "root": None, "update": None}

        def update_tracking(order):
            progress = order.get("progress") or 0.0
            status = order.get("status")
            if tracking["map_update"]:
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
                res_data = safe_get_json(f"{BACKEND_URL}/api/sos/current/{auth_state['phone']}")
                if res_data:
                    order = extract_order(res_data)

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
                            except Exception:
                                pass
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
            except Exception:
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
                    "customer_phone": auth_state["phone"],
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
            except Exception:
                show_snack("Không kết nối được server!")

        def handle_price_action(order_id, action):
            try:
                requests.post(f"{BACKEND_URL}/api/sos/price-action", json={"order_id": order_id, "action": action}, timeout=TIMEOUT)
            except Exception:
                pass
            last_sig["customer"] = None
            poll_customer_order()

        def open_cancel_dialog(order_id):
            def confirm_cancel(e):
                reason = txt_cancel_reason.value
                if not reason:
                    return
                try:
                    requests.post(f"{BACKEND_URL}/api/sos/cancel", json={"order_id": order_id, "reason": reason}, timeout=TIMEOUT)
                except Exception:
                    pass
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
                    res = requests.post(f"{BACKEND_URL}/api/rescue/accept", json={"order_id": order_id, "proposed_price": price, "helper_name": auth_state["helper_name"]}, timeout=TIMEOUT)
                    if res.status_code != 200:
                        show_snack("Không nhận được đơn")
                except Exception:
                    pass
                dialog.open = False
                switch_tab("DI_CUU_HO")

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
                    ft.OutlinedButton("Đồng ý giá khách", on_click=lambda e: send_accept(customer_price)),
                    ft.ElevatedButton("Gửi giá đề nghị", bgcolor="#EE4D2D", color=ft.colors.WHITE, on_click=lambda e: submit_custom_price(e)),
                ]
            )

            def submit_custom_price(e):
                new_price = parse_price(txt_input_price.value)
                if new_price is None:
                    txt_input_price.error_text = "Giá không hợp lệ"
                    page.update()
                    return
                send_accept(new_price)

            page.dialog = dialog
            dialog.open = True
            page.update()

        def open_chat_and_reoffer_dialog(order_id):
            txt_reoffer_price = ft.TextField(label="Đề xuất giá mới sau thương lượng (VNĐ)", border_radius=8, keyboard_type=ft.KeyboardType.NUMBER, expand=True)
            txt_helper_chat = ft.TextField(label="Nhập tin nhắn...", border_radius=8, expand=True)
            chat_history_list = ft.ListView(expand=1, spacing=8, padding=10)

            def load_chat_messages():
                res_data = safe_get_json(f"{BACKEND_URL}/api/rescue/chatting/{auth_state['helper_name']}")
                if res_data:
                    order_data = extract_order(res_data)
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

            def send_helper_msg(e):
                if not txt_helper_chat.value:
                    return
                try:
                    requests.post(f"{BACKEND_URL}/api/sos/chat/send", json={"order_id": order_id, "sender": "helper", "message": txt_helper_chat.value}, timeout=TIMEOUT)
                except Exception:
                    pass
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
                except Exception:
                    pass
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
            except Exception:
                pass
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

                order = None
                try:
                    res_working = safe_get_json(f"{BACKEND_URL}/api/rescue/current-helper/{auth_state['helper_name']}")
                    order = extract_order(res_working) if res_working else None
                except Exception:
                    pass

                if order and order.get("status") in ("NEGOTIATING", "ARRIVED"):
                    oid = order.get("id")
                    if order.get("status") == "NEGOTIATING":
                        update_helper_status(oid, "ARRIVED")
                    else:
                        update_helper_status(oid, "COMPLETED")
                elif not is_active:
                    set_active_state(True)

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
                if not is_approved():
                    # Hồ sơ chưa được duyệt: khóa chức năng thợ
                    set_badge(0)
                    render_locked_view()
                    bottom_container.current.visible = False
                    page.update()
                    return

                res_working = safe_get_json(f"{BACKEND_URL}/api/rescue/current-helper/{auth_state['helper_name']}")
                order = extract_order(res_working) if res_working else None

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
                    set_badge(1)

                    notice = ft.Container(
                        visible=not is_active, padding=10, border_radius=8, bgcolor=ft.colors.ORANGE_50,
                        content=ft.Row([
                            ft.Icon(ic("INFO_OUTLINE", ft.icons.INFO), color=ft.colors.ORANGE_800, size=18),
                            ft.Text("Bạn đang Tạm nghỉ nhưng đơn này chưa hoàn thành. Hãy hoàn tất đơn trước nhé!", size=12, color=ft.colors.ORANGE_900, expand=True),
                        ])
                    )

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
                                    notice,
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

                if not is_active:
                    # Tạm nghỉ và không còn đơn nào đang làm -> màn hình nghỉ
                    set_badge(0)
                    txt_slider_label.value = "Sẵn sàng hoạt động"
                    render_resting_view()
                    bottom_container.current.visible = True
                    page.update()
                    return

                res = safe_get_json(f"{BACKEND_URL}/api/rescue/pending", params={"helper_name": auth_state["helper_name"]})
                res_all = safe_get_json(f"{BACKEND_URL}/api/rescue/chatting/{auth_state['helper_name']}")

                rescue_orders_list = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)

                if res and "data" in res:
                    for item in res.get("data", []):
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

                if res_all:
                    cur_order = extract_order(res_all)
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
                set_badge(real_count)

                if not rescue_orders_list.controls:
                    rescue_orders_list.controls.append(
                        ft.Container(
                            padding=60, alignment=ft.alignment.center,
                            content=ft.Column([
                                ft.Icon(ft.icons.RADAR, size=60, color=ft.colors.GREY_400),
                                ft.Container(height=10),
                                ft.Text(f"Chưa có đơn cứu hộ nào trong bán kính {settings['radius_km']:g} km quanh bạn.", color=ft.colors.GREY_600, size=14, text_align=ft.TextAlign.CENTER),
                                ft.Text(
                                    "Vị trí của bạn đang lấy từ: " + {
                                        "gps": "GPS",
                                        "ip": "địa chỉ mạng (IP) - có thể lệch nhiều km",
                                        "default": "vị trí mặc định",
                                    }.get((loc_cache["val"] or (0, 0, ""))[2], "đang xác định..."),
                                    color=ft.colors.GREY_500, size=11, text_align=ft.TextAlign.CENTER,
                                ),
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
            except Exception:
                pass

        def is_approved():
            return auth_state.get("status") == "APPROVED"

        def update_header_text():
            if not is_approved():
                txt_status_header.value = "Chờ duyệt hồ sơ"
            else:
                txt_status_header.value = "Đang hoạt động" if is_active else "Tạm nghỉ"

        def refresh_account_status():
            """Hỏi server trạng thái hồ sơ hiện tại. Trả về True nếu hồ sơ đã được duyệt."""
            data = safe_get_json(f"{BACKEND_URL}/api/auth/status/{auth_state['phone']}")
            new_status = ((data or {}).get("data") or {}).get("status")
            if not new_status or new_status == auth_state.get("status"):
                return is_approved()

            was_approved = is_approved()
            auth_state["status"] = new_status
            now_approved = is_approved()

            if now_approved and not was_approved:
                show_snack("Hồ sơ của bạn đã được duyệt! Bạn có thể bật chế độ thợ.")
            if was_approved and not now_approved and is_active:
                set_active_state(False)
            update_header_text()
            if now_approved != was_approved and current_tab == "DI_CUU_HO":
                fetch_helper_working_view()
            page.update()
            return now_approved

        def render_locked_view():
            rejected = auth_state.get("status") == "REJECTED"
            title = "Hồ sơ chưa được chấp nhận" if rejected else "Hồ sơ đang chờ duyệt"
            body = (
                "Hồ sơ của bạn chưa được chấp nhận nên chưa thể làm thợ. Vui lòng liên hệ hỗ trợ."
                if rejected else
                "Sau khi hồ sơ được duyệt, bạn mới bật được chế độ thợ để nhận đơn cứu hộ. "
                "Trong lúc chờ, bạn vẫn dùng được chức năng Gọi cứu hộ."
            )

            def check_again(e):
                if not refresh_account_status():
                    show_snack("Hồ sơ vẫn chưa được duyệt, vui lòng quay lại sau!")

            content_column.controls = [
                ft.Container(
                    expand=True, alignment=ft.alignment.center, padding=20,
                    content=ft.Column([
                        ft.Container(content=ft.Icon(ic("HOURGLASS_TOP", ft.icons.LOCK), size=60, color="#EE4D2D"), bgcolor=ft.colors.ORANGE_50, padding=25, border_radius=50),
                        ft.Container(height=20),
                        ft.Text(title, weight=ft.FontWeight.BOLD, size=18, color="#212529"),
                        ft.Container(height=8),
                        ft.Text(body, text_align=ft.TextAlign.CENTER, color=ft.colors.GREY_600, size=13),
                        ft.Container(height=16),
                        ft.ElevatedButton("Kiểm tra lại", on_click=check_again, bgcolor="#EE4D2D", color=ft.colors.WHITE),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                )
            ]

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
                fetch_helper_working_view()
            page.update()

        def set_active_state(active: bool):
            nonlocal is_active
            if active and not is_approved():
                refresh_account_status()
                if not is_approved():
                    show_snack("Hồ sơ của bạn chưa được duyệt nên chưa thể bật chế độ thợ!")
                    if status_switch.current:
                        status_switch.current.value = False
                    page.update()
                    return
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
                    fetch_helper_working_view()  # còn đơn đang làm thì vẫn hiện, không thì về màn hình nghỉ

            if status_switch.current:
                status_switch.current.value = active
            update_header_text()
            page.update()
            threading.Thread(target=send_heartbeat, daemon=True).start()

        def auto_refresh():
            while True:
                time.sleep(POLL_INTERVAL)
                try:
                    if not is_approved():
                        status_check["n"] += 1
                        if status_check["n"] % 5 == 0:
                            refresh_account_status()

                    if is_active and settings["auto_accept"]:
                        check_offer()
                    elif offer_state["order_id"] is not None:
                        close_offer_dialog()

                    if current_tab == "DI_CUU_HO":
                        # Tạm nghỉ vẫn theo dõi đơn đang làm dở; chỉ khi đang hoạt động mới lấy thêm đơn chờ
                        res = (safe_get_json(f"{BACKEND_URL}/api/rescue/pending", params={"helper_name": auth_state["helper_name"]}) or {}) if is_active else {}
                        res_h = safe_get_json(f"{BACKEND_URL}/api/rescue/current-helper/{auth_state['helper_name']}") or {}
                        res_c = (safe_get_json(f"{BACKEND_URL}/api/rescue/chatting/{auth_state['helper_name']}") or {}) if is_active else {}
                        helper_order = res_h.get("data") or {}
                        cust_order = res_c.get("data") or {}
                        if set_badge(badge_count(res.get("data") or [], helper_order, cust_order)):
                            page.update()
                        sig = (
                            tuple(o["id"] for o in (res.get("data") or [])),
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
                        res = safe_get_json(f"{BACKEND_URL}/api/sos/current/{auth_state['phone']}") or {}
                        o = res.get("data") or {}
                        sig = (o.get("id"), o.get("status"), o.get("proposed_price"), o.get("price"), len(o.get("messages", [])))
                        if o.get("status") in ("NEGOTIATING", "ARRIVED"):
                            last_sig["customer"] = sig
                            poll_customer_order()
                        elif sig != last_sig["customer"]:
                            last_sig["customer"] = sig
                            poll_customer_order()

                        # Cập nhật số đơn trên tab "ĐI CỨU HỘ" dù đang đứng ở tab "GỌI CỨU HỘ"
                        res_h = safe_get_json(f"{BACKEND_URL}/api/rescue/current-helper/{auth_state['helper_name']}") or {}
                        res_p = (safe_get_json(f"{BACKEND_URL}/api/rescue/pending", params={"helper_name": auth_state["helper_name"]}) or {}) if is_active else {}
                        res_hc = (safe_get_json(f"{BACKEND_URL}/api/rescue/chatting/{auth_state['helper_name']}") or {}) if is_active else {}
                        if set_badge(badge_count(res_p.get("data") or [], res_h.get("data") or {}, res_hc.get("data") or {})):
                            page.update()
                except Exception:
                    pass

        def logout_account(e):
            auth_state["logged_in"] = False
            main_view_container.content = build_login_view()
            page.update()

        drawer_content = ft.NavigationDrawer(
            bgcolor=ft.colors.WHITE,
            controls=[
                ft.Container(
                    content=ft.Column([
                        ft.CircleAvatar(radius=35, content=ft.Icon(ft.icons.PERSON, size=35, color=ft.colors.WHITE), bgcolor="#EE4D2D"),
                        ft.Container(height=10),
                        ft.Text(f"SĐT: {auth_state['phone']}", weight=ft.FontWeight.BOLD, size=15),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=25
                ),
                ft.Divider(height=1),
                ft.ListTile(title=ft.Row([ft.Text("Trạng thái hoạt động", weight=ft.FontWeight.W_500), ft.Switch(ref=status_switch, value=False, active_color="#EE4D2D", on_change=lambda e: set_active_state(e.control.value))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)),
                ft.Divider(height=1),
                ft.ListTile(leading=ft.Icon(ft.icons.SETTINGS_OUTLINED, color="#EE4D2D"), title=ft.Text("Cài đặt"), on_click=open_settings_dialog),
                ft.ListTile(leading=ft.Icon(ft.icons.LOGOUT, color=ft.colors.RED), title=ft.Text("Đăng xuất tài khoản"), on_click=logout_account),
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
                ft.Column([ft.Text(f"Tài khoản: {auth_state['phone']}", weight=ft.FontWeight.BOLD, size=14, color="#212529"), txt_status_header], spacing=0)
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

        shell_content = ft.Column([header, tabs_bar, content_area_container, bottom_slider_container], spacing=0, expand=True)

        main_view_container.content = shell_content
        update_header_text()
        switch_tab("GOI_CUU_HO")
        threading.Thread(target=auto_refresh, daemon=True).start()
        setup_geolocator()
        threading.Thread(target=load_settings, daemon=True).start()
        threading.Thread(target=location_loop, daemon=True).start()
        page.update()

    # Khởi tạo Màn hình Đăng nhập
    main_view_container.content = build_login_view()

    # Khung "điện thoại": rộng tối đa PHONE_MAX_WIDTH, cao bằng cửa sổ, luôn căn giữa.
    # Không dùng expand=True cho khung này vì expand sẽ ghi đè width và làm giao diện bè ra trên web.
    PHONE_MAX_WIDTH = 420

    shell = ft.Container(
        content=main_view_container,
        width=PHONE_MAX_WIDTH,
        height=page.height or 800,
        bgcolor="#F8F9FA",
        border=ft.border.symmetric(vertical=ft.border.BorderSide(1, "#DEE2E6")),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    def fit_shell(e=None):
        shell.width = min(PHONE_MAX_WIDTH, page.width or PHONE_MAX_WIDTH)
        shell.height = page.height or 800
        try:
            shell.update()
        except Exception:
            pass

    page.on_resize = fit_shell
    page.add(ft.Row([shell], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.START, expand=True))
    fit_shell()


port = os.environ.get("PORT")
if port:
    ft.app(target=main, view=None, host="0.0.0.0", port=int(port), upload_dir=UPLOAD_DIR)
else:
    ft.app(target=main, upload_dir=UPLOAD_DIR)