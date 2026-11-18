---
name: ai-adapter
description: Rules for any AI/LLM call in Alphaleo BD. Use when editing the `ai` module, PROMPT.md, prompt templates, payload builders, or any code that sends data to or parses output from Gemini or another model provider.
---

# AI calls

- Only the `ai` adapter talks to a provider. No other module imports a provider SDK.
- Every call names a prompt **ID and version** from `PROMPT.md`. Changing a prompt creates a new version; old versions stay.
- Log prompt ID, version, model, latency and token counts. Never log lead data or prompts containing lead data.
- Payloads are built from an allow-list. Never send email addresses, phone numbers or LinkedIn URLs.
- Output is schema-validated JSON. Invalid JSON is a failure, never text to use.
- AI never writes SQL, and its free text is never executed.
- Fixed email sections (greeting, call to action, signature, footer) are never AI-written or rep-editable. The server rejects tampered edits.
- Tests use fakes or recorded responses, never a live provider call.
