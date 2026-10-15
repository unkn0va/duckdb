-- Q4: List the reserves of those open auctions where a certain person issued a bid before another person.
select reserve
from (select unnest(open_auctions.open_auction).reserve as reserve, list_filter(list_transform(unnest(open_auctions.open_auction).bidder, lambda x: x.personref._person), lambda x: x == 'person20' or x == 'person51') as bidders
from "sf10.parquet" bs)
where list_contains(bidders, 'person20') and list_contains(bidders, 'person51') and list_position(bidders, 'person20') < list_position(bidders,'person51')