import os
import asyncio
import logging
import subprocess
from pathlib import Path

from typing import Optional

# Partial imports
from evdev import \
    ff, \
    ecodes as e, \
    InputEvent, \
    UInput

from .constants import \
    CONTROLLER_EVENTS, \
    CHIMERA_LAUNCHER_PATH, \
    FF_DELAY, \
    INSTANT_EVENTS, QUEUED_EVENTS

from .device_explorer import DeviceExplorer


logger = logging.getLogger('handycon')


class EventEmitter(DeviceExplorer):
    # Stores inng button presses to block spam
    event_queue: list[InputEvent] = []
    last_button: Optional[list[int]] = None
    last_x_val: int = 0
    last_y_val: int = 0

    # Performance settings
    performance_mode: str = "--power-saving"
    thermal_mode: str = "0"

    def __init__(self):
        DeviceExplorer.__init__(self)
        self.ui_device = UInput(
            CONTROLLER_EVENTS,
            name='Handheld Controller',
            bustype=0x3,
            vendor=0x045e,
            product=0x028e,
            version=0x110
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

        # steam_path = self.HOME_PATH / '.steam/root/ubuntu12_32/steam'
        steam_path = 'steam'
        try:
            cmd = ' '.join([
                "su", self.USER, "-c", f"'{steam_path} -ifrunning {cmd}'"
            ])
            logger.debug(cmd)
            result = subprocess.run(cmd)
            return result.returncode == 0
        except Exception as err:
            logger.error(f"{err} | Error sending and to Steam.")
            logger.exception(err)
            return False

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
