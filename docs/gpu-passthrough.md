# P2000 passthrough and host console

Observed on `pve-00` after moving the cards and selecting the GT 710 as firmware primary display:

| PCI address | Device | IOMMU group | Firmware boot VGA | Intended owner |
|---|---|---:|---:|---|
| `0000:5b:00.0` | Quadro P2000 GPU (`10de:1c30`) | 2 | 0 | Guest via VFIO |
| `0000:5b:00.1` | P2000 audio (`10de:10f1`) | 2 | — | Same guest via VFIO |
| `0000:02:00.0` | GeForce GT 710 GPU (`10de:128b`) | 36 | 1 | Host console |
| `0000:02:00.1` | GT 710 audio (`10de:0e0f`) | 36 | — | Host |

Each group contains only the two functions listed. No ACS override is needed. The role checks the exact P2000 addresses and hardware IDs and confirms the GT 710 is firmware primary in both check and apply mode; it fails closed if these assumptions change. Before applying, use `task plan` or `ansible-playbook -i inventory site.yml --check --diff --tags gpu` to inspect the proposed changes. Only the operator runs `task apply`.

The role enables Intel IOMMU in `/etc/kernel/cmdline` on this ZFS/UEFI installation, loads VFIO early, and binds the P2000 GPU and audio by their exact vendor/device IDs. `softdep` orders VFIO before `nouveau` and `snd_hda_intel` so those drivers remain available for the GT 710 and host audio. Nothing globally blacklists NVIDIA drivers or disables the framebuffer. Applying refreshes Proxmox boot entries and initramfs but **does not reboot**. In a maintenance window run `task reboot`, which waits for the host to return.

After reboot, verify with `ssh pve-00 'lspci -nnk -s 5b:00.0; lspci -nnk -s 5b:00.1; lspci -nnk -s 02:00.0; cat /proc/cmdline'`. Both P2000 functions must show `Kernel driver in use: vfio-pci`, the GT 710 must remain on its host driver, and the command line must contain `intel_iommu=on`. If either P2000 function remains on a host driver, do not start a passthrough VM: inspect `dmesg` and `journalctl -b` for VFIO/IOMMU binding and framebuffer ownership. Assign both P2000 functions to the **same** guest; the playbook does not create a guest.

For the physical card arrangement, see the [motherboard reference](motherboard.html). Its PCIe slot numbers and the NVMe daughter card's physical position have not been verified on-site.
