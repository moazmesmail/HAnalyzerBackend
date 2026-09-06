from app.features.analysis.schemas import AnalysisProfileResponse

GENERIC_CAPABILITIES = {
    "frames": True,
    "observations": True,
    "semantic_visual_analysis": True,
    "visible_text": True,
    "participants": True,
    "runs": False,
    "events": True,
    "jumps": False,
    "comparisons": False,
    "structured_domain_results": True,
    "deep_report": True,
    "audio_transcription": False,
    "report": True,
    "usage": True,
}

PROFILES = {
    "generic": AnalysisProfileResponse(
        id="generic",
        version="2.0",
        display_name="Generic visual sampling",
        description="Analyzes timestamped frame batches for visible subjects, actions, text, and events.",
        minimum_fps=3,
        maximum_fps=15,
        default_fps=3,
        capabilities=GENERIC_CAPABILITIES,
    ),
    "equestrian_show_jumping": AnalysisProfileResponse(
        id="equestrian_show_jumping",
        version="2.0",
        display_name="Equestrian show jumping",
        description="Analyzes riders, horses, runs, obstacles, jumps, visible faults, technique, and displayed results.",
        minimum_fps=3,
        maximum_fps=15,
        default_fps=3,
        capabilities={
            **GENERIC_CAPABILITIES,
            "runs": True,
            "jumps": True,
            "comparisons": True,
        },
    ),
}
