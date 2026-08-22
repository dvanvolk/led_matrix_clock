"""Home Assistant REST client.

GETs the two outdoor entities (independently -- partial data is shown if
only one is reachable) and POSTs the five auto-created status entities.
Entity IDs for pushed data are sensor.{device_name_slug}_{suffix} (DEVICE_NAME
slugified to a valid HA object_id); HA creates them on first POST, no YAML
needed.
"""


def get_state(requests_session, cfg, entity_id):
    url = "{}/api/states/{}".format(cfg.ha_host, entity_id)
    headers = {"Authorization": "Bearer {}".format(cfg.ha_token)}
    try:
        response = requests_session.get(url, headers=headers)
    except OSError as e:
        print("ha_client: GET {} failed: {}".format(entity_id, e))
        return None
    try:
        if response.status_code != 200:
            return None
        return response.json().get("state")
    except (ValueError, AttributeError) as e:
        print("ha_client: GET {} bad response: {}".format(entity_id, e))
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


def post_state(requests_session, cfg, entity_suffix, state, friendly_suffix=None):
    entity_id = "sensor.{}_{}".format(cfg.device_name_slug, entity_suffix)
    url = "{}/api/states/{}".format(cfg.ha_host, entity_id)
    headers = {
        "Authorization": "Bearer {}".format(cfg.ha_token),
        "Content-Type": "application/json",
    }
    friendly_name = "{} {}".format(cfg.friendly_device_name, friendly_suffix or entity_suffix)
    payload = {"state": state, "attributes": {"friendly_name": friendly_name}}
    try:
        response = requests_session.post(url, headers=headers, json=payload)
    except OSError as e:
        print("ha_client: POST {} failed: {}".format(entity_id, e))
        return False
    try:
        if response.status_code not in (200, 201):
            print(
                "ha_client: POST {} failed: HTTP {} {}".format(
                    entity_id, response.status_code, response.text
                )
            )
            return False
        return True
    finally:
        response.close()


def report_all(requests_session, cfg, rtc_temp_c, lux, last_ntp_sync_iso, rssi, mode):
    metrics = (
        ("rtc_temperature", rtc_temp_c, "RTC Temperature"),
        ("lux", lux, "Lux"),
        ("last_ntp_sync", last_ntp_sync_iso, "Last NTP Sync"),
        ("wifi_rssi", rssi, "WiFi RSSI"),
        ("display_mode", mode, "Display Mode"),
    )
    attempted = 0
    succeeded = 0
    for suffix, value, friendly_suffix in metrics:
        if value is not None:
            attempted += 1
            if post_state(requests_session, cfg, suffix, value, friendly_suffix):
                succeeded += 1
    return succeeded, attempted
