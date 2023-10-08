#!/usr/bin/env python3
"""
This file is part of Handheld Game Console Controller System (HandyGCCS)
Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>
"""


# Python Modules
import asyncio
import logging
import signal
import sys
import warnings

# Local modules
from .event_emitter import EventEmitter
from .constants import \
    HIDE_PATH, \
    DETECT_DELAY

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


class HandheldController(EventEmitter):
    """
    Main class for catching controller/keyboard events
    """
    running: bool = True
    shutdown: bool = False

    def __init__(self):
        EventEmitter.__init__(self)

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
                        logger.debug('-----' * 10)

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

    async def exit(self):
        """
        Method for graceful shutdown of handycon
        :return:
        """
        logger.info("Receved exit signal. Restoring devices.")
        self.running = False

        for device, event, path in filter(
            lambda x: x[0] is not None,
            [
                (self.controller_device,
                 self.controller_event,
                 self.controller_path),
                (self.keyboard_device,
                 self.keyboard_event,
                 self.keyboard_path),
                (self.keyboard_2_device,
                 self.keyboard_2_event,
                 self.keyboard_2_path),
            ]
        ):
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
