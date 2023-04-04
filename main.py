import configparser
import copy
import sys
import threading
import time
import pulsectl
import serial
from serial.tools import list_ports


class Mixer:
    """
    Handles communicating with the physical hardware of a Hardware Mixer. Use this in conjunction with an audio backend.
    """

    def __init__(self):
        """
        Opens a connection with a Hardware Mixer. It blocks until the connection is established.
        """
        self._volumes = [0, 0]
        self._port = serial.Serial()
        self._channels = 0
        self._connect_mixer()
        self.read_volumes()

    def __del__(self):
        self._port.close()

    def _connect_mixer(self, frequency=1):
        """
        A blocking function that will update this Mixer to use the channel count and port of the first mixer found. This
        will always take at least two seconds. It will continue to block until it finds a Hardware Mixer.
        :return:
        """
        if self._port:
            self._port.close()
        while True:
            for i in serial.tools.list_ports.comports():
                if i.subsystem == 'usb' and i.manufacturer[:7] == 'Arduino':
                    self._port = serial.Serial(i.device)
                    time.sleep(2)
                    if self._port.read_all()[:14] == b'Hardware Mixer':
                        self._port.write(b"\0")
                        self._channels = int.from_bytes(self._port.read(1), 'big')
                        return
                    self._port.close()
            time.sleep(1 / frequency)

    def read_volumes(self):
        """
        A blocking function that will return once the Hardware Mixer has updated its values. This only happens when the
        user changes the volume.
        :return: None
        """
        try:
            values = self._port.read(self._channels)
            for i in range(self._channels):
                self._volumes[i] = values[i] / 100
        except serial.SerialException:
            self._connect_mixer()
        else:
            pass

    def get_volumes(self):
        """
        A non-blocking call that will get the most recent values of the potentiometers connected to a mixer.
        :return: A list of floats from 0-1
        """
        return copy.deepcopy(self._volumes)


class PulseAudioConnection:
    """
    Manages the connection of a Mixer to the PulseAudio audio backend. After constructing an instance of this object,
    call `listen` to begin changing application volumes.
    """

    def __init__(self, mixer: Mixer):
        """
        Starts a new thread to watch for mixer input changes. Handles all
        :param mixer: Mixer to connect
        """
        self._mixer = mixer
        self._pulse = pulsectl.Pulse("Hardware Mixer")

        # Subscribe to volume change events
        self._pulse.event_callback_set(lambda x: self._pulse.event_listen_stop())
        self._pulse.event_mask_set(self._pulse.event_masks[9])
        threading.Thread(target=self._mixer_listener).start()

    def __del__(self):
        self._pulse.close()

    def _mixer_listener(self):
        """
        Reads volumes from the mixer and then allows the volume set loop to continue.
        :return: None
        """
        while True:
            self._mixer.read_volumes()
            self._pulse.event_listen_stop()

    def listen(self):
        """
        Performs the volume set loop. This function never returns, and must be called from the main thread.
        :return: None
        """
        while True:
            # Get the mixer volumes
            volumes = self._mixer.get_volumes()

            self._pulse.event_mask_set(self._pulse.event_masks[8])

            # Set the sink input volumes
            for sink in self._pulse.sink_input_list():
                app_name = sink.proplist.get('application.name')
                if not app_name:
                    continue

                try:
                    for i, channel_apps in enumerate(channels):
                        if app_name in channel_apps:
                            self._pulse.volume_set_all_chans(sink, volumes[i])
                            break
                    else:
                        if any_controller is not False:
                            self._pulse.volume_set_all_chans(sink, volumes[any_controller - 1])
                except pulsectl.PulseOperationFailed:
                    pass

            self._pulse.event_mask_set(self._pulse.event_masks[9])

            self._pulse.event_listen()


if __name__ == "__main__":
    config = configparser.RawConfigParser()
    if len(sys.argv) > 1:
        config.read(sys.argv[1])
    else:
        config.read("main.cfg")
    try:
        channels = [[j.strip() for j in config.get("PINS", str(i)).split(", ")] for i in
                    range(1, len(config.items()) + 1)]
    except configparser.NoSectionError:
        channels = [["Tauon Music Box", "Firefox", "VLC media player (LibVLC 3.0.18)", "WEBRTC VoiceEngine"], ["ANY"]]
    try:
        any_controller = channels.index(["ANY"]) + 1
    except ValueError:
        any_controller = False

    PulseAudioConnection(Mixer()).listen()
