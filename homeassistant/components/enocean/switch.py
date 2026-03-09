"""Support for EnOcean switches."""

from __future__ import annotations

from typing import Any

from enocean_async import (
    EEP,
    Observable,
    Observation,
    QueryActuatorStatus,
    SetSwitchOutput,
)

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ID, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_CHANNEL, CONF_SENDER_ID
from .entity import EnOceanEntity, combine_hex

DEFAULT_NAME = "EnOcean Switch"


def generate_unique_id(dev_id: list[int], channel: int) -> str:
    """Generate a valid unique id."""
    return f"{combine_hex(dev_id)}-{channel}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EnOcean switch entities."""

    entities = []
    for subentry in config_entry.subentries.values():
        if subentry.data["type"] == Platform.SWITCH:
            device_id: list[int] = subentry.data[CONF_ID]
            dev_name: str = subentry.data[CONF_NAME]
            sender_id: list[int] = subentry.data[CONF_SENDER_ID]
            channel = subentry.data[CONF_CHANNEL]
            entities.append(EnOceanSwitch(device_id, dev_name, channel, sender_id))

    async_add_entities(entities)


class EnOceanSwitch(EnOceanEntity, SwitchEntity):
    """Representation of an EnOcean switch device."""

    _attr_is_on = False

    def __init__(
        self, dev_id: list[int], dev_name: str, channel: int, sender_id: list[int]
    ) -> None:
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id, EEP(0xD2, 0x01, 0x01), sender_id)
        self.channel: int = channel

        self._attr_unique_id = generate_unique_id(dev_id, channel)
        self._attr_name = dev_name

    def added_to_gateway(self):
        """Handle being added to the gateway."""
        self.send_command(QueryActuatorStatus(entity_id=str(self.channel)))

    def _set_state(self, on: bool):
        """Send a telegram to turn the switch on or off."""
        self.send_command(
            SetSwitchOutput(output_value=100 if on else 0, entity_id=str(self.channel))
        )
        self._attr_is_on = on

    def turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        self._set_state(on=True)

    def turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        self._set_state(on=False)

    def observation_received(self, observation: Observation):
        """Update the internal state of the switch based on an observation."""
        if Observable.SWITCH_STATE in observation.values:
            if observation.entity == str(self.channel):
                self._attr_is_on = observation.values[Observable.SWITCH_STATE]
                self.schedule_update_ha_state()

    # def erp1_telegram_received(self, telegram: ERP1Telegram) -> None:
    #     """Update the internal state of the switch."""
    #     if telegram.rorg == 0xA5:
    #         # power meter telegram, turn on if > 1 watts
    #         if (eep := EEP_SPECIFICATIONS.get(EEP(0xA5, 0x12, 0x01))) is None:
    #             LOGGER.warning("EEP A5-12-01 cannot be decoded")
    #             return

    #         msg: EEPMessage = EEPHandler(eep).decode(telegram)

    #         if "DT" in msg.values and msg.values["DT"].raw == 1:
    #             # this packet reports the current value
    #             raw_val = msg.values["MR"].raw
    #             divisor = msg.values["DIV"].raw
    #             watts = raw_val / (10**divisor)
    #             if watts > 1:
    #                 self._attr_is_on = True
    #                 self.schedule_update_ha_state()
