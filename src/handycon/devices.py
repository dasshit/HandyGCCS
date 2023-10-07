"""
!/usr/bin/env python3
This file is part of Handheld Game Console Controller System (HandyGCCS)
Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>
"""

import os
import shutil
from pathlib import Path

from .constants import HIDE_PATH

import logging

from evdev import InputEvent


logger = logging.getLogger(__name__)


def restore_device(
        event: InputEvent,
        path: Path
):
    """
    Both devices threads will attempt this,
    so ignore if they have been moved.
    :param event:
    :param path:
    :return:
    """
    try:
        shutil.move(str(HIDE_PATH / event), path)
    except FileNotFoundError:
        pass


def remove_device(
        path: Path,
        event: InputEvent
):
    try:
        os.remove(str(path / event))
    except FileNotFoundError:
        pass
