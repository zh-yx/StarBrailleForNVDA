# -*- coding: utf-8 -*-
# Copyright (C) 2026 starBrailleForNVDAAddon contributors
# This file is covered by the GNU General Public License, version 2 or later.

"""SetupAPI discovery and handshake for the Star Braille display.

This module owns "which device is ours" and "does it answer the protocol handshake".
 It knows nothing about NVDA and leaves all resource release to :class:`winusb.WinUsbDevice.close`.
"""

import ctypes
from ctypes import wintypes

from . import protocol, winusb

USB_ID = "VID_04D8&PID_0053"
_HARDWARE_ID_FRAGMENT = "usb#vid_04d8&pid_0053"

TRANSFER_TIMEOUT_MS = 500
PROBE_TIMEOUT_MS = 2000


class _GUID(ctypes.Structure):
	_fields_ = (
		("Data1", wintypes.DWORD),
		("Data2", wintypes.WORD),
		("Data3", wintypes.WORD),
		("Data4", ctypes.c_ubyte * 8),
	)


# {58D07210-27C1-11DD-BD0B-0800200C9A66}, the interface class from the protocol.
_INTERFACE_GUID = _GUID(
	0x58D07210,
	0x27C1,
	0x11DD,
	(0xBD, 0x0B, 0x08, 0x00, 0x20, 0x0C, 0x9A, 0x66),
)


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
	_fields_ = (
		("cbSize", wintypes.DWORD),
		("InterfaceClassGuid", _GUID),
		("Flags", wintypes.DWORD),
		("Reserved", ctypes.c_void_p),
	)


setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

setupapi.SetupDiGetClassDevsW.argtypes = (
	ctypes.POINTER(_GUID),
	wintypes.LPCWSTR,
	wintypes.HWND,
	wintypes.DWORD,
)
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE

setupapi.SetupDiEnumDeviceInterfaces.argtypes = (
	wintypes.HANDLE,
	ctypes.c_void_p,
	ctypes.POINTER(_GUID),
	wintypes.DWORD,
	ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
)
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = (
	wintypes.HANDLE,
	ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
	ctypes.c_void_p,
	wintypes.DWORD,
	ctypes.POINTER(wintypes.DWORD),
	ctypes.c_void_p,
)
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL

setupapi.SetupDiDestroyDeviceInfoList.argtypes = (wintypes.HANDLE,)
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL


def device_paths() -> list[str]:
	"""Return the interface paths of present devices in the display class."""
	paths: list[str] = []
	device_info_set = setupapi.SetupDiGetClassDevsW(
		ctypes.byref(_INTERFACE_GUID),
		None,
		None,
		DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
	)
	if not device_info_set or device_info_set == INVALID_HANDLE_VALUE:
		return paths

	try:
		index = 0
		while True:
			interface = _SP_DEVICE_INTERFACE_DATA()
			interface.cbSize = ctypes.sizeof(interface)
			if not setupapi.SetupDiEnumDeviceInterfaces(
				device_info_set,
				None,
				ctypes.byref(_INTERFACE_GUID),
				index,
				ctypes.byref(interface),
			):
				break

			needed = wintypes.DWORD()
			setupapi.SetupDiGetDeviceInterfaceDetailW(
				device_info_set,
				ctypes.byref(interface),
				None,
				0,
				ctypes.byref(needed),
				None,
			)
			if needed.value:
				# SP_DEVICE_INTERFACE_DETAIL_DATA_W is a DWORD followed by a flexible WCHAR array.
				#  Its size is 8 on 64-bit Windows and 6  on 32-bit Windows; DevicePath always starts at offset 4.
				buffer = ctypes.create_string_buffer(needed.value)
				cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
				ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[0] = cb_size
				if setupapi.SetupDiGetDeviceInterfaceDetailW(
					device_info_set,
					ctypes.byref(interface),
					buffer,
					needed.value,
					None,
					None,
				):
					path = ctypes.wstring_at(
						ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD)
					)
					if _HARDWARE_ID_FRAGMENT in path.lower():
						paths.append(path)
			index += 1
	finally:
		setupapi.SetupDiDestroyDeviceInfoList(device_info_set)

	return paths


def has_device() -> bool:
	"""Return whether a display with the expected hardware id is present."""
	return bool(device_paths())


def is_timeout_error(error: OSError) -> bool:
	"""Return whether a WinUSB error is a transfer timeout/abort."""
	return getattr(error, "winerror", None) in (
		winusb.ERROR_SEM_TIMEOUT,
		winusb.ERROR_OPERATION_ABORTED,
	)


def find_device(probe_timeout_ms: int = PROBE_TIMEOUT_MS) -> winusb.WinUsbDevice | None:
	"""Open the first display which answers the protocol handshake."""
	for path in device_paths():
		candidate = winusb.WinUsbDevice(
			path,
			endpoint_in=protocol.ENDPOINT_IN,
			endpoint_out=protocol.ENDPOINT_OUT,
			timeout_ms=probe_timeout_ms,
		)
		keep = False
		try:
			candidate.open()
			response = candidate.request(
				protocol.QUERY_PACKET,
				protocol.PACKET_SIZE,
			)
			if protocol.parse_button_response(response) is not None:
				candidate.set_timeout(TRANSFER_TIMEOUT_MS)
				keep = True
				return candidate
		except OSError:
			pass
		finally:
			if not keep:
				candidate.close()
	return None
