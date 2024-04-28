import typing

from ..helpers.namespaces import NamespaceHandler, PollingStrategy
from ..light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    MLLightBase,
    _rgb_to_int,
    _sat_1_100,
)
from ..merossclient import const as mc
from ..sensor import MLHumiditySensor, MLTemperatureSensor
from .spray import MLSpray

if typing.TYPE_CHECKING:
    from ..helpers.namespaces import DigestParseFunc
    from ..meross_device import MerossDevice


DIFFUSER_SENSOR_CLASS_MAP: dict[
    str, type[MLHumiditySensor] | type[MLTemperatureSensor]
] = {
    mc.KEY_HUMIDITY: MLHumiditySensor,
    mc.KEY_TEMPERATURE: MLTemperatureSensor,
}


def digest_init_diffuser(device: "MerossDevice", digest: dict) -> "DigestParseFunc":
    """
    {
        "type": "mod100",
        "light": [{"channel": 0, "onoff": 0, "lmTime": 1639082117, "mode": 0, "luminance": 100, "rgb": 4129023}],
        "spray": [{"channel": 0, "mode": 2, "lmTime": 1644353195}]
    }
    """

    diffuser_light_handler = NamespaceHandler(
        device, mc.NS_APPLIANCE_CONTROL_DIFFUSER_LIGHT, entity_class=MLDiffuserLight
    )
    for light_digest in digest.get(mc.KEY_LIGHT, []):
        MLDiffuserLight(device, light_digest)

    diffuser_spray_handler = NamespaceHandler(
        device, mc.NS_APPLIANCE_CONTROL_DIFFUSER_SPRAY, entity_class=MLDiffuserSpray
    )
    for spray_digest in digest.get(mc.KEY_SPRAY, []):
        MLDiffuserSpray(device, spray_digest[mc.KEY_CHANNEL])

    if mc.NS_APPLIANCE_CONTROL_DIFFUSER_SENSOR in device.descriptor.ability:
        # former mod100 devices reported fake values for sensors, maybe the mod150 and/or a new firmware
        # are supporting correct values so we implement them (#243)
        def _handle_Appliance_Control_Diffuser_Sensor(header: dict, payload: dict):
            """
            {
                "type": "mod100",
                "humidity": {"value": 0, "lmTime": 0},
                "temperature": {"value": 0, "lmTime": 0}
            }
            """
            entities = device.entities
            for key in (mc.KEY_HUMIDITY, mc.KEY_TEMPERATURE):
                if key in payload:
                    try:
                        entities[key].update_native_value(
                            payload[key][mc.KEY_VALUE] / 10
                        )
                    except KeyError:
                        DIFFUSER_SENSOR_CLASS_MAP[key](
                            device, None, device_value=payload[key][mc.KEY_VALUE] / 10
                        )

        PollingStrategy(
            device,
            mc.NS_APPLIANCE_CONTROL_DIFFUSER_SENSOR,
            item_count=1,
            handler=_handle_Appliance_Control_Diffuser_Sensor,
        )

    diffuser_light_parser = diffuser_light_handler.parse_list
    diffuser_spray_parser = diffuser_spray_handler.parse_list

    def digest_parse(digest: dict):
        """
        {
            "type": "mod100",
            "light": [{"channel": 0, "onoff": 0, "lmTime": 1639082117, "mode": 0, "luminance": 100, "rgb": 4129023}],
            "spray": [{"channel": 0, "mode": 2, "lmTime": 1644353195}]
        }
        """
        diffuser_light_parser(digest.get(mc.KEY_LIGHT, []))
        diffuser_spray_parser(digest.get(mc.KEY_SPRAY, []))

    return digest_parse


class MLDiffuserLight(MLLightBase):
    """
    light entity for Meross diffuser (MOD100)
    """

    namespace = mc.NS_APPLIANCE_CONTROL_DIFFUSER_LIGHT

    # HA core entity attributes:
    supported_color_modes = {ColorMode.RGB}

    def __init__(self, manager: "MerossDevice", payload: dict):
        super().__init__(manager, payload, mc.DIFFUSER_LIGHT_MODE_LIST)

    async def async_turn_on(self, **kwargs):
        if not kwargs:
            await self.async_request_onoff(1)
            return

        light = dict(self._light)
        light[mc.KEY_ONOFF] = 1

        if ATTR_RGB_COLOR in kwargs:
            light[mc.KEY_RGB] = _rgb_to_int(kwargs[ATTR_RGB_COLOR])
            light[mc.KEY_MODE] = mc.DIFFUSER_LIGHT_MODE_COLOR

        # Brightness must always be set in payload
        if ATTR_BRIGHTNESS in kwargs:
            light[mc.KEY_LUMINANCE] = _sat_1_100(kwargs[ATTR_BRIGHTNESS] * 100 // 255)
        elif not light.get(mc.KEY_LUMINANCE, 0):
            light[mc.KEY_LUMINANCE] = 100

        if ATTR_EFFECT in kwargs:
            light[mc.KEY_MODE] = self.effect_list.index(kwargs[ATTR_EFFECT])  # type: ignore

        if await self.manager.async_request_ack(
            self.namespace,
            mc.METHOD_SET,
            {self.key_namespace: [light]},
        ):
            self._parse_light(light)

    def _inherited_parse_light(self, payload: dict):
        if mc.KEY_MODE in payload:
            # taken from https://github.com/bwp91/homebridge-meross/blob/latest/lib/device/diffuser.js
            mode = payload[mc.KEY_MODE]
            if mode == mc.DIFFUSER_LIGHT_MODE_COLOR:
                self.effect = None
            else:
                try:
                    self.effect = self.effect_list[mode]  # type: ignore
                except Exception as exception:
                    self.log_exception(
                        self.WARNING, exception, "parsing light mode", timeout=86400
                    )
                    self.effect = None


class MLDiffuserSpray(MLSpray):

    SPRAY_MODE_MAP = {
        mc.DIFFUSER_SPRAY_MODE_OFF: MLSpray.OPTION_SPRAY_MODE_OFF,
        mc.DIFFUSER_SPRAY_MODE_ECO: MLSpray.OPTION_SPRAY_MODE_ECO,
        mc.DIFFUSER_SPRAY_MODE_FULL: MLSpray.OPTION_SPRAY_MODE_CONTINUOUS,
    }

    namespace = mc.NS_APPLIANCE_CONTROL_DIFFUSER_SPRAY

    # interface: MLSpray
    async def async_request_spray_ack(self, payload: dict):
        return await self.manager.async_request_ack(
            self.namespace,
            mc.METHOD_SET,
            {self.key_namespace: [payload]},
        )
