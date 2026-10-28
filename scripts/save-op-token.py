#!/usr/bin/env python3
"""Prompt for a 1Password service-account token and save it to macOS Keychain."""

import base64
import binascii
import ctypes
import getpass
import json
import os
import warnings
import sys


SERVICE = b"home-dc-proxmox-op"
SECURITY = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
CORE_FOUNDATION = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
SECURITY.SecKeychainFindGenericPassword.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
    ctypes.c_uint32, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
SECURITY.SecKeychainFindGenericPassword.restype = ctypes.c_int32
SECURITY.SecKeychainAddGenericPassword.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
    ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p,
    ctypes.c_void_p,
]
SECURITY.SecKeychainAddGenericPassword.restype = ctypes.c_int32
SECURITY.SecKeychainItemModifyAttributesAndData.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
]
SECURITY.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
CORE_FOUNDATION.CFRelease.argtypes = [ctypes.c_void_p]


def main():
    account = os.environ["USER"].encode()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass("1Password service-account token (input hidden): ")
    except (getpass.GetPassWarning, EOFError):
        print("Token was not saved: a hidden interactive prompt is required", file=sys.stderr)
        return 1
    try:
        if not token.startswith("ops_") or not isinstance(json.loads(base64.b64decode(token[4:], validate=True)), dict):
            raise ValueError("not a complete 1Password service-account token")
    except (ValueError, binascii.Error) as exc:
        print(f"Token was not saved: {exc}", file=sys.stderr)
        return 1

    data = token.encode()
    item = ctypes.c_void_p()
    status = SECURITY.SecKeychainFindGenericPassword(
        None, len(SERVICE), SERVICE, len(account), account,
        None, None, ctypes.byref(item),
    )
    if status == 0:
        try:
            result = SECURITY.SecKeychainItemModifyAttributesAndData(item, None, len(data), data)
        finally:
            CORE_FOUNDATION.CFRelease(item)
    elif status == -25300:  # errSecItemNotFound
        result = SECURITY.SecKeychainAddGenericPassword(
            None, len(SERVICE), SERVICE, len(account), account, len(data), data, None,
        )
    else:
        print(f"Keychain lookup failed (OSStatus {status}); no token saved", file=sys.stderr)
        return 1
    if result != 0:
        print(f"Keychain update failed (OSStatus {result})", file=sys.stderr)
        return 1
    print("Service-account token saved to Keychain (home-dc-proxmox-op).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
