/*
 * CR123A (Li-MnO2) monitoring, FR-06 / FR-07.
 *
 * Voltage: Q2 switches the 100k/100k divider on only while measuring (VBAT_MEAS_EN), ADC1_CH0 with
 * curve-fitting calibration. Percent remaining = min(charge counter, voltage table):
 *   - the discharge curve is flat, so the voltage alone says little until the knee near the end;
 *   - the charge counter integrates CONFIG_APP_BATTERY_AVG_CURRENT_UA over time (persisted in NVS) and
 *     restarts at 100 % when a fresh cell is detected after power-on.
 * BatChargeLevel: Warning <= CONFIG_APP_BATTERY_WARN_PERCENT, Critical <= CONFIG_APP_BATTERY_CRIT_PERCENT
 * (BatReplacementNeeded = true at Critical).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

esp_err_t battery_init(void);
void battery_measure_and_report(void);   /* APP_EVT_BATTERY_MEASURE */
bool battery_is_low(void);               /* Warning or Critical */
