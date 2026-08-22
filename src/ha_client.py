"""Home Assistant REST client.

GETs the two outdoor entities (independently -- partial data is shown if
only one is reachable) and POSTs the four auto-created status entities
(indoor temperature, indoor humidity, lux, last NTP sync). Entity IDs for
pushed data are sensor.{device_name_slug}_{suffix} (DEVICE_NAME slugified to
a valid HA object_id); HA creates them on first POST, no YAML needed.
"""
from log import log


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


def post_state(requests_session, cfg, entity_suffix, state, friendly_suffix=None, unit_override=None):
    entity_id = "sensor.{}_{}".format(cfg.device_name_slug, entity_suffix)
    url = "{}/api/states/{}".format(cfg.ha_host, entity_id)
    headers = {
        "Authorization": "Bearer {}".format(cfg.ha_token),
        "Content-Type": "application/json",
    }
    friendly_name = "{} {}".format(cfg.friendly_device_name, friendly_suffix or entity_suffix)
    attributes = {"friendly_name": friendly_name}
    attributes.update(_METRIC_ATTRS.get(entity_suffix, {}))
    if unit_override is not None:
        attributes["unit_of_measurement"] = unit_override
    payload = {"state": state, "attributes": attributes}
    try:
        response = requests_session.post(url, headers=headers, json=payload)
    except OSError as e:
        log("ha_client: POST {} failed: {}".format(entity_id, e))
        return False
    try:
        if response.status_code not in (200, 201):
            log(
                "ha_client: POST {} failed: HTTP {} {}".format(
                    entity_id, response.status_code, response.text
                )
            )
            return False
        return True
    finally:
        response.close()


def report_all(requests_session, cfg, indoor_temp_c, indoor_humidity_pct, lux, last_ntp_sync_iso):
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
    for suffix, value, friendly_suffix, unit_override in metrics:
        if value is None:
            log("ha_client: skipping {}, no value available".format(suffix))
            continue
        attempted += 1
        if post_state(requests_session, cfg, suffix, value, friendly_suffix, unit_override):
            succeeded += 1
    return succeeded, attempted
