import alpaca_trade_api as alpaca
import requests, yfinance
import math, json, os, datetime, sys
from time import sleep

# TODO: max out equity percentage (partially implemented)
# TODO: multiday calling (req. amazon efs or database)
# TODO: add crypto support
# TODO: analytics

# Constants. These constants are NOT used in getStockVal()
MIN_MENTIONS = 25
MIN_PURCHASE_PERCENT = 0.05
MIN_PURCHASE_RAW = 2500
PLPC_PROFIT = 0.5
PLPC_SELL = -0.1
MENTION_GROWTH_SELL = 0
MIN_SENTIMENT = 0.5
MAX_POSITION_PERCENT = 0.5
TRAILING_SELL_PERCENT= 10
MIN_POSITION_VALUE = 500
MIN_CASH = 1000

# Blacklisted stocks
boomerStocks = ["SPY", "QQQ", "TQQQ", "UVXY", "SQQQ"]

# This function calculates the percent (from 0 to 1) of 
# available BP to allocate to the stock
def getStockVal(mentions, mention_growth, stock_change, flags):    
    # If monday change growth behavior
    if datetime.datetime.now().weekday() == 0:
        if mentions < 250:
            mention_growth = min(5, mention_growth * 0.5)
        else:
            mention_growth = min(10, mention_growth * 0.5)
    else:
        mention_growth = min(10, mention_growth)

    # Strategy: always consider the highest performing memestock
    if (flags and mention_growth <= 0.5 and stock_change >= -0.1):
        return 0.05;

    # Throw out bad fits
    if stock_change <= -0.1 or mention_growth <= 0.5:
        return 0

    # This function is a hack
    # Emphasize mentions more - but growth is important at high mentions
    return (round(min(40, ((mentions / 100) ** 0.5) 
    * math.log(mention_growth * 100 - 50, 2))))/100.0


# Sell all of a position
def sellPosition(alpaca_api, position, debugFlag):
    print("Sold "  + position.symbol + "; Profit:", (position.unrealized_plpc))
    
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


# Initiate a trailing stop order for the entire position
def trailingStopSell(alpaca_api, name, amount, debugFlag):
    print("Initiated trailing stop for " + name)
    
    if debugFlag:
        return 0
    
    # Does it need time to register that the order was put in place?
    sleep(1)

    alpaca_api.submit_order(
        symbol=name,
        qty=int(amount),
        side="sell",
        type="trailing_stop",
        time_in_force="gtc",
        trail_percent=str(TRAILING_SELL_PERCENT),
    )

    return 1


# Buy a position
def buyPosition(alpaca_api, amount, apeInfo, debugFlag):
    print("Buying " + apeInfo["ticker"] + ":", amount, "shares;", "$" + str(round(amount*apeInfo["price"], 3)))

    if debugFlag:
        return 0

    alpaca_api.submit_order(
        symbol=apeInfo["ticker"],
        qty=amount,
        side="buy",
        type="market",
        time_in_force="day",
    )
    
    trailingStopSell(alpaca_api, apeInfo["ticker"], amount, debugFlag)
    return 1


# Cancel an order
def cancelOrder(alpaca_api, orders, ticker):
    for order in orders:
        if order.symbol == ticker:
            print("Cancelling order...")
            alpaca_api.cancel_order(order.id)

# Return an ape object: name, price, mentions, mentions_growth, price_growth
# Percentages are fractional values i.e. 100%=1
# Returns 0 on error
def apeFactory(ape):
    try:
        # Name
        name = ape["ticker"]

        # Mentions
        mentions = float(ape["mentions"])

        # Mentions Growth
        # Account for new stock - set to 500%
        mentions_growth = 5
        if ape["mentions_24h_ago"] != None:
            mentions_growth = (mentions - 
            float(ape["mentions_24h_ago"]))/float(ape["mentions_24h_ago"])

        # Price Change and current price
        ape_ticker = yfinance.Ticker(name)
        prev_close = ape_ticker.history(period="2d").reset_index().loc[0, "Close"]

        # The current price has a 5m day
        df = yfinance.download(tickers=name, period='1d', interval='1m', progress=False).reset_index()
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
        print("ERROR: Stock not supported (apefactory)", ape["ticker"])
        return None


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
        print("ERROR: Stock not supported (roundstock)")
        return 0    


# Stock Blacklist
def boomer(stock):
    return stock in boomerStocks;


# Get the sentiment of the stock using apewisdom
# Return [0, 1] on success. Higher to 1 indicating stronger sentiment
# Return -1 on error. Relies on web scraping so this data can be unreliable
def getSentiment(ticker):
    try:
        html = requests.get("https://apewisdom.io/stocks/" + ticker).text
        # Pretty poor way of doing this but it works for now. TODO implement using bs4
        search_str = '<div style="float:left; padding-left: 10px; padding-top: 2px; font-weight:bold; font-size:18px;">';
        start = html.index(search_str)
        if start == -1:
            return -1
        end = html.index("%", start + len(search_str))
        result = float(html[start+len(search_str):end].strip())/100
        print(ticker + " sentiment:", result)
        return result
    except:
        print("ERROR: Could not access sentiment value")
        return -1


# Sell
def sellRoutine(alpaca_api, account, ape_list, debugFlag):
    positions = alpaca_api.list_positions()
    orders = alpaca_api.list_orders()


    # Try selling
    for position in positions:
        # Find the ticker in apes
        apeInfo = None
        for ape in ape_list:
            if position.symbol == ape["ticker"]:
                apeInfo = apeFactory(ape)
                break
        
        # DEBUG: print
        if apeInfo != None:
            print("Selling Analysis:", apeInfo["ticker"], apeInfo["mentions_growth"], apeInfo["price_growth"],
                position.unrealized_plpc, position.market_value)

        # Evaluate if should sell or not
        # If sell, then print the reason, blacklist the stock, cancel any previous sell orders, and sell it
        if apeInfo == None:
            print("Sell reason: No apeinfo")
            boomerStocks.append(position.symbol)
            cancelOrder(alpaca_api, orders, position.symbol)
            sellPosition(alpaca_api, position, debugFlag)
        elif apeInfo["mentions_growth"] <= MENTION_GROWTH_SELL:
            print("Sell reason: Decline in mentions")
            boomerStocks.append(apeInfo["ticker"])
            cancelOrder(alpaca_api, orders, position.symbol)
            sellPosition(alpaca_api, position, debugFlag)
        elif float(position.unrealized_plpc) > PLPC_PROFIT:
            print("Sell reason: Profit Threshold")
            boomerStocks.append(apeInfo["ticker"])
            cancelOrder(alpaca_api, orders, position.symbol)
            sellPosition(alpaca_api, position, debugFlag)
        elif float(position.unrealized_plpc) < PLPC_SELL:
            print("Sell reason: Unprofitability")
            boomerStocks.append(apeInfo["ticker"])
            cancelOrder(alpaca_api, orders, position.symbol)
            sellPosition(alpaca_api, position, debugFlag)
        elif float(position.market_value) < MIN_POSITION_VALUE:
            print("Sell reason: Minimum Positional Value")
            cancelOrder(alpaca_api, orders, position.symbol)
            sellPosition(alpaca_api, position, debugFlag)
            # This could cause unintended effects, 
            # but may be necessary to prevent day trading
            boomerStocks.append(apeInfo["ticker"])
        else:
            # Check stock relative to portfolio value
            position_percent = float(position.market_value) / (float(account.multiplier) * float(account.equity))
            print(apeInfo["ticker"] + " BP allocation: " + str(position_percent) + "%")
            if position_percent > MAX_POSITION_PERCENT:
                boomerStocks.append(apeInfo["ticker"])
            
        
            
# Buy
def buyRoutine(alpaca_api, ape_list, account, debugFlag):
    # Orderlist

    # Try buying
    for ape in ape_list:
        # Don't buy boring boomer stocks
        if boomer(ape["ticker"]):
            print("Skipping:", ape["ticker"])
            continue;

        apeInfo = apeFactory(ape)

        # Stock not supported
        if apeInfo == None:
            continue;

        # Stock if mentions falls below threshold
        if apeInfo["mentions"] < MIN_MENTIONS:
            print("Stopping at", apeInfo["ticker"])
            break

        # Use getStockVal to evaluate the function
        # stockVal is the percentage of pp to use
        stockVal = getStockVal(apeInfo["mentions"], apeInfo["mentions_growth"], 
        apeInfo["price_growth"], int(ape["rank"]) == 1)

        # DEBUG: print
        print("Buy analysis:", ape["ticker"], apeInfo["mentions"], apeInfo["mentions_growth"], 
        apeInfo["price_growth"], stockVal)

        # Think about buying $rawBuying amount of the assest
        if stockVal > 0:
            stocks_to_buy = roundStockPrice(alpaca_api, apeInfo["ticker"], apeInfo["price"], 
            stockVal * max(float(account.buying_power) - MIN_CASH, 0))
            rawAmount = stocks_to_buy * apeInfo["price"]
            print("Thinking about buying...", rawAmount)
            # Minimum buying amount
            if rawAmount > MIN_PURCHASE_PERCENT * (float(account.multiplier) * float(account.equity)) or rawAmount > MIN_PURCHASE_RAW:
                # Last check for sentiment
                # Sentiment is only checked here to minimize web scraping
                # Ignore errors because of unreliability
                sentiment = getSentiment(apeInfo["ticker"])
                if sentiment < MIN_SENTIMENT and sentiment != -1:
                    continue;
                else:
                    buyPosition(alpaca_api, stocks_to_buy, apeInfo, debugFlag)


# Main routine
def apeAlgorithm(ALPACA_API_KEY, ALPACA_SECRET_KEY, debugFlag):
    # Get the first page of ape wisdom using their API
    response = requests.get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1")
    response.raise_for_status()

    # Load the JSON into python dict
    ape_list = json.loads(response.content)["results"]

    # Connect to alpaca on paper markets
    alpaca_api = alpaca.REST(
        ALPACA_API_KEY, ALPACA_SECRET_KEY, 'https://paper-api.alpaca.markets')
    account = alpaca_api.get_account()

    # Sell
    sellRoutine(alpaca_api, account, ape_list, debugFlag)

    # DEBUG: print
    print("Available Assets:", str(float(account.buying_power) / (float(account.multiplier) * float(account.equity))*100)+"%")

    # Buy
    buyRoutine(alpaca_api, ape_list, account, debugFlag)

    # Successful completion?
    return 200


# Gets called by AWS
def main(event, context):
    return apeAlgorithm(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], False)

if __name__ == '__main__':
    print("Note: called from command line")
    if len(sys.argv) != 3:
        print("Usage: handler.py <alpaca api key> <alpaca secret key>")
    else:
        apeAlgorithm(sys.argv[1], sys.argv[2], False)

