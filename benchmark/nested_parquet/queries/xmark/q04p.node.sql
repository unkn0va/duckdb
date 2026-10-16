select a.reserve from read_parquet_node('sf10.parquet', node := 'open_auctions.open_auction') a
join (select _ak1 from read_parquet_node('sf10.parquet', node := 'open_auctions.open_auction.bidder') group by _ak1
      having min(_sk) filter (where "personref._person" = 'person148112') < min(_sk) filter (where "personref._person" = 'person189013')) b
  on a._sk = b._ak1
