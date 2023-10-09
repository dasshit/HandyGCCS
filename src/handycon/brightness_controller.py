import logging
import os
import pathlib


logger = logging.getLogger('handycon')


def mode_generator():
    while True:
        for mode in [
            'Direct',
            'Static',
            'Breathing',
            'Spectrum Cycle',
            'Rainbow Wave',
            'Strobing'
        ]:
            yield mode


class BrightnessController:

    def __init__(self):
        self.current_brightness = self.get_current_brightness()
        self.led_path = pathlib.Path(
            '/sys/class/leds/asus'
            '::kbd_backlight/device/leds/asus'
            '::kbd_backlight/brightness'
        )
        self.led_mods = mode_generator()

    @property
    def display_path(self) -> pathlib.Path:
        for path in pathlib.Path('/sys/class/backlight').iterdir():
            brightness_path = path / 'brightness'
            if brightness_path.exists():
                return path

    def get_current_brightness(self):
        return int(
            (self.display_path / 'actual_brightness').read_text()
        )

    @property
    def max_brightness(self):
        return int(
            (self.display_path / 'max_brightness').read_text()
        )

    def set_display_brightness(self, value: int) -> bool:
        try:
            (self.display_path / 'brightness').write_text(f'{value}\n')
            return True
        except Exception as error:
            logger.error(
                f'Error while setting new value '
                f'for screen ({self.display_path} brightness'
            )
            logger.exception(error)
            return False

    def set_brightness(self, value: int) -> bool:
        try:
            if value > self.max_brightness:
                value = self.max_brightness
            elif value < 0:
                value = 0
            assert value != self.get_current_brightness(), \
                'New value == current brightness value'
            self.set_display_brightness(value)
        except Exception as error:
            logger.debug(f'Cant assign new value: {type(error)}{error}')
            return False

    def increase_screen_brightness(self, value: int = 10):
        current_brightness = self.get_current_brightness()
        self.set_brightness(
            current_brightness + value
        )

    def decrease_screen_brightness(self, value: int = 10):
        current_brightness = self.get_current_brightness()
        self.set_brightness(
            current_brightness - value
        )

    def turn_led_on(self):
        os.system(
            "brightnessctl -d 'asus::kbd_backlight' s 33%"
        )

    def get_led_brightness(self) -> int:
        try:
            return int(
                self.led_path.read_text()
            )
        except Exception as error:
            logger.error(
                f'Error while setting new value '
                f'for led brightness'
            )
            logger.exception(error)
            return 0

    def set_led_brightness(self, value):
        if value < 0:
            value = 0
        elif value > 3:
            value = 3

        self.led_path.write_text(f'{value}\n')

    def increase_led_brightness(self):
        logger.info('Increasing led brightness')
        current_brightness = self.get_led_brightness()
        if current_brightness == 0:
            cmd = "brightnessctl -d 'asus::kbd_backlight' s 33%"
            logger.debug(cmd)
            os.system(cmd)
        else:
            self.set_led_brightness(
                current_brightness + 1
            )

    def decrease_led_brightness(self):
        logger.info('Decreasing led brightness')
        current_brightness = self.get_led_brightness()
        self.set_led_brightness(
            current_brightness - 1
        )

    def switch_led_mode(self):
        try:
            cmd = f"openrgb " \
                  f"-d 'ASUS ROG Ally' " \
                  f"-m '{next(self.led_mods)}' " \
                  f"--noautoconnect"
            logger.info(f'CMD: {cmd}')
            os.system(cmd)
        except Exception as error:
            logger.error(f'Error while setting new mode for led')
            logger.exception(error)
