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
