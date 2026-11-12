/*
 * Water probe state machine (docs/02 section 5.1, requirements FR-01..FR-04).
 *
 *   ARMED_DRY   PROBE_EXC = 1 (held), both LEAK_x_N armed as EXT1 wake-ups. Dry = open circuit, so no
 *               probe current; the chip sleeps.
 *   CONFIRMING  First wet edge woke us. Sample every CONFIG_APP_PROBE_CONFIRM_INTERVAL_MS. One dry sample
 *               means a transient (< 200 ms with the defaults): back to ARMED_DRY, nothing is reported.
 *   WET         CONFIG_APP_PROBE_CONFIRM_SAMPLES wet samples in a row: StateValue = TRUE (+ StateChange
 *               event). PROBE_EXC = 0 removes the DC bias. Every CONFIG_APP_PROBE_WET_PULSE_PERIOD_S the
 *               probes get a CONFIG_APP_PROBE_WET_PULSE_MS pulse. After CONFIG_APP_PROBE_DRY_HOLD_S of dry
 *               pulses, one longer verification pulse; if still dry: StateValue = FALSE and back to ARMED_DRY.
 */
#pragma once

#include <stdbool.h>
#include "driver/gpio.h"
#include "esp_err.h"

esp_err_t leak_probe_init(void);
void leak_probe_on_wake(gpio_num_t pin);   /* APP_EVT_WAKE_GPIO for LEAK_A_N / LEAK_B_N */
void leak_probe_on_tick(void);             /* APP_EVT_PROBE_TICK */
bool leak_probe_is_wet(void);
