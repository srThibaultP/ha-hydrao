"""Constants for the Hydrao BLE integration."""

DOMAIN = "hydrao"
MANUFACTURER = "Hydrao"
MODEL = "Shower head"
DEVICE_NAME_PREFIX = "HYDRAO_SHOWER"

# ── GATT UUIDs ───────────────────────────────────────────────────────────────
SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"

CHAR = {
    "uuid":          "0000ca28-0000-1000-8000-00805f9b34fb",
    "fw_version":    "00002a26-0000-1000-8000-00805f9b34fb",
    "hw_version":    "0000ca24-0000-1000-8000-00805f9b34fb",
    "live_volume":   "0000ca1c-0000-1000-8000-00805f9b34fb",
    "live_flow":     "0000ca31-0000-1000-8000-00805f9b34fb",
    "live_temp":     "0000ca32-0000-1000-8000-00805f9b34fb",
    "thresholds":    "0000ca1d-0000-1000-8000-00805f9b34fb",
    "calibration":   "0000ca30-0000-1000-8000-00805f9b34fb",
    "reset_volume":  "0000ca20-0000-1000-8000-00805f9b34fb",
    "shower_range":  "0000ca21-0000-1000-8000-00805f9b34fb",
    "shower_request":"0000ca22-0000-1000-8000-00805f9b34fb",
    "shower_data":   "0000ca23-0000-1000-8000-00805f9b34fb",
}

# ── Protocol constants ────────────────────────────────────────────────────────
DEFAULT_CALIBRATION = 545
MAX_SOAPING_TIME = 180      # seconds
MIN_VALID_VOLUME = 3        # liters
LEGACY_FLOW = 6.8           # L/min for hw_version < 8
LIVE_POLL_INTERVAL = 2      # seconds between live reads
SOAPING_TIME = 120          # seconds the water can stay off within one shower
LIVE_EVERY_N_SHOWERS = 5    # live read between showers of the history sync
RESET_VOLUME_COMMAND = b"\x01"
CONNECT_TIMEOUT = 10        # seconds

DEFAULT_THRESHOLDS = [
    {"color": "#00FF00", "liter": 5.0},
    {"color": "#0000FF", "liter": 10.0},
    {"color": "#FF00FF", "liter": 15.0},
    {"color": "#FF0000", "liter": 20.0},
]

# ── LED thresholds, as the Hydrao app edits them ──────────────────────────────
THRESHOLD_COUNT = 4
THRESHOLD_MIN_VOLUME = 2    # liters
THRESHOLD_MAX_VOLUME = 250  # liters
THRESHOLD_MIN_GAP = 2       # liters between two thresholds

# Colors the app offers, with the value it writes for each
THRESHOLD_COLORS = {
    "yellow": "#FAB900",
    "orange": "#FF5000",
    "red": "#FF0000",
    "purple": "#FF00B4",
    "blue": "#0000FF",
    "light_blue": "#0AD2F0",
    "green": "#00FF00",
    "light_green": "#67FF11",
    "off": "#000000",
}
# Other values the app shows as one of the colors above
THRESHOLD_COLOR_ALIASES = {
    "#4CDDF1": "light_blue",
    "#FF00FF": "purple",
    "#FF7100": "orange",
    "#FFDE1A": "yellow",
}

# ── Sensor keys ───────────────────────────────────────────────────────────────
SENSOR_LIVE_VOLUME      = "live_volume"
SENSOR_LIVE_FLOW        = "live_flow"
SENSOR_LIVE_TEMPERATURE = "live_temperature"
SENSOR_LIVE_DURATION    = "live_duration"
SENSOR_LIVE_AVERAGE_FLOW        = "live_average_flow"
SENSOR_LIVE_AVERAGE_TEMPERATURE = "live_average_temperature"
SENSOR_TOTAL_VOLUME     = "total_volume"
SENSOR_LAST_VOLUME      = "last_shower_volume"
SENSOR_LAST_TEMPERATURE = "last_shower_temperature"
SENSOR_LAST_FLOW        = "last_shower_flow"
SENSOR_LAST_DURATION    = "last_shower_duration"
SENSOR_LAST_SOAPING     = "last_shower_soaping_time"
SENSOR_LAST_DATE        = "last_shower_date"
SENSOR_RSSI             = "rssi"
SENSOR_FW_VERSION       = "firmware_version"
SENSOR_CALIBRATION      = "calibration"
BINARY_IS_SHOWERING     = "is_showering"
BINARY_IS_SOAPING       = "is_soaping"
BUTTON_END_SHOWER       = "end_shower"
