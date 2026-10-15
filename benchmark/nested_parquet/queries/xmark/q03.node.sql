select a._id as id, b.first, b.last from read_parquet_node('sf10.parquet', node := 'open_auctions.open_auction') a
join (select _ak1, first(increase order by _sk) as first, last(increase order by _sk) as last from read_parquet_node('sf10.parquet', node := 'open_auctions.open_auction.bidder') group by _ak1) b on a._sk = b._ak1
where b.first * 2 <= b.last
