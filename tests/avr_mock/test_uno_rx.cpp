// Compile on Linux: g++ -std=c++17 -I tests/avr_mock
//   tests/avr_mock/test_uno_rx.cpp -o build/test_uno_rx
//
// Model the TI-83 Plus ROM _SendAByte bit-by-bit. The pullup on the Uno
// acknowledge wire rises over 60 us after line release. Without the
// RX_ACK_SETTLE state the Uno can accidentally read its own ACK as the next
// TI bit, despite successful PC/Uno USB handshake.
#include "Arduino.h"
#include <initializer_list>
#include <cstdio>
#include <cstdlib>
#include <cassert>
uint32_t testMicros = 0;
bool remoteLow[20] = {};
int pinModes[20] = {};
int pinLatches[20] = {};
uint32_t settleUntil[20] = {};
MockSerial Serial;

#include "../../arduino/CHAT83_Uno_v05/CHAT83_Uno_v05.ino"

// Lock in the real user's 2.5mm connector wiring. Tests that use TIP/RING
// symbolic constants otherwise pass even if both constants are wrong.
static_assert(TIP == 3, "CHAT83 physical TIP is D3, not upstream D2");
static_assert(RING == 6, "CHAT83 physical RING is D6, not upstream D3");

static void require(bool okay, const char *problem) {
    if (!okay) {
        std::fprintf(stderr,
                     "FAIL %s at %lu us: starts=%u ack=%u bytes=%u err=%u state=%u\n",
                     problem, (unsigned long)testMicros, rxStarts,
                     rxAckedBits, rxDoneBytes, rxTimeouts, (unsigned)state);
        std::exit(1);
    }
}
static void resetAll() {
    testMicros = 0;
    std::memset(remoteLow, 0, sizeof(remoteLow));
    std::memset(pinModes, 0, sizeof(pinModes));
    std::memset(pinLatches, 0, sizeof(pinLatches));
    std::memset(settleUntil, 0, sizeof(settleUntil));
    calcHead = calcTail = calcUsed = 0;
    rxStarts = rxAckedBits = rxDoneBytes = rxTimeouts = txTimeouts = 0;
    rxLastByte = 0;
    state = IDLE;
    rxByte = bitIndex = 0;
    sendPending = false;
    setup();
}

static void transmitTIByte(uint8_t data) {
    unsigned bit = 0;
    enum Phase { WAIT_IDLE, WAIT_ACK, WAIT_BOTH_HIGH, COMPLETE };
    Phase phase = WAIT_IDLE;
    unsigned loopCount = 0;
    while (phase != COMPLETE && loopCount++ < 100000) {
        // Device sender follows same four-phase protocol as original sketch.
        int source = (data & (1u << bit)) ? RING : TIP;
        int acknowledgement = (source == TIP) ? RING : TIP;
        if (phase == WAIT_IDLE) {
            if (digitalRead(TIP) == HIGH && digitalRead(RING) == HIGH) {
                remoteLow[source] = true;
                phase = WAIT_ACK;
            }
        } else if (phase == WAIT_ACK) {
            if (digitalRead(acknowledgement) == LOW) {
                remoteLow[source] = false;
                phase = WAIT_BOTH_HIGH;
            }
        } else if (phase == WAIT_BOTH_HIGH) {
            if (digitalRead(TIP) == HIGH && digitalRead(RING) == HIGH) {
                ++bit;
                phase = (bit == 8) ? COMPLETE : WAIT_IDLE;
            }
        }
        loop();                // Actual firmware cooperative FSM.
        testMicros += 10;     // Model loop polling with a 10-us cadence.
    }
    require(phase == COMPLETE, "TI ROM got stuck waiting for ACK");
    // Give Uno its 100us inter-bit guard, allowing byte publication.
    for (int i=0; i<35; ++i) { loop(); testMicros += 10; }
}
int main() {
    for (uint8_t sample: {uint8_t(0x53), uint8_t(0x00),
                          uint8_t(0x7F), uint8_t(0xFF)}) {
        resetAll();
        transmitTIByte(sample);
        require(rxLastByte == sample, "received byte differs from TI source");
        require(rxDoneBytes == 1, "exactly one byte should be received");
        require(rxStarts == 8 && rxAckedBits == 8, "phantom ACK/start edge");
        require(rxTimeouts == 0, "RX timed out during simple TI byte");
        std::printf("PASS TI -> Uno byte %02X, exactly 8 starts/ACKs\n",sample);
    }
    return 0;
}
