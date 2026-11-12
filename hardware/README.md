# Phần cứng — h2-watterleak-sensor rev A (KiCad 9)

```
hardware/
├── h2-leak-sensor/                 project KiCad 9 (mở h2-leak-sensor.kicad_pro)
│   ├── h2-leak-sensor.kicad_sch    trang gốc (4 sheet con)
│   ├── power.kicad_sch  mcu.kicad_sch  probe.kicad_sch  ui.kicad_sch
│   ├── h2-leak-sensor_schematic.pdf
│   ├── h2-leak-sensor.kicad_pcb    board 70 x 42 mm, 2 lớp, đã đi dây (luật DRC trong .kicad_pro)
│   ├── fab/                        Gerber zip, BOM + CPL cho JLCPCB, PDF lắp ráp, báo cáo DRC
│   ├── bom/h2-leak-sensor_bom.csv  BOM gộp theo giá trị (không gồm module ESP)
│   ├── lib/h2leak.kicad_sym        symbol riêng: ESP32-H2-WROOM-02C, Electrode_Comb
│   ├── lib/h2leak.pretty/          footprint riêng (module, TPS63900 hàn tay, 4020, điện cực)
│   ├── sym-lib-table  fp-lib-table bảng thư viện của project (thư viện "h2leak")
├── enclosure/                      vỏ in 3D: h2-leak-enclosure.scad + 3 file STL
└── tools/
    ├── sexpr.py                    đọc/ghi S-expression của KiCad (không phụ thuộc gì)
    ├── gen_lib.py                  sinh thư viện riêng
    ├── gen_sch.py                  sinh sơ đồ nguyên lý phân cấp
    ├── gen_pcb.py                  đặt linh kiện, luật DRC, vùng đổ GND, keep-out, silkscreen
    ├── route.py                    router A* 2 lớp + đổ GND + sửa liên thông GND
    └── fab_outputs.py              Gerber, drill, BOM/CPL JLCPCB, PDF lắp ráp, DRC
```

## Tái tạo và kiểm tra

Cần KiCad 9 (`kicad-cli`) và Python 3.

```sh
python3 hardware/tools/gen_lib.py
python3 hardware/tools/gen_sch.py
cd hardware/h2-leak-sensor
kicad-cli sch erc --severity-all h2-leak-sensor.kicad_sch          # kỳ vọng: 0 violations
kicad-cli sch export pdf -o h2-leak-sensor_schematic.pdf h2-leak-sensor.kicad_sch
kicad-cli sch export bom --fields 'Reference,Value,Footprint,LCSC,MPN,Manufacturer,${QUANTITY}' \
    --group-by 'Value,Footprint,LCSC' -o bom/h2-leak-sensor_bom.csv h2-leak-sensor.kicad_sch
```

Layout và file sản xuất (cần thêm `numpy`):

```sh
python3 hardware/tools/gen_pcb.py        # đọc netlist từ sơ đồ, đặt linh kiện
python3 hardware/tools/route.py          # đi dây, đổ GND, kiểm tra liên thông GND (~4 phút)
python3 hardware/tools/fab_outputs.py    # fab/: Gerber zip, BOM, CPL, PDF lắp ráp, DRC json
cd hardware/h2-leak-sensor
kicad-cli pcb drc --severity-all --schematic-parity h2-leak-sensor.kicad_pcb   # kỳ vọng: 0 / 0 / 0
```

> `gen_pcb.py` tạo board mới từ đầu, nên mọi chỉnh tay trên board sẽ mất.
> Nếu đã chỉnh tay thì chỉ chạy `route.py --gnd-only` (kiểm tra và sửa liên thông GND) và `fab_outputs.py`.

Tài liệu thiết kế:
- [docs/02-so-do-khoi-va-gan-chan.md](../docs/02-so-do-khoi-va-gan-chan.md): sơ đồ khối và gán chân.
- [docs/03-so-do-nguyen-ly.md](../docs/03-so-do-nguyen-ly.md): sơ đồ nguyên lý.
- [docs/04-layout-pcb.md](../docs/04-layout-pcb.md): layout, DRC, file sản xuất, vỏ.
