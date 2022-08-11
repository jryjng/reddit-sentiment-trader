import alpaca_trade_api as alpaca
import requests, yfinance
import math, json, os, datetime

# TODO: max out equity percentage 
# TODO: multiday calling
# TODO: add crypto support
# TODO: potential stock buyback
# TODO: factor in sentiment

# Import global variables
ALPACA_API_KEY = os.environ["ALPACA_API_KEY"]
ALPACA_SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]
BASE_URL = 'https://paper-api.alpaca.markets'


# https://github.com/alpacahq/alpaca-trade-api-python/
# Return a float x<0.3 indicating the percent based on the
def getStockVal(mentions, mention_growth, stock_change):    
    # If monday change growth behavior
    if datetime.datetime.now().weekday() == 0:
        if mentions < 250:
            mention_growth = min(5, mention_growth/2)
        else:
            mention_growth = min(10, mention_growth/2)
    else:
        mention_growth = min(10, mention_growth)
    
    # Throw out bad fits
    if stock_change <= -0.1 or mention_growth < 0.5:
        return 0

    # This function is a hack
    # Emphasize mentions more - but growth is important at high mentions
    return (round(min(30, ((mentions / 125) ** 0.5) 
    * math.log(mention_growth * 100 - 50, 2))))/100.0


# Sell all of a position
def sellPosition(alpaca_api, position, debugFlag):
    print("========= Selling", position.symbol + ".", "Change%:", position.unrealized_plpc, "=========")
    
    if debugFlag:
        return 0
    
    alpaca_api.submit_order(
        symbol=position.symbol,
        qty=position.qty,
        side="sell",
        type="market",
        time_in_force="day",
    )
    return 1


# Buy a position
def buyPosition(alpaca_api, amount, apeInfo, debugFlag):
    print("========= Buying", amount, "shares of", apeInfo["ticker"],  "for a total of $", round(amount*apeInfo["price"], 3), "=========")
    if debugFlag:
        return 0

    alpaca_api.submit_order(
        symbol=apeInfo["ticker"],
        qty=amount,
        side="buy",
        type="market",
        time_in_force="day",
    )
    return 1


# Return an ape's most important attributes as a dict
def apeFactory(ape):
    try:
        # apewisdom uses BTC.X
        # yfinance uses BTC-USD
        # alpaca api uses BTC/USD
        name = ape["ticker"]

        # Retrieve relevant data
        mentions = float(ape["mentions"])

        # Account for new stock - set to 500%
        mentions_growth = 5
        if ape["mentions_24h_ago"] != None:
            mentions_growth = (mentions - 
            float(ape["mentions_24h_ago"]))/float(ape["mentions_24h_ago"])

        # Get price change
        # Note: history and download gets the last trading day
        ape_ticker = yfinance.Ticker(name)
        prev_close = ape_ticker.history(period="2d").reset_index().loc[0, "Close"]

        # The current price has a 5m day
        df = yfinance.download(tickers=name, period='1d', interval='1m').reset_index()
        price = df.tail(1).reset_index().loc[0, "Close"]
        price_growth = (price/prev_close) - 1
        return {
            "ticker" : name, 
            "price" : price,
            "mentions" : mentions, 
            "mentions_growth" : mentions_growth, 
            "price_growth" : price_growth
        }
    except:
        print("apeFactory: Stock not supported")
        return 0


# Adjust the stock amount based on fractionability
# Returns the amount of stock that should be bought
def roundStockPrice(alpaca_api, ticker, stockPrice, money):
    try:
        if alpaca_api.get_asset(ticker).fractionable:
            # Round down to 0.001
            raw = str(money / stockPrice)
            dot = raw.index(".")
            if dot != -1 and len(raw) > dot + 4:
                return float(raw[0:dot+4])
            return float(raw)
        else:
            # Round down
            return int(money / stockPrice)
    except:
        print("alpaca-roundStock: Stock not supported")
        return 0    


# Stock Blacklist
def boomer(stock):
    boomerStocks = ["SPY", "QQQ"]
    return stock in boomerStocks;


def main(event, context):
    # Get the first page of ape wisdom using their API
    response = requests.get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1")
    response.raise_for_status()

    # Load the JSON into python dict
    ape_list = json.loads(response.content)["results"]

    # Connect to alpaca
    alpaca_api = alpaca.REST(
        ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=BASE_URL)

    # Retrieve account info
    account = alpaca_api.get_account()
    positions = alpaca_api.list_positions()

    # Flag used to disable trading activity
    debugFlag = True

    # Try selling
    for position in positions:
        # Find the ticker in apes
        apeInfo = None
        for ape in ape_list:
            if position.symbol == ape["ticker"]:
                apeInfo = apeFactory(ape)
                break
        
        # DEBUG: print
        if apeInfo == None:
            print("Missing apeinfo!")
        else:
            print(apeInfo["ticker"], apeInfo["mentions_growth"], apeInfo["price_growth"],
                position.unrealized_plpc)

        # Evaluate if should sell or not
        if apeInfo == None:
            sellPosition(alpaca_api, position, debugFlag)
        elif apeInfo["mentions_growth"] <= 0:
            sellPosition(alpaca_api, position, debugFlag)
        elif apeInfo["price_growth"] < -10:
            sellPosition(alpaca_api, position, debugFlag)
        elif float(position.unrealized_plpc) < -0.1:
            # TODO: find plpc meaning
            sellPosition(alpaca_api, position, debugFlag)


    # DEBUG: print
    print("Available Assests %", float(account.buying_power) / float(account.equity))

    # Try buying
    for ape in ape_list:
        # Don't buy boring boomer stocks
        if boomer(ape["ticker"]):
            continue;

        apeInfo = apeFactory(ape)

        # Stock not supported
        if apeInfo == 0:
            continue;

        # Stock if mentions falls below threshold
        if apeInfo["mentions"] < 25:
            print("Stopping at", apeInfo["ticker"])
            break

        # Use getStockVal to evaluate the function
        # stockVal is the percentage of pp to use
        stockVal = getStockVal(apeInfo["mentions"], apeInfo["mentions_growth"], 
        apeInfo["price_growth"])

        # DEBUG: print
        print(ape["ticker"], apeInfo["mentions"], apeInfo["mentions_growth"], 
        apeInfo["price_growth"], stockVal)

        # Think about buying $rawBuying amount of the assest
        if stockVal > 0:
            stocks_to_buy = roundStockPrice(alpaca_api, apeInfo["ticker"], apeInfo["price"], 
            stockVal * float(account.buying_power))
            
            rawAmount = stocks_to_buy * apeInfo["price"]
            # Don't buy too little. Buy only if 5% of equity or exceeds 10k
            if rawAmount > 0.05 * float(account.equity) or rawAmount > 10000:
                buyPosition(alpaca_api, stocks_to_buy, apeInfo, debugFlag)

    # Successful completion?            
    return 200
