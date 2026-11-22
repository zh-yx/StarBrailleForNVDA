# -*- coding: utf-8 -*-
# Copyright (C) 2026 starBrailleForNVDAAddon contributors
# This file is covered by the GNU General Public License, version 2 or later.

"""A small, self-contained WinUSB bulk transfer wrapper."""

import ctypes
import threading
from ctypes import wintypes

# CreateFileW flags.
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_SHARE_NONE = 0
FILE_ATTRIBUTE_NORMAL = 0x80
# WinUsb_Initialize requires an overlapped handle on current Windows versions,
# even though the calls below pass a NULL OVERLAPPED and therefore complete synchronously.
FILE_FLAG_OVERLAPPED = 0x40000000

PIPE_TRANSFER_TIMEOUT = 0x03
ERROR_INVALID_HANDLE = 6
ERROR_SEM_TIMEOUT = 121
ERROR_WRITE_FAULT = 29
ERROR_OPERATION_ABORTED = 995

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winusb = ctypes.WinDLL("winusb", use_last_error=True)

kernel32.CreateFileW.argtypes = (
	wintypes.LPCWSTR,
	wintypes.DWORD,
	wintypes.DWORD,
	ctypes.c_void_p,
	wintypes.DWORD,
	wintypes.DWORD,
	wintypes.HANDLE,
)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL

winusb.WinUsb_Initialize.argtypes = (
	wintypes.HANDLE,
	ctypes.POINTER(ctypes.c_void_p),
)
winusb.WinUsb_Initialize.restype = wintypes.BOOL

winusb.WinUsb_Free.argtypes = (ctypes.c_void_p,)
winusb.WinUsb_Free.restype = wintypes.BOOL

winusb.WinUsb_SetPipePolicy.argtypes = (
	ctypes.c_void_p,
	ctypes.c_ubyte,
	wintypes.ULONG,
	wintypes.ULONG,
	ctypes.c_void_p,
)
winusb.WinUsb_SetPipePolicy.restype = wintypes.BOOL

winusb.WinUsb_AbortPipe.argtypes = (ctypes.c_void_p, ctypes.c_ubyte)
winusb.WinUsb_AbortPipe.restype = wintypes.BOOL

winusb.WinUsb_ResetPipe.argtypes = (ctypes.c_void_p, ctypes.c_ubyte)
winusb.WinUsb_ResetPipe.restype = wintypes.BOOL

winusb.WinUsb_ReadPipe.argtypes = (
	ctypes.c_void_p,
	ctypes.c_ubyte,
	ctypes.POINTER(ctypes.c_ubyte),
	wintypes.ULONG,
	ctypes.POINTER(wintypes.ULONG),
	ctypes.c_void_p,
)
winusb.WinUsb_ReadPipe.restype = wintypes.BOOL

winusb.WinUsb_WritePipe.argtypes = (
	ctypes.c_void_p,
	ctypes.c_ubyte,
	ctypes.POINTER(ctypes.c_ubyte),
	wintypes.ULONG,
	ctypes.POINTER(wintypes.ULONG),
	ctypes.c_void_p,
)
winusb.WinUsb_WritePipe.restype = wintypes.BOOL


class WinUsbDevice:
	"""An exclusively opened WinUSB bulk interface."""

	def __init__(self, path: str, endpoint_in: int, endpoint_out: int, timeout_ms: int = 500):
		self.path = path
		self._endpoint_in = endpoint_in
		self._endpoint_out = endpoint_out
		self._timeout_ms = timeout_ms
		self._file = None
		self._interface = None
		# Re-entrant because request() holds the lock while calling write().
		# One lock for the whole request keeps another write from being inserted between a query and its answer.
		self._io_lock = threading.RLock()

	def open(self) -> None:
		"""Open the device and initialise WinUSB.

		On failure every handle opened so far is closed again before the OSError is raised.
		"""
		with self._io_lock:
			if self._interface:
				return

			# Share mode 0: the display is opened exclusively, as required by the protocol.
			# The handle must be overlapped for WinUsb_Initialize; a NULL OVERLAPPED is passed to each transfer.
			handle = kernel32.CreateFileW(
				self.path,
				GENERIC_READ | GENERIC_WRITE,
				FILE_SHARE_NONE,
				None,
				OPEN_EXISTING,
				FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED,
				None,
			)
			if not handle or handle == INVALID_HANDLE_VALUE:
				raise ctypes.WinError(ctypes.get_last_error())

			interface = ctypes.c_void_p()
			if not winusb.WinUsb_Initialize(handle, ctypes.byref(interface)):
				error = ctypes.get_last_error()
				kernel32.CloseHandle(handle)
				raise ctypes.WinError(error)

			self._file = handle
			self._interface = interface

		self._apply_timeout()

	def _apply_timeout(self) -> None:
		if not self._interface:
			return
		timeout = wintypes.ULONG(self._timeout_ms)
		for endpoint in (self._endpoint_in, self._endpoint_out):
			winusb.WinUsb_SetPipePolicy(
				self._interface, endpoint, PIPE_TRANSFER_TIMEOUT,
				ctypes.sizeof(timeout), ctypes.byref(timeout),
			)

	def set_timeout(self, timeout_ms: int) -> None:
		"""Change the transfer timeout of an already open device."""
		self._timeout_ms = timeout_ms
		self._apply_timeout()

	def abort(self) -> None:
		"""Abort transfers on both pipes without releasing the handles."""
		interface = self._interface
		if interface:
			winusb.WinUsb_AbortPipe(interface, self._endpoint_in)
			winusb.WinUsb_AbortPipe(interface, self._endpoint_out)

	def reset_pipes(self) -> bool:
		"""Clear a stalled bulk pipe pair without reopening the device."""
		with self._io_lock:
			interface = self._interface
			if not interface:
				return False
			in_ok = winusb.WinUsb_ResetPipe(interface, self._endpoint_in)
			out_ok = winusb.WinUsb_ResetPipe(interface, self._endpoint_out)
			return bool(in_ok and out_ok)

	def close(self) -> None:
		"""Abort pending transfers and release all handles."""
		with self._io_lock:
			interface, self._interface = self._interface, None
			if interface:
				winusb.WinUsb_AbortPipe(interface, self._endpoint_in)
				winusb.WinUsb_AbortPipe(interface, self._endpoint_out)
				winusb.WinUsb_Free(interface)

			handle, self._file = self._file, None
			if handle:
				kernel32.CloseHandle(handle)

	def write(self, data: bytes) -> None:
		"""Write one packet to the bulk OUT pipe."""
		with self._io_lock:
			if not self._interface:
				raise OSError(ERROR_INVALID_HANDLE, "device is not open")
			buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
			written = wintypes.ULONG()
			ok = winusb.WinUsb_WritePipe(
				self._interface,
				self._endpoint_out,
				buffer,
				len(data),
				ctypes.byref(written),
				None,
			)
			error = ctypes.get_last_error() if not ok else 0

		if not ok:
			raise ctypes.WinError(error)
		if written.value != len(data):
			raise OSError(ERROR_WRITE_FAULT, "short write")

	def read(self, size: int) -> bytes:
		"""Read up to ``size`` bytes from the bulk IN pipe.

		A transfer timeout is reported as an empty byte string.
		"""
		interface = self._interface
		if not interface:
			raise OSError(ERROR_INVALID_HANDLE, "device is not open")

		buffer = (ctypes.c_ubyte * size)()
		received = wintypes.ULONG()
		if not winusb.WinUsb_ReadPipe(
			interface,
			self._endpoint_in,
			buffer,
			size,
			ctypes.byref(received),
			None,
		):
			error = ctypes.get_last_error()
			if error in (ERROR_SEM_TIMEOUT, ERROR_OPERATION_ABORTED):
				return b""
			raise ctypes.WinError(error)
		return bytes(buffer[: received.value])

	def request(self, packet: bytes, read_size: int) -> bytes:
		"""Write ``packet`` and read ``read_size`` bytes as one exchange.

		The whole write/read sequence is serialised with other writes
		so a second packet cannot be inserted between the query and its answer.
		"""
		with self._io_lock:
			self.write(packet)
			return self.read(read_size)
