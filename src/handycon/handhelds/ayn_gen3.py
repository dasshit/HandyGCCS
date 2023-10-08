#!/usr/bin/env python3
"""
HandyGCCS HandyCon
Copyright 2022 Derek J. Clark <derekjohn dot clark at gmail dot com>
This will create a virtual UInput device and pull data from the built-in
controller and "keyboard". Right side buttons are keyboard buttons that
send macros (i.e. CTRL/ALT/DEL). We capture those events and send button
presses that Steam understands.
"""
from types import MethodType
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.handycon.event_emitter import EventEmitter

from evdev import ecodes as e, InputEvent


def init_handheld(handycon: "EventEmitter"):
    """
    Captures keyboard events and translates them to virtual device events.
    :param handycon:
    :return:
    """
    handycon.system_type = "AYN_GEN3"
    handycon.process_event = MethodType(process_event, handycon)
    handycon.BUTTON_DELAY = 0.11
    handycon.CAPTURE_CONTROLLER = True
    handycon.CAPTURE_KEYBOARD = True
    handycon.CAPTURE_POWER = True
    handycon.GAMEPAD_ADDRESS = 'usb-0000:04:00.4-2/input0'
    handycon.GAMEPAD_NAME = 'Microsoft X-Box 360 pad'
    handycon.KEYBOARD_ADDRESS = 'isa0060/serio0/input0'
    handycon.KEYBOARD_NAME = 'AT Translated Set 2 keyboard'


async def process_event(
        handycon: "EventEmitter",
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

    ## Loop variables
    button_on = seed_event.value

    # Automatically pass default keycodes we dont intend to replace.
    if seed_event.code in [e.KEY_VOLUMEDOWN, e.KEY_VOLUMEUP]:
        handycon.emit_event(seed_event)

    # BUTTON 1 (Default: Screenshot) Front lower-left + front lower-right
    if active_keys == [111] \
            and button_on == 1 \
            and button1 not in handycon.event_queue:
        await handycon.handle_key_down(seed_event, button1)
    elif active_keys == [] \
            and seed_event.code in [111] \
            and button_on == 0 \
            and button1 in handycon.event_queue:
        await handycon.handle_key_up(seed_event, button1)

    # BUTTON 2 (Default: QAM) Front lower-right
    if active_keys == [20, 29, 42, 56] \
            and button_on == 1 \
            and button2 not in handycon.event_queue:
        await handycon.handle_key_down(seed_event, button2)
    elif active_keys == [] \
            and seed_event.code in [20, 29, 42, 56] \
            and button_on == 0 \
            and button2 in handycon.event_queue:
        await handycon.handle_key_up(seed_event, button2)

    if handycon.last_button:
        await handycon.handle_key_up(seed_event, handycon.last_button)
