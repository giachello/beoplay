"""
Support for Bang & Olufsen speakers
"""
import logging
from datetime import timedelta
import voluptuous as vol

import asyncio
from asyncio import CancelledError
from aiohttp import ServerDisconnectedError
from aiohttp.client_exceptions import ClientError


import pybeoplay

from .const import (
    DOMAIN,
    BEOPLAY_NOTIFICATION,
)

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ServiceDataType
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
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
    RepeatMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_URL,
    CONF_HOST,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNKNOWN,
)
from homeassistant.core import callback

# from homeassistant.helpers.script import Script
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import Throttle

REQUIREMENTS = ["pybeoplay"]

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(
    seconds=20
)  # need this to check on the power state, that doesnt come in the stream of notifications

CHECK_TIMEOUT = 5

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

DATA_BEOPLAY = "beoplay_media_player"

BEOPLAY_EXPERIENCE_JOIN_SERVICE = "beoplay_join_experience"
BEOPLAY_EXPERIENCE_LEAVE_SERVICE = "beoplay_leave_experience"
BEOPLAY_ADD_MEDIA_SERVICE = "beoplay_add_media_to_queue"

EXPERIENCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

ADD_MEDIA_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(CONF_URL): cv.url,
    }
)


ENTITY_ID_FORMAT = DOMAIN + ".{}"


class BeoPlayData:
    """Storage class for platform global data."""

    def __init__(self):
        self.entities = []


async def _add_player(hass, async_add_devices, host):
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

    speaker = BeoPlay(hass, host)
    await speaker.async_update()
    async_add_devices([speaker], True)
    #        async_add_entities(sensors, update_before_add=True)

    _LOGGER.info("Added device with name: %s", speaker.name)

    if hass.is_running:
        _start_polling()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _start_polling)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
):
    """Setup sensors from a config entry created in the integrations UI."""
    # this is only needed if there is a global API object but we don't have one. we have individual api objects for each device.
    # config = hass.data[DOMAIN][config_entry.entry_id]
    # session = async_get_clientsession(hass)

    def join_experience(service: ServiceDataType):
        """Join to an existing experience"""
        _LOGGER.debug("Join experience service called")
        entity_ids = service.data.get("entity_id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.join_experience()

    def leave_experience(service: ServiceDataType):
        """Leave an existing experience"""
        _LOGGER.debug("Leave experience service called")
        entity_ids = service.data.get("entity_id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.leave_experience()

    def add_media(service: ServiceDataType):
        """Leave an existing experience"""
        _LOGGER.debug("Add Media to Queue service called")
        entity_ids = service.data.get("entity_id")
        url = service.data.get("url")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.add_media(url)

    host = config_entry.data[CONF_HOST]

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
    hass.services.async_register(
        DOMAIN,
        BEOPLAY_ADD_MEDIA_SERVICE,
        add_media,
        schema=ADD_MEDIA_SCHEMA,
    )
    await _add_player(hass, async_add_entities, host)


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the BeoPlay platform."""

    def join_experience(service: ServiceDataType):
        """Join to an existing experience"""
        _LOGGER.debug("Join experience service called")
        entity_ids = service.data.get("entity_id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.join_experience()

    def leave_experience(service: ServiceDataType):
        """Leave an existing experience"""
        _LOGGER.debug("Leave experience service called")
        entity_ids = service.data.get("entity_id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.leave_experience()

    def add_media(service: ServiceDataType):
        """Leave an existing experience"""
        _LOGGER.debug("Add Media to Queue service called")
        entity_ids = service.data.get("entity_id")
        url = service.data.get("url")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.add_media(url)

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
    hass.services.async_register(
        DOMAIN,
        BEOPLAY_ADD_MEDIA_SERVICE,
        add_media,
        schema=ADD_MEDIA_SCHEMA,
    )

    await _add_player(hass, async_add_devices, host)


class BeoPlay(MediaPlayerEntity):
    """Representation of a BeoPlay speaker"""

    def __init__(self, hass, host):
        self._hass: HomeAssistant = hass
        self._polling_session = async_get_clientsession(hass)
        self._polling_task = None  # The actual polling task.
        self._first_run = True

        # this is the connection manager with the actual speaker/TV
        self._speaker = pybeoplay.BeoPlay(host, self._polling_session)
        self._connfail = 0

        self._serial_number = ""
        self._name = ""
        self._type_number = ""
        self._item_number = ""
        self._unique_id = ""
        self._on = self._speaker.on
        self._state = self._speaker.state

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
            await asyncio.sleep(CHECK_TIMEOUT)
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

        def notif_callback(data: dict):
            self._on = self._speaker.on
            self._state = self._speaker.state
            self.async_schedule_update_ha_state()
            self._hass.add_job(self._notify_beoplay_notification, data)

        try:
            await self._speaker.async_notificationsTask(notif_callback)
        except (asyncio.TimeoutError, ClientError) as _e:
            # occasionally the notifications stream is closed by the speaker/TV
            # In that case, restart the polling
            self.async_schedule_update_ha_state()
            _LOGGER.info("Client error %s on %s" % (str(_e), self._name))
            raise

    # ========== Events ==============

    @callback
    def _notify_beoplay_notification(self, telegram):
        """Notify hass when an incoming ML message is received."""
        self._hass.bus.async_fire(BEOPLAY_NOTIFICATION, telegram)

    # ========== Properties ==========

    @property
    def name(self):
        """Return the device name."""
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def device_info(self):
        return DeviceInfo(
            name=self._name,
            manufacturer="Bang & Olufsen",
            via_device=(DOMAIN, self._serial_number),
            model=self._type_number,
        )

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
        if not self._on:
            return STATE_OFF
        if self._state is None:
            return None
        else:
            if self._state == "play" or self._state == "playing":
                return STATE_PLAYING
            if self._state == "pause":
                return STATE_PAUSED
            if self._state == "stop":
                return STATE_PAUSED
        if self._on:
            return STATE_ON
        return STATE_UNKNOWN

    @property
    def source(self):
        """Return the current input source."""
        return self._speaker.source if self._speaker.source else None

    @property
    def source_list(self):
        """List of available input sources."""
        return self._speaker.sources if self._speaker.sources else None

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._speaker.volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._speaker.muted

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_MUSIC

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        # if self._speaker.source == "AirPlay":
        #    return None
        return self._speaker.media_url if self._speaker.media_url else None

    @property
    def media_title(self):
        """Title of current playing media."""
        if self._speaker.source == "Google Cast":
            return self._speaker.media_album
        # return self._speaker.source if self._speaker.source else None
        return self._speaker.media_track if self._speaker.media_track else None

    @property
    def media_track(self):
        """Track number of current playing media (Music track only)."""
        return self._speaker.media_track if self._speaker.media_track else None

    @property
    def media_artist(self):
        """Artist of current playing media (Music track only)."""
        return self._speaker.media_artist if self._speaker.media_artist else None

    @property
    def media_album(self):
        """Album of current playing media (Music track only)."""
        return self._speaker.media_album if self._speaker.media_album else None

    @property
    def app_name(self):
        """Name of the current running app."""
        return self.source

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

    def set_shuffle(self, shuffle: bool) -> None:
        """Send previous track command."""
        self._speaker.Prev()

    def set_repeat(self, repeat: RepeatMode) -> None:
        """Send next track command."""
        self._speaker.Next()

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        self._speaker.setVolume(volume)

    def mute_volume(self, mute):
        """Send mute command"""
        self._speaker.setMute(mute)

    def select_source(self, source):
        """Select input source."""
        self._speaker.setSource(source)

    def join_experience(self):
        """Join on ongoing experience"""
        self._speaker.joinExperience()

    def leave_experience(self):
        """Leave experience"""
        self._speaker.leaveExperience()

    def add_media(self, url):
        """Leave experience"""
        item = {
            "playQueueItem": {"behaviour": "impulsive", "track": {"dlna": {"url": url}}}
        }
        self._speaker.playQueueItem(False, item)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Get the latest data and update device state."""
        # _LOGGER.debug("Updating")

        if self._first_run:
            await self._speaker.async_get_device_info()
            #            self._sources = self._speaker.sources
            self._serial_number = self._speaker.serialNumber
            self._name = self._speaker.name
            self._type_number = self._speaker.typeNumber
            self._item_number = self._speaker.itemNumber
            self._unique_id = f"beoplay-{self._serial_number}-media_player"
            self.entity_id = generate_entity_id(
                ENTITY_ID_FORMAT, self._serial_number, hass=self._hass
            )
            await self._speaker.async_get_sources()
            self._first_run = False
        try:
            await self._speaker.async_get_standby()
            if self._on != self._speaker.on:
                self._on = self._speaker.on
                _LOGGER.debug("Updating ON state: %s", self._on)
        except ServerDisconnectedError:
            _LOGGER.debug("Server disconnected, ignoring")
