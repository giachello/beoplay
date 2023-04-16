"""The BeoPlay for Bang & Olufsen integration."""
import asyncio

import voluptuous as vol
import pybeoplay
from aiohttp import ClientConnectorError, ClientError

from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN, CONF_BEOPLAY_API

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

# List the platforms that you want to support. BeoPlay supports both a media player and a remote
PLATFORMS = ["media_player", "remote"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the BeoPlay for Bang & Olufsen component.
    BeoPlay component cannot be set up using configuration.yaml"""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up BeoPlay for Bang & Olufsen from a config entry."""

    # this is the connection manager with the actual speaker/TV
    polling_session = async_get_clientsession(hass)
    host = entry.data[CONF_HOST]
    api = pybeoplay.BeoPlay(host, polling_session)
    try:
        await api.async_get_device_info()
    except (ClientError, ClientConnectorError) as ex:
        raise ConfigEntryNotReady(
            f"Cannot connect to {host}, is it in power saving mode?"
        ) from ex

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    hass.data[DOMAIN][entry.entry_id] = {CONF_BEOPLAY_API: api, CONF_HOST: host}

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
