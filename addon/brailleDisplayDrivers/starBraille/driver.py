# -*- coding: utf-8 -*-
# Copyright (C) 2026 starBrailleForNVDAAddon contributors
# This file is covered by the GNU General Public License, version 2 or later.

"""Device lifecycle and button polling for the Star Braille display.

The driver owns the open device, the polling thread and the link state.
When the link is lost, it releases the device and reports it through a callback.
"""

import threading

from logHandler import log

from . import device, protocol
from .buttonPoller import ButtonPoller

POLL_INTERVAL = 0.05
STOP_TIMEOUT = 1.0

# A timeout is weaker evidence than a hard Win32 error.
# Reset the pipes after a few timeouts.
# Report the device as unavailable only if timeouts continue.
TIMEOUT_RESET_THRESHOLD = 5
TIMEOUT_UNAVAILABLE_THRESHOLD = 10
ERROR_UNAVAILABLE_THRESHOLD = 5

# Special return values from _query_button().
# A real result is a button id, including NO_BUTTON.
QUERY_TIMEOUT = -2
COMMUNICATION_FAILURE = -1


class StarBrailleDriver:
	"""Own the device connection and deliver button events."""

	def __init__(self, on_button=None, on_unavailable=None):
		self._on_button = on_button
		self._on_unavailable = on_unavailable

		self._device = None
		self._device_lock = threading.Lock()
		self._poller = ButtonPoller(self._emit_button)
		self._stop_event = threading.Event()
		self._poll_thread = None

		self._start()

	def _start(self) -> None:
		"""Connect to the display and start the polling thread.

		Calling this while the thread is running is a no-op.
		"""
		if self._poll_thread is not None:
			if self._poll_thread.is_alive():
				return
			self._close()

		found = device.find_device()
		if found is None:
			raise RuntimeError("No Star Braille display found")

		try:
			self._stop_event.clear()
			self._poller.reset()
			self._device = found
			self._poll_thread = threading.Thread(
				target=self._poll_buttons,
				name="starBrailleButtonPoller",
				daemon=True,
			)
			self._poll_thread.start()
		except Exception:
			self._close()
			raise

	def _close(self) -> None:
		"""Stop the polling thread and release the device."""
		self._stop_event.set()
		thread, self._poll_thread = self._poll_thread, None

		if (
			thread is not None
			and thread is not threading.current_thread()
			and thread.ident is not None
		):
			thread.join(STOP_TIMEOUT)
			if thread.is_alive():
				with self._device_lock:
					current = self._device
				if current is not None:
					current.abort()
				thread.join(STOP_TIMEOUT)

		with self._device_lock:
			current, self._device = self._device, None
		if current is not None:
			current.close()

	def terminate(self) -> None:
		"""Stop polling and release the device."""
		self._close()

	def display(self, cells) -> None:
		"""Send up to 40 braille cells to the display."""
		packet = protocol.build_show_packet(cells)
		with self._device_lock:
			current = self._device
			if current is None:
				return
			try:
				current.write(packet)
			except OSError:
				# The polling thread detects the broken link later.
				log.debug("Could not write to the Star Braille display", exc_info=True)

	def _poll_buttons(self) -> None:
		"""Poll the current button until stopped or the link is lost."""
		# Failure counters since the last valid answer.
		timeouts = 0
		errors = 0
		# Try at most one pipe reset per failure streak.
		reset_attempted = False

		while not self._stop_event.is_set():
			status = self._query_button()

			if status == QUERY_TIMEOUT:
				# A missing answer is weaker evidence than a hard error.
				timeouts, reset_attempted, unavailable = self._handle_timeout(
					timeouts, reset_attempted
				)
				if unavailable:
					self._notify_unavailable()
					return
			elif status == COMMUNICATION_FAILURE:
				# A hard error means the device is likely gone.
				errors += 1
				if errors >= ERROR_UNAVAILABLE_THRESHOLD:
					self._notify_unavailable()
					return
			else:
				# Any valid answer ends the failure streak.
				timeouts = 0
				errors = 0
				reset_attempted = False
				self._poller.update(status)

			self._stop_event.wait(POLL_INTERVAL)

	def _handle_timeout(self, timeouts: int, reset_attempted: bool) -> tuple[int, bool, bool]:
		"""Update the consecutive timeout state.

		Return the new timeout count, whether a reset was attempted,
		and whether the device should be reported as unavailable.
		"""
		timeouts += 1

		if timeouts >= TIMEOUT_RESET_THRESHOLD and not reset_attempted:
			reset_attempted = True
			if self._reset_pipes():
				log.debug("Reset Star Braille pipes after %d timeouts", timeouts)
				timeouts = 0

		unavailable = timeouts >= TIMEOUT_UNAVAILABLE_THRESHOLD
		return timeouts, reset_attempted, unavailable

	def _query_button(self) -> int:
		"""Return the current button state or a failure value.

		A valid answer is a button id, including NO_BUTTON.
		QUERY_TIMEOUT means the device did not answer.
		COMMUNICATION_FAILURE means a hard error or an invalid answer.
		"""
		open_device = self._device
		if open_device is None:
			return COMMUNICATION_FAILURE

		try:
			response = open_device.request(protocol.QUERY_PACKET, protocol.PACKET_SIZE)
		except OSError as error:
			log.debug("Star Braille button query failed: %s", error)
			if device.is_timeout_error(error):
				return QUERY_TIMEOUT
			return COMMUNICATION_FAILURE

		if not response:
			log.debug("Star Braille button query timed out")
			return QUERY_TIMEOUT

		button = protocol.parse_button_response(response)
		if button is None:
			log.debug("Unexpected Star Braille response: %r", response[:8])
			return COMMUNICATION_FAILURE
		return button

	def _reset_pipes(self) -> bool:
		"""Try to reset both bulk pipes."""
		open_device = self._device
		if open_device is None:
			return False
		try:
			return open_device.reset_pipes()
		except Exception:
			log.debugWarning("Could not reset Star Braille pipes", exc_info=True)
			return False

	def _notify_unavailable(self) -> None:
		"""Release the device and report it through the callback."""
		self._close()

		log.info("Star Braille display unavailable")
		if self._on_unavailable is not None:
			try:
				self._on_unavailable()
			except Exception:
				log.debugWarning("Error while reporting Star Braille unavailable", exc_info=True)

	def _emit_button(self, button: int) -> None:
		if self._on_button is None:
			return
		try:
			self._on_button(button)
		except Exception:
			log.error("Error while handling a Star Braille button", exc_info=True)
