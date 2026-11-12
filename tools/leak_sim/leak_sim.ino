/*
 * Water simulator for the h2-watterleak-sensor test bench (phase 6, docs/06-ke-hoach-test.md).
 *
 * Any Arduino-compatible board. The optocoupler isolates the bench from the sensor:
 *
 *   OPTO_PIN --[330R]--> PC817 pin 1 (anode)      PC817 pin 4 (collector) --> J2 pin 1 (EXC_B)
 *            GND ------> PC817 pin 2 (cathode)    PC817 pin 3 (emitter) --[R_SIM]--> J2 pin 2 (SNS_B)
 *
 *   R_SIM = 100 kOhm  typical tap / RO water on the comb
 *           1 MOhm    weak water;  2.2-3.3 MOhm  near the trip threshold (1.3-4 MOhm)
 *   PC817 off-state leakage (< 100 nA at 3.3 V) is far above the trip resistance: reads dry.
 *
 *   MARK_PIN mirrors the "wet" state for the PPK2 logic input D0, so wet edges and the sensor's
 *   current trace share one time base. 5 V boards: feed D0 through a 10k/20k divider (PPK2 logic
 *   level follows its VCC pin, wired to the sensor's 3.3 V).
 *
 * Serial 115200 baud, one command per line, every command answers one line:
 *   W        wet  (opto on)            -> "OK W <millis>"
 *   D        dry  (opto off)           -> "OK D <millis>"
 *   P <ms>   wet pulse of <ms> ms      -> "OK P <ms> <millis at end>"
 *   ?        state                     -> "STATE WET|DRY"
 */
const uint8_t OPTO_PIN = 7;
const uint8_t MARK_PIN = 8;

static bool wet = false;

static void setWet(bool on)
{
    digitalWrite(OPTO_PIN, on ? HIGH : LOW);
    digitalWrite(MARK_PIN, on ? HIGH : LOW);
    wet = on;
}

void setup()
{
    pinMode(OPTO_PIN, OUTPUT);
    pinMode(MARK_PIN, OUTPUT);
    setWet(false);
    Serial.begin(115200);
    Serial.println("READY");
}

void loop()
{
    if (!Serial.available()) {
        return;
    }
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line == "W") {
        setWet(true);
        Serial.print("OK W ");
        Serial.println(millis());
    } else if (line == "D") {
        setWet(false);
        Serial.print("OK D ");
        Serial.println(millis());
    } else if (line.startsWith("P ")) {
        unsigned long ms = line.substring(2).toInt();
        setWet(true);
        delay(ms);
        setWet(false);
        Serial.print("OK P ");
        Serial.print(ms);
        Serial.print(' ');
        Serial.println(millis());
    } else if (line == "?") {
        Serial.println(wet ? "STATE WET" : "STATE DRY");
    } else if (line.length()) {
        Serial.println("ERR");
    }
}
