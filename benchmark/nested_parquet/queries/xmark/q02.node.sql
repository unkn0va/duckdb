select b.increase from read_parquet_node('sf10.parquet', node := 'open_auctions.open_auction') a
join (select _ak1, first(increase order by _sk) as increase from read_parquet_node('sf10.parquet', node := 'open_auctions.open_auction.bidder') group by _ak1) b on a._sk = b._ak1
