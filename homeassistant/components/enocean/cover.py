"""Support for EnOcean switches."""

from __future__ import annotations

from typing import Any

from enocean_async import (
    EEP,
    Observable,
    Observation,
    ObservationSource,
    QueryCoverPosition,
    SetCoverPosition,
    StopCover,
)
import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SENDER_ID
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EnOcean switch platform."""
    entities = []
    for subentry in config_entry.subentries.values():
        if subentry.data["type"] == "cover":
            device_id: list[int] = subentry.data[CONF_ID]
            dev_name: str = subentry.data[CONF_NAME]
            sender_id: list[int] = subentry.data[CONF_SENDER_ID]
            entities.append(EnOceanCover(device_id, dev_name, sender_id))

    async_add_entities(entities)


class EnOceanCover(EnOceanEntity, CoverEntity):
    """Representation of an EnOcean Cover device."""

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        return self._attr_current_cover_position == 0

    def __init__(
        self, device_id: list[int], dev_name: str, sender_id: list[int]
    ) -> None:
        """Initialize the EnOcean switch device."""
        super().__init__(device_id, EEP(0xD2, 0x05, 0x00), sender_id)

        self._attr_unique_id = generate_unique_id(device_id)
        self._attr_name = dev_name
        self._attr_is_closed = None
        self.requested_position: int | None = None
        self._attr_current_cover_position = None

        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.STOP
        )

    def added_to_gateway(self) -> None:
        """Handle being added to the gateway."""
        self.send_command(QueryCoverPosition())

    def _set_position(self, percentage: int):
        """Set the cover to a specific position."""

        self.requested_position = percentage

        # If we have a current position and a requested position, we can derive
        # the cover state (opening/closing) to provide better feedback in the
        # UI.
        if (
            self._attr_current_cover_position is not None
            and self.requested_position is not None
        ):
            current_position = 100 - self._attr_current_cover_position
            if current_position < self.requested_position:
                self._attr_is_closing = True
                self._attr_is_opening = False
            elif current_position > self.requested_position:
                self._attr_is_closing = False
                self._attr_is_opening = True
            self.schedule_update_ha_state()

        self.send_command(SetCoverPosition(position=percentage))

    def open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self._set_position(0)

    def close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._set_position(100)

    def stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        self._attr_is_closing = False
        self._attr_is_opening = False
        self.schedule_update_ha_state()
        self.send_command(StopCover())

    def set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover to a specific position."""
        position = kwargs.get("position")
        if position is not None:
            self._set_position(100 - position)

    def observation_received(self, observation: Observation):
        """Update the internal state of the cover based on an observation."""
        schedule_update = False

        if Observable.POSITION in observation.values:
            percent = observation.values[Observable.POSITION]
            self._attr_current_cover_position = 100 - percent
            schedule_update = True

        if Observable.COVER_STATE in observation.values and (
            not self.requested_position or observation.source == ObservationSource.TIMER
        ):
            # If we don't have a requested position, use cover state from the
            # message
            #
            # Currently, when the cover starts moving, we receive a stopped
            # state, followed by an opening/closing state, which causes the UI
            # to briefly show "stopped" before updating to the correct state. To
            # work around this, we prioritize the cover state from the message
            # only if we don't have a requested position.
            #
            # Only exception is if the observation source is a timer (from the
            # watchdog), in which case the cover stopped from external control
            # (eg. physical switch, obstacle).
            self.requested_position = None

            state = observation.values[Observable.COVER_STATE]
            if state == "closed":
                self._attr_is_closed = True
            else:
                self._attr_is_closed = False

            if state == "opening":
                self._attr_is_opening = True
                self._attr_is_closing = False
            elif state == "closing":
                self._attr_is_opening = False
                self._attr_is_closing = True
            else:
                self._attr_is_opening = False
                self._attr_is_closing = False

            schedule_update = True
        elif self._attr_current_cover_position is not None:
            # Assume movement has stopped if we receive a position matching the
            # requested position
            current_position = 100 - self._attr_current_cover_position

            if current_position == self.requested_position:
                self.requested_position = None
                self._attr_is_closing = False
                self._attr_is_opening = False

            schedule_update = True

        if schedule_update:
            self.schedule_update_ha_state()
