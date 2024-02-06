from homeassistant import const as hac
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_RGB_COLOR,
    DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)

from custom_components.meross_lan.devices.mod100 import MLDiffuserLight
from custom_components.meross_lan.light import (
    MLDNDLightEntity,
    MLLight,
    MLLightBase,
    _int_to_rgb,
    _rgb_to_int,
)
from custom_components.meross_lan.merossclient import const as mc

from tests.entities import EntityComponentTest, EntityTestContext


class EntityTest(EntityComponentTest):

    ENTITY_TYPE = LightEntity

    DIGEST_ENTITIES = {
        mc.KEY_LIGHT: {MLLight},
        mc.KEY_DIFFUSER: {MLDiffuserLight},
    }
    NAMESPACES_ENTITIES = {
        mc.NS_APPLIANCE_SYSTEM_DNDMODE: {MLDNDLightEntity},
    }

    async def async_test_each_callback(
        self,
        context: EntityTestContext,
        entity: MLLight | MLDiffuserLight | MLDNDLightEntity,
    ):
        supported_color_modes = entity.supported_color_modes
        supported_features = entity.supported_features
        assert supported_color_modes

        if isinstance(entity, MLDNDLightEntity):
            # special light here with reduced set of features
            assert entity is entity.manager.entity_dnd
            assert supported_color_modes == {ColorMode.ONOFF}
        else:
            ability = context.ability
            # check the other specialized implementations
            if mc.NS_APPLIANCE_CONTROL_DIFFUSER_LIGHT in ability:
                assert isinstance(entity, MLDiffuserLight)
                assert supported_color_modes == {ColorMode.RGB}
                assert supported_features == LightEntityFeature.EFFECT

            if mc.NS_APPLIANCE_CONTROL_LIGHT in ability:
                assert isinstance(entity, MLLight)
                capacity = ability[mc.NS_APPLIANCE_CONTROL_LIGHT][mc.KEY_CAPACITY]
                if capacity & mc.LIGHT_CAPACITY_RGB:
                    assert ColorMode.RGB in supported_color_modes
                if capacity & mc.LIGHT_CAPACITY_TEMPERATURE:
                    assert ColorMode.COLOR_TEMP in supported_color_modes

            if mc.NS_APPLIANCE_CONTROL_LIGHT_EFFECT in ability:
                assert supported_features == LightEntityFeature.EFFECT

    async def async_test_enabled_callback(
        self,
        context: EntityTestContext,
        entity: MLLight | MLDiffuserLight | MLDNDLightEntity,
        entity_id: str,
    ):
        hass = context.hass
        call_service = hass.services.async_call
        states = hass.states
        await call_service(
            DOMAIN,
            SERVICE_TURN_OFF,
            service_data={
                "entity_id": entity_id,
            },
            blocking=True,
        )
        assert (state := states.get(entity_id))
        assert state.state == hac.STATE_OFF
        await call_service(
            DOMAIN,
            SERVICE_TURN_ON,
            service_data={
                "entity_id": entity_id,
            },
            blocking=True,
        )
        assert (state := states.get(entity_id))
        assert state.state == hac.STATE_ON

        if entity is entity.manager.entity_dnd:
            return
        assert isinstance(entity, MLLightBase)
        supported_color_modes = entity.supported_color_modes

        if ColorMode.BRIGHTNESS in supported_color_modes:
            await call_service(
                DOMAIN,
                SERVICE_TURN_ON,
                service_data={
                    ATTR_BRIGHTNESS: 1,
                    "entity_id": entity_id,
                },
                blocking=True,
            )
            assert (state := states.get(entity_id))
            assert (
                state.state == hac.STATE_ON
                and state.attributes[ATTR_BRIGHTNESS] == (255 // 100)
                and entity._light[mc.KEY_LUMINANCE] == 1
            )
            await call_service(
                DOMAIN,
                SERVICE_TURN_ON,
                service_data={
                    ATTR_BRIGHTNESS: 255,
                    "entity_id": entity_id,
                },
                blocking=True,
            )
            assert (state := states.get(entity_id))
            assert (
                state.state == hac.STATE_ON
                and state.attributes[ATTR_BRIGHTNESS] == 255
                and entity._light[mc.KEY_LUMINANCE] == 100
            )

        if ColorMode.RGB in supported_color_modes:
            rgb_tuple = (255, 0, 0)
            rgb_meross = _rgb_to_int(rgb_tuple)
            await call_service(
                DOMAIN,
                SERVICE_TURN_ON,
                service_data={
                    ATTR_RGB_COLOR: rgb_tuple,
                    "entity_id": entity_id,
                },
                blocking=True,
            )
            assert (state := states.get(entity_id))
            assert (
                state.state == hac.STATE_ON
                and state.attributes[ATTR_RGB_COLOR] == _int_to_rgb(rgb_meross)
                and entity._light[mc.KEY_RGB] == rgb_meross
            )

        if ColorMode.COLOR_TEMP in supported_color_modes:
            MIREDS_TO_MEROSS_TEMP = {
                entity.min_mireds: 100,
                entity.max_mireds: 1,
            }
            for temp_mired, temp_meross in MIREDS_TO_MEROSS_TEMP.items():
                await call_service(
                    DOMAIN,
                    SERVICE_TURN_ON,
                    service_data={
                        ATTR_COLOR_TEMP: temp_mired,
                        "entity_id": entity_id,
                    },
                    blocking=True,
                )
                assert (state := states.get(entity_id))
                assert (
                    state.state == hac.STATE_ON
                    and state.attributes[ATTR_COLOR_TEMP] == temp_mired
                    and entity._light[mc.KEY_TEMPERATURE] == temp_meross
                )

    async def async_test_disabled_callback(
        self,
        context: EntityTestContext,
        entity: MLLight | MLDiffuserLight | MLDNDLightEntity,
    ):
        await entity.async_turn_on()
        assert entity.is_on
        await entity.async_turn_off()
        assert not entity.is_on
