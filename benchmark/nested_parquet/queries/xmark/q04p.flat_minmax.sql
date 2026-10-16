-- the auctions whose first bid of person148112 comes before the first bid of person189013 (the builtin semantics)
select a."open_auctions.open_auction.reserve" as reserve
from read_parquet_flat('sf10.parquet') a
join (select "open_auctions.open_auction._sk" as auction from read_parquet_flat('sf10.parquet') group by 1
      having min("open_auctions.open_auction.bidder._sk") filter (where "open_auctions.open_auction.bidder.personref._person" = 'person148112')
           < min("open_auctions.open_auction.bidder._sk") filter (where "open_auctions.open_auction.bidder.personref._person" = 'person189013')) b
  on a."open_auctions.open_auction._sk" = b.auction
