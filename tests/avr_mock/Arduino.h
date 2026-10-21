#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>

#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define LED_BUILTIN 13

extern uint32_t testMicros;
extern bool remoteLow[20];
extern int pinModes[20], pinLatches[20];
extern uint32_t settleUntil[20];

inline uint32_t micros() { return testMicros; }
inline uint32_t millis() { return testMicros / 1000; }
inline void digitalWrite(uint8_t pin, uint8_t value) { pinLatches[pin] = value; }
inline void pinMode(uint8_t pin, uint8_t mode) {
    if (pinModes[pin] == OUTPUT && mode == INPUT_PULLUP
        && pinLatches[pin] == LOW) {
        // Model a weak-pullup + cable capacitance tail after open-drain ACK.
        settleUntil[pin] = testMicros + 60;
    }
    pinModes[pin] = mode;
}
inline int digitalRead(uint8_t pin) {
    if (remoteLow[pin] || (pinModes[pin] == OUTPUT && pinLatches[pin] == LOW))
        return LOW;
    if (testMicros < settleUntil[pin]) return LOW;
    return HIGH;
}
struct MockSerial {
    void begin(unsigned long) {}
    int available() { return 0; }
    int read() { return -1; }
    int availableForWrite() { return 64; }
    size_t write(const uint8_t *, size_t size) { return size; }
} ;
extern MockSerial Serial;
