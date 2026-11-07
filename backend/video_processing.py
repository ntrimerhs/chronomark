import re
import math
import wave
import ffmpeg
from pathlib import Path


def _probe_duration_seconds(video_path: Path):
    try:
        probe = ffmpeg.probe(str(video_path))
        duration = probe.get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except Exception:
        return None


def _write_silence_wav(path: Path, duration_seconds: float, sample_rate: int = 16000):
    frame_count = max(0, int(duration_seconds * sample_rate))
    silence = b"\x00\x00" * frame_count

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(silence)


def _concat_wav_files(parts: list[Path], output_audio: Path):
    if not parts:
        raise RuntimeError("No WAV parts to concatenate")

    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()

    with wave.open(str(output_audio), "wb") as out:
        out.setparams(params)
        for part in parts:
            with wave.open(str(part), "rb") as src:
                out.writeframes(src.readframes(src.getnframes()))


def _extract_audio_chunked_with_silence(video_path: Path, output_audio: Path, chunk_seconds: int = 60):
    duration = _probe_duration_seconds(video_path)
    if not duration or duration <= 0:
        raise RuntimeError("Could not determine video duration for chunked fallback")

    print(f"Video duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
    
    total_chunks = int(math.ceil(duration / float(chunk_seconds)))
    temp_parts = []

    try:
        for index in range(total_chunks):
            start = index * chunk_seconds
            length = min(float(chunk_seconds), duration - start)
            part_path = output_audio.parent / f"{output_audio.stem}.part{index:04d}.wav"

            try:
                (
                    ffmpeg
                    .input(
                        str(video_path),
                        ss=start,
                        t=length,
                        err_detect="ignore_err",
                        fflags="+discardcorrupt",
                    )
                    .output(
                        str(part_path),
                        acodec="pcm_s16le",
                        ac=1,
                        ar=16000,
                    )
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )

                # Validate chunk: must have at least 50% of expected frames
                # Expected: length * 16000 frames/second
                expected_frames = int(length * 16000)
                min_frames_threshold = max(expected_frames // 2, 1000)  # At least 0.5 seconds worth

                if not part_path.exists() or part_path.stat().st_size == 0:
                    raise RuntimeError("chunk output was empty")

                with wave.open(str(part_path), "rb") as wav_file:
                    actual_frames = wav_file.getnframes()

                print(f"  Chunk {index}: {actual_frames:7d}/{expected_frames:7d} frames ({100*actual_frames/expected_frames:5.1f}%)")

                if actual_frames < min_frames_threshold:
                    print(f"    ^ WARNING: undersized chunk, replacing with silence")
                    raise RuntimeError(f"chunk had insufficient frames: {actual_frames} < {min_frames_threshold}")

            except Exception as e:
                print(f"  Chunk {index}: Extraction failed ({type(e).__name__}: {e}), using silence")
                _write_silence_wav(part_path, duration_seconds=length)

            temp_parts.append(part_path)

        _concat_wav_files(temp_parts, output_audio)
        print("Audio extracted with chunked corruption-tolerant fallback.")
    finally:
        for part_path in temp_parts:
            part_path.unlink(missing_ok=True)

def normalize_video(video_path, normalized_dir, force=False):
    """
    Return a video in the project's canonical format.

    Canonical format:
        Container : MP4
        Video     : H.264
        Audio     : AAC

    If the input already matches this format, the original path is returned.
    Otherwise the video is transcoded once and the path to the normalized
    file is returned.
    """

    video_path = Path(video_path)
    normalized_dir = Path(normalized_dir)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    try:
        probe = ffmpeg.probe(str(video_path))
    except ffmpeg.Error as e:
        raise RuntimeError(f"Could not probe video: {e}")

    container = probe["format"]["format_name"]

    video_codec = None
    audio_codec = None

    for stream in probe["streams"]:
        if stream["codec_type"] == "video":
            video_codec = stream["codec_name"]
        elif stream["codec_type"] == "audio":
            audio_codec = stream["codec_name"]

    already_ok = (not force) and (
        "mp4" in container
        and video_codec == "h264"
        and audio_codec == "aac"
    )

    output_path = normalized_dir / f"{video_path.stem}_normalized.mp4"

    if already_ok:
        # Codecs are already browser-friendly, but the moov atom (the index
        # the browser needs to map a seek time to a byte offset) can still
        # sit at the end of the file -- common for phone/screen recordings.
        # That makes the HTML5 seek bar land on the wrong timestamp when
        # dragged. Remux with a stream copy (no re-encode, fast) to move it
        # to the front.
        try:
            (
                ffmpeg
                .input(str(video_path))
                .output(str(output_path), c="copy", movflags="+faststart")
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            print("Video already in canonical format; remuxed for faststart seeking.")
            return output_path
        except ffmpeg.Error as e:
            print(f"Faststart remux failed, serving original file as-is: {e}")
            return video_path

    attempts = [
        {},
        {"err_detect": "ignore_err"},
        {"err_detect": "ignore_err", "fflags": "+discardcorrupt"},
    ]

    last_error = None

    print("Normalizing video...")

    for kwargs in attempts:
        try:
            (
                ffmpeg
                .input(str(video_path), **kwargs)
                .output(
                    str(output_path),
                    vcodec="libx264",
                    acodec="aac",
                    movflags="+faststart"
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

            print(f"Normalized video saved to {output_path}")
            return output_path
        except ffmpeg.Error as e:
            last_error = e

    stderr = last_error.stderr.decode(errors="replace") if last_error and last_error.stderr else str(last_error)
    raise RuntimeError(f"Could not normalize video: {stderr}")


def extract_audio(video_path, output_audio):
    attempts = [
        {},
        {"err_detect": "ignore_err"},
        {
            "err_detect": "ignore_err",
            "fflags": "+discardcorrupt",
        },
    ]

    last_error = None

    for kwargs in attempts:
        try:
            (
                ffmpeg
                .input(str(video_path), **kwargs)
                .output(
                    str(output_audio),
                    acodec="pcm_s16le",
                    ac=1,
                    ar=16000,
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

            print("Audio extracted successfully.")
            return

        except ffmpeg.Error as e:
            last_error = e

    try:
        _extract_audio_chunked_with_silence(Path(video_path), Path(output_audio))
        return
    except Exception as chunk_error:
        stderr = last_error.stderr.decode(errors="replace") if last_error and last_error.stderr else str(last_error)
        raise RuntimeError(f"{stderr}\nChunked fallback failed: {chunk_error}")


_PTS_TIME_RE = re.compile(r"pts_time:([0-9.]+)")


def extract_frame_at(video_path, timestamp, output_path, max_width=0):
    """Grab a single frame at a timestamp.

    Seeks to the timestamp rather than decoding from the start, so the cost is
    milliseconds no matter where in the video the moment sits. Used for frames
    chosen by meaning -- a definition, a worked example -- rather than by pixel
    change, so they must not require a full decode pass each.
    """
    try:
        timestamp = max(0.0, float(timestamp))
    except (TypeError, ValueError):
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_kwargs = {"vframes": 1, "q:v": 3}
    vf = []
    if max_width and int(max_width) > 0:
        vf.append(f"scale='min({int(max_width)},iw)':-2")
    if vf:
        output_kwargs["vf"] = ",".join(vf)

    try:
        (
            ffmpeg.input(str(video_path), ss=timestamp)
            .output(str(output_path), **output_kwargs)
            .overwrite_output()
            .global_args("-loglevel", "error")
            .run(capture_stdout=True, capture_stderr=True)
        )
    except Exception:
        return False

    return output_path.exists() and output_path.stat().st_size > 0


def _frame_hash(frame_path):
    """64-bit difference hash of a frame, or None when it cannot be read.

    dHash compares adjacent pixels in a 9x8 grayscale thumbnail: robust to
    brightness and compression noise, sensitive to layout changes -- which is
    what "is this still the same slide?" actually means.
    """
    try:
        from PIL import Image

        with Image.open(frame_path) as image:
            thumb = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
            pixels = list(thumb.getdata())
    except Exception:
        return None

    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _dedupe_frames(frame_files, timestamps, min_gap_sec=2.5, max_hash_distance=6):
    """Drop frames that merely restate the previous one.

    FFmpeg scores each frame against the frame immediately before it, not
    against the last frame kept. A slow continuous change -- a highlight
    fading, a cursor travelling, compression noise -- therefore crosses the
    scene threshold on many consecutive frames and produces near-identical
    stills a second apart.

    Two rules, because duplicates arise two ways: a minimum time gap kills
    bursts seconds apart, and a perceptual-hash distance from the last *kept*
    frame kills the same visual state recurring later, whatever the gap.
    Rejected files are deleted so the directory matches what is returned.
    """
    kept = []
    kept_moments = []
    kept_hashes = []

    for frame_file in frame_files:
        moment = timestamps.get(frame_file.name)

        if kept_moments and moment is not None and (moment - kept_moments[-1]) < min_gap_sec:
            frame_file.unlink(missing_ok=True)
            continue

        digest = _frame_hash(frame_file)
        if digest is not None and kept_hashes and kept_hashes[-1] is not None:
            if bin(digest ^ kept_hashes[-1]).count("1") < max_hash_distance:
                frame_file.unlink(missing_ok=True)
                continue

        kept.append(frame_file)
        kept_moments.append(moment if moment is not None else -1.0)
        kept_hashes.append(digest)

    return kept, {f.name: timestamps.get(f.name) for f in kept}


def extract_frames(
    video_path,
    output_dir,
    interval_seconds=5.0,
    extraction_mode="scene",
    scene_threshold=0.12,
    keyframes_only=False,
    max_width=0,
    quality=5,
    min_gap_sec=2.5,
    max_hash_distance=6,
):
    """Extract sampled JPEG frames from video_path into output_dir.

    Processing model:
    1) Clean existing frame files in output_dir
    2) Build ffmpeg input (optionally keyframe-only decoding)
    3) Apply frame-selection filter:
       - scene mode: keep frames where FFmpeg scene score exceeds threshold
       - interval mode: fps sampling based on interval_seconds
    4) Log each selected frame's true PTS timestamp via showinfo (stderr)
    5) Optionally resize frames to max_width
    6) Save sequential images: frame000001.jpg, frame000002.jpg, ...

    extraction_mode: "scene" or "interval".
    scene_threshold: FFmpeg scene-change threshold (0.0..1.0), used in scene mode.
        0.12 rather than 0.35 on purpose: slide-based lectures change gradually
        (a bullet appears, a line gets highlighted), and those edits never cross
        a threshold tuned for hard cuts. At 0.35 a six-minute Python lecture
        yielded four frames.
    interval_seconds: seconds between sampled frames.
    keyframes_only: if True, decode keyframes only. Defaults to off: with it on,
        FFmpeg only *sees* keyframes, so the scene detector is judging a small
        sample and misses changes between them. Costs decode time, gains frames.
    max_width: if > 0, constrain output width while preserving aspect ratio.
    quality: JPEG q:v quality (2 best quality/larger files .. 31 lowest quality).

    Returns:
        (frame_count, timestamps) where timestamps is a dict mapping
        "frame000001.jpg" -> seconds (float), in extraction order.
    """
    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Remove old frames so repeated processing of the same video stem does
        # not mix previous and current outputs.
        for old_frame in output_dir.glob("frame*.jpg"):
            old_frame.unlink(missing_ok=True)

        input_kwargs = {}
        if keyframes_only:
            input_kwargs["skip_frame"] = "nokey"

        stream = ffmpeg.input(str(video_path), **input_kwargs)

        safe_mode = str(extraction_mode or "scene").strip().lower()
        if safe_mode not in {"scene", "interval"}:
            raise ValueError("extraction_mode must be either 'scene' or 'interval'")

        vf_parts = []
        if safe_mode == "scene":
            safe_scene_threshold = min(max(float(scene_threshold), 0.0), 1.0)
            vf_parts.append(f"select='gt(scene\\,{safe_scene_threshold:.3f})'")
        else:
            safe_interval = max(float(interval_seconds), 0.1)
            vf_parts.append(f"fps=1/{safe_interval}")

        # showinfo logs pts_time for every frame that survives selection,
        # in output order — this is how we recover true timestamps below.
        vf_parts.append("showinfo")

        if max_width and int(max_width) > 0:
            vf_parts.append(f"scale='min({int(max_width)},iw)':-2")

        output_pattern = output_dir / "frame%06d.jpg"

        process = (
            stream.output(
                str(output_pattern),
                vf=",".join(vf_parts),
                format="image2",
                vsync="vfr",
                **{"q:v": max(2, min(int(quality), 31))},
                start_number=1,
            )
            .overwrite_output()
            # loglevel must be "info" (not "error") or showinfo's pts_time
            # lines get suppressed and we lose the timestamp data entirely.
            .global_args("-threads", "0", "-loglevel", "info")
        )

        result = process.run(capture_stdout=True, capture_stderr=True)
        stderr_text = result[1].decode(errors="replace") if result[1] else ""

        pts_times = [float(m) for m in _PTS_TIME_RE.findall(stderr_text)]

        frame_files = sorted(output_dir.glob("frame*.jpg"))
        frame_count = len(frame_files)

        if len(pts_times) != frame_count:
            # Mismatch shouldn't normally happen, but don't silently produce
            # wrong pairings — fall back to None rather than misalign frames.
            print(
                f"Warning: showinfo timestamp count ({len(pts_times)}) != "
                f"frame count ({frame_count}); timestamps may be incomplete."
            )

        timestamps = {}
        for i, frame_file in enumerate(frame_files):
            timestamps[frame_file.name] = pts_times[i] if i < len(pts_times) else None

        frame_files, timestamps = _dedupe_frames(
            frame_files,
            timestamps,
            min_gap_sec=min_gap_sec,
            max_hash_distance=max_hash_distance,
        )
        frame_count = len(frame_files)

        print(f"Frames extracted successfully to {output_dir} (count={frame_count})")
        return frame_count, timestamps
    except ValueError as e:
        raise RuntimeError(f"Frame extraction failed: {e}") from e
    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else str(e)
        raise RuntimeError(f"Frame extraction failed: {stderr}") from e