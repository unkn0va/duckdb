-- Umbra's query 4: every pair of a bid of person20 before a bid of person51 in the same auction
select p20."open_auctions.open_auction.bidder.personref._person", p20."open_auctions.open_auction.reserve"
from read_parquet_flat('sf10.parquet') p20, read_parquet_flat('sf10.parquet') p51
where p20."open_auctions.open_auction.bidder.personref._person" = 'person20' and p51."open_auctions.open_auction.bidder.personref._person" = 'person51'
  and p20."open_auctions.open_auction._id" = p51."open_auctions.open_auction._id"
  and p20."open_auctions.open_auction.bidder._sk" < p51."open_auctions.open_auction.bidder._sk"
