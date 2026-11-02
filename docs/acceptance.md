# Acceptance map (A01 to A20)

Each item from the development document, with the automated checks that exercise it.
Backend = `backend/tests`, UI = `frontend/tests` (Vitest), Browser = `frontend/e2e` (Playwright,
real Chrome and real backend).

Last full run: backend 235 passed, UI 95 passed, browser 12 passed (Chrome, real backend). Type check and production build clean.

| ID | Scenario | Checked by |
|---|---|---|
| A01 | Normal import: six fields, evidence, three rules pass, still `REVIEW_REQUIRED` | Backend `test_normal_import_returns_a_reviewable_document`, `test_samples_parse_to_the_hand_written_expectations` |
| A02 | Preset total error: PDF says 50,000.00, candidate 500000.00, total rule fails | Backend `test_amount_error_keeps_the_pdf_value_and_injects_the_candidate_fault`; Browser "preset total error" |
| A03 | Correct to 50000.00: initial value kept, before/after recorded, rules pass, not confirmed | Backend `test_correcting_the_total_fixes_the_rule_but_does_not_confirm`, `test_source_evidence_and_initial_values_survive_every_edit`; UI "keeps the draft…"; Browser "preset total error" |
| A04 | Six explicit checks then confirm; survives reload | Backend `test_six_explicit_checks_then_confirmation`, `test_full_correction_flow_from_the_preset_error`; Browser "preset total error" (reloads) |
| A05 | Editing a confirmed field revokes confirmation and checks, old events kept | Backend `test_editing_a_confirmed_document_revokes_the_confirmation`; UI "unlocks a confirmed record…"; Browser "preset total error" |
| A06 | Calling confirm/export around the buttons is refused with 409 | Backend `test_confirm_is_refused_when_rules_fail`, `test_confirm_is_refused_until_every_field_is_checked`, `test_checks_cannot_be_changed_on_a_confirmed_document`, `test_an_unconfirmed_document_cannot_be_exported`, `test_confirm_accepts_nothing_but_the_version` |
| A07 | Same file again: existing id returned, nothing overwritten | Backend `test_same_bytes_again_is_a_duplicate_pointing_at_the_original_record`, `test_reupload_never_overwrites_a_reviewed_record`, `test_simultaneous_identical_imports_create_one_record_and_keep_the_original`; UI list "points at the existing record…"; Browser "importing the same file again…" |
| A08 | Same name, different bytes: new record | Backend `test_same_filename_with_different_bytes_creates_a_new_record` |
| A09 | Two windows: first save wins, stale one refused, no lost update | Backend `test_two_windows_editing_the_same_version_cannot_both_win`, `test_stale_versions_are_rejected_by_every_write`, `test_a_locked_database_is_a_write_conflict_and_changes_nothing`; UI "never overwrites silently after a version conflict…"; Browser "two windows…" |
| A10 | Amount boundaries: 0.10 + 0.20 = 0.30; reject 1.001, -1, 1e3, NaN, 12,34 | Backend `test_money_is_exact`, `test_normalize_amount_rejects_invalid`, `test_cents_are_added_exactly`, `test_amount_boundaries_are_enforced_at_the_api`; UI `fieldInput.test.ts` |
| A11 | Null is not zero; missing source can never be checked or confirmed; no invented box | Backend `test_null_is_not_zero`, `test_missing_value_stays_null_without_an_invented_box`, `test_missing_evidence_blocks_verification_and_confirmation`; UI "never pretends to locate…"; Browser "a value with no source…" |
| A12 | All three amounts ×10: rule passes but nothing is auto-checked or confirmed | Backend `test_scaling_all_three_amounts_by_ten_still_passes_the_amount_rule`, `test_scaled_amounts_pass_the_rules_but_still_need_a_human` |
| A13 | Zoom and device pixel ratio: box stays on the same text | UI `evidenceGeometry.test.ts`, `viewer.test.tsx`; Browser `geometry.spec.ts` (fit/100%/150%, 1440 px and 390 px, DPR 2, ink measured in the canvas, plus a drift control) |
| A14 | Bad files: too large, encrypted, multi-page, scanned, rotated, cropped, corrupt, timeout; nothing left behind | Backend `test_pdf_parser.py` (unsupported files), `test_imports.py` (size boundary, each unsupported PDF, `test_a_hung_parser_is_killed_after_the_timeout`, cleanup assertions) |
| A15 | Persistence failure rolls back fields, version, status and history together | Backend `test_a_failure_while_writing_history_rolls_everything_back` (edit, check, confirm), `test_a_failed_revocation_restores_the_confirmed_state`, `test_commit_failure_removes_the_new_original_and_leaves_no_rows`, `test_a_failure_recording_the_event_means_no_download` |
| A16 | Export content: exact strings, one version, source, confirmation, rules, history | Backend `test_export_is_a_complete_exact_snapshot_of_the_confirmed_version`, `test_exporting_records_a_generation_event_but_not_a_new_version`; Browser "preset total error" (downloads and parses the file) |
| A17 | Export racing an edit: complete older snapshot or a version conflict, never a mix | Backend `test_a_change_after_the_snapshot_cannot_leak_into_the_export`, `test_an_edit_before_the_snapshot_is_a_version_conflict_not_a_mixed_file` |
| A18 | Original deleted or altered blocks reading, confirming and exporting | Backend `test_missing_or_altered_original_blocks_file_reads`, `test_confirm_checks_the_original_file`, `test_a_missing_or_altered_original_blocks_export`; UI "explains an original that cannot be loaded…" |
| A19 | Unsaved draft: confirm and export unavailable; not stored | UI "keeps edits as an unsaved draft…", "is unavailable while there are unsaved edits…", "asks the browser to confirm closing…", "asks before in-app navigation…"; Browser "leaving with a draft asks first…" |
| A20 | Repeated save/check/confirm adds no version and no history | Backend `test_repeating_an_operation_changes_neither_version_nor_history` |

## Manual checks

* Layout reviewed at 1440 px and 390 px (screenshots in `docs/screenshots`).
* Keyboard: the six "checked against PDF" boxes can be reached and toggled with Tab and Space
  (Browser "a missing extraction…").
* Not done here: the 90 to 120 second screen recording (script in `docs/demo-script.md`).
  A person has to record it.
