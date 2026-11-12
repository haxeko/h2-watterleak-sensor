/*
 * h2-watterleak-sensor - battery water leak detector, ESP32-H2, Matter over Thread (ICD, SIT)
 *
 * Flow: GPIO / EXT1 wake-up -> app task -> probe state machine -> BooleanState.StateValue -> subscription
 * report (the ICD enters active mode for the report) -> auto light sleep again.
 */
#include <esp_check.h>
#include <esp_log.h>
#include <esp_pm.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <nvs_flash.h>

#include "app_events.h"
#include "app_matter.h"
#include "battery.h"
#include "board_pins.h"
#include "button.h"
#include "leak_probe.h"
#include "status_led.h"
#include "wake_inputs.h"

static const char *TAG = "app";

/* Unused and test-pad-only pins: input, pull-down, no interrupt (no floating CMOS inputs in sleep). */
static void park_unused_pins(void)
{
    gpio_config_t io = {};
    io.pin_bit_mask = UNUSED_PIN_MASK;
    io.mode = GPIO_MODE_INPUT;
    io.pull_down_en = GPIO_PULLDOWN_ENABLE;
    io.pull_up_en = GPIO_PULLUP_DISABLE;
    io.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&io));
}

static void configure_power_management(void)
{
#if CONFIG_PM_ENABLE
    esp_pm_config_t pm = {};
    pm.max_freq_mhz = CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ;
    pm.min_freq_mhz = CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ;
#if CONFIG_FREERTOS_USE_TICKLESS_IDLE
    pm.light_sleep_enable = true;
#endif
    ESP_ERROR_CHECK(esp_pm_configure(&pm));
#endif
}

/* FR-09 short press: open the commissioning window when not in any fabric, otherwise show status. */
void app_on_short_press(void)
{
    if (!app_matter_is_commissioned()) {
        ESP_LOGI(TAG, "not commissioned: opening the commissioning window");
        app_matter_open_commissioning_window(CONFIG_APP_COMMISSIONING_WINDOW_S);
        return;
    }
    app_matter_notify_user_activity();      /* stay reachable for ActiveModeDuration */
    int8_t rssi = 0;
    uint8_t lq = 0;
    const bool attached = app_matter_get_parent_link(&rssi, &lq);
    if (attached) {
        ESP_LOGI(TAG, "Thread parent: avg RSSI %d dBm, link quality %u/3", rssi, (unsigned)lq);
    } else {
        ESP_LOGW(TAG, "not attached to a Thread parent");
    }
    if (leak_probe_is_wet()) {
        status_led_play(LED_PAT_LEAK_STATUS);
    } else if (battery_is_low()) {
        status_led_play(LED_PAT_LOW_BATTERY);
    } else if (!attached) {
        status_led_play(LED_PAT_NO_LINK);
    } else {
        /* phase 6 range test / installation aid: 1..3 blinks = link quality to the parent router */
        status_led_play(lq >= 3 ? LED_PAT_LINK_3 : (lq == 2 ? LED_PAT_LINK_2 : LED_PAT_LINK_1));
    }
    app_event_post(APP_EVT_BATTERY_MEASURE, 0);
}

static void app_task(void *)
{
    app_evt_t evt;
    for (;;) {
        if (!app_event_wait(&evt)) {
            continue;
        }
        switch (evt.type) {
        case APP_EVT_WAKE_GPIO:
            if (evt.arg == (uint32_t)PIN_BUTTON_N) {
                button_on_wake();
            } else {
                leak_probe_on_wake((gpio_num_t)evt.arg);
            }
            break;
        case APP_EVT_PROBE_TICK:
            leak_probe_on_tick();
            break;
        case APP_EVT_BUTTON_TICK:
            button_on_tick();
            break;
        case APP_EVT_BATTERY_MEASURE: {
            battery_measure_and_report();
            int8_t rssi = 0;
            uint8_t lq = 0;
            if (app_matter_get_parent_link(&rssi, &lq)) {          /* soak-test log, every 6 h */
                ESP_LOGI(TAG, "Thread parent: avg RSSI %d dBm, link quality %u/3", rssi, (unsigned)lq);
            }
            break;
        }
        case APP_EVT_FACTORY_RESET:
            ESP_LOGW(TAG, "factory reset (%s)", evt.arg ? "last fabric removed" : "button");
            status_led_play(LED_PAT_FACTORY_RESET);
            vTaskDelay(pdMS_TO_TICKS(evt.arg ? 3000 : 1200));   /* let the LED / RemoveFabric response finish */
            app_matter_factory_reset();
            break;
        }
    }
}

extern "C" void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    park_unused_pins();
    configure_power_management();

    ESP_ERROR_CHECK(app_events_init());
    ESP_ERROR_CHECK(status_led_init());
    ESP_ERROR_CHECK(battery_init());
    ESP_ERROR_CHECK(app_matter_init());     /* endpoints must exist before the probe can report */
    ESP_ERROR_CHECK(wake_inputs_init());
    ESP_ERROR_CHECK(leak_probe_init());
    ESP_ERROR_CHECK(button_init());

    xTaskCreate(app_task, "app", 6144, nullptr, 5, nullptr);
    app_event_post(APP_EVT_BATTERY_MEASURE, 0);
    ESP_LOGI(TAG, "h2-watterleak-sensor started");
}
