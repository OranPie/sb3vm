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
    # ---- Pen (all drawing is a no-op in headless) -------------------------
    if opcode in EXT_STMT_OPS and opcode.startswith("pen_"):
        return Stmt("no_op", {})
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

    # ---- Music ------------------------------------------------------------
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

