#!/usr/bin/env python3
# This file is part of Handheld Game Console Controller System (HandyGCCS)
# Copyright 2022-2023 Derek J. Clark <derekjohn.clark@gmail.com>

# Python Modules
import os
import shutil
from .constants import HIDE_PATH

import logging


logger = logging.getLogger(__name__)


def restore_device(event, path):
    logger.debug(f'event: {type(event)}')
    logger.debug(f'path: {type(path)}')
    # Both devices threads will attempt this,
    # so ignore if they have been moved.
    try:
        shutil.move(str(HIDE_PATH / event), path)
    except FileNotFoundError:
        pass


def remove_device(path, event):
    logger.debug(f'path: {type(path)}')
    logger.debug(f'event: {type(event)}')
    try:
        os.remove(str(path / event))
    except FileNotFoundError:
        pass
