# macUSB cho MacBookPro14,3 (Intel) chạy macOS Ventura

Bản gốc (Kruszoneq/macUSB v2.5) yêu cầu **macOS 14.6 Sonoma** trở lên, nên không mở được trên Ventura (13.x) — macOS cuối cùng mà MacBookPro14,3 được hỗ trợ.

## Những gì đã sửa

| Vấn đề | Cách sửa |
|---|---|
| Deployment target 14.6 (app + helper) | Hạ xuống **13.0** |
| `.onChange(of:) { }` không tham số (chỉ có từ macOS 14) — 8 chỗ trong `MacOSDownloaderWindowShellView` | Đổi sang dạng `{ _ in }` chạy được trên 13 |
| `.contentTransition(.symbolEffect(.replace))` (macOS 14) | Bọc `#available(macOS 14)`, Ventura dùng hiệu ứng mờ dần |
| Helper đặc quyền chỉ tin app ký bởi Team ID của tác giả (`27NC66L8P2`) → bản tự build sẽ báo "Không thể xác minh helper" | Yêu cầu chữ ký được tính lúc chạy: cùng Team ID với chính app nếu ký bằng chứng chỉ Apple; nếu ký ad-hoc thì khóa theo **cdhash** chính xác của app/helper trong cùng bundle |
| Dự án đặt chữ ký Developer ID của tác giả | Đổi sang ký ad-hoc (`-`), không cần tài khoản |
| Giao diện Liquid Glass (macOS 26) | Đã có sẵn nhánh dự phòng trong mã gốc, giữ nguyên |

Các API còn lại (SMAppService, Regex, `setCodeSigningRequirement`…) đều có từ macOS 13.

## Vì sao phải build trên GitHub Actions

Mã nguồn dùng định dạng project Xcode 16+, icon `.icon` và SDK macOS 26 → cần **Xcode 26**, mà Xcode 26 không chạy trên Ventura (Ventura tối đa Xcode 15.2). Workflow `.github/workflows/build-ventura-intel.yml` build trên máy ảo macOS 26 của GitHub (miễn phí cho repo public), xuất ra app x86_64 với `minos 13.0` và tự kiểm tra lại.

## Các bước

1. Đăng nhập github.com → mở https://github.com/Kruszoneq/macUSB → **Fork**.
2. Đưa bản sửa lên fork (trên Mac, cần `xcode-select --install` để có git):
   ```bash
   git clone https://github.com/<tên-bạn>/macUSB.git && cd macUSB
   git checkout -b ventura-intel
   git config user.name "Ten Ban"; git config user.email "ban@example.com"
   git am ~/Downloads/macUSB-ventura-intel.patch
   git push -u origin ventura-intel     # mật khẩu = Personal Access Token của GitHub
   ```
3. Vào tab **Actions** của fork → bấm bật workflows (fork tắt sẵn) → chọn *Build macUSB for Intel + macOS Ventura* → **Run workflow** trên nhánh `ventura-intel`. Đợi ~10–15 phút.
4. Tải artifact **macUSB-ventura-intel** (gồm `macUSB-ventura-intel.zip` và `install-macusb.sh`), giải nén, rồi:
   ```bash
   chmod +x install-macusb.sh
   ./install-macusb.sh macUSB-ventura-intel.zip
   ```
   Script gỡ quarantine, ký lại helper + app, cài vào `/Applications`.
5. Mở macUSB. Bật **System Settings → General → Login Items → Allow in the Background** cho macUSB và **Privacy & Security → Full Disk Access**.

## Nếu helper không đăng ký được (ký ad-hoc)

Một số máy không cho launchd chạy daemon ký ad-hoc. Khi đó ký bằng chứng chỉ **Apple Development** miễn phí:
1. Cài Xcode 15.2 (bản cuối chạy trên Ventura) → Settings → Accounts → thêm Apple ID → Manage Certificates → **+ Apple Development**.
2. `security find-identity -v -p codesigning` để lấy tên chứng chỉ.
3. `./install-macusb.sh macUSB-ventura-intel.zip "Apple Development: ten@email.com (XXXXXXXXXX)"`
4. Trong app: menu **Narzędzia/Tools → Napraw helpera** (Repair helper).

## Lưu ý

- Chưa thể chạy thử trên máy thật Ventura; bước build trên Actions sẽ báo lỗi biên dịch nếu còn API nào mới hơn 13.0 sót lại (xem artifact `build-log`).
- Một số biểu tượng SF Symbols mới có thể không hiện trên Ventura (chỉ ảnh hưởng hình ảnh).
- Tính năng tải macOS mới (Sonoma trở lên) vẫn tải được; nhưng *cài* chúng lên chính MacBookPro14,3 thì Apple không hỗ trợ.
