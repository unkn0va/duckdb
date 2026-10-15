select id, first, last
from (select unnest(open_auctions.open_auction)._id as id, unnest(open_auctions.open_auction).bidder[1].increase as first, 
             unnest(open_auctions.open_auction).bidder[-1].increase as last 
      from "sf10.parquet")
where first * 2 <= last