"""Support for Bang & Olufsen BeoPlay speakers for Home Assistant.

This file provides a Media Player interface to Bang & Olufsen devices using the BeoPlay interface.

Key features:
* Most Media Player functionality, including media information, sound modes, ...
* Completely async implementation
* Smart retry in case device is turned off
* Forwarding of Notifications from the device to Home Assistant Events

"""

import asyncio
from asyncio import CancelledError
from datetime import timedelta
import logging
import urllib.parse

from aiohttp import ClientError
import pybeoplay
import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaType,
    RepeatMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ID,
    CONF_URL,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback

# from homeassistant.helpers.script import Script
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.helpers.typing import ServiceDataType

# from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import Throttle

from .const import (
    BEOPLAY_CHANNEL,
    BEOPLAY_NOTIFICATION,
    CONF_BEOPLAY_API,
    CONF_TYPE,
    DOMAIN,
)

REQUIREMENTS = ["pybeoplay"]

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(
    seconds=20
)  # need this to check on the power state, that doesnt come in the stream of notifications

CHECK_TIMEOUT = 5

SUPPORT_BEOPLAY = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    | MediaPlayerEntityFeature.GROUPING
)

DATA_BEOPLAY = "beoplay_media_player"

BEOPLAY_EXPERIENCE_JOIN_SERVICE = "beoplay_join_experience"
BEOPLAY_EXPERIENCE_LEAVE_SERVICE = "beoplay_leave_experience"
BEOPLAY_ADD_MEDIA_SERVICE = "beoplay_add_media_to_queue"
BEOPLAY_SET_STAND_POSITION = "beoplay_set_stand_position"

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

SET_STAND_POSITION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(CONF_ID): cv.string,
    }
)

BEOPLAY_POLL_TASK = "BeoPlay Poll Task"

ENTITY_ID_FORMAT = DOMAIN + ".{}"
JID_FORMAT = "{}.{}.{}@products.bang-olufsen.com"


class BeoPlayData:
    """Storage class for platform global data. This gets filled in by entity added to hass."""

    def __init__(self) -> None:
        """Initialize the data."""
        self.entities = []


async def _add_player(
    hass: HomeAssistant, async_add_devices, api: pybeoplay.BeoPlay, type
):
    """Add speakers."""

    # the callbacks for the services
    def join_experience(service: ServiceDataType):
        """Join to an existing experience."""
        _LOGGER.debug("Join experience service called")
        entity_ids = service.data.get("entity_id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.join_experience()

    def leave_experience(service: ServiceDataType):
        """Leave an existing experience."""
        _LOGGER.debug("Leave experience service called")
        entity_ids = service.data.get("entity_id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.leave_experience()

    def add_media(service: ServiceDataType):
        """Leave an existing experience."""
        _LOGGER.debug("Add Media to Queue service called")
        entity_ids = service.data.get("entity_id")
        url = service.data.get("url")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.add_media(url)

    def set_stand_positions(service: ServiceDataType):
        """Join to an existing experience."""
        _LOGGER.debug("Get Positions service called")
        entity_ids = service.data.get("entity_id")
        id = service.data.get("id")
        entities = hass.data[DATA_BEOPLAY].entities

        if entity_ids:
            entities = [e for e in entities if e.entity_id in entity_ids]
        for entity in entities:
            entity.set_stand_position(id)

    # the callbacks for starting / stopping the polling (Notifications) task
    @callback
    def _start_polling(event=None):
        """Start polling."""
        speaker.start_polling()

    @callback
    def _stop_polling(event=None):
        """Stop polling."""
        speaker.stop_polling()

    # Register the service callbacks
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

    hass.services.async_register(
        DOMAIN,
        BEOPLAY_SET_STAND_POSITION,
        set_stand_positions,
        schema=SET_STAND_POSITION_SCHEMA,
    )

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_polling)

    speaker = BeoPlay(hass, api, type)
    await speaker.async_update()
    # Only add the device if it responded with its serial number.
    # Device must be on. This avoids the creation of spurious devices.
    if speaker.unique_id == "":
        _LOGGER.warning("Could not add %s device: %s", DOMAIN, api.host)
        return None

    async_add_devices([speaker], True)
    _LOGGER.info("Added device with name: %s", speaker.name)
    if hass.is_running:
        _start_polling()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _start_polling)

    return speaker


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
):
    """Set up sensors from a config entry created in the integrations UI."""

    beoplay_api = hass.data[DOMAIN][config_entry.entry_id][CONF_BEOPLAY_API]
    conf_type = config_entry.data[CONF_TYPE]

    if DATA_BEOPLAY not in hass.data:
        hass.data[DATA_BEOPLAY] = BeoPlayData()

    await _add_player(hass, async_add_entities, beoplay_api, conf_type)


class BeoPlay(MediaPlayerEntity):
    """Representation of a BeoPlay speaker."""

    def __init__(self, hass: HomeAssistant, api: pybeoplay.BeoPlay, type) -> None:
        """Initialize the BeoPlay speaker."""
        self._hass = hass
        self._polling_task = None  # The actual polling task.
        self._first_run = True

        self._speaker = api
        self._connfail = 0

        self._serial_number = ""
        self._name = ""
        self._type_number = ""
        self._type_name = ""
        self._hw_version = ""
        self._sw_version = ""
        self._jid = ""
        self._item_number = ""
        self._unique_id = ""
        self._on = self._speaker.on
        self._state = self._speaker.state
        self._beoplay_type = type

    async def async_added_to_hass(self):
        """Register entity."""
        self.hass.data[DATA_BEOPLAY].entities.append(self)

    async def async_will_remove_from_hass(self):
        """Device is going to be removed, so stop polling the notifications."""
        self.stop_polling()
        self.hass.data[DATA_BEOPLAY].entities.remove(self)

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
        self._polling_task = self._hass.async_create_background_task(
            self._start_poll_command(), BEOPLAY_POLL_TASK
        )

    def stop_polling(self):
        """Stop the polling task."""
        self._polling_task.cancel()

    async def async_update_status(self):
        """Long polling task."""

        def notif_callback(data: dict):
            self._on = self._speaker.on
            self._state = self._speaker.state
            self.async_schedule_update_ha_state()
            # add the entity ID of the speaker to the notification so we know
            # where it's coming from
            data["entity_id"] = self.entity_id
            self._hass.add_job(self._notify_beoplay_notification, data)

        try:
            await self._speaker.async_notificationsTask(notif_callback)
        except (TimeoutError, ClientError) as _e:
            # occasionally the notifications stream is closed by the speaker/TV
            # In that case, exit and restart the polling
            # Don't update if we haven't initialized yet.
            if self.hass is not None:
                self.async_schedule_update_ha_state()
            _LOGGER.info("Client error %s on %s", str(_e), self._name)
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
        """Return the unique ID of the device."""
        return self._unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            name=self._name,
            manufacturer="Bang & Olufsen",
            identifiers={(DOMAIN, self._serial_number)},
            model=f"{self._type_number} {self._type_name}",
            hw_version=self._hw_version,
            sw_version=self._sw_version,
        )
    
    @property
    def group_members(self):
        """Return the group members."""
        entities = self.hass.data[DATA_BEOPLAY].entities
        listeners = self._speaker.listeners if hasattr(self._speaker, 'listeners') else []
        return [entity.entity_id for entity in entities if entity._jid in listeners]

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

        if self._state in ("play", "playing"):
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
    def sound_mode(self):
        """Return the current sound mode."""
        return self._speaker.soundMode if self._speaker.soundMode else None

    @property
    def sound_mode_list(self):
        """List of available sound modes."""
        return self._speaker.soundModes if self._speaker.soundModes else None

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
        return MediaType.MUSIC

    @property
    def media_image_url(self):
        """Image url of current playing media."""
        if self._speaker.media_url:
            if self._speaker.source == "AirPlay":
                media_url_params = urllib.parse.urlencode(
                    {"track": self._speaker.media_track}
                )
                return f"{self._speaker.media_url}?{media_url_params}"
            return self._speaker.media_url
        return None

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

    @property
    def extra_state_attributes(self):
        """Return the state attributes (stand positions)."""
        attributes = {}
        attributes["stand_positions"] = self._speaker.standPositions
        attributes["stand_position"] = self._speaker.standPosition
        return attributes

    # ========== Service Calls ==========

    def turn_on(self):
        """Turn on the device."""
        self._speaker.turnOn()

    def turn_off(self):
        """Turn off the device."""
        self._speaker.Standby()

    def media_play(self):
        """Play the current music."""
        self._speaker.Play()

    def media_pause(self):
        """Pause the current music."""
        self._speaker.Pause()

    def media_stop(self):
        """Send stop command."""
        self._speaker.Stop()

    def media_previous_track(self):
        """Send previous track command. Will use the type of command appropriate for the device, based on the configuration."""
        if self._beoplay_type == BEOPLAY_CHANNEL:
            self._speaker.StepDown()
        else:
            self._speaker.Backward()

    def media_next_track(self):
        """Send next track command."""
        if self._beoplay_type == BEOPLAY_CHANNEL:
            self._speaker.StepUp()
        else:
            self._speaker.Forward()

    def set_shuffle(self, shuffle: bool) -> None:
        """Send previous track command."""
        self._speaker.Shuffle()

    def set_repeat(self, repeat: RepeatMode) -> None:
        """Send next track command."""
        self._speaker.Repeat()

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        self._speaker.setVolume(volume)

    def mute_volume(self, mute):
        """Send mute command."""
        self._speaker.setMute(mute)

    def select_sound_mode(self, sound_mode):
        """Select sound mode."""
        self._speaker.setSoundMode(sound_mode)

    def select_source(self, source):
        """Select input source."""
        self._speaker.setSource(source)

    def join_experience(self):
        """Join on ongoing experience."""
        self._speaker.joinExperience()

    def join_players(self, group_members):
        """Join `group_members` as a player group with the current player."""
        entities = self.hass.data[DATA_BEOPLAY].entities

        entities = [e for e in entities if e.entity_id in group_members]
        for entity in entities:
            entity.join_experience()

    def leave_experience(self):
        """Leave experience."""
        self._speaker.leaveExperience()

    def unjoin_player(self):
        """Unjoin the current player from the experience."""
        self._speaker.leaveExperience()

    def add_media(self, url):
        """Leave experience."""
        item = {
            "playQueueItem": {"behaviour": "impulsive", "track": {"dlna": {"url": url}}}
        }
        self._speaker.playQueueItem(False, item)

    def set_stand_position(self, id):
        """Set the stand position."""
        self._speaker.setStandPosition(id)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Get the latest data and update device state."""
        # _LOGGER.debug("Updating")

        if self._first_run:
            try:
                await self._speaker.async_get_device_info()
                self._serial_number = self._speaker.serialNumber
                self._name = self._speaker.name
                self._type_number = self._speaker.typeNumber
                self._item_number = self._speaker.itemNumber
                self._type_name = self._speaker.typeName
                self._hw_version = self._speaker.hardwareVersion
                self._sw_version = self._speaker.softwareVersion
                self._jid = JID_FORMAT.format(
                    self._speaker.typeNumber,
                    self._speaker.itemNumber,
                    self._speaker.serialNumber
                )
                self._unique_id = f"beoplay-{self._serial_number}-media_player"
                self.entity_id = generate_entity_id(
                    ENTITY_ID_FORMAT, self._name, hass=self._hass
                )
                await self._speaker.async_get_sources()
                await self._speaker.async_get_sound_modes()
                await self._speaker.async_get_stand_positions()
                await self._speaker.async_get_stand_position()
                self._first_run = False
            except ClientError:
                _LOGGER.error(
                    "Couldn't connect with %s (maybe Wake-On-Lan / Quickstart is disabled?)",
                    self._speaker.host,
                )
                return
        try:
            await self._speaker.async_get_standby()
            if self._on != self._speaker.on:
                self._on = self._speaker.on
                _LOGGER.debug("Updating ON state: %s", self._on)
        except ClientError:
            _LOGGER.debug("Server disconnected, ignoring")
