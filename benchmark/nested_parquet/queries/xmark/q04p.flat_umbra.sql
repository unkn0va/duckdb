-- Umbra's query 4: every pair of a bid of person148112 before a bid of person189013 in the same auction
select pa."open_auctions.open_auction.bidder.personref._person", pa."open_auctions.open_auction.reserve"
from read_parquet_flat('sf10.parquet') pa, read_parquet_flat('sf10.parquet') pb
where pa."open_auctions.open_auction.bidder.personref._person" = 'person148112' and pb."open_auctions.open_auction.bidder.personref._person" = 'person189013'
  and pa."open_auctions.open_auction._id" = pb."open_auctions.open_auction._id"
  and pa."open_auctions.open_auction.bidder._sk" < pb."open_auctions.open_auction.bidder._sk"
