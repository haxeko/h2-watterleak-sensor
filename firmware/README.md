# Firmware: h2-watterleak-sensor (ESP-IDF + esp-matter)

Firmware cho cảm biến rò nước chạy pin: ESP32-H2, Matter over Thread, ICD (Short Idle Time).
Thiết kế chi tiết và lý do lựa chọn nằm ở [docs/05-firmware.md](../docs/05-firmware.md).

| Thành phần | Phiên bản đã ghim |
|---|---|
| ESP-IDF | **v5.5.5** (esp-matter v1.6 khuyến nghị) |
| esp-matter | nhánh **release/v1.6**, commit `9f2e35a` (Matter 1.6, connectedhomeip `75902a0c6`) |
| Chip / module | ESP32-H2-WROOM-02C-H4S, flash 4 MB |

> Không dùng `release/v1.6.1`: nhánh đó yêu cầu ESP-IDF v6.0.2.

## Cấu trúc

```
firmware/
├── CMakeLists.txt        project; PROJECT_VER_NUMBER = SoftwareVersion cho OTA
├── partitions.csv        4 MB: 2 khe OTA 1,875 MB, nvs, fctry
├── sdkconfig.defaults    Thread MTD, ICD SIT, auto light-sleep, XTAL 32 kHz, VID/PID test
└── main/
    ├── Kconfig.projbuild menu "h2-watterleak-sensor": ngưỡng đầu dò, pin, nút, TX power
    ├── board_pins.h      gán chân (khớp docs/02 và sơ đồ nguyên lý)
    ├── app_main.cpp      khởi tạo, vòng lặp sự kiện, nhấn ngắn
    ├── app_events.*      hàng đợi sự kiện + khoá PM "không ngủ"
    ├── wake_inputs.*     EXT1 + GPIO wake + ngắt mức thấp cho GPIO9/10/12
    ├── leak_probe.*      máy trạng thái đầu dò ARMED_DRY → CONFIRMING → WET
    ├── button.*          nhấn ngắn / giữ 5 s / giữ 10 s rồi thả = factory reset / kẹt nút
    ├── status_led.*      mẫu nháy LED (chỉ sáng khi có sự kiện)
    ├── battery.*         ADC + bộ đếm điện tích → Power Source
    └── app_matter.*      node, endpoint Water Leak Detector + Power Source, OpenThread
```

## Cài môi trường (một lần)

Theo hướng dẫn chính thức của esp-matter (Linux; trên macOS thay `linux` bằng `darwin`):

```sh
git clone --recursive https://github.com/espressif/esp-idf.git
cd esp-idf && git checkout v5.5.5 && git submodule update --init --recursive
./install.sh esp32h2
source ./export.sh
cd ..

git clone -b release/v1.6 https://github.com/espressif/esp-matter.git
cd esp-matter && git checkout 9f2e35a
git submodule update --init --depth 1
cd connectedhomeip/connectedhomeip
./scripts/checkout_submodules.py --platform esp32 linux --shallow
cd ../..
./install.sh                 # thêm --no-host-tool nếu không cần chip-tool
cd ..
```

Mỗi terminal mới:

```sh
source esp-idf/export.sh
source esp-matter/export.sh          # đặt ESP_MATTER_PATH
export IDF_CCACHE_ENABLE=1           # tuỳ chọn, build lại nhanh hơn
```

## Build và nạp

```sh
cd h2-watterleak-sensor/firmware
idf.py set-target esp32h2
idf.py build
idf.py -p /dev/ttyUSB0 erase-flash flash monitor
```

- **Nạp qua jig J1:**
  - **UART:** nối TXD0/RXD0/GND/3V3; giữ IO9 = 0 (hoặc giữ SW1) rồi kéo EN xuống 0 → 1 để vào chế độ download.
  - **USB:** nối D−/D+ (USB-Serial-JTAG) thì esptool tự reset chip, không cần giữ IO9.
- **Pin:** tháo pin CR123A khi nạp. Jig cấp 3,3 V vào chân 1 của J1.
- **Log:** in ra UART0 (115200 baud). Sau khi tháo jig, log không tốn thêm năng lượng đáng kể. Ở bản chạy pin có thể hạ log xuống WARN (xem `sdkconfig.defaults`).
- **Đổi tham số:** `idf.py menuconfig` → menu **h2-watterleak-sensor**.

## Ghép (commissioning)

Thiết bị dùng dữ liệu test: VID `0xFFF1`, PID `0x8000`, passcode `20202021`, discriminator `3840`.
Mã QR và mã ghép thủ công được in ra log khi khởi động. Các controller sẽ báo "thiết bị chưa được chứng nhận"; chọn **Vẫn thêm**.

- **Apple Home** (cần HomePod hoặc Apple TV chạy bản 18.4 trở lên làm Thread Border Router và hub): Thêm phụ kiện → quét mã QR.
- **Home Assistant:** cài Matter Server và OpenThread Border Router (hoặc dùng border router sẵn có). Dùng app Home Assistant trên điện thoại để thêm thiết bị Matter.
- **chip-tool** (trong thư mục `esp-matter/connectedhomeip/connectedhomeip/out/host` sau khi chạy `install.sh`):

```sh
# lấy dataset của Thread network từ border router (OTBR):
#   ot-ctl dataset active -x   -> <dataset_hex>
chip-tool pairing ble-thread 0x7283 hex:<dataset_hex> 20202021 3840

chip-tool booleanstate read state-value 0x7283 1
chip-tool booleanstate subscribe state-value 1 3600 0x7283 1
chip-tool powersource read bat-percent-remaining 0x7283 1     # đơn vị 0,5 %
chip-tool powersource read bat-voltage 0x7283 1               # mV
chip-tool icdmanagement read idle-mode-duration 0x7283 0
chip-tool identify identify 10 0x7283 1                       # LED nháy 10 s
```

> Thiết bị là sleepy end device: lệnh gửi tới nó có thể chờ tới 15 s (slow poll).
> Nhấn nút một lần để thiết bị vào active mode, khi đó lệnh được phản hồi trong khoảng 200 ms.

## Nút và LED

| Thao tác | Kết quả |
|---|---|
| Nhấn ngắn, chưa ghép | Mở cửa sổ commissioning 15 phút. LED nháy 50 ms mỗi 2 s. |
| Nhấn ngắn, đã ghép | LED báo trạng thái: 1 nháy = ổn; 5 nháy nhanh = đang ướt; nháy đôi = pin yếu. Đồng thời đo lại pin, và ICD vào active mode. |
| Giữ 5 s | LED nháy 2 lần dài: cảnh báo sắp reset. |
| Giữ ≥ 10 s rồi **thả** | LED nhấp nháy nhanh từ giây thứ 10. Khi thả: factory reset. Reset chỉ chạy lúc thả vì GPIO9 là chân strap BOOT. |
| Giữ > 30 s | Coi là kẹt nút. Bỏ qua cho tới khi nút được thả ra. |
| Có rò | LED nháy 20 ms mỗi 3 s, tối đa 1 giờ. |

## OTA

`CONFIG_ENABLE_OTA_REQUESTOR=y`. Để tạo image OTA:
1. Tăng `PROJECT_VER_NUMBER` trong `CMakeLists.txt`.
2. Build lại.
3. Đóng gói `build/h2_leak_sensor.bin` bằng `connectedhomeip/src/app/ota_image_tool.py`, dùng đúng VID/PID ở trên.
4. Phát image qua OTA Provider: `chip-ota-provider-app`, hoặc OTA của Home Assistant khi có.
