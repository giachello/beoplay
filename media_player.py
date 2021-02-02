"""
Support for Bang & Olufsen speakers
"""
import asyncio
from asyncio import CancelledError
import logging
from datetime import timedelta

import aiohttp
from aiohttp.client_exceptions import ClientError
from aiohttp.hdrs import CONNECTION, KEEP_ALIVE
import async_timeout
import voluptuous as vol

import json

import pybeoplay as beoplay

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, HomeAssistantType, ServiceDataType
from homeassistant.components.media_player import MediaPlayerEntity, PLATFORM_SCHEMA
from homeassistant.components.media_player.const import (
    DOMAIN,
    MEDIA_TYPE_MUSIC,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
    SUPPORT_STOP,
    SUPPORT_PLAY,
    SUPPORT_SELECT_SOURCE,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_NAME,
    CONF_API_VERSION,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNKNOWN,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import callback
from homeassistant.helpers.script import Script
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import Throttle

REQUIREMENTS = ["pybeoplay"]

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(
    seconds=10
)  # need this to check on the power state, that doesnt come in the stream of notifications

CHECK_TIMEOUT = 10

SUPPORT_BEOPLAY = (
    SUPPORT_PAUSE
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_PREVIOUS_TRACK
    | SUPPORT_NEXT_TRACK
    | SUPPORT_PLAY_MEDIA
    | SUPPORT_STOP
    | SUPPORT_PLAY
    | SUPPORT_SELECT_SOURCE
)

# DEFAULT_DEVICE = 'default'
# DEFAULT_HOST = '127.0.0.1'
# DEFAULT_NAME = 'BeoPlay'

# PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
#     vol.Required(CONF_HOST, default=DEFAULT_HOST): cv.string,
#     vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
# })

DATA_BEOPLAY = "beoplay_media_player"

BEOPLAY_EXPERIENCE_JOIN_SERVICE = "beoplay_join_experience"
BEOPLAY_EXPERIENCE_LEAVE_SERVICE = "beoplay_leave_experience"

EXPERIENCE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

__hass: HomeAssistantType


class BeoPlayData:
    """Storage class for platform global data."""

    def __init__(self):
        self.entities = []


def _add_player(hass, async_add_devices, host):
    """Add speakers."""

    @callback
    def _start_polling(event=None):
        """Start polling."""
        speaker.start_polling()

    @callback
    def _stop_polling():
        """Stop polling."""
        speaker.stop_polling()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_polling)

    beoplayapi = beoplay.BeoPlay(host)
    speaker = BeoPlay(hass, beoplayapi)
    async_add_devices([speaker], True)
    #        async_add_entities(sensors, update_before_add=True)

    _LOGGER.info("Added device with name: %s", speaker._name)

    if hass.is_running:
        _start_polling()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _start_polling)


def join_experience(service: ServiceDataType):
    """Join to an existing experience"""
    _LOGGER.debug("Join experience service called")

    entity_ids = service.data.get("entity_id")
    entities = __hass.data[DATA_BEOPLAY].entities

    if entity_ids:
        entities = [e for e in entities if e.entity_id in entity_ids]

    for entity in entities:
        entity.join_experience()


def leave_experience(service: ServiceDataType):
    """Leave an existing experience"""
    _LOGGER.debug("Leave experience service called")

    entity_ids = service.data.get("entity_id")
    entities = __hass.data[DATA_BEOPLAY].entities

    if entity_ids:
        entities = [e for e in entities if e.entity_id in entity_ids]

    for entity in entities:
        entity.leave_experience()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
):
    """Setup sensors from a config entry created in the integrations UI."""
    # this is only needed if there is a global API object but we don't have one. we have individual api objects for each device.
    # config = hass.data[DOMAIN][config_entry.entry_id]
    # session = async_get_clientsession(hass)

    host = config_entry.data[CONF_HOST]

    if DATA_BEOPLAY not in hass.data:
        hass.data[DATA_BEOPLAY] = BeoPlayData()

    __hass = hass

    hass.services.async_register(
        DOMAIN,
        BEOPLAY_EXPERIENCE_JOIN_SERVICE,
        join_experience,
        schema=EXPERIENCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        BEOPLAY_EXPERIENCE_LEAVE_SERVICE,
        leave_experience,
        schema=EXPERIENCE_SCHEMA,
    )

    _add_player(hass, async_add_entities, host)


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the BeoPlay platform."""

    host = config.get(CONF_HOST)

    if DATA_BEOPLAY not in hass.data:
        hass.data[DATA_BEOPLAY] = BeoPlayData()

    hass.services.async_register(
        DOMAIN,
        BEOPLAY_EXPERIENCE_JOIN_SERVICE,
        join_experience,
        schema=EXPERIENCE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        BEOPLAY_EXPERIENCE_LEAVE_SERVICE,
        leave_experience,
        schema=EXPERIENCE_SCHEMA,
    )

    _add_player(hass, async_add_devices, host)


class BeoPlay(MediaPlayerEntity):
    """Representation of a BeoPlay speaker"""

    def __init__(self, hass, speaker):
        self._hass = hass
        self._polling_session = async_get_clientsession(hass)
        self._polling_task = None  # The actual polling task.
        self._firstRun = True

        self._speaker = speaker
        self._state = self._speaker.state
        self._min_volume = self._speaker.min_volume
        self._max_voume = self._speaker.max_volume
        self._volume = self._speaker.volume
        self._muted = self._speaker.muted
        self._source = self._speaker.source
        self._sources = self._speaker.sources
        self._media_url = self._speaker.media_url
        self._media_album = self._speaker.media_album
        self._media_track = self._speaker.media_track
        self._media_artist = self._speaker.media_artist
        self._connfail = 0
        self._serialNumber = ""
        self._name = ""
        self._model = ""
        self._on = self._speaker.on

    async def async_added_to_hass(self):
        self.hass.data[DATA_BEOPLAY].entities.append(self)

    class _TimeoutException(Exception):
        pass

    async def _start_poll_command(self):
        """Loop which polls the status of the speaker."""
        try:
            while True:
                await self.async_update_status()

        except (asyncio.TimeoutError, ClientError, BeoPlay._TimeoutException):
            _LOGGER.info("Node %s is offline, retrying later", self._name)
            await asyncio.sleep(CHECK_TIMEOUT, loop=self._hass.loop)
            self.start_polling()

        except CancelledError:
            _LOGGER.debug("Stopping the polling of node %s", self._name)
        except Exception:
            _LOGGER.exception("Unexpected error in %s", self._name)
            raise

    def start_polling(self):
        """Start the polling task."""
        self._polling_task = self._hass.async_add_job(self._start_poll_command())

    def stop_polling(self):
        """Stop the polling task."""
        self._polling_task.cancel()

    async def async_update_status(self):
        """Long polling task"""

        try:
            response = await self._polling_session.request(
                "get", self._speaker._host_notifications
            )

            if response.status == 200:
                while True:
                    data = await response.content.readline()
                    if not data:
                        break
                    data = data.decode("utf-8").replace("\r", "").replace("\n", "")
                    if data:
                        _LOGGER.info("Update status: " + self._name + data)

                        data_json = json.loads(data)
                        ############################################################
                        # functions are coming here that update the properties
                        ############################################################
                        # get volume
                        self._speaker.getVolume(data_json)
                        # get source
                        self._speaker.getSource(data_json)
                        # get state
                        self._speaker.getState(data_json)
                        # get currently playing music info
                        self._speaker.getMusicInfo(data_json)

                        self._volume = self._speaker.volume
                        self._muted = self._speaker.muted
                        self._state = self._speaker.state
                        self._source = self._speaker.source
                        self._media_url = self._speaker.media_url
                        self._media_album = self._speaker.media_album
                        self._media_track = self._speaker.media_track
                        self._media_artist = self._speaker.media_artist

                self.async_schedule_update_ha_state()

            else:
                _LOGGER.error(
                    "Error %s on %s. Trying one more time",
                    response.status,
                    self._speaker._host_notifications,
                )

        except (asyncio.TimeoutError, ClientError):
            self.async_schedule_update_ha_state()
            _LOGGER.info("Client connection error, marking %s as offline", self._name)
            raise

    # ========== Properties ==========

    @property
    def name(self):
        """Return the device name."""
        return self._name

    @property
    def should_poll(self):
        """Device should be polled."""
        # using this polling for the power state
        return True

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_BEOPLAY

    @property
    def state(self):
        """Get the device state."""
        if self._on == False:
            return STATE_OFF
        if self._state is None:
            return None
        else:
            if self._state == "play":
                return STATE_PLAYING
            if self._state == "pause":
                return STATE_PAUSED
            if self._state == "stop":
                return STATE_PAUSED

    @property
    def source(self):
        """Return the current input source."""
        return self._source

    @property
    def source_list(self):
        """List of available input sources."""
        return self._sources if self._sources else None

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_MUSIC

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        if self._source == "AirPlay":
            return None
        return self._media_url if self._media_url else None

    @property
    def media_title(self):
        """Title of current playing media."""
        if self._source == "Google Cast":
            return self._media_album
        # return self._speaker.source if self._speaker.source else None
        return self._media_track if self._media_track else None

    @property
    def media_track(self):
        """Track number of current playing media (Music track only)."""
        return self._media_track if self._media_track else None

    @property
    def media_artist(self):
        """Artist of current playing media (Music track only)."""
        return self._media_artist if self._media_artist else None

    @property
    def media_album(self):
        """Album of current playing media (Music track only)."""
        return self._media_album if self._media_album else None

    @property
    def app_name(self):
        """Name of the current running app."""
        return self._source if self._source else None

    # ========== Service Calls ==========

    def turn_on(self):
        """Turn on the device."""
        self._speaker.turnOn()

    def turn_off(self):
        """Turn off the device."""
        self._speaker.Standby()

    def media_play(self):
        """Play the current music"""
        self._speaker.Play()

    def media_pause(self):
        """Pause the current music"""
        self._speaker.Pause()

    def media_stop(self):
        """Send stop command."""
        self._speaker.Stop()

    def media_previous_track(self):
        """Send previous track command."""
        self._speaker.Prev()

    def media_next_track(self):
        """Send next track command."""
        self._speaker.Next()

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        self._speaker.setVolume(volume)

    def mute_volume(self, mute):
        """Send mute command"""
        if self._muted:
            self._speaker.setMute(False)
            self._muted = False
        else:
            self._speaker.setMute(True)
            self._muted = True

    def select_source(self, source):
        """Select input source."""
        self._speaker.setSource(source)

    def join_experience(self):
        """Join on ongoing experience"""
        self._speaker.joinExperience()

    def leave_experience(self):
        """Leave experience"""
        self._speaker.leaveExperience()

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data and update device state."""
        # _LOGGER.debug("Updating")
        self._speaker.getStandby()
        if self._on != self._speaker.on:
            self._on = self._speaker.on
            # _LOGGER.debug("Updating ON state: %s", self._on)
        if self._firstRun:
            self._speaker.getSources()
            self._sources = self._speaker.sources
            ## get the information about the device
            r = self._speaker._getReq("BeoDevice")
            if r:
                self._serialNumber = r["beoDevice"]["productId"]["serialNumber"]
                self._name = r["beoDevice"]["productFriendlyName"][
                    "productFriendlyName"
                ]
                self._model = r["beoDevice"]["productId"]["typeNumber"]
            self._firstRun = False
