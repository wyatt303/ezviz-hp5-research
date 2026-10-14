# How to download and unpack EZVIZ HP5 / HPD5 firmware

The firmware binaries are **not** included in this repo. Here is how to obtain and
unpack them yourself from the EZVIZ cloud.

## 1. Get the firmware's MD5 / download URL

EZVIZ serves firmware from a **content-addressed CDN**:

```
https://devupgrade-ali.ys7.com/<MD5>/digicap.dav
```

This URL needs **no authentication** — if you know the MD5, you can download it
directly. The catch: the cloud only *tells* you the MD5 when an update is **pending**
for your device. For a device already on the latest version, the upgrade-check
returns nothing.

### Option A — you already have the MD5

For example, HPD5 `V5.3.6 build 260512` is:

```
MD5  = 06512eb8a04adb47e723d331fc8f4ce5
size = 9,579,164 bytes
```

Skip to step 2.

### Option B — query the EZVIZ cloud for it

Use [`pyezvizapi`](https://pypi.org/project/pyezvizapi/). Log in once to get a token
file, then query the device:

```bash
pip install pyezvizapi
pyezvizapi -u YOUR_EMAIL -p YOUR_PASSWORD -r CUSTOM --save-token --token-file token.json devices
pyezvizapi --token-file token.json device_infos --serial YOUR_SERIAL
```

In the JSON, look for `UPGRADE.upgradePackageInfo` — when an update is available it
contains `md5`, `version`, `size` and `packageUrl`
(`devupgrade-ali.ys7.com/<md5>/digicap.dav`).

Equivalently, the app's firmware-check endpoint is
`POST /api/device/upgrade/info/get` with body `deviceSerialNo=<serial>` (public
params ride as session headers); the response field `upgradePacketInfo` carries the
`url`/`md5`. It returns `upgradePacketInfo: null, isNeedUpgrade: 0` when the device
is up to date.

> Community tool that automates the login + download + unpack:
> [yrambler2001/ezviz-firmware-dav-download-extract](https://github.com/yrambler2001/ezviz-firmware-dav-download-extract).

## 2. Download

```bash
curl -o firmware.dav "https://devupgrade-ali.ys7.com/<MD5>/digicap.dav"
# verify:
md5sum firmware.dav        # must equal <MD5>
```

## 3. Unpack the .dav

The `.dav` is a simple concatenation:

```
0x000000 .. 0x0000c3   196-byte proprietary header / metadata
0x0000c4               SquashFS  (app.img)           <- the application rootfs
0x47711c               legacy uImage  (mImage)       <- offsets vary per build
0x6e285c               legacy uImage  (uImage)
```

(The offsets above are for HPD5 `V5.3.6 build 260512`; run `binwalk` to get them for
your build.)

```bash
# See the layout and confirm offsets:
binwalk firmware.dav

# --- application rootfs (the useful part) ---
# Carve the SquashFS (it starts right after the 196-byte header).
dd if=firmware.dav of=app.img bs=1 skip=196 2>/dev/null
# unsquashfs reads the superblock size and ignores the trailing uImages:
unsquashfs app.img           # -> squashfs-root/   (libs, scripts, binaries)

# --- kernel images (optional) ---
# Carve them at the offsets binwalk reported, e.g.:
dd if=firmware.dav of=mImage bs=1 skip=$((16#47711c)) 2>/dev/null
dd if=firmware.dav of=uImage bs=1 skip=$((16#6e285c)) 2>/dev/null
# strip the 64-byte legacy uImage header to get the raw payload:
dd if=uImage of=uImage.payload bs=1 skip=64 2>/dev/null
```

> **Note:** the uImage/mImage kernel payloads are **encrypted / high-entropy** on
> this platform — `binwalk` will *not* find a kernel inside them, and they are not
> directly unpackable without the on-device decryption (`ezviz_toolbox`). The
> SquashFS `app.img` is the part you can actually read; even there the main
> application `ezapp` is shipped as the encrypted `ezapp.xz_secure`.

## 4. What you get

Inside `squashfs-root/` you'll find the application partition: `libsys.so`,
`libezbsp.so`, `libf7_isp.so`, `ezdsp`, `execSystemCmd`, `da_info`, `initrun.sh`,
`enc_publickey.txt`, `modules.tgz` (kernel modules), the encrypted `ezapp.xz_secure`,
etc. See [firmware-analysis-hpd5.md](firmware-analysis-hpd5.md) for a full walkthrough
of what's in there.

Suggested tools for going further: `binwalk`, `unsquashfs` (squashfs-tools),
`radare2`/`rizin` or Ghidra, `readelf`, `strings`, `xxd`.
