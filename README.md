# reddit-sentiment-trader
Automated stock trader based on reddit user mentions and sentiment

Uses [Ape Wisdom API](https://apewisdom.io/) for reddit stock information and yfinance for stock data.
Trades are made through alpaca using alpaca REST api. Deployed on AWS to run every trading day.

### Dependencies:
* alpaca_trade_api 
* yfinance

### To run:

#### Install dependencies
`pip install alpaca_trade_api`
`pip install yfinance`

#### Run
`python3 handler.py <alpaca api key> <alpaca secret key>`
