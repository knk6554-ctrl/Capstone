"""Compatibility shim: both wrist devices now use USB serial."""

from .serial_wrist import SerialWristController, WristStatus

BleWristController = SerialWristController

__all__ = ["BleWristController", "SerialWristController", "WristStatus"]
