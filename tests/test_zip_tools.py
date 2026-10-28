import zipfile

import pytest

from arturokai.zip_tools import ZipError, build_context, code_blocks_to_zip, safe_extract
from arturokai.video_gen import segments_needed


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def test_extract_and_context(tmp_path):
    z = make_zip(tmp_path / "a.zip", {"src/main.py": "print(1)\n", "node_modules/x.js": "skip"})
    root = safe_extract(z, tmp_path / "out")
    ctx = build_context(root)
    assert "src/main.py" in ctx and "print(1)" in ctx
    assert "skip" not in ctx


def test_zip_slip_blocked(tmp_path):
    z = make_zip(tmp_path / "evil.zip", {"../../evil.txt": "x"})
    with pytest.raises(ZipError):
        safe_extract(z, tmp_path / "out")


def test_code_blocks_to_zip():
    text = "```python app/main.py\nprint('hi')\n```\ntext\n```js\nconsole.log(1)\n```"
    import io
    with zipfile.ZipFile(io.BytesIO(code_blocks_to_zip(text))) as zf:
        assert sorted(zf.namelist()) == ["app/main.py", "snippet_2.js"]


def test_two_minutes_segments():
    # 120 c * 24 fps = 2880 кадров; 121 + 23*120 = 2881 ≥ 2880
    assert segments_needed(120, 24, 121) == 24
    assert segments_needed(3, 24, 121) == 1


def test_video_chaining_frame_count(tmp_path):
    import imageio.v3 as iio
    import numpy as np
    from types import SimpleNamespace
    from arturokai.video_gen import VideoGenerator

    calls = []

    def fake_pipe(**kw):
        calls.append("i2v" if "image" in kw else "t2v")
        return SimpleNamespace(frames=[np.random.rand(kw["num_frames"], kw["height"], kw["width"], 3)])

    cfg = dict(t2v_model="a", i2v_model="a", width=64, height=48, fps=8,
               frames_per_segment=9, steps=1, guidance=1.0, max_seconds=120)
    vg = VideoGenerator(cfg, tmp_path)
    vg.t2v = vg.i2v = fake_pipe
    out = vg.generate("test", seconds=3, seed=1)
    assert calls == ["t2v", "i2v", "i2v"]          # 9 + 8 + 8 ≥ 24 кадров
    assert len(list(iio.imiter(out))) == 24
