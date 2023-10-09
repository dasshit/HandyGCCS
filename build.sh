#!/bin/bash
rm /usr/lib/python3.11/site-packages/__init__.py
git pull
./remove.sh
python -m build --wheel --no-isolation
sudo python -m installer dist/*.whl
sudo cp -r usr/ /
sudo systemd-hwdb update
sudo udevadm control -R
