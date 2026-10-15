-- Q2: Return the initial increases of all open auctions
select open_auctions_open_auction_bidder_increase
from 'normalized/sf10_11.parquet' a11, 'normalized/sf10_8.parquet' a8
where a11._psk1 = a8._sk and a11._sk = ( select min(b11._sk) 
                                        from 'normalized/sf10_11.parquet' b11, 'normalized/sf10_8.parquet' b8
                                        where b11._psk1 = b8._sk and a8.open_auctions_open_auction__id = b8.open_auctions_open_auction__id)