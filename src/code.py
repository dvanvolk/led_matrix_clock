"""Matrix Portal RGB Clock -- orchestrator.

No I/O logic of its own: this just sequences the boot check and drives the
main loop, delegating every actual operation to the other modules.
"""
import time

import board

import brightness
import config
import display_modes
import ha_client
import i2c_recovery
import rtc_manager
import sensors
import tz
import wifi_manager
from log import log

NTP_RESYNC_INTERVAL = 24 * 60 * 60  # once a day, per the spec
SENSOR_SAMPLE_INTERVAL = 1.0  # BH1750/AHT20 sampled on their own ~1s timer,
# decoupled from the main loop's tick rate.
BOOT_RETRY_INTERVAL = 60
MAIN_LOOP_INTERVAL = 0.5
I2C_RECOVERY_COOLDOWN = 5.0  # don't re-attempt bus recovery more than this often
LUX_LOG_INTERVAL = 60  # throttle lux/brightness logging so it doesn't flood serial


def _iso(utc_struct_time):
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
        utc_struct_time.tm_year,
        utc_struct_time.tm_mon,
        utc_struct_time.tm_mday,
        utc_struct_time.tm_hour,
        utc_struct_time.tm_min,
        utc_struct_time.tm_sec,
    )


def _has_outdoor_data(outdoor_cache):
    return bool(outdoor_cache) and (
        outdoor_cache.get("temperature") is not None
        or outdoor_cache.get("conditions") is not None
    )


def _boot(cfg, renderer, rtc_mgr):
    """Covers both the "WiFi unavailable on boot" and "DS3231 invalid + no
    WiFi" degradation-table rows, which specify identical behavior: show
    "----" and retry every 60s until the RTC is valid. Returns the synced UTC
    time.struct_time if a boot-time NTP sync happened, else None (RTC was
    already valid, so no sync was needed) -- the caller uses this to seed
    last_ntp_sync_iso for the HA report."""
    if rtc_mgr.is_valid:
        log("code: RTC valid, starting immediately (no WiFi)")
        return None

    log("code: RTC invalid or lost power, need NTP before starting")
    while not rtc_mgr.is_valid:
        renderer.show_placeholder("----")
        if cfg.wifi_configured:
            with wifi_manager.session(cfg) as sess:
                if sess.connected:
                    utc = wifi_manager.ntp_sync(cfg)
                    if utc is not None:
                        rtc_mgr.write_utc(utc)
                        log("code: NTP sync ok, RTC updated")
                        return utc
                    log("code: NTP sync failed, retrying in {} s".format(BOOT_RETRY_INTERVAL))
                else:
                    log("code: WiFi connect failed, retrying in {} s".format(BOOT_RETRY_INTERVAL))
        time.sleep(BOOT_RETRY_INTERVAL)


def main():
    log("code: ==== Matrix Clock starting ====")
    cfg = config.load()
    log("code: device_name={} wifi_configured={} ha_configured={} timezone={}".format(
        cfg.device_name, cfg.wifi_configured, cfg.ha_configured, cfg.timezone
    ))
    log("code: mode_order={}".format(cfg.mode_order))
    if not cfg.wifi_configured:
        log("code: WiFi not configured -- running clock-only, offline")
    if not cfg.ha_configured:
        log("code: Home Assistant not configured -- HA modes disabled")

    i2c = board.I2C()
    display = display_modes.init_display()
    renderer = display_modes.Renderer(display, cfg)
    rtc_mgr = rtc_manager.RTCManager(i2c)
    sensor_hub = sensors.SensorHub(i2c)
    tz_instance = tz.PosixTZ(cfg.timezone)
    log("code: display/RTC/sensors/timezone initialized")

    boot_sync_utc = _boot(cfg, renderer, rtc_mgr)

    mode_mgr = display_modes.ModeManager(cfg)
    bottom_mgr = display_modes.BottomRotator(cfg)
    current_brightness = cfg.brightness_mid
    current_lux = None
    current_indoor = None
    last_sensor_sample = -SENSOR_SAMPLE_INTERVAL
    last_ntp_sync = time.monotonic()
    last_ntp_sync_iso = _iso(boot_sync_utc) if boot_sync_utc is not None else None
    last_ha_fetch = -cfg.ha_fetch_interval
    last_ha_report = -cfg.ha_report_interval
    outdoor_cache = None
    last_utc = boot_sync_utc
    last_i2c_recovery = -I2C_RECOVERY_COOLDOWN
    last_lux_log = -LUX_LOG_INTERVAL

    log("code: entering main loop")
    while True:
        try:
            now = time.monotonic()

            utc = rtc_mgr.read_utc()
            if utc is not None:
                last_utc = utc
            if last_utc is None:
                # Only possible if the very first read after boot glitches --
                # nothing to hold yet, so wait for a good read.
                time.sleep(MAIN_LOOP_INTERVAL)
                continue
            local_time, _tz_abbr = tz_instance.to_local(last_utc)

            if now - last_sensor_sample >= SENSOR_SAMPLE_INTERVAL:
                last_sensor_sample = now
                lux = sensor_hub.read_lux()
                if lux is not None:
                    current_lux = lux
                current_indoor = sensor_hub.read_indoor()

            if (
                (rtc_mgr.io_error or sensor_hub.io_error)
                and now - last_i2c_recovery >= I2C_RECOVERY_COOLDOWN
            ):
                last_i2c_recovery = now
                log("code: I2C error detected, recovering bus")
                i2c = i2c_recovery.recover(i2c)
                rtc_mgr.rebind(i2c)
                sensor_hub.rebind(i2c)

            if current_lux is not None:
                target = brightness.target_level(current_lux, cfg)
                current_brightness = brightness.smooth(current_brightness, target)
                renderer.set_brightness(current_brightness)

                if now - last_lux_log >= LUX_LOG_INTERVAL:
                    last_lux_log = now
                    log("code: lux={:.1f} brightness={:.2f}".format(current_lux, current_brightness))

            bottom_mgr.update_availability(
                indoor_available=current_indoor is not None,
                outdoor_available=_has_outdoor_data(outdoor_cache),
            )
            mode_mgr.tick(now)
            bottom_mgr.tick(now)
            mode = mode_mgr.current_mode()
            bottom_item = bottom_mgr.current_item()
            renderer.render(mode, bottom_item, local_time, current_indoor, outdoor_cache)

            if cfg.wifi_configured and now - last_ntp_sync >= NTP_RESYNC_INTERVAL:
                last_ntp_sync = now
                with wifi_manager.session(cfg) as sess:
                    if sess.connected:
                        synced = wifi_manager.ntp_sync(cfg)
                        if synced is not None:
                            rtc_mgr.write_utc(synced)
                            last_ntp_sync_iso = _iso(synced)
                            log("code: daily NTP resync ok, RTC updated")
                        else:
                            log("code: daily NTP resync failed, retrying next interval")
                    else:
                        log("code: daily NTP resync skipped, WiFi connect failed")

            if cfg.ha_configured and now - last_ha_fetch >= cfg.ha_fetch_interval:
                last_ha_fetch = now
                with wifi_manager.session(cfg) as sess:
                    if sess.connected:
                        outdoor_cache = ha_client.fetch_outdoor(sess.requests, cfg)
                        log("code: HA outdoor fetch done: {}".format(outdoor_cache))
                    else:
                        log("code: HA outdoor fetch skipped, WiFi connect failed")

            if cfg.ha_configured and now - last_ha_report >= cfg.ha_report_interval:
                last_ha_report = now
                with wifi_manager.session(cfg) as sess:
                    if sess.connected:
                        succeeded, attempted = ha_client.report_all(
                            sess.requests,
                            cfg,
                            rtc_mgr.read_chip_temperature(),
                            current_lux,
                            last_ntp_sync_iso,
                            sess.rssi(),
                            bottom_item,
                        )
                        log("code: HA status report sent ({}/{} ok)".format(
                            succeeded, attempted
                        ))
                    else:
                        log("code: HA status report skipped, WiFi connect failed")

        except Exception as e:  # noqa: BLE001 -- a transient fault must never blank the panel
            log("code: main loop error: {}".format(e))

        time.sleep(MAIN_LOOP_INTERVAL)


main()
