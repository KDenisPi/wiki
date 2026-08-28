#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One more attempt at a reply that ran away, with a frequency penalty.

The fine-tuned stage-2 model does not always stop. On some prompts it starts a
plausible query and then enumerates 'P44', 'P45', 'P46' until the token cap -
a repetition loop, not a missing end-of-text token: the training records end in
a closed fence, the tokenizer's eos is right, and nothing upstream contains a
list like that.

A frequency penalty breaks the loop, but it is the wrong thing to apply to
every request. Measured over all 144 comparison cases, 0.3 everywhere turned 28
cut-offs into 2 and scored exactly what greedy scored - 43 right of 138, seven
cases gained and seven lost - because it also pushes the model off the idioms
tuning taught it. Asked when Marie Curie was born it dropped a working person
filter for a regexp on 'scientist', which a physicist and chemist does not
match, and returned nothing.

Applied only where the reply was cut off, the same run scores 47 of 138 and
risks nothing: a cut-off reply was unusable anyway, and none of the seven
casualties had been cut off.

Both callers reach a model differently - compare_models.py posts to an endpoint
itself, sentence_to_sql.py goes through OllamaClient - so what is shared here is
the policy and the bookkeeping, not the request. Each passes a `call` that takes
a frequency penalty and returns a reply dict.
"""

import logging

logger = logging.getLogger("model_retry")

#Enough to break the loop in every case measured, low enough that the replies
#it rescues still parse. Not a tuned optimum - 0.3 is simply the first value
#tried that worked, over 3 cases by hand and then 144 in a batch.
DEFAULT_RETRY_PENALTY = 0.3

#Costs that belong to the case rather than to either attempt, so a retry shows
#up in the totals instead of hiding inside them.
SUMMED_FIELDS = ("seconds", "completion_tokens")

#Kept from the discarded attempt. Not its text: 1024 tokens of cycling ids say
#nothing a token count does not.
KEPT_FROM_FIRST = ("seconds", "completion_tokens", "finish_reason", "error")


def was_cut_off(reply: dict) -> bool:
    """Whether the model stopped because it hit the cap rather than finished."""
    return reply.get("finish_reason") == "length"


def with_cutoff_retry(call, base_penalty: float = 0.0,
                      retry_penalty: float = DEFAULT_RETRY_PENALTY,
                      label: str = "", log: logging.Logger = None) -> dict:
    """Call once; if the reply was cut off, call again with a penalty and keep
    the second.

    `call(frequency_penalty)` returns a reply dict carrying at least
    "finish_reason", and optionally the fields in SUMMED_FIELDS.

    Only a cut-off qualifies. A reply that stopped on its own is the model's
    real answer even when the SQL is wrong, and re-rolling it would be shopping
    for a better result rather than getting one. A retry_penalty no higher than
    what the first call already used would repeat the same request, so it is
    treated as switched off.
    """
    log = log or logger
    first = call(base_penalty)
    if not was_cut_off(first) or retry_penalty <= base_penalty:
        return first

    log.info("%swas cut off - retrying at frequency_penalty %.2f", label, retry_penalty)
    second = call(retry_penalty)
    second["first_try"] = {key: first.get(key) for key in KEPT_FROM_FIRST}
    second["retried_at_penalty"] = retry_penalty
    for field in SUMMED_FIELDS:
        if first.get(field) is not None and second.get(field) is not None:
            second[field] += first[field]
    if was_cut_off(second):
        log.warning("%sran away at frequency_penalty %.2f too", label, retry_penalty)
    return second
