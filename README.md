# EZVIZ HP5 — firmware & reverse-engineering notes

Research material for the **EZVIZ HP5** smart video doorphone, gathered while
working toward local / Home Assistant interoperability and (eventually) getting
into the indoor screen's firmware.

The system has two units:

- **Indoor screen** — `CS-HP5-R100-1W2TFC`, the "brains" (WiFi + cloud, 7" touch).
- **Outdoor panel** — camera/doorbell, `CS-HPD5-R100-1H2`, connected to the screen
  over a 2-wire `DB-/DB+` bus.

## What's here

```
docs/
  findings.md                 Consolidated findings (firmware acquisition, SoC, unlock, HA, teardown plan)
  download-and-unpack.md      How to download the firmware from the EZVIZ CDN and unpack the .dav
  firmware-analysis-hpd5.md   Full static firmware analysis of the camera unit (Fullhan FH865X)
tools/
  hp5_cpd7_probe.py           Probe the CPD7 LAN media path (uses pyezvizapi; serials are placeholders)
  hp5_audio_diagnostic.py     Audio-path diagnostic
  hp5_local_proxy.py          LAN stream -> ChaCha20 decode -> MPEG-TS HTTP proxy helper
```

The firmware binaries are **not** bundled — see
[docs/download-and-unpack.md](docs/download-and-unpack.md) to fetch and extract them
yourself (the EZVIZ CDN is open and MD5-addressed).

## Highlights

- **SoC: Fullhan FH865X**, ARMv7, Linux 4.9.129 (camera unit).
- **Door unlock = a direct GPIO relay** on the camera (`ezbsp_set_relay_lock_status`
  → GPIO 28) — so fully-local unlock needs no CAS/CPD7 or DB± protocol RE, just
  root on the camera.
- The EZVIZ firmware CDN is **open and MD5-addressed**
  (`devupgrade-ali.ys7.com/<md5>/digicap.dav`, no auth) but only hands out the MD5
  when an update is pending.
- Full signed **custom firmware is not realistic** (secp256k1 signing, no private
  key, encrypted `ezapp`/kernels). Realistic path: stock firmware + a local helper
  via UART root.
- For Home Assistant today, use **[Bobsilvio/ezviz_hp7](https://github.com/Bobsilvio/ezviz_hp7)** (works for HP5/HPD5).

See [docs/findings.md](docs/findings.md) for details.

## Status

- Camera (HPD5) firmware: obtained and statically analyzed (see docs).
- **Indoor screen: boot flash dumped and analyzed.** The 16 MB `25Q128` SPI NOR (UF1)
  was desoldered and read (CH341A/flashrom, two byte-identical passes). Contains a
  U-Boot 2017.09 blob and 7 JFFS2 regions. SoC is **Molchip, ARMv7, dual-core**
  (distinct from the camera's Fullhan) — part number still unconfirmed. Next: connect
  the silkscreened `Debug` UART header (115200 8N1) and extract `uImage`/`ramdisk.gz`
  from the JFFS2 data. See [docs/findings.md](docs/findings.md#screen-teardown). The
  raw dump is **not** included (contains device-unique secrets/MAC) — help/photos
  welcome.

## Disclaimer

No private keys, account tokens, device verification codes, or captured media are
included in this repo. Firmware is EZVIZ / Hikvision property and is **not**
redistributed here — only instructions to obtain it from the vendor's own CDN, for
interoperability and security-research purposes on hardware you own. Everything is
provided **as-is, with no warranty** — flashing or modifying firmware can permanently
brick your device. Use at your own risk.
