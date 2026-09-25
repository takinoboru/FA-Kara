from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from ruby_to_standard import convert_text


ROOT = Path(__file__).resolve().parent
TASK_ROOT = ROOT / ".kara_gui_runs"
TASK_META = ".gui_task.json"
TERMINAL_PYTHON = Path("/opt/anaconda3/envs/fa-kara/bin/python")
ALIGN_PYTHON = str(TERMINAL_PYTHON if TERMINAL_PYTHON.exists() else Path(sys.executable))
ASS_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})(?:\.(\d{2}))?")
ASS_TAG_RE = re.compile(r"\{[^}]*\}")
ASS_K_TAG_RE = re.compile(r"\{\\(?:k|K|kf|ko)(\d+)\}")
LRC_TIME_RE = re.compile(r"\[(\d{2}):(\d{2})(?:[.:](\d{2}))?\]")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
VIDEO_MIMES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}
AUDIO_MIMES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}

RUBY_LINE_TIME_RE = re.compile(r"\[(\d{2,}):(\d{2}):(\d{2})\]")


st.set_page_config(page_title="FA-Kara Studio", page_icon="♫", layout="wide")
RUBY_TIMELINE = components.declare_component(
    "ruby_timeline",
    path=str(ROOT / "ruby_timeline_component"),
)


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink:#172033; --muted:#5b6678; --paper:#f5f7fb; --card:#ffffff;
          --sidebar:#10233d; --sidebar-2:#173454; --accent:#0b77c5; --teal:#0f9f8f;
          --line:#cad5e3;
        }
        .stApp {
          background: radial-gradient(circle at 88% 0%, #dceefe 0, transparent 32%), var(--paper);
          color:var(--ink);
        }
        [data-testid="stSidebar"] {
          background:linear-gradient(180deg,var(--sidebar),var(--sidebar-2));
          border-right:1px solid #29496b;
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
          color:#f8fbff !important;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
          font-weight:700 !important;
          letter-spacing:.01em;
        }
        [data-testid="stSidebar"] input {
          background:#ffffff !important;
          color:#111827 !important;
          border:1px solid #8fb2d2 !important;
          caret-color:#0b77c5 !important;
        }
        [data-testid="stSidebar"] input::placeholder { color:#64748b !important; opacity:1; }
        [data-testid="stSidebar"] [data-baseweb="select"] > div {
          background:#ffffff !important;
          color:#111827 !important;
          border-color:#8fb2d2 !important;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] span,
        [data-testid="stSidebar"] [data-baseweb="select"] svg { color:#111827 !important; fill:#111827 !important; }
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
          background:#f8fbff !important;
          border:1px dashed #67a7d7 !important;
        }
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *,
        [data-testid="stSidebar"] [data-testid="stFileUploaderFile"] * { color:#26364a !important; }
        [data-testid="stSidebar"] [data-testid="stFileUploader"] small { color:#d7e7f5 !important; }
        [data-testid="stSidebar"] hr { border-color:#42617e !important; }
        [data-testid="stSidebar"] button[kind="primary"] {
          background:#17a99a !important; color:#ffffff !important; border:0 !important; font-weight:800 !important;
        }
        [data-testid="stSidebar"] button[kind="primary"] p { color:#ffffff !important; }
        h1, h2, h3 { letter-spacing:-.02em; }
        h1 { font-size:3rem; line-height:1.05; margin-bottom:.25rem; }
        .eyebrow { color:var(--accent); font-size:.78rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
        .subtitle { color:var(--muted); max-width:760px; margin-bottom:1.5rem; font-size:1.02rem; }
        .status-card {
          border:1px solid #b9ccdf; border-left:5px solid var(--teal); background:#ffffff;
          border-radius:8px; padding:.9rem 1rem; margin:.5rem 0 1rem; color:var(--ink);
        }
        .lyric-box {
          background:#10233d; color:#f5fbff; border:1px solid #29496b; border-radius:10px;
          padding:1.2rem; min-height:130px; font-size:1.08rem; line-height:2; white-space:pre-wrap;
        }
        div[data-testid="stFileUploader"] { border-radius:8px; }
        div[data-testid="stCode"] { border:1px solid var(--line); border-radius:8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def safe_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return cleaned or fallback


def ass_time_to_seconds(value: str) -> float | None:
    match = ASS_TIME_RE.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes, seconds, centiseconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centiseconds or 0) / 100


def lrc_time_to_seconds(match: re.Match[str]) -> float:
    return int(match.group(1)) * 60 + int(match.group(2)) + int(match.group(3) or 0) / 100


def format_vtt_time(seconds: float) -> str:
    milliseconds = max(round(seconds * 1000), 0)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def lrc_to_cues(lrc_text: str) -> list[tuple[float, float, str]]:
    offset_seconds = 0.0
    offset_match = re.search(r"(?mi)^@Offset\s*=\s*(-?\d+)", lrc_text)
    if offset_match:
        offset_seconds = int(offset_match.group(1)) / 1000

    cues: list[tuple[float, float, str]] = []
    for raw_line in lrc_text.splitlines():
        if not raw_line or raw_line.startswith("@"):
            continue
        timestamps = list(LRC_TIME_RE.finditer(raw_line))
        if not timestamps:
            continue
        lyric_start: float | None = None
        text_parts: list[str] = []
        for index, stamp in enumerate(timestamps):
            segment_end = timestamps[index + 1].start() if index + 1 < len(timestamps) else len(raw_line)
            segment = raw_line[stamp.end():segment_end].replace("●", "")
            segment = re.sub(r"\[[^]]*\]", "", segment)
            if segment:
                if lyric_start is None:
                    lyric_start = lrc_time_to_seconds(stamp)
                text_parts.append(segment)
        text = "".join(text_parts).strip()
        if lyric_start is None or not text:
            continue
        end = lrc_time_to_seconds(timestamps[-1])
        if end <= lyric_start:
            end = lyric_start + 2.0
        cues.append((max(lyric_start + offset_seconds, 0), max(end + offset_seconds, 0), text))
    return cues


def lrc_to_lines(lrc_text: str) -> list[list[object]]:
    return [[start, text] for start, _end, text in lrc_to_cues(lrc_text)]


def parse_ass_dialogues(ass_text: str) -> list[dict[str, object]]:
    dialogues: list[dict[str, object]] = []
    for source_index, line in enumerate(ass_text.splitlines()):
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(":", 1)[1].lstrip().split(",", 9)
        if len(fields) != 10:
            continue
        if fields[8].strip().lower() != "karaoke":
            continue
        start = ass_time_to_seconds(fields[1])
        end = ass_time_to_seconds(fields[2])
        if start is None or end is None or end <= start:
            continue
        dialogues.append({
            "source_index": source_index,
            "fields": fields,
            "start": start,
            "end": end,
            "karaoke_no": len(dialogues) + 1,
        })
    return dialogues


def ass_karaoke_tokens(text: str) -> tuple[str, list[dict[str, object]]]:
    matches = list(ASS_K_TAG_RE.finditer(text))
    if not matches:
        return text, []
    prefix = text[:matches[0].start()]
    tokens: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        token_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        tokens.append({"duration_cs": int(match.group(1)), "raw": text[match.end():token_end]})
    return prefix, tokens


def karaoke_surface_segments(tokens: list[dict[str, object]]) -> list[tuple[str, float]]:
    segments: list[tuple[str, float]] = []
    ruby_surface: str | None = None
    ruby_duration = 0.0

    def append_chars(surface: str, duration_cs: float) -> None:
        characters = list(surface)
        if not characters:
            segments.append(("", duration_cs))
            return
        duration_each = duration_cs / len(characters)
        segments.extend((character, duration_each) for character in characters)

    def flush_ruby() -> None:
        nonlocal ruby_surface, ruby_duration
        if ruby_surface is not None:
            append_chars(ruby_surface, ruby_duration)
        ruby_surface = None
        ruby_duration = 0.0

    for token in tokens:
        duration = float(token["duration_cs"])
        raw = ASS_TAG_RE.sub("", str(token["raw"]))
        raw = html.unescape(raw).replace("\\N", "\n").replace("\\n", "\n")
        if "|<" in raw:
            flush_ruby()
            ruby_surface, _reading = raw.split("|<", 1)
            ruby_duration = duration
        elif raw.startswith("#|") and ruby_surface is not None:
            ruby_duration += duration
        else:
            flush_ruby()
            append_chars(raw.replace("#|", ""), duration)
    flush_ruby()
    return segments


def karaoke_lines(ass_text: str) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    for dialogue in parse_ass_dialogues(ass_text):
        fields = dialogue["fields"]
        assert isinstance(fields, list)
        _prefix, tokens = ass_karaoke_tokens(str(fields[9]))
        cursor = float(dialogue["start"])
        characters: list[dict[str, object]] = []
        for character, duration_cs in karaoke_surface_segments(tokens):
            character_end = cursor + duration_cs / 100
            if character:
                characters.append({"text": character, "start": cursor, "end": character_end})
            cursor = character_end
        fallback = ASS_TAG_RE.sub("", str(fields[9])).replace("|<", "").replace("#|", "")
        lines.append({**dialogue, "characters": characters, "text": "".join(str(item["text"]) for item in characters) or fallback})
    return lines


def ass_dialogue_cues(ass_text: str) -> list[tuple[float, float, str]]:
    return [(float(line["start"]), float(line["end"]), str(line["text"]).strip()) for line in karaoke_lines(ass_text)]


def ass_to_vtt(ass_text: str, lrc_text: str | None = None) -> str:
    lines = karaoke_lines(ass_text)
    lrc_cues = lrc_to_cues(lrc_text) if lrc_text else []
    use_lrc_text = len(lrc_cues) == len(lines) and bool(lrc_cues)
    output = [
        "WEBVTT",
        "",
        "STYLE",
        "::cue { color: white; background-color: rgba(8, 20, 38, .78); font-size: 6vh; }",
        "::cue(.past) { color: #78ead8; }",
        "::cue(.active) { color: #ffd45a; font-weight: bold; }",
        "::cue(.future) { color: white; }",
        "",
    ]
    for line_index, line in enumerate(lines):
        characters = line["characters"]
        assert isinstance(characters, list)
        if characters:
            for active_index, character in enumerate(characters):
                start = float(character["start"])
                end = min(float(character["end"]), float(line["end"]))
                if end <= start:
                    continue
                past = html.escape("".join(str(item["text"]) for item in characters[:active_index]))
                active = html.escape(str(character["text"]))
                future = html.escape("".join(str(item["text"]) for item in characters[active_index + 1:]))
                cue_text = f"<c.past>{past}</c><c.active>{active}</c><c.future>{future}</c>"
                output.extend([f"{format_vtt_time(start)} --> {format_vtt_time(end)}", cue_text, ""])
            continue
        text = lrc_cues[line_index][2] if use_lrc_text else str(line["text"])
        if text:
            output.extend([
                f"{format_vtt_time(float(line['start']))} --> {format_vtt_time(float(line['end']))}",
                html.escape(text),
                "",
            ])
    return "\n".join(output)


def karaoke_audio_player(media_path: Path, lrc_text: str) -> None:
    media_type = AUDIO_MIMES.get(media_path.suffix.lower(), "audio/mpeg")
    media_uri = "data:" + media_type + ";base64," + base64.b64encode(media_path.read_bytes()).decode("ascii")
    lyric_payload = json.dumps(lrc_to_lines(lrc_text), ensure_ascii=False).replace("</", "<\\/")
    markup = f"""
    <div style="font-family:system-ui;background:#10233d;color:#f5fbff;padding:16px;border:1px solid #29496b;border-radius:10px">
      <audio id="media" controls preload="metadata" style="width:100%"><source src="{media_uri}" type="{media_type}"></audio>
      <div id="line" style="font-size:22px;line-height:1.5;min-height:2em;padding:18px 2px 4px;color:#d9f5ef"></div>
    </div>
    <script>
    const media = document.getElementById('media');
    const line = document.getElementById('line');
    const lines = {lyric_payload};
    function updateLine() {{
      let current = '';
      for (const item of lines) {{
        if (item[0] <= media.currentTime) current = item[1];
        else break;
      }}
      line.textContent = current;
    }}
    media.addEventListener('timeupdate', updateLine);
    media.addEventListener('seeked', updateLine);
    </script>
    """
    components.html(markup, height=150, scrolling=False)


def uploaded_file_signature(uploaded: object) -> str | None:
    if uploaded is None or not hasattr(uploaded, "getvalue"):
        return None
    return hashlib.sha256(uploaded.getvalue()).hexdigest()


def uploaded_text(uploaded: object) -> str:
    return uploaded.getvalue().decode("utf-8-sig", errors="replace")


def active_standardized_lyrics(uploaded: object) -> dict[str, object] | None:
    state = st.session_state.get("standardized_lyrics")
    if not isinstance(state, dict):
        return None
    if state.get("source_signature") != uploaded_file_signature(uploaded):
        return None
    return state


def render_upload_preview(lyrics_file: object, audio_file: object, video_file: object) -> None:
    if not any((lyrics_file, audio_file, video_file)):
        st.info("上传歌词、音频或视频后，这里会出现输入预览与歌词标准化工具。")
        return
    st.subheader("输入预览")
    lyric_tab, audio_tab, video_tab = st.tabs(["注音歌词", "人声音频", "检查视频"])
    with lyric_tab:
        if lyrics_file is None:
            st.caption("尚未上传注音歌词。")
        else:
            source_text = uploaded_text(lyrics_file)
            standardized = active_standardized_lyrics(lyrics_file)
            current_text = str(standardized["content"]) if standardized else source_text
            current_name = str(standardized["output_name"]) if standardized else str(lyrics_file.name)
            if standardized:
                st.success(
                    f"当前歌词输入已替换为 {current_name}；"
                    f"共转换 {standardized['replacements']} 处非标准注音。"
                )
            st.text_area("当前会用于对齐的歌词", value=current_text, height=260, disabled=True)
            convert_col, download_col = st.columns(2)
            with convert_col:
                if st.button("一键转换为标准注音并替换输入", type="primary", use_container_width=True):
                    converted, replacements = convert_text(source_text)
                    source_path = Path(str(lyrics_file.name))
                    output_stem = source_path.stem if source_path.stem.endswith("_std") else f"{source_path.stem}_std"
                    output_name = f"{output_stem}{source_path.suffix or '.txt'}"
                    prepared_dir = TASK_ROOT / "_standardized_uploads"
                    prepared_dir.mkdir(parents=True, exist_ok=True)
                    saved_path = prepared_dir / safe_name(output_name, "lyrics_std.txt")
                    saved_path.write_text(converted, encoding="utf-8")
                    st.session_state["standardized_lyrics"] = {
                        "source_signature": uploaded_file_signature(lyrics_file),
                        "source_name": str(lyrics_file.name),
                        "output_name": saved_path.name,
                        "content": converted,
                        "replacements": replacements,
                        "saved_path": str(saved_path),
                    }
                    st.rerun()
            with download_col:
                if standardized:
                    st.download_button(
                        "下载标准化歌词",
                        str(standardized["content"]),
                        file_name=str(standardized["output_name"]),
                        use_container_width=True,
                    )
            st.caption("转换规则来自本地 ruby_to_standard.py：漢字(かな) → {漢字|かな}。")
    with audio_tab:
        if audio_file is None:
            st.caption("尚未上传人声音频。")
        else:
            st.audio(audio_file.getvalue(), format=AUDIO_MIMES.get(Path(audio_file.name).suffix.lower(), "audio/mpeg"))
            st.caption(f"{audio_file.name} · {len(audio_file.getvalue()) / 1024 / 1024:.1f} MB")
    with video_tab:
        if video_file is None:
            st.caption("尚未上传检查视频。")
        else:
            st.video(video_file.getvalue(), format=VIDEO_MIMES.get(Path(video_file.name).suffix.lower(), "video/mp4"))
            st.caption(f"{video_file.name} · {len(video_file.getvalue()) / 1024 / 1024:.1f} MB")


def save_upload(uploaded, target: Path, fallback: str) -> Path | None:
    if uploaded is None:
        return None
    path = target / safe_name(uploaded.name, fallback)
    path.write_bytes(uploaded.getvalue())
    return path


def build_alignment_command(task_dir: Path, args: dict[str, object]) -> list[str]:
    command = [ALIGN_PYTHON, str(ROOT / "main.py"), "-p", str(task_dir)]
    for flag, value in args.items():
        if value in (None, "") or value is False:
            continue
        if value is True:
            command.append(flag)
        else:
            command.extend([flag, str(value)])
    return command


def start_alignment(task_dir: Path, args: dict[str, object], media: dict[str, object], job_label: str = "强制对齐") -> dict[str, object]:
    command = build_alignment_command(task_dir, args)
    log_path = task_dir / "alignment.log"
    with log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            start_new_session=True,
        )
    metadata_path = task_dir / TASK_META
    metadata: dict[str, object] = {}
    if metadata_path.exists():
        try:
            saved = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                metadata.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    metadata.update(media)
    metadata["last_command"] = command
    metadata["last_args"] = args
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "process": process,
        "task_dir": str(task_dir),
        "log_path": str(log_path),
        "started_at": time.time(),
        "command": command,
        "media": metadata,
        "label": job_label,
    }


def read_log_tail(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def stop_alignment(job: dict[str, object]) -> None:
    process = job.get("process")
    if not isinstance(process, subprocess.Popen) or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def read_output(task_dir: Path, name: str) -> str | None:
    path = task_dir / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def task_media(task_dir: Path) -> dict[str, object]:
    metadata_path = task_dir / TASK_META
    if metadata_path.exists():
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, json.JSONDecodeError):
            pass
    state_media = st.session_state.get("task_media")
    if isinstance(state_media, dict) and st.session_state.get("task_dir") == str(task_dir):
        return state_media
    video = next((path.name for path in task_dir.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES), None)
    audio = next((path.name for path in task_dir.iterdir() if path.suffix.lower() in AUDIO_SUFFIXES), None)
    lyrics = next((path.name for path in task_dir.glob("*.txt") if path.name != "pronunciations.txt"), None)
    return {"audio": audio, "video": video, "lyrics": lyrics}


def task_outputs(task_dir: Path) -> tuple[Path | None, Path | None, Path | None]:
    ass_candidates = [
        path for path in task_dir.glob("*.ass")
        if ".before_" not in path.name and not path.name.endswith("_prepared.ass")
    ]
    ass_path = max(ass_candidates, key=lambda path: path.stat().st_mtime, default=None)
    ruby_candidates = list(task_dir.glob("*_ruby.lrc"))
    rlf_candidates = list(task_dir.glob("*_rlf.lrc"))
    ruby_path = max(ruby_candidates, key=lambda path: path.stat().st_mtime, default=None)
    rlf_path = max(rlf_candidates, key=lambda path: path.stat().st_mtime, default=None)
    return ass_path, ruby_path, rlf_path


def latest_completed_task() -> Path | None:
    if not TASK_ROOT.exists():
        return None
    candidates = sorted(
        (path for path in TASK_ROOT.glob("task_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return next((path for path in candidates if task_outputs(path)[0] is not None), None)


def video_codec(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def media_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def make_synced_preview(video: Path, audio: Path, destination: Path) -> tuple[bool, str]:
    video_duration = media_duration(video)
    audio_duration = media_duration(audio)
    if not video_duration or not audio_duration:
        return False, "ffprobe 无法读取上传媒体的完整时长。"
    target_duration = max(video_duration, audio_duration)
    codec = video_codec(video)
    command = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio)]
    if video_duration + 0.05 < target_duration:
        command.extend([
            "-filter_complex",
            f"[0:v:0]tpad=stop_mode=clone:stop_duration={target_duration - video_duration:.3f}[v];"
            f"[1:a:0]apad=whole_dur={target_duration:.3f},atrim=duration={target_duration:.3f}[a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        ])
    else:
        command.extend([
            "-filter_complex",
            f"[1:a:0]apad=whole_dur={target_duration:.3f},atrim=duration={target_duration:.3f}[a]",
            "-map", "0:v:0", "-map", "[a]",
        ])
        if codec == "h264":
            command.extend(["-c:v", "copy"])
        else:
            command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "21"])
    command.extend([
        "-c:a", "aac", "-b:a", "192k", "-t", f"{target_duration:.3f}",
        "-movflags", "+faststart", str(destination),
    ])
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + "\n" + result.stderr)[-6000:]


@st.fragment(run_every=1.0)
def render_alignment_job() -> None:
    job = st.session_state.get("alignment_job")
    if not isinstance(job, dict):
        return
    process = job.get("process")
    if not isinstance(process, subprocess.Popen):
        st.error("任务状态已丢失，请重新开始生成。")
        st.session_state.pop("alignment_job", None)
        return

    elapsed = max(int(time.time() - float(job.get("started_at", time.time()))), 0)
    minutes, seconds = divmod(elapsed, 60)
    log = read_log_tail(Path(str(job["log_path"])))
    code = process.poll()
    label = str(job.get("label", "强制对齐"))
    if code is None:
        with st.status(f"{label}正在运行 · {minutes:02d}:{seconds:02d}", expanded=True):
            st.caption("任务在独立进程中运行；页面会每秒刷新日志，界面不会再被 subprocess.run 阻塞。")
            st.code(log or "子进程已启动，正在准备模型…", language="text")
            st.caption("命令：" + shlex.join([str(item) for item in job.get("command", [])]))
        if st.button("停止当前任务", type="secondary", key="cancel_alignment"):
            stop_alignment(job)
            st.session_state["last_alignment_log"] = read_log_tail(Path(str(job["log_path"])))
            st.session_state.pop("alignment_job", None)
            st.warning("任务已停止，已保留输入文件和日志。")
            st.rerun(scope="app")
        return

    st.session_state["last_alignment_log"] = log
    if code == 0:
        task_dir = Path(str(job["task_dir"]))
        st.session_state["task_dir"] = str(task_dir)
        st.session_state["task_media"] = job.get("media", {})
        st.session_state["message"] = f"{label}完成：{task_dir.name}"
        st.session_state.pop("alignment_job", None)
        st.rerun(scope="app")
    else:
        st.session_state.pop("alignment_job", None)
        st.error(f"生成失败（退出码 {code}）。")
        st.code(log or "没有终端输出", language="text")


def ruby_match_to_seconds(match: re.Match[str]) -> float:
    return int(match.group(1)) * 60 + int(match.group(2)) + int(match.group(3)) / 100


def format_ruby_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    minutes, centiseconds = divmod(centiseconds, 6000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"[{minutes:02d}:{secs:02d}:{centiseconds:02d}]"


def parse_ruby_timeline_lines(ruby_text: str) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    for source_index, raw_line in enumerate(ruby_text.splitlines()):
        if not raw_line or raw_line.startswith("@"):
            continue
        matches = list(RUBY_LINE_TIME_RE.finditer(raw_line))
        if len(matches) < 2:
            continue
        points: list[dict[str, object]] = []
        for point_index, match in enumerate(matches):
            text_end = matches[point_index + 1].start() if point_index + 1 < len(matches) else len(raw_line)
            points.append({
                "index": point_index,
                "time": ruby_match_to_seconds(match),
                "stamp": match.group(0),
                "text": raw_line[match.end():text_end],
            })
        visible_text = "".join(str(point["text"]) for point in points if str(point["text"]) != "●")
        parsed.append({
            "line_index": len(parsed),
            "source_index": source_index,
            "points": points,
            "text": visible_text,
        })
    return parsed


def ruby_info_for_points(ruby_text: str, points: list[dict[str, object]]) -> list[str]:
    occurrence_stamps = {str(point["stamp"]) for point in points if str(point["text"]).strip("●")}
    related: list[str] = []
    for line in ruby_text.splitlines():
        if not line.startswith("@Ruby") or "=" not in line:
            continue
        fields = line.split("=", 1)[1].split(",")
        if any(field.strip() in occurrence_stamps for field in fields[2:]):
            related.append(line)
    return related


def plain_ruby_reading(value: str) -> str:
    return RUBY_LINE_TIME_RE.sub("", value)


def parse_ruby_definitions(ruby_text: str) -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = []
    for line in ruby_text.splitlines():
        if not line.startswith("@Ruby") or "=" not in line:
            continue
        heading, value = line.split("=", 1)
        fields = value.split(",")
        if len(fields) < 2:
            continue
        definitions.append({
            "id": heading,
            "surface": fields[0],
            "reading_encoded": fields[1],
            "reading": plain_ruby_reading(fields[1]),
            "occurrences": [field.strip() for field in fields[2:] if field.strip()],
        })
    return definitions


def annotate_ruby_points(ruby_text: str, points: list[dict[str, object]]) -> list[dict[str, object]]:
    by_stamp: dict[str, list[dict[str, object]]] = {}
    for definition in parse_ruby_definitions(ruby_text):
        for stamp in definition["occurrences"]:
            by_stamp.setdefault(str(stamp), []).append(definition)

    annotated: list[dict[str, object]] = []
    for point in points:
        item = dict(point)
        stamp = str(point.get("stamp", format_ruby_time(float(point["time"]))))
        token_text = str(point.get("text", ""))
        candidates = by_stamp.get(stamp, [])
        definition = next(
            (candidate for candidate in candidates if str(candidate["surface"]) in token_text),
            candidates[0] if candidates else None,
        )
        if definition:
            item.update({
                "ruby_id": definition["id"],
                "ruby_ids": [candidate["id"] for candidate in candidates if str(candidate["surface"]) in token_text],
                "ruby": definition["reading"],
                "ruby_surface": definition["surface"],
            })
        annotated.append(item)
    return annotated


def ruby_playback_lines(ruby_text: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for line in parse_ruby_timeline_lines(ruby_text):
        points = annotate_ruby_points(ruby_text, list(line["points"]))
        tokens: list[dict[str, object]] = []
        for index, point in enumerate(points[:-1]):
            text = str(point.get("text", ""))
            if not text or text == "●":
                continue
            tokens.append({
                "text": text,
                "start": float(point["time"]),
                "end": float(points[index + 1]["time"]),
                "ruby": str(point.get("ruby", "")),
                "ruby_id": str(point.get("ruby_id", "")),
                "ruby_ids": list(point.get("ruby_ids", [])),
            })
        if tokens:
            output.append({
                "line_index": int(line["line_index"]),
                "start": float(points[0]["time"]),
                "end": float(points[-1]["time"]),
                "tokens": tokens,
            })
    return output


def ruby_editor_lines(ruby_text: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for line in parse_ruby_timeline_lines(ruby_text):
        points = [
            {
                "index": int(point["index"]),
                "time": float(point["time"]),
                "text": str(point["text"]),
                "ruby_id": str(point.get("ruby_id", "")),
                "ruby_ids": list(point.get("ruby_ids", [])),
                "ruby": str(point.get("ruby", "")),
                "ruby_surface": str(point.get("ruby_surface", "")),
            }
            for point in annotate_ruby_points(ruby_text, list(line["points"]))
        ]
        output.append({
            "line_index": int(line["line_index"]),
            "text": str(line["text"]),
            "points": points,
        })
    return output


def encode_ruby_reading(current_encoded: str, new_reading: str, duration: float) -> str:
    new_characters = list(new_reading.strip())
    if not new_characters:
        raise ValueError("假名注音不能为空。")
    current_plain = plain_ruby_reading(current_encoded)
    matches = list(RUBY_LINE_TIME_RE.finditer(current_encoded))
    if len(current_plain) == len(new_characters):
        boundaries: dict[int, list[str]] = {}
        for match in matches:
            character_index = len(plain_ruby_reading(current_encoded[:match.start()]))
            boundaries.setdefault(character_index, []).append(match.group(0))
        rebuilt: list[str] = []
        for index, character in enumerate(new_characters, start=1):
            rebuilt.append(character)
            rebuilt.extend(boundaries.get(index, []))
        return "".join(rebuilt)

    last_relative = max((ruby_match_to_seconds(match) for match in matches), default=0.0)
    total_duration = max(float(duration), last_relative + 0.01, len(new_characters) * 0.05)
    rebuilt = []
    for index, character in enumerate(new_characters):
        rebuilt.append(character)
        if index < len(new_characters) - 1:
            rebuilt.append(format_ruby_time(total_duration * (index + 1) / len(new_characters)))
    return "".join(rebuilt)


def streamlit_media_url(media_path: Path, task_name: str) -> tuple[str, str]:
    from streamlit.runtime import get_instance

    suffix = media_path.suffix.lower()
    mimetype = VIDEO_MIMES.get(suffix) or AUDIO_MIMES.get(suffix) or "application/octet-stream"
    url = get_instance().media_file_mgr.add(
        str(media_path),
        mimetype,
        f"ruby-timeline-{task_name}-{media_path.name}",
        file_name=media_path.name,
    )
    return url, "video" if suffix in VIDEO_SUFFIXES else "audio"


def apply_ruby_timeline_edits(
    ruby_path: Path,
    line_edits: list[dict[str, object]],
    ruby_edits: dict[str, object] | None = None,
) -> Path:
    ruby_text = ruby_path.read_text(encoding="utf-8")
    timeline_lines = parse_ruby_timeline_lines(ruby_text)
    old_to_new: dict[str, str] = {}
    source_lines = ruby_text.splitlines(keepends=True)
    for edit in line_edits:
        try:
            line_index = int(edit["line_index"])
            updated_points = list(edit["points"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("时间线保存请求不完整，请重新载入后重试。") from exc
        if line_index < 0 or line_index >= len(timeline_lines):
            raise ValueError("Ruby 歌词行在编辑期间已变化，请刷新后重试。")
        target = timeline_lines[line_index]
        original_points = target["points"]
        assert isinstance(original_points, list)
        if len(updated_points) != len(original_points):
            raise ValueError("时间点数量与 Ruby 歌词不一致，请刷新后重试。")

        new_times: list[float] = []
        for point_index, point in enumerate(updated_points):
            try:
                value = round(float(point["time"]), 2)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"第 {point_index + 1} 个时间点无效。") from exc
            if point_index and value < new_times[point_index - 1]:
                raise ValueError("时间点不能早于前一个时间点。")
            new_times.append(value)

        rebuilt_line: list[str] = []
        for original, new_time in zip(original_points, new_times):
            old_stamp = str(original["stamp"])
            new_stamp = format_ruby_time(new_time)
            rebuilt_line.append(new_stamp + str(original["text"]))
            if str(original["text"]).strip("●"):
                old_to_new[old_stamp] = new_stamp
        source_index = int(target["source_index"])
        newline = "\r\n" if source_lines[source_index].endswith("\r\n") else "\n"
        source_lines[source_index] = "".join(rebuilt_line) + newline

    for index, line in enumerate(source_lines):
        stripped = line.rstrip("\r\n")
        if not stripped.startswith("@Ruby") or "=" not in stripped:
            continue
        heading, value = stripped.split("=", 1)
        fields = value.split(",")
        changed = False
        for field_index in range(2, len(fields)):
            stamp = fields[field_index].strip()
            if stamp in old_to_new:
                fields[field_index] = fields[field_index].replace(stamp, old_to_new[stamp])
                changed = True
        edit = (ruby_edits or {}).get(heading)
        if isinstance(edit, dict) and len(fields) >= 2:
            new_reading = str(edit.get("reading", "")).strip()
            try:
                duration = float(edit.get("duration", 0))
            except (TypeError, ValueError):
                duration = 0
            fields[1] = encode_ruby_reading(fields[1], new_reading, duration)
            changed = True
        if changed:
            line_ending = "\r\n" if line.endswith("\r\n") else "\n"
            source_lines[index] = heading + "=" + ",".join(fields) + line_ending

    backup_path = ruby_path.with_name(f"{ruby_path.stem}.before_timeline_{time.strftime('%Y%m%d-%H%M%S')}.lrc")
    shutil.copy2(ruby_path, backup_path)
    ruby_path.write_text("".join(source_lines), encoding="utf-8", newline="")
    return backup_path


def apply_ruby_timeline_edit(
    ruby_path: Path,
    line_index: int,
    updated_points: list[dict[str, object]],
    ruby_edits: dict[str, object] | None = None,
) -> Path:
    return apply_ruby_timeline_edits(
        ruby_path,
        [{"line_index": line_index, "points": updated_points}],
        ruby_edits,
    )


def render_ruby_timeline(task_dir: Path, ruby_path: Path, ruby_text: str, media_path: Path | None = None) -> None:
    lines = ruby_editor_lines(ruby_text)
    if not lines:
        st.warning("Ruby LRC 中没有可编辑的逐词时间行。")
        return
    st.subheader("音视频与 Ruby 分词时间线校对")
    st.caption("编辑在浏览器中暂存，不会因拖动圆点刷新页面；先同步到视频预览，确认后再保存到字幕文件。")
    media_url = ""
    media_kind = ""
    if media_path and media_path.exists():
        try:
            media_url, media_kind = streamlit_media_url(media_path, task_dir.name)
        except Exception as exc:
            st.warning(f"无法把媒体载入时间线播放器：{exc}")
    component_value = RUBY_TIMELINE(
        editor_lines=lines,
        playback_lines=ruby_playback_lines(ruby_text),
        media_url=media_url,
        media_kind=media_kind,
        default=None,
        key=f"ruby_timeline_component_{task_dir.name}_{ruby_path.name}_{ruby_path.stat().st_mtime_ns}",
    )
    if isinstance(component_value, dict) and component_value.get("action") == "save":
        nonce = str(component_value.get("nonce", ""))
        nonce_key = f"ruby_timeline_save_nonce_{task_dir.name}_{ruby_path.name}"
        if nonce and st.session_state.get(nonce_key) != nonce:
            st.session_state[nonce_key] = nonce
            try:
                backup = apply_ruby_timeline_edits(
                    ruby_path,
                    list(component_value.get("lines", [])),
                    dict(component_value.get("ruby_edits", {})),
                )
            except (KeyError, TypeError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state["message"] = f"已保存 Ruby 时间线；备份：{backup.name}"
                st.rerun()


def render_partial_realign(task_dir: Path, ass_path: Path, media: dict[str, object]) -> None:
    audio_name = str(media.get("audio") or "")
    lyrics_name = str(media.get("lyrics") or "")
    with st.expander("局部重对轴（fork 的 --realign 流程）", expanded=False):
        st.caption("只跑指定 ASS 歌词行。时间范围留空时，使用上一句结束到下一句开始的区间。")
        row_range = st.text_input("重跑歌词行", value="", placeholder="例如 227 或 227-245", key=f"realign_rows_{task_dir.name}")
        time_range = st.text_input("音频时间范围（可选）", value="", placeholder="例如 18:35-19:20", key=f"realign_time_{task_dir.name}")
        range_mode = st.selectbox("行号类型", ["karaoke", "event"], key=f"realign_mode_{task_dir.name}")
        replacement_text = st.text_area(
            "替换歌词（可选，每行一句）",
            value="",
            placeholder="留空则使用 ASS 中已编辑的歌词",
            key=f"realign_text_{task_dir.name}",
        )
        inplace = st.checkbox("成功后直接覆盖当前 ASS（会先备份）", value=False, key=f"realign_inplace_{task_dir.name}")
        update_text = st.checkbox(
            "将 ASS 中的歌词同步回原输入 TXT",
            value=False,
            disabled=bool(replacement_text.strip()),
            key=f"realign_update_text_{task_dir.name}",
        )
        if st.button("开始局部重对轴", key=f"run_realign_{task_dir.name}", disabled=isinstance(st.session_state.get("alignment_job"), dict)):
            if not row_range.strip():
                st.error("请输入要重跑的行号或范围。")
                return
            if not audio_name or not lyrics_name:
                st.error("该任务缺少原始音频或歌词文件记录，无法局部重跑。")
                return
            args: dict[str, object] = {}
            saved_args = media.get("alignment_args")
            if isinstance(saved_args, dict):
                for flag in ("-v", "--lang", "-cs", "-cl", "-t", "-tl", "-tp", "-tr", "--offset", "--bpm", "--bpb", "-x", "-n", "--pronunciation_file"):
                    if flag in saved_args:
                        args[flag] = saved_args[flag]
            args.update({
                "-it": lyrics_name,
                "-ia": audio_name,
                "--realign": row_range.strip(),
                "--realign_ass": ass_path.name,
                "--realign_mode": range_mode,
                "--realign_time": time_range.strip() or None,
                "--realign_update_text": update_text,
            })
            if inplace:
                backup = ass_path.with_name(f"{ass_path.stem}.before_realign_{time.strftime('%Y%m%d-%H%M%S')}.ass")
                shutil.copy2(ass_path, backup)
                args["--realign_inplace"] = True
            else:
                args["--realign_output"] = f"{ass_path.stem}_realign_{time.strftime('%Y%m%d-%H%M%S')}.ass"
            if replacement_text.strip():
                replacement_path = task_dir / f"realign_replacement_{time.strftime('%Y%m%d-%H%M%S')}.txt"
                replacement_path.write_text(replacement_text.rstrip() + "\n", encoding="utf-8")
                args["--realign_text_file"] = replacement_path.name
                args["--realign_update_text"] = False
            st.session_state["alignment_job"] = start_alignment(task_dir, args, media, job_label="局部重对轴")
            st.rerun()


def render_results(task_dir: Path) -> None:
    st.markdown(
        f'<div class="status-card">{html.escape(st.session_state.get("message", "已载入任务"))}</div>',
        unsafe_allow_html=True,
    )
    ass_path, ruby_path, rlf_path = task_outputs(task_dir)
    ass_text = ass_path.read_text(encoding="utf-8") if ass_path else None
    ruby_text = ruby_path.read_text(encoding="utf-8") if ruby_path else None
    rlf_text = rlf_path.read_text(encoding="utf-8") if rlf_path else None

    media = task_media(task_dir)
    audio_path = task_dir / str(media["audio"]) if media.get("audio") else None
    video_path = task_dir / str(media["video"]) if media.get("video") else None
    audio_path = audio_path if audio_path and audio_path.exists() else None
    video_path = video_path if video_path and video_path.exists() else None

    timeline_media_path: Path | None = None
    if video_path and audio_path:
        preview_path = task_dir / "uploaded_video_and_audio_preview.mp4"
        sync_key = f"sync_preview_attempt_{task_dir.name}"
        if not preview_path.exists() and not st.session_state.get(sync_key):
            st.session_state[sync_key] = True
            with st.spinner("正在准备完整视频与上传音频的同步精修播放器…"):
                ok, ffmpeg_log = make_synced_preview(video_path, audio_path, preview_path)
            if not ok:
                st.session_state[f"sync_preview_error_{task_dir.name}"] = ffmpeg_log
            else:
                st.session_state.pop(f"sync_preview_error_{task_dir.name}", None)
        if preview_path.exists():
            timeline_media_path = preview_path
        else:
            st.error("无法生成视频与上传音频的同步精修播放器。")
            error_log = st.session_state.get(f"sync_preview_error_{task_dir.name}")
            if error_log:
                st.code(str(error_log), language="text")
            if st.button("重试生成同步播放器", key=f"retry_sync_{task_dir.name}"):
                st.session_state.pop(sync_key, None)
                st.rerun()
    elif video_path:
        timeline_media_path = video_path
    elif audio_path:
        timeline_media_path = audio_path

    refine_tab, realign_tab, export_tab = st.tabs([
        "音视频与分词精修",
        "片段重新 AI 打轴",
        "导出字幕",
    ])

    with refine_tab:
        if ruby_path and ruby_text:
            render_ruby_timeline(task_dir, ruby_path, ruby_text, timeline_media_path)
        elif timeline_media_path:
            st.info("当前任务没有 Ruby LRC，因此无法打开分词精修播放器。")

    with realign_tab:
        st.subheader("片段重新 AI 打轴")
        st.caption("可在同一页播放原视频与人声音频，并对指定歌词行重新执行 AI 对齐。")
        if timeline_media_path:
            if timeline_media_path.suffix.lower() in VIDEO_SUFFIXES:
                subtitle_path = task_dir / "preview.vtt"
                subtitles = ass_to_vtt(ass_text, ruby_text) if ass_text else None
                if subtitles and (not subtitle_path.exists() or subtitle_path.read_text(encoding="utf-8") != subtitles):
                    subtitle_path.write_text(subtitles, encoding="utf-8")
                st.video(
                    str(timeline_media_path),
                    subtitles={"FA-Kara 逐字高亮": str(subtitle_path)} if subtitles else None,
                )
            else:
                st.audio(str(timeline_media_path))
        if ass_path and ass_text:
            render_partial_realign(task_dir, ass_path, media)
        else:
            st.info("当前任务没有 ASS 字幕，无法执行片段重新打轴。")

    with export_tab:
        st.subheader("导出字幕文件")
        available_exports = [
            (label, path, content)
            for label, path, content in [
                ("ASS 字幕", ass_path, ass_text),
                ("Ruby LRC", ruby_path, ruby_text),
                ("RLF LRC", rlf_path, rlf_text),
            ]
            if path and content
        ]
        if available_exports:
            selected_label = st.selectbox("导出格式", [item[0] for item in available_exports])
            label, path, content = next(item for item in available_exports if item[0] == selected_label)
            st.download_button(
                f"下载 {label}",
                content,
                file_name=path.name,
                key=f"download_{path.name}",
                type="primary",
                use_container_width=True,
            )
            st.caption(f"文件名：{path.name}")
        else:
            st.info("尚未生成可导出的字幕文件。")


def optional_number(raw_value: str, label: str, cast: type[int] | type[float]) -> int | float | None:
    value = raw_value.strip()
    if not value:
        return None
    try:
        return cast(value)
    except ValueError as exc:
        raise ValueError(f"{label}必须是数字，或者留空使用 main.py 默认值。") from exc


def optional_binary(raw_value: str, label: str) -> int | None:
    value = raw_value.strip()
    if not value:
        return None
    if value not in {"0", "1"}:
        raise ValueError(f"{label}只能输入 0、1，或者留空。")
    return int(value)


def optional_language(raw_value: str) -> str | None:
    value = raw_value.strip().lower()
    if not value:
        return None
    aliases = {"jp": "ja", "jpn": "ja", "zh": "zhen", "zh-cn": "zhen", "cn": "zhen", "en": "jaen"}
    value = aliases.get(value, value)
    if value not in {"auto", "ja", "jaen", "zhen"}:
        raise ValueError("歌词语言支持 auto、ja、jaen、zhen；也接受 jp/jpn、zh/cn、en 别名。")
    return value


def main() -> None:
    inject_style()
    st.markdown('<div class="eyebrow">FA-Kara / alignment desk</div>', unsafe_allow_html=True)
    st.title("FA-Kara Studio")
    st.markdown(
        '<div class="subtitle">上传注音歌词与人声音频，生成后可直接用音频或视频检查字幕时序。对齐任务在独立进程中运行，日志会实时更新。</div>',
        unsafe_allow_html=True,
    )

    if not st.session_state.get("task_dir") and not isinstance(st.session_state.get("alignment_job"), dict):
        recent_task = latest_completed_task()
        if recent_task:
            st.session_state["task_dir"] = str(recent_task)
            st.session_state["message"] = f"已恢复最近完成任务：{recent_task.name}"

    with st.sidebar:
        st.header("输入文件")
        lyrics_file = st.file_uploader("注音歌词 TXT", type=["txt"], key="lyrics")
        audio_file = st.file_uploader("人声音频", type=["wav", "mp3", "flac", "m4a", "ogg"], key="audio")
        video_file = st.file_uploader("可选：检查视频", type=["mp4", "mov", "mkv", "webm"], key="video")
        pronunciation_file = st.file_uploader("可选：pronunciations.txt", type=["txt"], key="pronunciation")
        st.divider()
        st.header("可选对齐参数")
        st.caption("所有框默认为空。留空时不会向 main.py 传递该选项，完全使用原项目的 argparse 默认值。")
        speed = st.text_input("推理音频速度 -v", value="", placeholder="留空 = main.py 默认 1")
        language = st.text_input("歌词语言 --lang", value="", placeholder="留空 = auto")
        chunk_seconds = st.text_input("自动分块时长 -cs", value="", placeholder="留空 = 0（关闭分块）")
        chars_per_line = st.text_input("每行最大字数 -cl", value="", placeholder="留空 = 0")
        tail_correct = st.text_input("尾音拖长修正 -t", value="", placeholder="留空 = 3")
        tail_window = st.text_input("静音检测窗口 -tl", value="", placeholder="留空 = 0.8")
        tail_pct = st.text_input("尾音阈值百分位 -tp", value="", placeholder="留空 = 10")
        tail_ratio = st.text_input("尾音阈值比例 -tr", value="", placeholder="留空 = 0.1")
        offset = st.text_input("Ruby Offset --offset", value="", placeholder="留空 = -150")
        bpm = st.text_input("导唱 BPM --bpm", value="", placeholder="留空 = 60")
        bpb = st.text_input("导唱符号数 --bpb", value="", placeholder="留空 = 3")
        sokuon = st.text_input("拆分促音 -x（0/1）", value="", placeholder="留空 = 0")
        hatsuon = st.text_input("拆分拨音 -n（0/1）", value="", placeholder="留空 = 1")
        run_button = st.button(
            "开始生成",
            type="primary",
            use_container_width=True,
            disabled=isinstance(st.session_state.get("alignment_job"), dict),
        )

    render_upload_preview(lyrics_file, audio_file, video_file)

    if run_button:
        if not lyrics_file or not audio_file:
            st.error("请至少上传注音歌词和人声音频。")
        else:
            try:
                optional_args: dict[str, object] = {
                    "-v": optional_number(speed, "推理音频速度", float),
                    "--lang": optional_language(language),
                    "-cs": optional_number(chunk_seconds, "自动分块时长", float),
                    "-cl": optional_number(chars_per_line, "每行最大字数", int),
                    "-t": optional_number(tail_correct, "尾音拖长修正", int),
                    "-tl": optional_number(tail_window, "静音检测窗口", float),
                    "-tp": optional_number(tail_pct, "尾音阈值百分位", float),
                    "-tr": optional_number(tail_ratio, "尾音阈值比例", float),
                    "--offset": optional_number(offset, "Ruby Offset", int),
                    "--bpm": optional_number(bpm, "导唱 BPM", float),
                    "--bpb": optional_number(bpb, "导唱符号数", int),
                    "-x": optional_binary(sokuon, "拆分促音"),
                    "-n": optional_binary(hatsuon, "拆分拨音"),
                }
            except ValueError as exc:
                st.error(str(exc))
            else:
                TASK_ROOT.mkdir(exist_ok=True)
                task_dir = Path(tempfile.mkdtemp(prefix="task_", dir=TASK_ROOT))
                standardized = active_standardized_lyrics(lyrics_file)
                if standardized:
                    lyrics_path = task_dir / safe_name(str(standardized["output_name"]), "lyrics_std.txt")
                    lyrics_path.write_text(str(standardized["content"]), encoding="utf-8")
                else:
                    lyrics_path = save_upload(lyrics_file, task_dir, "lyrics.txt")
                audio_path = save_upload(audio_file, task_dir, "vocal.wav")
                video_path = save_upload(video_file, task_dir, "source.mp4")
                pronunciation_path = save_upload(pronunciation_file, task_dir, "pronunciations.txt")
                args = {
                    "-it": lyrics_path.name,
                    "-ia": audio_path.name,
                    **optional_args,
                    "--pronunciation_file": pronunciation_path.name if pronunciation_path else None,
                }
                args = {flag: value for flag, value in args.items() if value not in (None, "")}
                media: dict[str, object] = {
                    "lyrics": lyrics_path.name,
                    "audio": audio_path.name,
                    "video": video_path.name if video_path else None,
                    "pronunciation": pronunciation_path.name if pronunciation_path else None,
                    "alignment_args": args,
                }
                st.session_state["alignment_job"] = start_alignment(task_dir, args, media)
                st.session_state.pop("task_dir", None)

    render_alignment_job()
    if not isinstance(st.session_state.get("alignment_job"), dict) and st.session_state.get("last_alignment_log"):
        with st.expander("上一次任务日志", expanded=False):
            st.code(st.session_state["last_alignment_log"], language="text")

    task_dir_value = st.session_state.get("task_dir")
    task_dir = Path(task_dir_value) if task_dir_value else None
    if task_dir and task_dir.exists():
        render_results(task_dir)


if __name__ == "__main__":
    main()
