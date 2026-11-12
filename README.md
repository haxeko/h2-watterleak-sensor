# h2-watterleak-sensor

Cảm biến rò rỉ nước chạy pin, kết nối **Matter over Thread**. Chip là **ESP32-H2**, chạy ở chế độ ICD / Sleepy End Device.
Thiết bị dùng được với Apple Home và Home Assistant thông qua Thread Border Router.

## Tiến độ theo giai đoạn

| # | Giai đoạn | Tài liệu | Trạng thái |
|---|---|---|---|
| 1 | Yêu cầu & ngân sách dòng | [docs/01-yeu-cau-va-ngan-sach-dong.md](docs/01-yeu-cau-va-ngan-sach-dong.md) | ✅ Đã chốt |
| 2 | Sơ đồ khối + gán chân GPIO | [docs/02-so-do-khoi-va-gan-chan.md](docs/02-so-do-khoi-va-gan-chan.md) | ✅ Đã chốt |
| 3 | Sơ đồ nguyên lý (KiCad 9) | [docs/03-so-do-nguyen-ly.md](docs/03-so-do-nguyen-ly.md) · [PDF](hardware/h2-leak-sensor/h2-leak-sensor_schematic.pdf) · [project](hardware/) | ✅ Xong, ERC 0 lỗi |
| 4 | Layout PCB, DRC, BOM, CPL, vỏ in 3D | [docs/04-layout-pcb.md](docs/04-layout-pcb.md) · [Gerber zip](hardware/h2-leak-sensor/fab/h2-leak-sensor_gerbers.zip) · [vỏ](hardware/enclosure/) | ✅ Xong, DRC 0 lỗi / 0 cảnh báo, chờ duyệt |
| 5 | Firmware (ESP-IDF v5.5.5 + esp-matter release/v1.6) | [docs/05-firmware.md](docs/05-firmware.md) · [firmware/](firmware/) | ✅ Đã viết code, chờ bạn build thử |
| 6 | Kế hoạch test (dòng ngủ, thử nước, tầm Thread) | [docs/06-ke-hoach-test.md](docs/06-ke-hoach-test.md) | ✅ Kế hoạch + công cụ xong, chờ board |

## Công cụ

| Script | Giai đoạn | Việc |
|---|---|---|
| `tools/power_budget.py` | 1, 6 | Mô hình dòng và tuổi thọ pin |
| `hardware/tools/gen_*.py`, `route.py`, `fab_outputs.py` | 3–4 | Sinh sơ đồ, board, đi dây, file sản xuất (xem [hardware/README.md](hardware/README.md)) |
| `tools/ppk2_analyze.py` | 6 | Phân tích bản ghi PPK2: dòng sàn/TB, poll, độ trễ báo rò, tuổi thọ |
| `tools/leak_test_runner.py` + `tools/leak_sim/` | 6 | Bộ giả lập nước + đo độ trễ / chống báo giả qua Home Assistant |

- `tools/power_budget.py`: mô hình ngân sách dòng và tuổi thọ pin, chỉ dùng thư viện chuẩn Python 3.

  ```sh
  python3 tools/power_budget.py              # in toàn bộ bảng (dùng trong tài liệu GĐ1)
  python3 tools/power_budget.py --sai 10     # thử slow-poll 10 s
  python3 tools/power_budget.py --floor 31.5 # thay sàn ngủ bằng số đo thật (GĐ6)
  ```
