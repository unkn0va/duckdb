SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM 'trade_Bsorted.parquet') WHERE e.leg_id < 'leg270';
