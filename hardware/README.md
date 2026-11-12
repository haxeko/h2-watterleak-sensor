# Phần cứng — h2-watterleak-sensor rev A (KiCad 9)

```
hardware/
├── h2-leak-sensor/                 project KiCad 9 (mở h2-leak-sensor.kicad_pro)
│   ├── h2-leak-sensor.kicad_sch    trang gốc (4 sheet con)
│   ├── power.kicad_sch  mcu.kicad_sch  probe.kicad_sch  ui.kicad_sch
│   ├── h2-leak-sensor_schematic.pdf
│   ├── bom/h2-leak-sensor_bom.csv  BOM gộp theo giá trị (không gồm module ESP)
│   ├── lib/h2leak.kicad_sym        symbol riêng: ESP32-H2-WROOM-02C, Electrode_Comb
│   ├── lib/h2leak.pretty/          footprint riêng (module, TPS63900 hàn tay, 4020, điện cực)
│   ├── sym-lib-table  fp-lib-table bảng thư viện của project (thư viện "h2leak")
└── tools/
    ├── sexpr.py                    đọc/ghi S-expression của KiCad (không phụ thuộc gì)
    ├── gen_lib.py                  sinh thư viện riêng
    └── gen_sch.py                  sinh sơ đồ nguyên lý phân cấp
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

Tài liệu thiết kế:
- [docs/02-so-do-khoi-va-gan-chan.md](../docs/02-so-do-khoi-va-gan-chan.md): sơ đồ khối và gán chân.
- [docs/03-so-do-nguyen-ly.md](../docs/03-so-do-nguyen-ly.md): sơ đồ nguyên lý.
