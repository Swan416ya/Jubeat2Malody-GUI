import argparse
import os
import adpcmwave
import numpy
import struct
import wavfile
import pydub

import audio
import tmpfile

import helper

helper.check_ffmpeg()

def parse_bin(input_filename, output_filename):
    with open(input_filename,"rb") as f:
        data = f.read()

    if data[0:4].decode('ascii') != "BMP\0":
        print("Not a BMP audio file")
        exit(1)

    data_size, loop_start, loop_end = struct.unpack(">III", data[0x04:0x10])
    channels, bits = struct.unpack("<HH", data[0x10:0x14])
    rate, = struct.unpack(">I", data[0x14:0x18])

    is_looped = True if loop_start > 0 or loop_end > 0 else False

    if is_looped:
        loops = [(loop_start, loop_end)]
        print("Found loop offsets: start = %d, end = %d" % (loop_start, loop_end))

        # foobar2000 plugin (rename .wav to .wavloop): http://slemanique.com/software/foo_input_wave_loop.html
        print("Loop information will be stored in a SMPL chunk for playback in players that have support for SMPL loops")
    else:
        loops = None

    data = bytearray(data[0x20:])
    output = adpcmwave.decode_data(data, rate, channels, bits)
    output = numpy.ndarray((int(len(output) // 2 // channels), channels), numpy.int16, output, 0)
    wavfile.write(output_filename, rate, output, loops=loops)

def parse_wav(input_filename, output_filename, loop_start=None, loop_end=None, channels=2, rate=48000):
    input_filename = audio.get_processed_wav(input_filename, channels=channels, rate=rate, bits=16)

    if not input_filename:
        return

    rate, data, bits, loops = wavfile.read(input_filename, readloops=True)
    channels = 1 if len(data.shape) == 1 else data.shape[1]

    if len(loops) > 0:
        if len(loops) > 1:
            print("Found %d loops, only reading first loop" % len(loops))
        loop_start, loop_end = loops[0]
    else:
        loop_start = 0
        loop_end = 0

    output = adpcmwave.encode_data(data, channels)

    with open(output_filename, "wb") as outfile:
        outfile.write("BMP\0".encode('ascii'))
        outfile.write(struct.pack(">I", len(output)))
        outfile.write(struct.pack(">I", loop_start))
        outfile.write(struct.pack(">I", loop_end))
        outfile.write(struct.pack("<H", channels))
        outfile.write(struct.pack("<H", bits))
        outfile.write(struct.pack(">I", rate))
        outfile.write(bytearray([0] * 8))
        outfile.write(output)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-e', '--encode', action='store_true', help='Encode mode')
    group.add_argument('-d', '--decode', action='store_true', help='Decode mode')
    parser.add_argument('-i', '--input', help='Input file', required=True)
    parser.add_argument('-o', '--output', help='Output file', required=True)
    parser.add_argument('-c', '--channels', help='Number of channels for input WAV', type=int, default=2)
    parser.add_argument('-r', '--rate', help='Sample rate for input WAV', type=int, default=48000)
    parser.add_argument('-ls', '--loop-start', help='Loop start point (in bytes)', type=int, default=None)
    parser.add_argument('-le', '--loop-end', help='Loop end point (in bytes)', type=int, default=None)
    args = parser.parse_args()

    if args.decode:
        parse_bin(args.input, args.output)
    elif args.encode:
        parse_wav(args.input, args.output, args.loop_start, args.loop_end, args.channels, args.rate)
