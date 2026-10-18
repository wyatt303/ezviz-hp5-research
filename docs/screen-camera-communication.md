# Indoor screen to outdoor camera communication

For cameras added from the EZVIZ account, see
[Additional EZVIZ cameras on the indoor screen](additional-ezviz-cameras.md).
That workflow has separate account authorization, remote SDK and local-companion
handling; it should not be inferred solely from the door-station link below.

## Scope

This note describes how the indoor HP5 screen communicates with the outdoor
HPD5 camera, based primarily on static analysis of the screen's stripped ARM
ELF executable `ezapp`.

Analyzed artifact:

- file: `ezapp`
- SHA-256: `a8ef273c1d60213fcae8ae7567c0d2cb199162bc269766f0cade5e86045a7377`
- analysis provider: Ghidra 12.1.4 through REA

No device credentials, pairing keys, Wi-Fi passwords, tokens, or decrypted
payloads are reproduced in this document.

## Executive conclusion

At application level, the screen and outdoor unit communicate as two IP hosts.
The screen uses a dedicated Ethernet interface, `eth0`, configured as
`192.168.99.1/24`. Its configuration contains a DHCP range from
`192.168.99.50` through `192.168.99.200`; the paired outdoor unit is recorded as
`192.168.99.52` with port `8000`.

The proprietary DB-/DB+ pair is therefore below the `ezapp` protocol layer.
The firmware and device tree establish an Ethernet MAC/PHY path, while the
application sees an ordinary IPv4 peer. It is highly likely that dedicated
hardware carries Ethernet and power over the two-wire link, but the precise
line encoding and analogue front end cannot be established from `ezapp` alone.

The main application-level path is:

```text
Indoor screen                                      Outdoor camera

UI action
  -> EzLinkSDK local authorization
  -> JSON operation: iot/LiveStreaming/StartPreview
  -> encrypted, segmented CoAP message
  -> IPv4 UDP via eth0 ---------------------------> paired device IP/port
                                                     validates request
                                                     starts media sender
  <- media to screen IP + negotiated SRTPort <----- camera-initiated stream
  -> PS/RTP unpacking
  -> hardware/software video decode
  -> display

Physical carrier underneath: DB-/DB+ two-wire power/data link
```

Here, `SRTPort` is the literal field name used by the firmware. Static analysis
does not by itself prove that the acronym means Secure RTP, nor does it reveal
the runtime-selected port value.

## 1. Private link topology

The screen maintains a network dedicated to the outdoor unit, separate from
the household Wi-Fi connection:

| Item | Observed value | Confidence |
|---|---:|---|
| Screen interface | `eth0` | High |
| Screen address | `192.168.99.1/24` | High |
| Configured DHCP pool | `192.168.99.50` - `192.168.99.200` | High |
| Paired outdoor unit | `192.168.99.52` | High for this extracted configuration |
| Paired-device port | `8000` | High for this extracted configuration |
| Physical terminals | DB-/DB+ | High |
| Exact DB± electrical modulation | Unknown | Requires hardware analysis |

The screen image includes `dnsmasq`, and its configuration contains the DHCP
pool above. Together with the screen's fixed `.1` address, this strongly
indicates that the screen is the DHCP server for the private link.

The device tree exposes a Synopsys DesignWare Ethernet MAC and PHY alternatives
for RMII/RGMII. This supports the Ethernet interpretation, but it does not
identify the separate component that adapts Ethernet to the two-wire DB± bus.

## 2. Pairing and trust establishment

The EzLinkSDK pairing subsystem creates or joins a device group and persists an
authorized-device record. The binary contains the following relevant pairing
operations:

- `EzLinkSDK_Pair_TrigPair_Ezviz`
- `EzLinkSDK_Pair_TrigPair_ForHub`
- `EzLinkSDK_Pair_TrigPair_ByChecktype`
- activation/pass-configuration and capability-discovery operations
- group creation and paired-state checks

The persistent EzLink configuration contains authorized-device metadata and
per-device/group key material. Values are deliberately omitted here. Before a
preview command is transmitted, `ezLink_start_preview` requests local
authorization (`FUN_00621964`, mode 3). Failure stops the operation rather than
falling back to an unauthenticated request.

## 3. Preview control flow

The screen initiates live view with the following call chain:

```text
ezLink_start_preview                    0x608874
  -> local group authorization          0x621964
  -> GenStartPreviewReq                 0x6076d0
  -> group OTAP send                    0x62e334
  -> Grp_SendLanMsg                     0x630278
  -> EzLinkSDK_Trans_SendMsg            0x6aff48
  -> Msg_Send / Msg_Seg_Send            0x6b7df8 / 0x6b77c4
  -> Msg_Encrypt_Send                   0x6b61b8
  -> link_send                          0x6b1c84
  -> IPv4 UDP sendto                    0x61eae0
```

`ezLink_start_preview` constructs an `operate` request in the `iot` namespace,
with domain `LiveStreaming` and action `StartPreview`. The request body contains:

```json
{
  "ReceiverInfo": {
    "ECDHInfo": {
      "ECDHVersion": "<runtime value>",
      "ECDHPublicKey": "<ephemeral public value>"
    },
    "serverSessionID": "<runtime value>",
    "ipV4Address": "<screen address>",
    "SRTPort": "<screen listening port>"
  },
  "streamType": "<requested quality/type>"
}
```

This is the key architectural detail: the screen does not merely open a fixed
media URL. It tells the camera where to send the selected stream and supplies
ECDH session information. The outdoor unit then sends media back to the screen's
advertised address and port.

## 4. Control transport

The EzLinkSDK transport found in this build identifies itself through source
paths as `EzLinkSDK_V3.1.1_Heartbeat`.

For ordinary paired-device traffic, the application:

1. serializes the operation into an EzLink protocol message;
2. optionally translates newer group messages for older peer protocol versions;
3. divides a large message into chunks of at most 1024 bytes;
4. encrypts the message with a stored device/group key;
5. wraps it in CoAP format; and
6. sends it with IPv4 UDP `sendto()` to the selected peer address and port.

The encryption routine uses mbedTLS AES with a 128-bit key and CBC mode, with
block padding performed before encryption. The transport header contains the
protocol/version value `0x3101`. Authentication and replay/session details are
maintained in the authorized-device and message state; a missing key causes the
send operation to fail.

The socket layer also supports discovery/broadcast mechanisms:

| Mechanism | Address/port or link type |
|---|---|
| IPv4 multicast | `239.255.255.251` |
| Discovery-related UDP port | `50160` (`0xc3f0`) |
| Broadcast-related UDP port | `50162` (`0xc3f2`) |
| Layer-2 fallback/broadcast | Linux `AF_PACKET`, protocol `0x8d8d` |

These paths explain how unpaired devices can be discovered before the ordinary
authorized unicast path is available. They do not imply that every production
message is broadcast.

## 5. Receiving messages from the outdoor unit

`EzLinkSDK_Grp_MsgRecvTask` (`FUN_00622568`) continuously removes messages from
an internal receive queue, logs their domain and type, selects a registered
domain handler, and dispatches the message through its callback. This supplies
the reverse direction used for device state, events, responses, and related
notifications.

The binary includes handlers/types for online-state changes and IP-address
changes, which are consistent with a paired camera whose address is assigned on
the private network. A packet capture is still required to map each doorbell,
tamper, motion, and call event to its exact on-wire domain and payload.

## 6. Media handling and the separate RTSP client

The accessory layer contains media workers for both MPEG-PS and RTP unpacking,
as well as a talk/audio thread. It also contains a generic
`accessory_stream_open_rtsp` path that creates an RTSP session, binds it to a
chosen interface, configures buffering and credentials, and starts the unpack
thread.

The presence of this RTSP client does **not** prove that the paired HPD5 uses
RTSP for the screen preview. The HPD5-specific preview path analyzed above uses
the EzLink `StartPreview` negotiation and instructs the camera to push media to
the screen's advertised `SRTPort`. The RTSP code may support other accessory
models or act as an alternative/fallback path.

Similarly, the camera's CPD7 service on TCP port 9020, used by the separate LAN
stream tooling in this repository, must not be conflated with the screen's
private-link preview path. No fixed `9020` value was found in this screen binary.

## 7. Door-unlock commands use the same channel

Door and gate unlock requests follow the same authorized EzLink group transport.
The application sends domain `DoorLockMgr`, identifier `RemoteUnlockReq`, with a
small JSON body selecting lock 1 or 2:

```json
{"params":{"lockNo":1}}
```

The request then passes through `Grp_SendLanMsg`, message encryption, CoAP
framing, and UDP delivery just like the preview control operation. This means
the screen-to-camera connection carries control operations as well as live-view
negotiation.

## 8. What is proven, inferred, and still unknown

### Confirmed from the extracted firmware and configuration

- the screen and outdoor unit communicate as IPv4 peers over `eth0`;
- a dedicated `192.168.99.0/24` network is configured;
- the paired camera record points to `192.168.99.52` and port `8000`;
- EzLink control messages are authorized, AES-CBC encrypted, CoAP-framed, and
  sent over UDP;
- `StartPreview` carries the screen's return address/port and ECDH information;
- the SDK has a bidirectional receive-and-dispatch task;
- unlock operations use the same group transport.

### Strong inference

- the screen provides DHCP on this private network;
- Ethernet is transported over DB-/DB+ by hardware below the Linux/application
  layer;
- the paired-device record supplies the ordinary unicast destination used for
  HPD5 control traffic.

### Requires runtime capture or hardware inspection

- the exact UDP source and destination ports used in each session;
- the runtime value and precise protocol meaning of `SRTPort`;
- the complete media framing, codec selection, and key derivation sequence;
- the exact on-wire payloads for doorbell, motion, tamper, and call events;
- DB± voltage levels, modulation, line coding, and the converter IC.

## 9. Recommended verification capture

On a rooted screen, collect a short capture while performing one action at a
time:

```sh
ip addr show dev eth0
ip neigh show dev eth0
ss -lunp
ss -tnp
tcpdump -ni eth0 -s0 -w /tmp/hp5-db-link.pcap
```

A useful sequence is: cold boot, pairing/discovery, doorbell press, open live
view, start/stop two-way audio, then unlock. Correlating timestamps with the UI
and EzLink logs should resolve the remaining dynamic ports and event domains.
The capture may contain identifiers and encrypted session material and should
therefore be treated as sensitive.

To identify the DB± physical layer, application firmware is insufficient. That
requires a teardown to identify the line-interface IC and a passive electrical
capture made with appropriately isolated equipment.

## Static-analysis evidence references

The following REA evidence identifiers correspond to the principal findings:

- preview entry: `ev_2310e3dc1769d3d09f6d7ccf57b8fa8c854d243914f7eaa6d64b6b35e740be7e`
- preview JSON generator: `ev_5c63038d85f0170ca8b8d261c1447f3b7bcd56c815efefeef5be56c84a81b06e`
- local authorization: `ev_92e3c449812a8aece82424bf9262278561d8ef3179154a1dbcc6aaffd6cd09d9`
- group OTAP send: `ev_b49ae3d194155db0ae8f9d285746be14f1bc2a81cbcc116b1863bb440894a529`
- LAN message construction: `ev_9b56e10a32f45280292c1f5bd424a61d4bfbf2495774cb18e7512e1daf695978`
- segmentation: `ev_291eaf31877b332a79c183d438ac64c2a9acf79faecf0d2d9c0565222353ff09`
- encryption/send: `ev_368d0e4147ce32053ad3e887c7787f89f66518fb6dec6109f9523eb813c74c71`
- AES-CBC implementation: `ev_ec5453d445f12383a81bfcc463b95c20c03e27082c438a1a6d2ab5c6dfb6fb2c`
- CoAP framing: `ev_a1a97facdf11fb0a5119814157de072953231cbb6a078f3cf791a6feb9397f9e`
- UDP and layer-2 socket send: `ev_14a5d82a1181a3aab9308e5ebbf65bb4a66adfbeb0ed56101e759049bf020e32`
- socket binding and multicast address: `ev_46d5aaee75d120718820e628e291b3e9e2a8eacc7ef0088584470011ad650a74`
- inbound group-message dispatch: `ev_ad9f47fdd6fa71fe438d082f339071c082518f38018aff6c69eede2c738f00fa`
- generic RTSP accessory path: `ev_43a8ad4701bde97cab9bebbee55d45999f7335fa0fc2dbb122146febcee6ca8e`

