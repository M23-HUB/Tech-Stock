import os
import json
import pandas as pd
import time
from datetime import datetime, timedelta
from twelvedata import TDClient
import argparse
import serpapi
import pyfabricops as pf

#------- CONSTANT VARIABLES -------#

APPID = os.getenv("ALPHA_VANTAGE_KEY")
TWELVEDATA_API = os.getenv("TWELVEDATA_API")
RATE_LIMIT_SLEEP = 8
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
NEWS_STATE_FILE = "news_last_updated.json"

STOCKS = {
    "AAPL": "APPLE INC. (XMAS:AAPL)",
    "AMZN": "AMAZON.COM, INC. (XMAS:AMZN)",
    "BABA": "Alibaba Group Holding Limited (XMAS:BABA)",
    "CRM": "SALESFORCE, INC. (XMAS:CRM)",
    "FB": "Meta Platforms, Inc. (XMAS:FB)",
    "GOOG": "ALPHABET INC. (XMAS:GOOG)",
    "INTC": "INTEL CORPORATION (XMAS:INTC)",
    "MSFT": "MICROSOFT CORPORATION (XMAS:MSFT)",
    "NVDA": "NVIDIA CORPORATION (XMAS:NVDA)",
    "TSLA": "Tesla Inc"
}

# ------- NEWS -------#

def fetch_latest_news(company_name, api_key):
    """Fetch the last week of Google News headlines for a company."""
    try:
        client = serpapi.Client(api_key=api_key, timeout=20)
        results = client.search({
            "engine": "google_news",
            "q": f"{company_name} when:1w",
            "gl": "us",
            "hl": "en",
        })

        news_list = []
        for item in results.get("news_results", [])[:3]:
            source = item.get("source")
            news_list.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "source": source.get("name") if isinstance(source, dict) else source,
            })
        return news_list
    except Exception as e:
        print(f"Failed to fetch news for {company_name}: {e}")
        return []

def should_refresh_news(interval_days=7):
    """True if >= interval_days since the last successful news refresh."""
    if not os.path.exists(NEWS_STATE_FILE):
        return True
    try:
        with open(NEWS_STATE_FILE) as f:
            last = datetime.fromisoformat(json.load(f)["last_updated"])
        return datetime.now() - last >= timedelta(days=interval_days)
    except (json.JSONDecodeError, KeyError, ValueError):
        return True

def mark_news_refreshed():
    with open(NEWS_STATE_FILE, "w") as f:
        json.dump({"last_updated": datetime.now().isoformat()}, f, indent=2)

def refresh_all_news():
    """Refresh company_info.json for all tickers. Returns True on success."""
    if not SERPAPI_KEY:
        print(" --- SERPAPI_KEY is not set, skipping news refresh")
        return False

    if not should_refresh_news(interval_days=7):
        print(" - News refreshed <7 days ago, skipping.")
        return False

    print(f" - Refreshing news for {len(STOCKS)} stocks...\n")
    info_section = {}
    for symbol, company_name in STOCKS.items():
        news = fetch_latest_news(company_name, SERPAPI_KEY)
        info_section[symbol] = {
            "company": company_name,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "top_news": news or "No recent news found.",
        }
        time.sleep(1)

    with open("company_info.json", "w") as f:
        json.dump(info_section, f, indent=4)

    mark_news_refreshed()
    print(f" - News saved to company_info.json ({len(info_section)} tickers).")
    return True

#------ API REQUEST ------#  

def fetch_and_save_stock(
    symbol,
    company_name,
    api_key,
    series_types=("daily", "monthly"),
    start_date=None,
    end_date=None,
    output_dir=".",
):
    """
    Fetch and save daily / monthly bars from Twelve Data.

    series_types: iterable of Twelve Data intervals, e.g. ("1day", "1month", "1week")
    start_date / end_date: optional "YYYY-MM-DD" strings. If omitted, Twelve Data
                           returns the most recent N bars (default size=30 for
                           daily; use outputsize to change).
    """
    print(f" -- Processing {company_name} ({symbol})")

    td = TDClient(apikey=api_key)

    endpoints = {
        "1day":   (td.time_series, "Daily"),
        "1month": (td.time_series, "Monthly"),
    }

    for interval in series_types:
        if interval not in endpoints:
            print(f" --- Unknown series type '{interval}', skipping")
            continue

        endpoint_fn, name = endpoints[interval]

        try:
            kwargs = dict(
                symbol=symbol,
                interval=interval,
                outputsize=5000, 
            )
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date

            ts = endpoint_fn(**kwargs).as_pandas()

            if ts is None or ts.empty:
                print(f" --- {name} returned no data for {symbol}")
                time.sleep(RATE_LIMIT_SLEEP)
                continue

            ts = ts.sort_index()
            ts.index.name = "Date"

            save_stock_data(
                f"{output_dir}/{name}_stock_data.json",
                ts,
                symbol,
            )
            print(f" -- {name} data saved for {symbol} ({len(ts)} rows)")

        except Exception as e:
            # TDClient raises on API errors (bad symbol, rate limit, etc.)
            print(f" --- {name} error for {symbol}: {e}")

        time.sleep(RATE_LIMIT_SLEEP)

def save_stock_data(filename, df, symbol):
    """
    Merge new bars into an existing JSON file keyed by symbol.
    Stores rows as {date: {open, high, low, close, volume}}.
    """
    try:
        with open(filename, "r") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        loaded = {}

    new_rows = {}
    for date, row in df.iterrows():
        new_rows[str(date.date() if hasattr(date, "date") else date)] = {
            "open":   float(row["open"]),
            "high":   float(row["high"]),
            "low":    float(row["low"]),
            "close":  float(row["close"]),
            "volume": float(row["volume"]),
        }

    loaded.setdefault(symbol, {}).update(new_rows)

    with open(filename, "w") as f:
        json.dump(loaded, f, indent=4)

    return df

def combine_all_stock_data(
    stocks,
    source_file="Monthly_stock_data.json",
    output_file="stock_data_combined.csv",
):
    """
    Combine per-symbol bars into one CSV with year/month helpers and YTD return.
    `stocks` is the dict {symbol: company_name, ...} used as the ticker list.
    """
    all_frames = []

    try:
        with open(source_file, "r") as f:
            series_data = json.load(f)

        if not isinstance(series_data, dict) or not series_data:
            print(f" -- {source_file} is empty or malformed")
            return None

        for symbol in stocks.keys():
            series = series_data.get(symbol)
            if not series:
                print(f" -- No data found for {symbol}, skipping")
                continue

            df = pd.DataFrame.from_dict(series, orient="index")
            df.index = pd.to_datetime(df.index)
            df = df.sort_index().astype(float).rename(
                columns=str.title
            )  # open->Open, etc.
            df = df.reset_index().rename(columns={"index": "Date"})
            df["Name"] = symbol
            all_frames.append(df)

        if not all_frames:
            print(" -- No data to combine")
            return None

        combined_df = pd.concat(all_frames, ignore_index=True)

        combined_df["Year"] = combined_df["Date"].dt.year
        combined_df["Month"] = combined_df["Date"].dt.month
        combined_df["YearMonth"] = combined_df["Date"].dt.to_period("M")

        combined_df = combined_df.sort_values(["Name", "Date"])
        first_close = combined_df.groupby(["Name", "Year"])["Close"].transform("first")
        combined_df["YTD_Return"] = (combined_df["Close"] / first_close) - 1

        cols = [
            "Date", "Year", "Month", "YearMonth", "Name",
            "Close", "Open", "High", "Low", "Volume", "YTD_Return",
        ]
        combined_df = combined_df[cols].sort_values("Date").reset_index(drop=True)

        combined_df.to_csv(output_file, index=False)
        print(
            f" -- Combined {len(combined_df)} rows from "
            f"{combined_df['Name'].nunique()} tickers -> {output_file}"
        )
        return combined_df

    except Exception as e:
        print(f"Error combining data: {e}")
        return None

# ------- POWER BI -------#
      
def trigger_power_bi_refresh():
    
    pf.set_auth_provider("env")
    try:                        
        workspace_id = os.getenv('POWER_BI_WORKSPACE_ID')
        dataset_id = os.getenv('POWER_BI_DATASET_ID')
        
        # Trigger refresh
        response = pf.refresh_semantic_model(workspace_id, dataset_id)
        print(f"Power BI refresh triggered: {response}")
        return True
    except Exception as e:
        print(f"Failed to trigger Power BI refresh: {e}")
        return False
          
# ------- MAIN -------#

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Fetch Twelve Data stock data + news.")
    parser.add_argument(
        "mode",
        choices=["daily", "monthly","news"],
        help="daily = refresh daily bars; monthly = refresh monthly bars: news = refresh company news",
    )
    args = parser.parse_args()

    if args.mode == "news":
        ok = refresh_all_news()
        raise SystemExit(0 if ok else 1)
    
    if args.mode == "daily":
        series_types = ("1day",)
        source_file  = "Daily_stock_data.json"
        output_file  = "stock_data_combined_daily.csv"
    else:
        series_types = ("1month",)
        source_file  = "Monthly_stock_data.json"
        output_file  = "stock_data_combined_monthly.csv"    
    
    print(f" - Starting {args.mode} fetch for {len(STOCKS)} stocks...\n")

    for symbol, name in STOCKS.items():
        fetch_and_save_stock(
            symbol=symbol,
            company_name=name,
            api_key=TWELVEDATA_API,
            series_types=series_types,
            start_date=None,
            end_date=None,
        )

    print("\n - All data fetched successfully!")
    
    combined_df = combine_all_stock_data(
        stocks=STOCKS,
        source_file=source_file,
        output_file=output_file,
        )

    if combined_df is not None:
        print(f"Combined {args.mode} data saved ({len(combined_df)} rows)")
    else:
        print("Combining failed - see error above. No CSV written.")
    
    trigger_power_bi_refresh()