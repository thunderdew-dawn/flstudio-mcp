# Knowledgebase Protocol

Agents use the Knowledgebase to avoid guessing FL Studio behavior, API ranges,
parameter mappings, automation IDs, plugin parameter indices, and recurring
pitfalls.

## FL Studio Knowledgebase Protocol

- Agents must check the Knowledgebase (`knowledgebase/`) before making changes
  to FL Studio state, mixer parameters, plugin parameters, automation, REC
  events, or MIDI data.
- Agents must not guess valid value ranges, normalized values, dB/Hz mappings,
  REC event IDs, track indexing, or plugin parameter indices.
- Agents must prefer high-level MCP tools over raw FL API calls. Raw calls are
  only permitted if no safe wrapper exists.
- When new verified knowledge is acquired, it must be documented in a Markdown
  file. If machine-relevant, it must additionally be documented in JSON/YAML.
- Every Knowledgebase entry needs at least: Topic, Source/Verification Method,
  Date, Confidence Level, Affected API/Function/Tool, Valid Ranges, Example,
  and Known Pitfalls.
- Hard rule: Agents must not leave reusable findings only in chat, commit
  messages, or temporary scratch notes.

## Knowledge Capture Protocol

An agent must update the Knowledgebase if any of the following occur:

- An FL Studio API behavior is practically tested.
- A parameter range is confirmed by trial, readback, docs, or error messages.
- A mapping between a UI value and an API value is discovered.
- A recurring error or pitfall is detected.
- A workaround is successfully applied.
- An MCP wrapper is added, modified, or identified as necessary.
- An assumption is proven wrong.
- A tool call or server error shows that existing KB knowledge is missing or
  unclear.
- A musical recipe rule is reusable.
- A behavior depends on the FL Studio version, platform, plugin version, or API
  version.

Every new entry must contain:

- Date
- Agent/Author
- Topic
- Affected File/API
- Context
- Observation
- Tested Values
- Result
- Confidence Level
- Source/Method
- Reproduction Steps, if relevant
- Open Questions
- Next Recommended Action

## Confidence Levels

Use one of these confidence levels:

- `hypothesis`
- `user_reported`
- `docs_confirmed`
- `measured_once`
- `measured_repeated`
- `implementation_verified`
- `cross_platform_verified`
- `deprecated_or_rejected`

## Machine-Relevant Findings

If a finding affects tool behavior, Markdown is not enough. JSON/YAML must be
updated.

If uncertain, do not document false certainty. Use a low confidence level and
add an open question.

Every new or modified MCP function must check for a KB entry. If none exists,
create a brief entry.

Every resolved false assumption must also be documented in
`knowledgebase/known_pitfalls/`.
