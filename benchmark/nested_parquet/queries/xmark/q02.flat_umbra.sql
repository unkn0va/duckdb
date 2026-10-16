-- Umbra's query 2: the first bidder is the one with the smallest key of the auction (correlated by _id)
select "open_auctions.open_auction.bidder.increase"
from read_parquet_flat('sf10.parquet') a
where "open_auctions.open_auction.bidder._sk" = (select min("open_auctions.open_auction.bidder._sk") from read_parquet_flat('sf10.parquet') b where a."open_auctions.open_auction._id" = b."open_auctions.open_auction._id")
