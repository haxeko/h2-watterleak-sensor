# h2-watterleak-sensor

Cảm biến rò rỉ nước chạy pin, kết nối **Matter over Thread**. Chip là **ESP32-H2**, chạy ở chế độ ICD / Sleepy End Device.
Thiết bị dùng được với Apple Home và Home Assistant thông qua Thread Border Router.

## Tiến độ theo giai đoạn

| # | Giai đoạn | Tài liệu | Trạng thái |
|---|---|---|---|
| 1 | Yêu cầu & ngân sách dòng | [docs/01-yeu-cau-va-ngan-sach-dong.md](docs/01-yeu-cau-va-ngan-sach-dong.md) | ✅ Đã chốt |
| 2 | Sơ đồ khối + gán chân GPIO | — | Chưa bắt đầu |
| 3 | Sơ đồ nguyên lý (KiCad) | — | Chưa bắt đầu |
| 4 | Layout PCB, DRC, BOM, CPL | — | Chưa bắt đầu |
| 5 | Firmware (ESP-IDF + esp-matter) | — | Chưa bắt đầu |
| 6 | Kế hoạch test (dòng ngủ, thử nước, tầm Thread) | — | Chưa bắt đầu |

## Công cụ

- `tools/power_budget.py`: mô hình ngân sách dòng và tuổi thọ pin, chỉ dùng thư viện chuẩn Python 3.

  ```sh
  python3 tools/power_budget.py              # in toàn bộ bảng (dùng trong tài liệu GĐ1)
  python3 tools/power_budget.py --sai 10     # thử slow-poll 10 s
  python3 tools/power_budget.py --floor 31.5 # thay sàn ngủ bằng số đo thật (GĐ6)
  ```
