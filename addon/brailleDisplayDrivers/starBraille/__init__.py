# -*- coding: utf-8 -*-
# Copyright (C) 2026 starBrailleForNVDAAddon contributors
# This file is covered by the GNU General Public License, version 2 or later.

"""NVDA driver addon for the Star Braille display."""

import bdDetect
import inputCore
from logHandler import log

from . import device, driver, protocol

try:
	# NVDA 2026.3 and later.
	from braille.display.driver import BrailleDisplayDriver as _BrailleDisplayDriver
	from braille.display.gesture import BrailleDisplayGesture
except ImportError:
	# NVDA 2024.1 through 2026.2.
	from braille import BrailleDisplayDriver as _BrailleDisplayDriver
	from braille import BrailleDisplayGesture

try:
	from bdDetect import ProtocolType
except ImportError:
	# ProtocolType and CommunicationType replaced DeviceType in NVDA 2025.1.
	# DeviceType remains as the older compatibility name.
	from bdDetect import DeviceType as ProtocolType

NAME = "starBraille"
DESCRIPTION = "Star Braille Display"

# Button physical layout:
# The six keys are on the user-facing side, in a plane perpendicular to the
# braille and routing-key surface.
# Left pair: button1 (ID 41), button2 (ID 42).
# Middle standalone keys: button3 (ID 43), button6 (ID 46).
# Right pair: button4 (ID 44), button5 (ID 45).
# Left to right across the device:
# button1, button2, button3, button6, button5, button4.
# Button id -> (neutral gesture id, default NVDA command).
_BUTTON_ACTIONS = {
	41: ("button1", "braille_previousLine"),
	42: ("button2", "braille_scrollBack"),
	43: ("button3", "kb:tab"),
	44: ("button4", "braille_nextLine"),
	45: ("button5", "braille_scrollForward"),
	46: ("button6", "kb:enter"),
}

_HAS_CELL_INDEXES = hasattr(BrailleDisplayGesture, "cellIndexes")


class StarBrailleGesture(BrailleDisplayGesture):
	"""Base class for gestures produced by the display."""

	source = NAME


class RoutingKeyGesture(StarBrailleGesture):
	"""A routing key press above one braille cell."""

	def __init__(self, cell_index: int):
		super().__init__()
		self.id = "routing"
		if _HAS_CELL_INDEXES:
			self.cellIndexes = [cell_index]
		else:
			self.routingIndex = cell_index


class ButtonGesture(StarBrailleGesture):
	"""One of the six function keys below the braille line."""

	def __init__(self, gesture_id: str):
		super().__init__()
		self.id = gesture_id


# Routing keys use the standard braille_routeTo script.  The six function keys
# get neutral names so that they can be remapped in NVDA's Input Gestures
# dialog without implying a fixed function.
_gestureMap = inputCore.GlobalGestureMap(
	{
		"globalCommands.GlobalCommands": {
			"braille_routeTo": (f"br({NAME}):routing",),
			**{
				command: (f"br({NAME}):{gesture_id}",)
				for gesture_id, command in _BUTTON_ACTIONS.values()
			},
		}
	}
)


class BrailleDisplayDriver(_BrailleDisplayDriver):
	"""NVDA braille display driver for the Star Braille display."""

	name = NAME
	description = DESCRIPTION
	isThreadSafe = True
	supportsAutomaticDetection = True
	gestureMap = _gestureMap

	@classmethod
	def check(cls) -> bool:
		"""Return whether a Star Braille display is currently connected."""
		try:
			if device.has_device():
				return True
		except Exception:
			log.debugWarning("Could not enumerate Star Braille displays", exc_info=True)
		# Also let bdDetect match the registered USB ID, in case the device
		# interface class cannot be enumerated for some reason.
		try:
			return super().check()
		except Exception:
			log.debugWarning("bdDetect check for Star Braille failed", exc_info=True)
			return False

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar) -> None:
		"""Let NVDA's automatic detection find the display by its USB ID."""
		# addUsbDevice was added in NVDA 2025.1.
		# Use addUsbDevices for NVDA 2024.1 through 2024.4.
		if hasattr(driverRegistrar, "addUsbDevice"):
			driverRegistrar.addUsbDevice(ProtocolType.CUSTOM, device.USB_ID)
		else:
			driverRegistrar.addUsbDevices(ProtocolType.CUSTOM, [device.USB_ID])

	@classmethod
	def getManualPorts(cls):
		# The display has no serial or Bluetooth variant.
		raise NotImplementedError

	def __init__(self, port="auto"):
		super().__init__()
		self.numCells = protocol.CELL_COUNT
		self._driver = None
		self._driver = driver.StarBrailleDriver(
			on_button=self._on_button,
			on_unavailable=self._on_unavailable,
		)

	def terminate(self) -> None:
		"""Clear the display, then stop polling and release the device."""
		try:
			super().terminate()
		finally:
			current = self._driver
			if current is not None:
				current.terminate()

	def display(self, cells) -> None:
		"""Send up to 40 braille cells to the display."""
		current = self._driver
		if current is not None:
			current.display(cells)

	def _on_button(self, button: int) -> None:
		gesture = self._gesture_for_button(button)
		if gesture is None:
			log.debug("Unknown Star Braille button id %r", button)
			return
		try:
			inputCore.manager.executeGesture(gesture)
		except inputCore.NoInputGestureAction:
			pass
		except Exception:
			log.error("Error while handling a Star Braille button", exc_info=True)

	def _on_unavailable(self) -> None:
		"""Return control to NVDA's automatic detection on the main thread."""
		try:
			import braille
			import core

			core.callLater(0, braille.handler.handleDisplayUnavailable)
		except Exception:
			log.debugWarning(
				"Could not notify NVDA that the Star Braille display is unavailable",
				exc_info=True,
			)

	@staticmethod
	def _gesture_for_button(button: int):
		if 1 <= button <= protocol.CELL_COUNT:
			return RoutingKeyGesture(button - 1)
		action = _BUTTON_ACTIONS.get(button)
		if action is None:
			return None
		return ButtonGesture(action[0])
