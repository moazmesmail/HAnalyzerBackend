"""Prompt builders for evidence extraction and evidence-grounded reporting."""

import json


EXTRACTION_OUTPUT_SCHEMA = r"""

Output Schema

Respond with JSON only: no markdown, code fences, preamble, or trailing explanation.
The values below are TYPE DESCRIPTIONS, not example content. Never copy them as values.
Every top-level field and every record field shown below must be present in every response.
Use [] when a list has no supported items and null when an optional value is unavailable.

{
  "summary": "<concise summary of visible evidence in this request only>",
  "observations": [
    {
      "type": "<short observation type>",
      "start_seconds": <number copied from a supplied frame timestamp>,
      "end_seconds": <number copied from a supplied frame timestamp>,
      "observation": "<directly visible fact>",
      "interpretation": "<cautious interpretation or null>",
      "confidence": <number 0.0-1.0>,
      "importance": <number 0.0-1.0>,
      "evidence_frame_ids": ["<one or more supplied frame_id UUIDs>"],
      "limitations": ["<specific visibility or sampling limitation>"]
    }
  ],
  "domain_records": [
    {
      "category": "<segment|participant|run|obstacle|jump|fault|scoreboard|assessment|movement|causal_hypothesis>",
      "subtype": "<category-specific controlled label>",
      "title": "<short evidence-grounded title>",
      "start_seconds": <number copied from a supplied frame timestamp>,
      "end_seconds": <number copied from a supplied frame timestamp>,
      "observation": "<directly visible fact>",
      "interpretation": "<cautious interpretation or null>",
      "attributes": {"<only category-specific keys defined below>": "<visible value or null>"},
      "confidence": <number 0.0-1.0>,
      "importance": <number 0.0-1.0>,
      "evidence_frame_ids": ["<one or more supplied frame_id UUIDs>"],
      "limitations": ["<specific visibility or sampling limitation>"]
    }
  ]
}

Hard constraints:
- The response must contain exactly these three top-level keys: summary, observations, domain_records.
- Return at most 15 domain_records and at most 3 general observations. Prioritize distinct events.
- Keep the complete response below 4,500 tokens. Use one sentence for observation and interpretation.
- Keep attributes compact: short labels and values, with no repeated narrative.
- Every object in observations and domain_records must contain every field shown above.
- Copy frame_id values exactly. Never return contact-sheet labels such as F001 as frame IDs.
- Every timestamp must equal a timestamp from a supplied frame label in this request.
- start_seconds must be less than or equal to end_seconds.
- observations may be empty. Use it only for important facts that fit no domain category.
- Never put a visible fact only in interpretation. Put the visible evidence in observation first.
- Never claim that a fault or event was absent across the video from this sampled window.

Category attribute contracts:
- segment: segment_type, description.
- participant: participant_type, name, country, team, bib_number, uniform_colors, horse_color, identifying_features.
- run: rider_name, horse_name, country, team, bib_number, starting_order, official_faults, official_time, official_rank.
- obstacle: obstacle_number, obstacle_type, combination_label, color, position, approach_direction, difficulty, difficulty_reason.
- jump: jump_number, obstacle_number, obstacle_type, approach, takeoff, airborne, landing, recovery, rail_contact, rail_down, refusal.
- fault: event_type, obstacle_number, severity, possible_causes, official_consequence.
- scoreboard: raw_text, rider_name, horse_name, country, rank, faults, time, team_score.
- assessment: assessment_category, balance, control, rhythm, posture, rein_control, turn_efficiency, landing_recovery, synchronization, strategy, metrics.
- movement: from_obstacle, to_obstacle, duration_seconds, movement, turn, rhythm_change, acceleration_change.
- causal_hypothesis: event, possible_causes, consequence. Every possible cause must be described as uncertain.

For attributes, include only keys from the selected category contract. Use null for a contract field
that is relevant but not visible. Do not invent alternative key names for the same concept.
"""


REPORT_OUTPUT_SCHEMA = r"""

Output Schema

Respond with JSON only: no markdown, code fences, preamble, or trailing explanation.
The values below are TYPE DESCRIPTIONS, not example content. Never copy them as values.
Return every top-level field. Use {}, [], or null when evidence does not support a section.

{
  "executive_summary": "<evidence-grounded overall summary>",
  "video_features": {"<stable feature name>": "<supported value or null>"},
  "competition_context": {"<stable context name>": "<supported value or null>"},
  "key_moments": [{"artifact_id": "<supplied artifact UUID>", "timestamp_seconds": <number>, "title": "<text>", "description": "<text>"}],
  "run_summaries": [{"artifact_id": "<supplied artifact UUID>", "rider": "<text or null>", "horse": "<text or null>", "summary": "<text>"}],
  "course_analysis": {"<supported course feature>": "<value>"},
  "technique_analysis": {"<supported technique feature>": "<value>"},
  "synchronization_analysis": {"<supported interaction feature>": "<value>"},
  "scoreboard_results": [{"artifact_id": "<supplied artifact UUID>", "raw_text": "<verbatim visible text>", "parsed_values": {}}],
  "comparisons": [{"artifact_id": "<supplied artifact UUID>", "comparison": "<text>", "basis": "<text>"}],
  "causal_hypotheses": [{"artifact_id": "<supplied artifact UUID>", "possible_cause": "<text>", "event": "<text>", "consequence": "<text or null>", "confidence": <number 0.0-1.0>}],
  "strengths": ["<evidence-grounded strength>"],
  "weaknesses": ["<evidence-grounded weakness>"],
  "recommendations": ["<recommendation tied to visible evidence>"],
  "limitations": ["<coverage, visibility, sampling, or uncertainty limitation>"]
}

Hard constraints:
- Return exactly the fifteen top-level keys shown above.
- Keep the complete response below 4,500 tokens. Prefer concise synthesis over repeating evidence.
- Return at most 10 key moments and at most one run summary per detected run.
- Reference only artifact_id values supplied in the structured evidence.
- Never turn a missing or failed time range into an absence claim.
- Do not present interpretation or possible causation as an observed fact.
- Do not combine conflicting scoreboard readings; describe the conflict in limitations.
"""


def extraction_prompt(profile_id: str) -> str:
    if profile_id != "equestrian_show_jumping":
        focus = "Identify visible subjects, actions, scene changes, readable text, and notable events."
    else:
        focus = """Extract show-jumping domain records when visible:
- segment: introduction, rider_entry, preparation, competition_run, jump, replay, scoreboard, reaction, results, or ceremony
- participant: rider, horse, country, team, bib number, colors, and identifying features
- run: rider/horse round boundaries and visible official result fields
- obstacle: number, type, combination, color, position, direction, and qualitative difficulty
- jump: approach, takeoff, airborne clearance, landing, recovery, and obstacle number
- fault: rail contact/down, refusal, run-out, hesitation, imbalance, bad landing, deviation, or fall
- scoreboard: raw visible text plus separately parsed rider, horse, country, faults, time, and rank
- assessment: horse behavior, rider technique, horse-rider synchronization, or strategy
- movement: qualitative speed, direction, rhythm, turn, and timing changes
- causal_hypothesis: possible cause, visible event, and consequence, clearly marked as uncertain"""
    return f"""Analyze only this 10-second silent frame window in chronological order.
{focus}

Return domain_records as the primary result. Use general observations only for an important visible
finding that does not fit any domain category. Put domain-specific fields in each record's attributes
object. Use null or omit an attribute when it is not visible. Never invent a
name, country, obstacle number, official result, or measurement. Exact speed, distance, height,
joint angle, emotion, pain, and medical state cannot be determined from these frames.

Every item must reference supplied frame_id UUID values and timestamps inside this window. The
observation is the directly visible fact; interpretation is optional and uncertain. Do not claim
that an event did not happen merely because sampled frames do not show it. For scoreboard records,
preserve raw_text separately from parsed fields. Return concise, non-duplicate records.""" + EXTRACTION_OUTPUT_SCHEMA


def report_prompt(evidence: dict) -> str:
    return """Generate a deep competition report using only the structured evidence JSON below.
Do not add facts from general knowledge. Treat observation fields as visible facts and interpretation
or causal_hypothesis fields as uncertain. Never turn missing coverage into an absence claim. Keep
official scoreboard values separate from inferred performance. Comparisons are allowed only when at
least two resolved runs have sufficient evidence. Include artifact_id in key moments, run summaries,
scoreboard entries, comparisons, and causal hypotheses whenever they support a claim. Put unavailable
sections in limitations instead of guessing.

Structured evidence:
""" + json.dumps(evidence, ensure_ascii=False, separators=(",", ":")) + REPORT_OUTPUT_SCHEMA
