# WayBand RIGHT USB serial wrist

Upload `wrist_right.ino` to the right ESP32 DevKit V1.

- Board: `DOIT ESP32 DEVKIT V1` (or the matching ESP32 DevKit board)
- Motor control: GPIO25 through the MOSFET gate circuit
- Baud rate: 115200
- `R1000`: vibrate for 1000 ms
- `X` or `S`: stop immediately
- `I`: print `WAYBAND_RIGHT` so Raspberry Pi can identify this USB port

Upload `../wrist_left/wrist_left.ino` to the left ESP32 DevKit. Both boards
must be connected to the Raspberry Pi with USB data cables.

The gateway normally identifies both boards automatically. If identical USB
serial adapters cannot be distinguished, set explicit stable paths before
starting a demo:

```bash
export WAYBAND_LEFT_SERIAL=/dev/serial/by-path/<left-path>
export WAYBAND_RIGHT_SERIAL=/dev/serial/by-path/<right-path>
```
