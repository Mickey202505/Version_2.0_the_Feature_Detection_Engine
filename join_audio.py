# join_audio.py
#
# Generic audio-clip joiner for Smart Caddie's voice feature, plus builder
# functions for each message template (main shot recommendation, putting,
# and simple whole-sentence messages like the woods/lay-up warnings).
#
# Key differences from the original version:
#   - join_clips() actually checks whether ffmpeg succeeded before
#     reporting success (the original always printed "Successfully
#     generated" even when ffmpeg failed and left a corrupt/truncated file).
#   - Every referenced clip is checked to exist BEFORE calling ffmpeg, so a
#     missing file is reported clearly (which one, and why) instead of
#     discovered only via ffmpeg's own error text.
#   - None/empty-string entries are automatically skipped rather than
#     producing a broken filename like "move_.mp3" (confirmed real bug:
#     the original script's own test call passed movement="", which
#     ffmpeg then failed on silently).
#   - One generic function (join_clips) now backs every message template —
#     the wind/aim/lie/club recommendation, putting, and simple fixed
#     sentences — instead of a function tied to one specific sentence shape.

import os
import subprocess
import tempfile

FOLDER = "caddie_audio"


def join_clips(clip_names, output_filename, folder=FOLDER):
    """Joins an ordered list of clip base-names (no folder, no extension —
    e.g. "static_1", "dist_150") into a single mp3.

    Returns (success: bool, message: str). Never silently reports success
    on failure — checks both the ffmpeg exit code AND that a real output
    file was produced, and refuses to even attempt the join if any listed
    clip is missing (skips None/"" entries automatically, since those mean
    "nothing to say here," e.g. no crosswind, no elevation, no missing-
    field warning).
    """
    clips = [c for c in clip_names if c]  # drop None / "" placeholders
    if not clips:
        return False, "No clips to join — empty clip list."

    paths = [os.path.join(folder, f"{c}.mp3") for c in clips]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        return False, f"Missing audio file(s), nothing generated: {', '.join(missing)}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_file = f.name
        for p in paths:
            # ffmpeg's concat demuxer resolves relative paths relative to
            # the LIST FILE's own location, not the working directory —
            # since this list file lives in the system temp dir (not
            # necessarily next to caddie_audio/), paths must be absolute
            # or ffmpeg will look in the wrong place entirely.
            abs_path = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{abs_path}'\n")

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output_filename],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False, f"ffmpeg failed (exit {result.returncode}): {result.stderr.strip()[-500:]}"
        if not os.path.isfile(output_filename) or os.path.getsize(output_filename) == 0:
            return False, "ffmpeg reported success but produced no output file — treating as failure."
        return True, f"Generated {output_filename} from {len(clips)} clips."
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def build_shot_recommendation_clips(distance, wind_dir, wind_speed, movement,
                                     aim, lie, rec, club):
    """Builds the clip list for the main wind/aim/lie/club recommendation
    template. 'movement' can be None/"" for a genuine no-crosswind shot —
    that slot is simply omitted rather than referencing a nonexistent file
    (this is the exact case that silently failed before)."""
    return [
        "static_1", f"dist_{distance}", "static_2",
        f"winddir_{wind_dir}" if wind_dir else None,
        f"windspeed_{wind_speed}" if wind_speed else None,
        "static_3" if movement else None,
        f"move_{movement}" if movement else None,
        "static_4",
        f"aim_{aim}",
        f"lie_{lie}" if lie else None,
        f"rec_{rec}",
        f"club_{club}",
    ]


def build_putting_clips(distance_ft, break_direction, break_inches, stimp, feel_ft):
    """Builds the clip list for the putting narrative template (§5.7 /
    voice recording list §12): 'You have a {distance} foot putt, with a
    {N} inch {uphill/downhill} break. On a stimp of {stimp}, that plays
    like a {feel} foot putt.' 'break_direction'/'break_inches' can be
    None for a flat green (uses the "on a flat green" clip instead)."""
    has_break = break_direction and break_inches
    return [
        "putt_you_have_a", f"dist_{distance_ft}", "putt_foot_putt",
        f"putt_with_a_{break_inches}_inch_{break_direction}_break" if has_break else "putt_on_a_flat_green",
        "putt_on_a_stimp_of", f"dist_{stimp}",
        "putt_that_plays_like_a", f"dist_{feel_ft}", "putt_foot_putt",
    ]


def build_fixed_sentence_clips(sentence_key):
    """For whole fixed sentences with no variable slots (woods, lay-up
    prompt, prereq warnings, etc. — voice recording list §11). Each is
    just one clip, but goes through the same join_clips() path so
    playback code doesn't need a special case for "no joining needed."""
    return [sentence_key]


if __name__ == "__main__":
    # --- Test: main shot recommendation, WITH crosswind ---
    clips = build_shot_recommendation_clips(
        distance="22", wind_dir="west", wind_speed="1mph",
        movement="l2r", aim="left", lie="downslope", rec="hard", club="6iron",
    )
    ok, msg = join_clips(clips, "caddie_says_test.mp3")
    print(("OK: " if ok else "FAILED: ") + msg)

    # --- Test: main shot recommendation, NO crosswind (the case that
    # silently failed before) ---
    clips_no_wind = build_shot_recommendation_clips(
        distance="22", wind_dir="west", wind_speed="1mph",
        movement="", aim="left", lie="downslope", rec="strong", club="6iron",
    )
    ok, msg = join_clips(clips_no_wind, "caddie_says_test_nowind.mp3")
    print(("OK: " if ok else "FAILED: ") + msg)
