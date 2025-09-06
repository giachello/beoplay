"""Config flow for BeoPlay for Bang & Olufsen."""
import ipaddress
import logging
import re

from aiohttp import ClientError
import pybeoplay as beoplay
import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import BEOPLAY_TRACK, BEOPLAY_TYPES, CONF_TYPE, DOMAIN

_LOGGER = logging.getLogger(__name__)


USER_STEP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=""): str,
        vol.Optional(CONF_TYPE, default=BEOPLAY_TRACK): vol.In(BEOPLAY_TYPES),
    }
)

ZERO_CONF_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TYPE, default=BEOPLAY_TRACK): vol.In(BEOPLAY_TYPES),
    }
)


def host_valid(host):
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version in (4, 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


class BeoPlayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BeoPlay device."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize."""
        self.beoplayapi = None
        self.host = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        _LOGGER.debug("Async Step User Config Flow called")

        if user_input is not None:
            try:
                if not host_valid(user_input[CONF_HOST]):
                    raise InvalidHost()

                self.beoplayapi = beoplay.BeoPlay(
                    user_input[CONF_HOST], async_get_clientsession(self.hass)
                )

                await self.beoplayapi.async_get_device_info()
                title = f"{self.beoplayapi.name}"

                await self.async_set_unique_id(self.beoplayapi.serialNumber)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=title, data=user_input)
            except InvalidHost:
                errors[CONF_HOST] = "wrong_host"
            except (ConnectionError, ConnectionRefusedError, ClientError):
                errors["base"] = "cannot_connect"
            except AbortFlow:
                return self.async_abort(reason="single_instance_allowed")

        return self.async_show_form(
            step_id="user", data_schema=USER_STEP_DATA_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(self, discovery_info):
        """Handle zeroconf discovery."""
        _LOGGER.debug("Async_Step_Zeroconf start")
        if discovery_info is None:
            return self.async_abort(reason="cannot_connect")
        _LOGGER.debug("Async_Step_Zeroconf discovery info %s ", discovery_info)

        # Check if BeoVision and BeoSound speakers, or BLC device (NL/ML Converter).
        # not sure this is actually necessary, since we already check
        # for _beoremote zeroconf type.
        if not discovery_info.name or not (
            discovery_info.name.startswith("Beo")
            or discovery_info.name.startswith("BLC")
        ):
            return self.async_abort(reason="not_beoplay_device")

        # Hostname is format: BLC-xxxxx.local.
        self.host = discovery_info.hostname.rstrip(".")
        _LOGGER.debug("Async_Step_Zeroconf Hostname %s", self.host)

        self.beoplayapi = beoplay.BeoPlay(self.host, async_get_clientsession(self.hass))
        if self.beoplayapi is None:
            _LOGGER.debug("Could not create BeoPlay API for %s", str(self.host))
            return self.async_abort(reason="cannot_connect")
        
        try:
            await self.beoplayapi.async_get_device_info()
        except ClientError:
            _LOGGER.debug(
                "Could not connect with %s as %s",
                self.beoplayapi.name,
                str(self.host),
            )
            return self.async_abort(reason="cannot_connect")
        except TimeoutError:
            _LOGGER.debug(
                "Timeout connecting with %s as %s",
                self.beoplayapi.name,
                str(self.host),
            )
            return self.async_abort(reason="cannot_connect")

        # Check if already configured
        sn = self.beoplayapi.serialNumber
        _LOGGER.debug("Async_Step_Zeroconf Set unique Id %s", sn)

        try:
            if sn is not None:
                await self.async_set_unique_id(sn)
                for elem in self._async_current_entries():
                    _LOGGER.debug(
                        "Async_Step_Zeroconf current entries: %s", elem.unique_id
                    )
                self._abort_if_unique_id_configured()
        except AbortFlow:
            return self.async_abort(reason="single_instance_allowed")
        if sn is None:
            return self.async_abort(reason="no_serial_number")

        # pylint: disable=no-member # https://github.com/PyCQA/pylint/issues/3167
        self.context.update(
            {
                "title_placeholders": {
                    "serial_number": self.beoplayapi.serialNumber if self.beoplayapi.serialNumber else "unknown",
                    "model": self.beoplayapi.name if self.beoplayapi.name else "unknown",
                }
            }
        )
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input=None):
        """Handle a flow initiated by zeroconf."""

        if self.beoplayapi is None:
            return self.async_abort(reason="cannot_connect")
        _sn : str = self.beoplayapi.serialNumber if self.beoplayapi.serialNumber else "unknown"
        _tn : str = self.beoplayapi.typeNumber if self.beoplayapi.typeNumber else "unknown"
        _name : str = self.beoplayapi.name if self.beoplayapi.name else "unknown"
        _LOGGER.debug("zeroconf_confirm: %s", _name)

        if user_input is not None:
            title = f"{_name}"
            # pylint: disable=no-member # https://github.com/PyCQA/pylint/issues/3167
            return self.async_create_entry(
                title=title,
                data={CONF_HOST: self.host, CONF_TYPE: user_input[CONF_TYPE]},
            )

        _LOGGER.debug("zeroconf_confirm calling show form: %s", _name)

        return self.async_show_form(
            step_id="zeroconf_confirm",
            data_schema=ZERO_CONF_DATA_SCHEMA,
            description_placeholders={
                "serial_number": _sn,
                "model": _tn,
                "name": _name,
            },
        )


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate that hostname/IP address is invalid."""
