# reddit-sentiment-trader
Automated stock trader based on reddit user mentions and sentiment

Uses [Ape Wisdom API](https://apewisdom.io/) for reddit stock information and yfinance for stock data.
Trades are made through alpaca using alpaca REST api. Deployed on AWS to run every trading day.

### Dependencies:
* alpaca_trade_api 
* yfinance


 
### To run:

##### Install dependencies
`pip install alpaca_trade_api`

`pip install yfinance`



### Run
`python3 handler.py <alpaca api key> <alpaca secret key>`



### Strategy


#### Sell:

a. Can't find stock information

b. Decline in mentions (<0% change in mentions in 24hr)

c. Trailing stop decline in stock (<-10%)

d. Overall Decline in position (<-10% change in position)

e. Profitability Threshold (>40%)


#### Buy:

Stocks are evaluated from the highest number of mentions to lowest.

a. Stock does not exceed percent of porfolio (50%)

b. Stock was not sold

c. Stock is not an ETF ($SPY, $QQQ, $UVXY)

d. Stock has minimum number of mentions (25 in 24hr)

e. Stock has positive sentiment (50% or greater)

f. Stock has not recently declined (<-10% change in 24hr)

g. Stock has recent growth in mentions (50% or greater)


If a stock meets the above criterion, the stock is evaluated based on its mentions and mention_growth. The function returns [0, 0.35] which is the proportional of purchasing power to buy the stock i.e. use 35% of purchasing power at maximum. The function used has a higher rate of growth of mentions vs mention_growth. mention_growth is also capped. The behavior of mention_growth is also adjusted on Mondays. The #1 most mentioned stock will always be bought as long as it has not fallen recently. 

If the dollar amount to buy is higher than the minimum amount, the stock is bought.

The program is ran every trading day 5 minutes after market opens. The account uses 2x margin. 

Note: the constants and function described here can be easily changed by modifying the constants and function.
