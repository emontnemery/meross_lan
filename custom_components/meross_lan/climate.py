import typing

from homeassistant.components import climate

from . import meross_entity as me
from .helpers import reverse_lookup
from .merossclient import const as mc
from .select import MtsTrackedSensor
from .sensor import MLTemperatureSensor, UnitOfTemperature, MLOutputPowerState, MLModeStateSensor

if typing.TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .calendar import MtsSchedule
    from .meross_device import MerossDeviceBase
    from .number import MtsSetPointNumber, MtsTemperatureNumber


async def async_setup_entry(
    hass: "HomeAssistant", config_entry: "ConfigEntry", async_add_devices
):
    me.platform_setup_entry(hass, config_entry, async_add_devices, climate.DOMAIN)


class MtsClimate(me.MerossEntity, climate.ClimateEntity):
    PLATFORM = climate.DOMAIN

    ATTR_TEMPERATURE: typing.Final = climate.ATTR_TEMPERATURE
    TEMP_CELSIUS: typing.Final = UnitOfTemperature.CELSIUS

    HVACAction: typing.Final = climate.HVACAction
    HVACMode: typing.Final = climate.HVACMode

    PRESET_CUSTOM: typing.Final = "custom"
    PRESET_COMFORT: typing.Final = "comfort"
    PRESET_SLEEP: typing.Final = "sleep"
    PRESET_AWAY: typing.Final = "away"
    PRESET_AUTO: typing.Final = "auto"

    device_scale: typing.ClassVar[float] = mc.MTS_TEMP_SCALE

    MTS_MODE_TO_PRESET_MAP: typing.ClassVar[dict[int | None, str]]
    """maps device 'mode' value to the HA climate.preset_mode"""
    MTS_MODE_TO_TEMPERATUREKEY_MAP: typing.ClassVar[dict[int | None, str]]
    """maps the current mts mode to the name of temperature setpoint key"""
    PRESET_TO_ICON_MAP: typing.Final = {
        PRESET_COMFORT: "mdi:sun-thermometer",
        PRESET_SLEEP: "mdi:power-sleep",
        PRESET_AWAY: "mdi:bag-checked",
    }
    """lookups used in MtsSetpointNumber to map a pretty icon to the setpoint entity"""

    manager: "MerossDeviceBase"
    number_adjust_temperature: typing.Final["MtsTemperatureNumber"]
    number_preset_temperature: dict[str, "MtsSetPointNumber"]
    schedule: typing.Final["MtsSchedule"]
    select_tracked_sensor: typing.Final["MtsTrackedSensor"]

    # HA core entity attributes:
    current_humidity: float | None
    current_temperature: float | None
    current_mode: str | None
    hvac_action: climate.HVACAction | None
    hvac_mode: climate.HVACMode | None
    hvac_modes: list[climate.HVACMode] = [HVACMode.OFF, HVACMode.HEAT]
    max_temp: float
    min_temp: float
    preset_mode: str | None
    preset_modes: list[str] = [
        PRESET_CUSTOM,
        PRESET_COMFORT,
        PRESET_SLEEP,
        PRESET_AWAY,
        PRESET_AUTO,
    ]
    supported_features: climate.ClimateEntityFeature = (
        climate.ClimateEntityFeature.PRESET_MODE
        | climate.ClimateEntityFeature.TARGET_TEMPERATURE
        | getattr(climate.ClimateEntityFeature, "TURN_OFF", 0)
        | getattr(climate.ClimateEntityFeature, "TURN_ON", 0)
    )
    _enable_turn_on_off_backwards_compatibility = (
        False  # compatibility flag (see HA core climate)
    )
    target_temperature: float | None
    target_temperature_step: float = 0.5
    temperature_unit: str = TEMP_CELSIUS
    translation_key = "mts_climate"

    __slots__ = (
        "current_humidity",
        "current_temperature",
        "current_output_power_state",
        "current_mode_state",
        "current_mode_state_attr",
        "hvac_action",
        "hvac_mode",
        "max_temp",
        "min_temp",
        "preset_mode",
        "target_temperature",
        "_mts_active",
        "_mts_mode",
        "_mts_onoff",
        "_mts_payload",
        "number_adjust_temperature",
        "number_preset_temperature",
        "schedule",
        "select_tracked_sensor",
        "sensor_current_temperature",
        "sensor_output_power_state",
        "sensor_mode_state",
        "_mtsclimate_mask"
    )

    def __init__(
        self,
        manager: "MerossDeviceBase",
        channel: object,
        adjust_number_class: typing.Type["MtsTemperatureNumber"],
        preset_number_class: typing.Type["MtsSetPointNumber"] | None,
        calendar_class: typing.Type["MtsSchedule"],
        mtsclimate_mask: int = mc.MTSCLIMATE_MASK_NONE
    ):
        self.current_humidity = None
        self.current_temperature = None
        self.current_output_power_state = None
        self.current_mode_state = None
        self.current_mode_state_attr = None
        self.hvac_action = None
        self.hvac_mode = None
        self.max_temp = 35
        self.min_temp = 5
        self.preset_mode = None
        self.target_temperature = None
        self._mts_active = None
        self._mts_mode: int | None = None
        self._mts_onoff: int | None = None
        self._mts_payload = {}
        self._mtsclimate_mask=mtsclimate_mask
        self.sensor_output_power_state: "MLOutputPowerState" = None
        self.sensor_mode_state: "MLModeStateSensor" = None

        super().__init__(manager, channel)
        self.number_adjust_temperature = adjust_number_class(self)  # type: ignore
        self.number_preset_temperature = {}
        if preset_number_class:
            for preset in MtsClimate.PRESET_TO_ICON_MAP.keys():
                number_preset_temperature = preset_number_class(self, preset)
                self.number_preset_temperature[number_preset_temperature.key_value] = (
                    number_preset_temperature
                )
        self.schedule = calendar_class(self)
        self.select_tracked_sensor = MtsTrackedSensor(self)
        self.sensor_current_temperature = MLTemperatureSensor(manager, channel)
        self.sensor_current_temperature.entity_registry_enabled_default = True
        self.sensor_current_temperature.suggested_display_precision = 1
        if self._mtsclimate_mask & mc.MTSCLIMATE_MASK_SENSOR_OUTPUT_POWER_STATE:
            self.sensor_output_power_state = MLOutputPowerState(manager, channel)
            self.sensor_output_power_state.entity_registry_enabled_default = True
        if self._mtsclimate_mask & mc.MTSCLIMATE_MASK_SENSOR_MODE_STATE:
            self.sensor_mode_state = MLModeStateSensor(manager, channel, entitykey = "Mode State")
            self.sensor_mode_state.entity_registry_enabled_default = True

    # interface: MerossEntity
    async def async_shutdown(self):
        await super().async_shutdown()
        self.sensor_current_temperature: "MLTemperatureSensor" = None  # type: ignore
        if self.sensor_output_power_state:
            self.sensor_output_power_state: "MLOutputPowerState" = None  # type: ignore
        if self.sensor_mode_state:
            self.sensor_mode_state: "MLModeStateSensor" = None  # type: ignore
        self.select_tracked_sensor = None  # type: ignore
        self.schedule = None  # type: ignore
        self.number_adjust_temperature = None  # type: ignore
        self.number_preset_temperature = None  # type: ignore

    def set_unavailable(self):
        self._mts_active = None
        self._mts_mode = None
        self._mts_onoff = None
        self._mts_payload = {}
        self.current_humidity = None
        self.current_temperature = None
        self.current_output_power_state = None
        self._update_mode_state(mc.SensorModeStateEnum.UNKNOW)
        self.preset_mode = None
        self.hvac_action = None
        self.hvac_mode = None
        super().set_unavailable()

    def flush_state(self):
        self.preset_mode = self.MTS_MODE_TO_PRESET_MAP.get(self._mts_mode)
        super().flush_state()
        self.schedule.flush_state()

    # interface: ClimateEntity
    async def async_turn_on(self):
        await self.async_request_onoff(1)

    async def async_turn_off(self):
        await self.async_request_onoff(0)

    async def async_set_hvac_mode(self, hvac_mode: "MtsClimate.HVACMode"):
        raise NotImplementedError()

    async def async_set_preset_mode(self, preset_mode: str):
        mode = reverse_lookup(self.MTS_MODE_TO_PRESET_MAP, preset_mode)
        if mode is not None:
            await self.async_request_mode(mode)

    async def async_set_temperature(self, **kwargs):
        raise NotImplementedError()

    # interface: self
    async def async_request_mode(self, mode: int):
        """Implements the protocol to set the Meross thermostat mode"""
        raise NotImplementedError()

    async def async_request_onoff(self, onoff: int):
        """Implements the protocol to turn on the thermostat"""
        raise NotImplementedError()

    def is_mts_scheduled(self):
        raise NotImplementedError()

    def _update_current_temperature(self, current_temperature: float | int):
        """
        Common handler for incoming room temperature value
        """
        if self.current_temperature != current_temperature:
            self.current_temperature = current_temperature
            self.select_tracked_sensor.check_tracking()
            self.sensor_current_temperature.update_native_value(current_temperature)
            return True
        return False

    def _update_output_power_state(self, current_output_power_state: bool):
        """
        Common handler for incoming room temperature value
        """
        if self.sensor_output_power_state and self.current_output_power_state != current_output_power_state:
            self.current_output_power_state = current_output_power_state
            self.sensor_output_power_state.update_onoff(current_output_power_state)
            return True
        return False

    def _update_mode_state(self, current_mode_state: "mc.SensorModeStateEnum", extra_attributs:dict|None = None):
        """
        Common handler for incoming room temperature value
        """
        if self.sensor_mode_state and (self.current_mode_state != current_mode_state or self.current_mode_state_attr != extra_attributs):
            self.current_mode_state = current_mode_state
            self.current_mode_state_attr = extra_attributs
            self.sensor_mode_state.update_native_and_extra_state_attribut(current_mode_state,extra_attributs)
            return True
        return False