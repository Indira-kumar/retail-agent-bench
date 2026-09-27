"""Audio taps that retain both sides of an evaluator room."""

from __future__ import annotations

import wave
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType

from livekit import rtc
from livekit.agents.voice import io


class WavWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._wave: wave.Wave_write | None = None
        self._stack = ExitStack()
        self._sample_rate: int | None = None
        self._num_channels: int | None = None

    def write(self, frame: rtc.AudioFrame) -> None:
        if self._wave is None:
            self._sample_rate = frame.sample_rate
            self._num_channels = frame.num_channels
            audio_file = wave.open(str(self._path), "wb")  # noqa: SIM115
            self._wave = self._stack.enter_context(audio_file)
            self._wave.setnchannels(frame.num_channels)
            self._wave.setsampwidth(2)
            self._wave.setframerate(frame.sample_rate)
        if frame.sample_rate != self._sample_rate or frame.num_channels != self._num_channels:
            raise ValueError("Audio format changed during a benchmark trial")
        self._wave.writeframesraw(bytes(frame.data))

    def close(self) -> None:
        if self._wave is not None:
            self._stack.close()
            self._wave = None

    def __enter__(self) -> WavWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


class RecordingAudioInput(io.AudioInput):
    def __init__(self, source: io.AudioInput, writer: WavWriter) -> None:
        super().__init__(label="benchmark-output-recorder", source=source)
        self._writer = writer

    async def __anext__(self) -> rtc.AudioFrame:
        frame = await super().__anext__()
        self._writer.write(frame)
        return frame


class RecordingAudioOutput(io.AudioOutput):
    def __init__(self, output: io.AudioOutput, writer: WavWriter) -> None:
        super().__init__(
            label="benchmark-input-recorder",
            capabilities=io.AudioOutputCapabilities(pause=output.can_pause),
            next_in_chain=output,
            sample_rate=output.sample_rate,
        )
        self._writer = writer

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        self._writer.write(frame)
        assert self.next_in_chain is not None
        await self.next_in_chain.capture_frame(frame)

    def flush(self) -> None:
        super().flush()
        assert self.next_in_chain is not None
        self.next_in_chain.flush()

    def clear_buffer(self) -> None:
        assert self.next_in_chain is not None
        self.next_in_chain.clear_buffer()
