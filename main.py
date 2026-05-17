import argparse
import asyncio
import logging
from datetime import datetime
import json
import os

from module_chips import fetch_chips_data
from module_spot import fetch_spot_data
from module_macro import fetch_macro_data
from module_technical import fetch_technical_data
from module_formatter import format_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="Taiwan Stock & Futures Daily Data Fetcher")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y%m%d"), help="Target date in YYYYMMDD format")
    args = parser.parse_args()
    
    date_str = args.date
    
    # Format date for output
    try:
        formatted_date = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        logger.error("Invalid date format. Use YYYYMMDD.")
        return

    logger.info(f"Starting data fetch for date: {formatted_date}")
    
    # Use ThreadPoolExecutor for synchronous I/O bound modules
    loop = asyncio.get_running_loop()
    
    logger.info("Dispatching module requests concurrently...")
    
    # Run synchronously in threads since requests/pandas are blocking
    spot_task = loop.run_in_executor(None, fetch_spot_data, date_str)
    chips_task = loop.run_in_executor(None, fetch_chips_data, date_str)
    macro_task = loop.run_in_executor(None, fetch_macro_data, date_str)
    tech_task = loop.run_in_executor(None, fetch_technical_data, date_str)
    
    spot_data, chips_data, macro_data, tech_data = await asyncio.gather(
        spot_task, chips_task, macro_task, tech_task
    )
    
    logger.info("All data fetched, formatting output...")
    json_output = format_report(formatted_date, spot_data, chips_data, macro_data, tech_data)
    
    output_filename = f"output_{date_str}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(json_output)
        
    logger.info(f"Report generated successfully: {output_filename}")
    print(json_output)

if __name__ == "__main__":
    asyncio.run(main())
