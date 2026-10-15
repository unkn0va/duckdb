SELECT author, year, count(title)
FROM (select title, unnest(author) as author, year from 'dblp.parquet' WHERE title like '%database%' and title like '%text%' and title like '%mining%')
GROUP BY author, year