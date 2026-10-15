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
- The screen's own local update-check config independently confirms this scheme:
  it stores its *currently installed* build's own download URL/MD5 in the same
  `devupgrade-ali.ys7.com/<md5>/digicap.dav` form — `5fe8f6cd71c601e67d71e2e29f0b28b1`
  for `V1.0.1 build 260417`. Since this value describes the build already running
  (not a pending update), it isn't retrievable through the app's upgrade-check API
  above; it only shows up in the device's own on-device state.

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
| (under main shield) | **Molchip, ARMv7, dual-core** (see below) | Main SoC + DRAM (display/multimedia class, distinct from the camera's Fullhan). Exact part number not yet read — need to remove the shield. |
| U1 | module w/ QR code, 40.0 MHz crystal (`T4L`) | Likely the WiFi (+BT) SoC/module. |
| UE3 | **Motorcomm YT8510C** | 10/100 Ethernet PHY. |
| UE2 | **Realtek RTL8201F** | 10/100 Ethernet PHY. |
| X5 | 25.0 MHz crystal | Ethernet PHY reference clock. |
| J3 | CR2032 coin cell | RTC backup. |
| UV1 / LV1 / LV9 | `JMS116F`, `SS310A`, 10 µH (`100`), `3756` buck | 24 V → rail DC-DC conversion. |
| WE 251 | Würth magnetics | Line transformer (likely for the 2-wire bus / Ethernet). |

- **A UART header is silkscreened `Debug`** (with a direction arrow, next to `JP2`)
  — the realistic root path.
- **Dual Ethernet PHYs (YT8510C + RTL8201F) + the WE line transformer + the 2-wire
  `DB-/DB+` terminal strongly suggest the camera link is Ethernet/IP carried over the
  2-wire bus** (a 2-wire extender), not a bespoke serial protocol. That is consistent
  with the outdoor unit being an ordinary EZVIZ IP camera (RTSP/CAS). Bench-confirm.

### Boot flash dumped (2026-10) — UF1, 16 MB SPI NOR

The UF1 NOR was desoldered and read with a SOIC-8 clip + CH341A under `flashrom`
(`flashrom -p ch341a_spi -c GD25Q128C -r dump.bin`; flashrom offers three matching
GigaDevice part defs — GD25B128B/GD25Q128B/GD25Q128E/GD25Q128C — they only differ in
erase/write, the read path is identical, so any of them is fine for a dump). **Two
independent passes produced byte-identical images (same SHA-256)** — treat that as a
requirement, not a nicety, since a flaky clip/CH341A can silently return garbage.

**Troubleshooting notes (two false leads, for next time):**
- `/dev/ttyUSB0` is irrelevant here. The CH341A in SPI mode enumerates as USB
  `1a86:5512` and is driven over libusb by flashrom's `ch341a_spi` programmer — not
  a tty. A serial device only appears when the same chip is bridged into UART mode,
  which cannot program flash.
- The `spi_ch341` kernel module (binds the interface, creates `spi0`/`spi0.0`) does
  **not** need to be unloaded/blacklisted — flashrom reads fine with it loaded.
- The actual cause of early failures (`id1 0xff, id2 0xffff`, i.e. MISO stuck high,
  no response) was **poor SOIC-8 clip contact**. Reseating the clip fixed it
  immediately. On Linux, a udev rule (`70-flashrom.rules`) typically grants the USB
  device ACL to the user, so `sudo` is not needed to read.

### What's in the dump

`binwalk` + manual inspection of the 16 MB image:

```
0x000000  header, magic "PERF"
0x000100  ARM exception vector table (ldr pc,[pc,#0x14]) → stage-1 loader
0x008040  LZMA blob → U-Boot 2017.09-SN49643 (built 2024-07-10, +0800), 441029 B decompressed
0x080000  JFFS2 (LE), 1295 nodes, 5312648 B   <- primary partition
0x5ABEC4  JFFS2 (LE), 1147 nodes, 5062984 B
0xA9D32C  JFFS2 (LE),  222 nodes,  928992 B
0xB91CE4  JFFS2 (LE),   26 nodes,  582440 B
0xC347C0  JFFS2 (LE),   98 nodes,  768836 B
0xD01B74  JFFS2 (LE),  465 nodes, 2155672 B
0xF2EF98  JFFS2 (LE),  204 nodes,  856168 B
```

So: **JFFS2**, not SquashFS, across 7 regions/partitions (unlike the camera's
SquashFS `.dav`). The U-Boot environment in this image has **no `mtdparts`/`mtdids`/
`bootcmd`** — the partition table is presumably compiled into the kernel or a DTB
embedded in the `uImage`, not set from the U-Boot env.

**SoC, from the U-Boot blob:** `board=molchip`, `board_name=molchip`, `soc=molchip`,
`cpu=armv7`, with `cpu@0` *and* `cpu@1` in the device tree → **Molchip, ARMv7,
dual-core**. No specific part number is in the U-Boot strings (that likely needs the
physical marking under the shield, or the DTB/kernel inside the JFFS2 regions). This
confirms the screen uses a **different SoC vendor than the camera** (Fullhan FH865X,
Linux 4.9.129) — two distinct platforms in the one product.

**Debug UART parameters, read from the U-Boot env (not yet connected to a terminal):**

```
baudrate=115200
bootargs=mem=86M console=ttyS0,115200 root=/dev/ram0 rw
bootdelay=0
serverip=192.0.0.128
```

Practical implications: console is **115200 8N1 on ttyS0**. `root=/dev/ram0` means
the running root filesystem is a **RAM disk** — runtime changes are not persistent,
which matters for any "root via UART + patch" plan (changes need to be written back
to the JFFS2 image, not just made live). `bootdelay=0` means there's no autoboot
countdown window to interrupt with a keypress — getting to the U-Boot prompt will
need something beyond "mash a key at power-on" (e.g. holding a GPIO/strap, or a
hardware trick covered in the methodology links below).

**File names found in the JFFS2 directory-entry nodes** (names only, from
uncompressed dirent nodes — image not mounted/extracted yet; 18 unique names across
23 dirent nodes):

```
uImage  ramdisk.gz  start.sh  logo.dav  filelist.enc.bin
app.tar.xz_secure  drivers.tar.xz_secure  gui_res.tar.xz_secure
resource.tar.xz_secure  wifi.tar.xz  wifi.tar.xz_secure
all_source.pem  dev_id_sec  dev_masterkey_sec  dev_info
ezlink_cfg  backend_cfg  backend_cfg_backup
```

The `_secure` suffix convention and `all_source.pem` / `filelist.enc.bin` line up
with the same signing/encryption scheme already documented for the camera (see
[firmware-analysis-hpd5.md](firmware-analysis-hpd5.md)). Naming note: `logo.dav`
*looks* like a Dahua artifact but `ezlink_cfg` confirms this is EZVIZ/Hikvision —
`.dav` as an extension is a red herring here, same as on the camera.

**⚠️ The raw 16 MB dump is not publishable as-is.** It contains `dev_masterkey_sec`,
`dev_id_sec`, and this unit's real Ethernet MAC address in the U-Boot environment —
device-specific secrets and identifiers. Only derived, redacted material (offsets,
partition layout, version strings, a MAC-scrubbed env dump) belongs in this repo —
never the full image.

### Methodology from sibling EZVIZ devices

- [EZVIZ DVR rooting](https://mattj.uk/blog/ezviz-dvr-root/) — UART header, interrupt U-Boot, `sf read` + TFTP flash dump.
- [EZVIZ BD-2402B1](https://blog.back.engineering/20/01/2022/) — U-Boot 115200, `rdinit=/bin/sh`.
- [UART/U-Boot intro](https://voidstarsec.com/blog/uart-uboot-and-usb), [SPI flash extraction](https://wrongbaud.github.io/posts/router-teardown/).

### Next steps

1. Carve the LZMA blob and each JFFS2 region into separate files; recover the real
   partition boundaries (since there's no `mtdparts`, check inside `uImage`/the DTB).
2. Extract `uImage` and `ramdisk.gz` from the JFFS2 data → kernel version, init,
   `start.sh`, and most likely the Molchip part number.
3. Determine whether the `_secure` payloads are encrypted or only signed — this
   decides whether "stock firmware + a UART-delivered helper" is the only viable
   local path, same as on the camera.
4. Connect the `Debug` header at 115200 8N1 to confirm the env above and capture a
   live boot log; figure out how to break into the U-Boot prompt with `bootdelay=0`.

Open questions remaining: the exact Molchip part number, how to interrupt U-Boot
with no autoboot window, whether U-Boot is otherwise locked down, and whether the
`_secure` files are encrypted (like the camera's `ezapp.xz_secure`) or just signed.
