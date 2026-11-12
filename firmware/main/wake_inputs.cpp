#include "wake_inputs.h"

#include "app_events.h"
#include "board_pins.h"
#include "esp_check.h"
#include "esp_sleep.h"

static const char *TAG = "wake";

static void wake_isr(void *arg)
{
    const gpio_num_t pin = (gpio_num_t)(intptr_t)arg;
    gpio_intr_disable(pin);                 /* level interrupt: exactly one event per arming */
    BaseType_t woken = pdFALSE;
    app_event_post_from_isr(APP_EVT_WAKE_GPIO, (uint32_t)pin, &woken);
    if (woken) {
        portYIELD_FROM_ISR();
    }
}

esp_err_t wake_inputs_init(void)
{
    gpio_config_t io = {};
    io.pin_bit_mask = WAKE_EXT1_MASK;
    io.mode = GPIO_MODE_INPUT;
    io.pull_up_en = GPIO_PULLUP_DISABLE;     /* external pull-ups: internal pulls are lost in TOP power-down */
    io.pull_down_en = GPIO_PULLDOWN_DISABLE;
    io.intr_type = GPIO_INTR_DISABLE;        /* enabled per pin by wake_inputs_arm() */
    ESP_RETURN_ON_ERROR(gpio_config(&io), TAG, "gpio_config");

    esp_err_t err = gpio_install_isr_service(0);
    ESP_RETURN_ON_FALSE(err == ESP_OK || err == ESP_ERR_INVALID_STATE, err, TAG, "isr service");

    const gpio_num_t pins[] = {PIN_BUTTON_N, PIN_LEAK_A_N, PIN_LEAK_B_N};
    for (gpio_num_t pin : pins) {
        ESP_RETURN_ON_FALSE(esp_sleep_is_valid_wakeup_gpio(pin), ESP_ERR_INVALID_ARG, TAG, "GPIO%d cannot wake", (int)pin);
        ESP_RETURN_ON_ERROR(gpio_isr_handler_add(pin, wake_isr, (void *)(intptr_t)pin), TAG, "isr add");
    }
    ESP_RETURN_ON_ERROR(esp_sleep_enable_gpio_wakeup(), TAG, "gpio wakeup");
    return ESP_OK;
}

void wake_inputs_arm(gpio_num_t pin)
{
    gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);                         /* also sets the interrupt type */
    esp_sleep_enable_ext1_wakeup_io(BIT64(pin), ESP_EXT1_WAKEUP_ANY_LOW);  /* per-pin mask on ESP32-H2   */
    gpio_intr_enable(pin);
}

void wake_inputs_disarm(gpio_num_t pin)
{
    gpio_intr_disable(pin);
    gpio_wakeup_disable(pin);
    esp_sleep_disable_ext1_wakeup_io(BIT64(pin));
}
