/*
 * CHAT83 Uno transport v0.5
 * Target: Arduino Uno / ATmega328P 16 MHz, TIP=D2, RING=D3, GND=GND.
 *
 * PC USB UART: 115200 baud, COBS-terminated packets (0x00 delimiter).
 * Decoded packet format: [type, fields..., CRC8(poly 0x07)].
 *   P                      -> H,major,minor,capabilities
 *   G,gap_ms (2..50)       -> A,0,0
 *   T,seq,n,byte[0..15]    -> A,seq,status (after all link bytes handshake)
 *   R,byte                 <-  calculator TX byte
 *   E,error_code           <-  link or parser error
 *
 * A status 0 = fully sent; 1 = link timeout; 2 = busy; 3 = malformed.
 * Credit/window: max 16 bytes per T batch; PC MUST wait for its A before
 * sending the next T batch. No silent Arduino UART buffer overrun.
 *
 * Open-drain: drive LOW via digitalWrite(pin,LOW)/pinMode(OUTPUT); release
 * via pinMode(INPUT_PULLUP). Never actively drive either link wire high.
 *
 * The cooperative line FSM never waits in a while loop for a peer. UART
 * receives, TI link RX and TI link TX are interleaved in loop().
 * No SoftwareSerial, dynamic allocation, or blocking delays in loop().
 *
 * IMPORTANT: Only flash this experimental sketch with the hardware powered
 * down, and close TiLP before opening USB serial. This is NOT TiLP firmware.
 */
#include <Arduino.h>

static const uint8_t TIP = 2;
static const uint8_t RING = 3;
static const uint8_t MAX_TX = 16;
static const uint8_t MAX_WIRE = 36;
static const uint32_t BIT_TIMEOUT_US = 50000UL;
static const uint32_t RX_TIMEOUT_US = 30000UL;

static uint8_t wireIn[MAX_WIRE];
static uint8_t wireUsed = 0;
static bool wireOverflow = false;
static uint8_t txQueue[MAX_TX];
static uint8_t txSize = 0;
static uint8_t txIndex = 0;
static uint8_t txSeq = 0;
static uint8_t bitIndex = 0;
static uint8_t rxByte = 0;
static uint8_t lineDriven = TIP;
static uint8_t peerLine = RING;
static uint32_t deadlineFrom = 0;
static uint32_t lastByteAt = 0;
static uint8_t gapMs = 35; // initially conservative; PC can set via G
static bool sendPending = false;
enum LinkState : uint8_t { IDLE, RX_WAIT_RELEASE, TX_WAIT_ACK, TX_WAIT_RELEASE };
static LinkState state = IDLE;

static uint8_t crc8(const uint8_t *data, uint8_t n) {
  uint8_t crc = 0;
  while (n--) {
    crc ^= *data++;
    for (uint8_t k = 0; k < 8; ++k) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

static void releaseLine(uint8_t pin) {
  pinMode(pin, INPUT_PULLUP);
}
static void pullLow(uint8_t pin) {
  digitalWrite(pin, LOW);
  pinMode(pin, OUTPUT);
}
static bool idleLines() {
  return digitalRead(TIP) == HIGH && digitalRead(RING) == HIGH;
}
static bool elapsed(uint32_t since, uint32_t limit) {
  return (uint32_t)(micros() - since) >= limit;
}

static void sendPacket(const uint8_t *message, uint8_t size) {
  // One COBS block encoded on the stack, no zero bytes except delimiter.
  uint8_t raw[MAX_WIRE];
  uint8_t encoded[MAX_WIRE + 2];
  if (!size || size >= MAX_WIRE - 1) return;
  memcpy(raw, message, size);
  raw[size] = crc8(raw, size);
  uint8_t total = size + 1;
  uint8_t write = 1, codeIndex = 0, code = 1;
  for (uint8_t i = 0; i < total; ++i) {
    if (raw[i] == 0) {
      encoded[codeIndex] = code;
      codeIndex = write++;
      code = 1;
    } else {
      encoded[write++] = raw[i];
      ++code;
      if (code == 0xFF) {
        encoded[codeIndex] = code;
        codeIndex = write++;
        code = 1;
      }
    }
  }
  encoded[codeIndex] = code;
  encoded[write++] = 0;
  Serial.write(encoded, write);
}
static void ack(uint8_t seq, uint8_t status) {
  const uint8_t msg[] = {'A', seq, status};
  sendPacket(msg, 3);
}
static void errorEvent(uint8_t code) {
  const uint8_t msg[] = {'E', code};
  sendPacket(msg, 2);
}
static void deliverCalcByte(uint8_t byte) {
  const uint8_t msg[] = {'R', byte};
  sendPacket(msg, 2);
}

// Decode COBS input (without delimiter) in place.
static bool decodeCobs(uint8_t *buf, uint8_t &length) {
  uint8_t read = 0, write = 0;
  const uint8_t original = length;
  while (read < original) {
    const uint8_t code = buf[read++];
    if (code == 0 || (unsigned)read + code - 1 > original) return false;
    for (uint8_t j = 1; j < code; ++j) buf[write++] = buf[read++];
    if (code != 0xFF && read < original) buf[write++] = 0;
  }
  length = write;
  return true;
}

static void handleHost(uint8_t *raw, uint8_t count) {
  if (count < 2 || crc8(raw, count) != 0) {
    errorEvent(1);
    return;
  }
  const uint8_t type = raw[0];
  if (type == 'P' && count == 2) {
    const uint8_t msg[] = {'H', 0, 5, MAX_TX};
    sendPacket(msg, 4);
  } else if (type == 'G' && count == 3 && raw[1] >= 2 && raw[1] <= 50) {
    gapMs = raw[1];
    ack(0, 0);
  } else if (type == 'T' && count >= 5 && count == (uint8_t)(4 + raw[2]) &&
             raw[2] > 0 && raw[2] <= MAX_TX) {
    if (sendPending || state == TX_WAIT_ACK || state == TX_WAIT_RELEASE) {
      ack(raw[1], 2);
      return;
    }
    txSeq = raw[1];
    txSize = raw[2];
    txIndex = 0;
    memcpy(txQueue, raw + 3, txSize);
    sendPending = true;
  } else {
    errorEvent(2);
  }
}

static void pollHost() {
  // Per-loop bounded UART work avoids starving bit-level handshake.
  uint8_t budget = 8;
  while (budget-- && Serial.available()) {
    uint8_t b = (uint8_t)Serial.read();
    if (b == 0) {
      if (wireUsed && !wireOverflow) {
        uint8_t len = wireUsed;
        if (decodeCobs(wireIn, len)) handleHost(wireIn, len);
        else errorEvent(3);
      } else if (wireOverflow) {
        errorEvent(4);
      }
      wireUsed = 0;
      wireOverflow = false;
    } else if (wireUsed < MAX_WIRE) {
      wireIn[wireUsed++] = b;
    } else {
      wireOverflow = true;
    }
  }
}

static void finishSend(uint8_t status) {
  releaseLine(TIP);
  releaseLine(RING);
  state = IDLE;
  sendPending = false;
  txSize = 0;
  lastByteAt = micros();
  ack(txSeq, status);
}

static void startTxBit() {
  const bool one = (txQueue[txIndex] & (1u << bitIndex)) != 0;
  lineDriven = one ? RING : TIP;
  peerLine = one ? TIP : RING;
  pullLow(lineDriven);
  deadlineFrom = micros();
  state = TX_WAIT_ACK;
}

static void pollLink() {
  if (state == RX_WAIT_RELEASE) {
    if (digitalRead(peerLine) == HIGH) {
      releaseLine(lineDriven);
      state = IDLE;
      ++bitIndex;
      if (bitIndex == 8) {
        bitIndex = 0;
        deliverCalcByte(rxByte);
        rxByte = 0;
      }
    } else if (elapsed(deadlineFrom, RX_TIMEOUT_US)) {
      releaseLine(lineDriven);
      state = IDLE;
      bitIndex = 0;
      rxByte = 0;
      errorEvent(5);
    }
    return;
  }
  if (state == TX_WAIT_ACK) {
    if (digitalRead(peerLine) == LOW) {
      releaseLine(lineDriven);
      deadlineFrom = micros();
      state = TX_WAIT_RELEASE;
    } else if (elapsed(deadlineFrom, BIT_TIMEOUT_US)) {
      finishSend(1);
    }
    return;
  }
  if (state == TX_WAIT_RELEASE) {
    if (digitalRead(peerLine) == HIGH) {
      ++bitIndex;
      if (bitIndex == 8) {
        bitIndex = 0;
        ++txIndex;
        lastByteAt = micros();
        state = IDLE;
        if (txIndex >= txSize) {
          finishSend(0);
        }
      } else {
        startTxBit();
      }
    } else if (elapsed(deadlineFrom, BIT_TIMEOUT_US)) {
      finishSend(1);
    }
    return;
  }

  // IDLE: detect calculator transmission before starting our own.
  if (!idleLines()) {
    bool bit = (digitalRead(RING) == LOW);
    rxByte = (uint8_t)((rxByte >> 1) | (bit ? 0x80 : 0));
    peerLine = bit ? RING : TIP;
    lineDriven = bit ? TIP : RING;
    pullLow(lineDriven);
    deadlineFrom = micros();
    state = RX_WAIT_RELEASE;
    return;
  }
  if (sendPending &&
      ((uint32_t)(micros() - lastByteAt) >= (uint32_t)gapMs * 1000UL)) {
    // Never send a new byte until the previous bit exchange is completed.
    startTxBit();
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  releaseLine(TIP);
  releaseLine(RING);
  Serial.begin(115200);
  lastByteAt = micros();
}
void loop() {
  pollLink();  // Highest priority: open-drain bit handshake.
  pollHost();  // Read at most eight UART bytes per loop.
}
