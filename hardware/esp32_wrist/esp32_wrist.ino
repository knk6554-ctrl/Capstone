// WayBand 오른쪽 팔찌 테스트
// XIAO ESP32C3
// Motor control : D2 = GPIO4

const int MOTOR_PIN = D2;

void vibrate(int ms) {
  digitalWrite(MOTOR_PIN, HIGH);
  delay(ms);
  digitalWrite(MOTOR_PIN, LOW);
}

void setup() {
  Serial.begin(115200);

  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);

  delay(1000);

  // 전원 ON 확인용
  vibrate(200);

  Serial.println("================================");
  Serial.println("WayBand RIGHT bracelet");
  Serial.println("R 입력 -> 오른쪽 팔찌 진동");
  Serial.println("L 입력 -> 반응 없음");
  Serial.println("================================");
}

void loop() {

  if (Serial.available() > 0) {

    char command = Serial.read();

    if (command == 'R' || command == 'r') {

      Serial.println("RIGHT vibration!");

      vibrate(500);
    }

    else if (command == 'L' || command == 'l') {

      Serial.println("L command received -> RIGHT bracelet does nothing");
    }
  }
}