# Giai đoạn 5 — Firmware (ESP-IDF + esp-matter)

> **Trạng thái:** đã viết xong code, **chưa build bằng toolchain thật**. Theo lựa chọn của bạn, việc build làm trên máy bạn.
> - Mọi API dùng trong code đều đã được đối chiếu với mã nguồn của đúng phiên bản đã ghim (xem §9).
> - Các module không phụ thuộc Matter đã qua kiểm tra cú pháp bằng `g++ -Wall -Werror`, dùng header giả lập chép đúng chữ ký hàm của ESP-IDF v5.5.5.
> - Hướng dẫn build, nạp và ghép: [firmware/README.md](../firmware/README.md).

## 0. Quyết định đã chốt trước GĐ5

| Câu hỏi | Lựa chọn | Hệ quả |
|---|---|---|
| Phiên bản SDK | Bám **ESP-IDF v5.x** | **ESP-IDF v5.5.5 + esp-matter `release/v1.6`** (commit `9f2e35a`, Matter 1.6). Nhánh `release/v1.6.1` đòi ESP-IDF v6.0.2 nên không dùng. |
| VID/PID | **Test 0xFFF1 / 0x8000** | Dùng DAC test và dữ liệu ghép test có sẵn trong SDK: passcode 20202021, discriminator 3840. Controller sẽ cảnh báo "chưa chứng nhận". |
| Build | **Chỉ viết code** | Bạn tự build. Nếu gặp lỗi biên dịch, gửi mình log để sửa. |
| Apple Home | **Chỉ Water Leak Detector** | Một endpoint đúng chuẩn. Hub Apple cần bản 18.4 trở lên. |

## 1. Kiến trúc

```
 GPIO9 nút ─┐   EXT1 (TOP power-down)  ┌──────────────┐  APP_EVT_*   ┌──────────────────────────────┐
 GPIO10 A ──┼─► + GPIO wake + ngắt ───►│ wake_inputs  │─────────────►│ app task (hàng đợi sự kiện)   │
 GPIO12 B ──┘   mức thấp               └──────────────┘              │  ├─ leak_probe (máy trạng thái)│
                                     esp_timer: probe / button / ───►│  ├─ button (giữ 5 s / 10 s)     │
                                     battery (đánh thức light-sleep) │  ├─ battery (ADC + bộ đếm)     │
                                                                     │  └─ app_matter ──► CHIP stack │
                                                                     └──────────────────────────────┘
 status_led: esp_timer + LP IO hold (LED sáng mà chip vẫn ngủ được)      CHIP/OpenThread task: ICD, SED poll
```

- **Ngủ:** auto light-sleep (tickless idle) với TOP domain power-down (`CONFIG_PM_POWER_DOWN_PERIPHERAL_IN_LIGHT_SLEEP`), flash power-down và MAC/BB power-down. Đây đúng là cấu hình mà ngân sách GĐ1 giả định (sàn khoảng 25 µA).
- **Đánh thức:**
  - Timer của OpenThread (data poll 15 s), esp_timer của ứng dụng, và EXT1 trên 3 LP IO.
  - EXT1 dùng được khi TOP domain tắt. `gpio_wakeup` chỉ bổ sung cho trường hợp TOP domain còn bật (ví dụ đang commissioning BLE).
  - Sau khi chip chạy lại, ngắt mức thấp báo cho ứng dụng biết chân nào. ISR tắt ngắt của chân đó, nên mỗi lần "arm" chỉ có đúng một sự kiện.
- **Quy tắc quan trọng:** chân nào đang ở mức thấp (nút đang giữ, đầu dò đang ướt) thì phải được *disarm*. Nếu không, EXT1 sẽ đánh thức chip ngay sau mỗi lần ngủ và pin cạn rất nhanh.
- **Chân không dùng** (GPIO2–5, 22, 25): đặt input có pull-down. Hai ngõ ra dùng hold của LP IO (PROBE_EXC, LED_N). VBAT_MEAS_EN là IO số thường nên chỉ được bật trong lúc giữ khoá PM "không ngủ".

## 2. Mô hình dữ liệu Matter

| Endpoint | Device type | Cluster |
|---|---|---|
| 0 | Root Node | esp-matter tự tạo: Descriptor, Basic Information, Access Control, Administrator Commissioning, General Commissioning, General Diagnostics, Group Key Management, Network Commissioning (Thread), Operational Credentials, Thread Network Diagnostics, **ICD Management**, **OTA Software Update Requestor** |
| 1 | **Water Leak Detector (0x0043)** + **Power Source (0x0011)** | Identify (Visible Indicator = LED), **Boolean State** (`StateValue`, sự kiện `StateChange`), **Power Source** (feature BAT + REPLC) |

Power Source trên EP1:

| Thuộc tính | Giá trị |
|---|---|
| Status | Active |
| Description | "CR123A" |
| BatReplaceability | UserReplaceable |
| BatReplacementDescription | "CR123A 3 V lithium" |
| BatQuantity | 1 |
| BatCommonDesignation | CR123A (0x1D) |
| BatApprovedChemistry | LithiumManganeseDioxide (0x06) |
| BatCapacity | 1500 mAh |
| BatVoltage | mV, cập nhật mỗi lần đo |
| BatPercentRemaining | đơn vị 0,5 %, cập nhật mỗi lần đo |
| BatChargeLevel | OK / Warning ≤ 15 % / Critical ≤ 5 % |
| BatReplacementNeeded | true khi Critical |

**Điểm khác ở esp-matter v1.6, dễ bị sai:**
- Ở bản này, `StateValue` của Boolean State do chính cluster server quản lý (cờ `ATTRIBUTE_FLAG_MANAGED_INTERNALLY`).
- Vì vậy `esp_matter::attribute::update()` trả `ESP_ERR_NOT_SUPPORTED` cho thuộc tính này (xem FAQ của esp-matter).
- Firmware lấy đối tượng `BooleanStateCluster` từ registry của data-model provider rồi gọi `SetStateValue()`. Hàm này **tự phát sự kiện `StateChange`**, đúng yêu cầu FR-05.
- Các thuộc tính Power Source vẫn nằm trong kho thuộc tính của esp-matter, nên dùng `attribute::update()` bình thường.

## 3. ICD và đánh đổi độ trễ – pin

| Tham số (`sdkconfig.defaults`) | Giá trị | Ý nghĩa |
|---|---|---|
| `CONFIG_ENABLE_ICD_SERVER` / `CONFIG_ENABLE_ICD_LIT` | y / n | ICD **SIT**. Tương thích tốt nhất với Apple Home và Home Assistant. |
| `CONFIG_ICD_SLOW_POLL_INTERVAL_MS` | 15000 | Data poll khi nhàn rỗi. 15 s là mức tối đa của SIT. |
| `CONFIG_ICD_FAST_POLL_INTERVAL_MS` | 200 | Poll khi ở active mode, sau khi gửi báo cáo hoặc khi bấm nút. |
| `CONFIG_ICD_ACTIVE_MODE_INTERVAL_MS` / `..._THRESHOLD_MS` | 1000 / 1000 | Đủ cho một trao đổi ReportData ↔ StatusResponse. |
| `CONFIG_ICD_IDLE_MODE_INTERVAL_SEC` | 3600 | Trần MaxInterval của subscription, tức keep-alive 1 giờ/lần. Controller biết thiết bị "chết" trong khoảng 1 giờ. |

**Độ trễ báo rò không phụ thuộc slow poll:**
- Thiết bị chủ động phát. Từ lúc nước chạm điện cực đến lúc gói tin rời anten: xác nhận 3 mẫu × 100 ms ≈ 0,2 s, cộng thời gian gửi báo cáo, tổng **< 1 s** (FR-02).
- `SetStateValue()` đánh dấu thuộc tính đã thay đổi. Firmware gọi thêm `ICDNotifier::NotifyNetworkActivityNotification()` để vào active mode ngay.

Slow poll chỉ ảnh hưởng tới **lệnh từ controller gửi tới thiết bị** (đọc thuộc tính, Identify, mở commissioning). Số liệu từ mô hình GĐ1 (`tools/power_budget.py`, kịch bản điển hình, CR123A):

| Slow poll | Độ trễ lệnh tối đa | Dòng TB @3,3 V | Tuổi thọ CR123A |
|---|---|---|---|
| 5 s | 5 s | 47,6 µA | 2,4 năm |
| 10 s | 10 s | 37,4 µA | 3,1 năm |
| **15 s (chọn)** | **15 s** | **34,0 µA** | **3,4 năm** |
| LIT 30 s | 30 s | 30,6 µA | 3,7 năm |

- **Muốn lệnh phản hồi nhanh** (ví dụ khi cài đặt): bấm nút một lần. ICD vào active mode và poll 200 ms trong khoảng 1 s mỗi lần có trao đổi.
- **Chuyển sang LIT** sau này:
  - `CONFIG_ENABLE_ICD_LIT=y`, slow poll khoảng 30 s;
  - controller phải hỗ trợ Check-In Protocol;
  - lợi thêm khoảng 10 % tuổi thọ, nhưng lệnh có thể trễ tới 30 s.

## 4. Đầu dò nước (FR-01..FR-04)

```
ARMED_DRY ──(EXT1: LEAK_x_N = 0)──► CONFIRMING ──(3 mẫu ướt, cách 100 ms)──► WET
    ▲             │ 1 mẫu khô = nhiễu (< 200 ms), không báo           │ StateValue = TRUE + StateChange
    │◄────────────┘                                                    │ PROBE_EXC = 0 (bỏ phân cực DC)
    │                                                                  │ cứ 10 s: xung 5 ms, đọc A và B
    └──(khô liên tục 30 s + xung kiểm tra 50 ms vẫn khô)───────────────┘ StateValue = FALSE
```

| Tham số (menuconfig) | Mặc định | Yêu cầu |
|---|---|---|
| `APP_PROBE_CONFIRM_SAMPLES` / `..._INTERVAL_MS` | 3 / 100 ms | FR-03: 3 mẫu ướt liên tiếp. |
| `APP_PROBE_WET_PULSE_PERIOD_S` / `..._PULSE_MS` | 10 s / 5 ms | FR-04: dòng DC trung bình qua nước < 2 nA. |
| `APP_PROBE_DRY_HOLD_S` | 30 s | FR-03: về "khô" khi khô liên tục ≥ 30 s. |
| `APP_PROBE_DRY_VERIFY_PULSE_MS` | 50 ms | Bổ sung ở GĐ5 (giải thích bên dưới). |

**Vì sao thêm xung kiểm tra 50 ms:**
- Với nước có điện trở cao (gần ngưỡng 1,3–4 MΩ), RC ở cổng MOSFET (R_w + 20 kΩ, nạp vào 10 nF ‖ 1 MΩ) có thể chưa nạp tới ngưỡng trong 5 ms.
- Khi đó xung ngắn đọc "khô" trong khi phân cực tĩnh lại đọc "ướt". Trạng thái sẽ bật tắt liên tục: báo rò, hết rò, rồi lại báo rò.
- Xung dài 50 ms chỉ chạy một lần trước khi kết luận "khô", nên gần như không tốn thêm năng lượng.

Kênh nào ướt (A = răng lược đáy, B = đầu dò rời) chỉ được ghi vào log. Matter chỉ có một `StateValue`.

## 5. Nút và LED (FR-07, FR-09..FR-11)

Bảng thao tác nằm ở [firmware/README.md](../firmware/README.md#nút-và-led).

**Nhấn ngắn khi khô và pin còn tốt:** LED nháy 1–3 lần theo chất lượng liên kết tới router cha (`mLinkQualityIn` của OpenThread).
- 3 nháy: biên liên kết ≥ 20 dB.
- 2 nháy: ≥ 10 dB.
- 1 nháy: ≥ 2 dB.
- 1 nháy dài: chưa bám được router.

RSSI trung bình được ghi ra log, cả khi nhấn nút lẫn mỗi 6 giờ. Tính năng này phục vụ thử tầm ở GĐ6 và giúp chọn chỗ đặt khi lắp.

Ba điểm thiết kế:
- **Factory reset chạy lúc thả nút** (sau khi đã giữ ≥ 10 s), không chạy lúc đang giữ. GPIO9 là chân strap BOOT; nếu reboot trong lúc nút còn bị giữ, chip sẽ vào ROM download mode.
- **Nút kẹt** (chốt bấm của vỏ bị kẹt): giữ quá 30 s thì firmware bỏ qua. Trong lúc đó nút chỉ được kiểm tra mỗi 1 s, không nằm trong mask EXT1. Nhờ vậy nút kẹt không giữ chip thức liên tục.
- **Khi gỡ thiết bị khỏi controller cuối cùng** (fabric cuối bị xoá): thiết bị tự factory reset. Thread credentials bị xoá và BLE commissioning mở lại như lúc mới mua. Tắt được bằng `APP_FACTORY_RESET_ON_LAST_FABRIC_REMOVED`.

## 6. Đo pin và % pin (FR-06, FR-07)

- **Đo điện áp:**
  - Cứ 6 giờ một lần, mỗi lần bấm nút, và lúc khởi động.
  - Bật `VBAT_MEAS_EN` để Q2 nối cầu chia 100k/100k vào mạch, chờ 30 ms (6τ), đọc ADC1_CH0 8 lần ở ATTEN2 với hiệu chuẩn curve-fitting, rồi nhân 2.
  - Mỗi lần đo tốn khoảng 33 µA × 30 ms. Không đáng kể.
- **% pin** = min(**bộ đếm điện tích**, **bảng điện áp**):
  - **Bộ đếm điện tích:** tích phân `APP_BATTERY_AVG_CURRENT_UA` theo thời gian, mặc định 43 µA phía pin theo mô hình GĐ1. Giá trị được lưu NVS ở mỗi lần đo. Thay bằng số đo thật ở GĐ6.
  - **Bảng điện áp:** thô, chỉ để bắt "cái gối" cuối đời pin. Đường xả của Li-MnO2 rất phẳng, nên điện áp gần như không cho biết gì trước đoạn đó.
- **Phát hiện pin mới:**
  - Sau reset do cấp nguồn (lắp pin), nếu điện áp ≥ 3,15 V thì bộ đếm về 0.
  - Hạn chế: lắp lại một viên pin cũ còn trên 3,15 V cũng làm bộ đếm về 0. Khi gần hết pin, bảng điện áp vẫn kéo % xuống đúng.

## 7. OTA và phân vùng

- `CONFIG_ENABLE_OTA_REQUESTOR=y`. Phân vùng 4 MB giống ví dụ `icd_app` của esp-matter:
  - `ota_0` và `ota_1`, mỗi khe 1,875 MB;
  - `nvs` 48 KB;
  - `fctry` 24 KB, để sau này nạp DAC/PAI thật;
  - `esp_secure_cert`.
- Image OTA phải có `PROJECT_VER_NUMBER` lớn hơn bản đang chạy. Cách đóng gói xem trong README firmware.

## 8. Cấu hình liên quan tới năng lượng

| Cấu hình | Lý do |
|---|---|
| `CONFIG_PM_POWER_DOWN_PERIPHERAL_IN_LIGHT_SLEEP=y`, `CONFIG_ESP_SLEEP_POWER_DOWN_FLASH=y`, `CONFIG_ESP_PHY_MAC_BB_PD=y`, `CONFIG_IEEE802154_SLEEP_ENABLE=y` | Sàn ngủ khoảng 25 µA thay vì 85 µA. Đây là rủi ro số 1 đã nêu ở GĐ1. |
| `CONFIG_RTC_CLK_SRC_EXT_CRYS=y` | Board có Y1 32,768 kHz. Không phải hiệu chuẩn RC mỗi lần thức. |
| `CONFIG_USE_BLE_ONLY_FOR_COMMISSIONING=y` | BLE bị gỡ sau khi ghép xong. |
| TX power +9 dBm (`APP_THREAD_TX_POWER_DBM`) | Đặt mỗi khi trạng thái Thread đổi. Mặc định của radio có thể là +20 dBm (140 mA so với 60 mA). |
| Console UART0, không dùng USB-Serial-JTAG làm console | Khi chạy pin không có thêm khối nào hoạt động. |

## 9. Đã kiểm chứng gì, còn rủi ro gì

**Đã đối chiếu với mã nguồn (đúng commit đã ghim):**
- **esp-matter `9f2e35a`:**
  - `water_leak_detector::create`;
  - `power_source::add` và các hàm tạo thuộc tính tuỳ chọn;
  - cờ `MANAGED_INTERNALLY` và đường đi của `attribute::update`;
  - registry `data_model::provider`;
  - `factory_reset`, `ScopedChipStackLock`, cấu hình `icd_app`.
- **connectedhomeip `75902a0c6`:**
  - `BooleanStateCluster::SetStateValue`;
  - giá trị enum của Power Source (CR123A = 0x1D, Li-MnO2 = 0x06, UserReplaceable = 0x02);
  - tên các Kconfig ICD;
  - `CommissioningWindowManager`, `ICDNotifier`.
- **ESP-IDF v5.5.5:**
  - `esp_sleep_enable/disable_ext1_wakeup_io`; ESP32-H2 hỗ trợ chế độ EXT1 riêng cho từng chân;
  - `gpio_wakeup_enable`, `gpio_hold_en`;
  - ADC oneshot và curve fitting;
  - struct cấu hình OpenThread.

**Rủi ro còn lại (sẽ kiểm ở GĐ6):**
1. **Chưa biên dịch thật.**
   - Phần dễ lỗi nhất là `app_matter.cpp` (dùng API C++ của CHIP). Các module khác đã qua kiểm tra cú pháp.
   - Nếu `idf.py build` báo lỗi, gửi mình log.
2. **Đánh thức bằng EXT1 kèm ngắt mức sau khi TOP domain tắt.**
   - Cơ chế này giống component `button` v4 của Espressif ở chế độ power-save, và đó là cách `icd_app` dùng trên H2.
   - Vẫn cần đo thực tế: dòng sàn, và độ trễ từ lúc nhúng nước đến lúc controller nhận báo cáo.
3. **Bộ đếm điện tích dùng dòng trung bình giả định.** Cần thay bằng số đo ở GĐ6.
4. **Bảng điện áp CR123A là số gần đúng.** Cần đo đường xả thật (hoặc tra datasheet của hãng pin) để chỉnh.
