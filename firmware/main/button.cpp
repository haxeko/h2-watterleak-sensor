#include "button.h"

#include <inttypes.h>

#include "app_events.h"
#include "board_pins.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "status_led.h"
#include "wake_inputs.h"

static const char *TAG = "button";

#define TICK_MS        20
#define STUCK_POLL_MS  1000
#define MIN_PRESS_MS   30
#define RELEASE_TICKS  2      /* consecutive "released" samples = debounce */

static esp_timer_handle_t s_timer;
static bool s_active;
static bool s_warned, s_reset_armed, s_stuck;
static int s_release_ticks;
static int64_t s_press_us;

static void tick_cb(void *)
{
    app_event_post(APP_EVT_BUTTON_TICK, 0);
}

esp_err_t button_init(void)
{
    esp_timer_create_args_t args = {};
    args.callback = tick_cb;
    args.dispatch_method = ESP_TIMER_TASK;
    args.name = "button";
    args.skip_unhandled_events = true;
    ESP_RETURN_ON_ERROR(esp_timer_create(&args, &s_timer), TAG, "timer");
    wake_inputs_arm(PIN_BUTTON_N);
    return ESP_OK;
}

void button_on_wake(void)
{
    if (s_active) {
        return;
    }
    wake_inputs_disarm(PIN_BUTTON_N);      /* stays low while pressed: poll instead */
    s_active = true;
    s_warned = s_reset_armed = s_stuck = false;
    s_release_ticks = 0;
    s_press_us = esp_timer_get_time();
    esp_timer_start_periodic(s_timer, TICK_MS * 1000);
}

void button_on_tick(void)
{
    if (!s_active) {
        return;
    }
    const int64_t held_ms = (esp_timer_get_time() - s_press_us) / 1000;

    if (gpio_get_level(PIN_BUTTON_N) == 0) {            /* still pressed */
        s_release_ticks = 0;
        if (s_stuck) {
            return;
        }
        if (held_ms >= CONFIG_APP_BUTTON_STUCK_MS) {
            ESP_LOGW(TAG, "held for %d s: treated as stuck until released", CONFIG_APP_BUTTON_STUCK_MS / 1000);
            s_stuck = true;
            s_reset_armed = false;
            status_led_cancel();
            esp_timer_stop(s_timer);
            esp_timer_start_periodic(s_timer, STUCK_POLL_MS * 1000);
        } else if (!s_reset_armed && held_ms >= CONFIG_APP_BUTTON_RESET_MS) {
            s_reset_armed = true;
            ESP_LOGW(TAG, "release now to factory reset");
            status_led_play(LED_PAT_RESET_ARMED);
        } else if (!s_warned && held_ms >= CONFIG_APP_BUTTON_WARN_MS) {
            s_warned = true;
            status_led_play(LED_PAT_HOLD_WARNING);
        }
        return;
    }

    if (++s_release_ticks < RELEASE_TICKS) {
        return;
    }
    esp_timer_stop(s_timer);
    s_active = false;
    wake_inputs_arm(PIN_BUTTON_N);

    if (s_stuck) {
        ESP_LOGI(TAG, "stuck button released");
    } else if (s_reset_armed) {
        app_event_post(APP_EVT_FACTORY_RESET, 0);
    } else if (!s_warned && held_ms >= MIN_PRESS_MS) {
        ESP_LOGI(TAG, "short press (%" PRId64 " ms)", held_ms);
        app_on_short_press();
    }
}
