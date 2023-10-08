#!/usr/bin/env python3
"""
This file is part of Handheld Game Console Controller System (HandyGCCS)
Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>
"""
from types import MethodType
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.handycon.device_explorer import DeviceExplorer

import os
from evdev import ecodes as e, InputEvent


def init_handheld(handycon: "DeviceExplorer"):
    """
    Captures keyboard events and translates them to virtual device events.
    :param handycon:
    :return:
    """
    handycon.process_event = MethodType(process_event, handycon)
    handycon.BUTTON_DELAY = 0.09
    handycon.CAPTURE_CONTROLLER = True
    handycon.CAPTURE_KEYBOARD = True
    handycon.CAPTURE_POWER = True
    handycon.GAMEPAD_ADDRESS = ''
    handycon.GAMEPAD_NAME = 'Microsoft X-Box 360 pad'
    handycon.KEYBOARD_ADDRESS = 'isa0060/serio0/input0'
    handycon.KEYBOARD_NAME = 'AT Translated Set 2 keyboard'
    setattr(handycon, 'process_event', process_event)
    if os.path.exists('/sys/devices/platform/oxp-platform/tt_toggle'):
        command = 'echo 1 > /sys/devices/platform/oxp-platform/tt_toggle'
        os.popen(command, buffering=1).read().strip()


async def process_event(
        handycon: "DeviceExplorer",
        seed_event: InputEvent,
        active_keys: list[int]
):
    """
    Captures keyboard events and translates them to virtual device events.
    :param handycon:
    :param seed_event:
    :param active_keys:
    :return:
    """
    # Button map shortcuts for easy reference.
    button1 = handycon.button_map["button1"]  # Default Screenshot
    button2 = handycon.button_map["button2"]  # Default QAM
    button3 = handycon.button_map["button3"]  # Default ESC
    button4 = handycon.button_map["button4"]  # Default OSK
    button5 = handycon.button_map["button5"]  # Default MODE
    button6 = handycon.button_map["button6"]  # Default Launch Chimera

    ## Loop variables
    this_button = None
    button_on = seed_event.value

    # Automatically pass default keycodes we dont intend to replace.
    if seed_event.code in [e.KEY_VOLUMEDOWN, e.KEY_VOLUMEUP]:
        handycon.emit_event(seed_event)

    # Handle missed keys. 
    if active_keys == [] and handycon.event_queue != []:
        this_button = handycon.event_queue[0]

    # BUTTON 1 Short press orange + turbo
    if active_keys == [99, 125] \
            and button_on == 1 \
            and button1 not in handycon.event_queue:
        handycon.event_queue.append(button1)
    elif active_keys == [] \
            and seed_event.code in [99, 125] \
            and button_on == 0 \
            and button1 in handycon.event_queue:
        this_button = button1

    ## BUTTON 2 (Default: QAM) Turbo Button
    if active_keys == [3, 97] \
            and button_on == 1 \
            and button2 not in handycon.event_queue:
        handycon.event_queue.append(button2)
    elif active_keys == [] \
            and seed_event.code in [3, 97] \
            and button_on == 0 \
            and button2 in handycon.event_queue:
        this_button = button2
        await handycon.do_rumble(0, 150, 1000, 0)

    # BUTTON 3 (Default: ESC) Short press orange + KB
    if active_keys == [97, 100, 111] \
            and button_on == 1 \
            and button3 not in handycon.event_queue:
        handycon.event_queue.append(button3)
    elif active_keys == [] \
            and seed_event.code in [100, 111] \
            and button_on == 0 \
            and button3 in handycon.event_queue:
        this_button = button3

    # BUTTON 4 (Default: OSK) Short press KB
    if active_keys == [24, 97, 125] \
            and button_on == 1 \
            and button4 not in handycon.event_queue:
        handycon.event_queue.append(button4)
    elif active_keys == [] \
            and seed_event.code in [24, 97, 125] \
            and button_on == 0 \
            and button4 in handycon.event_queue:
        this_button = button4

    # BUTTON 5 (Default: MODE) Short press orange
    if active_keys == [32, 125] \
            and button_on == 1 \
            and button5 not in handycon.event_queue:
        handycon.event_queue.append(button5)
    elif active_keys == [] \
            and seed_event.code in [32, 125] \
            and button_on == 0 \
            and button5 in handycon.event_queue:
        this_button = button5

    # BUTTON 6 (Default: Launch Chimera) Long press orange
    if active_keys == [34, 125] \
            and button_on == 1 \
            and button6 not in handycon.event_queue:
        handycon.event_queue.append(button6)
    elif active_keys == [] \
            and seed_event.code in [34, 125] \
            and button_on == 0 \
            and button6 in handycon.event_queue:
        this_button = button6

    # Handle L_META from power button
    elif active_keys == [] \
            and seed_event.code == 125 \
            and button_on == 0 \
            and handycon.event_queue == [] \
            and handycon.shutdown is True:
        handycon.shutdown = False

    # Create list of events to fire.
    # Handle new button presses.
    if this_button and not handycon.last_button:
        handycon.event_queue.remove(this_button)
        handycon.last_button = this_button
        await handycon.emit_now(seed_event, this_button, 1)

    # Clean up old button presses.
    elif handycon.last_button and not this_button:
        await handycon.emit_now(seed_event, handycon.last_button, 0)
        handycon.last_button = None
