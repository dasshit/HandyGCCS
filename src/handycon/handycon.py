"""
!/usr/bin/env python3
This file is part of Handheld Game Console Controller System (HandyGCCS)
Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>
"""


# Python Modules
import asyncio
import configparser
import logging
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import warnings
from typing import Literal, Union, Optional

# Local modules
from .constants import \
    CHIMERA_LAUNCHER_PATH, \
    HIDE_PATH, POWER_ACTION_MAP, EVENT_MAP, CONFIG_PATH, CONFIG_DIR, \
    DETECT_DELAY, INSTANT_EVENTS, QUEUED_EVENTS, FF_DELAY, CONTROLLER_EVENTS
from . import devices
from .devices import remove_device
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
from pathlib import Path
# Partial imports
from evdev import \
    ecodes as e, \
    ff, \
    InputDevice, \
    InputEvent, \
    list_devices, \
    UInput


warnings.filterwarnings("ignore", category=DeprecationWarning)


class HandheldController:
    """
    Main class for catching controller/keyboard events
    """
    logger = logging.getLogger(__name__)

    # Session Variables
    config: Optional[configparser.ConfigParser] = None
    button_map: dict[str, list[list[int]]] = {}
    # Stores inng button presses to block spam
    event_queue: list[InputEvent] = []
    last_button: Optional[list[int]] = None
    last_x_val: int = 0
    last_y_val: int = 0
    power_action: Literal["Hibernate", "Suspend", "Shutdown"] = "Suspend"
    running: bool = False
    shutdown: bool = False

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
    USER: str = None
    HOME_PATH: Path = None

    # UInput Devices
    controller_device = None
    keyboard_device = None
    keyboard_2_device = None
    power_device = None
    power_device_2 = None

    # Paths
    controller_event = None
    controller_path = None
    keyboard_event = None
    keyboard_path = None
    keyboard_2_event = None
    keyboard_2_path = None

    # Performance settings
    performance_mode: str = "--power-saving"
    thermal_mode: str = "0"

    def __init__(self):
        self.running = True
        self.logger.info(
            "Starting Handhend Game Console Controller Service..."
        )
        if self.is_process_running("opengamepadui"):
            self.logger.warning(
                "Detected an OpenGamepadUI Process. "
                "Input management not possible. Exiting."
            )
            exit()
        Path(HIDE_PATH).mkdir(parents=True, exist_ok=True)
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
        self.system_type = 'Generic System'

        # Run asyncio loop to capture all events.
        self.loop = asyncio.get_event_loop()

        # Attach the event loop of each device to the asyncio loop.
        asyncio.ensure_future(self.capture_controller_events())
        asyncio.ensure_future(self.capture_ff_events())
        asyncio.ensure_future(self.capture_keyboard_events())
        if self.KEYBOARD_2_NAME != '' and self.KEYBOARD_2_ADDRESS != '':
            asyncio.ensure_future(self.capture_keyboard_2_events())

        asyncio.ensure_future(self.capture_power_events())
        self.logger.info("Handheld Game Console Controller Service started.")

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
            self.logger.info("Keyboard interrupt.")
            exit_code = 1
        except Exception as err:
            self.logger.error(f"{err} | Hit exception condition.")
            self.logger.exception(err)
            exit_code = 2
        finally:
            self.loop.stop()
            sys.exit(exit_code)

    # Match runtime variables to the config
    def map_config(self):
        """
        Assign config file values for buttons and power button
        :return:
        """
        self.button_map = {
            "button1": EVENT_MAP[self.config["Button Map"]["button1"]],
            "button2": EVENT_MAP[self.config["Button Map"]["button2"]],
            "button3": EVENT_MAP[self.config["Button Map"]["button3"]],
            "button4": EVENT_MAP[self.config["Button Map"]["button4"]],
            "button5": EVENT_MAP[self.config["Button Map"]["button5"]],
            "button6": EVENT_MAP[self.config["Button Map"]["button6"]],
            "button7": EVENT_MAP[self.config["Button Map"]["button7"]],
            "button8": EVENT_MAP[self.config["Button Map"]["button8"]],
            "button9": EVENT_MAP[self.config["Button Map"]["button9"]],
            "button10": EVENT_MAP[self.config["Button Map"]["button10"]],
            "button11": EVENT_MAP[self.config["Button Map"]["button11"]],
            "button12": EVENT_MAP[self.config["Button Map"]["button12"]],
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
        if not os.path.exists(CONFIG_DIR):
            os.mkdir(CONFIG_DIR)

        with open(CONFIG_PATH, 'w') as config_file:
            self.config.write(config_file)
            self.logger.info(f"Created new config: {CONFIG_PATH}")

    def get_config(self):
        """
        Getting config from /etc/handygccs/handygccs.conf
        :return:
        """
        # Check for an existing config file and load it.
        self.config: configparser.ConfigParser = configparser.ConfigParser()
        if os.path.exists(CONFIG_PATH):
            self.logger.info(f"Loading existing config: {CONFIG_PATH}")
            self.config.read(CONFIG_PATH)
            if "power_button" not in self.config["Button Map"]:
                self.logger.info(
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

    def launch_chimera(self):
        """
        Launching Chimera App
        :return:
        """
        if not self.HAS_CHIMERA_LAUNCHER:
            return
        subprocess.run(["su", self.USER, "-c", CHIMERA_LAUNCHER_PATH])

    def is_process_running(self, name: str) -> bool:
        """
        Checking if process with name running
        :param name: Process name
        :return:
        """
        cmd = f"ps -Af | egrep '{name}' | egrep 'grep' -v | wc -l"
        read_proc = os.popen(cmd).read()
        proc_count = int(read_proc)
        if proc_count > 0:
            self.logger.debug(f'Process {name} is running.')
            return True
        self.logger.debug(f'Process {name} is NOT running.')
        return False

    def steam_ifrunning_deckui(self, cmd: str) -> bool:
        """
        Get the currently running Steam PID.
        :param cmd:
        :return:
        """
        steampid_path = self.HOME_PATH + '/.steam/steam.pid'
        try:
            with open(steampid_path) as f:
                pid = f.read().strip()
        except Exception as err:
            self.logger.error(f"{err} | Error getting steam PID.")
            self.logger.exception(err)
            return False

        # Get the andline for the Steam process by checking /proc.
        steam_cmd_path = f"/proc/{pid}/cmdline"
        if not os.path.exists(steam_cmd_path):
            # Steam not running.
            return False

        try:
            with open(steam_cmd_path, "rb") as f:
                steam_cmd = f.read()
        except Exception as err:
            self.logger.error(f"{err} | Error getting steam cmdline.")
            self.logger.exception(err)
            return False

            # Use this andline to determine if Steam is running in DeckUI mode.
        # e.g. "steam://shortpowerpress" only works in DeckUI.
        is_deckui = b"-gamepadui" in steam_cmd
        if not is_deckui:
            return False

        steam_path = self.HOME_PATH + '/.steam/root/ubuntu12_32/steam'
        try:
            result = subprocess.run([
                "su", self.USER, "-c", f"{steam_path} -ifrunning {cmd}"
            ])
            return result.returncode == 0
        except Exception as err:
            self.logger.error(f"{err} | Error sending and to Steam.")
            self.logger.exception(err)
            return False

    def get_user(self):
        """
        Capture the username
        and home path of the user who has been logged in the longest.
        :return:
        """
        self.logger.debug("Identifying user.")
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

        self.logger.debug(f"USER: {self.USER}")
        self.HOME_PATH = "/home/" + self.USER
        self.logger.debug(f"HOME_PATH: {self.HOME_PATH}")

    # Identify the current device type. Kill script if not atible.
    def id_system(self):
        """
        Identify system and set self attrs of controller and keyboards
        :return:
        """
        system_id = pathlib.Path(
            "/sys/devices/virtual/dmi/id/product_name").read_text().strip()
        cpu_vendor = self.get_cpu_vendor()
        self.logger.debug(f"Found CPU Vendor: {cpu_vendor}")

        # ANBERNIC Devices
        if system_id in (
                "Win600",
        ):
            self.system_type = "ANB_GEN1"
            anb_gen1.init_handheld(self)

        # AOKZOE Devices
        elif system_id in (
                "AOKZOE A1 AR07",
        ):
            self.system_type = "AOK_GEN1"
            aok_gen1.init_handheld(self)

        elif system_id in (
                "AOKZOE A1 Pro",
        ):
            self.system_type = "AOK_GEN2"
            aok_gen2.init_handheld(self)

        # ASUS Devices
        elif system_id in (
                "ROG Ally RC71L_RC71L",
        ):
            self.system_type = "ALY_GEN1"
            ally_gen1.init_handheld(self)

        # Aya Neo Devices
        elif system_id in (
                "AYA NEO FOUNDER",
                "AYA NEO 2021",
                "AYANEO 2021",
                "AYANEO 2021 Pro",
                "AYANEO 2021 Pro Retro Power",
        ):
            self.system_type = "AYA_GEN1"
            aya_gen1.init_handheld(self)

        elif system_id in (
                "NEXT",
                "NEXT Pro",
                "NEXT Advance",
                "AYANEO NEXT",
                "AYANEO NEXT Pro",
                "AYANEO NEXT Advance",
        ):
            self.system_type = "AYA_GEN2"
            aya_gen2.init_handheld(self)

        elif system_id in (
                "AIR",
                "AIR Pro",
        ):
            self.system_type = "AYA_GEN3"
            aya_gen3.init_handheld(self)

        elif system_id in (
                "AYANEO 2",
                "GEEK",
        ):
            self.system_type = "AYA_GEN4"
            aya_gen4.init_handheld(self)

        elif system_id in (
                "AIR Plus",
        ):
            if cpu_vendor == "GenuineIntel":
                self.system_type = "AYA_GEN7"
                aya_gen7.init_handheld(self)
            else:
                self.system_type = "AYA_GEN5"
                aya_gen5.init_handheld(self)

        elif system_id in (
                "AYANEO 2S",
                "GEEK 1S",
                "AIR 1S",
        ):
            self.system_type = "AYA_GEN6"
            aya_gen6.init_handheld(self)

        # Ayn Devices
        elif system_id in (
                "Loki Max",
        ):
            self.system_type = "AYN_GEN1"
            ayn_gen1.init_handheld(self)

        elif system_id in (
                "Loki Zero",
        ):
            self.system_type = "AYN_GEN2"
            ayn_gen2.init_handheld(self)

        elif system_id in (
                "Loki MiniPro",
        ):
            self.system_type = "AYN_GEN3"
            ayn_gen3.init_handheld(self)

        # GPD Devices.
        # Have 2 buttons with 3 modes (left, right, both)
        elif system_id in (
                "G1618-03",  # Win3
        ):
            self.system_type = "GPD_GEN1"
            gpd_gen1.init_handheld(self)

        elif system_id in (
                "G1619-04",  # WinMax2
        ):
            self.system_type = "GPD_GEN2"
            gpd_gen2.init_handheld(self)

        elif system_id in (
                "G1618-04",  # Win4
        ):
            self.system_type = "GPD_GEN3"
            gpd_gen3.init_handheld(self)

        # ONEXPLAYER and AOKZOE devices.
        # BIOS have inlete DMI data
        # and most models report as "ONE XPLAYER" or "ONEXPLAYER".
        elif system_id in (
                "ONE XPLAYER",
                "ONEXPLAYER",
        ):

            # GEN 1
            if cpu_vendor == "GenuineIntel":
                self.system_type = "OXP_GEN1"
                oxp_gen1.init_handheld(self)

            # GEN 2
            else:
                self.system_type = "OXP_GEN2"
                oxp_gen2.init_handheld(self)

        # GEN 3
        elif system_id in (
                "ONEXPLAYER mini A07",
        ):
            self.system_type = "OXP_GEN3"
            oxp_gen3.init_handheld(self)

        # GEN 4
        elif system_id in (
                "ONEXPLAYER Mini Pro",
        ):
            self.system_type = "OXP_GEN4"
            oxp_gen4.init_handheld(self)

        # GEN 5
        # elif system_id in (
        #     "ONEXPLAYER 2",
        #     "ONEXPLAYER 2 Pro",
        # ):
        #    self.system_type = "OXP_GEN5"
        #    oxp_gen5.init_handheld(self)

        # GEN 6
        elif system_id in (
                "ONEXPLAYER F1",
        ):
            self.system_type = "OXP_GEN6"
            oxp_gen6.init_handheld(self)

        # Devices that aren't supported could cause issues, exit.
        else:
            self.logger.error(
                f"{system_id} is not currently supported by this tool. "
                f"Open an issue on Github "
                f"at https://github.ShadowBlip/HandyGCCS if this is a bug. "
                f"If possible, se run the capture-system.py "
                f"utility found on the GitHub repository "
                f"and upload the file with your issue."
            )
            sys.exit(0)
        self.logger.info(
            f"Identified host system as {system_id} "
            f"and configured defaults for {self.system_type}."
        )

    # Gracefull shutdown.
    async def exit(self):
        """
        Method for graceful shutdown of handycon
        :return:
        """
        self.logger.info("Receved exit signal. Restoring devices.")
        self.running = False

        if self.controller_device:
            try:
                self.controller_device.ungrab()
            except IOError:
                pass
            devices.restore_device(self.controller_event, self.controller_path)
        if self.keyboard_device:
            try:
                self.keyboard_device.ungrab()
            except IOError:
                pass
            devices.restore_device(self.keyboard_event, self.keyboard_path)
        if self.keyboard_2_device:
            try:
                self.keyboard_2_device.ungrab()
            except IOError:
                pass
            devices.restore_device(self.keyboard_2_event, self.keyboard_2_path)
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
        self.logger.info("Devices restored.")

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
                self.logger.exception(err)
        self.loop.stop()
        self.logger.info("Handheld Game Console Controller Service stopped.")

    def get_controller(self) -> bool:
        """
        Getting controller device
        :return:
        """
        # Identify system input event devices.
        self.logger.debug(f"Attempting to grab {self.GAMEPAD_NAME}.")
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        except Exception as error:
            self.logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            self.logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False

        # Grab the built-in devices.
        # This will give us exclusive acces to the devices
        # and their capabilities.
        for device in devices_original:
            if device.name == self.GAMEPAD_NAME \
                    and device.phys == self.GAMEPAD_ADDRESS:
                self.controller_path = device.path
                self.controller_device = InputDevice(
                    self.controller_path
                )
                if self.CAPTURE_CONTROLLER:
                    self.controller_device.grab()
                    self.controller_event = Path(
                        self.controller_path).name
                    shutil.move(
                        self.controller_path,
                        str(HIDE_PATH / self.controller_event)
                    )
                break

        # Sometimes the service loads
        # before all input devices have full initialized. Try a few times.
        if not self.controller_device:
            self.logger.warning(
                "Controller device not yet found. Restarting scan."
            )
            time.sleep(DETECT_DELAY)
            return False
        else:
            self.logger.info(
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
        self.logger.debug(f"Attempting to grab {self.KEYBOARD_NAME}.")
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        except Exception as error:
            self.logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            self.logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False
        # Grab the built-in devices.
        # This will give us exclusive acces to the devices
        # and their capabilities.
        for device in devices_original:
            self.logger.debug(f"{device.name}, {device.phys}")
            if device.name == self.KEYBOARD_NAME \
                    and device.phys == self.KEYBOARD_ADDRESS:
                self.keyboard_path = device.path
                self.keyboard_device = InputDevice(self.keyboard_path)
                if self.CAPTURE_KEYBOARD:
                    self.keyboard_device.grab()
                    self.keyboard_event = Path(self.keyboard_path).name
                    shutil.move(
                        self.keyboard_path,
                        str(HIDE_PATH / self.keyboard_event)
                    )
                break

        # Sometimes the service loads
        # before all input devices have full initialized. Try a few times.
        if not self.keyboard_device:
            self.logger.warning(
                "Keyboard device not yet found. Restarting scan.")
            time.sleep(DETECT_DELAY)
            return False
        else:
            self.logger.info(
                f"Found {self.keyboard_device.name}. Capturing input data."
            )
            return True

    def get_keyboard_2(self) -> bool:
        """
        Getting keyboard
        :return:
        """
        self.logger.debug(
            f"Attempting to grab {self.KEYBOARD_2_NAME}.")
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        except Exception as error:
            self.logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            self.logger.exception(error)
            time.sleep(DETECT_DELAY)
            return False

        # Grab the built-in devices.
        # This will give us exclusive acces
        # to the devices and their capabilities.
        for device in devices_original:
            self.logger.debug(f"{device.name}, {device.phys}")
            if device.name == self.KEYBOARD_2_NAME \
                    and device.phys == self.KEYBOARD_2_ADDRESS:
                self.keyboard_2_path = device.path
                self.keyboard_2_device = InputDevice(self.keyboard_2_path)
                if self.CAPTURE_KEYBOARD:
                    self.keyboard_2_device.grab()
                    self.keyboard_2_event = Path(
                        self.keyboard_2_path).name
                    shutil.move(
                        self.keyboard_2_path,
                        str(HIDE_PATH / self.keyboard_2_event)
                    )
                break

        # Sometimes the service loads
        # before all input devices have full initialized. Try a few times.
        if not self.keyboard_2_device:
            self.logger.warning(
                "Keyboard device 2 not yet found. Restarting scan."
            )
            time.sleep(DETECT_DELAY)
            return False
        else:
            self.logger.info(
                f"Found {self.keyboard_2_device.name}. Capturing input data."
            )
            return True

    def get_powerkey(self):
        """
        Getting power button
        :return:
        """
        self.logger.debug("Attempting to grab power buttons.")
        # Identify system input event devices.
        try:
            devices_original = [InputDevice(path) for path in list_devices()]
        # Some funky stuff happens sometimes when booting.
        # Give it another shot.
        except Exception as error:
            self.logger.error(
                "Error when scanning event devices. Restarting scan."
            )
            self.logger.exception(error)
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
                self.logger.debug(
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
                self.logger.debug(
                    f"found alternate power device {self.power_device_2.phys}"
                )
                if self.CAPTURE_POWER:
                    self.power_device_2.grab()

        if not self.power_device and not self.power_device_2:
            self.logger.warning("No Power Button found. Restarting scan.")
            time.sleep(DETECT_DELAY)
            return False
        else:
            if self.power_device:
                self.logger.info(
                    f"Found {self.power_device.name}. Capturing input data."
                )
            if self.power_device_2:
                self.logger.info(
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
                        self.logger.debug(
                            f"Seed Value: {seed_event.value}, "
                            f"Seed Code: {seed_event.code}, "
                            f"Seed Type: {seed_event.type}."
                        )
                        if active_keys:
                            self.logger.debug(
                                f"Active Keys: {active_keys}")
                        else:
                            self.logger.debug("No active keys")
                        if self.event_queue:
                            self.logger.debug(
                                f"Queued events: {self.event_queue}"
                            )
                        else:
                            self.logger.debug("No active events.")

                        # Capture keyboard events
                        # and translate them to mapped events.
                        match self.system_type:
                            case "ALY_GEN1":
                                await ally_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "ANB_GEN1":
                                await anb_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AOK_GEN1":
                                await aok_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AOK_GEN2":
                                await aok_gen2.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN1":
                                await aya_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN2":
                                await aya_gen2.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN3":
                                await aya_gen3.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN4":
                                await aya_gen4.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN5":
                                await aya_gen5.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN6":
                                await aya_gen6.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYA_GEN7":
                                await aya_gen7.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYN_GEN1":
                                await ayn_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYN_GEN2":
                                await ayn_gen2.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "AYN_GEN3":
                                await ayn_gen3.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "GPD_GEN1":
                                await gpd_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "GPD_GEN2":
                                await gpd_gen2.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "GPD_GEN3":
                                await gpd_gen3.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "OXP_GEN1":
                                await oxp_gen1.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "OXP_GEN2":
                                await oxp_gen2.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "OXP_GEN3":
                                await oxp_gen3.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            case "OXP_GEN4":
                                await oxp_gen4.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )
                            # case "OXP_GEN5":
                            #    await oxp_gen5.process_event(
                            #                                 seed_event,
                            #                                 active_keys
                            #                             )
                            case "OXP_GEN6":
                                await oxp_gen6.process_event(
                                    self,
                                    seed_event,
                                    active_keys
                                )

                except Exception as err:
                    self.logger.error(
                        f"{err} | "
                        f"Error reading events from "
                        f"{self.keyboard_device.name}"
                    )
                    self.logger.exception(err)
                    remove_device(HIDE_PATH, self.keyboard_event)
                    self.keyboard_device = None
                    self.keyboard_event = None
                    self.keyboard_path = None
            else:
                self.logger.info("Attempting to grab keyboard device...")
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
                        self.logger.debug(
                            f"Seed Value: {seed_event_2.value}, "
                            f"Seed Code: {seed_event_2.code}, "
                            f"Seed Type: {seed_event_2.type}."
                        )
                        if active_keys_2:
                            self.logger.debug(
                                f"Active Keys: {active_keys_2}")
                        else:
                            self.logger.debug("No active keys")
                        if self.event_queue:
                            self.logger.debug(
                                f"Queued events: {self.event_queue}"
                            )
                        else:
                            self.logger.debug("No active events.")

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
                    self.logger.error(
                        f"{err} | "
                        f"Error reading events "
                        f"from {self.keyboard_2_device.name}"
                    )
                    self.logger.exception(err)
                    remove_device(HIDE_PATH, self.keyboard_2_event)
                    self.keyboard_2_device = None
                    self.keyboard_2_event = None
                    self.keyboard_2_path = None
            else:
                self.logger.info("Attempting to grab keyboard device 2...")
                self.get_keyboard_2()
                await asyncio.sleep(DETECT_DELAY)

    async def capture_controller_events(self):
        """
        Capture keyboard events and translate them to mapped events.
        :return:
        """
        self.logger.debug(f"capture_controller_events, {self.running}")
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
                    self.logger.error(
                        f"{err} | "
                        f"Error reading events from "
                        f"{self.controller_device.name}."
                    )
                    self.logger.exception(err)
                    remove_device(HIDE_PATH, self.controller_event)
                    self.controller_device = None
                    self.controller_event = None
                    self.controller_path = None
            else:
                self.logger.info("Attempting to grab controller device...")
                self.get_controller()
                await asyncio.sleep(DETECT_DELAY)

    async def capture_power_events(self):
        """
        Captures power events and handles long or short press events.
        :return:
        """
        if self.power_device is not None:
            power_key = self.power_device
        elif self.power_device_2 is not None:
            power_key = self.power_device_2
        else:
            self.logger.warning(
                'Power device is undefined, searching for it...')
            self.logger.warning(
                "Attempting to grab controller device...")
            self.get_powerkey()
            await asyncio.sleep(DETECT_DELAY)
            return

        while self.running:
            try:
                async for event in power_key.async_read_loop():
                    self.logger.debug(
                        f"Got event: "
                        f"{event.type} | {event.code} | {event.value}"
                    )
                    if event.type == e.EV_KEY and event.code == 116:
                        # KEY_POWER
                        if event.value == 0:
                            self.handle_power_action()

            except Exception as err:
                self.logger.error(
                    f"{err} | Error reading events from power device."
                )
                self.logger.exception(err)
                self.power_device = None
                self.power_device_2 = None

                self.logger.info("Attempting to grab controller device...")
                self.get_powerkey()
                await asyncio.sleep(DETECT_DELAY)

    def handle_power_action(self):
        """
        Performs specific power actions based on user config.
        :return:
        """
        self.logger.debug(f"Power Action: {self.power_action}")
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
                        effect)
                    effect.id = effect_id

                    ff_effect_id_set.add(effect_id)

                    upload.retval = 0
                except IOError as err:
                    self.logger.error(
                        f"{err} | Error uploading effect {effect.id}."
                    )
                    self.logger.exception(err)
                    upload.retval = -1

                self.ui_device.end_upload(upload)

            elif event.code == e.UI_FF_ERASE:
                erase = self.ui_device.begin_erase(event.value)

                try:
                    self.controller_device.erase_effect(erase.effect_id)
                    ff_effect_id_set.remove(erase.effect_id)
                    erase.retval = 0
                except IOError as err:
                    self.logger.error(
                        f"{err} | Error erasing effect {erase.effect_id}."
                    )
                    self.logger.exception(err)
                    erase.retval = -1

                self.ui_device.end_erase(erase)

    def restore_hidden(self):
        """
        Deleting hidden events
        :return:
        """
        for hidden_event in os.listdir(HIDE_PATH):
            self.logger.debug(f'Restoring {hidden_event}')
            shutil.move(
                str(HIDE_PATH / hidden_event),
                "/dev/input/" + hidden_event
            )

    async def emit_events(self, events: list[InputEvent]):
        """
        Emits passed or generated events to the virtual controller.
        This shouldn't be called directly for custom events,
        only to pass realtime events.
        Use emit_now and the device's event_queue.
        :param events: InputEvents list
        :return:
        """
        self.logger.debug(f'events: {type(events)}')

        for event in events:
            self.logger.debug(type(event))
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
        self.logger.debug(f"Emitting event: {event}")
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
            self.logger.error(
                "emit_now received malfirmed event_list. No action"
            )
            return

        # Handle string events
        if isinstance(event_list[0], str):
            if value == 0:
                self.logger.debug(
                    "Received string event with value 0. "
                    "KEY_UP event not required. Skipping"
                )
                return
            match event_list[0]:
                case "Open Chimera":
                    self.logger.debug(
                        "Open Chimera"
                    )
                    self.launch_chimera()
                case "Toggle Gyro":
                    self.logger.debug(
                        "Toggle Gyro is not currently enabled"
                    )
                case "Toggle Mouse Mode":
                    self.logger.debug(
                        "Toggle Mouse Mode is not currently enabled"
                    )
                case "Toggle Performance":
                    self.logger.debug("Toggle Performance")
                    await self.toggle_performance()
                case "Hibernate", "Suspend", "Shutdown":
                    self.logger.error(
                        f"Power mode {event_list[0]} set to button action. "
                        f"Check your configuration file."
                    )
                case _:
                    self.logger.warning(f"{event_list[0]} not defined.")
            return

        self.logger.debug(f'Event list: {event_list}')
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
        self.logger.debug(f'seed_event: {type(seed_event)}')
        self.logger.debug(f'queued_event: {type(queued_event)}')
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
        self.logger.debug(run)

        if self.system_type in ["ALY_GEN1"]:
            if self.thermal_mode == "1":
                self.thermal_mode = "0"
            else:
                self.thermal_mode = "1"

            command = f'echo {self.thermal_mode} > ' \
                      f'/sys/devices/' \
                      f'platform/asus-nb-wmi/throttle_thermal_policy'
            os.popen(command, buffering=1).read().strip()
            self.logger.debug(
                f'Thermal mode set to {self.thermal_mode}.')


def main():
    """
    Start of handycon
    :return:
    """
    logging.basicConfig(
        format='[%(levelname)s] -  %(name)s - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s',
        level=logging.DEBUG
    )

    HandheldController()
