# Score Threshold On Retrieve

`RetrieveRequest.score_threshold` drops hits below a minimum similarity after dense (or
hybrid) search.

## Guidance

- Default `0.0` for eval and Skill unless corpus calibration exists.
- High thresholds cause empty result sets on first BGE-M3 cold start noise.

Agent CLI exposes `--score-threshold` mapped to this field.
