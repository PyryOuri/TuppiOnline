# Observation encoder

`seat_relative_observation_encoder_v2` is a compact observation-only encoder.
It uses shared card embeddings, a DeepSets-style own-hand pool, a small GRU
over public showing/trick history, a current-trick pool, and a 32-value public
context vector. The legal-action scorer embeds only actions present in the
formal legal tuple, so an illegal action cannot receive positive probability.

History includes card, relative seat, event kind, declared showing contract,
within-trick position, and public trick winner. Context includes contract,
declarer/leader roles, public trick totals, match score, phase, current trick
length, dealer/forehand roles, and public void flags. Match and deal identifiers
are absent from the encoded representation.

Show actions encode declared contract and shown card. Trick actions encode the
played card. Greedy evaluation selects the greatest logit and resolves an
exact tie by the engine's existing legal-action order. No fallback repair is
performed.

The primary configuration is `seat_relative_actor_gru_deepsets_v2` and has
41,900 trainable parameters. The exported identity includes architecture,
encoder, preprocessing, action encoder, inference-rule versions, and the
checkpoint weight digest.
