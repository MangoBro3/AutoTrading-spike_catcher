import ccxt
bithumb = ccxt.bithumb()
markets = bithumb.load_markets()
print("First 10 keys:", list(markets.keys())[:10])
