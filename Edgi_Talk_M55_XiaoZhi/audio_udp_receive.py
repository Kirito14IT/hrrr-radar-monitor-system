#!/usr/bin/env python3
"""
HTTP server to receive audio from the device.
"""

import socket
import wave
import os
import sys
import argparse
from datetime import datetime

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
NUM_CHANNELS = 2
HTTP_PORT = 8889  # Default HTTP port (UDP_PORT + 1)


def receive_audio_http(port: int, output_file: str = None, auto_play: bool = False):
    """Receive audio via HTTP and save to WAV file."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(1)

    print(f"HTTP Server listening on port {port}...")

    try:
        conn, addr = server.accept()
        print(f"Connection from {addr}")

        # Read HTTP request header
        header = b""
        while b"\r\n\r\n" not in header:
            data = conn.recv(1)
            if not data:
                break
            header += data

        print(f"Request: {header[:200]}")

        # Parse Content-Length
        content_length = 0
        for line in header.decode('utf-8', errors='ignore').split('\r\n'):
            if line.lower().startswith('content-length:'):
                content_length = int(line.split(':')[1].strip())
                break

        if content_length == 0:
            print("No Content-Length found!")
            conn.close()
            return None

        print(f"Receiving {content_length} bytes...")

        # Receive audio data
        audio_data = b""
        while len(audio_data) < content_length:
            remaining = content_length - len(audio_data)
            data = conn.recv(remaining)
            if not data:
                break
            audio_data += data
            print(f"Received {len(audio_data)} / {content_length} bytes")

        conn.close()

        # Determine output file
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"received_audio_{timestamp}.wav"

        # Save as WAV
        num_samples = len(audio_data) // SAMPLE_WIDTH
        print(f"Saving to {output_file} ({num_samples} samples, {num_samples / SAMPLE_RATE:.1f} seconds)...")

        with wave.open(output_file, 'wb') as wav_file:
            wav_file.setnchannels(NUM_CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio_data)

        print(f"Saved: {output_file}")

        # Playback if requested
        if auto_play:
            try:
                import pyaudio
                p = pyaudio.PyAudio()
                with wave.open(output_file, 'rb') as wav:
                    data = wav.readframes(wav.getnframes())
                    stream = p.open(
                        format=p.get_format_from_width(wav.getsampwidth()),
                        channels=wav.getnchannels(),
                        rate=wav.getframerate(),
                        output=True
                    )
                    stream.write(data)
                    stream.stop_stream()
                    stream.close()
                p.terminate()
                print("Playback finished")
            except ImportError:
                print("Playback skipped: pyaudio not available")
            except Exception as e:
                print(f"Playback error: {e}")

        return output_file

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        server.close()

    return None


def main():
    parser = argparse.ArgumentParser(description="Receive audio via HTTP and save as WAV")
    parser.add_argument('-p', '--port', type=int, default=HTTP_PORT,
                      help=f'HTTP port to listen on (default: {HTTP_PORT})')
    parser.add_argument('-o', '--output', type=str, default=None,
                      help='Output WAV file (default: auto-generated)')
    parser.add_argument('--play', action='store_true',
                      help='Auto-play after receiving')

    args = parser.parse_args()

    output = receive_audio_http(args.port, args.output, args.play)
    if output:
        print(f"Done: {output}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()