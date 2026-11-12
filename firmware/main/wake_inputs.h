/*
 * Wake-up inputs: BUTTON_N (GPIO9), LEAK_A_N (GPIO10), LEAK_B_N (GPIO12), all active-low LP IOs with
 * external pull-ups.
 *
 * An "armed" input wakes the chip from auto light sleep and raises one APP_EVT_WAKE_GPIO event:
 *  - EXT1 (any low) wakes the chip when the TOP power domain is down
 *    (CONFIG_PM_POWER_DOWN_PERIPHERAL_IN_LIGHT_SLEEP);
 *  - GPIO wake-up covers light sleep with the TOP domain still on;
 *  - a low-level GPIO interrupt, which fires once the chip runs again, tells the app which pin it was.
 *    The ISR disables that pin's interrupt.
 *
 * An input that stays low (button held, probe wet) must be disarmed while it is low; otherwise EXT1
 * would wake the chip again right after each sleep.
 */
#pragma once

#include "driver/gpio.h"
#include "esp_err.h"

esp_err_t wake_inputs_init(void);
void wake_inputs_arm(gpio_num_t pin);
void wake_inputs_disarm(gpio_num_t pin);
