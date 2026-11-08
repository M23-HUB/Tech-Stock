import os
import requests 
import json
import pandas as pd
import time
from datetime import datetime
import argparse
from pyfabricops import FabricClient

#------- CONSTANT VARIABLES -------#

APPID = os.getenv("ALPHA_VANTAGE_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

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

NEWS_STATE_FILE = "news_last_updated.json"

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
    
def fetch_and_save_stock(symbol, company_name, api_key, series_types=("TIME_SERIES_DAILY", "TIME_SERIES_MONTHLY")):
   
    """
    series_types:
        "TIME_SERIES_DAILY"   -> daily bars
        "TIME_SERIES_MONTHLY" -> monthly bars
    """
    
    functions = {
        "TIME_SERIES_DAILY":   ("Time Series (Daily)",  "Daily"),
        "TIME_SERIES_MONTHLY": ("Monthly Time Series",  "Monthly"),
    }

    print(f" -- Processing {company_name} ({symbol})")

    try:
        for func_key in series_types:
            if func_key not in functions:
                print(f" --- Unknown series type '{func_key}', skipping")
                continue

            series_key, name = functions[func_key]
            params = {
                "function": func_key,
                "apikey":   api_key,
                "symbol":   symbol,
            }

            response = requests.get("https://www.alphavantage.co/query?", params=params)
            response.raise_for_status()
            data = response.json()

            if "Error Message" in data:
                print(f" --- {name} API error for {symbol}: {data['Error Message']}")
            elif "Note" in data:
                # Alpha Vantage rate-limit notice comes back as "Note"
                print(f" --- {name} rate-limited for {symbol}: {data['Note']}")
            else:
                save_stock_data(f"{name}_stock_data.json", data, series_key, symbol)
                print(f" -- {name} data saved for {symbol}")

            time.sleep(12)

    except requests.exceptions.RequestException as e:
        print(f" --- Network error for {symbol}: {e}")
    except Exception as e:
        print(f" --- Unexpected error for {symbol}: {e}")

def save_stock_data(filename, new_data, series_key, symbol):
    try:
        with open(filename, "r") as data:
            loaded = json.load(data)
    except (FileNotFoundError, json.JSONDecodeError):
        loaded = {}
    
    loaded.setdefault(symbol, {}).update(new_data.get(series_key, {}))
    
    with open(filename, "w") as data:
        json.dump(loaded, data, indent=4)
    
    # Return the processed dataframe
    
    df = pd.DataFrame.from_dict(loaded[symbol], orient='index')
    df.columns = [col.split('. ')[1].title() for col in df.columns]
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().astype(float).reset_index().rename(columns={'index':'Date'})
    return df

def combine_all_stock_data(source_file='Monthly_stock_data.json',
                           output_file='stock_data_combined.csv'):
    all_frames = []

    try:
        with open(source_file, 'r') as f:
            series_data = json.load(f)

        if not isinstance(series_data, dict) or not series_data:
            print(f" -- {source_file} is empty or malformed")
            return None
        
        for symbol in STOCKS.keys():
            series = series_data.get(symbol)
            if not series:
                print(f" -- No data found for {symbol}, skipping")
                continue

            df = pd.DataFrame.from_dict(series, orient='index')
            df.columns = [col.split('. ')[1].title() for col in df.columns]
            df.index = pd.to_datetime(df.index)
            df = df.sort_index().astype(float)
            df = df.reset_index().rename(columns={'index': 'Date'})
            df['Name'] = symbol
            all_frames.append(df)

        if not all_frames:
            print(" -- No data to combine")
            return None

        combined_df = pd.concat(all_frames, ignore_index=True)

        # Year / month helpers
        combined_df['Year'] = combined_df['Date'].dt.year
        combined_df['Month'] = combined_df['Date'].dt.month
        combined_df['YearMonth'] = combined_df['Date'].dt.to_period('M')

        # YTD return: (Close / first Close of year) - 1, per Name/Year
        combined_df = combined_df.sort_values(['Name', 'Date'])
        first_close = combined_df.groupby(['Name', 'Year'])['Close'].transform('first')
        combined_df['YTD_Return'] = (combined_df['Close'] / first_close) - 1

        # Final column selection / ordering
        cols = ['Date', 'Year', 'Month', 'YearMonth', 'Name',
                'Close', 'Open', 'High', 'Low', 'Volume', 'YTD_Return']
        combined_df = combined_df[cols].sort_values('Date').reset_index(drop=True)

        combined_df.to_csv(output_file, index=False)
        print(f" -- Combined {len(combined_df)} rows from "
              f"{combined_df['Name'].nunique()} tickers -> {output_file}")

        return combined_df
    
    except Exception as e:
        print(f"Error combining data: {e}")
        return None

# ------- POWER BI -------#
      
def trigger_power_bi_refresh():
  
    try:
        
        client = FabricClient(
            tenant_id=os.getenv('POWER_BI_TENANT_ID'),
            client_id=os.getenv('POWER_BI_CLIENT_ID'),
            client_secret=os.getenv('POWER_BI_CLIENT_SECRET')
        )
        
        workspace_id = os.getenv('POWER_BI_WORKSPACE_ID')
        dataset_id = os.getenv('POWER_BI_DATASET_ID')
        
        # Trigger refresh
        response = client.refresh_dataset(workspace_id, dataset_id)
        print(f"Power BI refresh triggered: {response}")
        return True
    except Exception as e:
        print(f"Failed to trigger Power BI refresh: {e}")
        return False
      
# ------- MAIN -------#

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Fetch Alpha Vantage stock data + news.")
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
        series_types = ("TIME_SERIES_DAILY",)
        source_file  = "Daily_stock_data.json"
        output_file  = "stock_data_combined_daily.csv"
    else:
        series_types = ("TIME_SERIES_MONTHLY",)
        source_file  = "Monthly_stock_data.json"
        output_file  = "stock_data_combined_monthly.csv"    
    
    print(f" - Starting {args.mode} fetch for {len(STOCKS)} stocks...\n")

    for symbol, company_name in STOCKS.items():
        fetch_and_save_stock(symbol, company_name, APPID, series_types=series_types)
    print("\n - All data fetched successfully!")

    combined_df = combine_all_stock_data(source_file=source_file, output_file=output_file)
    if combined_df is not None:
        print(f"Combined {args.mode} data saved ({len(combined_df)} rows)")
    else:
        print("Combining failed - see error above. No CSV written.")
    
    trigger_power_bi_refresh()
