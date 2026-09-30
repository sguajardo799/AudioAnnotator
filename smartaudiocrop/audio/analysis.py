import numpy as np
from scipy.signal import stft


def spectrogram(audio, sr, n_fft=1024, hop_size=256):
    frequencies, times, Zxx = stft(
        audio,
        fs=sr,
        nperseg=n_fft,
        noverlap=n_fft - hop_size,
    )

    magnitude = np.abs(Zxx)

    spec_db = 20 * np.log10(magnitude + 1e-10)
    spec_db -= spec_db.max()

    return spec_db.T, times, frequencies
