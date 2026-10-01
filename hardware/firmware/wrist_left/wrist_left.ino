const int MOTOR_PIN = 25;
// Keep this aligned with Config.rotation_timeout_seconds (10 seconds).
const unsigned long MAX_VIBRATION_MS = 10000;

bool vibrating = false;
unsigned long vibrationEndTime = 0;

String commandBuffer = "";

void stopMotor() {
  digitalWrite(MOTOR_PIN, LOW);
  vibrating = false;
  vibrationEndTime = 0;
}

void startVibration(unsigned long durationMs) {
  if (durationMs == 0) {
    durationMs = 500;
  }

  if (durationMs > MAX_VIBRATION_MS) {
    durationMs = MAX_VIBRATION_MS;
  }

  digitalWrite(MOTOR_PIN, HIGH);
  vibrating = true;
  vibrationEndTime = millis() + durationMs;

  Serial.print("LEFT vibration: ");
  Serial.print(durationMs);
  Serial.println(" ms");
}

void processCommand(String command) {
  command.trim();

  if (command.length() == 0) {
    return;
  }

  char type = command.charAt(0);

  if (type == 'X' || type == 'x') {
    stopMotor();
    Serial.println("LEFT vibration stopped");
    return;
  }

  if (type == 'L' || type == 'l') {
    unsigned long durationMs = 500;

    if (command.length() > 1) {
      durationMs = command.substring(1).toInt();
    }

    startVibration(durationMs);
    return;
  }

  if (type == 'R' || type == 'r') {
    Serial.println("RIGHT command ignored by LEFT bracelet");
    return;
  }

  Serial.print("Unknown command: ");
  Serial.println(command);
}

void setup() {
  Serial.begin(115200);

  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);

  delay(1000);

  // Power-on confirmation vibration for 0.2 seconds.
  startVibration(200);

  Serial.println();
  Serial.println("================================");
  Serial.println("WayBand LEFT bracelet ready");
  Serial.println("L500  -> vibration for 500 ms");
  Serial.println("L1000 -> vibration for 1000 ms");
  Serial.println("L2000 -> vibration for 2000 ms");
  Serial.println("L10000 -> vibration for 10000 ms (maximum)");
  Serial.println("Rxxx  -> ignored");
  Serial.println("X     -> stop immediately");
  Serial.println("================================");
}

void loop() {
  // Stop the motor after the requested duration.
  if (vibrating &&
      static_cast<long>(millis() - vibrationEndTime) >= 0) {
    stopMotor();
    Serial.println("LEFT vibration complete");
  }

  // Receive commands one line at a time.
  while (Serial.available() > 0) {
    char received = Serial.read();

    if (received == '\n' || received == '\r') {
      if (commandBuffer.length() > 0) {
        processCommand(commandBuffer);
        commandBuffer = "";
      }
    } else if (commandBuffer.length() < 31) {
      commandBuffer += received;
    }
  }
}
