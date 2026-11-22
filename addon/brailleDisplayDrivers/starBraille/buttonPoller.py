# -*- coding: utf-8 -*-
# Copyright (C) 2026 starBrailleForNVDAAddon contributors
# This file is covered by the GNU General Public License, version 2 or later.

"""Button state processing for the Star Braille display."""

from collections.abc import Callable

from .protocol import NO_BUTTON


class ButtonPoller:
	"""Turn consecutive button ids into press callbacks."""

	def __init__(self, on_press: Callable[[int], None]):
		self._on_press = on_press
		self._previous = NO_BUTTON

	def reset(self) -> None:
		"""Forget the held button, e.g. after a reconnect."""
		self._previous = NO_BUTTON

	def update(self, button_id: int) -> None:
		"""Feed the currently held button and report a new press."""
		pressed = button_id != NO_BUTTON and button_id != self._previous
		self._previous = button_id
		if pressed:
			self._on_press(button_id)
