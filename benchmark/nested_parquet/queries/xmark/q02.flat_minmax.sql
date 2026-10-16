-- the first bidder per auction, joined on its key
select f."open_auctions.open_auction.bidder.increase"
from read_parquet_flat('sf10.parquet') f
join (select min("open_auctions.open_auction.bidder._sk") as first_sk from read_parquet_flat('sf10.parquet') group by "open_auctions.open_auction._sk") m on f."open_auctions.open_auction.bidder._sk" = m.first_sk
