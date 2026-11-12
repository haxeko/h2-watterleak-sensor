/*
 * Matter side of the sensor (esp-matter release/v1.6, legacy data model = default):
 *   EP0  Root Node (+ ICD Management, OTA Requestor, Thread network commissioning ...)
 *   EP1  Water Leak Detector (0x0043): Identify, Boolean State (StateValue + StateChange event)
 *        + Power Source device type: Power Source cluster, features BAT + REPLC (CR123A, 1 cell)
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

esp_err_t app_matter_init(void);              /* create the node and start Matter + Thread */

void app_matter_set_leak(bool leak);          /* BooleanState.StateValue, emits StateChange */
void app_matter_set_battery(uint32_t mv, uint8_t percent, uint8_t charge_level, bool replace);

bool app_matter_is_commissioned(void);
void app_matter_open_commissioning_window(uint16_t seconds);
void app_matter_notify_user_activity(void);  /* ICD: enter active mode now (button press) */
void app_matter_factory_reset(void);
