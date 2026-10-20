# macUSB Win — tạo USB Recovery cho Mac Intel trên Windows

Tải **macUSB-Win.exe** bên dưới, chạy (Windows sẽ hỏi quyền Administrator), rồi:

1. Chọn phiên bản macOS (danh sách có ghi đời máy hỗ trợ).
2. Cắm USB (khuyên dùng 8 GB trở lên) → bấm **Làm mới** → chọn ổ USB.
3. Bấm **Tạo USB Recovery**. USB sẽ bị **xoá sạch**.

App tải ảnh Recovery trực tiếp từ máy chủ Apple, kiểm tra chữ ký số của Apple, định dạng USB FAT32 và chép bộ khởi động OpenCore tối giản (không kext, không sửa NVRAM/SMBIOS).

## Khởi động trên Mac
1. Cắm USB, bật máy và giữ phím **Option (⌥)**.
2. Chọn **EFI Boot**, rồi chọn mục **macOS Recovery / macOS Base System**.
3. Kết nối Wi-Fi, chọn **Reinstall macOS** (cài qua Internet).

**Mac có chip T2 (đa số đời 2018–2020):** vào Recovery của máy (⌘R) → Utilities → Startup Security Utility → **No Security** + **Allow booting from external media**. Mac 2017 trở về trước không cần bước này.

Không dùng cho Mac chip M (Apple silicon).

Nếu Windows SmartScreen cảnh báo (app chưa ký số): bấm **More info → Run anyway**.

Ảnh Recovery: © Apple. Bộ khởi động: OpenCore © Acidanthera (BSD-3-Clause). Giao thức Recovery theo macrecovery.py của OpenCorePkg.
