# Anchors — studio seal heads pinned into hosted git history

Each row below anchors a sealed hub thread head into this repository's git
history: a weak external timestamp — the anchored head existed no later than
the anchor commit's push, as witnessed by the hosting provider's git history
(DR-phase5-topology rule 4.2). It is not cryptographic notarization — there is
no trusted timestamp authority, a host or a force-push can rewrite this
history, and anchoring never changes what is canonical: the hub records remain
the canonical artifacts (rules 4.3 and 2.1).

| anchored_at (ISO, UTC) | slug | head hash | records | hub thread id | note |
|---|---|---|---|---|---|
| 2026-07-13T03:02:16Z | founding-architecture | sha256:96ca38e6a2260ab9271ba50c996c2b13ae1aa421ec900101347dea5ff91c568c | 14 | thd_85fb8e66ae8c | retroactive backfill; sealed under single custodial author id_troy (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | ship-the-support-beta | sha256:00a0a3f7a700ce44432cc0e3d158783eda5504841099c8fcb24f76bf20a799f7 | 9 | thd_d8772aa588a9 | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | prompt-studio-2026-07-12-threads-phase-4-ships | sha256:203b7c2f93be210be81d979c3d93b1447079ccd1f5f6c8955ce081494f937233 | 15 | thd_a90077496e2e | retroactive backfill; per-record authors (3 distinct); custody regime legible per record (DR 5.3); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | promote-consensus-protocol-v1-1-0-to-production | sha256:1233b6d89cee1c4ab32f2958ab2f6c483edcbfad4c840bbec3c6eb1f8b0f0161 | 7 | thd_9c9cb876922b | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | promote-agent-operational-checklist-v1-0-0-to-production | sha256:7ec6ba9c444ed8877acf334014b9ef1c4d89921c9988b86ab98decface19239b | 7 | thd_5074435c1aba | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | promote-premium-enterprise-review-v1-0-to-production | sha256:ac8e8519a249649f5a7b05fe4422215602264aa9f87cf8e2896d91bc4c9d3f69 | 7 | thd_05761164f67c | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | promote-lite-fast-review-v1-0-to-production | sha256:78d9bbd3d39c56f0bced7869f948cd7a400cc2e57275e214b09da1c548712091 | 7 | thd_1a2fb69683e7 | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | promote-industry-playbook-technology-v1-0-to-production | sha256:6a79e18480f0c6fa2e013e7a101c14d3386bbd14efce8ad84b830afd798fa32b | 7 | thd_64281f82b251 | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | dr-phase5-topology | sha256:a406d40ae108df11160bbee04c9e927432761c90245da74bf7ae9e2c9060706a | 12 | thd_725f1cef76ac | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | dr-2026-07-12-fcp-metrics | sha256:ff7aef2f69da0091df84f6c5b9e78f2665eef083c978e49c80416cf094493bc3 | 8 | thd_032624ba7f19 | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:02:16Z | dr-2026-07-12-curation-check | sha256:a077f6d0dfe905276b4a81b8657d3e398c1b09b25acc059bddccc2fd4fb471af | 8 | thd_7d96f3851c00 | retroactive backfill; sealed under single custodial author id_f71531f1d383 (one distinct record author); anchored_at is the backfill time, not the seal time |
| 2026-07-13T03:14:00Z | challenge-agent-operational-checklist-purpose-fit-directive-v1-1 | sha256:da86708117c8deeb4216fa622abe32d1b345de7ee555da9f9a8886129ddb9437 | 14 | thd_bc679070f90a |  |
| 2026-07-13T03:18:17Z | promote-agent-operational-checklist-v1-1-0-to-production | sha256:a5e06febaf342c31ed20018b8cb39ef9ec4502b4bbddf27cd11d04b453d0b43f | 8 | thd_4773b17369c9 |  |
| 2026-07-13T05:22:06Z | prompt-studio-2026-07-13-phase-5-ships | sha256:738a304e511429219eafa6084e189ac9093e73648da022cdc610ed4fa706c6c7 | 10 | thd_80c47882fb67 |  |
| 2026-07-13T06:45:03Z | dr-2026-07-13-record-is-the-interface | sha256:f188271ee3d7072378cc5ba59d7efbe8dd2906bb79180f6ad4cbb36d926361ee | 8 | thd_bb82066ad694 |  |
| 2026-07-13T08:34:18Z | challenge-agent-operational-checklist-purpose-fit-directive-v1-1 | sha256:01add139d42b8dbfe275f946105bae3a9bbbf82068f6c31df60c345d95b06515 | 15 | thd_bc679070f90a | retroactive backfill; per-record authors (5 distinct); custody regime legible per record (DR 5.3); anchored_at is the backfill time, not the seal time |
| 2026-07-13T08:34:18Z | promote-agent-operational-checklist-v1-1-0-to-production | sha256:fb388e3109bfa72ca65650c17895a76fa03dd4ebd0b4eaeb51425ee37c39dd40 | 9 | thd_4773b17369c9 | retroactive backfill; per-record authors (2 distinct); custody regime legible per record (DR 5.3); anchored_at is the backfill time, not the seal time |
