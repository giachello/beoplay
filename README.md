# BeoPlay: Bang & Olufsen Speakers and TVs in Home Assistant

This component enables integration with B&O equipment and Home Assistant. 

## Installation

Installation for the moment is in the custom_components.

Configuration is very simple, go to Configuration -> Integrations -> Add Integration (bottom right corner), search for BeoPlay and insert the host name or IP.

It should work with both TVs and Speakers.

At the moment we only support one device at the time. More improvements coming!

Currently this is heavily under development so YMMV

It should show up as something like this:

![beoplay_mini_media_player.png](./beoplay_mini_media_player.png)

## Services

The integration is a Media Player so responds to all Media Player commands

It also exposes 2 additional services:

```
beoplay_join_experience:
  description: "Join Experience."
  fields:
    entity_id:
      description: "A media player Entity ID."
      example: "media_player.my_chromecast"
beoplay_leave_experience:
  description: "Leave Experience."
  fields:
    entity_id:
      description: "A media player Entity ID."
      example: "media_player.my_chromecast"
```
