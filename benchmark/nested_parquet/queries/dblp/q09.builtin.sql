SELECT author, year, count(title)
FROM (select title, unnest(author) as author, year from 'dblp.parquet')
WHERE title like '%database%' or title like '%text%' or title like '%mining%'
GROUP BY author, year