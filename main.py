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

#------ API REQUEST ------#

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
      
# Main execution

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Fetch Alpha Vantage stock data.")
    parser.add_argument(
        "mode",
        choices=["daily", "monthly"],
        help="daily = refresh daily bars; monthly = refresh monthly bars",
    )
    args = parser.parse_args()

    if args.mode == "daily":
        series_types = ("TIME_SERIES_DAILY",)
        source_file  = "Daily_stock_data.json"
        output_file  = "stock_data_combined_daily.csv"
    else:
        series_types = ("TIME_SERIES_MONTHLY",)
        source_file  = "Monthly_stock_data.json"
        output_file  = "stock_data_combined_monthly.csv"    
    
    print(f" - Starting data fetch for {len(STOCKS)} stocks...\n")

    for symbol, company_name in STOCKS.items():
        fetch_and_save_stock(symbol, company_name, APPID)

    print("\n - All data fetched successfully!")

    combined_df = combine_all_stock_data()
    if combined_df is not None:
        print(f"Combined data saved to stock_data_combined.csv ({len(combined_df)} rows)")
    else:
        print("Combining failed - see error above. No CSV written.")

    # Trigger Power BI refresh
    trigger_power_bi_refresh()
