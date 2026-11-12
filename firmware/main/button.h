/*
 * One button (SW1 on GPIO9, also the BOOT strap), FR-09:
 *   short press (< 5 s)  -> app_on_short_press(): status / Identify, or open the commissioning window
 *   hold 5 s             -> LED warning
 *   hold >= 10 s, release -> factory reset. Never while pressed: a reboot with GPIO9 low = download mode.
 *   held > 30 s          -> treated as stuck (enclosure plunger jammed): ignored until released, so a
 *                           stuck button cannot keep the chip awake.
 * The button is only polled (20 ms) while it is down; otherwise it is an EXT1 wake-up source.
 */
#pragma once

#include "esp_err.h"

esp_err_t button_init(void);
void button_on_wake(void);   /* APP_EVT_WAKE_GPIO for BUTTON_N */
void button_on_tick(void);   /* APP_EVT_BUTTON_TICK */

/* implemented by the application (app_main.cpp) */
void app_on_short_press(void);
