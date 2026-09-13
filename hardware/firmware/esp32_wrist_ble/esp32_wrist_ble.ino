#include <ArduinoBLE.h>

// Build LEFT_WRIST=1 for the left device and 0 for the right device.
#ifndef LEFT_WRIST
#define LEFT_WRIST 0
#endif

const int MOTOR_PIN = D2;
BLEService waybandService("7d8f1000-8e7f-4d3b-a3a6-6f44a16c1000");
BLEStringCharacteristic commandCharacteristic("7d8f1001-8e7f-4d3b-a3a6-6f44a16c1000", BLEWrite, 96);
BLEStringCharacteristic statusCharacteristic("7d8f1002-8e7f-4d3b-a3a6-6f44a16c1000", BLERead | BLENotify, 32);
unsigned int pulseMs[10], gapMs[9];
int pulseCount = 0, pulseIndex = 0;
bool active = false, motorOn = false;
unsigned long nextChange = 0;

void motor(bool on) { digitalWrite(MOTOR_PIN, on ? HIGH : LOW); }

void stopPattern(String status) {
  active = false; motorOn = false; pulseCount = 0; motor(false);
  statusCharacteristic.writeValue(status);
}

int parseNumbers(String text, unsigned int *output, int capacity) {
  int count = 0;
  while (text.length() && count < capacity) {
    int comma = text.indexOf(','); String token = comma < 0 ? text : text.substring(0, comma);
    output[count++] = token.toInt();
    if (comma < 0) break;
    text = text.substring(comma + 1);
  }
  return count;
}

void executePattern(String command) {
  if (command == "S") { stopPattern("ACK:STOP"); return; }
  if (!command.startsWith("P|")) { statusCharacteristic.writeValue("ERR:FORMAT"); return; }
  int first = command.indexOf('|'); int second = command.indexOf('|', first + 1); int third = command.indexOf('|', second + 1);
  String pulses = command.substring(first + 1, second); String gaps = command.substring(second + 1, third);
  pulseCount = parseNumbers(pulses, pulseMs, 10); parseNumbers(gaps, gapMs, 9);
  if (!pulseCount) { stopPattern("ERR:EMPTY"); return; }
  pulseIndex = 0; active = true; motorOn = true; motor(true);
  nextChange = millis() + pulseMs[0]; statusCharacteristic.writeValue("ACK:START");
}

void updatePattern() {
  if (!active || (long)(millis() - nextChange) < 0) return;
  if (motorOn) {
    motor(false); motorOn = false;
    if (pulseIndex >= pulseCount - 1) { stopPattern("ACK:DONE"); return; }
    nextChange = millis() + gapMs[pulseIndex];
  } else {
    pulseIndex++; motor(true); motorOn = true;
    nextChange = millis() + pulseMs[pulseIndex];
  }
}

void setup() {
  pinMode(MOTOR_PIN, OUTPUT); motor(false); Serial.begin(115200);
  if (!BLE.begin()) while (true) delay(1000);
  BLE.setLocalName(LEFT_WRIST ? "WAYBAND_LEFT" : "WAYBAND_RIGHT");
  BLE.setAdvertisedService(waybandService); waybandService.addCharacteristic(commandCharacteristic); waybandService.addCharacteristic(statusCharacteristic);
  BLE.addService(waybandService); statusCharacteristic.writeValue("BAT:100"); BLE.advertise();
}

void loop() {
  BLEDevice central = BLE.central();
  while (central.connected()) {
    if (commandCharacteristic.written()) executePattern(commandCharacteristic.value());
    updatePattern();
  }
  stopPattern("DISCONNECTED");
}
