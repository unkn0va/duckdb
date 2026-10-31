| stage | config | operators (root → scan) | scan reads | scan filters | check |
|---|---|---|---|---|---|
| s1_box | base | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | legs |  | ok |
| s1_box | prenestoff | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | legs |  | ok |
| s1_box | prenest | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | legs |  | ok |
| s1_box | flat | UNGROUPED_AGGREGATE → PROJECTION → READ_PARQUET_NODE | legs: _sk |  | ok |
| s1_box | pureflat | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | ak0 |  | ok |
| s2_unnest | base | PROJECTION → UNGROUPED_AGGREGATE → PROJECTION → UNNEST → PARQUET_SCAN | legs |  | ok |
| s2_unnest | prenestoff | PROJECTION → UNGROUPED_AGGREGATE → PROJECTION → UNNEST → PARQUET_SCAN | legs |  | ok |
| s2_unnest | prenest | PROJECTION → UNGROUPED_AGGREGATE → PROJECTION → UNNEST → PARQUET_SCAN | legs |  | ok |
| s2_unnest | flat | UNGROUPED_AGGREGATE → PROJECTION → READ_PARQUET_NODE | legs: leg_id, value |  | ok |
| s2_unnest | pureflat | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | leg_id, value |  | ok |
| s2f_fields | base | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → UNNEST → PARQUET_SCAN | legs |  | ok |
| s2f_fields | prenestoff | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → UNNEST → PARQUET_SCAN | legs.leg_id, legs.value |  | ok |
| s2f_fields | prenest | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → UNNEST → PARQUET_SCAN | legs.leg_id, legs.value |  | ok |
| s2f_fields | flat | UNGROUPED_AGGREGATE → PROJECTION → READ_PARQUET_NODE | legs: leg_id, value |  | ok |
| s2f_fields | pureflat | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | leg_id, value |  | ok |
| s3_cond | base | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → PROJECTION → FILTER → UNNEST → PARQUET_SCAN | legs |  | ok |
| s3_cond | prenestoff | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → PROJECTION → FILTER → UNNEST → PARQUET_SCAN | legs.value, legs.leg_id |  | ok |
| s3_cond | prenest | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → PROJECTION → FILTER → UNNEST → PARQUET_SCAN | legs.value, legs.leg_id |  | ok |
| s3_cond | flat | UNGROUPED_AGGREGATE → PROJECTION → PROJECTION → READ_PARQUET_NODE | legs: leg_id, value | (leg_id < 'leg270') | ok |
| s3_cond | pureflat | UNGROUPED_AGGREGATE → PROJECTION → PARQUET_SCAN | value | (leg_id < 'leg270') | ok |
