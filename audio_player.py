import sounddevice as sd


class AudioPlayer:
    def play(
        self,
        audio,
        sample_rate,
    ):
        sd.play(
            audio,
            sample_rate,
        )

    def stop(self):
        sd.stop()   