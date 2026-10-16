-- Umbra's query 3: first and last bidder by the smallest/largest key of the auction (correlated by _id)
select first."open_auctions.open_auction._id", first."open_auctions.open_auction.bidder.increase", last."open_auctions.open_auction.bidder.increase"
from read_parquet_flat('sf10.parquet') first, read_parquet_flat('sf10.parquet') last
where first."open_auctions.open_auction.bidder._sk" = (select min("open_auctions.open_auction.bidder._sk") from read_parquet_flat('sf10.parquet') b where first."open_auctions.open_auction._id" = b."open_auctions.open_auction._id")
  and last."open_auctions.open_auction.bidder._sk" = (select max("open_auctions.open_auction.bidder._sk") from read_parquet_flat('sf10.parquet') b where last."open_auctions.open_auction._id" = b."open_auctions.open_auction._id")
  and first."open_auctions.open_auction.bidder.increase" * 2 <= last."open_auctions.open_auction.bidder.increase"
  and last."open_auctions.open_auction._id" = first."open_auctions.open_auction._id"
