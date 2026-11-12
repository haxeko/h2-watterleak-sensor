# Giai đoạn 1 — Yêu cầu & ngân sách dòng điện

> **Trạng thái:** ĐÃ CHỐT (2026-11-12). Các quyết định nằm ở [§9](#9-quyết-định-đã-chốt): **CR123A**, **ESP32-H2-WROOM-02C-H4S**, **không có buzzer**, **2 kênh đầu dò riêng**.
> Mọi con số dòng/tuổi thọ được sinh ra bởi [`tools/power_budget.py`](../tools/power_budget.py).
> Tới Giai đoạn 6, đo dòng thật rồi chạy lại với `--floor <µA đo được>` để cập nhật.

## 1. Tóm tắt

| Hạng mục | Đề xuất |
|---|---|
| Kiến trúc ngủ | Matter **ICD dạng SIT** chạy trên **Thread Sleepy End Device**. Chip ngủ **light-sleep có power-down CPU và peripheral**. Vận hành bình thường không dùng deep-sleep (lý do ở §3). Phần cứng vẫn đánh thức được từ deep-sleep qua LP GPIO (EXT1) như yêu cầu. |
| Dòng trung bình @3,3 V | **≈ 34 µA** điển hình, 27 µA lạc quan, 52 µA bi quan. Khoảng 74 % là dòng sàn light-sleep của chip (25 µA theo datasheet), nên tối ưu chu kỳ poll chỉ cải thiện được có giới hạn. |
| Tuổi thọ pin (điển hình / bi quan) | **CR123A (đã chọn) ≈ 3,4 / 2,2 năm**, lạc quan 4,2 năm. Các phương án đã loại để so sánh: 2×AAA lithium ≈ 3,0 / 2,0 · 2×AAA alkaline ≈ 2,1 / 1,4 · 2×AA alkaline ≈ 4,5 / 3,0. |
| Báo động tại chỗ | **Không có buzzer** (Q3). Báo động qua Matter (thông báo trên Apple Home / HA) và LED. |
| Nguồn | **TPS63900** buck-boost (IQ 75 nA, VIN 1,8–5,5 V, hiệu suất ≈ 85–91 % ở tải 10 µA) cấp 3,3 V. Thêm P-MOSFET chống ngược cực. |
| Đầu dò | Điện cực được phân cực bằng LP GPIO, qua MOSFET Vth thấp, pull-down 1 MΩ. **Khi khô, dòng qua điện cực = 0.** Khi ướt, MOSFET kéo LP GPIO xuống mức thấp để đánh thức chip. Sau đó firmware **bỏ phân cực và chuyển sang đo xung**, duty dưới 0,1 %. |
| Module | **Không có ESP32-H2-WROOM-01.** Chọn giữa **WROOM-02C-H4S** (đề xuất) và **MINI-1-H4S**. Bắt buộc bản **4 MB** flash để làm OTA. |
| ICD | SIT. Slow poll **15 s**, fast poll 200 ms, Active Mode 1 s, IdleModeDuration **1 h**. Firmware có tuỳ chọn LIT. |
| Thạch anh 32,768 kHz | **Có** (GPIO13/14). Đỡ khâu hiệu chuẩn RC mỗi lần ngủ (+3,3 µA) và giữ timing chính xác. |

## 2. Yêu cầu

### 2.1 Chức năng

| ID | Yêu cầu | Tiêu chí nghiệm thu |
|---|---|---|
| FR-01 | Phát hiện nước bằng điện cực răng lược ENIG ở mặt đáy PCB (2 vùng) và cổng đầu dò rời. | Kích khi điện trở giữa hai điện cực < ~1 MΩ (ngưỡng tuỳ Vth MOSFET, xem §5). Phát hiện được nước máy, nước mưa, nước RO. Độ ẩm không ngưng tụ không gây kích. |
| FR-02 | Báo ngay khi có nước. | Từ lúc nước chạm điện cực đến lúc gói Matter rời anten ≤ **1 s** (đã gồm debounce). |
| FR-03 | Chống báo giả. | Chỉ xác nhận "ướt" khi có 3 mẫu ướt liên tiếp, cách nhau ≥ 100 ms. Chỉ về "khô" khi khô liên tục ≥ 30 s (cấu hình được). Điện cực ngắn mạch thoáng qua < 200 ms thì không báo. |
| FR-04 | Chống điện phân và ăn mòn. | Khi khô: dòng qua điện cực ≈ 0 (chỉ còn rò nA). Khi ướt: dòng DC ≤ 3,3 µA (giới hạn bởi 1 MΩ), sau đó firmware chuyển sang đo xung 5 ms mỗi 10 s. |
| FR-05 | Matter device type **Water Leak Detector (0x0043)** trên EP1. | Có Identify và Boolean State (`StateValue` = TRUE khi rò, kèm sự kiện `StateChange`). Boolean State Configuration là tuỳ chọn, chỉ với feature Visual (LED), vì không có buzzer. |
| FR-06 | **Power Source** (feature BAT). | Có các thuộc tính `BatVoltage`, `BatPercentRemaining`, `BatChargeLevel`, `BatReplacementNeeded`, `BatReplaceability`, `BatReplacementDescription`, `BatQuantity`. % pin ước tính từ điện áp có tải kết hợp bộ đếm năng lượng trong firmware, vì CR123A có đường xả rất phẳng. |
| FR-07 | Cảnh báo pin yếu. | `BatChargeLevel` = Warning khi ≤ 15 %, Critical khi ≤ 5 % (ngưỡng điện áp cho CR123A). Gửi qua subscription. Tại chỗ: LED nháy mẫu "pin yếu" mỗi khi bấm nút hoặc khi có sự kiện. |
| FR-08 | ICD server. | Có ICD Management cluster. Tham số theo §7. Ngủ light-sleep giữa các lần poll. |
| FR-09 | Commissioning qua BLE, dùng một nút. | Nhấn ngắn: Identify / hiện trạng thái, hoặc mở lại cửa sổ commissioning nếu chưa vào fabric. Giữ 5 s: LED cảnh báo. Giữ 10 s: factory reset. |
| FR-10 | 1 LED trạng thái. | LED chỉ sáng khi có sự kiện (commissioning, kết nối xong, rò, pin yếu, reset). Không nháy "heartbeat" định kỳ. |
| FR-11 | ~~Buzzer~~: loại bỏ theo quyết định Q3. | Không có báo động âm thanh tại chỗ. Khi rò, LED nháy mẫu "rò" (20 ms mỗi 3 s) cho tới khi khô hoặc tối đa 1 h. |
| FR-12 | OTA Matter (OTA Requestor). | Flash 4 MB, 2 phân vùng app. |
| FR-13 | Tương thích controller. | Apple Home: iOS/tvOS ≥ 18.4 đã hiển thị Matter leak sensor. Home Assistant: Matter integration + OTBR. Multi-admin ≥ 2 fabric. |
| FR-14 | Nạp và debug. | Pad pogo: 3V3, GND, EN, IO9/BOOT, TXD0, RXD0, USB D−/D+. |

### 2.2 Phi chức năng

| ID | Yêu cầu |
|---|---|
| NFR-01 | Tuổi thọ pin ≥ 2 năm ở kịch bản bi quan, mục tiêu ≥ 3 năm ở kịch bản điển hình. |
| NFR-02 | Dòng sàn khi ngủ, đo ở cực pin (CR123A): ≤ 35 µA. Đây là tiêu chí test của Giai đoạn 6. |
| NFR-03 | Môi trường trong nhà, 0–45 °C. Điện cực được phép ngập. Phần mạch phía trên phải kín nước bắn. |
| NFR-04 | PCB 2 lớp, gia công JLCPCB. Linh kiện SMT có sẵn trên LCSC, ưu tiên loại Basic. |
| NFR-05 | Chống ngược cực pin. Có ESD/TVS trên cổng đầu dò rời. Cầu chia đo pin có công tắc, dòng rò khi ngủ ≈ 0. |
| NFR-06 | Anten module nằm ở mép board, tuân thủ keep-out của Espressif. Đường đầu dò đi xa vùng RF. |

## 3. Kiến trúc ngủ: light-sleep SED hay deep-sleep?

| Tiêu chí | **A. Light-sleep SED (chọn)** | B. Deep-sleep, reboot mỗi lần thức |
|---|---|---|
| Dòng sàn chip | 25 µA (DS bảng 5-9, CPU, radio và peripheral đều power-down) | 7 µA (DS bảng 5-9) |
| Trạng thái Thread | Vẫn là child của parent, poll định kỳ | Mất trạng thái. Parent xoá child sau child-timeout, nên mỗi lần thức phải attach lại: Parent Request rồi chờ trả lời với RX bật cỡ 1 s @ 25 mA |
| Phiên Matter | CASE session và subscription vẫn nằm trong RAM | Mất. Phải CASE resumption và khôi phục subscription |
| Độ trễ báo rò | ≈ 0,1–0,5 s | ≈ 2–5 s (boot + attach + CASE) |
| Controller nhìn thấy | Luôn phản hồi; Identify, OTA, đọc thuộc tính dùng được | "Không phản hồi" giữa các lần thức. Lệnh và OTA gần như không dùng được |
| Dòng TB @3,3 V | ≈ 34 µA | Mỗi lần thức tốn ≈ 50–100 mC. Thức mỗi 1 h thì ≈ 20–35 µA, tức là không lợi hơn. Chỉ lợi khi thức thưa (≥ 4 h), đổi lại mất tính "luôn kết nối" |

**Kết luận:** chọn A, cũng là cách esp-matter/ESP-IDF khuyến nghị cho Thread sleepy device. Phần cứng vẫn đáp ứng yêu cầu "đánh thức từ deep-sleep qua LP GPIO", vì đầu dò và nút đều nối vào LP GPIO. Hơn nữa, khi bật `CONFIG_PM_POWER_DOWN_PERIPHERAL_IN_LIGHT_SLEEP` thì API GPIO-wakeup thường bị vô hiệu, **chỉ EXT1 trên LP GPIO (GPIO8–14) còn dùng được**. Vậy là cùng một mạch chạy được cho cả hai chế độ ngủ.

## 4. Nguồn điện

### 4.1 Vì sao cần buck-boost
- ESP32-H2 cần **3,0–3,6 V**. Abs max là 3,6 V (DS bảng 5-1/5-2).
- CR123A (Li-MnO2): mới khoảng 3,2 V, hết pin ở khoảng 2,0 V. Dưới xung TX điện áp còn tụt thêm. Nối thẳng vào chip thì phần lớn đời pin sẽ dưới 3,0 V.
- 2×AAA alkaline: 3,2 V xuống 1,8 V. 2×AAA lithium (Li-FeS2) mới có thể lên tới ≈ 3,6 V hở mạch.
- Vì vậy phải vừa tăng áp (pin yếu) vừa hạ áp (Li-FeS2 mới). Bộ buck-boost xử lý được mọi loại pin trong danh sách.

### 4.2 So sánh lựa chọn

| IC | IQ | VIN | Nhận xét |
|---|---|---|---|
| **TPS63900** (chọn) | **75 nA** typ / 1 µA max | 1,8–5,5 V (UVLO lên 1,75 V, trễ 100 mV) | Buck-boost "single-mode", không có transient khi chuyển mode. Dòng ra > 400 mA khi VIN ≥ 2 V. Hiệu suất @ VO 3,3 V: ≈ 85 % (VIN 1,8 V) đến 91 % (VIN 3,0 V) ở tải 10 µA, 90–93 % ở tải mA. Vỏ WSON-10 2,5×2,5 mm pitch 0,5 mm, JLCPCB lắp được. VOUT và giới hạn dòng vào đặt bằng 3 điện trở. |
| TPS63901 | 75 nA | 1,8–5,5 V | Điện giống TPS63900 nhưng vỏ WCSP 12 bi pitch 0,35 mm, khó gia công với PCB phổ thông. |
| TPS6380x | ≈ 11 µA | 1,3–5,5 V | IQ bằng gần ½ dòng sàn của chip, mất 25–35 % tuổi thọ. |
| Boost nanopower (vd. TPS61094, MAX1722x) | sub-µA | dưới 1 V trở lên | Chỉ tăng áp. Không hạ được Li-FeS2 3,6 V xuống, chỉ hợp nếu khoá cứng một loại pin ≤ 3,3 V. |
| LDO | — | — | Không dùng được vì pin < 3,3 V gần như suốt đời. |

### 4.3 Cấu hình TPS63900 (chốt chi tiết ở GĐ3)
- **VOUT = 3,3 V:** `RCFG3 = 16,2 kΩ 1 %`, `SEL = GND` (chọn VO(1)).
- **Giới hạn dòng vào = Unlimited:** `RCFG1 = RCFG2 = 0 Ω`. Lý do: với giới hạn 100 mA, khi VIN = 2,0 V công suất ra tối đa ≈ 0,18 W, tức ≈ 55 mA @ 3,3 V. Mức đó thấp hơn dòng TX +9 dBm (60 mA) và rất xa TX +20 dBm (140 mA).
- L = 2,2 µH (Isat ≥ 1,5 A), CIN 10 µF, COUT 22 µF đặt sát IC, cộng tụ bulk 47–100 µF MLCC sát module để đỡ xung TX. Khi pin yếu, nội trở pin tăng; tụ bulk lúc này tránh brown-out.
- **Chống ngược cực:** dùng P-MOSFET kiểu "ideal diode" (gate nối GND). Rds(on) phải được chỉ định ở VGS = −1,8 V. Không có dòng tĩnh, sụt áp < 20 mV ở 100 mA.
- **Đo pin:** đo trước converter, qua cầu chia có MOSFET ngắt. Khi tắt, dòng rò = 0. ADC1 dùng ATTEN2 (0–1,9 V, sai số ±12 mV). Tuỳ chọn VOUT = 3,2 V (qua VO(2)) tiết kiệm thêm ≈ 3 %. Mặc định vẫn để 3,3 V cho dư biên.

## 5. Đầu dò nước: dòng nghỉ = 0 (nguyên lý, sơ đồ chi tiết ở GĐ3)

```
LP GPIO "PROBE_EXC" ──[10k]──► E1 (răng lược 1)  ┐
                                                 │ nước: R_w
                    E2 (răng lược 2) ──[10k]──┬──┴─► Gate Q (N-MOSFET, Vth thấp)
                                              ├─[1 MΩ]─► GND      (giới hạn dòng + đặt ngưỡng)
                                              └─[10 nF]─► GND     (lọc nhiễu RF / xung)
LP GPIO "LEAK_SENSE" ◄── Drain Q (pull-up ngoài 1 MΩ; EXT1 ANY_LOW) ; Source Q → GND
TVS 2 chiều, dòng rò thấp, trên E1/E2 của cổng đầu dò rời
```

- **Khô:** E1 ở 3,3 V nhưng hở mạch nên I = 0 (chỉ rò nA). Q tắt, LEAK_SENSE = 1.
- **Ướt:** V_G = 3,3 V · 1 MΩ / (1 MΩ + R_w + 20 kΩ) > Vth. Q dẫn, LEAK_SENSE = 0, EXT1 đánh thức chip từ light-sleep hoặc deep-sleep. Dòng qua nước ≤ 3,3 µA vì bị 1 MΩ chặn.
- **Sau khi xác nhận:** firmware hạ PROBE_EXC = 0 để bỏ phân cực, rồi đo xung 5 ms mỗi 10 s. Dòng DC trung bình qua nước < 2 nA. Xung 5 ms đủ cho cổng MOSFET nạp tới ngưỡng cả với nước RO (τ ≈ 2,7 ms, xem GĐ3).
  - Nếu để DC 3,3 µA liên tục, lượng điện tích đủ để hoà tan cả lớp vàng ENIG 0,05–0,1 µm của cực dương (≈ 0,2 C/cm²) sẽ đạt sau khoảng 1 ngày. Đây là cận trên, nhưng cho thấy vì sao phải đo xung.
- **Ngưỡng:** R_w,trip ≈ 1 MΩ · (3,3 / Vth − 1). Với Vth của AO3400A 0,65–1,45 V, ngưỡng nằm khoảng **1,3–4 MΩ** (tính chi tiết ở GĐ3).
  - Nước máy trên lược khe 0,5 mm: vài trăm Ω đến vài chục kΩ.
  - Nước RO: ≈ 25–250 kΩ.
  - Màng ẩm sạch trên solder mask: > 100 MΩ.
  - Biên an toàn giữa ba trường hợp này lớn.
- **2 kênh:** kênh A là điện cực đáy (2 vùng nối song song), kênh B là cổng đầu dò rời. Hai kênh dùng chung PROBE_EXC, mỗi kênh chiếm 1 LP GPIO để firmware biết nước ở đâu (tuỳ quyết định Q4).

## 6. Ngân sách dòng

### 6.1 Số liệu gốc

| Thông số | Giá trị | Nguồn |
|---|---|---|
| TX 802.15.4 @ +20 / +9 / 0 / −24 dBm | 140 / 60 / 36 / 24 mA | ESP32-H2 DS v1.3, bảng 5-7 |
| RX 802.15.4 | 25 mA | bảng 5-7 |
| Modem-sleep 96 MHz: CPU idle / chạy (clock peripheral tắt → bật) | 6 / 10–17 mA | bảng 5-8 |
| Light-sleep, CPU + radio + peripheral power-down | **25 µA** | bảng 5-9 |
| Light-sleep, peripheral chỉ gate clock (TOP không power-down) | 85 µA | bảng 5-9 |
| Deep-sleep (RTC timer + LP memory) / Power-off | 7 / 1 µA | bảng 5-9 |
| TPS63900 IQ / hiệu suất @ VO 3,3 V | 75 nA; ≈ 85–91 % @ 10 µA, ≈ 90–93 % @ 1–100 mA | SLVSET3D, EC table, hình 8-7 |
| 802.15.4 PHY | 32 µs/byte, backoff 320 µs, turnaround 192 µs | IEEE 802.15.4-2.4 GHz |

### 6.2 Giả định chính (tham số trong script)
- **1 lần poll:** đánh thức (wake), chờ CSMA-CA, CCA, TX Data Request (PSDU 22 B, có MAC security), rồi chờ ACK (frame-pending = 0). Wake và ngủ lại tốn tổng 2,5 ms @ 6 mA. Đây là ước tính, sẽ đo ở GĐ6.
- **1 báo cáo Matter:**
  - Đánh thức, TX 1,5 frame ReportData, CPU chạy 20 ms @ 15 mA.
  - Fast poll 200 ms trong 1 s Active Mode.
  - Nhận StatusResponse, gửi MRP ACK.
- **Subscription:** 2 subscription (Apple Home hub + Home Assistant), MaxInterval = IdleModeDuration = 1 h.
- **Bảo trì mạng:**
  - Child supervision 129 s (mặc định OpenThread, mỗi lần nhận thêm 1 frame).
  - Làm mới SRP 2 h/lần (3 frame + chữ ký ECDSA 60 ms).
- **Sự kiện theo năm:**
  - 2 lần rò mỗi năm, mỗi lần 1 h ướt: 4 báo cáo Matter, đo xung 10 s/lần, LED 20 ms @ 3 mA mỗi 3 s. Không có buzzer.
  - 1 OTA/năm ≈ 2,3 mAh.
  - Commissioning một lần ≈ 3 mAh.
- **Pin:**
  - CR123A: 1450 mAh, 2,85 V trung bình, dùng được 92 %, tự xả 1 %/năm.
  - 2×AAA Li-FeS2: 1200 mAh, 3,0 V, 95 %, 1 %/năm.
  - 2×AAA alkaline: 1150 mAh, 2,45 V, 90 %, 2,5 %/năm.
- **Kịch bản bi quan:**
  - Sàn 40 µA (rò flash in-package, linh kiện thực tế), board 1 µA, poll × 1,3 (retry MAC).
  - 3 subscription, 6 lần rò/năm, 2 OTA/năm.
- **Kịch bản lạc quan:** sàn 20 µA, TX 0 dBm, 1 subscription.

### 6.3 Điện tích từng sự kiện (điển hình, +9 dBm, có XTAL 32 kHz)

| Sự kiện | Điện tích |
|---|---|
| Wake + ngủ lại (1 chu kỳ light-sleep) | 15.0 µC |
| Wake + ngủ lại khi KHÔNG có XTAL 32 kHz (thêm hiệu chuẩn RC) | 62.3 µC |
| 1 Thread data poll @ 0 dBm | 80.6 µC |
| 1 Thread data poll @ +9 dBm | 102.1 µC |
| 1 Thread data poll @ +20 dBm | 173.8 µC |
| 1 báo cáo Matter (ReportData + Active Mode + ACK) | 1.47 mC |
| 1 lần làm mới SRP | 2.39 mC |
| 1 sự kiện rò rỉ 1 h (LED + đo xung + 4 báo cáo) | 0.024 mAh |
| *(tham khảo) như trên nếu có buzzer* | 0.55 mAh |

### 6.4 Phân rã dòng trung bình @3,3 V

| Thành phần | Lạc quan | **Điển hình** | Bi quan |
|---|---:|---:|---:|
| Ngủ nhẹ (sàn chip) | 20.00 | **25.00** | 40.00 |
| Rò rỉ trên board | 0.50 | **0.50** | 1.00 |
| Thread data poll (SAI 15 s) | 5.37 | **6.81** | 8.85 |
| Child supervision | 0.41 | **0.51** | 0.51 |
| Báo cáo keep-alive (subscriptions) | 0.32 | **0.82** | 1.60 |
| Làm mới SRP | 0.27 | **0.33** | 0.35 |
| Đo pin (6 h/lần) | 0.00 | **0.00** | 0.00 |
| **Tổng (µA)** | **26.9** | **34.0** | **52.3** |
| Sự kiện theo năm (rò, OTA), mAh/năm | 2.3 | 2.3 | 4.8 |

### 6.5 Tuổi thọ pin ước tính (năm)

| Pin | Năng lượng dùng được | Dòng từ pin (điển hình) | Lạc quan | **Điển hình** | Bi quan |
|---|---:|---:|---:|---:|---:|
| CR123A (Li-MnO2, 1 cell) | 3.80 Wh | 43.1 µA | 4.2 | **3.4** | 2.2 |
| 2×AAA lithium (Li-FeS2) | 3.42 Wh | 40.8 µA | 3.8 | **3.0** | 2.0 |
| 2×AAA alkaline | 2.54 Wh | 51.7 µA | 2.6 | **2.1** | 1.4 |
| 2×AA alkaline (tham khảo) | 5.73 Wh | 51.7 µA | 5.5 | **4.5** | 3.0 |

**Đọc kết quả:**
- CR123A đạt ≥ 2 năm kể cả ở kịch bản bi quan.
- 2×AAA alkaline chỉ đạt khoảng 2 năm ở kịch bản điển hình. Ngoài ra alkaline có nguy cơ chảy dịch sau 2–3 năm, đúng ở nơi đặt sát sàn ẩm.
- Muốn trên 4 năm thì phải dùng pin to hơn (2×AA). Tối ưu firmware không đủ, vì dòng sàn chip chiếm khoảng ¾.

### 6.6 Đánh đổi chu kỳ poll ICD

Leak và battery đều là báo cáo **do thiết bị khởi phát**: chip thức dậy và gửi ngay, không phải chờ đến lần poll. Slow poll chỉ quyết định độ trễ của lệnh **từ controller xuống thiết bị**: Identify, đọc thuộc tính, cấu hình, bắt đầu OTA.

| Chế độ | Slow poll | Trễ lệnh controller→thiết bị (tối đa) | Dòng TB @3,3 V | CR123A | 2×AAA alkaline |
|---|---:|---:|---:|---:|---:|
| SIT | 5 s | 5 s | 47.6 µA | 2.4 năm | 1.6 năm |
| SIT | 10 s | 10 s | 37.4 µA | 3.1 năm | 1.9 năm |
| **SIT** | **15 s** | **15 s** | **34.0 µA** | **3.4 năm** | **2.1 năm** |
| LIT | 30 s | 30 s | 30.6 µA | 3.7 năm | 2.3 năm |
| LIT | 60 s | 60 s | 28.9 µA | 3.9 năm | 2.5 năm |

- SIT bị giới hạn slow poll ≤ 15 s.
- LIT cần controller hỗ trợ Check-In protocol.
- Từ SIT 15 s lên LIT 60 s chỉ thêm khoảng 15 % tuổi thọ, vì dòng sàn chiếm phần lớn. Vì vậy đề xuất **SIT 15 s** để tương thích rộng nhất. Firmware vẫn để tuỳ chọn LIT; khi chưa có client đăng ký Check-In, thiết bị tự chạy như SIT.

### 6.7 Độ nhạy (kịch bản điển hình, CR123A)

| Thay đổi | Dòng TB @3,3 V | Tuổi thọ CR123A |
|---|---:|---:|
| Cơ sở (SAI 15 s, +9 dBm, XTAL 32 kHz, IdleModeDuration 1 h) | 34.0 µA | 3.4 năm |
| TX 0 dBm | 32.2 µA | 3.5 năm |
| TX +20 dBm | 39.8 µA | 2.9 năm |
| Không lắp XTAL 32 kHz (hiệu chuẩn RC mỗi chu kỳ ngủ) | 37.3 µA | 3.1 năm |
| IdleModeDuration 15 phút thay vì 1 h | 36.4 µA | 3.2 năm |
| Fast poll 500 ms thay vì 200 ms | 33.8 µA | 3.4 năm |
| **Lỗi FW: peripheral không power-down khi ngủ (sàn 85 µA)** | **94.0 µA** | **1.2 năm** |

> ⚠️ Rủi ro lớn nhất **không nằm ở phần cứng**. Nó nằm ở chỗ firmware có thực sự power-down được miền peripheral (TOP) khi ngủ hay không.
> - Một số driver ngăn power-down: USB-Serial-JTAG console, SARADC đang mở, PCNT, hoặc một lock PM bị giữ.
> - Nếu power-down không xảy ra, sàn ngủ nhảy từ 25 lên 85 µA và tuổi thọ giảm gần 3 lần.
> - GĐ5 sẽ cấu hình để tránh các trường hợp trên. GĐ6 sẽ đo xác nhận.

## 7. Tham số ICD / Thread đề xuất

| Tham số | Giá trị | Lý do |
|---|---|---|
| Chế độ ICD | SIT (tuỳ chọn LIT, fallback SIT) | Tương thích Apple Home và HA. Xem §6.6. |
| Slow Poll Interval | 15 s | Mức tối đa của SIT. Báo rò không bị ảnh hưởng. |
| Fast Poll Interval (Active Mode) | 200 ms | Nhận phản hồi nhanh sau khi gửi báo cáo. Đổi sang 500 ms gần như không đổi mức tiêu thụ. |
| Active Mode Duration / Threshold | 1000 ms / 1000 ms | Đủ cho một trao đổi ReportData↔StatusResponse. |
| Idle Mode Duration | 3600 s | Thành MaxInterval của subscription (keep-alive 1 h/lần). Controller phát hiện thiết bị chết trong khoảng 1 h. |
| Thread | MTD, SED (data poll), child supervision mặc định | Không dùng SSED/CSL vì cần đồng hồ chính xác và router hỗ trợ CSL. |
| TX power | +9 dBm, chỉnh sau khi thử tầm ở GĐ6 | Xuống 0 dBm chỉ tiết kiệm khoảng 5 %. Ưu tiên giữ link ổn định. |
| Nguồn đồng hồ ngủ | XTAL 32,768 kHz ngoài | `CONFIG_RTC_CLK_SRC_EXT_CRYS`. Bỏ được bước hiệu chuẩn RC mỗi lần ngủ. |

## 8. Ràng buộc chân đã kiểm tra trong datasheet (đầu vào cho GĐ2)

**Strapping (DS v1.3 §3):**
- **GPIO8** mặc định floating. Download boot cần GPIO8 = 1 và GPIO9 = 0.
  - Nếu GPIO8 lái tải thì phải có **pull-up ngoài** để strap luôn đọc mức 1.
  - Kết luận: không dùng GPIO8 để kéo xuống trong lúc reset.
- **GPIO9** có WPU. Mức 0 khi reset sẽ vào download. Đây là chân nút BOOT, cũng là LP GPIO nên dùng làm nguồn đánh thức được.
- **GPIO25** (chọn nguồn JTAG) không có pull nội. Chỉ có tác dụng khi eFuse `STRAP_JTAG_SEL_ENABLE` = 1; mặc định bị bỏ qua.
- **Thời gian giữ strap:** t_H ≥ 3 ms sau khi CHIP_EN lên mức cao. Mạch RC/tụ trên GPIO9 không được làm trễ quá mức này.

**LP GPIO:**
- Chỉ có **GPIO8–14** (7 chân). Đây là các chân duy nhất hoạt động trong deep-sleep, hoạt động khi TOP power-down, và đánh thức được bằng EXT1 (ANY_LOW / ANY_HIGH / mask theo từng chân).
- GPIO13/14 dành cho XTAL 32 kHz.
- Như vậy còn **5 LP GPIO** cho: nút, phân cực đầu dò, 1–2 kênh sense, LED.

**Chân khác:**
- ADC1: GPIO1–5 (CH0–CH4).
- USB: GPIO26 = D−, GPIO27 = D+ (USB pull-up bật mặc định).
- UART0: GPIO23 = RX, GPIO24 = TX.
- GPIO2–5 là chân JTAG pad, mặc định chỉ có IE.
- GPIO0, 1, 10–14, 22 không có pull khi reset.

**Hành vi khi ngủ:**
- Chân digital (GPIO0–5, 22–27) mất trạng thái khi TOP power-down. Mọi ngõ ra digital (ví dụ công tắc cầu chia đo pin) vì vậy phải **mặc định tắt bằng điện trở kéo ngoài**.
- Pull nội không giữ được khi RTC peripheral tắt. Các ngõ vào đánh thức (nút, sense) cần **pull-up ngoài**.

## 9. Quyết định đã chốt

| # | Câu hỏi | Quyết định (2026-11-12) | Hệ quả |
|---|---|---|---|
| Q1 | Loại pin | **CR123A** (1 cell Li-MnO2) | Tuổi thọ ≈ 3,4 năm điển hình, 2,2 năm bi quan. VBAT ≤ 3,3 V nên cầu chia đo pin không bao giờ đưa áp vượt VDD lên chân ADC. |
| Q2 | Module | **ESP32-H2-WROOM-02C-H4S** | 20×18×3,2 mm, 4 MB, chân castellated. Mạch RC 10 kΩ/1 µF cho EN đã có sẵn trong module. |
| Q3 | Buzzer | **Không** | Bỏ FR-11. Tiết kiệm 1 GPIO và 1 MOSFET. Boolean State Configuration chỉ còn Visual, hoặc bỏ. |
| Q4 | Kênh đầu dò | **2 kênh riêng**: A = điện cực đáy (2 vùng song song), B = cổng đầu dò rời | Mỗi kênh 1 LP GPIO sense, dùng chung PROBE_EXC. Firmware gộp OR vào 1 endpoint Water Leak (có thể tách sau). |

**Mặc định đang áp dụng** (bạn có thể đổi bất cứ lúc nào):
- KiCad 9.
- JLCPCB: 2 lớp, FR4 1,6 mm, **ENIG** (bắt buộc cho điện cực).
- ESP-IDF: bản mà esp-matter release ổn định mới nhất yêu cầu (kiểm lại ở GĐ5).
- Có thạch anh 32 kHz. Có pad pogo UART + USB.
- TX +9 dBm. SIT 15 s.
- Kích thước board và vỏ in 3D: sẽ hỏi trước GĐ4.

## 10. Nguồn tham khảo
- [ESP32-H2 Series Datasheet v1.3](https://documentation.espressif.com/esp32-h2_datasheet_en.html): bảng 2-1, 3-1…3-6, 5-1…5-9.
- [ESP32-H2-WROOM-02C Datasheet v1.2](https://documentation.espressif.com/esp32-h2-wroom-02c_datasheet_en.html).
- [ESP32-H2-MINI-1/1U Datasheet](https://documentation.espressif.com/esp32-h2-mini-1_mini-1u_datasheet_en.pdf).
- [ESP-IDF Sleep Modes (ESP32-H2)](https://docs.espressif.com/projects/esp-idf/en/v5.4.2/esp32h2/api-reference/system/sleep_modes.html) và [Power Management](https://docs.espressif.com/projects/esp-idf/en/v5.4.2/esp32h2/api-reference/system/power_management.html).
- Ví dụ ESP-IDF `examples/openthread/ot_sleepy_device` (light_sleep / deep_sleep).
- [TI TPS63900 datasheet (SLVSET3D)](https://www.ti.com/lit/ds/symlink/tps63900.pdf) và [trang sản phẩm](https://www.ti.com/product/TPS63900).
- [Matter Alpha: iOS 18.4 hỗ trợ Matter water leak sensor](https://www.matteralpha.com/manufacturer-news/ios-18-4-expands-matter-support-with-smoke-co-and-water-leak-sensors).
