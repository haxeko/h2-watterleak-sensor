# Giai đoạn 6 — Kế hoạch test (đo dòng ngủ, thử nước, thử tầm Thread)

> **Trạng thái:** kế hoạch và công cụ đã sẵn sàng, chờ có board và firmware build được.
> Thiết bị đo: **Nordic PPK2**. Controller: **Apple Home** và **Home Assistant** (multi-admin).

## 0. Công cụ

| Công cụ | Dùng để | Đã kiểm tra |
|---|---|---|
| [`tools/ppk2_analyze.py`](../tools/ppk2_analyze.py) | Phân tích CSV từ PPK2: dòng TB, dòng sàn, xung radio, chu kỳ poll, điện tích mỗi poll, tuổi thọ CR123A theo mô hình GĐ1. Có kênh logic thì tính thêm độ trễ báo rò, chống báo giả và xung đo khi ướt. | Chạy trên bản ghi tổng hợp có giá trị biết trước: kết quả khớp (sàn 28,0 µA, xác nhận 205 ms, gói radio 210 ms, xung 120 ms bị lọc). |
| [`tools/leak_sim/leak_sim.ino`](../tools/leak_sim/leak_sim.ino) | Bộ giả lập nước: Arduino + opto PC817 + điện trở R_SIM cắm vào J2. Lệnh `W`, `D`, `P <ms>` qua serial. | Đã soát giao thức với script chạy test. |
| [`tools/leak_test_runner.py`](../tools/leak_test_runner.py) | Điều khiển bộ giả lập, đồng thời nghe Home Assistant qua websocket. Có 3 chế độ: `latency` (độ trễ đầu-cuối, thời gian về khô), `transient` (chống báo giả), `monitor` (ghi log khi thử nước thật hoặc chạy dài ngày). | Chạy với HA websocket giả + Arduino giả trên pty: đúng ở cả 3 chế độ. |
| [`tools/power_budget.py`](../tools/power_budget.py) | Tính lại ngân sách với số đo thật (`--floor`). | Mô hình của GĐ1. |
| Firmware | Nhấn ngắn khi khô: LED nháy 1–3 lần theo chất lượng liên kết Thread, RSSI ghi ra log UART. | Thêm ở GĐ6 cho bài thử tầm. |

Cài cho máy tính chạy test (Python ≥ 3.9): `pip install websockets pyserial`.

## 1. Chuẩn bị

### 1.1 Thiết bị và vật tư

- **Đo đạc và điều khiển:**
  - Nordic PPK2, cùng nRF Connect for Desktop → **Power Profiler**.
  - 1 Arduino bất kỳ (Uno, Nano, Pro Micro…), 1 opto PC817, điện trở 330 Ω, R_SIM = 100 kΩ, 1 MΩ, 2,2 MΩ, 3,3 MΩ, 4,7 MΩ, 10 MΩ, cầu chia 10k/20k (nếu Arduino chạy 5 V).
  - Hộp điện trở thập phân 100 kΩ–10 MΩ (nếu có).
  - Phích JST-PH 2 chân để cắm vào J2.
  - Jig UART/USB vào J1 để xem log (115200 baud).
- **Pin:** pin CR123A mới (2–3 viên).
- **Nước thử:** nước máy, nước RO hoặc nước lọc đóng chai, nước mưa, nước muối 1 %, nước xà phòng giặt, nước cất (chỉ để tham khảo).
- **Dụng cụ khác:**
  - khay phẳng, thước đo độ sâu, khăn giấy;
  - hộp kín có miếng mút ướt để tạo độ ẩm khoảng 95 %, nhiệt-ẩm kế.
- **Mạng:**
  - Apple Home với HomePod hoặc Apple TV chạy bản 18.4 trở lên.
  - Home Assistant có Matter Server và OpenThread Border Router (ví dụ dongle ZBT-1), chung mạng Thread với Apple. Ghép đa admin theo §3 T1.

### 1.2 Nối PPK2

**Cách A — khuyến nghị cho mọi phép đo dòng: PPK2 thay pin (source meter).**
- Tháo pin.
- PPK2 **VOUT** nối vào cực **+** của đế pin BT1, là pad vuông ở bên trái, cạnh dấu "+" trên silkscreen. **GND** nối vào cực **−**, là pad tròn bên phải.
- Đặt nguồn **3,00 V** (điện áp danh định của CR123A khi tải nhẹ), bật "Enable power output".
- JP1 để nguyên. Dòng đo được là đúng dòng pin cung cấp, đã gồm Q1 và tổn hao của TPS63900.

**Cách B — kiểm tra lại bằng pin thật (ampere meter).**
- Cắt cầu đồng của **JP1** bằng dao. JP1 là jumper hàn loại *Bridged*, bước 1,3 mm, nằm cạnh D1 và Q1.
- Hàn 2 dây AWG30:
  - pad **1** (BAT_CELL, phía pin) nối vào PPK2 **VIN**;
  - pad **2** (BAT_RAW) nối vào PPK2 **VOUT**;
  - GND chung.
- Đo xong, hàn nối lại JP1 bằng một giọt thiếc.

**Cổng logic của PPK2:**

| Chân logic | Nối tới | Ghi chú |
|---|---|---|
| VCC | 3,3 V của **Arduino**, không lấy từ board cảm biến | Lấy từ board cảm biến thì dòng của bộ chuyển mức sẽ cộng vào phép đo. |
| GND | GND board cảm biến (J1 chân 8) | |
| D0 | `MARK_PIN` (D8) của bộ giả lập | Qua cầu chia 10k/20k nếu Arduino 5 V. |
| D1 | **TP7** (PROBE_EXC) | Ngõ ra GPIO trực tiếp, an toàn để đo. |
| D2 (tuỳ chọn) | J1 chân 3 (IO9, nút) | Có sẵn pull-up 10 kΩ. |

> **Không** nối cổng logic vào TP5 hay TP6 (LEAK_A_N, LEAK_B_N). Hai nút này chỉ có pull-up 470 kΩ, nên đầu vào của PPK2 có thể kéo chúng xuống và gây báo ướt giả.
> Khi đo **dòng sàn**, tháo cáp logic ra cho sạch.

### 1.3 Nối bộ giả lập nước vào J2

```
Arduino D7 ─[330 Ω]─► PC817 chân 1        PC817 chân 4 (C) ──► J2 chân 1 (EXC_B)
Arduino GND ────────► PC817 chân 2        PC817 chân 3 (E) ─[R_SIM]─► J2 chân 2 (SNS_B)
Arduino D8 ─[10k/20k nếu 5 V]─► PPK2 D0
```

Opto cách ly hoàn toàn board cảm biến với Arduino và máy tính. Khi opto tắt, dòng rò dưới 100 nA, tương đương hơn 33 MΩ, cao hơn nhiều so với ngưỡng 1,3–4 MΩ, nên được đọc là khô.

### 1.4 Thiết lập ghi trong Power Profiler

| Loại bản ghi | Tốc độ mẫu | Thời lượng | Dùng cho |
|---|---|---|---|
| Sự kiện | 100 kS/s | 2–10 phút | Dòng sàn, hình dạng từng poll/TX, độ trễ |
| Trung bình dài | 1 kS/s (PPK2 lấy trung bình bên trong, điện tích không đổi) | ≥ 2 giờ | Dòng TB thật, có cả keep-alive 1 giờ/lần và đo pin |

Xuất dữ liệu: **Export → CSV**, chọn cột thời gian, dòng điện và *digital channels*. Sau đó chạy:

```sh
python3 tools/ppk2_analyze.py sleep_10min.csv --vsrc 3.0
python3 tools/ppk2_analyze.py leak.csv --vsrc 3.0 --trigger D0 --exc D1 --json leak.json
```

> Nếu cột logic xuất ra dạng chuỗi `D0-D7` mà kết quả trông như bị đảo kênh, thêm `--digital-order d7first`.

## 2. Thứ tự thực hiện

| Ngày | Bài test |
|---|---|
| 1 | T0 lên nguồn, T1 ghép, T2 dòng ngủ |
| 2 | T3 độ trễ (PPK2), T4 độ trễ đầu-cuối, T5 chống báo giả, T6 về khô, T7 ngưỡng |
| 3 | T8 nước thật, T9 chống báo giả do ẩm, bắt đầu T10 (ngâm 24 h) |
| 4 | T11 đo pin, T12 tầm Thread, T13 nút/LED/reset, T14 độ bền hệ thống |
| 2 tuần | T15 chạy dài ngày (`monitor`) |

## 3. Các bài test

Cột "Yêu cầu" trỏ tới [docs/01 §2](01-yeu-cau-va-ngan-sach-dong.md#2-yêu-cầu).

### T0 — Lên nguồn lần đầu (trước khi lắp pin)
1. **Kiểm tra trước khi cấp nguồn:**
   - Đo trở kháng +3V3–GND, VBAT_P–GND và BAT_RAW–GND bằng đồng hồ. Phải không chập (thường > 10 kΩ).
   - Kiểm tra hướng Q1, U2, các diode và LED.
2. **Bật PPK2 ở 3,00 V, chưa nạp firmware.** Đo +3V3 ở J1 chân 1: phải **3,30 V ± 2 %**. Ghi lại dòng nghỉ (module chưa có firmware sẽ ở chế độ ROM).
3. **Nạp firmware** theo [firmware/README.md](../firmware/README.md). Log phải in ra:
   - mã QR;
   - `Water Leak Detector on endpoint 1`;
   - `armed (dry)`;
   - một dòng đo pin, ví dụ `3000 mV, 100 %…`.

### T1 — Ghép với Apple Home rồi chia sẻ sang Home Assistant (FR-09, FR-13)
1. **Ghép với Apple Home:**
   - Quét mã QR trong ứng dụng Nhà.
   - Phụ kiện phải hiện là **cảm biến rò nước** kèm % pin.
   - LED nháy 3 lần ngắn khi ghép xong.
2. **Chia sẻ sang Home Assistant:**
   - Trong ứng dụng Nhà: phụ kiện → Cài đặt phụ kiện → **Bật chế độ ghép nối** → lấy mã.
   - Trong app Home Assistant: Thêm thiết bị Matter → thiết bị **đã dùng ở nơi khác** → nhập mã.
   - Ghi lại tên các entity HA tạo ra, thường là `binary_sensor.…` (moisture) và `sensor.…_battery`.
3. **Kiểm tra trạng thái ban đầu:** cả hai controller cùng hiện "Không có nước" và % pin.

**Đạt:** cả hai controller nhận thiết bị; không có cảnh báo nào ngoài cảnh báo "chưa chứng nhận".

### T2 — Dòng ngủ và tuổi thọ pin (NFR-01, NFR-02)
1. **Điều kiện:** thiết bị đã ghép (BLE đã gỡ), khô, PPK2 cách A ở 3,00 V, cáp logic tháo ra.
2. **Bản ghi sự kiện:** 10 phút ở 100 kS/s, rồi chạy `ppk2_analyze.py`.
3. **Bản ghi trung bình:** 2 giờ ở 1 kS/s, rồi chạy `ppk2_analyze.py`.
4. **Cập nhật mô hình:** chạy `python3 tools/power_budget.py --floor <giá trị script in ra>` để cập nhật bảng tuổi thọ.

| Chỉ tiêu | Tiêu chí | Kết quả |
|---|---|---|
| Dòng sàn (trung vị, 10 phút) | **≤ 35 µA** @ 3,0 V | |
| Chu kỳ slow poll | 15 s ± 0,5 s | |
| Điện tích một lần poll | Ghi lại, so với mô hình (script in kèm, khoảng 120 µC) | |
| Dòng TB (2 giờ) | ≤ 50 µA @ 3,0 V (mô hình điển hình 41 µA) | |
| Tuổi thọ CR123A (script) | ≥ 3 năm (mục tiêu), ≥ 2 năm (bắt buộc) | |

**Nếu dòng sàn vượt 35 µA**, xem §4.

### T3 — Độ trễ trên thiết bị: từ lúc có nước đến gói radio (FR-02)
1. **Chuẩn bị:** PPK2 cách A, logic D0 nối bộ giả lập, D1 nối TP7. R_SIM = 100 kΩ.
2. **Ghi:** ở 100 kS/s, chạy `leak_test_runner.py … latency --cycles 10`. Bước này cần HA; nếu chưa có HA, gõ lệnh `W` / `D` trực tiếp trong Serial Monitor.
3. **Phân tích:** `ppk2_analyze.py leak.csv --trigger D0 --exc D1`.

| Chỉ tiêu | Tiêu chí |
|---|---|
| Xác nhận WET (D0 lên → PROBE_EXC xuống) | 200–260 ms (3 mẫu, mỗi mẫu cách 100 ms) |
| Gói radio đầu tiên sau khi có nước | **≤ 1 s**, kỳ vọng khoảng 0,21–0,3 s |
| Xung đo khi ướt | 5 ms ± 1 ms, mỗi 10 s ± 0,2 s |

### T4 — Độ trễ đầu-cuối tới Home Assistant và Apple Home
```sh
export HA_TOKEN=...      # HA: Hồ sơ → Bảo mật → Long-lived access token
python3 tools/leak_test_runner.py --ha ws://homeassistant.local:8123/api/websocket \
    --entity binary_sensor.<tên_entity_rò> --sim /dev/ttyACM0 latency --cycles 20
```
- **Đạt:**
  - 20/20 lần đều báo;
  - **trung vị ≤ 1,5 s**, **max ≤ 3 s**;
  - thời gian về khô từ **30 đến 41 s**.
- **Apple Home** (đo tay):
  - Bật thông báo cho phụ kiện.
  - Quay video màn hình điện thoại cạnh bộ giả lập, lặp 5 lần.
  - Đạt khi thông báo nghiêm trọng (critical alert) hiện ra trong vòng 3 s.

### T5 — Chống báo giả do xung ngắn (FR-03)
```sh
python3 tools/leak_test_runner.py --ha … --entity … --sim /dev/ttyACM0 transient
```
Script phát xung 50 / 100 / 150 / 250 / 400 / 800 ms, mỗi loại 5 lần.

| Xung | Kỳ vọng |
|---|---|
| 50, 100, 150 ms | 0/5 lần báo |
| 250 ms | Vùng biên (thường có báo). Chỉ ghi nhận, không xét đạt. |
| 400, 800 ms | 5/5 lần báo |

Kiểm chứng chéo bằng PPK2: với xung ngắn, D1 (PROBE_EXC) phải **không** có cạnh xuống.

### T6 — Về khô và không dao động gần ngưỡng
1. Dùng R_SIM = 100 kΩ: giữ ướt 60 s rồi khô. Một lần báo "hết rò" sau 30–41 s.
2. **Dùng R_SIM = 2,2 MΩ** (gần ngưỡng): giữ ướt 10 phút.
   - **Đạt:** trạng thái giữ nguyên "rò", không bật tắt.
   - Xung kiểm tra 50 ms trước khi kết luận khô sẽ thấy rõ trên D1.
3. Lặp lại với 3,3 MΩ. Ghi nhận xem thiết bị có báo rò không, và nếu có thì trạng thái có ổn định không.

### T7 — Ngưỡng kích (FR-01)
1. Nối hộp điện trở thập phân (hoặc từng điện trở) vào J2 thay cho R_SIM, không qua opto.
2. Giảm dần từ 10 MΩ.
3. Ghi lại **R_trip**: giá trị lớn nhất mà sau 1 phút thiết bị báo rò.

**Kỳ vọng:** 1,3–4 MΩ, tuỳ Vth của Q4 (AO3400A). Nên đo cả kênh A: hàn tạm hai dây vào một ngón EXC và một ngón SNS của A1.

| Kênh | R_trip đo được | Đạt (1,3–4 MΩ) |
|---|---|---|
| A (răng lược đáy) | | |
| B (J2) | | |

### T8 — Thử với nước thật (FR-01), thiết bị nằm trong vỏ
Chạy `leak_test_runner.py … monitor` để ghi thời điểm. Đặt thiết bị lên khay khô rồi rót nước từ mép khay.

| Nước | Độ sâu 0,5 mm | 1 mm | 2 mm | 3 mm | Thời gian báo | Về khô sau khi lau |
|---|---|---|---|---|---|---|
| Nước máy | | | | | | |
| Nước RO / nước lọc | | | | | | |
| Nước mưa | | | | | | |
| Nước muối 1 % | | | | | | |
| Nước xà phòng giặt | | | | | | |
| Nước cất (tham khảo) | | | | | | |

- **Kỳ vọng:**
  - Báo ở **≥ 1,2 mm** (cửa sổ vỏ cách sàn 1,2 mm, xem [docs/04 §7](04-layout-pcb.md#7-vỏ-in-3d)).
  - Nước cất có thể **không** báo, vì điện trở rất cao.
  - Màng nước mỏng hơn 1,2 mm thì dùng đầu dò rời ở J2 đặt sát sàn.
- **Kiểm tra thêm:**
  - Nghiêng thiết bị 5°: vẫn phải báo.
  - Cả hai điện cực A1 và A2 đều kích được: cho nước vào từng đầu một.

### T9 — Không báo giả khi ẩm hoặc đọng sương (FR-01)
1. Đặt thiết bị khô 24 giờ trong hộp kín ở độ ẩm khoảng 95 %. **Đạt:** không có lần báo nào.
2. Đặt chai nước lạnh lên nắp, để sương đọng chảy xuống quanh vỏ. Ghi nhận kết quả.
3. Chạm ngón tay khô vào răng lược: không báo. Ngón tay ướt có thể kích; chỉ ghi nhận.

### T10 — Ngâm ướt 24 giờ: năng lượng và ăn mòn (FR-04, FR-11)
1. **Chuẩn bị:** dùng nước máy, thiết bị đang báo rò. PPK2 cách A.
2. **Ghi:** 30 phút ở 1 kS/s.
3. **Kỳ vọng dòng TB khi ướt:** sàn + LED (20 ms × khoảng 1,5 mA mỗi 3 s ≈ 10 µA) + xung đo. LED phải tự tắt sau 1 giờ.
4. **Sau 24 giờ:** chụp macro điện cực A1/A2, so với ảnh trước khi thử.
   - **Đạt:** không đổi màu hay rỗ ở ngón EXC (cực dương).
   - Lặp lại 7 ngày nếu có thời gian.

### T11 — Đo pin và cảnh báo pin yếu (FR-06, FR-07)
1. PPK2 cách A, quét điện áp: 3,30 → 3,10 → 3,00 → 2,90 → 2,80 → 2,70 → 2,60 → 2,40 → 2,20 → 2,00 → 1,90 V.
2. Ở mỗi mức: nhấn nút (để đo lại pin), rồi đọc trong HA (`BatVoltage` nếu HA tạo entity điện áp, % pin) và trong log UART.

| V nguồn | BatVoltage báo về | Sai số | % | BatChargeLevel |
|---|---|---|---|---|
| 3,30 | | | | |
| … | | | | |

- **Đạt:**
  - Sai số **≤ ±40 mV**.
  - Warning khi ≤ 15 %, Critical khi ≤ 5 %, theo bảng điện áp: khoảng 2,80 V và 2,60 V.
  - Thiết bị vẫn báo rò được ở 2,0 V (TPS63900 chạy tới 1,8 V).
- **Kiểm tra phát hiện pin mới:**
  - Rút nguồn rồi cấp lại ở 3,25 V: bộ đếm về 100 %.
  - Cấp lại ở 3,05 V: bộ đếm giữ nguyên.
  - Ngưỡng là `APP_BATTERY_NEW_CELL_MV` = 3,15 V.

### T12 — Tầm Thread và chọn chỗ đặt
Vị trí thử:
- gầm bồn rửa (tủ gỗ);
- sau máy giặt (vỏ kim loại);
- cạnh bình nóng lạnh (bình kim loại);
- khác tầng với border router;
- xa nhất có thể trong nhà.

Ở mỗi vị trí:
1. Nhấn nút một lần. LED nháy **1–3 lần** theo chất lượng liên kết tới router cha:
   - 3 = biên ≥ 20 dB, 2 = ≥ 10 dB, 1 = ≥ 2 dB, nháy dài = chưa bám được router.
   - Nếu có jig UART thì ghi RSSI từ log.
2. Chạy `latency --cycles 10` (laptop và bộ giả lập mang theo, HA nằm ở xa qua LAN).

| Vị trí | Số nháy (LQ) | RSSI (dBm) | Báo được / 10 | Độ trễ trung vị |
|---|---|---|---|---|
| | | | | |

- **Đạt:** LQ ≥ 2 và 10/10 lần báo.
- **Nếu LQ = 1 hoặc mất gói:** thêm một Thread router (ổ cắm thông minh Thread, HomePod…) ở gần, hoặc dời thiết bị.
- **Thử công suất phát** ở vị trí tệ nhất, với `APP_THREAD_TX_POWER_DBM` = 0 / +9 / +20 dBm:
  - đo RSSI phía router cha (thông qua LQ);
  - đo điện tích mỗi lần TX bằng PPK2;
  - chọn công suất nhỏ nhất cho LQ ≥ 2, rồi cập nhật mặc định trong Kconfig.

### T13 — Nút, LED, factory reset (FR-09..FR-11)

| Thao tác | Kỳ vọng | Kết quả |
|---|---|---|
| Nhấn ngắn khi khô | 1–3 nháy (LQ); ICD vào active mode | |
| Nhấn ngắn khi đang ướt | 5 nháy nhanh | |
| Nhấn ngắn khi pin ≤ 15 % (PPK2 ở 2,75 V) | Nháy đôi | |
| Giữ 5 s rồi thả | 2 nháy dài, **không** reset | |
| Giữ 12 s rồi thả | Nháy nhanh từ giây thứ 10, thả ra thì factory reset; ghép lại được ngay qua BLE | |
| Giữ 40 s rồi thả (giả lập kẹt nút) | Sau 30 s LED tắt, dòng (PPK2) về mức sàn; khi thả thì mọi thứ bình thường | |
| Xoá thiết bị khỏi Apple Home rồi khỏi HA | Sau khi xoá fabric cuối, thiết bị tự factory reset và quảng bá BLE lại | |

### T14 — Độ bền hệ thống

| Tình huống | Kỳ vọng |
|---|---|
| Rút pin 10 s rồi lắp lại | Tự nối lại Thread trong vòng 2 phút; trạng thái và % pin đúng |
| Khởi động lại border router hoặc HA | Thiết bị không "unavailable" lâu hơn khoảng 1 giờ (một chu kỳ keep-alive), báo rò ngay sau khi mạng trở lại |
| Rò nước khi border router đang khởi động lại | Báo được sau khi mạng có lại (OpenThread và Matter tự gửi lại) |
| Cả hai controller cùng lúc | Apple Home và HA đều nhận sự kiện rò ở T4 |
| (Tuỳ chọn) OTA | Cần OTA provider. HA chỉ lấy bản cập nhật từ DCL, nên với VID test cần `chip-ota-provider-app` + chip-tool trên Linux. Để sau. |

### T15 — Chạy dài ngày (2 tuần)
- **Cách chạy:** `leak_test_runner.py … --entity <rò> --entity <pin> monitor` chạy liên tục trên một máy luôn bật; pin CR123A thật.
- **Đạt:**
  - Không có lần báo giả nào.
  - Không lần nào "unavailable" quá 1 giờ.
  - % pin giảm đúng nhịp của bộ đếm: 43 µA × 168 h = 7,2 mAh, khoảng 0,5 %/tuần.
- **Sau 2 tuần:** đo lại T2 và cập nhật `APP_BATTERY_AVG_CURRENT_UA` bằng dòng TB thật.

## 4. Khi dòng sàn cao hơn 35 µA

| Triệu chứng | Nguyên nhân hay gặp | Cách kiểm tra |
|---|---|---|
| Sàn khoảng 85 µA | TOP domain không tắt khi light-sleep: có khoá PM đang giữ, hoặc thiếu `CONFIG_PM_POWER_DOWN_PERIPHERAL_IN_LIGHT_SLEEP` | Bản debug: bật `CONFIG_PM_PROFILING`, gọi `esp_pm_dump_locks(stdout)` trong sự kiện đo pin |
| Sàn khoảng 1 mA hoặc hơn, không ngủ | Ngõ EXT1 đang ở mức thấp: nút kẹt, đầu dò ướt nhưng chưa disarm, hoặc cáp logic kéo LEAK xuống | Log `armed (dry)`; tháo cáp logic; đo TP5/TP6 phải ≈ 3,3 V |
| Tăng vài µA | Cáp logic PPK2 lấy VCC từ board; jig UART còn cắm (TX/RX của bộ chuyển USB-UART cấp ngược dòng) | Tháo cáp logic và jig rồi đo lại |
| Tăng khoảng 33 µA | Q2 dẫn: VBAT_MEAS_EN (GPIO0) bị kẹt mức cao | Đo gate của Q2 phải ≈ 0 V khi ngủ |
| Tăng vài chục µA khi chưa ghép | BLE đang quảng bá (cửa sổ commissioning mở 15 phút) | Bình thường; đo lại sau khi ghép |
| Sàn đúng nhưng TB cao | Poll dày hơn 15 s, hoặc report lặp (nhiều subscription) | Xem "Chu kỳ slow poll" và số xung radio trong báo cáo của `ppk2_analyze.py` |
| Cần tách phần chip khỏi TPS63900 | — | Trên một board chưa hàn U2/L1 (hoặc board thứ hai), cấp 3,30 V từ PPK2 vào J1 chân 1 (+3V3) rồi đo. So với dòng đo ở BAT_RAW quy đổi: I_bat × 3,0 V × 0,91 / 3,3 V (hiệu suất khoảng 0,91 ở tải µA). |

## 5. Tổng hợp tiêu chí nghiệm thu

| Yêu cầu | Bài test | Tiêu chí | Đạt? |
|---|---|---|---|
| NFR-02 dòng sàn | T2 | ≤ 35 µA @ 3,0 V | |
| NFR-01 tuổi thọ | T2, T15 | ≥ 2 năm (bắt buộc), ≥ 3 năm (mục tiêu) với CR123A | |
| FR-02 độ trễ | T3, T4 | ≤ 1 s tới anten; HA trung vị ≤ 1,5 s, max ≤ 3 s | |
| FR-03 chống báo giả | T5, T6, T9 | Xung < 200 ms không báo; về khô 30–41 s; không dao động; không báo do ẩm | |
| FR-01 phát hiện | T7, T8 | R_trip 1,3–4 MΩ; nước máy, RO, mưa, muối, xà phòng đều báo ở ≥ 1,2 mm | |
| FR-04 điện phân | T3, T10 | Xung 5 ms / 10 s; điện cực không hỏng sau 24 h | |
| FR-06/07 pin | T11 | Sai số ≤ ±40 mV; Warning/Critical đúng ngưỡng | |
| FR-09..11 nút/LED | T13 | Đúng bảng | |
| FR-13 controller | T1, T4, T14 | Apple Home + HA cùng nhận, multi-admin | |
| Tầm Thread | T12 | LQ ≥ 2, 10/10 lần báo ở mọi vị trí lắp | |

Sau khi đo, chép số liệu vào các bảng ở trên. Các con số nào khác với giả định (dòng sàn, điện tích mỗi poll, R_trip, công suất phát) thì cập nhật vào `sdkconfig.defaults` / Kconfig và vào [docs/01 §6](01-yeu-cau-va-ngan-sach-dong.md#6-ngân-sách-dòng).
