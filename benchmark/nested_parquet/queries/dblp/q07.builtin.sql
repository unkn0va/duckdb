SELECT author, year, count(title)
FROM (select title, unnest(author) as author, year from 'dblp.parquet')
GROUP BY author, year