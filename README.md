# BeoPlay: Bang & Olufsen Speakers and TVs in Home Assistant

This component enables integration with B&O equipment and Home Assistant. 

## Installation

Installation for the moment is in the custom_components.

Configuration is very simple, either using Config Flow, or you can try to config using Configuration.yaml

```
beoplay:
    host: 192.168.xx.xx
```

Currently this is heavily under development so YMMV

It should show up as something like this:



## Services

The integration is a Media Player so responds to all Media Player commands

It also exposes 2 services:

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
