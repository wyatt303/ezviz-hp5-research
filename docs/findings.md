# Research findings — EZVIZ HP5 video doorphone

Consolidated notes from investigating an EZVIZ HP5 system for interoperability and
reverse-engineering. Two physical units:

| Unit | Role | Model (devType) | Firmware (as of 2026-10) | Notes |
|---|---|---|---|---|
| Indoor screen | "the brains" | `CS-HP5-R100-1W2TFC` | `V1.0.1 build 260417` | 7" 1024×600, 2.4/5 GHz WiFi, cloud. 24 VDC. **CE / EU product, no FCC filing.** |
| Outdoor panel | camera/doorbell | `CS-HPD5-R100-1H2` | `V5.3.6 build 260512` | Connects to screen over 2-wire **DB-/DB+** bus. Firmware in this repo. |

The indoor screen's info page reports *both* firmware versions ("Wersja dzwonka
drzwiowego" = camera, "Wersja ekranu" = screen).

## Firmware acquisition (EZVIZ cloud/CDN)

- The firmware update CDN is **open and content-addressed by MD5**:
  `https://devupgrade-ali.ys7.com/<md5>/digicap.dav` serves the `.dav`
  **unauthenticated** (verified).
- The EZVIZ cloud only returns a firmware download URL/MD5 **when an upgrade is
  pending**. The app's firmware-check endpoint is
  `POST /api/device/upgrade/info/get` with body `deviceSerialNo=<serial>`
  (public params ride as session headers). For an up-to-date device it returns
  `upgradePacketInfo: null, isNeedUpgrade: 0` — so you cannot pull the *current*
  firmware of an up-to-date unit this way.
- The `ftpInfo` returned by that endpoint is **vestigial** (`addr: 8.8.8.8`
  placeholder; `i.ezvizlife.com:21` = connection refused).
- The legacy model-addressed scheme
  `usdownload.ezvizlife.com/device/<MODEL>/<ver>/<MODEL>.dav` returns **404** for
  HP5/HPD5 (only works for old models).
- Net result: once you know a firmware's MD5 (i.e. the moment EZVIZ publishes an
  update) you can download it instantly from the open CDN. The firmware here
  (HPD5 V5.3.6 build 260512) was obtained this way.

The Android app (`com.ezviz`) trusts only `system` CAs in its
`network_security_config` and has a signature/anti-tamper check that self-kills a
resigned APK — so a repackaged-APK + mitmproxy approach to sniff the cloud API
does **not** work without also defeating the integrity check. Calling the API
directly with a valid session token (e.g. via `pyezvizapi`) is simpler.

## Hardware / SoC (camera unit)

- **Fullhan FH865X**, ARMv7, Linux 4.9.129, uClibc. See
  [firmware-analysis-hpd5.md](firmware-analysis-hpd5.md) for the full static analysis.
- **Door unlock is a direct GPIO relay** on the camera: `ezbsp_set_relay_lock_status`
  → GPIO 28, `ezbsp_set_relay_dr_status` → GPIO 0 (in `libezbsp.so`/`libsys.so`).
  So fully-local unlock needs **no** CAS/CPD7 or DB± protocol RE — just root on the
  camera + a small helper that pulses the lock relay. (Which relay is the real
  strike must be bench-confirmed.)
- Main app `ezapp` is encrypted (`ezapp.xz_secure`, decrypted on-device via
  `/usr/sbin/ezviz_toolbox ez_sec_dec`); CAS/CPD7/ChaCha20/ECDH and the network
  services live inside it, out of reach of static analysis.
- Firmware is signed (secp256k1, `ez_sec_cksign`); no private key → full signed
  custom firmware is not realistic. Device secrets are bound to `sec.bin` (MTD,
  magic `SWKH`) + OTP/eFuse (`FH_CRYPTO_ReadOTPKey`), which is why a cloud-free CAS
  stream key does not appear to be globally derivable.

## Home Assistant integration

- A working HACS integration already exists: **[Bobsilvio/ezviz_hp7](https://github.com/Bobsilvio/ezviz_hp7)**
  (covers HP7/CP7 and siblings HP5/HPD5): live video (H.264/HEVC + audio), door
  unlock, chime control, unlock events. It is `cloud_polling` (control via the
  EZVIZ cloud; the LAN stream still fetches the CAS key from the cloud).
- The `tools/` here include a LAN stream proxy helper and CPD7/audio probes
  (serials scrubbed to placeholders) built around `pyezvizapi`.
- The only thing the cloud integration does *not* give is fully cloud-free
  operation — that would require root on the camera (GPIO unlock) and/or recovering
  the CAS key scheme from the decrypted `ezapp`.

## Screen teardown

No public teardown of the HP5 indoor screen exists, and there is no FCC filing
(EU/CE product) so no FCC internal photos. The rear terminals are only
`+24VDC/GND` and the `DB-/DB+` 2-wire bus — **not** a debug port. Getting the
screen's firmware / root requires opening the enclosure and finding a UART header
on the PCB.

### What's on the board (observed 2026-10)

The main PCB was opened and inspected. Key parts:

| Ref | Part | Role |
|---|---|---|
| UF1 | `25Q128` (marking `MD AY2424 25Q128STG`), SOP-8 | **SPI NOR flash, 128 Mbit / 16 MB, 3.3 V, JEDEC 25-series.** Boot flash. A 2nd footprint (UF2) is unpopulated. |
| (under main shield) | not yet read | Main SoC + DRAM (display/multimedia class, distinct from the camera's Fullhan). Remove the large metal can to read markings. |
| U1 | module w/ QR code, 40.0 MHz crystal (`T4L`) | Likely the WiFi (+BT) SoC/module. |
| UE3 | **Motorcomm YT8510C** | 10/100 Ethernet PHY. |
| UE2 | **Realtek RTL8201F** | 10/100 Ethernet PHY. |
| X5 | 25.0 MHz crystal | Ethernet PHY reference clock. |
| J3 | CR2032 coin cell | RTC backup. |
| UV1 / LV1 / LV9 | `JMS116F`, `SS310A`, 10 µH (`100`), `3756` buck | 24 V → rail DC-DC conversion. |
| WE 251 | Würth magnetics | Line transformer (likely for the 2-wire bus / Ethernet). |

- **A UART header is silkscreened `Debug`** (with a direction arrow, next to `JP2`)
  — the realistic root path. Probe the connector for GND (continuity to ground/shield),
  VCC (steady ~3.3 V), TX (idles ~3.3 V, bursts at boot) and RX; attach a **3.3 V**
  USB-UART, most likely **115200 8N1**. The boot log should reveal the SoC, bootloader,
  and the full partition map in one shot.
- **The 16 MB UF1 NOR can be dumped offline** with a SOIC-8 clip + CH341A/flashrom
  (or a Pi Pico running `pico-serprog`); `flashrom` auto-detects it by JEDEC ID.
  In-circuit reads may be corrupted by the SoC holding the bus — if so, hold the SoC
  in reset or desolder the chip. `binwalk` the dump for U-Boot + env (bootargs) and
  any carveable kernel/rootfs.
- **Capacity note:** 16 MB NOR is tight for a full 7" Linux UI, so either the rootfs
  is a compressed squashfs in this NOR, or there is an additional eMMC/NAND under the
  main shield. The UART boot log / partition map will settle this.
- **Dual Ethernet PHYs (YT8510C + RTL8201F) + the WE line transformer + the 2-wire
  `DB-/DB+` terminal strongly suggest the camera link is Ethernet/IP carried over the
  2-wire bus** (a 2-wire extender), not a bespoke serial protocol. That is consistent
  with the outdoor unit being an ordinary EZVIZ IP camera (RTSP/CAS). Bench-confirm.

### Methodology from sibling EZVIZ devices

- [EZVIZ DVR rooting](https://mattj.uk/blog/ezviz-dvr-root/) — UART header, interrupt U-Boot, `sf read` + TFTP flash dump.
- [EZVIZ BD-2402B1](https://blog.back.engineering/20/01/2022/) — U-Boot 115200, `rdinit=/bin/sh`.
- [UART/U-Boot intro](https://voidstarsec.com/blog/uart-uboot-and-usb), [SPI flash extraction](https://wrongbaud.github.io/posts/router-teardown/).

Open questions remaining for the screen: the exact SoC/DRAM part (under the shield),
the `Debug` header pinout + baud, whether U-Boot is password-locked, the partition
layout, and whether there is an eMMC/NAND in addition to the 16 MB NOR.
