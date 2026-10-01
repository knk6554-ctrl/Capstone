#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>

// WayBand RIGHT wrist: XIAO ESP32C3 BLE receiver + D2 vibration motor.
// This sketch intentionally does not vibrate on boot, connect, or disconnect.

namespace {
// Seeed Studio XIAO ESP32C3: board pin D2 maps to chip GPIO4.
constexpr int MOTOR_PIN = D2;
constexpr bool MOTOR_ACTIVE_HIGH = true;
constexpr unsigned long MAX_PATTERN_MS = 10000;
constexpr size_t MAX_PULSES = 8;
constexpr size_t COMMAND_QUEUE_DEPTH = 8;
constexpr size_t MAX_COMMAND_LENGTH = 95;

constexpr char DEVICE_NAME[] = "WAYBAND_RIGHT";
constexpr char SERVICE_UUID[] = "7d8f1000-8e7f-4d3b-a3a6-6f44a16c1000";
constexpr char COMMAND_UUID[] = "7d8f1001-8e7f-4d3b-a3a6-6f44a16c1000";
constexpr char STATUS_UUID[] = "7d8f1002-8e7f-4d3b-a3a6-6f44a16c1000";

struct CommandMessage {
  char text[MAX_COMMAND_LENGTH + 1];
};

QueueHandle_t commandQueue = nullptr;
BLECharacteristic *statusCharacteristic = nullptr;
volatile bool bleConnected = false;
volatile bool disconnectStopRequested = false;

unsigned long pulses[MAX_PULSES] = {};
unsigned long gaps[MAX_PULSES - 1] = {};
size_t pulseCount = 0;
size_t pulseIndex = 0;
bool patternRunning = false;
bool motorRunning = false;
unsigned long transitionAt = 0;

void setMotor(bool on) {
  motorRunning = on;
  digitalWrite(MOTOR_PIN, (on == MOTOR_ACTIVE_HIGH) ? HIGH : LOW);
}

void stopPattern() {
  setMotor(false);
  patternRunning = false;
  pulseCount = 0;
  pulseIndex = 0;
  transitionAt = 0;
}

void publishStatus(const String &status) {
  Serial.print("STATUS: ");
  Serial.println(status);
  if (statusCharacteristic == nullptr) {
    return;
  }
  statusCharacteristic->setValue(status.c_str());
  if (bleConnected) {
    statusCharacteristic->notify();
  }
}

bool parsePositiveList(const String &text, unsigned long *output,
                       size_t capacity, size_t &count) {
  count = 0;
  if (text.length() == 0) {
    return true;
  }
  int start = 0;
  while (start <= static_cast<int>(text.length())) {
    if (count >= capacity) {
      return false;
    }
    int comma = text.indexOf(',', start);
    String token = comma < 0 ? text.substring(start) : text.substring(start, comma);
    token.trim();
    if (token.length() == 0) {
      return false;
    }
    unsigned long value = token.toInt();
    if (value == 0 || value > MAX_PATTERN_MS) {
      return false;
    }
    output[count++] = value;
    if (comma < 0) {
      break;
    }
    start = comma + 1;
  }
  return true;
}

bool startPatternCommand(const String &command) {
  // Wire format: P|500,500|300|190
  int first = command.indexOf('|');
  int second = command.indexOf('|', first + 1);
  int third = command.indexOf('|', second + 1);
  if (first != 1 || second < 0 || third < 0) {
    return false;
  }

  unsigned long parsedPulses[MAX_PULSES] = {};
  unsigned long parsedGaps[MAX_PULSES - 1] = {};
  size_t parsedPulseCount = 0;
  size_t parsedGapCount = 0;
  if (!parsePositiveList(command.substring(first + 1, second), parsedPulses,
                         MAX_PULSES, parsedPulseCount) ||
      parsedPulseCount == 0 ||
      !parsePositiveList(command.substring(second + 1, third), parsedGaps,
                         MAX_PULSES - 1, parsedGapCount) ||
      parsedGapCount != parsedPulseCount - 1) {
    return false;
  }

  unsigned long total = 0;
  for (size_t i = 0; i < parsedPulseCount; ++i) {
    total += parsedPulses[i];
    if (i < parsedGapCount) {
      total += parsedGaps[i];
    }
    if (total > MAX_PATTERN_MS) {
      return false;
    }
  }

  stopPattern();
  pulseCount = parsedPulseCount;
  for (size_t i = 0; i < parsedPulseCount; ++i) {
    pulses[i] = parsedPulses[i];
    if (i < parsedGapCount) {
      gaps[i] = parsedGaps[i];
    }
  }
  pulseIndex = 0;
  patternRunning = true;
  setMotor(true);
  transitionAt = millis() + pulses[0];
  return true;
}

void processCommand(String command) {
  command.trim();
  Serial.print("COMMAND: ");
  Serial.println(command);

  if (command == "S" || command == "X") {
    stopPattern();
    publishStatus("STOPPED");
    return;
  }
  if (command.startsWith("P|") && startPatternCommand(command)) {
    publishStatus("ACK:P");
    return;
  }
  // Legacy direct-test command. The normal Raspberry Pi driver uses P|... .
  if (command.startsWith("R")) {
    unsigned long duration = command.substring(1).toInt();
    if (duration > 0 && duration <= MAX_PATTERN_MS) {
      stopPattern();
      pulseCount = 1;
      pulses[0] = duration;
      patternRunning = true;
      setMotor(true);
      transitionAt = millis() + duration;
      publishStatus("ACK:R");
      return;
    }
  }
  stopPattern();
  publishStatus("ERROR:COMMAND");
}

void updatePattern() {
  if (!patternRunning || static_cast<long>(millis() - transitionAt) < 0) {
    return;
  }
  if (motorRunning) {
    setMotor(false);
    if (pulseIndex + 1 >= pulseCount) {
      patternRunning = false;
      publishStatus("DONE");
      return;
    }
    transitionAt = millis() + gaps[pulseIndex];
    ++pulseIndex;
  } else {
    setMotor(true);
    transitionAt = millis() + pulses[pulseIndex];
  }
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *) override {
    bleConnected = true;
    Serial.println("BLE connected");
  }

  void onDisconnect(BLEServer *server) override {
    bleConnected = false;
    disconnectStopRequested = true;
    Serial.println("BLE disconnected");
    server->getAdvertising()->start();
  }
};

class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    auto rawValue = characteristic->getValue();
    String value(rawValue.c_str());
    if (value.length() == 0 || commandQueue == nullptr) {
      return;
    }
    CommandMessage message = {};
    size_t length = value.length();
    if (length > MAX_COMMAND_LENGTH) {
      length = MAX_COMMAND_LENGTH;
    }
    memcpy(message.text, value.c_str(), length);
    message.text[length] = '\0';
    if (xQueueSend(commandQueue, &message, 0) != pdTRUE) {
      publishStatus("ERROR:QUEUE_FULL");
    }
  }
};
}  // namespace

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  setMotor(false);
  Serial.begin(115200);
  commandQueue = xQueueCreate(COMMAND_QUEUE_DEPTH, sizeof(CommandMessage));

  BLEDevice::init(DEVICE_NAME);
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  BLEService *service = server->createService(SERVICE_UUID);

  BLECharacteristic *commandCharacteristic = service->createCharacteristic(
      COMMAND_UUID,
      BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  commandCharacteristic->setCallbacks(new CommandCallbacks());

  statusCharacteristic = service->createCharacteristic(
      STATUS_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  statusCharacteristic->addDescriptor(new BLE2902());
  statusCharacteristic->setValue("READY");

  service->start();
  BLEAdvertising *advertising = server->getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->start();
  Serial.println("WAYBAND_RIGHT ready");
}

void loop() {
  if (disconnectStopRequested) {
    disconnectStopRequested = false;
    stopPattern();
  }

  CommandMessage message = {};
  while (commandQueue != nullptr &&
         xQueueReceive(commandQueue, &message, 0) == pdTRUE) {
    processCommand(String(message.text));
  }
  updatePattern();
  delay(1);
}
