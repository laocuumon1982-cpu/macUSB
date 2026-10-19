#!/bin/bash
# Cài macUSB (bản build cho Intel + macOS Ventura) vào /Applications.
#
# Cách dùng:
#   ./install-macusb.sh macUSB-ventura-intel.zip            # ký ad-hoc (không cần Apple ID)
#   ./install-macusb.sh macUSB-ventura-intel.zip "Apple Development: ten@email.com (XXXXXXXXXX)"
#
# Xem danh sách chứng chỉ ký có trên máy:  security find-identity -v -p codesigning
set -euo pipefail

SRC="${1:-}"
IDENTITY="${2:--}"
DEST="/Applications/macUSB.app"
HELPER_ID="com.kruszoneq.macusb.helper"

if [ -z "$SRC" ] || [ ! -e "$SRC" ]; then
  echo "Cách dùng: $0 <macUSB-ventura-intel.zip | macUSB.app> [tên chứng chỉ ký]" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [[ "$SRC" == *.zip ]]; then
  ditto -x -k "$SRC" "$WORK"
  APP="$(find "$WORK" -maxdepth 2 -name 'macUSB.app' -type d | head -1)"
else
  ditto "$SRC" "$WORK/macUSB.app"
  APP="$WORK/macUSB.app"
fi
[ -d "$APP" ] || { echo "Không tìm thấy macUSB.app trong $SRC" >&2; exit 1; }

echo "==> Kiểm tra kiến trúc và phiên bản macOS tối thiểu"
lipo -info "$APP/Contents/MacOS/macUSB"
/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" "$APP/Contents/Info.plist" || true

echo "==> Gỡ cờ quarantine (file tải từ Internet)"
xattr -cr "$APP"

ENT_APP="$WORK/app.entitlements"
ENT_HELPER="$WORK/helper.entitlements"
cat > "$ENT_APP" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.automation.apple-events</key><true/>
</dict></plist>
PLIST
cat > "$ENT_HELPER" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict/></plist>
PLIST

if [ "$IDENTITY" = "-" ]; then
  echo "==> Ký ad-hoc (không có Team ID)"
else
  echo "==> Ký bằng chứng chỉ: $IDENTITY"
fi
# Helper phải được ký trước, sau đó mới ký app (app niêm phong chữ ký của helper).
codesign --force --options runtime --timestamp=none \
  --identifier "$HELPER_ID" --entitlements "$ENT_HELPER" \
  --sign "$IDENTITY" "$APP/Contents/Library/Helpers/macUSBHelper"
codesign --force --options runtime --timestamp=none \
  --entitlements "$ENT_APP" --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=1 "$APP"

echo "==> Cài vào $DEST"
osascript -e 'tell application id "com.kruszoneq.macUSB" to quit' >/dev/null 2>&1 || true
sleep 1
if [ -d "$DEST" ]; then
  rm -rf "$DEST" 2>/dev/null || sudo rm -rf "$DEST"
fi
ditto "$APP" "$DEST" 2>/dev/null || sudo ditto "$APP" "$DEST"

echo
echo "Xong. Mở macUSB từ /Applications."
echo "Lần đầu: bật macUSB trong System Settings → General → Login Items (Allow in the Background)"
echo "và System Settings → Privacy & Security → Full Disk Access."
echo "Nếu app báo lỗi helper, chọn menu Narzędzia/Tools → Napraw helpera (Repair helper)."
open -R "$DEST"
