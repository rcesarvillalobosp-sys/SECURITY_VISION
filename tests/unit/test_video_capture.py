from __future__ import annotations

import threading
import time
from pathlib import Path

import av
import numpy as np
import pytest

from security_vision.core.interfaces.video import SourceStatus, VideoSource, VideoSourceConfig, VideoSourceError
from security_vision.modules.cameras.supervisor import CameraSpec, CameraState, CameraSupervisor, ReconnectPolicy
from security_vision.modules.video.frame_slot import FrameSlot
from security_vision.plugins.video_sources.pyav_source import PyAVVideoSource, _with_credentials
from security_vision.plugins.video_sources.test_pattern import TestPatternSource

FAST = ReconnectPolicy(initial_delay=0.05, max_delay=0.2, stall_timeout=2.0)


def make_video(path: Path, frames: int = 30, size=(160, 120), fps: int = 15) -> Path:
    """Vídeo de prueba codificado con MPEG-4 Part 2 (codificador LGPL de FFmpeg; no x264)."""
    with av.open(str(path), "w") as out:
        st = out.add_stream("mpeg4", rate=fps)
        st.width, st.height, st.pix_fmt = size[0], size[1], "yuv420p"
        for i in range(frames):
            img = np.full((size[1], size[0], 3), (i * 8) % 256, dtype=np.uint8)
            for pkt in st.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(pkt)
        for pkt in st.encode():
            out.mux(pkt)
    return path


# --- FrameSlot -----------------------------------------------------------------------

def test_frame_slot_keeps_latest_and_counts_drops():
    slot: FrameSlot[int] = FrameSlot(capacity=2)
    for i in range(5):
        slot.put(i)
    assert slot.dropped == 3 and len(slot) == 2
    assert slot.get_latest(0) == 4
    assert slot.dropped == 4  # el 3 no consumido también cuenta
    assert slot.get_latest(0.01) is None


def test_frame_slot_put_never_blocks_and_get_wakes_up():
    slot: FrameSlot[int] = FrameSlot()
    got = []
    t = threading.Thread(target=lambda: got.append(slot.get_latest(2)))
    t.start()
    time.sleep(0.05)
    slot.put(7)
    t.join(1)
    assert got == [7]


# --- contrato VideoSource (todas las implementaciones) ---------------------------------

def _sources(tmp_path: Path) -> list[VideoSource]:
    video = make_video(tmp_path / "clip.mp4")
    return [
        TestPatternSource(VideoSourceConfig(uri="testpattern://?width=64&height=48&fps=100")),
        PyAVVideoSource(VideoSourceConfig(uri=str(video))),
        PyAVVideoSource(VideoSourceConfig(uri=video.resolve().as_uri())),
    ]


def test_video_source_contract(tmp_path):
    for src in _sources(tmp_path):
        assert src.get_status() is SourceStatus.DISCONNECTED
        src.connect()
        assert src.get_status() is SourceStatus.CONNECTED
        frames = [src.read_frame(1.0) for _ in range(5)]
        assert all(f is not None for f in frames)
        f = frames[-1]
        assert f.data.dtype == np.uint8 and f.data.ndim == 3 and f.data.shape[2] == 3
        assert f.captured_at.tzinfo is not None
        assert [x.frame_id for x in frames] == sorted(x.frame_id for x in frames)
        meta = src.get_metadata()
        assert meta.width == f.width and meta.height == f.height
        src.disconnect()
        assert src.get_status() is SourceStatus.DISCONNECTED


def test_pyav_file_end_loop_and_resize(tmp_path):
    video = make_video(tmp_path / "c.mp4", frames=10)
    once = PyAVVideoSource(VideoSourceConfig(uri=str(video)))
    once.connect()
    for _ in range(10):
        once.read_frame(1)
    with pytest.raises(VideoSourceError) as e:
        once.read_frame(1)
    assert e.value.retryable is False
    looped = PyAVVideoSource(VideoSourceConfig(uri=str(video), width=80, height=60, options={"loop": True}))
    looped.connect()
    frames = [looped.read_frame(1) for _ in range(25)]
    assert all(f.data.shape == (60, 80, 3) for f in frames)


def test_pyav_missing_file_is_not_retryable(tmp_path):
    src = PyAVVideoSource(VideoSourceConfig(uri=str(tmp_path / "nope.mp4")))
    with pytest.raises(VideoSourceError) as e:
        src.connect()
    assert e.value.retryable is False and src.get_status() is SourceStatus.ERROR


def test_rtsp_credentials_are_injected_and_quoted():
    url = _with_credentials("rtsp://10.0.0.5:554/stream1", "admin", "p@ss:w/rd")
    assert url == "rtsp://admin:p%40ss%3Aw%2Frd@10.0.0.5:554/stream1"


def test_unreachable_rtsp_fails_fast_with_timeout():
    # Puerto local cerrado: debe fallar rápido y ser reintentable (no colgarse).
    src = PyAVVideoSource(VideoSourceConfig(uri="rtsp://127.0.0.1:1/none",
                                            options={"open_timeout": 2, "read_timeout": 2}))
    t0 = time.monotonic()
    with pytest.raises(VideoSourceError) as e:
        src.connect()
    assert e.value.retryable and time.monotonic() - t0 < 10


# --- supervisor -----------------------------------------------------------------------

def _factory(spec: CameraSpec) -> VideoSource:
    return TestPatternSource(spec.source)


def _spec(cid: str, query: str) -> CameraSpec:
    return CameraSpec(cid, cid, "testpattern", VideoSourceConfig(uri=f"testpattern://?width=32&height=24&{query}"))


def test_one_failing_camera_does_not_affect_others():
    events: list[tuple[str, CameraState]] = []
    sup = CameraSupervisor(_factory, FAST, on_status=lambda c, s, d: events.append((c, s)))
    try:
        sup.start(_spec("ok1", "fps=50"))
        sup.start(_spec("dead", "fail_connect=1"))
        sup.start(_spec("ok2", "fps=50"))
        time.sleep(1.0)
        w = sup.workers()
        assert w["ok1"].stats.frames > 20 and w["ok2"].stats.frames > 20
        assert w["dead"].stats.frames == 0 and w["dead"].stats.connection_errors >= 3
        assert w["dead"].stats.state is CameraState.RECONNECTING
        assert all(x.alive for x in w.values())
    finally:
        sup.stop_all()
    assert ("ok1", CameraState.STREAMING) in events and ("ok1", CameraState.STOPPED) in events


def test_camera_reconnects_after_stream_interruption():
    sup = CameraSupervisor(_factory, FAST)
    try:
        w = sup.start(_spec("flaky", "fps=100&fail_after=10"))
        time.sleep(1.0)
        assert w.stats.reconnects >= 2 and w.stats.read_errors >= 2
        assert w.stats.frames >= 30
    finally:
        sup.stop_all()


def test_slow_consumer_gets_fresh_frames_and_drops_are_counted():
    sup = CameraSupervisor(_factory, FAST)
    try:
        w = sup.start(_spec("cam", "fps=100"))
        ids = []
        for _ in range(5):
            time.sleep(0.1)  # consumidor a ~10/s frente a 100 fps de captura
            f = w.slot.get_latest(1)
            ids.append(f.frame_id)
        assert ids == sorted(ids) and ids[-1] - ids[0] >= 20  # no se queda atrás
        assert w.slot.dropped > 20
    finally:
        sup.stop_all()


def test_supervisor_apply_reconciles():
    sup = CameraSupervisor(_factory, FAST)
    try:
        sup.apply([_spec("a", "fps=10"), _spec("b", "fps=10")])
        res = sup.apply([_spec("b", "fps=20"), _spec("c", "fps=10")])
        assert res == {"added": ["c"], "changed": ["b"], "removed": ["a"]}
        assert set(sup.workers()) == {"b", "c"}
    finally:
        sup.stop_all()
