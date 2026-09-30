import unittest

import numpy as np

from smartaudiocrop.audio.player import AudioPlayer, PlaybackState


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.active = False
        self.start_count = 0
        self.stop_count = 0
        self.abort_count = 0
        self.close_count = 0
        self.time = 0.0
        self.fail_start = False

    def start(self):
        if self.fail_start:
            raise RuntimeError("output device unavailable")
        self.active = True
        self.start_count += 1

    def stop(self):
        self.active = False
        self.stop_count += 1

    def abort(self):
        self.active = False
        self.abort_count += 1

    def close(self):
        self.active = False
        self.close_count += 1


class StreamFactory:
    def __init__(self):
        self.streams = []
        self.fail_start = False

    def __call__(self, **kwargs):
        stream = FakeStream(**kwargs)
        stream.fail_start = self.fail_start
        self.streams.append(stream)
        return stream


class AudioPlayerTests(unittest.TestCase):
    def setUp(self):
        self.factory = StreamFactory()
        self.player = AudioPlayer(stream_factory=self.factory)
        self.audio = np.arange(10, dtype=np.float32)
        self.player.set_source(self.audio, 10)

    def tearDown(self):
        self.player.close()

    def callback(self, frame_count):
        stream = self.factory.streams[-1]
        outdata = np.empty((frame_count, 1), dtype=np.float32)
        stream.kwargs["callback"](outdata, frame_count, None, None)
        return outdata[:, 0]

    def test_stream_is_reused_for_pause_resume_stop_and_play(self):
        self.player.play(1, 8)
        stream = self.factory.streams[0]

        self.callback(2)
        self.player.pause()
        self.assertEqual(self.player.snapshot().position_frames, 3)
        self.assertEqual(self.player.snapshot().state, PlaybackState.PAUSED)

        self.player.resume()
        np.testing.assert_array_equal(self.callback(2), [3, 4])
        self.player.stop()
        self.player.play(2, 6)

        self.assertEqual(len(self.factory.streams), 1)
        self.assertEqual(stream.start_count, 1)
        self.assertEqual(stream.stop_count, 0)
        self.assertEqual(stream.abort_count, 0)

    def test_incompatible_source_format_recreates_stream(self):
        self.player.play(0, 2)
        first = self.factory.streams[0]

        self.player.set_source(np.zeros((8, 2), dtype=np.float32), 48_000)
        self.player.play(0, 4)

        self.assertEqual(first.close_count, 1)
        self.assertEqual(len(self.factory.streams), 2)
        self.assertEqual(self.factory.streams[1].kwargs["channels"], 2)

    def test_compatible_source_reuses_stream_and_resets_position(self):
        self.player.play(2, 8)
        stream = self.factory.streams[0]
        self.callback(2)

        self.player.set_source(np.arange(6, dtype=np.float32), 10)
        self.player.play(1, 4)

        self.assertEqual(len(self.factory.streams), 1)
        self.assertEqual(stream.close_count, 0)
        np.testing.assert_array_equal(self.callback(2), [1, 2])

    def test_non_looping_selection_zero_fills_final_buffer(self):
        self.player.play(2, 5)
        stream = self.factory.streams[0]
        output = np.empty((5, 1), dtype=np.float32)

        stream.kwargs["callback"](output, 5, None, None)

        np.testing.assert_array_equal(output[:, 0], [2, 3, 4, 0, 0])
        snapshot = self.player.snapshot()
        self.assertEqual(snapshot.state, PlaybackState.STOPPED)
        self.assertEqual(snapshot.position_frames, 5)

    def test_completed_selection_can_play_again_on_active_stream(self):
        self.player.play(2, 5)
        stream = self.factory.streams[0]
        self.callback(5)

        self.player.play(1, 4)
        output = self.callback(2)

        np.testing.assert_array_equal(output, [1, 2])
        self.assertTrue(stream.active)
        self.assertEqual(stream.start_count, 1)

    def test_loop_wraps_multiple_times_inside_buffer(self):
        self.player.play(2, 4, loop=True)

        np.testing.assert_array_equal(self.callback(7), [2, 3, 2, 3, 2, 3, 2])
        self.assertEqual(self.player.snapshot().position_frames, 3)

    def test_stop_resets_position_and_restart_uses_new_bounds(self):
        self.player.play(1, 8)
        self.callback(2)
        self.player.stop()

        self.assertEqual(self.player.snapshot().position_frames, 1)

        self.player.restart(4, 7)
        np.testing.assert_array_equal(self.callback(2), [4, 5])

    def test_empty_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            self.player.play(4, 4)

    def test_multichannel_source_is_copied_without_callback_conversion(self):
        source = np.arange(12, dtype=np.float32).reshape(6, 2)
        self.player.set_source(source, 10)
        self.player.play(1, 5)
        stream = self.factory.streams[-1]
        output = np.empty((2, 2), dtype=np.float32)

        stream.kwargs["callback"](output, 2, None, None)

        np.testing.assert_array_equal(output, source[1:3])

    def test_failed_initial_start_restores_stopped_state(self):
        self.factory.fail_start = True

        with self.assertRaisesRegex(RuntimeError, "device unavailable"):
            self.player.play(2, 6)

        snapshot = self.player.snapshot()
        self.assertEqual(snapshot.state, PlaybackState.STOPPED)
        self.assertEqual(snapshot.position_frames, 2)

    def test_failed_resume_restores_paused_state(self):
        self.player.play(1, 8)
        self.callback(2)
        self.player.pause()
        self.factory.streams[0].active = False
        self.factory.streams[0].fail_start = True

        with self.assertRaisesRegex(RuntimeError, "device unavailable"):
            self.player.resume()

        self.assertEqual(self.player.snapshot().state, PlaybackState.PAUSED)

    def test_snapshot_compensates_for_queued_output_latency(self):
        class TimeInfo:
            currentTime = 10.0
            outputBufferDacTime = 10.1

        self.player.play(2, 8)
        stream = self.factory.streams[0]
        output = np.empty((2, 1), dtype=np.float32)
        stream.time = 10.0
        stream.kwargs["callback"](output, 2, TimeInfo(), None)

        self.assertEqual(self.player.snapshot().position_frames, 2)

        stream.time = 10.2
        self.assertEqual(self.player.snapshot().position_frames, 3)


if __name__ == "__main__":
    unittest.main()
