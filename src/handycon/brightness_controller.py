import logging
import pathlib


logger = logging.getLogger('handycon')


class ScreenBrightnessController:

    def __init__(self):
        self.current_brightness = self.get_current_brightness()

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
            (self.display_path / 'actual_brightness').write_text(f'{value}\n')
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
            assert value <= self.max_brightness, \
                'New value is bigger than display brightness max value'
            assert value >= 0, \
                f'Wrong value for screen brightness: {value}'
            assert value != self.get_current_brightness(), \
                'New value == current brightness value'
            self.set_display_brightness(value)
        except Exception as error:
            logger.debug(f'Cant assign new value: {type(error)}{error}')
            return False

    def increase_brightness(self, value: int = 10):
        current_brightness = self.get_current_brightness()
        self.set_brightness(
            current_brightness + value
        )

    def decrease_brightness(self, value: int = 10):
        current_brightness = self.get_current_brightness()
        self.set_brightness(
            current_brightness - value
        )
