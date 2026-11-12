/*
 * Single red LED on GPIO8 (active-low). FR-10: the LED only lights on events, there is no heartbeat.
 *
 * One-shot patterns (status_led_play) interrupt the background mode and then hand back to it.
 * Background modes, highest priority first: identify > leak > commissioning window open.
 * The pin is driven through the LP IO hold, so an "on" phase does not keep the chip awake.
 */
#pragma once

#include <stdbool.h>
#include "esp_err.h"

typedef enum {
    LED_PAT_OK = 0,          /* 1 x 80 ms: dry, battery fine                         */
    LED_PAT_CONNECTED,       /* 3 short blinks: commissioning complete               */
    LED_PAT_LOW_BATTERY,     /* 2 x 40 ms, then 2 x 40 ms after a pause              */
    LED_PAT_LEAK_STATUS,     /* 5 fast blinks: currently wet                          */
    LED_PAT_HOLD_WARNING,    /* 2 x 300 ms at 5 s: keep holding for factory reset     */
    LED_PAT_RESET_ARMED,     /* fast flicker from 10 s: release now to factory reset  */
    LED_PAT_FACTORY_RESET,   /* 1 s on: reset in progress                             */
    LED_PAT_IDENTIFY_EFFECT, /* 1 x 500 ms: Identify TriggerEffect                    */
    LED_PAT_COUNT
} led_pattern_t;

esp_err_t status_led_init(void);
void status_led_play(led_pattern_t pattern);
void status_led_cancel(void);                   /* stop the current one-shot pattern */
void status_led_set_leak(bool on);              /* FR-11: 20 ms every 3 s, at most CONFIG_APP_LED_LEAK_MAX_MIN */
void status_led_set_commissioning(bool on);     /* 50 ms every 2 s while the commissioning window is open */
void status_led_set_identify(bool on);          /* 500 ms on / 500 ms off during Identify */
