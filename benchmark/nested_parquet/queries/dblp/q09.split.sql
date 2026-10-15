SELECT d1.author, d0.year, count(d0.title)
FROM 'normalized/dblp0.parquet' d0, 'normalized/dblp1.parquet' d1
WHERE d0._sk = d1._psk0 and (d0.title like '%database%' or d0.title like '%text%' or d0.title like '%mining%') and d1.author not null
GROUP BY d1.author, d0.year