SELECT author as a, count(title) as b
FROM (select title, unnest(author) as author from 'dblp.parquet')
GROUP BY author