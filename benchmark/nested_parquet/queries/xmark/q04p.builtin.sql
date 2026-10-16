-- query 4 with two persons that bid in the same auctions (person20/person51 never do): checks the order
-- Q4: List the reserves of those open auctions where a certain person issued a bid before another person.
select reserve
from (select unnest(open_auctions.open_auction).reserve as reserve, list_filter(list_transform(unnest(open_auctions.open_auction).bidder, lambda x: x.personref._person), lambda x: x == 'person148112' or x == 'person189013') as bidders
from "sf10.parquet" bs)
where list_contains(bidders, 'person148112') and list_contains(bidders, 'person189013') and list_position(bidders, 'person148112') < list_position(bidders,'person189013')