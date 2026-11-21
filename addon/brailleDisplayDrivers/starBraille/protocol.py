# -*- coding: utf-8 -*-
# Copyright (C) 2026 starBrailleForNVDAAddon contributors
# This file is covered by the GNU General Public License, version 2 or later.

"""Protocol of the Star Braille display."""

CELL_COUNT = 40
PACKET_SIZE = 64
ENDPOINT_IN = 0x81
ENDPOINT_OUT = 0x01

COMMAND_SHOW = 0x80
COMMAND_QUERY = 0x81
BUTTON_INDEX = 1
NO_BUTTON = 0xFF

QUERY_PACKET = bytes((COMMAND_QUERY,)).ljust(PACKET_SIZE, b"\x00")
BLANK_PACKET = bytes((COMMAND_SHOW,)).ljust(PACKET_SIZE, b"\x00")


def build_show_packet(cells) -> bytes:
	"""Return the 64-byte packet which displays ``cells``."""
	cells = [cell & 0xFF for cell in cells[:CELL_COUNT]]
	return bytes((COMMAND_SHOW, *cells)).ljust(PACKET_SIZE, b"\x00")


def parse_button_response(response: bytes) -> int | None:
	"""Parse a button query response.

	@return: The button byte, or ``None`` if the response is invalid or incomplete.
	"""
	if not response:
		return None
	if response[0] != COMMAND_QUERY:
		return None
	if len(response) <= BUTTON_INDEX:
		return None
	return response[BUTTON_INDEX]
