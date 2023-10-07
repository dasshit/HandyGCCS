#!/usr/bin/env python3
"""
This file is part of Handheld Game Console Controller System (HandyGCCS)
Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>
"""


# Python Modules
import asyncio
import configparser
import logging
import os
import re
import signal
import subprocess
import sys
import time
import warnings

from pathlib import Path
from typing import Literal, Union, Optional

# Local modules
from .constants import \
    CHIMERA_LAUNCHER_PATH, \
    HIDE_PATH, \
    POWER_ACTION_MAP, \
    EVENT_MAP, \
    CONFIG_PATH, \
    CONFIG_DIR, \
    DETECT_DELAY, \
    INSTANT_EVENTS, \
    QUEUED_EVENTS, \
    FF_DELAY, \
    CONTROLLER_EVENTS
from .handhelds import \
    ally_gen1, \
    anb_gen1, \
    aok_gen1, \
    aok_gen2, \
    aya_gen1, \
    aya_gen2, \
    aya_gen3, \
    aya_gen4, \
    aya_gen5, \
    aya_gen6, \
    aya_gen7, \
    ayn_gen1, \
    ayn_gen2, \
    ayn_gen3, \
    gpd_gen1, \
    gpd_gen2, \
    gpd_gen3, \
    oxp_gen1, \
    oxp_gen2, \
    oxp_gen3, \
    oxp_gen4, \
    oxp_gen6

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


class HandheldController:
    """
    Main class for catching controller/keyboard events
    """
    # Session Variables
    config: Optional[configparser.ConfigParser] = None
    button_map: dict[str, list[list[int]]] = {}
    # Stores inng button presses to block spam
    event_queue: list[InputEvent] = []
    last_button: Optional[list[int]] = None
    last_x_val: int = 0
    last_y_val: int = 0
    power_action: Literal["Hibernate", "Suspend", "Shutdown"] = "Suspend"
    running: bool = True
    shutdown: bool = False
    system_type: str = "Generic handheld"

    # Handheld Config
    BUTTON_DELAY: Union[int, float] = 0.00
    CAPTURE_CONTROLLER: bool = False
    CAPTURE_KEYBOARD: bool = False
    CAPTURE_POWER: bool = False
    GAMEPAD_ADDRESS: str = ''
    GAMEPAD_NAME: str = ''
    KEYBOARD_ADDRESS: str = ''
    KEYBOARD_NAME: str = ''
    KEYBOARD_2_ADDRESS: str = ''
    KEYBOARD_2_NAME: str = ''
    POWER_BUTTON_PRIMARY: str = "LNXPWRBN/button/input0"
    POWER_BUTTON_SECONDARY: str = "PNP0C0C/button/input0"

    # Enviroment Variables
    HAS_CHIMERA_LAUNCHER: bool = False
    USER: Optional[str] = None
    HOME_PATH: Optional[Path] = None

    # UInput Devices
    controller_device: Optional[InputDevice] = None
    keyboard_device: Optional[InputDevice] = None
    keyboard_2_device: Optional[InputDevice] = None
    power_device: Optional[InputDevice] = None
    power_device_2: Optional[InputDevice] = None

    # Paths
    controller_event: Optional[str] = None
    controller_path: Optional[Path] = None
    keyboard_event: Optional[str] = None
    keyboard_path: Optional[Path] = None
    keyboard_2_event: Optional[str] = None
    keyboard_2_path: Optional[Path] = None

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
        HIDE_PATH.mkdir(parents=True, exist_ok=True)
        self.restore_hidden()
        self.get_user()
        self.HAS_CHIMERA_LAUNCHER = os.path.isfile(CHIMERA_LAUNCHER_PATH)
        self.id_system()
        self.get_config()
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

    def init_handheld(handycon):
        """
        Captures keyboard events and translates them to virtual device events.
        :param handycon:
        :return:
        """
        handycon.BUTTON_DELAY = 0.2
        handycon.CAPTURE_CONTROLLER = True
        handycon.CAPTURE_KEYBOARD = True
        handycon.CAPTURE_POWER = True
        handycon.GAMEPAD_ADDRESS = 'usb-0000:0a:00.3-2/input0'
        handycon.GAMEPAD_NAME = 'Microsoft X-Box 360 pad'
        handycon.KEYBOARD_ADDRESS = 'usb-0000:0a:00.3-3/input0'
        handycon.KEYBOARD_NAME = 'Asus Keyboard'
        handycon.KEYBOARD_2_ADDRESS = 'usb-0000:0a:00.3-3/input2'
        handycon.KEYBOARD_2_NAME = 'Asus Keyboard'

    async def process_event(
            handycon,
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
        # Button map shortcuts for easy reference.
        button1 = handycon.button_map["button1"]  # Default Screenshot
        button2 = handycon.button_map["button2"]  # Default QAM
        button3 = handycon.button_map["button3"]  # Default ESC
        button4 = handycon.button_map["button4"]  # Default OSK
        button5 = handycon.button_map["button5"]  # Default MODE
        button6 = handycon.button_map["button6"]
        button7 = handycon.button_map["button7"]
        button8 = handycon.button_map["button8"]
        button9 = handycon.button_map["button9"]
        button10 = handycon.button_map["button10"]
        button11 = handycon.button_map["button11"]
        button12 = handycon.button_map["button12"]

        # Loop variables
        button_on = seed_event.value
        this_button = None

        # Handle missed keys.
        if active_keys == [] and handycon.event_queue != []:
            this_button = handycon.event_queue[0]

        # BUTTON 1 (Default: Screenshot) Paddle + Y
        if active_keys == [184] \
                and button_on == 1 \
                and button1 not in handycon.event_queue:
            handycon.event_queue.append(button1)
        elif active_keys == [] \
                and seed_event.code in [184, 185] \
                and button_on == 0 \
                and button1 in handycon.event_queue:
            this_button = button1

        # BUTTON 2 (Default: QAM) Armory Crate Button Short Press
        if active_keys == [148] \
                and button_on == 1 \
                and button2 not in handycon.event_queue:
            handycon.event_queue.append(button2)
        elif active_keys == [] \
                and seed_event.code in [148] \
                and button_on == 0 \
                and button2 in handycon.event_queue:
            this_button = button2

        # BUTTON 3 (Default: ESC) Paddle + X Temp disabled, goes nuts.
        # This event triggers from KEYBOARD_2.
        if active_keys == [25, 125] \
                and button_on == 1 \
                and button3 not in handycon.event_queue:
            handycon.event_queue.append(button3)
        elif active_keys == [] \
                and seed_event.code in [49, 125, 185] \
                and button_on == 0 \
                and button3 in handycon.event_queue:
            this_button = button3

        # BUTTON 4 (Default: OSK) Paddle + D-Pad UP
        if active_keys == [88] \
                and button_on == 1 \
                and button4 not in handycon.event_queue:
            handycon.event_queue.append(button4)
        elif active_keys == [] \
                and seed_event.code in [88, 185] \
                and button_on == 0 \
                and button4 in handycon.event_queue:
            this_button = button4

        # BUTTON 5 (Default: Mode) Control Center Short Press.
        if active_keys == [186] \
                and button_on == 1 \
                and button5 not in handycon.event_queue:
            handycon.event_queue.append(button5)
        elif active_keys == [] \
                and seed_event.code in [186] \
                and button_on == 0 \
                and button5 in handycon.event_queue:
            this_button = button5

        # BUTTON 6 (Default: Launch Chimera) Paddle + A
        if active_keys == [68] \
                and button_on == 1 \
                and button6 not in handycon.event_queue:
            handycon.event_queue.append(button6)
        elif active_keys == [] \
                and seed_event.code in [68, 185] \
                and button_on == 0 \
                and button6 in handycon.event_queue:
            this_button = button6

        # BUTTON 7 (Default: Toggle Performance) Armory Crate Button Long Press
        # This button triggers immediate down/up
        # after holding for ~1s an F17 and then
        # released another down/up for F18 on release.
        # We use the F18 "KEY_UP" for release.
        if active_keys == [187] \
                and button_on == 1 \
                and button7 not in handycon.event_queue:
            handycon.event_queue.append(button7)
            await handycon.do_rumble(0, 150, 1000, 0)
        elif active_keys == [] \
                and seed_event.code in [188] \
                and button_on == 0 \
                and button7 in handycon.event_queue:
            this_button = button7

        # BUTTON 8 (Default: Mode) Control Center Long Press.
        # This event triggers from KEYBOARD_2.
        if active_keys == [29, 56, 111] \
                and button_on == 1 \
                and button8 not in handycon.event_queue:
            handycon.event_queue.append(button8)
            await handycon.do_rumble(0, 150, 1000, 0)
        elif active_keys == [] \
                and seed_event.code in [29, 56, 111] \
                and button_on == 0 \
                and button8 in handycon.event_queue:
            this_button = button8

        # BUTTON 9 (Default: Toggle Mouse) Paddle + D-Pad DOWN
        # This event triggers from KEYBOARD_2.
        if active_keys == [1, 29, 42] \
                and button_on == 1 \
                and button9 not in handycon.event_queue:
            handycon.event_queue.append(button9)
        elif active_keys == [] \
                and seed_event.code in [1, 29, 42, 185] \
                and button_on == 0 \
                and button9 in handycon.event_queue:
            this_button = button9

        # BUTTON 10 (Default: ALT+TAB) Paddle + D-Pad LEFT
        # This event triggers from KEYBOARD_2.
        if active_keys == [32, 125] \
                and button_on == 1 \
                and button10 not in handycon.event_queue:
            handycon.event_queue.append(button10)
        elif active_keys == [] \
                and seed_event.code in [32, 125, 185] \
                and button_on == 0 \
                and button10 in handycon.event_queue:
            this_button = button10

        # BUTTON 11 (Default: KILL) Paddle + D-Pad RIGHT
        # This event triggers from KEYBOARD_2.
        if active_keys == [15, 125] \
                and button_on == 1 \
                and button11 not in handycon.event_queue:
            handycon.event_queue.append(button11)
        elif active_keys == [] \
                and seed_event.code in [15, 125, 185] \
                and button_on == 0 \
                and button11 in handycon.event_queue:
            this_button = button11

        # BUTTON 12 (Default: Toggle Gyro) Paddle + B
        # This event triggers from KEYBOARD_2.
        if active_keys == [49, 125] \
                and button_on == 1 \
                and button12 not in handycon.event_queue:
            handycon.event_queue.append(button12)
        elif active_keys == [] \
                and seed_event.code in [25, 125, 185] \
                and button_on == 0 \
                and button12 in handycon.event_queue:
            this_button = button12

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

    # Match runtime variables to the config
    def map_config(self):
        """
        Assign config file values for buttons and power button
        :return:
        """
        self.button_map = {
            key: EVENT_MAP[self.config['Button Map'][key]]
            for key in self.config["Button Map"].keys()
        }
        self.power_action = POWER_ACTION_MAP[
            self.config["Button Map"]["power_button"]
        ][0]

    # Sets the default configuration.
    def set_default_config(self):
        """
        Setting default handygccs.conf
        :return:
        """
        self.config["Button Map"] = {
            "button1": "SCR",
            "button2": "QAM",
            "button3": "ESC",
            "button4": "OSK",
            "button5": "MODE",
            "button6": "OPEN_CHIMERA",
            "button7": "TOGGLE_PERFORMANCE",
            "button8": "MODE",
            "button9": "TOGGLE_MOUSE",
            "button10": "ALT_TAB",
            "button11": "KILL",
            "button12": "TOGGLE_GYRO",
            "power_button": "SUSPEND",
        }

    # Writes current config to disk.
    def write_config(self):
        """
        Creating /etc/handygccs folder and writing config
        :return:
        """
        # Make the HandyGCCS directory if it doesn't exist.
        if not CONFIG_DIR.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        with CONFIG_PATH.open(mode='w') as config_file:
            self.config.write(config_file)
            logger.info(f"Created new config: {CONFIG_PATH}")

    def get_config(self):
        """
        Getting config from /etc/handygccs/handygccs.conf
        :return:
        """
        # Check for an existing config file and load it.
        self.config = configparser.ConfigParser()

        if CONFIG_PATH.exists():
            logger.info(f"Loading existing config: {CONFIG_PATH}")
            self.config.read(CONFIG_PATH)

            if "power_button" not in self.config["Button Map"]:
                logger.info(
                    "Config file out of date. Generating new config."
                )
                self.set_default_config()
                self.write_config()

        else:
            self.set_default_config()
            self.write_config()

        self.map_config()

    @staticmethod
    def get_cpu_vendor():
        """
        Getting cpu vendor
        :return:
        """
        cmd = "cat /proc/cpuinfo | egrep 'vendor_id'"
        all_info = subprocess.check_output(cmd, shell=True).decode().strip()
        for line in all_info.split("\n"):
            if "vendor_id" in line:
                return re.sub(".*vendor_id.*:", "", line, 1).strip()

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

    def get_user(self) -> bool:
        """
        Capture the username
        and home path of the user who has been logged in the longest.
        :return:
        """
        logger.debug("Identifying user.")
        cmd = "who | awk '{print $1}' | sort | head -1"
        while self.USER is None:
            USER_LIST = subprocess.Popen(
                args=cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )
            for get_first in USER_LIST.stdout:
                name = get_first.decode().strip()
                if name is not None:
                    self.USER = name
                break
            time.sleep(1)

        logger.debug(f"USER: {self.USER}")
        self.HOME_PATH = Path("/home/") / self.USER
        logger.debug(f"HOME_PATH: {self.HOME_PATH}")
        return True

    def id_system(self):
        """
        Identify system and set self attrs of controller and keyboards
        :return:
        """
        system_id = Path(
            "/sys/devices/virtual/dmi/id/product_name").read_text().strip()
        cpu_vendor = self.get_cpu_vendor()
        logger.debug(f"Found CPU Vendor: {cpu_vendor}")

        self.system_type = "ALY_GEN1"
        self.init_handheld()

        logger.info(
            f"Identified host system as {system_id} "
            f"and configured defaults for {self.system_type}."
        )

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

    def get_controller(self) -> bool:
        """
        Getting controller device
        :return:
        """
        # Identify system input event devices.
        logger.debug(f"Attempting to grab {self.GAMEPAD_NAME}.")
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        except Exception as error:
            logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False

        # Grab the built-in devices.
        # This will give us exclusive acces to the devices
        # and their capabilities.
        for device in devices_original:
            if device.name == self.GAMEPAD_NAME \
                    and device.phys == self.GAMEPAD_ADDRESS:
                self.controller_path = Path(device.path)
                self.controller_device = InputDevice(
                    self.controller_path
                )
                if self.CAPTURE_CONTROLLER:
                    self.controller_device.grab()
                    self.controller_event = self.controller_path.name
                    self.controller_path.rename(
                        HIDE_PATH / self.controller_event
                    )
                break

        # Sometimes the service loads
        # before all input devices have full initialized. Try a few times.
        if not self.controller_device:
            logger.warning(
                "Controller device not yet found. Restarting scan."
            )
            time.sleep(DETECT_DELAY)
            return False
        else:
            logger.info(
                f"Found {self.controller_device.name}. "
                f"Capturing input data."
            )
            return True

    def get_keyboard(self) -> bool:
        """
        Getting keyboard
        :return:
        """
        # Identify system input event devices.
        logger.debug(f"Attempting to grab {self.KEYBOARD_NAME}.")
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        except Exception as error:
            logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False
        # Grab the built-in devices.
        # This will give us exclusive acces to the devices
        # and their capabilities.
        for device in devices_original:
            logger.debug(f"{device.name}, {device.phys}")
            if device.name == self.KEYBOARD_NAME \
                    and device.phys == self.KEYBOARD_ADDRESS:
                self.keyboard_path = Path(device.path)
                self.keyboard_device = InputDevice(self.keyboard_path)
                if self.CAPTURE_KEYBOARD:
                    self.keyboard_device.grab()
                    self.keyboard_event = self.keyboard_path.name
                    self.keyboard_path.rename(
                        HIDE_PATH / self.keyboard_event
                    )
                break

        # Sometimes the service loads
        # before all input devices have full initialized. Try a few times.
        if not self.keyboard_device:
            logger.warning(
                "Keyboard device not yet found. Restarting scan.")
            time.sleep(DETECT_DELAY)
            return False
        else:
            logger.info(
                f"Found {self.keyboard_device.name}. Capturing input data."
            )
            return True

    def get_keyboard_2(self) -> bool:
        """
        Getting keyboard
        :return:
        """
        logger.debug(
            f"Attempting to grab {self.KEYBOARD_2_NAME}.")
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        except Exception as error:
            logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False

        # Grab the built-in devices.
        # This will give us exclusive acces
        # to the devices and their capabilities.
        for device in devices_original:
            logger.debug(f"{device.name}, {device.phys}")
            if device.name == self.KEYBOARD_2_NAME \
                    and device.phys == self.KEYBOARD_2_ADDRESS:
                self.keyboard_2_path = Path(device.path)
                self.keyboard_2_device = InputDevice(self.keyboard_2_path)
                if self.CAPTURE_KEYBOARD:
                    self.keyboard_2_device.grab()
                    self.keyboard_2_event = self.keyboard_2_path.name
                    self.keyboard_2_path.rename(
                        HIDE_PATH / self.keyboard_2_event
                    )
                break

        # Sometimes the service loads
        # before all input devices have full initialized. Try a few times.
        if not self.keyboard_2_device:
            logger.warning(
                "Keyboard device 2 not yet found. Restarting scan."
            )
            time.sleep(DETECT_DELAY)
            return False
        else:
            logger.info(
                f"Found {self.keyboard_2_device.name}. Capturing input data."
            )
            return True

    def get_powerkey(self):
        """
        Getting power button
        :return:
        """
        logger.debug("Attempting to grab power buttons.")
        # Identify system input event devices.
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        # Some funky stuff happens sometimes when booting.
        # Give it another shot.
        except Exception as error:
            logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False

        # Grab the built-in devices.
        # This will give us exclusive
        # acces to the devices and their capabilities.
        for device in filter(
                lambda x: x.name == 'Power Button',
                devices_original
        ):

            # Power Button
            if device.phys == self.POWER_BUTTON_PRIMARY \
                    and not self.power_device:
                self.power_device = device
                logger.debug(
                    f"found power device {self.power_device.phys}"
                )
                if self.CAPTURE_POWER:
                    self.power_device.grab()

            # Some devices have an extra power
            # input device corresponding to the same
            # physical button that needs to be grabbed.
            if device.phys == self.POWER_BUTTON_SECONDARY \
                    and not self.power_device_2:
                self.power_device_2 = device
                logger.debug(
                    f"found alternate power device {self.power_device_2.phys}"
                )
                if self.CAPTURE_POWER:
                    self.power_device_2.grab()

        if not self.power_device and not self.power_device_2:
            logger.warning("No Power Button found. Restarting scan.")
            time.sleep(DETECT_DELAY)
            return False
        else:
            if self.power_device:
                logger.info(
                    f"Found {self.power_device.name}. Capturing input data."
                )
            if self.power_device_2:
                logger.info(
                    f"Found {self.power_device_2.name}. Capturing input data."
                )
            return True

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
                        if active_keys:
                            logger.debug(
                                f"Active Keys: {active_keys}")
                        else:
                            logger.debug("No active keys")
                        if self.event_queue:
                            logger.debug(
                                f"Queued events: {self.event_queue}"
                            )
                        else:
                            logger.debug("No active events.")

                        # Capture keyboard events
                        # and translate them to mapped events.
                        await self.process_event(
                            seed_event,
                            active_keys
                        )

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
                        if active_keys_2:
                            logger.debug(
                                f"Active Keys: {active_keys_2}")
                        else:
                            logger.debug("No active keys")
                        if self.event_queue:
                            logger.debug(
                                f"Queued events: {self.event_queue}"
                            )
                        else:
                            logger.debug("No active events.")

                        # Capture keyboard events
                        # and translate them to mapped events.
                        match self.system_type:
                            case "ALY_GEN1":
                                await ally_gen1.process_event(
                                    self,
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

    @staticmethod
    def restore_hidden():
        """
        Deleting hidden events
        :return:
        """
        for hidden_event in HIDE_PATH.iterdir():
            logger.debug(f'Restoring {hidden_event}')
            hidden_event.rename(
                Path("/dev/input/") / hidden_event
            )

    @staticmethod
    def restore_device(
            event: str,
            path: Path
    ):
        """
        Both devices threads will attempt this,
        so ignore if they have been moved.
        :param event:
        :param path:
        :return:
        """
        hide_event_path = HIDE_PATH / event
        if hide_event_path.exists():
            hide_event_path.rename(path)

    @staticmethod
    def remove_device(
            path: Path,
            event: str
    ):
        """
        Remove device
        :param path:
        :param event:
        :return:
        """
        device_path = path / event
        if device_path.exists():
            device_path.unlink(missing_ok=True)

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
        level=logging.DEBUG
    )

    HandheldController()
