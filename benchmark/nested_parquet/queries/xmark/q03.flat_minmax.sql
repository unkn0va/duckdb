-- the first and last bidder per auction, joined on their keys
select f."open_auctions.open_auction._id" as id, f."open_auctions.open_auction.bidder.increase" as first, l."open_auctions.open_auction.bidder.increase" as last
from (select min("open_auctions.open_auction.bidder._sk") as first_sk, max("open_auctions.open_auction.bidder._sk") as last_sk from read_parquet_flat('sf10.parquet') group by "open_auctions.open_auction._sk") m
join read_parquet_flat('sf10.parquet') f on f."open_auctions.open_auction.bidder._sk" = m.first_sk
join read_parquet_flat('sf10.parquet') l on l."open_auctions.open_auction.bidder._sk" = m.last_sk
where f."open_auctions.open_auction.bidder.increase" * 2 <= l."open_auctions.open_auction.bidder.increase"
