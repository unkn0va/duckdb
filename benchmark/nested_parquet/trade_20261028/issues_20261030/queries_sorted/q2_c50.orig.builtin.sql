SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM 'trade_B.parquet') WHERE e.leg_id < 'leg270';
