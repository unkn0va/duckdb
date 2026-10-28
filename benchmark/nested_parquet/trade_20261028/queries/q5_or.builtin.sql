SELECT sum(e.value) FROM (SELECT unnest(legs) AS e FROM 'trade_B.parquet') WHERE e.currency = 'AUD' OR e.option_type = 'put';
