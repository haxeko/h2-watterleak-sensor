#include "status_led.h"

#include "board_pins.h"
#include "esp_check.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "led";

typedef struct {
    uint16_t on_ms;
    uint16_t off_ms;
} led_step_t;

typedef struct {
    const led_step_t *steps;
    uint8_t count;
} led_seq_t;

static const led_step_t k_ok[] = {{80, 200}};
static const led_step_t k_connected[] = {{80, 120}, {80, 120}, {80, 400}};
static const led_step_t k_low_battery[] = {{40, 160}, {40, 600}, {40, 160}, {40, 400}};
static const led_step_t k_leak_status[] = {{40, 120}, {40, 120}, {40, 120}, {40, 120}, {40, 400}};
static const led_step_t k_hold_warning[] = {{300, 300}, {300, 300}};
static const led_step_t k_reset_armed[] = {{50, 50}, {50, 50}, {50, 50}, {50, 50}, {50, 50},
                                           {50, 50}, {50, 50}, {50, 50}, {50, 50}, {50, 50}};
static const led_step_t k_factory_reset[] = {{1000, 100}};
static const led_step_t k_identify_effect[] = {{500, 200}};
static const led_step_t k_link_1[] = {{150, 250}};
static const led_step_t k_link_2[] = {{150, 250}, {150, 250}};
static const led_step_t k_link_3[] = {{150, 250}, {150, 250}, {150, 250}};
static const led_step_t k_no_link[] = {{800, 200}};

#define SEQ(a) {a, (uint8_t)(sizeof(a) / sizeof(a[0]))}
static const led_seq_t k_patterns[LED_PAT_COUNT] = {
    SEQ(k_ok), SEQ(k_connected), SEQ(k_low_battery), SEQ(k_leak_status),
    SEQ(k_hold_warning), SEQ(k_reset_armed), SEQ(k_factory_reset), SEQ(k_identify_effect),
    SEQ(k_link_1), SEQ(k_link_2), SEQ(k_link_3), SEQ(k_no_link),
};

/* background modes: on / off times */
static const led_step_t k_bg_identify = {500, 500};
static const led_step_t k_bg_leak = {20, 2980};
static const led_step_t k_bg_commissioning = {50, 1950};

static SemaphoreHandle_t s_lock;
static esp_timer_handle_t s_timer;
static const led_seq_t *s_fg;        /* current one-shot pattern, NULL if none */
static uint8_t s_fg_idx;
static bool s_fg_on;
static bool s_bg_on;
static bool s_identify, s_leak, s_commissioning;
static int64_t s_leak_until_us;

static void led_write(bool on)
{
    gpio_hold_dis(PIN_LED_N);
    gpio_set_level(PIN_LED_N, on ? 0 : 1);
    gpio_hold_en(PIN_LED_N);
}

static void schedule_ms(uint32_t ms)
{
    esp_timer_stop(s_timer);
    esp_timer_start_once(s_timer, (uint64_t)(ms ? ms : 1) * 1000);
}

static const led_step_t *background(void)
{
    if (s_identify) {
        return &k_bg_identify;
    }
    if (s_leak && esp_timer_get_time() < s_leak_until_us) {
        return &k_bg_leak;
    }
    if (s_commissioning) {
        return &k_bg_commissioning;
    }
    return NULL;
}

/* Advance the LED state machine by one phase. Called with s_lock held. */
static void step_locked(void)
{
    if (s_fg) {
        if (s_fg_on) {
            led_write(false);
            s_fg_on = false;
            schedule_ms(s_fg->steps[s_fg_idx].off_ms);
            s_fg_idx++;
            return;
        }
        if (s_fg_idx < s_fg->count) {
            led_write(true);
            s_fg_on = true;
            schedule_ms(s_fg->steps[s_fg_idx].on_ms);
            return;
        }
        s_fg = NULL;
        s_bg_on = false;
    }
    const led_step_t *bg = background();
    if (!bg) {
        led_write(false);
        s_bg_on = false;
        esp_timer_stop(s_timer);
        return;
    }
    s_bg_on = !s_bg_on;
    led_write(s_bg_on);
    schedule_ms(s_bg_on ? bg->on_ms : bg->off_ms);
}

static void timer_cb(void *)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    step_locked();
    xSemaphoreGive(s_lock);
}

esp_err_t status_led_init(void)
{
    gpio_config_t io = {};
    io.pin_bit_mask = BIT64(PIN_LED_N);
    io.mode = GPIO_MODE_OUTPUT;
    ESP_RETURN_ON_ERROR(gpio_config(&io), TAG, "gpio");
    led_write(false);

    s_lock = xSemaphoreCreateMutex();
    ESP_RETURN_ON_FALSE(s_lock, ESP_ERR_NO_MEM, TAG, "mutex");
    esp_timer_create_args_t args = {};
    args.callback = timer_cb;
    args.dispatch_method = ESP_TIMER_TASK;
    args.name = "led";
    args.skip_unhandled_events = true;
    return esp_timer_create(&args, &s_timer);
}

void status_led_play(led_pattern_t pattern)
{
    if (pattern >= LED_PAT_COUNT) {
        return;
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_fg = &k_patterns[pattern];
    s_fg_idx = 0;
    s_fg_on = false;
    led_write(false);
    step_locked();
    xSemaphoreGive(s_lock);
}

void status_led_cancel(void)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_fg = NULL;
    s_fg_on = false;
    s_bg_on = true;          /* next step starts the background mode with an "off" phase */
    step_locked();
    xSemaphoreGive(s_lock);
}

static void set_mode(bool *flag, bool on)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    const bool changed = (*flag != on);
    *flag = on;
    if (changed && !s_fg) {
        s_bg_on = false;     /* restart the background cycle with an "on" phase right away */
        step_locked();
    }
    xSemaphoreGive(s_lock);
}

void status_led_set_leak(bool on)
{
    if (on) {
        s_leak_until_us = esp_timer_get_time() + (int64_t)CONFIG_APP_LED_LEAK_MAX_MIN * 60 * 1000000;
    }
    set_mode(&s_leak, on);
}

void status_led_set_commissioning(bool on)
{
    set_mode(&s_commissioning, on);
}

void status_led_set_identify(bool on)
{
    set_mode(&s_identify, on);
}
