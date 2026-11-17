"""Constants for the UGREEN PowerRoam Bluetooth integration."""

DOMAIN = "powerroam_ble"

# GATT characteristics, read off a GS1200 by tanka8. The service (ABF0)
# isn't advertised, so discovery matches the local name instead: the power
# stations advertise as "ugreen gs<model>", other UGREEN gadgets don't.
NOTIFY_UUID = "0000abf2-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000abf1-0000-1000-8000-00805f9b34fb"
NAME_PREFIX = "ugreen gs"
# Picked by hand from the list, any UGREEN name is offered when no unit
# advertises the usual "ugreen gs" name.
FALLBACK_NAME_PREFIX = "ugreen"

# Battery capacity by the model in the advertised name ("ugreen gs1200").
# Other models get no derived values unless the capacity is set in the
# options. GS2200: 2048 Wh per UGREEN's specifications, name assumed.
CAPACITY_WH = {"GS1200": 1024, "GS2200": 2048}
CONF_CAPACITY_WH = "capacity_wh"

# The unit pushes every ~0.6 s; entities are written at most this often so
# the recorder isn't flooded on small hosts such as a Raspberry Pi.
STATE_DEBOUNCE = 10.0

# No frame for this long on an open connection means it is half-open, and
# the link is rebuilt.
FRAME_STALE_AFTER = 30.0

# Entities keep their last values this long after the last frame. At a weak
# signal (about -80 dBm on a Raspberry Pi's built-in adapter) the link drops
# every minute or so and is back within seconds; without this every drop
# would blank the dashboard.
HOLD_AFTER_LAST_FRAME = 120.0

# Reconnect waits, in seconds, after a failed attempt. A fresh advertisement
# cuts the wait short (not below the start value). A link that was up and
# dropped is retried at once.
BACKOFF_START = 5
BACKOFF_MAX = 60

# A write waits for the next reported state and builds on that, so a
# setting changed on the unit a minute ago isn't reverted from a held copy.
SWITCH_STATE_WAIT = 5.0

# How long the unit gets to report the written state back before the write
# is called unconfirmed.
SWITCH_CONFIRM_WAIT = 5.0
