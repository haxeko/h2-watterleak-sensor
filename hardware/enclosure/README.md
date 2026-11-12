# Vỏ in 3D — h2-watterleak-sensor rev A

File nguồn: [`h2-leak-enclosure.scad`](h2-leak-enclosure.scad). Đây là file OpenSCAD có tham số; vị trí các chi tiết lấy từ `hardware/tools/gen_pcb.py`.
Đã xuất sẵn 3 file STL: `h2-leak-base.stl`, `h2-leak-lid.stl`, `h2-leak-plunger.stl`.

```sh
openscad -o h2-leak-base.stl    -D 'part="base"'    h2-leak-enclosure.scad
openscad -o h2-leak-lid.stl     -D 'part="lid"'     h2-leak-enclosure.scad
openscad -o h2-leak-plunger.stl -D 'part="plunger"' h2-leak-enclosure.scad
```

| Thông số | Giá trị |
|---|---|
| Kích thước ngoài | ≈ 82,5 × 46,4 × 29,2 mm (D × R × C) |
| Vật liệu | **PETG** hoặc **ASA**. Không dùng PLA vì PLA hút ẩm và mềm khi đặt gần bình nóng lạnh. |
| In | Lớp 0,2 mm, 3 vòng tường, 4 lớp đáy/đỉnh, infill 25 %, không cần support. Đế in úp đáy xuống. Nắp in lật ngược (mặt chữ LEAK nằm trên bàn in). |
| Vít | 4 × M2×8 bắt từ dưới đáy, qua lỗ PCB, vào trụ của nắp (vít tự ren vào nhựa). **H1/H2 nằm gần anten nên dùng vít nhựa nylon.** |

## Đặc điểm thiết kế

- **Đế:**
  - Sàn dày 1,2 mm, có 2 cửa sổ vát 45° ngay dưới hai điện cực A1/A2. PCB nằm phẳng trên sàn, nên điện cực cách mặt đất khoảng **1,2 mm**: vũng nước sâu ≥ 1,2 mm là kích. Muốn bắt cả màng nước mỏng hơn thì dùng **đầu dò rời ở J2** đặt sát sàn.
  - Có hốc sâu 0,7 mm dưới các chân THT (đế pin, J2, J1, lỗ hàn EPAD của module). **Cắt chân THT còn ≤ 0,6 mm** để PCB nằm phẳng.
  - Vách phải có khe cho phích JST-PH của J2.
- **Phía anten:**
  - Lòng vỏ chừa thêm 8,5 mm bên trái PCB cho phần anten chìa ra (6 mm) cộng khe hở 2,5 mm.
  - **Không đặt vật kim loại** (vít thép, nam châm, băng dính nhôm) trong khoảng 15 mm quanh anten.
- **Nắp:**
  - 4 trụ ép PCB xuống sàn.
  - Ống dẫn hướng Ø4,2 mm cho chốt bấm nút SW1. Chốt in rời, có vành chặn; lắp từ phía trong trước khi đóng nắp.
  - Lỗ Ø2,2 mm phía trên LED1. Có thể nhét một đoạn filament trong (light pipe) hoặc nhỏ keo trong vào lỗ.
- **Chống nước:**
  - Mặt đáy PCB phải được **phủ conformal coating** (hoặc sơn móng tay hay epoxy mỏng) ở mọi chỗ, **trừ hai vùng răng lược A1/A2**. Đặc biệt phải phủ các chân THT và cực + / − của đế pin.
  - Mép ghép nắp–đế có thể bôi một đường silicone mỏng.

## Kiểm tra sau khi in

1. PCB đặt vừa vào đế, các lỗ M2 thẳng hàng với 4 lỗ trên PCB.
2. Chốt bấm nhấn được nút SW1 với hành trình khoảng 0,3 mm, và tự bật lại.
3. Phích JST-PH cắm vào J2 qua khe được.
4. Pin CR123A tháo lắp được khi mở nắp.
5. Đổ thử khoảng 2 mm nước lên mặt phẳng rồi đặt thiết bị vào: hai cửa sổ phải ngập.
