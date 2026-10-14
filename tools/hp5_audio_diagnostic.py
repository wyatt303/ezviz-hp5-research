#!/usr/bin/env python3
"""Count CPD7 channels and plaintext PES packets without logging payloads/keys.
Run alongside hp5_local_proxy.py from ~/ezviz-test with the venv active.
"""
import argparse
from collections import Counter
import sys
import hp5_local_proxy as proxy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='hp5-lan')
    parser.add_argument('--duration', type=float, default=20)
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error('--duration must be positive')
    _, Decoder = proxy.load_cpd7(args.repo)
    counts = Counter()
    sizes = Counter()
    shapes = Counter()
    decrypted = Counter()
    pes = Counter()
    scanners = {}
    original = Decoder._handle_chunk
    saved_argv = sys.argv

    def scan(channel, data):
        # Keep partial PS packets across network chunks, with bounded buffering.
        buf = scanners.setdefault(channel, bytearray())
        buf.extend(data)
        while True:
            p = buf.find(b'\x00\x00\x01')
            if p < 0:
                if len(buf) > 3:
                    del buf[:-3]
                return
            if p:
                del buf[:p]
            if len(buf) < 6:
                return
            sid = buf[3]
            if sid < 0xb9:
                del buf[:4]
                continue
            if sid == 0xba:
                if len(buf) < 14:
                    return
                length = 14 + (buf[13] & 7)
            elif sid == 0xb9:
                length = 4
            else:
                payload_len = int.from_bytes(buf[4:6], 'big')
                if not payload_len:
                    del buf[:6]
                    continue
                length = 6 + payload_len
            if len(buf) < length:
                return
            pes[(channel, sid)] += 1
            del buf[:length]

    def observed(self, channel, payload):
        counts[channel] += 1
        sizes[channel] += len(payload)
        if not self._first_chunk_consumed:
            shapes[(channel, 'handshake')] += 1
        else:
            # Only protocol marker bytes, never nonce/key/media content.
            marker = payload[4:6]
            shape = 'ECDH_DATA' if marker == b'\x24\x02' else 'other'
            shapes[(channel, shape)] += 1
            if self.keys_derived and marker == b'\x24\x02':
                plain = self._decrypt_data_chunk(payload)
                decrypted[channel] += len(plain)
                if plain:
                    scan(channel, plain)
        return original(self, channel, payload)

    Decoder._handle_chunk = observed
    sys.argv = ['hp5_local_proxy.py', '--repo', args.repo, '--audio',
                '--capture', 'hp5-audio-diagnostic.ts', '--duration', str(args.duration)]
    try:
        result = proxy.main()
    finally:
        Decoder._handle_chunk = original
        sys.argv = saved_argv
        print('\nCPD7 CHANNEL SUMMARY (no keys or payload bytes):')
        for channel in sorted(counts):
            print(f'channel=0x{channel:02x}: packets={counts[channel]}, encrypted_payload_bytes={sizes[channel]}, decrypted_bytes={decrypted[channel]}')
        for (channel, shape), count in sorted(shapes.items()):
            print(f'channel=0x{channel:02x}: {shape}={count}')
        for (channel, sid), count in sorted(pes.items()):
            print(f'channel=0x{channel:02x}: PS_packet=0x{sid:02x}, count={count}')
    return result


if __name__ == '__main__':
    sys.exit(main())

