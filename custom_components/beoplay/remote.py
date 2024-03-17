"""Remote control support for BeoPlay devices."""
import asyncio
from collections.abc import Iterable
import logging
from typing import Any
import pybeoplay

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_BEOPLAY_API

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
ENTITY_ID_FORMAT = DOMAIN + ".{}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load BeoPlay remote based on a config entry."""
    api = hass.data[DOMAIN][config_entry.entry_id][CONF_BEOPLAY_API]
    (_, name, _, _)= await api.async_get_device_info()

    _LOGGER.info("remote async setup: %s %s", name,config_entry.unique_id)

    remote = BeoPlayRemote(hass, name, config_entry.unique_id, api)
    async_add_entities([remote])
    _LOGGER.info("Added remote with name: %s", remote.name)


class BeoPlayRemote(RemoteEntity):
    """Device that sends commands to a BeoPlay device."""

    def __init__(self, hass: HomeAssistant, name, identifier, api: pybeoplay.BeoPlay):
        """Initialize device."""
        self.api = api
        self._hass = hass
        self._attr_name = name
        self._name = name
        self.entity_id = generate_entity_id(ENTITY_ID_FORMAT, name, hass=hass )
        _LOGGER.info("Entity_id: %s", self.entity_id)

        self._attr_unique_id = identifier
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, identifier)})

    @property
    def is_api(self):
        """Return true if device api is there."""
        return self.api is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        await self.api.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        await self.api.async_standby()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send a command to one device."""
        num_repeats = kwargs[ATTR_NUM_REPEATS]
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)

        if not self.is_api:
            _LOGGER.error("Unable to send commands, not connected to %s", self.name)
            return

        for _ in range(num_repeats):
            for single_command in command:
                if single_command not in self.api.remote_commands:
                    raise ValueError("Command not found. Exiting sequence")

                _LOGGER.info("Sending command %s", single_command)
                await self.api.async_remote_command(single_command)
                await asyncio.sleep(delay)