"""Scratch 3.0 official extension support for the headless VM.

Each official extension (pen, music extras, videoSensing, text2speech,
translate) is handled here.  Headless behaviour:

* **pen**       – all drawing ops are no-ops; pen-state changes are silently
                  ignored since there is no renderer.
* **music**     – timing (play drum / rest) works; tempo is mutable;
                  instrument selection is a no-op.
* **videoSensing** – no camera → videoOn returns 0; toggle/transparency
                  are no-ops.
* **text2speech** – no audio output → speakAndWait and voice/language
                  setters are no-ops.
* **translate** – getTranslate returns the original text unchanged;
                  getViewerLanguage returns "en".

TurboWarp built-in extensions:

* **tw**               – isPaused/isTurboModeEnabled → False; getLastKeyPressed
                  → ""; log/warn/error → no-ops.
* **runtime_options**  – getFPS → 30; getCloneLimit → 300; getStageWidth → 480;
                  getStageHeight → 360; all boolean getters → False; all setters
                  and frameCount → no-ops / 0.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sb3vm.parse.ast_nodes import Expr, Stmt
from sb3vm.vm.scratch_values import to_number

if TYPE_CHECKING:
    from sb3vm.vm.state import ThreadState, VMState

# ---------------------------------------------------------------------------
# Opcode sets – imported and merged into SUPPORTED_* in extract_scripts.py
# ---------------------------------------------------------------------------

EXT_EVENT_OPS: set[str] = set()

EXT_EXPR_OPS: set[str] = {
    # Music reporters / menus
    "music_getTempo",
    "music_menu_DRUM",
    "music_menu_INSTRUMENT",
    # Pen menus
    "pen_menu_colorParam",
    # VideoSensing reporters / menus
    "videoSensing_videoOn",
    "videoSensing_menu_ATTRIBUTE",
    "videoSensing_menu_SUBJECT",
    "videoSensing_menu_VIDEO_STATE",
    # Text2Speech menus
    "text2speech_menu_voices",
    "text2speech_menu_languages",
    # Translate reporters / menus
    "translate_getTranslate",
    "translate_getViewerLanguage",
    "translate_menu_languages",
    # TurboWarp built-ins
    "tw_getLastKeyPressed",
    "tw_isTurboModeEnabled",
    "tw_isPaused",
    "tw_counter",
    "tw_menu_TARGET",
    # TurboWarp runtime_options reporters
    "runtime_options_getFPS",
    "runtime_options_getCloneLimit",
    "runtime_options_getStageWidth",
    "runtime_options_getStageHeight",
    "runtime_options_isInfiniteClonesEnabled",
    "runtime_options_getFrameCount",
    "runtime_options_isFrameCountEnabled",
    "runtime_options_isHighQualityPenEnabled",
    "runtime_options_isWarpTimerEnabled",
    "runtime_options_isInterpolationEnabled",
}

EXT_STMT_OPS: set[str] = {
    # Music (additional; music_playNoteForBeats lives in SUPPORTED_STMT_OPS)
    "music_playDrumForBeats",
    "music_restForBeats",
    "music_setInstrument",
    "music_setTempo",
    "music_changeTempo",
    # Pen
    "pen_clear",
    "pen_stamp",
    "pen_penDown",
    "pen_penUp",
    "pen_setPenColorToColor",
    "pen_changePenColorParamBy",
    "pen_setPenColorParamTo",
    "pen_changePenSizeBy",
    "pen_setPenSizeTo",
    "pen_setPenShadeToNumber",
    "pen_changePenShadeBy",
    "pen_setPenHueToNumber",
    "pen_changePenHueBy",
    # VideoSensing
    "videoSensing_videoToggle",
    "videoSensing_setVideoTransparency",
    # Text2Speech
    "text2speech_speakAndWait",
    "text2speech_setVoice",
    "text2speech_setLanguage",
    # TurboWarp built-ins
    "tw_log",
    "tw_warn",
    "tw_error",
    "tw_setCustomFPS",
    "tw_setCounter",
    "tw_incrementCounter",
    # TurboWarp runtime_options setters
    "runtime_options_setFPS",
    "runtime_options_setCloneLimit",
    "runtime_options_setInfiniteClonesEnabled",
    "runtime_options_setFrameCountEnabled",
    "runtime_options_setHighQualityPenEnabled",
    "runtime_options_setWarpTimerEnabled",
    "runtime_options_setInterpolationEnabled",
    "runtime_options_setRemoveLimitsEnabled",
}

# ---------------------------------------------------------------------------
# Parse helpers – called from extract_scripts.ProjectParser
# ---------------------------------------------------------------------------

def parse_ext_stmt(
    opcode: str,
    block: dict[str, Any],
    expr_fn: Any,
    field_fn: Any,
) -> Stmt | None:
    """Return a Stmt for a known extension opcode, or None if unrecognised."""
    # ---- Music ------------------------------------------------------------
    if opcode == "music_playDrumForBeats":
        return Stmt("music_play_drum", {"drum": expr_fn("DRUM"), "beats": expr_fn("BEATS")})
    if opcode == "music_restForBeats":
        return Stmt("music_rest", {"beats": expr_fn("BEATS")})
    if opcode == "music_setInstrument":
        return Stmt("music_set_instrument", {"instrument": expr_fn("INSTRUMENT")})
    if opcode == "music_setTempo":
        return Stmt("music_set_tempo", {"tempo": expr_fn("TEMPO")})
    if opcode == "music_changeTempo":
        return Stmt("music_change_tempo", {"delta": expr_fn("TEMPO")})
    # ---- Pen ---------------------------------------------------------------
    if opcode == "pen_clear":
        return Stmt("pen_clear", {})
    if opcode == "pen_penDown":
        return Stmt("pen_down", {})
    if opcode == "pen_penUp":
        return Stmt("pen_up", {})
    if opcode == "pen_stamp":
        return Stmt("pen_stamp", {})
    if opcode == "pen_setPenSizeTo":
        return Stmt("pen_set_size", {"size": expr_fn("SIZE")})
    if opcode == "pen_changePenSizeBy":
        return Stmt("pen_change_size", {"delta": expr_fn("SIZE")})
    if opcode == "pen_setPenColorToColor":
        return Stmt("pen_set_color_to_color", {"color": expr_fn("COLOR")})
    if opcode == "pen_changePenColorParamBy":
        return Stmt("pen_change_color_param", {"param": expr_fn("colorParam"), "delta": expr_fn("VALUE")})
    if opcode == "pen_setPenColorParamTo":
        return Stmt("pen_set_color_param", {"param": expr_fn("colorParam"), "value": expr_fn("VALUE")})
    if opcode == "pen_setPenShadeToNumber":
        return Stmt("pen_set_shade", {"shade": expr_fn("SHADE")})
    if opcode == "pen_changePenShadeBy":
        return Stmt("pen_change_shade", {"delta": expr_fn("SHADE")})
    if opcode == "pen_setPenHueToNumber":
        return Stmt("pen_set_hue", {"hue": expr_fn("HUE")})
    if opcode == "pen_changePenHueBy":
        return Stmt("pen_change_hue", {"delta": expr_fn("HUE")})
    # ---- VideoSensing -----------------------------------------------------
    if opcode in {"videoSensing_videoToggle", "videoSensing_setVideoTransparency"}:
        return Stmt("no_op", {})
    # ---- Text2Speech -------------------------------------------------------
    if opcode in {"text2speech_speakAndWait", "text2speech_setVoice", "text2speech_setLanguage"}:
        return Stmt("no_op", {})
    # ---- TurboWarp tw_ (all no-ops in headless) ----------------------------
    if opcode in {"tw_log", "tw_warn", "tw_error", "tw_setCustomFPS",
                  "tw_setCounter", "tw_incrementCounter"}:
        return Stmt("no_op", {})
    # ---- TurboWarp runtime_options (all setters are no-ops) ----------------
    if opcode in EXT_STMT_OPS and opcode.startswith("runtime_options_"):
        return Stmt("no_op", {})
    return None


def parse_ext_expr(
    opcode: str,
    block: dict[str, Any],
    expr_fn: Any,
    field_fn: Any,
) -> Expr | None:
    """Return an Expr for a known extension opcode, or None if unrecognised."""
    # ---- Music ------------------------------------------------------------
    if opcode == "music_getTempo":
        return Expr("music_tempo")
    if opcode == "music_menu_DRUM":
        return Expr("literal", field_fn(block, "DRUM") or "")
    if opcode == "music_menu_INSTRUMENT":
        return Expr("literal", field_fn(block, "INSTRUMENT") or "")
    # ---- Pen menu ---------------------------------------------------------
    if opcode == "pen_menu_colorParam":
        return Expr("literal", field_fn(block, "colorParam") or "")
    # ---- VideoSensing -----------------------------------------------------
    if opcode == "videoSensing_videoOn":
        return Expr("video_sensing", {
            "attribute": expr_fn("ATTRIBUTE"),
            "subject": expr_fn("SUBJECT"),
        })
    if opcode == "videoSensing_menu_ATTRIBUTE":
        return Expr("literal", field_fn(block, "ATTRIBUTE") or "")
    if opcode == "videoSensing_menu_SUBJECT":
        return Expr("literal", field_fn(block, "SUBJECT") or "")
    if opcode == "videoSensing_menu_VIDEO_STATE":
        return Expr("literal", field_fn(block, "VIDEO_STATE") or "")
    # ---- Text2Speech menus ------------------------------------------------
    if opcode == "text2speech_menu_voices":
        return Expr("literal", field_fn(block, "voices") or "")
    if opcode == "text2speech_menu_languages":
        return Expr("literal", field_fn(block, "languages") or "")
    # ---- Translate --------------------------------------------------------
    if opcode == "translate_getTranslate":
        return Expr("translate", {"text": expr_fn("WORDS"), "language": expr_fn("LANGUAGE")})
    if opcode == "translate_getViewerLanguage":
        return Expr("viewer_language")
    if opcode == "translate_menu_languages":
        return Expr("literal", field_fn(block, "languages") or "")
    # ---- TurboWarp tw_ reporters ------------------------------------------
    if opcode == "tw_getLastKeyPressed":
        return Expr("literal", "")
    if opcode in {"tw_isTurboModeEnabled", "tw_isPaused"}:
        return Expr("literal", False)
    if opcode == "tw_counter":
        return Expr("literal", 0)
    if opcode == "tw_menu_TARGET":
        return Expr("literal", field_fn(block, "TARGET") or "")
    # ---- TurboWarp runtime_options reporters ------------------------------
    if opcode == "runtime_options_getFPS":
        return Expr("literal", 30)
    if opcode == "runtime_options_getCloneLimit":
        return Expr("literal", 300)
    if opcode == "runtime_options_getStageWidth":
        return Expr("literal", 480)
    if opcode == "runtime_options_getStageHeight":
        return Expr("literal", 360)
    if opcode in {
        "runtime_options_isInfiniteClonesEnabled",
        "runtime_options_isFrameCountEnabled",
        "runtime_options_isHighQualityPenEnabled",
        "runtime_options_isWarpTimerEnabled",
        "runtime_options_isInterpolationEnabled",
    }:
        return Expr("literal", False)
    if opcode == "runtime_options_getFrameCount":
        return Expr("literal", 0)
    return None


# ---------------------------------------------------------------------------
# Eval helper – called from eval_expr.eval_expr()
# ---------------------------------------------------------------------------

def eval_ext_expr(kind: str, expr: Any, vm_state: Any, thread: Any, vm: Any) -> Any:
    """Evaluate an extension expression kind.  Raises ValueError if unknown."""
    if kind == "music_tempo":
        return vm_state.music_tempo
    if kind == "video_sensing":
        # No camera in headless mode.
        return 0
    if kind == "translate":
        from sb3vm.vm.eval_expr import eval_expr  # late import avoids cycle
        from sb3vm.vm.scratch_values import to_string
        return to_string(eval_expr(expr.value["text"], vm_state, thread, vm))
    if kind == "viewer_language":
        return "en"
    if kind == "graceful_ext":
        # Unknown custom extension expression – return safe default.
        return ""
    raise ValueError(f"Unsupported extension expression kind: {kind}")


# ---------------------------------------------------------------------------
# Runtime helper – called from runtime.Sb3Vm._execute_stmt()
# ---------------------------------------------------------------------------

def exec_ext_stmt(kind: str, stmt: Any, thread: Any, vm: Any) -> str | None:
    """Execute an extension statement.  Raises ValueError if unknown."""
    from sb3vm.vm.eval_expr import eval_expr  # late import avoids cycle

    # ---- Pen ---------------------------------------------------------------
    if kind.startswith("pen_"):
        return exec_pen_stmt(kind, stmt, thread, vm)
    if kind == "music_play_drum":
        eval_expr(stmt.args["drum"], vm.state, thread, vm)
        thread.wake_time = vm.state.time_seconds + vm._beats_to_seconds(
            eval_expr(stmt.args["beats"], vm.state, thread, vm)
        )
        return "block"
    if kind == "music_rest":
        thread.wake_time = vm.state.time_seconds + vm._beats_to_seconds(
            eval_expr(stmt.args["beats"], vm.state, thread, vm)
        )
        return "block"
    if kind == "music_set_instrument":
        eval_expr(stmt.args["instrument"], vm.state, thread, vm)
        return None
    if kind == "music_set_tempo":
        tempo = to_number(eval_expr(stmt.args["tempo"], vm.state, thread, vm))
        vm.state.music_tempo = max(20.0, min(500.0, tempo))
        return None
    if kind == "music_change_tempo":
        delta = to_number(eval_expr(stmt.args["delta"], vm.state, thread, vm))
        vm.state.music_tempo = max(20.0, min(500.0, vm.state.music_tempo + delta))
        return None
    raise ValueError(f"Unsupported extension statement kind: {kind}")


# ---------------------------------------------------------------------------
# Pen helpers
# ---------------------------------------------------------------------------

def _pen_color_from_scratch_int(value: int) -> tuple[int, int, int, int]:
    """Convert a Scratch color integer (0xRRGGBB or 0xAARRGGBB) to RGBA."""
    v = int(value) & 0xFFFFFFFF
    if v > 0xFFFFFF:
        a = 255 - ((v >> 24) & 0xFF)
        r = (v >> 16) & 0xFF
        g = (v >> 8) & 0xFF
        b = v & 0xFF
    else:
        a = 255
        r = (v >> 16) & 0xFF
        g = (v >> 8) & 0xFF
        b = v & 0xFF
    return (r, g, b, a)


def _pen_color_from_hex(value: str) -> tuple[int, int, int, int]:
    """Parse #RRGGBB or #RRGGBBAA hex colour string."""
    h = value.strip().lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (r, g, b, 255)
    if len(h) == 8:
        r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
        return (r, g, b, a)
    return (0, 0, 0, 255)


def _resolve_pen_color(raw: Any) -> tuple[int, int, int, int]:
    if isinstance(raw, str) and raw.strip().startswith("#"):
        return _pen_color_from_hex(raw)
    try:
        return _pen_color_from_scratch_int(int(to_number(raw)))
    except (TypeError, ValueError):
        return (0, 0, 0, 255)


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """h in [0,360), s and v in [0,1]. Returns (R,G,B) 0-255."""
    import math
    h = h % 360.0
    hi = int(h / 60) % 6
    f = h / 60 - math.floor(h / 60)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    mapping = [
        (v, t, p), (q, v, p), (p, v, t),
        (p, q, v), (t, p, v), (v, p, q),
    ]
    r, g, b = mapping[hi]
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Returns (h in [0,360), s in [0,1], v in [0,1])."""
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r_, g_, b_)
    cmin = min(r_, g_, b_)
    delta = cmax - cmin
    v = cmax
    s = 0.0 if cmax == 0 else delta / cmax
    if delta == 0:
        h = 0.0
    elif cmax == r_:
        h = 60.0 * (((g_ - b_) / delta) % 6)
    elif cmax == g_:
        h = 60.0 * ((b_ - r_) / delta + 2)
    else:
        h = 60.0 * ((r_ - g_) / delta + 4)
    return (h, s, v)


def _apply_pen_color_param(instance: Any, param: str, value: float) -> None:
    """Set a colour parameter; recompute instance.pen_color."""
    r, g, b, a = instance.pen_color
    h, s, v = _rgb_to_hsv(r, g, b)
    param_lower = str(param).lower().strip()
    if param_lower in {"color", "colour"}:
        h = (value / 100.0 * 360.0) % 360.0
    elif param_lower == "saturation":
        s = max(0.0, min(1.0, value / 100.0))
    elif param_lower == "brightness":
        v = max(0.0, min(1.0, value / 100.0))
    elif param_lower == "transparency":
        a = max(0, min(255, int(round(255 * (1.0 - value / 100.0)))))
    rn, gn, bn = _hsv_to_rgb(h, s, v)
    instance.pen_color = (rn, gn, bn, a)


def _change_pen_color_param(instance: Any, param: str, delta: float) -> None:
    r, g, b, a = instance.pen_color
    h, s, v = _rgb_to_hsv(r, g, b)
    param_lower = str(param).lower().strip()
    if param_lower in {"color", "colour"}:
        h = ((h + delta / 100.0 * 360.0) % 360.0)
    elif param_lower == "saturation":
        s = max(0.0, min(1.0, s + delta / 100.0))
    elif param_lower == "brightness":
        v = max(0.0, min(1.0, v + delta / 100.0))
    elif param_lower == "transparency":
        current_t = (1.0 - a / 255.0) * 100.0
        new_t = max(0.0, min(100.0, current_t + delta))
        a = max(0, min(255, int(round(255 * (1.0 - new_t / 100.0)))))
    rn, gn, bn = _hsv_to_rgb(h, s, v)
    instance.pen_color = (rn, gn, bn, a)


def exec_pen_stmt(kind: str, stmt: Any, thread: Any, vm: Any) -> str | None:
    """Execute a pen statement; returns None or a flow control string."""
    from sb3vm.vm.eval_expr import eval_expr
    from sb3vm.vm.scratch_values import to_number

    instance = vm.state.get_instance(thread.instance_id)
    if kind == "pen_clear":
        if vm.pen_clear_hook is not None:
            vm.pen_clear_hook()
        return None
    if kind == "pen_down":
        instance.pen_down = True
        return None
    if kind == "pen_up":
        instance.pen_down = False
        return None
    if kind == "pen_stamp":
        if vm.pen_stamp_hook is not None:
            vm.pen_stamp_hook(thread.instance_id)
        return None
    if kind == "pen_set_size":
        instance.pen_size = max(1.0, to_number(eval_expr(stmt.args["size"], vm.state, thread, vm)))
        return None
    if kind == "pen_change_size":
        delta = to_number(eval_expr(stmt.args["delta"], vm.state, thread, vm))
        instance.pen_size = max(1.0, instance.pen_size + delta)
        return None
    if kind == "pen_set_color_to_color":
        raw = eval_expr(stmt.args["color"], vm.state, thread, vm)
        instance.pen_color = _resolve_pen_color(raw)
        return None
    if kind == "pen_set_color_param":
        param = str(eval_expr(stmt.args["param"], vm.state, thread, vm))
        value = to_number(eval_expr(stmt.args["value"], vm.state, thread, vm))
        _apply_pen_color_param(instance, param, value)
        return None
    if kind == "pen_change_color_param":
        param = str(eval_expr(stmt.args["param"], vm.state, thread, vm))
        delta = to_number(eval_expr(stmt.args["delta"], vm.state, thread, vm))
        _change_pen_color_param(instance, param, delta)
        return None
    if kind == "pen_set_shade":
        shade = int(to_number(eval_expr(stmt.args["shade"], vm.state, thread, vm))) % 200
        instance.pen_shade = shade
        # Convert legacy shade/hue to color
        v = shade / 100.0 if shade <= 100 else (200 - shade) / 100.0
        s = 1.0
        h = instance.pen_hue / 200.0 * 360.0
        rn, gn, bn = _hsv_to_rgb(h, s, v)
        instance.pen_color = (rn, gn, bn, instance.pen_color[3])
        return None
    if kind == "pen_change_shade":
        delta = int(to_number(eval_expr(stmt.args["delta"], vm.state, thread, vm)))
        shade = (instance.pen_shade + delta) % 200
        instance.pen_shade = shade
        v = shade / 100.0 if shade <= 100 else (200 - shade) / 100.0
        h = instance.pen_hue / 200.0 * 360.0
        rn, gn, bn = _hsv_to_rgb(h, 1.0, v)
        instance.pen_color = (rn, gn, bn, instance.pen_color[3])
        return None
    if kind == "pen_set_hue":
        hue = int(to_number(eval_expr(stmt.args["hue"], vm.state, thread, vm))) % 200
        instance.pen_hue = hue
        h = hue / 200.0 * 360.0
        shade = instance.pen_shade
        v = shade / 100.0 if shade <= 100 else (200 - shade) / 100.0
        rn, gn, bn = _hsv_to_rgb(h, 1.0, v)
        instance.pen_color = (rn, gn, bn, instance.pen_color[3])
        return None
    if kind == "pen_change_hue":
        delta = int(to_number(eval_expr(stmt.args["delta"], vm.state, thread, vm)))
        new_hue = (instance.pen_hue + delta) % 200
        # Reuse set_hue logic via a synthetic call
        instance.pen_hue = new_hue
        h = new_hue / 200.0 * 360.0
        shade = instance.pen_shade
        v = shade / 100.0 if shade <= 100 else (200 - shade) / 100.0
        rn, gn, bn = _hsv_to_rgb(h, 1.0, v)
        instance.pen_color = (rn, gn, bn, instance.pen_color[3])
        return None
    return None

