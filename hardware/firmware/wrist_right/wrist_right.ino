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

  Serial.print("RIGHT vibration: ");
  Serial.print(durationMs);
  Serial.println(" ms");
}

void processCommand(String command) {
  command.trim();
  if (command.length() == 0) {
    return;
  }

  char type = command.charAt(0);
  if (type == 'X' || type == 'x' || type == 'S' || type == 's') {
    stopMotor();
    Serial.println("RIGHT vibration stopped");
    return;
  }

  if (type == 'R' || type == 'r') {
    unsigned long durationMs = 500;
    if (command.length() > 1) {
      durationMs = command.substring(1).toInt();
    }
    startVibration(durationMs);
    return;
  }

  if (type == 'L' || type == 'l') {
    Serial.println("LEFT command ignored by RIGHT bracelet");
    return;
  }

  if (type == 'I' || type == 'i') {
    Serial.println("WAYBAND_RIGHT");
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

  // No boot vibration: the motor runs only after an R command.
  Serial.println();
  Serial.println("================================");
  Serial.println("WayBand RIGHT bracelet ready");
  Serial.println("R500   -> vibration for 500 ms");
  Serial.println("R1000  -> vibration for 1000 ms");
  Serial.println("R10000 -> vibration for 10000 ms (maximum)");
  Serial.println("Lxxx   -> ignored");
  Serial.println("X       -> stop immediately");
  Serial.println("I       -> identify as WAYBAND_RIGHT");
  Serial.println("================================");
}

void loop() {
  if (vibrating && static_cast<long>(millis() - vibrationEndTime) >= 0) {
    stopMotor();
    Serial.println("RIGHT vibration complete");
  }

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
