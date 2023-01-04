# BeoPlay: Bang & Olufsen Speakers and TVs in Home Assistant

This component enables integration of B&O Audio/Video equipment with Home Assistant and specifically TVs, Speakers and units like the BeoLink Converter ML/NL. 

## Installation via HACS
The preferred type of installation is via HACS. In this way, you'll get updates when there are new versions.

### Manual Installation

You can also install it manually in custom_components. Just copy the full contents of the `custom_components/beoplay` folder into the `config/custom_components/beoplay` folder in your Home Assistant system (You'll need to create the beoplay folder). If you are installing over a previous version, delete all the contents and start fresh. Then, restart Home Assistant.

## Configuration

Configuration is very simple, go to Configuration -> Integrations -> Add Integration (bottom right corner), search for BeoPlay and insert the host name or IP. It should work with both TVs, Speakers and other devices like NL/ML converters.

The component also works with Zeroconf, so B&amp;O devices should automaticlly show up in your discovery panel (Configuration->Integrations)

It should show up as something like this:

![beoplay_mini_media_player.png](./beoplay_mini_media_player.png)

## Services

The integration is a Media Player so responds to all Media Player commands.

It also exposes 3 additional services:

```
beoplay_join_experience:
```
This command joins the speaker to the current primary experience.

```
beoplay_leave_experience:
```
This command makes the speaker quit the current primary experience.

```
beoplay_add_media_to_queue:
```
This command is experimental. It allows to add a URL of a DLNA asset on your network to the speaker and play it. Let me know if it works for you!

You can use them to have the speaker join and leave an existing play experience, just like pressing the 'Join' button on the remote. A source must be playing already for Join to work.

These are called through service calls, e.g.:

![image](https://user-images.githubusercontent.com/60585229/145609296-2080a73b-001b-4be8-8eec-27787f49be08.png)


## Events

Beoplay also generates events (`beoplay_notification`) where you can track status changes of the speaker. You can use this to enable all kinds of cool experiences (e.g., catch buttons like `A.MEM` to control automations on the Home Assistant like starting a streaming player)

<img width="739" alt="image" src="https://user-images.githubusercontent.com/60585229/145608754-8107acb5-fb85-447a-87bd-3f3804e5e3ed.png">
