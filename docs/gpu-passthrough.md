# P2000 passthrough and host console

Observed on the freshly installed `pve-00` before configuration:

| PCI address | Device | IOMMU group | Firmware boot VGA | Intended owner |
|---|---|---:|---:|---|
| `0000:02:00.0` | Quadro P2000 GPU (`10de:1c30`) | 35 | 1 | Guest via VFIO |
| `0000:02:00.1` | P2000 audio (`10de:10f1`) | 35 | — | Same guest via VFIO |
| `0000:05:00.0` | GeForce GT 710 GPU (`10de:128b`) | 37 | 0 | Host console |
| `0000:05:00.1` | GT 710 audio (`10de:0e0f`) | 37 | — | Host |

Groups 35 and 37 each contain **only** the two functions shown. No ACS override is needed. Firmware currently initializes the wrong GPU for the requested console split. Set GT 710 as the BIOS primary GPU and reboot **before** `task apply`; the role checks the GT 710's `boot_vga` and stops before changing GPU configuration if it is not 1. Confirm via `/sys/bus/pci/devices/0000:05:00.0/boot_vga`.

The role enables Intel IOMMU and loads `vfio-pci` early, binding the P2000 GPU and audio by their exact vendor/device IDs. `softdep` orders VFIO before `nouveau` and `snd_hda_intel` so those drivers remain available for the GT 710 and host audio. Nothing globally blacklists NVIDIA drivers, disables the framebuffer, or automatically reboots. Device IDs are checked at the expected addresses to fail closed if cards move or hardware changes.

After apply and a maintenance reboot, verify `lspci -nnk -s 02:00.0`, `lspci -nnk -s 02:00.1`, and `lspci -nnk -s 05:00.0`. Both P2000 functions must say `Kernel driver in use: vfio-pci`; the GT 710 must not. If either P2000 function remains on a host driver, do not start a passthrough VM: inspect `/proc/cmdline`, `dmesg`, and `journalctl -b` for VFIO/IOMMU binding and framebuffer ownership first. Assign the two P2000 functions to the **same** guest; creating a guest is not part of this playbook.
