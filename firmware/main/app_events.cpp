#include "app_events.h"

#include "esp_check.h"
#include "esp_pm.h"
#include "freertos/queue.h"

static const char *TAG = "events";
static QueueHandle_t s_queue;
static esp_pm_lock_handle_t s_awake_lock;

esp_err_t app_events_init(void)
{
    s_queue = xQueueCreate(16, sizeof(app_evt_t));
    ESP_RETURN_ON_FALSE(s_queue, ESP_ERR_NO_MEM, TAG, "queue");
#if CONFIG_PM_ENABLE
    ESP_RETURN_ON_ERROR(esp_pm_lock_create(ESP_PM_NO_LIGHT_SLEEP, 0, "app_awake", &s_awake_lock), TAG, "pm lock");
#endif
    return ESP_OK;
}

bool app_event_post(app_evt_type_t type, uint32_t arg)
{
    const app_evt_t evt = {type, arg};
    return xQueueSend(s_queue, &evt, 0) == pdTRUE;
}

bool app_event_post_from_isr(app_evt_type_t type, uint32_t arg, BaseType_t *higher_prio_woken)
{
    const app_evt_t evt = {type, arg};
    return xQueueSendFromISR(s_queue, &evt, higher_prio_woken) == pdTRUE;
}

bool app_event_wait(app_evt_t *evt)
{
    return xQueueReceive(s_queue, evt, portMAX_DELAY) == pdTRUE;
}

void app_awake_acquire(void)
{
#if CONFIG_PM_ENABLE
    esp_pm_lock_acquire(s_awake_lock);
#endif
}

void app_awake_release(void)
{
#if CONFIG_PM_ENABLE
    esp_pm_lock_release(s_awake_lock);
#endif
}
