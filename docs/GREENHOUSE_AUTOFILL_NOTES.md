# Greenhouse Autofill Notes (Transcarent case)

Date: 2026-03-30
Job URL: https://boards.greenhouse.io/transcarent/jobs/5814748004

## Answers used

### Core application fields
- First Name: `Carter`
- Last Name: `Lim`
- Email: `clim40@calpoly.edu`
- Phone: `3603253124`
- LinkedIn Profile: `https://www.linkedin.com/in/carterlim`
- Website: `https://carter-a-lim.github.io/personal-site/`
- Location during the Summer: `Bellingham, WA`
- Resume/CV: `resume-applier/data/resume_master.pdf`

### Work authorization / compliance
- Country: `United States`
- Are you currently authorized to work in the country outlined for this job?: `Yes`
- Will you now or in the future require sponsorship for employment visa status?: `No`

### Voluntary self-identification
- Gender: `Male`
- Are you Hispanic/Latino?: `No`
- Veteran Status: `No`
- Disability Status: `No`

## What worked

1. Standard text-input filling by stable IDs worked reliably:
   - `#first_name`, `#last_name`, `#email`, `#phone`
   - `#question_15514604004` (LinkedIn)
   - `#question_15514605004` (Website)
   - `#question_15514606004` (Location during summer)

2. File upload worked via:
   - `input[type="file"]` -> fixed resume PDF

3. For custom Greenhouse dropdowns/comboboxes, the most successful strategy was:
   - click field (force when needed)
   - type seed character (e.g., `n`, `y`, `u`)
   - `ArrowDown`
   - `Enter`
   - `Tab` (blur/commit)
   - submit-trigger validation check

4. Final deep pass reported:
   - `required_unresolved_count: 0`

## Caveats observed

- Several custom controls did not expose stable labels/IDs in a way that made direct value verification reliable.
- Per-field direct verification may show "failed" while overall required validation still passes.
- Use final required-field count as readiness signal.

## Artifacts

- `data/artifacts/7425f40b-8f10-479d-b3c7-615a23e3d7c8_online_methods_try.json`
- `data/artifacts/7425f40b-8f10-479d-b3c7-615a23e3d7c8_online_methods_try.png`
- Prior debug artifacts under `data/artifacts/` with same job id prefix.
