#include "app_matter.h"

#include <cstring>

#include <esp_check.h>
#include <esp_log.h>
#include <esp_matter.h>
#include <esp_openthread.h>
#include <esp_openthread_lock.h>
#include <esp_openthread_types.h>
#include <openthread/platform/radio.h>
#include <openthread/thread.h>

#include <app/clusters/boolean-state-server/BooleanStateCluster.h>
#include <app/server/CommissioningWindowManager.h>
#include <app/server/Server.h>
#include <data_model_provider/esp_matter_data_model_provider.h>
#include <platform/ESP32/OpenthreadLauncher.h>
#if CONFIG_ENABLE_ICD_SERVER
#include <app/icd/server/ICDNotifier.h>
#endif

#include "app_events.h"
#include "status_led.h"

static const char *TAG = "matter";

using namespace esp_matter;
using namespace chip::app::Clusters;

static uint16_t s_leak_ep = chip::kInvalidEndpointId;

/* ------------------------------------------------------------------ callbacks */
static void apply_thread_tx_power(void)
{
    if (!esp_openthread_lock_acquire(pdMS_TO_TICKS(100))) {
        return;
    }
    otInstance *ot = esp_openthread_get_instance();
    if (ot && otPlatRadioSetTransmitPower(ot, CONFIG_APP_THREAD_TX_POWER_DBM) == OT_ERROR_NONE) {
        ESP_LOGI(TAG, "Thread TX power %d dBm", CONFIG_APP_THREAD_TX_POWER_DBM);
    }
    esp_openthread_lock_release();
}

static void app_event_cb(const ChipDeviceEvent *event, intptr_t arg)
{
    switch (event->Type) {
    case chip::DeviceLayer::DeviceEventType::kThreadStateChange:
        apply_thread_tx_power();
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningComplete:
        ESP_LOGI(TAG, "commissioning complete");
        status_led_play(LED_PAT_CONNECTED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowOpened:
        ESP_LOGI(TAG, "commissioning window opened");
        status_led_set_commissioning(true);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowClosed:
        ESP_LOGI(TAG, "commissioning window closed");
        status_led_set_commissioning(false);
        break;
    case chip::DeviceLayer::DeviceEventType::kFabricRemoved:
        ESP_LOGI(TAG, "fabric removed, %u left", (unsigned)chip::Server::GetInstance().GetFabricTable().FabricCount());
#if CONFIG_APP_FACTORY_RESET_ON_LAST_FABRIC_REMOVED
        if (chip::Server::GetInstance().GetFabricTable().FabricCount() == 0) {
            /* handled in the app task, after the RemoveFabric response has gone out */
            app_event_post(APP_EVT_FACTORY_RESET, 1);
        }
#endif
        break;
    default:
        break;
    }
}

static esp_err_t app_identification_cb(identification::callback_type_t type, uint16_t endpoint_id, uint8_t effect_id,
                                       uint8_t effect_variant, void *priv_data)
{
    ESP_LOGI(TAG, "identify: type %u, effect %u", (unsigned)type, (unsigned)effect_id);
    switch (type) {
    case identification::START:
        status_led_set_identify(true);
        break;
    case identification::STOP:
        status_led_set_identify(false);
        break;
    case identification::EFFECT:
        status_led_play(LED_PAT_IDENTIFY_EFFECT);
        break;
    default:
        break;
    }
    return ESP_OK;
}

static esp_err_t app_attribute_update_cb(attribute::callback_type_t type, uint16_t endpoint_id, uint32_t cluster_id,
                                         uint32_t attribute_id, esp_matter_attr_val_t *val, void *priv_data)
{
    return ESP_OK;   /* no writable application attributes */
}

/* ------------------------------------------------------------------ setup */
static esp_err_t add_power_source(endpoint_t *ep)
{
    endpoint::power_source::config_t cfg;
    cfg.power_source.status = chip::to_underlying(PowerSource::PowerSourceStatusEnum::kActive);
    cfg.power_source.order = 0;
    strncpy(cfg.power_source.description, "CR123A", sizeof(cfg.power_source.description) - 1);
    cfg.power_source.feature_flags = cluster::power_source::feature::battery::get_id() |
                                     cluster::power_source::feature::replaceable::get_id();
    cfg.power_source.features.battery.bat_charge_level = chip::to_underlying(PowerSource::BatChargeLevelEnum::kOk);
    cfg.power_source.features.battery.bat_replacement_needed = false;
    cfg.power_source.features.battery.bat_replaceability =
        chip::to_underlying(PowerSource::BatReplaceabilityEnum::kUserReplaceable);
    strncpy(cfg.power_source.features.replaceable.bat_replacement_description, "CR123A 3 V lithium",
            sizeof(cfg.power_source.features.replaceable.bat_replacement_description) - 1);
    cfg.power_source.features.replaceable.bat_quantity = 1;
    ESP_RETURN_ON_ERROR(endpoint::power_source::add(ep, &cfg), TAG, "power source");

    /* optional attributes (FR-06) */
    cluster_t *ps = cluster::get(ep, PowerSource::Id);
    ESP_RETURN_ON_FALSE(ps, ESP_FAIL, TAG, "power source cluster");
    cluster::power_source::attribute::create_bat_voltage(ps, nullable<uint32_t>(), nullable<uint32_t>(0),
                                                         nullable<uint32_t>(4000));
    cluster::power_source::attribute::create_bat_percent_remaining(ps, nullable<uint8_t>(), nullable<uint8_t>(0),
                                                                   nullable<uint8_t>(200));
    cluster::power_source::attribute::create_bat_common_designation(
        ps, chip::to_underlying(PowerSource::BatCommonDesignationEnum::kCr123a), 0, 0xFE);
    cluster::power_source::attribute::create_bat_approved_chemistry(
        ps, chip::to_underlying(PowerSource::BatApprovedChemistryEnum::kLithiumManganeseDioxide), 0, 0xFE);
    cluster::power_source::attribute::create_bat_capacity(ps, CONFIG_APP_BATTERY_CAPACITY_MAH, 0, UINT32_MAX);
    return ESP_OK;
}

esp_err_t app_matter_init(void)
{
    node::config_t node_config;
    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);
    ESP_RETURN_ON_FALSE(node, ESP_FAIL, TAG, "node");

    endpoint::water_leak_detector::config_t leak_config;   /* Identify type: visible indicator (LED) */
    endpoint_t *ep = endpoint::water_leak_detector::create(node, &leak_config, ENDPOINT_FLAG_NONE, nullptr);
    ESP_RETURN_ON_FALSE(ep, ESP_FAIL, TAG, "water leak detector endpoint");
    s_leak_ep = endpoint::get_id(ep);
    ESP_RETURN_ON_ERROR(add_power_source(ep), TAG, "power source");

    esp_openthread_platform_config_t ot_config = {};
    ot_config.radio_config.radio_mode = RADIO_MODE_NATIVE;
    ot_config.host_config.host_connection_mode = HOST_CONNECTION_MODE_NONE;
    ot_config.port_config.storage_partition_name = "nvs";
    ot_config.port_config.netif_queue_size = 10;
    ot_config.port_config.task_queue_size = 10;
    set_openthread_platform_config(&ot_config);

    ESP_RETURN_ON_ERROR(esp_matter::start(app_event_cb), TAG, "esp_matter::start");
    ESP_LOGI(TAG, "Water Leak Detector on endpoint %u", (unsigned)s_leak_ep);
    return ESP_OK;
}

/* ------------------------------------------------------------------ runtime */
void app_matter_set_leak(bool leak)
{
    /* StateValue is managed by the BooleanState server cluster (ATTRIBUTE_FLAG_MANAGED_INTERNALLY):
     * attribute::update() cannot set it. SetStateValue() also generates the StateChange event. */
    lock::ScopedChipStackLock lock(portMAX_DELAY);
    chip::app::ServerClusterInterface *iface = data_model::provider::get_instance().registry().Get(
        chip::app::ConcreteClusterPath(s_leak_ep, BooleanState::Id));
    if (!iface) {
        ESP_LOGE(TAG, "BooleanState cluster not found on endpoint %u", (unsigned)s_leak_ep);
        return;
    }
    static_cast<BooleanStateCluster *>(iface)->SetStateValue(leak);
#if CONFIG_ENABLE_ICD_SERVER
    /* enter ICD active mode now: the report goes out at once and the controller's reply is polled fast */
    chip::app::ICDNotifier::GetInstance().NotifyNetworkActivityNotification();
#endif
    ESP_LOGI(TAG, "StateValue = %s", leak ? "TRUE (leak)" : "FALSE");
}

void app_matter_set_battery(uint32_t mv, uint8_t percent, uint8_t charge_level, bool replace)
{
    /* Power Source attributes live in the esp-matter attribute store: attribute::update() reports them */
    esp_matter_attr_val_t v = esp_matter_nullable_uint32(nullable<uint32_t>(mv));
    attribute::update(s_leak_ep, PowerSource::Id, PowerSource::Attributes::BatVoltage::Id, &v);
    v = esp_matter_nullable_uint8(nullable<uint8_t>((uint8_t)(percent * 2)));   /* half-percent units */
    attribute::update(s_leak_ep, PowerSource::Id, PowerSource::Attributes::BatPercentRemaining::Id, &v);
    v = esp_matter_enum8(charge_level);
    attribute::update(s_leak_ep, PowerSource::Id, PowerSource::Attributes::BatChargeLevel::Id, &v);
    v = esp_matter_bool(replace);
    attribute::update(s_leak_ep, PowerSource::Id, PowerSource::Attributes::BatReplacementNeeded::Id, &v);
}

bool app_matter_is_commissioned(void)
{
    lock::ScopedChipStackLock lock(portMAX_DELAY);
    return chip::Server::GetInstance().GetFabricTable().FabricCount() > 0;
}

void app_matter_open_commissioning_window(uint16_t seconds)
{
    lock::ScopedChipStackLock lock(portMAX_DELAY);
    chip::CommissioningWindowManager &mgr = chip::Server::GetInstance().GetCommissioningWindowManager();
    if (mgr.IsCommissioningWindowOpen()) {
        return;
    }
    CHIP_ERROR err = mgr.OpenBasicCommissioningWindow(chip::System::Clock::Seconds32(seconds),
                                                      chip::CommissioningWindowAdvertisement::kAllSupported);
    if (err != CHIP_NO_ERROR) {
        ESP_LOGE(TAG, "open commissioning window failed: %" CHIP_ERROR_FORMAT, err.Format());
    }
}

void app_matter_notify_user_activity(void)
{
#if CONFIG_ENABLE_ICD_SERVER
    chip::DeviceLayer::PlatformMgr().ScheduleWork(
        [](intptr_t) { chip::app::ICDNotifier::GetInstance().NotifyNetworkActivityNotification(); });
#endif
}

void app_matter_factory_reset(void)
{
    esp_matter::factory_reset();   /* erases Matter + Thread settings, then restarts */
}

bool app_matter_get_parent_link(int8_t *avg_rssi_dbm, uint8_t *link_quality)
{
    bool ok = false;
    if (!esp_openthread_lock_acquire(pdMS_TO_TICKS(100))) {
        return false;
    }
    otInstance *ot = esp_openthread_get_instance();
    otRouterInfo parent;
    if (ot && otThreadGetDeviceRole(ot) == OT_DEVICE_ROLE_CHILD && otThreadGetParentInfo(ot, &parent) == OT_ERROR_NONE) {
        int8_t rssi = 0;
        if (otThreadGetParentAverageRssi(ot, &rssi) != OT_ERROR_NONE) {
            otThreadGetParentLastRssi(ot, &rssi);
        }
        *avg_rssi_dbm = rssi;
        *link_quality = parent.mLinkQualityIn;
        ok = true;
    }
    esp_openthread_lock_release();
    return ok;
}
