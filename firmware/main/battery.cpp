#include "battery.h"

#include "app_events.h"
#include "app_matter.h"
#include "board_pins.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"

static const char *TAG = "battery";
static const char *NVS_NS = "battery";

/* Light-load voltage -> remaining capacity for a CR123A at room temperature. Coarse on purpose: it only
 * has to catch the knee at the end of life, the charge counter does the rest. Refine in phase 6. */
static const uint16_t k_mv[] = {2950, 2900, 2800, 2700, 2600, 2500, 2300, 2000};
static const uint8_t k_pct[] = {100, 30, 15, 8, 5, 3, 1, 0};

static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_cali;
static esp_timer_handle_t s_timer;
static uint32_t s_used_uah;          /* charge drawn from the current cell (uAh), persisted */
static int64_t s_account_us;         /* time up to which s_used_uah is accounted */
static uint64_t s_rem_uaus;          /* sub-uAh remainder of the counter (uA x us) */
static bool s_first = true;
static uint8_t s_level;              /* BatChargeLevelEnum: 0 OK, 1 Warning, 2 Critical */

static void timer_cb(void *)
{
    app_event_post(APP_EVT_BATTERY_MEASURE, 0);
}

static uint8_t pct_from_mv(int mv)
{
    const int n = sizeof(k_mv) / sizeof(k_mv[0]);
    if (mv >= k_mv[0]) {
        return 100;
    }
    for (int i = 1; i < n; i++) {
        if (mv >= k_mv[i]) {
            return k_pct[i] + (uint8_t)((k_pct[i - 1] - k_pct[i]) * (mv - k_mv[i]) / (k_mv[i - 1] - k_mv[i]));
        }
    }
    return 0;
}

static void nvs_save(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u32(h, "used_uah", s_used_uah);
        nvs_commit(h);
        nvs_close(h);
    }
}

static int read_vbat_mv(void)
{
    app_awake_acquire();                                /* GPIO0 is not an LP IO: stay awake while driven */
    gpio_set_level(PIN_VBAT_MEAS_EN, 1);
    vTaskDelay(pdMS_TO_TICKS(VBAT_SETTLE_MS));
    int sum = 0, n = 0;
    for (int i = 0; i < 8; i++) {
        int raw = 0, mv = 0;
        if (adc_oneshot_read(s_adc, VBAT_ADC_CHANNEL, &raw) == ESP_OK &&
            adc_cali_raw_to_voltage(s_cali, raw, &mv) == ESP_OK) {
            sum += mv;
            n++;
        }
    }
    gpio_set_level(PIN_VBAT_MEAS_EN, 0);
    app_awake_release();
    return n ? (sum / n) * VBAT_DIVIDER_NUM : -1;
}

esp_err_t battery_init(void)
{
    gpio_config_t io = {};
    io.pin_bit_mask = BIT64(PIN_VBAT_MEAS_EN);
    io.mode = GPIO_MODE_OUTPUT;
    ESP_RETURN_ON_ERROR(gpio_config(&io), TAG, "gpio");
    gpio_set_level(PIN_VBAT_MEAS_EN, 0);

    adc_oneshot_unit_init_cfg_t unit_cfg = {};
    unit_cfg.unit_id = VBAT_ADC_UNIT;
    ESP_RETURN_ON_ERROR(adc_oneshot_new_unit(&unit_cfg, &s_adc), TAG, "adc unit");
    adc_oneshot_chan_cfg_t chan_cfg = {};
    chan_cfg.atten = VBAT_ADC_ATTEN;
    chan_cfg.bitwidth = ADC_BITWIDTH_DEFAULT;
    ESP_RETURN_ON_ERROR(adc_oneshot_config_channel(s_adc, VBAT_ADC_CHANNEL, &chan_cfg), TAG, "adc channel");
    adc_cali_curve_fitting_config_t cali_cfg = {};
    cali_cfg.unit_id = VBAT_ADC_UNIT;
    cali_cfg.chan = VBAT_ADC_CHANNEL;
    cali_cfg.atten = VBAT_ADC_ATTEN;
    cali_cfg.bitwidth = ADC_BITWIDTH_DEFAULT;
    ESP_RETURN_ON_ERROR(adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali), TAG, "adc calibration");

    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        nvs_get_u32(h, "used_uah", &s_used_uah);
        nvs_close(h);
    }
    s_account_us = esp_timer_get_time();

    esp_timer_create_args_t args = {};
    args.callback = timer_cb;
    args.dispatch_method = ESP_TIMER_TASK;
    args.name = "battery";
    args.skip_unhandled_events = true;
    ESP_RETURN_ON_ERROR(esp_timer_create(&args, &s_timer), TAG, "timer");
    return esp_timer_start_periodic(s_timer, (uint64_t)CONFIG_APP_BATTERY_PERIOD_MIN * 60 * 1000000);
}

void battery_measure_and_report(void)
{
    const int mv = read_vbat_mv();
    if (mv < 0) {
        ESP_LOGE(TAG, "ADC read failed");
        return;
    }

    /* fresh cell inserted? (power-on reset + rest voltage of a new Li-MnO2 cell) */
    if (s_first && esp_reset_reason() == ESP_RST_POWERON && mv >= CONFIG_APP_BATTERY_NEW_CELL_MV) {
        ESP_LOGI(TAG, "fresh cell detected (%d mV): charge counter reset", mv);
        s_used_uah = 0;
    }
    s_first = false;

    /* charge counter: average current x elapsed time (esp_timer keeps counting through light sleep) */
    const int64_t now = esp_timer_get_time();
    s_rem_uaus += (uint64_t)(now - s_account_us) * CONFIG_APP_BATTERY_AVG_CURRENT_UA;
    s_account_us = now;
    const uint64_t uah = s_rem_uaus / 3600000000ULL;    /* 1 uAh = 3.6e9 uA x us */
    s_used_uah += (uint32_t)uah;
    s_rem_uaus -= uah * 3600000000ULL;
    nvs_save();

    const uint32_t cap_uah = (uint32_t)CONFIG_APP_BATTERY_CAPACITY_MAH * 1000;
    const uint8_t pct_charge = s_used_uah >= cap_uah ? 0 : (uint8_t)(100 - (uint64_t)s_used_uah * 100 / cap_uah);
    const uint8_t pct_volt = pct_from_mv(mv);
    const uint8_t pct = pct_charge < pct_volt ? pct_charge : pct_volt;

    s_level = pct <= CONFIG_APP_BATTERY_CRIT_PERCENT ? 2 : (pct <= CONFIG_APP_BATTERY_WARN_PERCENT ? 1 : 0);
    ESP_LOGI(TAG, "%d mV, %u %% (counter %u %%, voltage %u %%), level %u", mv, (unsigned)pct, (unsigned)pct_charge,
             (unsigned)pct_volt, (unsigned)s_level);
    app_matter_set_battery((uint32_t)mv, pct, s_level, s_level == 2);
}

bool battery_is_low(void)
{
    return s_level != 0;
}
