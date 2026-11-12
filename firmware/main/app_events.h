/* Single application event queue: ISRs and esp_timer callbacks post, the app task handles. */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"

typedef enum {
    APP_EVT_WAKE_GPIO = 0,    /* arg = GPIO number; its low-level interrupt fired and is now disabled */
    APP_EVT_PROBE_TICK,       /* water probe state machine timer                                      */
    APP_EVT_BUTTON_TICK,      /* button polling timer (only runs while the button is down)            */
    APP_EVT_BATTERY_MEASURE,  /* periodic or on-demand battery measurement                            */
    APP_EVT_FACTORY_RESET,    /* button released after the factory-reset hold, or last fabric removed */
} app_evt_type_t;

typedef struct {
    app_evt_type_t type;
    uint32_t arg;
} app_evt_t;

esp_err_t app_events_init(void);
bool app_event_post(app_evt_type_t type, uint32_t arg);
bool app_event_post_from_isr(app_evt_type_t type, uint32_t arg, BaseType_t *higher_prio_woken);
bool app_event_wait(app_evt_t *evt);

/* Keep the chip out of light sleep while timing matters (probe pulse, ADC settling). Nestable. */
void app_awake_acquire(void);
void app_awake_release(void);
