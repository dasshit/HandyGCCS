import os
import asyncio
import logging
import subprocess
from pathlib import Path

from typing import Optional, Literal

# Partial imports
from evdev import \
    ff, \
    ecodes as e, \
    InputEvent, \
    UInput

from .brightness_controller import \
    BrightnessController
from .constants import \
    CONTROLLER_EVENTS, \
    CHIMERA_LAUNCHER_PATH, \
    FF_DELAY, \
    INSTANT_EVENTS, QUEUED_EVENTS, EVENT_BTN_A, EVENT_BTN_X

from .device_explorer import DeviceExplorer

from .notify_db import add_toast


logger = logging.getLogger('handycon')


class EventEmitter(DeviceExplorer):
    # Stores inng button presses to block spam
    event_queue: list[InputEvent] = []
    last_button: Optional[list[int]] = None
    last_x_val: int = 0
    last_y_val: int = 0

    # Performance settings
    performance_mode: Literal[
        "Max Boost", "Average Performance", "Power Saving"] = "Max Boost"

    perf_modes = {
        "Max Boost": {
            "name": "Max Boost",
            "mode": "--max-performance",
            "thermal_mode": "1"
        },
        "Average Performance": {
            "name": "Average Performance",
            "mode": "--max-performance",
            "thermal_mode": "1"
        },
        "Power Saving": {
            "name": "Power Saving",
            "mode": "--power-saving",
            "thermal_mode": "0"
        },
    }

    def __init__(self):
        DeviceExplorer.__init__(self)
        self.brightness = BrightnessController()
        self.ui_device = UInput(
            CONTROLLER_EVENTS,
            name='Handheld Controller',
            bustype=0x3,
            vendor=0x045e,
            product=0x028e,
            version=0x110
        )
        self.mode_generator = self.mode_gen()

    def mode_gen(self):
        while True:
            for key in self.perf_modes.keys():
                yield self.perf_modes[key]


    async def emit_events(self, events: list[InputEvent]):
        """
        Emits passed or generated events to the virtual controller.
        This shouldn't be called directly for custom events,
        only to pass realtime events.
        Use emit_now and the device's event_queue.
        :param events: InputEvents list
        :return:
        """

        for event in events:
            self.emit_event(event)
            # Pause between multiple events,
            # but not after the last one in the list.
            if event != events[-1]:
                await asyncio.sleep(self.BUTTON_DELAY)

    def emit_event(self, event: InputEvent):
        """
        Emit a single event. Skips some logic checks for optimization.
        :param event:
        :return:
        """
        # logger.debug(f"Emitting event: {event}")
        self.ui_device.write_event(event)
        self.ui_device.syn()

    async def emit_now(
            self,
            seed_event: InputEvent,
            event_list: list[InputEvent],
            value: int
    ):
        """
        Generates events from an event list.
        Can be called directly or when looping through
        the event queue.
        :param seed_event:
        :param event_list:
        :param value:
        :return:
        """
        # Ignore malformed requests
        if not event_list:
            logger.error(
                "emit_now received malfirmed event_list. No action"
            )
            return

        # Handle string events
        if isinstance(event_list[0], str):
            if value == 0:
                logger.debug(
                    "Received string event with value 0. "
                    "KEY_UP event not required. Skipping"
                )
                return
            match event_list[0]:
                case "Increase screen brightness":
                    self.brightness.increase_screen_brightness(25)
                case "Decrease screen brightness":
                    self.brightness.decrease_screen_brightness(25)
                case "Increase led brightness":
                    self.brightness.increase_led_brightness()
                case "Decrease led brightness":
                    self.brightness.decrease_led_brightness()
                case "Switch led mode":
                    self.brightness.switch_led_mode()
                case "Open Keyboard":
                    self.steam_ifrunning_deckui('steam://open/keyboard')
                case "Open Chimera":
                    logger.debug(
                        "Open Chimera"
                    )
                    self.launch_chimera()
                case "Toggle Gyro":
                    logger.debug(
                        "Toggle Gyro is not currently enabled"
                    )
                case "Toggle Mouse Mode":
                    logger.debug(
                        "Toggle Mouse Mode is not currently enabled"
                    )
                case "Toggle Performance":
                    logger.debug("Toggle Performance")
                    await self.toggle_performance()
                case "Hibernate", "Suspend", "Shutdown":
                    logger.error(
                        f"Power mode {event_list[0]} set to button action. "
                        f"Check your configuration file."
                    )
                case _:
                    logger.warning(f"{event_list[0]} not defined.")
            return

        logger.debug(f'Event list: {event_list}')
        events = []

        if value == 0:
            for button_event in reversed(event_list):
                new_event = InputEvent(
                    seed_event.sec,
                    seed_event.usec,
                    button_event[0],
                    button_event[1],
                    value
                )
                events.append(new_event)
        else:
            for button_event in event_list:
                new_event = InputEvent(
                    seed_event.sec,
                    seed_event.usec,
                    button_event[0],
                    button_event[1],
                    value
                )
                events.append(new_event)

        size = len(events)
        if size > 1:
            await self.emit_events(events)
        elif size == 1:
            self.emit_event(events[0])

    def launch_chimera(self) -> bool:
        """
        Launching Chimera App
        :return:
        """
        add_toast(
            title='[Handycon] Chimera App',
            body='Openning Chimera App'
        )
        if not self.HAS_CHIMERA_LAUNCHER:
            return False
        try:
            subprocess.run(["su", self.USER, "-c", CHIMERA_LAUNCHER_PATH])
            return True
        except Exception as error:
            logger.exception(error)
            return False

    async def toggle_performance(self):
        """
        Switch performance mode
        :return:
        """
        mode = next(self.mode_generator)

        mode_name = mode['name']
        mode_arg = mode['mode']
        thermal_mode = mode['thermal_mode']

        if mode == "Max Boost":
            cmd_args = f'-a 22000 -b 23000 -c 19000 {mode_arg}'
        elif mode == "Average Performance":
            cmd_args = f'-a 18000 -b 19000 -c 17000 {mode_arg}'
        else:
            cmd_args = f'-a 14000 -b 16000 -c 12000 {mode_arg}'

        await self.do_rumble()
        await asyncio.sleep(FF_DELAY)
        await self.do_rumble(interval=300)

        add_toast(
            title='[Handycon] Performance mode',
            body=f'Switching to "{mode_name}" mode'
        )

        ryzenadj_command = f'ryzenadj {cmd_args}'
        run = os.popen(ryzenadj_command, buffering=1).read().strip()
        logger.debug(run)

        command = f'echo {thermal_mode} > ' \
                  f'/sys/devices/' \
                  f'platform/asus-nb-wmi/throttle_thermal_policy'
        os.popen(command, buffering=1).read().strip()
        logger.debug(
            f'Thermal mode set to {thermal_mode}.')

    async def do_rumble(
            self,
            button: int = 0,
            interval: int = 10,
            length: int = 1000,
            delay: int = 0
    ):
        """
        Process gamepad rumble
        :param button:
        :param interval:
        :param length:
        :param delay:
        :return:
        """
        # Prevent look crash if controller_device was taken.
        if not self.controller_device:
            return

        # Create the rumble effect.
        rumble = ff.Rumble(strong_magnitude=0x0000, weak_magnitude=0xffff)
        effect = ff.Effect(
            e.FF_RUMBLE,
            -1,
            0,
            ff.Trigger(button, interval),
            ff.Replay(length, delay),
            ff.EffectType(ff_rumble_effect=rumble)
        )

        # Upload and transmit the effect.
        effect_id = self.controller_device.upload_effect(effect)
        self.controller_device.write(e.EV_FF, effect_id, 1)
        await asyncio.sleep(interval / 1000)
        self.controller_device.erase_effect(effect_id)

    def steam_ifrunning_deckui(self, cmd: str) -> bool:
        """
        Get the currently running Steam PID.
        :param cmd:
        :return:
        """
        add_toast(
            title='[Handycon] Keyboard',
            body='Openning screen keyboard'
        )
        steampid_path = self.HOME_PATH / '.steam/steam.pid'
        try:
            pid = steampid_path.read_text().strip()
        except Exception as err:
            logger.error(f"{err} | Error getting steam PID.")
            logger.exception(err)
            return False

        # Get the andline for the Steam process by checking /proc.
        steam_cmd_path = Path(f"/proc/{pid}/cmdline")
        if not steam_cmd_path.exists():
            # Steam not running.
            return False

        try:
            steam_cmd = steam_cmd_path.read_bytes()
        except Exception as err:
            logger.error(f"{err} | Error getting steam cmdline.")
            logger.exception(err)
            return False

            # Use this andline to determine if Steam is running in DeckUI mode.
        # e.g. "steam://shortpowerpress" only works in DeckUI.
        is_deckui = b"-gamepadui" in steam_cmd
        if not is_deckui:
            return False

        steam_path = self.HOME_PATH / '.steam/root/ubuntu12_32/steam'
        # steam_path = 'steam'
        try:
            cmd = ' '.join([
                "su", self.USER, "-c", f"'{steam_path} -ifrunning {cmd}'"
            ])
            logger.debug(cmd)
            os.system(cmd)
            return True
        except Exception as err:
            logger.error(f"{err} | Error sending and to Steam.")
            logger.exception(err)
            return False

    async def process_event(
            self,
            seed_event: InputEvent,
            active_keys: list[int]
    ):
        """
        Translate event to button press
        :param handycon:
        :param seed_event:
        :param active_keys:
        :return:
        """
        logger.debug(f'seed_event: {seed_event}')
        logger.debug(f'active_keys: {active_keys}')
        # Button map shortcuts for easy reference.
        button1 = self.button_map["button1"]  # Default Screenshot
        button2 = self.button_map["button2"]  # Default QAM
        button3 = self.button_map["button3"]  # Default ESC
        button4 = self.button_map["button4"]  # Default OSK
        button5 = self.button_map["button5"]  # Default MODE
        button6 = self.button_map["button6"]
        # button7 = self.button_map["button7"]
        button8 = self.button_map["button8"]
        button9 = self.button_map["button9"]
        button10 = self.button_map["button10"]
        button11 = self.button_map["button11"]
        button12 = self.button_map["button12"]

        button_a = EVENT_BTN_A
        # button_b = EVENT_BTN_B
        button_x = EVENT_BTN_X
        # button_y = EVENT_BTN_Y

        # Loop variables
        button_on = seed_event.value
        this_button = None

        # Handle missed keys.
        if active_keys == [] and self.event_queue != []:
            this_button = self.event_queue[0]

        if active_keys == [186, 311] \
                and seed_event.code == 186 \
                and button_on == 1:
            this_button = ["Increase screen brightness"]

        if active_keys == [186, 310] \
                and seed_event.code == 186 \
                and button_on == 1:
            this_button = ["Decrease screen brightness"]

        if active_keys == [148, 311] \
                and seed_event.code == 148 \
                and button_on == 1:
            this_button = ["Increase led brightness"]

        if active_keys == [148, 310] \
                and seed_event.code == 148 \
                and button_on == 1:
            this_button = ["Decrease led brightness"]

        if active_keys == [148, 310, 311] \
                and seed_event.code == 148 \
                and button_on == 1:
            this_button = ["Switch led mode"]

        if active_keys == [186, 310, 311] \
                and seed_event.code == 186 \
                and button_on == 1:
            this_button = ["Toggle Performance"]

        if active_keys == [186, 307] \
                and seed_event.code == 186 \
                and button_on == 1:
            this_button = ["Open Keyboard"]

        if active_keys == [187] \
                and button_on in [1, 2]:
            await self.emit_now(seed_event, button_a, 1)
        elif active_keys == [] \
                and seed_event.code == 187 \
                and button_on == 0:
            await self.emit_now(seed_event, button_a, 0)

        if active_keys == [188] \
                and button_on in [1, 2]:
            await self.emit_now(seed_event, button_x, 1)
        elif active_keys == [] \
                and seed_event.code == 188 \
                and button_on == 0:
            await self.emit_now(seed_event, button_x, 0)

        # BUTTON 1 (Default: Screenshot) Paddle + Y
        if active_keys == [184] \
                and button_on == 1 \
                and button1 not in self.event_queue:
            self.event_queue.append(button1)
        elif active_keys == [] \
                and seed_event.code in [184, 185] \
                and button_on == 0 \
                and button1 in self.event_queue:
            this_button = button1

        # BUTTON 2 (Default: QAM) Armory Crate Button Short Press
        if active_keys == [148] \
                and button_on == 1 \
                and button2 not in self.event_queue:
            self.event_queue.append(button2)
        elif active_keys == [] \
                and seed_event.code in [148] \
                and button_on == 0 \
                and button2 in self.event_queue:
            this_button = button2

        # BUTTON 3 (Default: ESC) Paddle + X Temp disabled, goes nuts.
        # This event triggers from KEYBOARD_2.
        if active_keys == [25, 125] \
                and button_on == 1 \
                and button3 not in self.event_queue:
            self.event_queue.append(button3)
        elif active_keys == [] \
                and seed_event.code in [49, 125, 185] \
                and button_on == 0 \
                and button3 in self.event_queue:
            this_button = button3

        # BUTTON 4 (Default: OSK) Paddle + D-Pad UP
        if active_keys == [88] \
                and button_on == 1 \
                and button4 not in self.event_queue:
            self.event_queue.append(button4)
        elif active_keys == [] \
                and seed_event.code in [88, 185] \
                and button_on == 0 \
                and button4 in self.event_queue:
            this_button = button4

        # BUTTON 5 (Default: Mode) Control Center Short Press.
        if active_keys == [186] \
                and button_on == 1 \
                and button5 not in self.event_queue:
            self.event_queue.append(button5)
        elif active_keys == [] \
                and seed_event.code in [186] \
                and button_on == 0 \
                and button5 in self.event_queue:
            this_button = button5

        # BUTTON 6 (Default: Launch Chimera) Paddle + A
        if active_keys == [68] \
                and button_on == 1 \
                and button6 not in self.event_queue:
            self.event_queue.append(button6)
        elif active_keys == [] \
                and seed_event.code in [68, 185] \
                and button_on == 0 \
                and button6 in self.event_queue:
            this_button = button6

        # BUTTON 7 (Default: Toggle Performance) Armory Crate Button Long Press
        # This button triggers immediate down/up
        # after holding for ~1s an F17 and then
        # released another down/up for F18 on release.
        # We use the F18 "KEY_UP" for release.
        # if active_keys == [187] \
        #         and button_on == 1 \
        #         and button7 not in self.event_queue:
        #     self.event_queue.append(button7)
        #     await self.do_rumble(0, 150, 1000, 0)
        # elif active_keys == [] \
        #         and seed_event.code in [188] \
        #         and button_on == 0 \
        #         and button7 in self.event_queue:
        #     this_button = button7

        # BUTTON 8 (Default: Mode) Control Center Long Press.
        # This event triggers from KEYBOARD_2.
        if active_keys == [29, 56, 111] \
                and button_on == 1 \
                and button8 not in self.event_queue:
            self.event_queue.append(button8)
            await self.do_rumble(0, 150, 1000, 0)
        elif active_keys == [] \
                and seed_event.code in [29, 56, 111] \
                and button_on == 0 \
                and button8 in self.event_queue:
            this_button = button8

        # BUTTON 9 (Default: Toggle Mouse) Paddle + D-Pad DOWN
        # This event triggers from KEYBOARD_2.
        if active_keys == [1, 29, 42] \
                and button_on == 1 \
                and button9 not in self.event_queue:
            self.event_queue.append(button9)
        elif active_keys == [] \
                and seed_event.code in [1, 29, 42, 185] \
                and button_on == 0 \
                and button9 in self.event_queue:
            this_button = button9

        # BUTTON 10 (Default: ALT+TAB) Paddle + D-Pad LEFT
        # This event triggers from KEYBOARD_2.
        if active_keys == [32, 125] \
                and button_on == 1 \
                and button10 not in self.event_queue:
            self.event_queue.append(button10)
        elif active_keys == [] \
                and seed_event.code in [32, 125, 185] \
                and button_on == 0 \
                and button10 in self.event_queue:
            this_button = button10

        # BUTTON 11 (Default: KILL) Paddle + D-Pad RIGHT
        # This event triggers from KEYBOARD_2.
        if active_keys == [15, 125] \
                and button_on == 1 \
                and button11 not in self.event_queue:
            self.event_queue.append(button11)
        elif active_keys == [] \
                and seed_event.code in [15, 125, 185] \
                and button_on == 0 \
                and button11 in self.event_queue:
            this_button = button11

        # BUTTON 12 (Default: Toggle Gyro) Paddle + B
        # This event triggers from KEYBOARD_2.
        if active_keys == [49, 125] \
                and button_on == 1 \
                and button12 not in self.event_queue:
            self.event_queue.append(button12)
        elif active_keys == [] \
                and seed_event.code in [25, 125, 185] \
                and button_on == 0 \
                and button12 in self.event_queue:
            this_button = button12

        # Create list of events to fire.
        # Handle new button presses.
        if this_button and not self.last_button:
            try:
                self.event_queue.remove(this_button)
            except ValueError:
                pass
            self.last_button = this_button
            await self.emit_now(seed_event, this_button, 1)

        # Clean up old button presses.
        elif self.last_button and not this_button:
            await self.emit_now(seed_event, self.last_button, 0)
            self.last_button = None

    def handle_power_action(self):
        """
        Performs specific power actions based on user config.
        :return:
        """
        logger.debug(f"Power Action: {self.power_action}")
        match self.power_action:
            case "Suspend":
                os.system('systemctl suspend')

            case "Hibernate":
                os.system('systemctl hibernate')

            case "Shutdown":
                os.system('systemctl poweroff')

    async def handle_key_down(
            self,
            seed_event: InputEvent,
            queued_event: InputEvent
    ):
        """
        Handling key down
        :param seed_event:
        :param queued_event:
        :return:
        """
        self.event_queue.append(queued_event)
        if queued_event in INSTANT_EVENTS:
            await self.emit_now(seed_event, queued_event, 1)

    async def handle_key_up(
            self,
            seed_event: InputEvent,
            queued_event: InputEvent
    ):
        """
        Handling key up
        :param seed_event:
        :param queued_event:
        :return:
        """
        if queued_event in INSTANT_EVENTS:
            self.event_queue.remove(queued_event)
            await self.emit_now(seed_event, queued_event, 0)
        elif queued_event in QUEUED_EVENTS:
            # Create list of events to fire.
            # Handle new button presses.
            if not self.last_button:
                self.event_queue.remove(queued_event)
                self.last_button = queued_event
                await self.emit_now(seed_event, queued_event, 1)
                return

            # Clean up old button presses.
            if self.last_button:
                await self.emit_now(seed_event, self.last_button, 0)
                self.last_button = None
