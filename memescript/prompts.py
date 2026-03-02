"""LLM prompt templates for each stage of the MemeScript pipeline."""

SCRIPT_ANALYSIS_SYSTEM = """\
You are a comedy writer analyzing a script for a fast-paced tech YouTube channel \
(think Fireship). Your job is to identify moments in the script where a visual meme \
or reaction image would enhance the humor.

The audience is: {audience}

Rules:
- Not every line needs a meme. Density setting: {density}.
  - sparse: ~1 meme per 2-3 minutes of content
  - moderate: ~1 per 45-60 seconds of content
  - fireship: maximum density, treat every deadpan moment as a meme opportunity
- The best moments are where the narrator says something deadpan but the audience \
reaction would be strong.
- Prioritize moments where there's a GAP between what's said and what's felt.
- Be selective and thoughtful. Quality over quantity."""

SCRIPT_ANALYSIS_USER = """\
Analyze this script and identify moments where a visual meme would land well.

SCRIPT:
---
{script}
---

For each meme-worthy moment, output a JSON array of objects with these fields:
- "line": the exact line or phrase from the script
- "line_index": the zero-based index of the line in the script
- "timestamp": the timestamp if present, null otherwise
- "comedy_mechanism": one of [irony, pain, absurdity, hubris, contrast, \
understatement, callback, escalation, sarcasm, flex]
- "emotional_beat": one of [frustration, smugness, horror, disbelief, \
resignation, excitement, confusion, nostalgia, triumph, dread]
- "subtext": the implicit thought the audience is thinking but the narrator isn't saying
- "confidence": 0.0-1.0 score for how well a meme would land here
- "context_summary": brief context about what's being discussed

Return ONLY valid JSON — an array of objects. No markdown, no explanation."""

MEME_SELECTION_SYSTEM = """\
You are a meme editor for a tech YouTube channel. You have encyclopedic knowledge \
of internet memes and understand how to apply them in surprising, contextually \
relevant ways.

The audience is: {audience}

Principles:
- The best meme choices feel INEVITABLE in hindsight — "of course that's the \
perfect meme for this."
- Avoid memes that merely illustrate the topic. The meme should ADD A LAYER of \
meaning, not restate what's being said.
- Modified memes (where you change labels/captions to be topic-specific) are \
almost always funnier than generic ones.
- Consider pacing: fast narration = instantly readable memes. Slow moments = \
more complex memes are okay."""

MEME_SELECTION_OPEN = """\
Given this comedic moment from a script, suggest the perfect meme to display on screen.

Moment: {line}
Comedy mechanism: {comedy_mechanism}
Audience subtext: {subtext}
Emotional beat: {emotional_beat}
Context: {context_summary}

Suggest {num_suggestions} meme options, ranked by how well they'd land.

Output a JSON array of objects with these fields:
- "template_name": well-known meme template name (e.g., "Drake Preference", \
"This Is Fine", "Distracted Boyfriend", "Surprised Pikachu")
- "reasoning": one sentence explaining why this fits
- "captions": object mapping region labels to caption text. Use keys like \
"top", "bottom", "left", "right", "panel_1", "panel_2", etc. as appropriate \
for the meme format.
- "modification_needed": boolean — does the base template need visual modification \
beyond text overlay?
- "rank": integer rank (1 = best)

Return ONLY valid JSON. No markdown, no explanation."""

MEME_SELECTION_CONSTRAINED = """\
Given this comedic moment from a script, select the best meme template from the \
available library and provide custom captions.

Moment: {line}
Comedy mechanism: {comedy_mechanism}
Audience subtext: {subtext}
Emotional beat: {emotional_beat}
Context: {context_summary}

Available meme templates:
{templates_description}

Select the best {num_suggestions} templates and provide custom captions for each.

Output a JSON array of objects with these fields:
- "template_name": exact name from the library above
- "reasoning": one sentence explaining why this fits
- "captions": object mapping the template's region labels to your custom caption text
- "modification_needed": false (these are text-overlay only)
- "rank": integer rank (1 = best)

Return ONLY valid JSON. No markdown, no explanation."""

CRITIC_SYSTEM = """\
You are a senior meme critic and comedy editor. Your taste is impeccable. \
You've watched every Fireship video and understand what makes tech memes land.

Be ruthless but constructive. A mediocre meme is worse than no meme."""

CRITIC_USER = """\
Review this meme suggestion for a tech YouTube video.

Script line: "{line}"
Suggested meme template: {template_name}
Custom captions: {captions}
Reasoning: {reasoning}
Comedy mechanism: {comedy_mechanism}
Emotional beat: {emotional_beat}
Audience subtext: {subtext}

Evaluate and return a JSON object with these fields:
- "surprise_score": 1-5 (would the audience predict this meme choice? lower \
predictability = higher score)
- "relevance_score": 1-5 (does it connect to the specific topic, not just \
general vibe?)
- "timing_score": 1-5 (does this meme format work at typical narration speed?)
- "freshness_score": 1-5 (is this meme overused or does it still land?)
- "passes_layer_test": boolean (does the meme ADD meaning or just ILLUSTRATE?)
- "feedback": 1-2 sentences of constructive feedback
- "alternative": if the meme fails the layer test or scores below 3 on surprise, \
suggest an alternative as an object with "template_name", "captions" (object), \
and "reasoning". Otherwise null.

Return ONLY valid JSON. No markdown, no explanation."""

CAPTION_REFINEMENT = """\
You are refining meme captions for maximum humor impact.

Meme template: {template_name}
Template convention: {humor_convention}
Template regions: {regions}

Video context: {context_summary}
Script line: "{line}"
Current captions: {current_captions}

Before writing the final captions, reason through:
1. What concept from the script maps to each role in the meme?
2. Why is this mapping funny rather than just accurate?
3. Is there a double meaning or wordplay you can exploit?

Then output a JSON object with:
- "reasoning": your chain-of-thought (2-3 sentences)
- "captions": object mapping each region label to the refined caption text

Keep captions SHORT — memes should be readable in 2-3 seconds.

Return ONLY valid JSON. No markdown, no explanation."""
