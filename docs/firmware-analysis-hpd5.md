# Firmware analysis — EZVIZ HP5 / CS-HPD5-R100-1H2 (camera unit)

> Static analysis only. No firmware binary was executed. Kernel modules were
> unpacked into a separate working directory; the input images were left unchanged.

## Summary

- Platform is **Fullhan FH865X**, ARMv7, Linux 4.9.129, EABI5 hard-float / uClibc.
- **Door control does not have to go through the DB-/DB+ bus**: the firmware has two
  direct relay outputs on **GPIO 0** and **GPIO 28**.
- `execSystemCmd` is a local broker that runs arbitrary commands via `system()`, but
  it only listens on a UNIX socket (not reachable from the LAN).
- The main application `ezapp` is not present in cleartext. It is encrypted as
  `ezapp.xz_secure`, so the CAS/CPD7 implementation and most network services are
  out of reach of this static set.
- Updates use separate decrypt and signature-verify operations via `ezviz_toolbox`;
  only a secp256k1 **public** key is available.
- A full signed firmware replacement through the official updater is currently
  unrealistic. More feasible: stock firmware plus a custom local helper, once you
  have access to a running system.

## 1. Platform, SoC and bootloader

All available programs and libraries are: ELF32 little-endian, ARM, EABI5,
hard-float ABI, linked against uClibc.

Kernel modules report: `vermagic=4.9.129 mod_unload ARMv7 p2v8`, `author=FULLHAN`.
The FH865X names, Fullhan libraries and drivers clearly point to a
Fullhan / Fudan Microelectronics **FH865X** SoC.

`mImage` and `uImage` have classic 64-byte legacy uImage headers:

| Image in DAV | DAV offset | Date | Payload size | Load/entry |
|---|---:|---|---:|---|
| mImage | 0x47711c | 2025-05-21 07:46:48 UTC | 2,537,216 | 0xa0008000 |
| uImage | 0x6e285c | 2026-05-11 06:58:42 UTC | 2,359,552 | 0xa0008000 |

Both declare Linux / ARM / Kernel / compression none. However, the payloads are
high-entropy and do not look like an uncompressed ELF/zImage kernel — most likely
encrypted or obfuscated. Legacy uImage is a U-Boot-compatible format (a strong
hint, but not proof, that the bootloader is specifically U-Boot — its binary is not
in the DAV). No readable U-Boot environment, bootargs, `console=` line, or partition
layout from the cmdline was found.

Evidence: `modules.tgz` → `load_modules.sh` (rtthread_arc_FH865X.bin, vmm.ko,
xbus_rpc.ko; VMM memory at 0xa2900000, 23040 KiB; coprocessor firmware loaded at
0xbff80000), `libsys.so`/`ezdsp` (Fullhan symbols and devices incl. `/dev/fh_efuse`),
`libys_vqe_fh865x.so` (platform name in the clear).

Confidence: high for Fullhan FH865X / ARMv7 / Linux 4.9.129; medium for U-Boot; low
for bootloader configuration (absent from the material).

## 2. Boot, processes and diagnostic interfaces

### initrun.sh
1. Sets the date to 2022-10-1. 2. Copies `da_info` to `/bin`. 3. Links libraries
from `/dav` to `/lib`. 4. Creates `/devinfo/devlog`. 5. Unpacks voice files to
`/home` in the background. 6. Brings up `eth0` and `lo`. 7. A one-second console
window (key `n` skips app start). 8. If `/dav/ezapp` exists: runs `execSystemCmd &`
and `ezapp &`. 9. Otherwise unpacks `/home/dav/ezapp.xz` and runs the same two
processes.

The image contains neither `ezapp` nor `ezapp.xz`, only `ezapp.xz_secure` — so an
earlier boot stage outside this SquashFS must perform the decryption. The script
does not explicitly start ezdsp/udhcpc, has no restart loop, does not configure a
watchdog, and does not load `modules.tgz` — those are done by the base init or the
decrypted `ezapp`.

### execSystemCmd — local arbitrary command execution
Creates `/var/systemCmd.socket` (AF_UNIX/SOCK_STREAM, not TCP). `processSystemCmd`
(VA 0x13a0): reads a 4-byte length, accepts a payload up to 1023 bytes, passes it
straight to `system()`, returns the result code. No allowlist, no crypto auth. The
client must bind its own UNIX socket with permissions exactly 0700; the server does
not check SO_PEERCRED/UID/PID. Weak access control, but the interface is not
reachable from the LAN.

### da_info
A diagnostic client for the main app: connects to `127.0.0.1:7001/TCP`, binary
header with length / command ID / argument count, a table of 103 commands
(ELF VA 0x12000). Interesting ones: `taskShow, prtHardInfo, show_server, show_key,
show_status, set_sdk_debug, stop_dsp, upg_start, dsp_dbg, set_dbg, getISP, setISP,
motor, t1_mcu_event_test, t1_get_lock_comm_status, at_cmd, ota_test, upgrade_test`.
No explicit unlock/open_lock/open_door command. `t1_get_lock_comm_status` is a status
read only.

### Shell/debug
The application partition contains no telnetd/Dropbear/sshd/adbd/passwd/shadow and
no explicit default credentials (this does not rule out services in the base
rootfs/initramfs, which is not present here). The one-second `n` quick-exit is a
useful diagnostic hook if the script's stdin is wired to a UART.

Confidence: high for `initrun.sh`, `execSystemCmd`, `da_info` behaviour; medium for
the complete list of startup services (main program and base init unavailable).

## 3. LAN attack surface and CAS/CPD7

| Endpoint | Scope | Function | Auth |
|---|---|---|---|
| /var/systemCmd.socket | local UNIX | arbitrary `system()` | only weak socket type/perm check |
| 127.0.0.1:7001/TCP | loopback | da_info diagnostics | client sends no credentials; server is in ezapp |
| optional DBI-over-TCP | 0.0.0.0, port from caller | ISP debug | no auth in the transport layer |

Optional DBI: `libf7_isp.so` `libtcp_dbi_thread` (VA 0x22748) — AF_INET/SOCK_STREAM,
binds INADDR_ANY, listen(5), replaces the previous client; no callers inside the
library; no evidence the production `ezapp` enables it. The `crypto_api` sockets in
`ezdsp` are Linux AF_ALG/skcipher, not a network service.

No recognizable CPD7, CAS, ChaCha20, ECDH, port 9020, MQTT, STUN/P2P, or stream
RTSP/HTTP in the cleartext binaries. The implementation is almost certainly inside
the encrypted `ezapp.xz_secure`. No evidence of a globally-derivable LAN key; the
`sec.bin` and OTP handling suggest device-specific data.

Confidence: high for the local endpoints; low/undetermined for CAS/CPD7 (main
program encrypted).

## 4. Door control, relays and the DB-/DB+ bus (most important)

`libezbsp.so` exports:
- `ezbsp_set_relay_dr_status` (VA 0x3b8c): logs `==>open door %d`, calls
  `general_set_pin_value(2, value!=0)`.
- `ezbsp_set_relay_lock_status` (VA 0x3bbc): logs `==>open lock %d`, calls
  `general_set_pin_value(3, value!=0)`.

`libsys.so general_set_pin_value` (ELF VA 0x17200) maps the logical type to a GPIO
table entry: `gpio_pin_set(type+0x100, value)`. Table `g_gpio_sets`
(ELF VA 0x5210c, offset 0x4210c, 284 entries × 8 bytes):

| Function | Index | File offset | Entry | GPIO |
|---|---:|---:|---|---:|
| relay_dr | 0x102 | 0x4291c | `00000000 beef0001` | GPIO 0 |
| relay_lock | 0x103 | 0x42924 | `0000001c beef0001` | GPIO 28 |

Both are configured as active-high outputs. The low-level path is `gpio_pin_set`
(ELF VA 0x17f3c) → `ioctl 0x40084704` (HAL_GPIO_SET_VALUE). The exact device path for
that descriptor was not conclusively tied down; libsys also uses `/dev/ezio`.

Doorbell button: `ezbsp_get_doorbell_value` (VA 0x3178) → `libsys get_doorbell_value`
(ELF VA 0x0a2c4), entry 0x21, `g_gpio_sets` offset 0x42214 `0000002f beef0100` →
GPIO 47, input. Polarity should be confirmed with a meter.

MCU / DB-/DB+: `libsys` has an MCU comm layer (`mcu_comm_set/send/recv`, `init_mcu`),
an MKL protocol with a 16-bit command code. `controller_desc` (offset 0x429ec):
`/dev/spidev1.0` (SPI) and `/dev/ttyS2` (UART, `mcu_startup`); MCU-update code also
references `/dev/ttyS1`. There is not enough evidence that `/dev/ttyS2` is
electrically the DB-/DB+ bus. `xbus_rpc.ko` loads RTThread into the coprocessor
(a media-DSP bus, not DB-/DB+).

**Consequence: opening the lock is available as a direct GPIO/relay and does not
require understanding the DB-/DB+ protocol.**

Confidence: high for GPIO 0/28 and the relay functions; medium for the role of the
two relays; low for the physical DB-/DB+ assignment to a specific UART/SPI.

## 5. Firmware crypto and update

DAV layout: `0x000000–0x0000c3` 196-byte header/metadata; `0x0000c4` SquashFS
`app.img`; `0x47711c` mImage; `0x6e285c` uImage. `app.img` = SquashFS 4.0 / XZ
(38 inodes, FS 4,678,366 bytes). The application partition is not fully encrypted —
its key program and manifest are.

`ezapp.xz_secure` (1,687,552 bytes): no XZ header, high entropy, length divisible by
16, no useful cleartext strings. `libsys get_decrypt_file` (ELF VA 0x2e7e8) invokes
`/usr/sbin/ezviz_toolbox ez_sec_dec INPUT OUTPUT` (the toolbox is in the base system,
not in this SquashFS).

Signature verification: `libsys check_file_signed` (ELF VA 0x2e954) →
`ezviz_toolbox ez_sec_cksign INPUT KEY_OR_SIGNATURE`; `decrypt_boot_params` →
`ez_sec_decsecbin`. `enc_publickey.txt` is a valid EC public key (secp256k1,
256-bit). The filename suggests encryption, but the presence of a separate
`ez_sec_cksign` operation suggests it may also be used for signature verification;
without the toolbox the signature format (ECDSA vs an ECIES/ECDH wrapper) cannot be
confirmed. `filelist.enc.bin` (3328 bytes): high entropy, no magic — likely an
encrypted/signed file manifest.

Anti-rollback: no explicit rollback-index / OTP version counter / version-compare
code found in the available material (the logic may be in the toolbox, bootloader,
or encrypted kernel).

Feasibility: rebuilding the SquashFS is technically easy; installing such a DAV
through the official updater would likely fail signature verification; there is no
private key for `enc_publickey.txt`; the kernels are encrypted; replacing `ezapp`
breaks the `ez_sec_dec`/`ez_sec_cksign` mechanism. Raw-writing a modified application
partition via bootloader/programmer might work if boot does not verify the whole
partition — undeterminable without the bootloader or a hardware test.

## 6. Secrets and keys

`libsys ezdi_get_seckey` (ELF VA 0x29cb0) reads an MTD partition named `sec.bin`:
starts parsing at offset 0x300, expects magic `0x484b5753` (`SWKH`), walks 0x30-byte
records, decrypts each via `cipher_unpack_sec_bin` (callback
`g_cipher_unpack_secbin_ops`, not part of libsys — likely from `libeztools.so`).
libsys can dynamically load `/lib/libeztools.so` (`ez_simple_crypto`,
`ez_unpack_sec_bin`) — not present in this partition.

OTP/eFuse: `ezdsp` has Fullhan APIs `FH_CRYPTO_ReadOTPKey/ReadOTPDeviceID/ReadOTPIV/
WriteOTPKey/SetLock` and `/dev/fh_efuse` → a strong hint that some secrets are
hardware-bound to the individual device.

`enc_publickey.txt` is public and most likely global to the firmware line. The actual
secrets are probably in `sec.bin` and/or OTP/eFuse (device-specific). No private key,
client certificate or cleartext password was found; no `shipin7` string or FTP
password-decryption routine in the cleartext binaries (likely in the decrypted
`ezapp` or the base `ezviz_toolbox`/`libeztools.so`).

Confidence: high for `sec.bin` and the OTP API; medium for the device-specific nature
of the keys; undetermined for `shipin7`.

## Most promising path to full local integration

Best next step: obtain the decrypted `ezapp` from a running device (from RAM or
`/home/dav/ezapp` after boot) via a physical UART/root shell, without modifying the
firmware. That one artifact should let you: (1) find the call site of
`ezbsp_set_relay_lock_status` and determine the exact local-unlock command;
(2) reconstruct the `127.0.0.1:7001` server; (3) confirm ports 9020/MQTT/P2P;
(4) analyze ECDH/ChaCha20/the CPD7 KDF; (5) resolve the use of the device
verification code and the `sec.bin` keys; (6) build a local HA bridge on the stock
kernel.

For door-opening alone, the shortest software path is a custom ARM helper running on
the device that calls the existing BSP: `ezbsp_set_relay_lock_status(1)` → short
pulse → `(0)`. Alternatively, drive physical GPIO 28, but this needs correct driver
init and careful bench confirmation of which relay is the actual lock. Exposing
`execSystemCmd` directly to the LAN is not recommended.

## Verdict — custom firmware

A full signed replacement via the standard OTA path: currently unrealistic. Obstacles:
no private signing key, `ez_sec_cksign`, encrypted `ezapp`, encrypted kernel payloads,
no bootloader code and unknown secure-boot/anti-rollback, dependence on closed Fullhan
drivers and RTThread firmware. Realistic alternative: **stock firmware plus a
persistent sidecar/helper**, introduced via UART / a local vulnerability / direct
modification of the application partition (after determining whether the bootloader
verifies it).
