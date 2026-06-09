# Audio-related helper functions

import fnmatch
import glob
import os
import subprocess
import pydub
import tmpfile

import helper
import ifs
import wavbintool

helper.check_ffmpeg()

def get_audio_file(filename):
    filename = helper.getCaseInsensitivePath(filename)
    if not filename or not os.path.exists(filename):
        return None

    if filename.lower().endswith('.xa'):
        wav_filename = helper.getCaseInsensitivePath(filename.lower().replace('.xa', '.wav'))

        if not os.path.exists(wav_filename):
            filename = get_wav_from_xa(filename)
        else:
            filename = wav_filename

    return pydub.AudioSegment.from_file(filename, "wav")


def get_duration(filename):
    filename = helper.getCaseInsensitivePath(filename)
    sound_file = get_audio_file(filename)

    if not sound_file:
        return 0

    return len(sound_file) / 1000


def clip_audio(input_filename, output_filename, duration, loop_duration=0.370):
    filename = helper.getCaseInsensitivePath(input_filename)
    sound_file = get_audio_file(filename)

    while duration * 1000 > len(sound_file):
        if len(sound_file) < loop_duration * 1000:
            tail_loop = sound_file[::]

        else:
            tail_loop = sound_file[-loop_duration * 1000:]

        sound_file = sound_file.append(tail_loop, crossfade=30 if len(tail_loop) > 30 else len(tail_loop) - 1)

    sound_file = sound_file[:duration * 1000]
    sound_file.export(output_filename, format="wav")

    # print("Generated", output_filename, len(sound_file) / 1000, duration)


def merge_bgm(bgm_info, input_foldername, output_filename=None):
    longest_duration = bgm_info['end']

    # Find maximum duration of BGM
    channels = 1
    for bgm in bgm_info['data']:
        filename = helper.getCaseInsensitivePath(os.path.join(input_foldername, bgm['filename']))
        print(filename)
        bgm['file'] = pydub.AudioSegment.from_file(filename)
        duration = bgm['timestamp'] + len(bgm['file']) / 1000

        if bgm['file'].channels > channels:
            channels = bgm['file'].channels

        if duration > longest_duration:
            longest_duration = duration

    output = pydub.AudioSegment.silent(duration=longest_duration * 1000, frame_rate=48000)
    output.set_channels(channels)

    for bgm in bgm_info['data']:
        output = output.overlay(bgm['file'], position=bgm['timestamp'] * 1000)

    if output_filename:
        temp_filename = output_filename
    else:
        temp_filename = tmpfile.mkstemp(suffix=".wav")

    output.export(temp_filename, format="wav")

    return temp_filename


def get_wav_from_xa(input_filename):
    input_filename = helper.getCaseInsensitivePath(input_filename)

    prefix = ""
    if helper.is_wsl():
        prefix = "./"
    elif os.name != "nt":
        prefix = "wine "

    cmd = "{}xa.exe -d \"{}\"".format(prefix, helper.get_windows_path(input_filename))
    subprocess.call(cmd, shell=True)

    temp_filename = os.path.splitext(input_filename)[0] + ".wav"
    tmpfile.add_temp_file(temp_filename)

    return temp_filename


def get_wav_from_pcm(input_filename):
    input_filename = helper.getCaseInsensitivePath(input_filename)

    prefix = ""
    if helper.is_wsl():
        prefix = "./"
    elif os.name != "nt":
        prefix = "wine "

    wav_filename = os.path.splitext(input_filename)[0] + ".wav"

    cmd = "{}vgmstream_cli.exe -q -o \"{}\" \"{}\"".format(prefix, helper.get_windows_path(wav_filename), helper.get_windows_path(input_filename))
    subprocess.call(cmd, shell=True)

    return wav_filename


def get_processed_wav(input_filename, output_filename=None, channels=1, bits=16, rate=48000):
    input_filename = helper.getCaseInsensitivePath(input_filename)

    output = get_audio_file(input_filename)

    if not output:
        return None

    made_change = False
    if output.sample_width != bits // 8:
        made_change = True
        output = output.set_sample_width(bits // 8)

    if output.channels != channels:
        made_change = True
        output = output.set_channels(channels)

    if output.frame_rate != rate:
        made_change = True
        output = output.set_frame_rate(rate)

    if not made_change and input_filename.lower().endswith('.wav'):
        # This file is already the exact requirements, just return the original
        return input_filename

    if output_filename == None:
        output_filename = tmpfile.mkstemp(suffix=".wav")

    #print("Converted {} to {}".format(input_filename, output_filename))
    output.export(output_filename, format="wav")

    return output_filename


def get_isolated_bgm(input, instrument):
    if os.path.isfile(input):
        filenames_bgm, ifs_path = ifs.extract(input)
        tmpfile.add_temp_folder(ifs_path)
        input = ifs_path

    else:
        filenames_bgm = glob.glob(input + "/bgm*.bin") + glob.glob(input + "/bgm*.wav")
        ifs_path = input

    # Find matching BGMs for each isolation type
    isolation_bgms_bin = {
        "drum": [("bgm*___k.bin", "bgm*d__k.bin"), ("bgm*___k_xg.bin", "bgm*d__k_xg.bin")],
        "guitar": [("bgm*__bk.bin", "bgm*_gbk.bin"), ("bgm*__bk_xg.bin", "bgm*_gbk_xg.bin")],
        "bass": [("bgm*___k.bin", "bgm*__bk.bin"), ("bgm*___k_xg.bin", "bgm*__bk_xg.bin")],
    }

    isolation_bgms_wav = {
        "drum": [("bgm*___k.wav", "bgm*d__k.wav"), ("bgm*___k_xg.wav", "bgm*d__k_xg.wav")],
        "guitar": [("bgm*__bk.wav", "bgm*_gbk.wav"), ("bgm*__bk_xg.wav", "bgm*_gbk_xg.wav")],
        "bass": [("bgm*___k.wav", "bgm*__bk.wav"), ("bgm*___k_xg.wav", "bgm*__bk_xg.wav")],
    }

    filenames_bgm_basename = [os.path.basename(x) for x in filenames_bgm]

    base_bgm = None
    instrument_bgm = None
    for isolated_bgms in [isolation_bgms_bin, isolation_bgms_wav]:
        isolated_bgm_set = isolated_bgms[instrument]

        for (base_bgm_pattern, instrument_bgm_pattern) in isolated_bgm_set:
            if not base_bgm:
                results = fnmatch.filter(filenames_bgm_basename, base_bgm_pattern)

                if len(results) > 0:
                    base_bgm = results[0]

            if not instrument_bgm:
                results = fnmatch.filter(filenames_bgm_basename, instrument_bgm_pattern)

                if len(results) > 0:
                    instrument_bgm = results[0]

            if base_bgm and instrument_bgm:
                break

        if base_bgm and instrument_bgm:
            break

    base_bgm = os.path.join(input, base_bgm)
    instrument_bgm = os.path.join(input, instrument_bgm)

    if base_bgm.endswith(".bin"):
        base_bgm_out = base_bgm.replace(".bin", ".wav")
        wavbintool.parse_bin(base_bgm, base_bgm_out)
        tmpfile.add_temp_file(base_bgm_out)
        base_bgm = base_bgm_out

    if instrument_bgm.endswith(".bin"):
        instrument_bgm_out = instrument_bgm.replace(".bin", ".wav")
        wavbintool.parse_bin(instrument_bgm, instrument_bgm_out)
        tmpfile.add_temp_file(instrument_bgm_out)
        instrument_bgm = instrument_bgm_out

    base_audio = pydub.AudioSegment.from_file(base_bgm).invert_phase()
    instrument_audio = pydub.AudioSegment.from_file(instrument_bgm)
    instrument_phased = instrument_audio.overlay(base_audio)

    return instrument_phased, base_bgm
