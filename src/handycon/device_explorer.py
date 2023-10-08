import re
import time
import logging
import subprocess
import configparser

from typing import Optional, Literal, Union
from pathlib import Path

from .constants import \
    HIDE_PATH, \
    CHIMERA_LAUNCHER_PATH, \
    CONFIG_DIR, \
    CONFIG_PATH, \
    EVENT_MAP, \
    POWER_ACTION_MAP, \
    DETECT_DELAY
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
    InputEvent, \
    InputDevice, \
    list_devices


logger = logging.getLogger('handycon')


class DeviceExplorer:
    # Session Variables
    config: Optional[configparser.ConfigParser] = None
    button_map: dict[str, list[list[int]]] = {}

    # Enviroment Variables
    HAS_CHIMERA_LAUNCHER: bool = False
    USER: Optional[str] = None
    HOME_PATH: Optional[Path] = None

    # Stores inng button presses to block spam
    power_action: Literal["Hibernate", "Suspend", "Shutdown"] = "Suspend"
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

    def __init__(self):
        HIDE_PATH.mkdir(parents=True, exist_ok=True)
        self.restore_hidden()
        self.get_user()
        self.HAS_CHIMERA_LAUNCHER = CHIMERA_LAUNCHER_PATH.is_file()
        self.id_system()
        self.get_config()

    async def process_event(
            self,
            seed_event: InputEvent,
            active_keys: list[int]
    ):
        """
        Captures keyboard events and translates them to virtual device events.
        :param seed_event:
        :param active_keys:
        :return:
        """
        logger.debug(
            f'self: {self}, '
            f'seed_event: {seed_event}, '
            f'active_keys: {active_keys}'
        )
        logger.warning('Method process_event not assigned right now!!!')

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

    def id_system(self):
        """
        Identify system and set self attrs of controller and keyboards
        :return:
        """
        system_id = Path(
            "/sys/devices/virtual/dmi/id/product_name").read_text().strip()
        cpu_vendor = self.get_cpu_vendor()
        logger.debug(f"Found CPU Vendor: {cpu_vendor}")

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
            logger.error(
                f"{system_id} is not currently supported by this tool. "
                f"Open an issue on Github "
                f"at https://github.ShadowBlip/HandyGCCS if this is a bug. "
                f"If possible, se run the capture-system.py "
                f"utility found on the GitHub repository "
                f"and upload the file with your issue."
            )
            exit(0)
        logger.info(
            f"Identified host system as {system_id} "
            f"and configured defaults for {self.system_type}."
        )

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
