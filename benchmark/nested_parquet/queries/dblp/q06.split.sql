SELECT d1.author as a, count(d0.title) as b
FROM 'normalized/dblp0.parquet' d0, 'normalized/dblp1.parquet' d1
WHERE d0._sk = d1._psk0 and d1.author not null
GROUP BY d1.author;