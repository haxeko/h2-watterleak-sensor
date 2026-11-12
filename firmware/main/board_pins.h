/*
 * h2-watterleak-sensor rev A - ESP32-H2-WROOM-02C-H4S pin map
 * Source of truth: docs/02-so-do-khoi-va-gan-chan.md (sections 3, 5, 7) and the KiCad schematic.
 */
#pragma once

#include "driver/gpio.h"
#include "hal/adc_types.h"
#include "esp_bit_defs.h"

#define PIN_VBAT_MEAS_EN   GPIO_NUM_0   /* out, active-high, ext. 1 MOhm pull-down on the Q2 gate       */
#define PIN_VBAT_SENSE     GPIO_NUM_1   /* ADC1_CH0, divider 100k/100k (x2), 100 nF                      */
#define PIN_LED_N          GPIO_NUM_8   /* LP IO, out, active-low, ext. 47 kOhm pull-up (strap pin)       */
#define PIN_BUTTON_N       GPIO_NUM_9   /* LP IO, in, active-low, ext. 10 kOhm pull-up (BOOT strap)       */
#define PIN_LEAK_A_N       GPIO_NUM_10  /* LP IO, in, active-low, ext. 470 kOhm pull-up - bottom combs A1/A2 */
#define PIN_PROBE_EXC      GPIO_NUM_11  /* LP IO, out, 1 = both probes biased ("armed"), held in sleep    */
#define PIN_LEAK_B_N       GPIO_NUM_12  /* LP IO, in, active-low, ext. 470 kOhm pull-up - remote probe J2 */
/* GPIO13/14: 32.768 kHz crystal Y1 (CONFIG_RTC_CLK_SRC_EXT_CRYS=y)                                         */
/* GPIO23/24: UART0 console on J1, GPIO26/27: USB D-/D+ on J1                                                 */

/* Not connected or test pads only: parked as inputs with pull-down (HW guideline: no floating inputs). */
#define UNUSED_PIN_MASK    (BIT64(GPIO_NUM_2) | BIT64(GPIO_NUM_3) | BIT64(GPIO_NUM_4) | BIT64(GPIO_NUM_5) | \
                            BIT64(GPIO_NUM_22) | BIT64(GPIO_NUM_25))

#define VBAT_ADC_UNIT      ADC_UNIT_1
#define VBAT_ADC_CHANNEL   ADC_CHANNEL_0
#define VBAT_ADC_ATTEN     ADC_ATTEN_DB_6      /* ATTEN2 on ESP32-H2: 0 .. about 1.9 V                  */
#define VBAT_DIVIDER_NUM   2
#define VBAT_SETTLE_MS     30                  /* about 6 tau, tau = (100k || 100k) * 100 nF = 5 ms     */

/* Wake-up inputs: all active-low LP IOs -> EXT1 "any low" (works with the TOP domain powered down). */
#define WAKE_MASK_BUTTON   BIT64(PIN_BUTTON_N)
#define WAKE_MASK_LEAK     (BIT64(PIN_LEAK_A_N) | BIT64(PIN_LEAK_B_N))
#define WAKE_EXT1_MASK     (WAKE_MASK_BUTTON | WAKE_MASK_LEAK)
