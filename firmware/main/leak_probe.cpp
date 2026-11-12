#include "leak_probe.h"

#include "app_events.h"
#include "app_matter.h"
#include "board_pins.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "status_led.h"
#include "wake_inputs.h"

static const char *TAG = "probe";

typedef enum { PROBE_ARMED_DRY, PROBE_CONFIRMING, PROBE_WET } probe_state_t;

#define CH_A 0x1u   /* bottom combs A1/A2 */
#define CH_B 0x2u   /* remote probe on J2 */

static probe_state_t s_state = PROBE_ARMED_DRY;
static int s_wet_samples;
static uint32_t s_channels;        /* channels seen wet during this event */
static int64_t s_dry_since_us;     /* 0 = not dry */
static esp_timer_handle_t s_timer;

static void timer_cb(void *)
{
    app_event_post(APP_EVT_PROBE_TICK, 0);
}

static void timer_start_ms(uint32_t ms)
{
    esp_timer_stop(s_timer);
    esp_timer_start_once(s_timer, (uint64_t)ms * 1000);
}

static void exc_set(int level)
{
    gpio_hold_dis(PIN_PROBE_EXC);
    gpio_set_level(PIN_PROBE_EXC, level);
    gpio_hold_en(PIN_PROBE_EXC);       /* LP IO hold keeps the level through light sleep */
}

static uint32_t read_channels(void)
{
    uint32_t wet = 0;
    if (gpio_get_level(PIN_LEAK_A_N) == 0) {
        wet |= CH_A;
    }
    if (gpio_get_level(PIN_LEAK_B_N) == 0) {
        wet |= CH_B;
    }
    return wet;
}

/* Bias the probes for pulse_ms, read both channels, remove the bias. The gate RC (10 kOhm + water into
 * 10 nF || 1 MOhm) needs a few ms; tap or RO water settles well within 5 ms (docs/01 section 5). */
static uint32_t pulse_sample(uint32_t pulse_ms)
{
    app_awake_acquire();
    exc_set(1);
    vTaskDelay(pdMS_TO_TICKS(pulse_ms));
    const uint32_t wet = read_channels();
    exc_set(0);
    app_awake_release();
    return wet;
}

static const char *channel_names(uint32_t ch)
{
    switch (ch & (CH_A | CH_B)) {
    case CH_A:        return "A (bottom combs)";
    case CH_B:        return "B (remote probe)";
    case CH_A | CH_B: return "A + B";
    default:          return "-";
    }
}

static void enter_armed_dry(void)
{
    s_state = PROBE_ARMED_DRY;
    esp_timer_stop(s_timer);
    exc_set(1);                        /* bias both probes; dry = open circuit, zero current */
    wake_inputs_arm(PIN_LEAK_A_N);     /* a probe that is already wet fires right away */
    wake_inputs_arm(PIN_LEAK_B_N);
    ESP_LOGI(TAG, "armed (dry)");
}

static void enter_wet(void)
{
    s_state = PROBE_WET;
    s_dry_since_us = 0;
    exc_set(0);                        /* no DC through the water while wet (FR-04) */
    ESP_LOGW(TAG, "LEAK confirmed, channel %s", channel_names(s_channels));
    app_matter_set_leak(true);
    status_led_set_leak(true);
    timer_start_ms(CONFIG_APP_PROBE_WET_PULSE_PERIOD_S * 1000);
}

static void confirm_step(void)
{
    const uint32_t wet = read_channels();   /* PROBE_EXC is still 1 (static bias) */
    if (!wet) {
        ESP_LOGI(TAG, "transient after %d wet sample(s), ignored", s_wet_samples);
        enter_armed_dry();
        return;
    }
    s_channels |= wet;
    if (++s_wet_samples >= CONFIG_APP_PROBE_CONFIRM_SAMPLES) {
        enter_wet();
        return;
    }
    timer_start_ms(CONFIG_APP_PROBE_CONFIRM_INTERVAL_MS);
}

static void wet_step(void)
{
    const uint32_t wet = pulse_sample(CONFIG_APP_PROBE_WET_PULSE_MS);
    const int64_t now = esp_timer_get_time();
    if (wet) {
        s_channels |= wet;
        s_dry_since_us = 0;
    } else {
        if (s_dry_since_us == 0) {
            s_dry_since_us = now;
        }
        if (now - s_dry_since_us >= (int64_t)CONFIG_APP_PROBE_DRY_HOLD_S * 1000000) {
            /* the long pulse lets the gate settle fully, so high-resistance water is still seen */
            if (pulse_sample(CONFIG_APP_PROBE_DRY_VERIFY_PULSE_MS) == 0) {
                ESP_LOGI(TAG, "dry for %d s, leak cleared (was channel %s)", CONFIG_APP_PROBE_DRY_HOLD_S,
                         channel_names(s_channels));
                s_channels = 0;
                app_matter_set_leak(false);
                status_led_set_leak(false);
                enter_armed_dry();
                return;
            }
            s_dry_since_us = 0;
        }
    }
    timer_start_ms(CONFIG_APP_PROBE_WET_PULSE_PERIOD_S * 1000);
}

void leak_probe_on_wake(gpio_num_t pin)
{
    if (s_state != PROBE_ARMED_DRY) {
        return;                        /* stale event */
    }
    /* the line stays low while wet: stop it from waking us, sample with the timer instead */
    wake_inputs_disarm(PIN_LEAK_A_N);
    wake_inputs_disarm(PIN_LEAK_B_N);
    ESP_LOGI(TAG, "wet edge on GPIO%d, confirming", (int)pin);
    s_state = PROBE_CONFIRMING;
    s_wet_samples = 0;
    s_channels = 0;
    confirm_step();
}

void leak_probe_on_tick(void)
{
    switch (s_state) {
    case PROBE_CONFIRMING:
        confirm_step();
        break;
    case PROBE_WET:
        wet_step();
        break;
    default:
        break;
    }
}

bool leak_probe_is_wet(void)
{
    return s_state == PROBE_WET;
}

esp_err_t leak_probe_init(void)
{
    gpio_config_t io = {};
    io.pin_bit_mask = BIT64(PIN_PROBE_EXC);
    io.mode = GPIO_MODE_OUTPUT;
    ESP_RETURN_ON_ERROR(gpio_config(&io), TAG, "gpio");

    esp_timer_create_args_t args = {};
    args.callback = timer_cb;
    args.dispatch_method = ESP_TIMER_TASK;
    args.name = "probe";
    args.skip_unhandled_events = true;
    ESP_RETURN_ON_ERROR(esp_timer_create(&args, &s_timer), TAG, "timer");

    enter_armed_dry();   /* water already present at boot -> immediate interrupt -> confirm -> report */
    return ESP_OK;
}
