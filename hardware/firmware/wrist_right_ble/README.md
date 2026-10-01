# WayBand right BLE wrist firmware

Arduino IDE에서 ESP32 보드 패키지를 설치한 뒤
`wrist_right_ble.ino`를 오른쪽 Seeed Studio XIAO ESP32C3에 업로드한다.

- Board: `XIAO_ESP32C3`
- Device name: `WAYBAND_RIGHT`
- Motor control pin: XIAO `D2` (chip `GPIO4`)
- BLE service: `7d8f1000-8e7f-4d3b-a3a6-6f44a16c1000`
- Command characteristic: `7d8f1001-8e7f-4d3b-a3a6-6f44a16c1000`
- Status characteristic: `7d8f1002-8e7f-4d3b-a3a6-6f44a16c1000`

Supported commands:

- `P|2000||255`: one 2000 ms pulse
- `P|500,500|300|190`: two 500 ms pulses separated by 300 ms
- `R1500`: legacy right-wrist test pulse
- `S` or `X`: stop immediately

The firmware never vibrates merely because it boots, connects, reconnects, or
disconnects. A BLE disconnect immediately stops any running pattern.
