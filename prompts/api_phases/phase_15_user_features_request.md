# Prompt 1 of 2 — API: accept user-defined feature specs in the /run request

> Archive at prompts/api_phases/phase_XX_user_features_request.md
> RUN FIRST. The UI prompt depends on this being committed.

---

Read CLAUDE.md, PROJECT_WISDOM.md, PROJECT_STATE.md, plan_tweak.md, backend_short_desc.md,
api_short_desc.md first. The engine now supports user-defined structured features
(`UserFeatureBuilder` + the `user_features` config key — see backend_short_desc.md and
backend/classifyos/preprocessing/user_features.py). This session exposes that on the API so the
dashboard can send user-defined feature specs. API layer only — do NOT modify engine or UI.

## Goal

Let the `/api/v1/run` request carry the `user_features` list (the structured specs the engine's
build_config already validates), so a user's dashboard-defined features flow into the run. This
is REQUEST-side. Check whether it needs any response-schema change (it likely does NOT — the
created columns already show up in the existing active_features/feature list in the response).
Confirm from the code; only bump schema_version if the RESPONSE shape actually changes.

## Before writing — inspect the current state

Read backend/api/models.py (the RunConfig request model and how it maps to the engine config)
and backend/api/routes/run.py. Determine exactly how request fields become the engine config
today (e.g. a to_engine_config() mapping). The change must follow that existing pattern.

## Change

1. **backend/api/models.py** — add `user_features` to the RunConfig REQUEST model as an optional
   list, default empty. Model each spec with a Pydantic sub-model (`UserFeatureSpec`) mirroring
   the engine's allowlist: `name` (str), `op` (str), `type` (str: numeric | single |
   datetime_diff), `col_a` (str), `col_b` (str | None), `unit` (str | None). Use Pydantic v2
   validation to reject unknown op/type values at the API boundary (reuse/mirror the engine's
   allowlists — do not invent new ones; if the engine exposes them as constants, import/reference
   them rather than duplicating). Empty/omitted → no user features (unchanged behaviour).
2. **Mapping** — ensure `user_features` is forwarded into the engine config wherever the request
   is translated (the to_engine_config path), so ModelRunner receives it. The engine's build_config
   is the authoritative validator; the API validation is a fast-fail convenience that must not
   diverge from it.
3. **Response** — verify the created user-feature columns already appear in the response's
   feature/active_features list (they should, since they're real columns post-engineering). If so,
   NO response-schema change and NO version bump. If for some reason they don't surface and you
   judge they should, STOP and report it rather than silently bumping the contract.
4. **docs/api_contract.md** — document the new request field (`user_features` + the spec shape).
   If no response change, note explicitly "request-side only; response schema unchanged".
5. **api_short_desc.md** — note the new request field.

## Tests (additive)

- A /run request with a valid `user_features` spec (e.g. a numeric divide, and a datetime_diff
  duration) succeeds and the created columns appear in the response feature list.
- An invalid spec (unknown op, or missing required col) → 422 with a clear validation error.
- A request with no `user_features` behaves identically to before (regression).
- Full API + engine suite green.

## Process

- Verify Pydantic v2 signatures against the installed version (hallucination check).
- Save this prompt to prompts/api_phases/phase_XX_user_features_request.md.
- Update PROJECT_STATE.md, api_short_desc.md, docs/api_contract.md. plan_tweak.md: note the
  additive request field (and whether the response/version was affected — ideally not).
- Commit as: "api: accept user-defined feature specs in /run request"

---

## Implementation notes (post-run, by Claude Code)

- **No response-schema change / no version bump.** Confirmed from the runner: user-feature
  columns are joined into the engineered feature matrix (`runner._engineer`, step 5b) and end up
  in `active_features_` (`X_train.columns`), so they already surface in `result.run.active_features`
  (and `result.feature_impact` when ranked). `schema_version` stays `"1.1"`.
- **`UserFeatureSpec`** mirrors the engine via imported constants (`USER_FEATURE_TYPES`,
  `USER_FEATURE_NUMERIC_OPS`, `USER_FEATURE_DATETIME_DIFF_OPS`, `USER_FEATURE_SINGLE_OPS`,
  `USER_FEATURE_DATETIME_UNITS`) — no allowlist duplicated. `extra="forbid"`; a Pydantic v2
  `model_validator(mode="after")` rejects an unknown type/op-for-type, a two-column type missing
  `col_b`, and a single type that carries `col_b`.
- **Mapping caveat:** `to_engine_config` dumps each spec with `model_dump(exclude_none=True)` —
  the engine treats a present `unit=None`/`col_b=None` as invalid, so the None optionals must be
  ABSENT, not present-as-null.
- **datetime_diff not E2E-tested here:** the sample CSVs have only one datetime column
  (`policy_lapse.policy_start_date`), so a two-column `datetime_diff` isn't expressible against the
  fixtures; the live test covers a numeric `divide` + a `single` date-part (`year`). The engine's
  own tests cover `datetime_diff`.
- Pydantic 2.13.4 verified in the venv.
