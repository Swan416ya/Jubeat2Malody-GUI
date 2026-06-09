import os
import subprocess
import tmpfile

import helper

def decode_data(data, rate, channels, bits):
    input_filename = tmpfile.mkstemp()
    output_filename = tmpfile.mkstemp()

    with open(input_filename, "wb") as f:
        f.write(data)

    prefix = ""
    if helper.is_wsl():
        prefix = "./"
    elif os.name != "nt":
        prefix = "wine "

    cmd = "{}adpcmwavetool.exe d \"{}\" \"{}\" {}".format(prefix, helper.get_windows_path(input_filename), helper.get_windows_path(output_filename), channels)
    subprocess.call(cmd, shell=True)

    with open(output_filename, "rb") as f:
        data = bytearray(f.read())

    return data

def encode_data(data, channels):
    input_filename = tmpfile.mkstemp()
    output_filename = tmpfile.mkstemp()

    with open(input_filename, "wb") as f:
        f.write(data)

    prefix = ""
    if helper.is_wsl():
        prefix = "./"
    elif os.name != "nt":
        prefix = "wine "

    cmd = "{}adpcmwavetool.exe e \"{}\" \"{}\" {}".format(prefix, helper.get_windows_path(input_filename), helper.get_windows_path(output_filename), channels)
    subprocess.call(cmd, shell=True)

    with open(output_filename, "rb") as f:
        data = bytearray(f.read())

    return data
