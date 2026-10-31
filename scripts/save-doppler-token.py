#!/usr/bin/env python3
"""Prompt for the home-dc-proxmox/prd Doppler service token and save it to macOS Keychain."""

import ctypes
import getpass
import os
import subprocess
import sys
import warnings


SERVICE = b"home-dc-doppler-proxmox"
PROJECT = "home-dc-proxmox"
CONFIG = "prd"
PREFIX = "dp.st.prd."
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


def validate(token):
    """Return an error string, or None when the token has the expected shape."""
    if token.startswith(("dp.ct.", "dp.pt.", "dp.sa.", "dp.scim.")):
        return "personal, CLI, service-account and SCIM tokens are refused; use a config-scoped service token"
    if not token.startswith(PREFIX):
        return f"not a {CONFIG} service token (expected prefix {PREFIX})"
    if len(token) == len(PREFIX) or any(c.isspace() for c in token):
        return "token is empty after its prefix or contains whitespace"
    return None


def verify(token):
    """Prove the token reads home-dc-proxmox/prd. The token travels in the environment, never argv."""
    env = dict(os.environ, DOPPLER_TOKEN=token)
    try:
        result = subprocess.run(
            ["doppler", "secrets", "--only-names", "--project", PROJECT, "--config", CONFIG, "--no-check-version"],
            env=env, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not run the Doppler CLI: {type(exc).__name__}"
    if result.returncode != 0:
        detail = (result.stderr or "").strip().replace(token, "***")
        return f"Doppler rejected the token for {PROJECT}/{CONFIG}: {detail or 'no detail'}"
    return None


def main():
    account = os.environ["USER"].encode()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass(f"Doppler {PROJECT}/{CONFIG} service token (input hidden): ").strip()
    except (getpass.GetPassWarning, EOFError):
        print("Token was not saved: a hidden interactive prompt is required", file=sys.stderr)
        return 1
    problem = validate(token) or verify(token)
    if problem:
        print(f"Token was not saved: {problem}", file=sys.stderr)
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
    print(f"Service token saved to Keychain ({SERVICE.decode()}); it can read {PROJECT}/{CONFIG}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
