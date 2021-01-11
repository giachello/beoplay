"""Config flow for BeoPlay for Bang & Olufsen."""
import beoplay


import ipaddress
import re


from homeassistant import config_entries, exceptions
from homeassistant.helpers import config_entry_flow
from homeassistant.const import CONF_HOST, CONF_TYPE

import voluptuous as vol

from .const import DOMAIN, BEOPLAY_TYPES

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=""): str,
        vol.Optional(CONF_TYPE, default="TV"): vol.In(BEOPLAY_TYPES),
    }
)


def host_valid(host):
    """Return True if hostname or IP address is valid."""
    try:
        if ipaddress.ip_address(host).version == (4 or 6):
            return True
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))


# async def _async_has_devices(hass) -> bool:
#     """Return if there are devices that can be discovered."""
#     # TODO Check if there are any devices that can be discovered in the network.
#     devices = await hass.async_add_executor_job(my_pypi_dependency.discover)
#     return len(devices) > 0


# config_entry_flow.register_discovery_flow(
#     DOMAIN,
#     "BeoPlay for Bang & Olufsen",
#     _async_has_devices,
#     config_entries.CONN_CLASS_UNKNOWN,
# )


class BeoPlayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BeoPlay device."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize."""
        self.beoplayapi = None
        self.host = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                if not host_valid(user_input[CONF_HOST]):
                    raise InvalidHost()

                self.beoplayapi = beoplay.BeoPlay(user_input[CONF_HOST])

                #                await self.async_set_unique_id(beoplayapi.serial.lower())
                #                self._abort_if_unique_id_configured()

                #                title = f"{brother.model} {brother.serial}"
                title = "beoplay"
                return self.async_create_entry(title=title, data=user_input)
            except InvalidHost:
                errors[CONF_HOST] = "wrong_host"
            except ConnectionError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(self, discovery_info):
        """Handle zeroconf discovery."""
        if discovery_info is None:
            return self.async_abort(reason="cannot_connect")

        if not discovery_info.get("name") or not discovery_info["name"].startswith(
            "BeoPlay"
        ):
            return self.async_abort(reason="not_beoplay_device")

        # Hostname is format: brother.local.
        self.host = discovery_info["hostname"].rstrip(".")

        self.beoplayapi = beoplay.BeoPlay(self.host)
        # try:
        #     await self.brother.async_update()
        # except (ConnectionError, SnmpError, UnsupportedModel):
        #     return self.async_abort(reason="cannot_connect")

        # Check if already configured
        # await self.async_set_unique_id(self.brother.serial.lower())
        # self._abort_if_unique_id_configured()

        # pylint: disable=no-member # https://github.com/PyCQA/pylint/issues/3167
        self.context.update(
            {
                "title_placeholders": {
                    "serial_number": "BEOPLAY DEVICE",
                    "model": "DONT KNOW",
                }
            }
        )
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input=None):
        """Handle a flow initiated by zeroconf."""
        r = self.beoplayapi._getReq("BeoDevice")
        if r:
            _serialNumber = r["beoDevice"]["productId"]["serialNumber"]
            _typeNumber = r["beoDevice"]["productId"]["typeNumber"]
            _name = r["beoDevice"]["productFriendlyName"]["productFriendlyName"]
            if user_input is not None:
                title = f"{_name} {_serialNumber}"
                # pylint: disable=no-member # https://github.com/PyCQA/pylint/issues/3167
                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: self.host, CONF_TYPE: user_input[CONF_TYPE]},
                )
            return self.async_show_form(
                step_id="zeroconf_confirm",
                data_schema=vol.Schema(
                    {vol.Optional(CONF_TYPE, default="Speaker"): vol.In(BEOPLAY_TYPES)}
                ),
                description_placeholders={
                    "serial_number": _serialNumber,
                    "model": _typeNumber,
                    "name": _name,
                },
            )


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate that hostname/IP address is invalid."""
