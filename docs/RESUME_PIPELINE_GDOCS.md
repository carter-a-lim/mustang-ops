# Resume Pipeline (Canonical): Google Docs + Apps Script

## Status

**Canonical path (use this):** Google Docs template + Apps Script edits + PDF export.

**Do NOT use** the local Playwright HTML resume renderer for production-style resumes if visual consistency with the original template is required.

Template doc:
- https://docs.google.com/document/d/1qWnL3jthnT-gucpctoXNvl2GCc8qa5b_FWr8SdmhVvk/edit?tab=t.0

## Why

The Google Doc template preserves formatting/style that matches the original resume.
The local renderer is ATS-safe but does not match template styling closely enough.

## Required flow

1. Select job from `data/assisted_apply_queue.json` (filtered + ranked)
2. Generate tailored content (bullets/keywords/summary)
3. Create a copy of the template Google Doc
4. Update copied doc via Apps Script (section replacements)
5. Run keyword bolding via Apps Script (`boldKeywords` / `boldAnchors`)
6. Export final Google Doc to PDF
7. Attach/send PDF

## Local script assets

- `tools/gdocs-style/Code.gs`
- `tools/gdocs-style/appsscript.json`

## Implementation note for future chats

If a user asks for "test resume", "show me the PDF", or "resume generation":
- Default to the Google Docs pipeline above.
- Only use local HTML/Playwright renderer for quick internal tests or when explicitly requested.

## Apps Script configuration

Configured Script ID:
- `1ktwk_WByHoLEvLveYMETOKq41sbkGhOe_R3E60ZKm1DcwiH2BnYHTIjc`

Notes:
- Script ID is valid for identifying the Apps Script project.
- For backend HTTP execution, we still need the deployed **Web App URL** (or another execution bridge such as clasp/Apps Script API with auth) wired into Mustang Ops.

## Current gap

Need deployed Apps Script execution path wired into backend to automate doc copy/edit/export end-to-end.
