# macUSB Win — tạo USB Recovery cho Mac Intel trên Windows

Tải **macUSB-Win.exe** bên dưới, chạy (Windows sẽ hỏi quyền Administrator). App làm theo từng bước:

1. **Chọn nguồn**
   - *Recovery từ Apple*: chọn phiên bản macOS (có ghi đời máy hỗ trợ) hoặc tự nhập board-id.
   - *Trình tải bộ cài macOS*: danh sách bộ cài đầy đủ từ Apple, kể cả **Public Beta**. Tải được file `InstallAssistant.pkg` (có kiểm tra toàn vẹn, tải tiếp khi bị ngắt), hoặc tạo USB Recovery cùng phiên bản.
   - *Nguồn trên máy*: file `BaseSystem.dmg` / `RecoveryImage.dmg` (kèm `.chunklist`) hoặc thư mục `com.apple.recovery.boot`.
2. **Chọn ổ USB** (chỉ hiện USB/thẻ nhớ).
3. **Xem lại thông tin** trước khi xoá USB.
4. **Theo dõi từng giai đoạn**: tải → kiểm tra chữ ký Apple → định dạng → chép OpenCore → chép Recovery → kiểm tra USB.
5. **Kết quả**: nút **Tháo USB an toàn** ngay trên màn hình cuối.

Giới hạn của Windows: file `.pkg` bộ cài đầy đủ không biến thành USB cài offline được (cần `createinstallmedia` trên Mac). USB tạo ra là USB Recovery — cài macOS qua Internet.

## Khởi động trên Mac
1. Cắm USB, bật máy và giữ phím **Option (⌥)**.
2. Chọn **EFI Boot**, rồi chọn mục **macOS Recovery / macOS Base System**.
3. Kết nối Wi-Fi, chọn **Reinstall macOS** (cài qua Internet).

**Mac có chip T2 (đa số đời 2018–2020):** vào Recovery của máy (⌘R) → Utilities → Startup Security Utility → **No Security** + **Allow booting from external media**. Mac 2017 trở về trước không cần bước này.

Không dùng cho Mac chip M (Apple silicon).

Nếu Windows SmartScreen cảnh báo (app chưa ký số): bấm **More info → Run anyway**.

Ảnh Recovery: © Apple. Bộ khởi động: OpenCore © Acidanthera (BSD-3-Clause). Giao thức Recovery theo macrecovery.py của OpenCorePkg.
