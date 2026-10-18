# Can a generic RTSP camera be added by editing configuration alone?

Date: 2026-10-17. Scope: offline inspection of the extracted screen configuration
and its startup/connection code. No access to the physical screen or a camera
was available. No device test was performed and the original configuration was
not changed.

## Result

The normal additional-camera path in this firmware does not provide a confirmed
configuration-only way to open an arbitrary RTSP URL with a username/password.
There are connection-related fields in `accessories`, but the startup code
forces additional channels into the remote EZVIZ implementation. A generic RTSP
URL field is absent from the extracted profile.

The existence of an RTSP client inside the executable therefore does not make
editing this file sufficient. The earlier suggestion that a simple entry might
work was a possibility to investigate, not a demonstrated capability.

## Actual configuration fields

The inspected `backend_cfg.plaintext.json` contains one accessory, channel 0,
the outdoor door station. The following field names and types are present;
credentials and identifiers are intentionally not reproduced:

| Field | Type | Relevant purpose |
|---|---|---|
| `chan` | number | Accessory channel |
| `ip` | string | Device IP address |
| `port` | number | Accessory connection port; not established as an arbitrary RTSP port |
| `usrname` | string | Username, with this exact spelling |
| `pwd` | string | Password |
| `proto_type` | number | Protocol selection stored in the configuration |
| `prod_type` | number | Product category |
| `ifname` | string | Network interface |
| `active`, `auth` | numbers | Stored accessory activation/authentication state |
| `stream` | array | Main/substream codec, resolution, bitrate and audio parameters |
| `remote_cfg` | object | Remote SDK camera IDs, service hosts/ports and capability fields |

There is no `rtsp_url`, `url`, or editable RTSP stream-path field in this
extracted accessory. `stream` contains encoding parameters rather than URLs.
The presence of `remote_cfg.domain_name` and `remote_cfg.stream_port` does not
establish that the remote SDK accepts RTSP in those fields.

This schema observation concerns the extracted profile. It is not proof that
no unpopulated or legacy field exists anywhere in the application. References
to the configuration reader were located, but its containing function was not
available for full decompilation in the current Ghidra analysis.

## Startup overrides the protocol for additional channels

`_acsy_recover` at Ghidra address `0x25f60c` restores saved accessories. The
boundary helper at `0x062540` returns **1** in this executable. Consequently:

- channel 0 follows the built-in door-station branch;
- channels 1 and above follow the additional-accessory branch;
- the additional branch assigns protocol **6** before registering the main
  accessory, irrespective of the saved protocol value;
- it creates a companion using protocol **7**, except for the NAS product
  category where it uses protocol **1**.

`accessory_create_ex` performs a similar forced remote registration for the
interactive Add path, as documented in `additional-ezviz-cameras.md`.

Therefore setting, for example, `proto_type: 1` in a newly appended channel does
not make that channel a standalone RTSP client after ordinary startup.

## Protocol 1 is not a generic RTSP shortcut

The HCNet initialization routine at `0x28be38` registers the same implementation
table for protocol IDs 1 and 2. Its online-state method at `0x28b6b8` checks
HCNet login and exchange state and consults remote discovery state. These IDs
should not be relabeled "plain RTSP" merely because an RTSP client also exists.

Existing static string-reference evidence for `_open_rtsp_stream` also shows
RTSP-port negotiation followed by construction of `/ch%d/%s/av_stream`. This
supports a vendor-specific streaming path rather than a configurable arbitrary
URL. The function containing that older reference was not available for full
decompilation in this pass, so this observation is supporting evidence, not the
sole basis for the conclusion above.

Changing the door-station channel to evade the additional-channel branch would
replace the existing door-station profile. It is not a demonstrated solution
for adding a second camera and was not attempted.

## File format and test boundary

The plaintext JSON is an extracted analysis copy. The device's `backend_cfg`
uses an encrypted container with a plaintext digest; editing the JSON copy
alone would not install a valid new configuration on the screen.

An offline JSON syntax check could show that a new object is well-formed, but
it could not show that the screen accepts the camera or displays video. The
code above already identifies a concrete obstacle before such a runtime test:
the additional-channel protocol is overwritten during restoration.

No deployable RTSP profile is supplied because neither an accepted arbitrary
RTSP URL field nor an effective configuration-only protocol selection was
established. A next implementation would have to address protocol registration
or expose the RTSP client explicitly before a generic URL test is meaningful.

## Evidence

- Artifact SHA-256: `a8ef273c1d60213fcae8ae7567c0d2cb199162bc269766f0cade5e86045a7377`.
- Saved-accessory restoration: `ev_4f8d29dbc3517bac18fb1fac4be4aab8a482fe11474c43bc13cdb81a17ca7e2f`.
- Built-in-channel boundary returns 1: `ev_f65b6a2cd67a8a466f2ec122831dad5fa5151b8a1a8050188580720c932b2f36`.
- Protocol IDs 1/2 HCNet registration: `ev_08661c698b22bcf39ac44bf82d88d69edd2bf6f909a789fceb022fbc18cdc44f`.
- HCNet method table: `ev_917185ef6cfe382420a9c9df9c37419423bfa28c232cf3d9d9bd4cf1b913de3e`.
- HCNet online-state checks: `ev_4cdc80a587db293d7e6ccf586bae7fd1ffef0e26e896e9cecd9244f76492a2d9`.
- Configuration-reader reference coverage: `ev_a2a29938344efcdd5f96bf92b810cebabf7b77ae80a117203ba76863fbf8ab55`.

This is static evidence of what the shipped code does, not an observation of
the screen running with a modified configuration.
