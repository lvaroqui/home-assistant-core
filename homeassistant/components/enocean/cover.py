"""Support for EnOcean switches."""

from __future__ import annotations

from typing import Any

from enocean_async import EURID, Address, BaseAddress, ERP1Telegram
from enocean_async.esp3.packet import ESP3PacketType
import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_SENDER_ID, LOGGER
from .entity import EnOceanEntity, combine_hex

DEFAULT_NAME = "EnOcean Cover"

PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


def generate_unique_id(dev_id: list[int]) -> str:
    """Generate a valid unique id."""
    return f"{combine_hex(dev_id)}"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the EnOcean switch platform."""
    sender_id: list[int] = config[CONF_SENDER_ID]
    dev_id: list[int] = config[CONF_ID]
    dev_name: str = config[CONF_NAME]

    async_add_entities([EnOceanCover(dev_id, dev_name, sender_id)])


class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean switch device."""

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        return self._attr_current_cover_position == 0

    def __init__(self, dev_id: list[int], dev_name: str, sender_id: list[int]) -> None:
        """Initialize the EnOcean switch device."""
        super().__init__(dev_id)

        try:
            if len(sender_id) == 0:
                # Default sender ID if not provided (will use) the dongle's ID
                sender_id = [0x00, 0x00, 0x00, 0x00]
            sender_id_addr = Address.from_bytelist(sender_id)
            if sender_id_addr.is_eurid():
                self.sender_id = EURID.from_number(sender_id_addr.to_number())
            elif sender_id_addr.is_base_address():
                self.sender_id = BaseAddress.from_number(sender_id_addr.to_number())
        except ValueError:
            LOGGER.warning("Invalid sender_id provided, sender_id will be None")
            self.sender_id = None

        self._attr_unique_id = generate_unique_id(dev_id)
        self._attr_name = dev_name
        self._attr_is_closed = None

        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.STOP
        )

    def _send_telegram(self, payload: list[int]):
        """Send a telegram to set the cover position."""
        if not self.address or not self.sender_id:
            LOGGER.warning("Cannot send telegram, address or sender_id is None")
            return

        optional = [0x03]
        optional.extend(self.address.to_bytelist())
        optional.extend([0xFF, 0x00])

        data = [0xD2]
        data.extend(payload)
        data.extend(self.sender_id.to_bytelist())
        data.append(0x00)

        self.send_command(
            data=data,
            optional=optional,
            packet_type=ESP3PacketType(0x01),
        )

    def _set_position(self, percentage: int):
        """Set the cover to a specific position."""
        self._send_telegram([percentage, 0x00, 0x00, 0x01])

    def _stop(self):
        """Stop the cover."""
        self._send_telegram([0x02])

    def open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self._set_position(0)

    def close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._set_position(100)

    def stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        self._stop()

    def set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover to a specific position."""
        position = kwargs.get("position")
        if position is not None:
            self._set_position(100 - position)

    def value_changed(self, telegram: ERP1Telegram) -> None:
        """Update the internal state of the switch."""

        if telegram.rorg == 0xD2:
            percent = telegram.telegram_data[0]
            self._attr_current_cover_position = 100 - percent
            self.schedule_update_ha_state()
