#!/usr/bin/env python3
"""
This file is part of Handheld Game Console Controller System (HandyGCCS)
Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>
"""


# Python Modules
import asyncio
import logging
import os
import signal
import subprocess
import sys
import warnings

from pathlib import Path
from typing import Optional

# Local modules
from .device_explorer import DeviceExplorer
from .constants import \
    CHIMERA_LAUNCHER_PATH, \
    HIDE_PATH, \
    DETECT_DELAY, \
    INSTANT_EVENTS, \
    QUEUED_EVENTS, \
    FF_DELAY, \
    CONTROLLER_EVENTS

# Partial imports
from evdev import \
    ecodes as e, \
    ff, \
    InputDevice, \
    InputEvent, \
    list_devices, \
    UInput


logger = logging.getLogger('handycon')


warnings.filterwarnings("ignore", category=DeprecationWarning)


class HandheldController(DeviceExplorer):
    """
    Main class for catching controller/keyboard events
    """
    # Stores inng button presses to block spam
    event_queue: list[InputEvent] = []
    last_button: Optional[list[int]] = None
    last_x_val: int = 0
    last_y_val: int = 0
    running: bool = True
    shutdown: bool = False

    # Performance settings
    performance_mode: str = "--power-saving"
    thermal_mode: str = "0"

    def __init__(self):
        logger.info(
            "Starting Handhend Game Console Controller Service..."
        )
        if self.is_process_running("opengamepadui"):
            logger.warning(
                "Detected an OpenGamepadUI Process. "
                "Input management not possible. Exiting."
            )
            exit()
        DeviceExplorer.__init__(self)
        self.ui_device = UInput(
            CONTROLLER_EVENTS,
            name='Handheld Controller',
            bustype=0x3,
            vendor=0x045e,
            product=0x028e,
            version=0x110
        )

        # Run asyncio loop to capture all events.
        self.loop = asyncio.get_event_loop()

        # Attach the event loop of each device to the asyncio loop.
        asyncio.ensure_future(self.capture_controller_events())
        asyncio.ensure_future(self.capture_ff_events())
        asyncio.ensure_future(self.capture_keyboard_events())
        if self.KEYBOARD_2_NAME != '' and self.KEYBOARD_2_ADDRESS != '':
            asyncio.ensure_future(self.capture_keyboard_2_events())

        asyncio.ensure_future(self.capture_power_events())
        logger.info("Handheld Game Console Controller Service started.")

        # Establish signaling to handle gracefull shutdown.
        for recv_signal in (
                signal.SIGHUP,
                signal.SIGTERM,
                signal.SIGINT,
                signal.SIGQUIT
        ):
            self.loop.add_signal_handler(
                recv_signal,
                lambda s=recv_signal: asyncio.create_task(self.exit())
            )

        exit_code = 0
        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt.")
            exit_code = 1
        except Exception as err:
            logger.error(f"{err} | Hit exception condition.")
            logger.exception(err)
            exit_code = 2
        finally:
            self.loop.stop()
            sys.exit(exit_code)

    def launch_chimera(self) -> bool:
        """
        Launching Chimera App
        :return:
        """
        if not self.HAS_CHIMERA_LAUNCHER:
            return False
        try:
            subprocess.run(["su", self.USER, "-c", CHIMERA_LAUNCHER_PATH])
            return True
        except Exception as error:
            logger.exception(error)
            return False

    @staticmethod
    def is_process_running(name: str) -> bool:
        """
        Checking if process with name running
        :param name: Process name
        :return:
        """
        cmd = f"ps -Af | egrep '{name}' | egrep 'grep' -v | wc -l"
        read_proc = os.popen(cmd).read()
        proc_count = int(read_proc)
        if proc_count > 0:
            logger.debug(f'Process {name} is running.')
            return True
        logger.debug(f'Process {name} is NOT running.')
        return False

    def steam_ifrunning_deckui(self, cmd: str) -> bool:
        """
        Get the currently running Steam PID.
        :param cmd:
        :return:
        """
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
        try:
            result = subprocess.run([
                "su", self.USER, "-c", f"{steam_path} -ifrunning {cmd}"
            ])
            return result.returncode == 0
        except Exception as err:
            logger.error(f"{err} | Error sending and to Steam.")
            logger.exception(err)
            return False

    async def exit(self):
        """
        Method for graceful shutdown of handycon
        :return:
        """
        logger.info("Receved exit signal. Restoring devices.")
        self.running = False

        for device, event, path in [
            (self.controller_device,
             self.controller_event,
             self.controller_path),
            (self.keyboard_device,
             self.keyboard_event,
             self.keyboard_path),
            (self.keyboard_2_device,
             self.keyboard_2_event,
             self.keyboard_2_path),
        ]:
            if device:
                try:
                    device.ungrab()
                except IOError:
                    pass
                self.restore_device(event, path)

        if self.power_device and self.CAPTURE_POWER:
            try:
                self.power_device.ungrab()
            except IOError:
                pass
        if self.power_device_2 and self.CAPTURE_POWER:
            try:
                self.power_device_2.ungrab()
            except IOError:
                pass
        logger.info("Devices restored.")

        # Kill all tasks. They are infinite loops so we will wait forver.
        for task in [
            t
            for t in asyncio.all_tasks()
            if t is not asyncio.current_task()
        ]:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError as err:
                logger.exception(err)
        self.loop.stop()
        logger.info("Handheld Game Console Controller Service stopped.")

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

    # Captures keyboard events and translates them to virtual device events.
    async def capture_keyboard_events(self):
        """
        Capture keyboard events and translate them to mapped events.
        :return:
        """
        while self.running:
            if self.keyboard_device:
                try:
                    async for seed_event \
                            in self.keyboard_device.async_read_loop():
                        # Loop variables
                        active_keys = self.keyboard_device.active_keys()

                        # Debugging variables
                        logger.debug(
                            f"Seed Value: {seed_event.value}, "
                            f"Seed Code: {seed_event.code}, "
                            f"Seed Type: {seed_event.type}."
                        )
                        logger.debug(f"Active Keys: {active_keys}")
                        logger.debug(f"Queued events: {self.event_queue}")

                        # Capture keyboard events
                        # and translate them to mapped events.
                        await self.process_event(seed_event, active_keys)

                except Exception as err:
                    logger.error(
                        f"{err} | "
                        f"Error reading events from "
                        f"{self.keyboard_device.name}"
                    )
                    logger.exception(err)
                    self.remove_device(HIDE_PATH, self.keyboard_event)
                    self.keyboard_device = None
                    self.keyboard_event = None
                    self.keyboard_path = None
            else:
                logger.info("Attempting to grab keyboard device...")
                self.get_keyboard()
                await asyncio.sleep(DETECT_DELAY)

    # Captures keyboard events and translates them to virtual device events.
    async def capture_keyboard_2_events(self):
        """
        Capture keyboard events and translate them to mapped events.
        :return:
        """
        while self.running:
            if self.keyboard_2_device:
                try:
                    async for seed_event_2 \
                            in self.keyboard_2_device.async_read_loop():
                        # Loop variables
                        active_keys_2 = self.keyboard_2_device.active_keys()

                        # Debugging variables
                        logger.debug(
                            f"Seed Value: {seed_event_2.value}, "
                            f"Seed Code: {seed_event_2.code}, "
                            f"Seed Type: {seed_event_2.type}."
                        )
                        logger.debug(f"Active Keys: {active_keys_2}")
                        logger.debug(f"Queued events: {self.event_queue}")

                        # Capture keyboard events
                        # and translate them to mapped events.
                        match self.system_type:
                            case "ALY_GEN1":
                                await self.process_event(
                                    seed_event_2,
                                    active_keys_2
                                )

                except Exception as err:
                    logger.error(
                        f"{err} | "
                        f"Error reading events "
                        f"from {self.keyboard_2_device.name}"
                    )
                    logger.exception(err)
                    self.remove_device(HIDE_PATH, self.keyboard_2_event)
                    self.keyboard_2_device = None
                    self.keyboard_2_event = None
                    self.keyboard_2_path = None
            else:
                logger.info("Attempting to grab keyboard device 2...")
                self.get_keyboard_2()
                await asyncio.sleep(DETECT_DELAY)

    async def capture_controller_events(self):
        """
        Capture keyboard events and translate them to mapped events.
        :return:
        """
        logger.debug(f"capture_controller_events, {self.running}")
        while self.running:
            if self.controller_device:
                try:
                    async for event in \
                            self.controller_device.async_read_loop():
                        # Block FF events, or get infinite recursion.
                        # Up to you I guess...
                        if event.type in [e.EV_FF, e.EV_UINPUT]:
                            continue

                        # Output the event.
                        self.emit_event(event)
                except Exception as err:
                    logger.error(
                        f"{err} | "
                        f"Error reading events from "
                        f"{self.controller_device.name}."
                    )
                    logger.exception(err)
                    self.remove_device(HIDE_PATH, self.controller_event)
                    self.controller_device = None
                    self.controller_event = None
                    self.controller_path = None
            else:
                logger.info("Attempting to grab controller device...")
                self.get_controller()
                await asyncio.sleep(DETECT_DELAY)

    async def capture_power_events(self):
        """
        Captures power events and handles long or short press events.
        :return:
        """

        while self.running:

            if self.power_device is not None:
                power_key = self.power_device
            elif self.power_device_2 is not None:
                power_key = self.power_device_2
            else:
                logger.warning(
                    'Power device is undefined, searching for it...')
                logger.warning(
                    "Attempting to grab controller device...")
                self.get_powerkey()
                await asyncio.sleep(DETECT_DELAY)
                continue

            try:
                async for event in power_key.async_read_loop():
                    logger.debug(
                        f"Got event: "
                        f"{event.type} | {event.code} | {event.value}"
                    )
                    if event.type == e.EV_KEY and event.code == 116:
                        # KEY_POWER
                        if event.value == 0:
                            self.handle_power_action()

            except Exception as err:
                logger.error(
                    f"{err} | Error reading events from power device."
                )
                logger.exception(err)
                self.power_device = None
                self.power_device_2 = None

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

    async def capture_ff_events(self):
        """
        Handle FF event uploads
        :return:
        """

        ff_effect_id_set = set()

        async for event in self.ui_device.async_read_loop():
            if self.controller_device is None:
                # Slow down the loop, so we don't waste millions of cycles
                # and overheat our controller.
                await asyncio.sleep(DETECT_DELAY)
                continue

            if event.type == e.EV_FF:
                # Forward FF event to controller.
                self.controller_device.write(
                    e.EV_FF,
                    event.code,
                    event.value
                )
                continue

            # Programs will submit
            # these EV_UINPUT events to ensure the device is capable.
            # Doing this forever doesn't seem to pose a problem,
            # and attempting to ignore
            # any of them causes the program to halt.
            if event.type != e.EV_UINPUT:
                continue

            if event.code == e.UI_FF_UPLOAD:
                # Upload to the virtual device to prevent threadlocking.
                # This does nothing else
                upload = self.ui_device.begin_upload(event.value)
                effect = upload.effect

                if effect.id not in ff_effect_id_set:
                    effect.id = -1  # set to -1
                    # for kernel to allocate a new id.
                    # all other values throw an error for invalid input.

                try:
                    # Upload to the actual controller.
                    effect_id = self.controller_device.upload_effect(
                        effect
                    )
                    effect.id = effect_id

                    ff_effect_id_set.add(effect_id)

                    upload.retval = 0
                except IOError as err:
                    logger.error(
                        f"{err} | Error uploading effect {effect.id}."
                    )
                    logger.exception(err)
                    upload.retval = -1

                self.ui_device.end_upload(upload)

            elif event.code == e.UI_FF_ERASE:
                erase = self.ui_device.begin_erase(event.value)

                try:
                    self.controller_device.erase_effect(erase.effect_id)
                    ff_effect_id_set.remove(erase.effect_id)
                    erase.retval = 0
                except IOError as err:
                    logger.error(
                        f"{err} | Error erasing effect {erase.effect_id}."
                    )
                    logger.exception(err)
                    erase.retval = -1

                self.ui_device.end_erase(erase)

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
        logger.debug(f"Emitting event: {event}")
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

    async def toggle_performance(self):
        """
        Switch performance mode
        :return:
        """
        if self.performance_mode == "--max-performance":
            self.performance_mode = "--power-saving"
            await self.do_rumble()
            await asyncio.sleep(FF_DELAY)
            await self.do_rumble(interval=100)
        else:
            self.performance_mode = "--max-performance"
            await self.do_rumble(interval=500)
            await asyncio.sleep(FF_DELAY)
            await self.do_rumble(interval=75)
            await asyncio.sleep(FF_DELAY)
            await self.do_rumble(interval=75)

        ryzenadj_command = f'ryzenadj {self.performance_mode}'
        run = os.popen(ryzenadj_command, buffering=1).read().strip()
        logger.debug(run)

        if self.system_type in ["ALY_GEN1"]:
            self.thermal_mode = "0" if self.thermal_mode == "1" else "1"

            command = f'echo {self.thermal_mode} > ' \
                      f'/sys/devices/' \
                      f'platform/asus-nb-wmi/throttle_thermal_policy'
            os.popen(command, buffering=1).read().strip()
            logger.debug(
                f'Thermal mode set to {self.thermal_mode}.')


def main():
    """
    Start of handycon
    :return:
    """
    logging.basicConfig(
        format='[%(levelname)s] -  '
               '%(name)s - '
               '(%(filename)s).%(funcName)s(%(lineno)d) - '
               '%(message)s',
        level=logging.INFO
    )

    HandheldController()
