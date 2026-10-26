select a.bidder[1].increase from (select unnest(open_auctions.open_auction) as a from "sf10.parquet") where len(a.bidder) > 0
