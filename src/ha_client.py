"""Home Assistant client: REST GET for outdoor data, MQTT discovery push for
indoor status.

GETs the two outdoor entities (independently -- partial data is shown if
only one is reachable) via REST, unchanged. Publishes the four status
metrics (indoor temperature, indoor humidity, lux, last NTP sync) to Home
Assistant via MQTT discovery instead of REST POST, so they show up in HA
grouped under one device card instead of as bare ungrouped entities.
Connects, publishes, and disconnects once per report cycle -- no persistent
MQTT connection is held, matching this project's opportunistic-WiFi pattern
(see wifi_manager.py).
"""
import json

import adafruit_minimqtt.adafruit_minimqtt as MQTT

from log import log

DISCOVERY_PREFIX = "homeassistant"  # HA's fixed default discovery topic prefix


def get_state(requests_session, cfg, entity_id):
    url = "{}/api/states/{}".format(cfg.ha_host, entity_id)
    headers = {"Authorization": "Bearer {}".format(cfg.ha_token)}
    try:
        response = requests_session.get(url, headers=headers)
    except OSError as e:
        log("ha_client: GET {} failed: {}".format(entity_id, e))
        return None
    try:
        if response.status_code != 200:
            log(
                "ha_client: GET {} failed: HTTP {} {}".format(
                    entity_id, response.status_code, response.text
                )
            )
            return None
        return response.json().get("state")
    except (ValueError, AttributeError) as e:
        log("ha_client: GET {} bad response: {}".format(entity_id, e))
        return None
    finally:
        response.close()


def fetch_outdoor(requests_session, cfg):
    """Fetches outdoor temperature/conditions independently of each other --
    whichever entity is reachable is returned, rather than requiring both."""
    return {
        "temperature": get_state(requests_session, cfg, cfg.ha_outdoor_temp_entity),
        "conditions": get_state(requests_session, cfg, cfg.ha_outdoor_conditions_entity),
    }


# HA display metadata per pushed metric, so entities render as proper typed
# sensors (unit, icon, history graph) instead of bare unit-less values.
_METRIC_ATTRS = {
    "indoor_temperature": {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"},
    "indoor_humidity": {"unit_of_measurement": "%", "device_class": "humidity", "state_class": "measurement"},
    "lux": {"unit_of_measurement": "lx", "device_class": "illuminance", "state_class": "measurement"},
    "last_ntp_sync": {"device_class": "timestamp"},
}


def _state_topic(cfg, suffix):
    return "{}/sensor/{}/state".format(cfg.device_name_slug, suffix)


def _discovery_topic(cfg, suffix):
    return "{}/sensor/{}_{}/config".format(DISCOVERY_PREFIX, cfg.device_name_slug, suffix)


def _device_block(cfg):
    # Shared verbatim across all 4 metrics' discovery configs -- HA groups
    # entities that share the same "identifiers" value under one device card.
    return {
        "identifiers": [cfg.device_name_slug],
        "name": cfg.friendly_device_name,
        "manufacturer": "Adafruit",
        "model": "Matrix Portal M4 RGB Clock",
    }


def _make_client(pool, cfg):
    return MQTT.MQTT(
        broker=cfg.mqtt_host,
        port=cfg.mqtt_port,
        username=cfg.mqtt_username or None,
        password=cfg.mqtt_password or None,
        client_id=cfg.device_name_slug,
        socket_pool=pool,
        is_ssl=False,  # plain broker, port 1883, no TLS
    )


def _publish_discovery(client, cfg, suffix, friendly_suffix, unit_override):
    object_id = "{}_{}".format(cfg.device_name_slug, suffix)
    payload = {
        "name": friendly_suffix,
        "unique_id": object_id,
        "object_id": object_id,  # pins entity_id to sensor.{device_name_slug}_{suffix}
        "state_topic": _state_topic(cfg, suffix),
        "device": _device_block(cfg),
        "expire_after": cfg.ha_report_interval * 3,  # 3 missed cycles -> HA shows Unavailable
    }
    payload.update(_METRIC_ATTRS.get(suffix, {}))
    if unit_override is not None:
        payload["unit_of_measurement"] = unit_override
    client.publish(_discovery_topic(cfg, suffix), json.dumps(payload), retain=True)


def _publish_state(client, cfg, suffix, value):
    client.publish(_state_topic(cfg, suffix), str(value), retain=True)


def report_all(pool, cfg, indoor_temp_c, indoor_humidity_pct, lux, last_ntp_sync_iso):
    indoor_temp = indoor_temp_c
    temp_unit = None
    if indoor_temp_c is not None and cfg.temp_unit_f:
        indoor_temp = indoor_temp_c * 9.0 / 5.0 + 32.0
        temp_unit = "°F"

    metrics = (
        ("indoor_temperature", indoor_temp, "Indoor Temperature", temp_unit),
        ("indoor_humidity", indoor_humidity_pct, "Indoor Humidity", None),
        ("lux", lux, "Lux", None),
        ("last_ntp_sync", last_ntp_sync_iso, "Last NTP Sync", None),
    )

    attempted = 0
    succeeded = 0
    to_publish = []
    for suffix, value, friendly_suffix, unit_override in metrics:
        if value is None:
            log("ha_client: skipping {}, no value available".format(suffix))
            continue
        attempted += 1
        to_publish.append((suffix, value, friendly_suffix, unit_override))

    if not to_publish:
        return succeeded, attempted

    client = _make_client(pool, cfg)
    try:
        client.connect()
    except (MQTT.MMQTTException, OSError, RuntimeError) as e:
        log("ha_client: MQTT connect to {}:{} failed: {}".format(cfg.mqtt_host, cfg.mqtt_port, e))
        return succeeded, attempted

    try:
        for suffix, value, friendly_suffix, unit_override in to_publish:
            try:
                _publish_discovery(client, cfg, suffix, friendly_suffix, unit_override)
                _publish_state(client, cfg, suffix, value)
                succeeded += 1
            except (MQTT.MMQTTException, OSError, RuntimeError) as e:
                log("ha_client: MQTT publish {} failed: {}".format(suffix, e))
    finally:
        try:
            client.disconnect()
        except (MQTT.MMQTTException, OSError, RuntimeError):
            pass

    return succeeded, attempted
