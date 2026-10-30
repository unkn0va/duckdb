SELECT count(e.leg_id), count(e.value) FROM (SELECT unnest(legs) AS e FROM 'trade_B.parquet');
