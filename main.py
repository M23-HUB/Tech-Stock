import os
import requests 
import json
import pandas as pd
import time
from datetime import datetime

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

#------ FUNCTIONS & API REQUEST ------# 

# Stocks Data

def save_stock_data(filename, new_data, file):    
    # Save stock data    
    try:
        with open(filename, "r") as data:
            loaded = json.load(data)
    except (FileNotFoundError, json.JSONDecodeError):
        loaded = {}
            
    loaded.update(new_data)
    with open(filename, "w") as data:
        json.dump(loaded, data, indent=4)
              
    df = pd.DataFrame.from_dict(loaded[file], orient='index')
    df.columns = [col.split('. ')[1].title() for col in df.columns]
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().astype(float).reset_index().rename(columns={'index':'Date'})
    return df
  
def fetch_and_save_stock(symbol, company_name, api_key):
    
    # Fetch and save both daily and monthly data for a stock 
    
    functions = {
    "TIME_SERIES_DAILY": ("Time Series (Daily)", "Daily"),
    "TIME_SERIES_MONTHLY": ("Monthly Time Series", "Monthly")
    }

    print(f" -- Processing {company_name} ({symbol})")
    
    daily_data = None
    monthly_data = None

    try:      
      for func_key, (series_key, name) in functions.items():
        
        params = {
            "function": func_key,
            "apikey": APPID,
            "symbol": symbol
        }
        
        response = requests.get("https://www.alphavantage.co/query?", params=params)
        response.raise_for_status()
        data = response.json()
        
        if "Error Message" in data:
            print(f" --- {name} API error for {symbol}: {data['Error Message']}")
        else:
            save_stock_data(f"{name}_stock_data.json", data, series_key)
            print(f" -- {name} data saved for {symbol}")
        time.sleep(12)    
            
    except requests.exceptions.RequestException as e:
        print(f" --- Network error for {symbol}: {e}")
    except Exception as e:
        print(f" --- Unexpected error for {symbol}: {e}")

def combine_all_stock_data(): 
  all_data = []
  
  try:
    with open('Monthly_stock_data.json', 'r') as f:
      monthly_data = json.load(f)['Monthly Time Series']  
      
    for name, df in STOCKS.items():
      df['Date'] = pd.to_datetime(df['Date'])
      df['Name'] = name

    # Combine all dataframes
    combined_df = pd.concat(STOCKS.values(), ignore_index=True)

    # Extract year and month information
    combined_df['Year'] = combined_df['Date'].dt.year
    combined_df['Month'] = combined_df['Date'].dt.month
    combined_df['YearMonth'] = combined_df['Date'].dt.to_period('M')  
    
    complete_data = complete_data[['Date','Year', 'Month', 'YearMonth', 'Name', 'Close', 'Open', 'High', 'Low', 'Volume', 'YTD_Return']].groupby(['Name', 'Year']).reset_index(drop=True)
    # Sort by Date and Name
    complete_data = complete_data.sort_values('Date').reset_index(drop=True)
    complete_data.to_csv('stock_data_combined.csv', index=False)
  
  except Exception as e:
    print(f"Error combining data: {e}")

def trigger_power_bi_refresh():
    
    try:
        from pyfabricops import FabricClient
        
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
    print(f" - Starting data fetch for {len(STOCKS)} stocks...\n")
    print(f" - Run time: {datetime.now()}")
    
    for symbol, company_name in STOCKS.items():
        fetch_and_save_stock(symbol, company_name, APPID)

    print("\n - All data fetched successfully!")
  
    try:
        combined_df = combine_all_stock_data()
        combined_df.to_csv('stock_data_combined.csv', index=False)
        print("Combined data saved to stock_data_combined.csv")
    except Exception as e:
        print(f"Error saving combined data: {e}")

    # Trigger Power BI refresh
    trigger_power_bi_refresh()